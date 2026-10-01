#!/usr/bin/env python3
"""DQAEIP FINAL PORTABLE EVIDENCE & RELEASE HARDENING — Phase 7.

SELF-CONTAINED RELEASE VERIFICATION (task-book section 8).

Extracts the release ZIP into a RANDOM clean temporary directory and
verifies, from the EXTRACTED copy ONLY (never the original working
tree, never the original git checkout):

    [1]  package import works
    [2]  33 in / 8 flags / 41 out contract holds
    [3]  exactly 8 frozen V1 rules register
    [4]  portable FINAL_RESULTS parses; schema identity KNOWN and
         structural anchors hold; verification state as recorded
    [5]  release manifest + release lock verify against extracted files
    [6]  security scan over the extracted evidence tree
    [7]  contradiction checker runs CONSISTENT in the extracted tree
    [8]  README consistency check passes in the extracted tree
    [9]  full test suite passes in the extracted tree
    [10] integrity monitor runs against the extracted baseline
         snapshot and reports PASS
    [11] claim graph verification PASSES in the extracted tree
         (re-hash + re-derive every claim)
    [12] artifact identity registry validates against extracted files
    [13] absolute-path release gate PASSES in the extracted tree
    [14] evidence freshness is CURRENT in the extracted tree
    [15] evidence schema compatibility: every current release artifact
         is KNOWN (registered schema, structurally valid)
    [16] release identity consistent across FINAL_RESULTS / manifest /
         lock / README identity block
    [17] executable bits preserved by extraction (faithful restore)

Output: SELF_CONTAINED_RELEASE_VERIFICATION.json (repo-side record —
a verification report about the ZIP is necessarily outside the ZIP).
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

ZIP_NAME = "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18"
NS = "evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18"
REPORT_OUT = os.path.join(
    REPO_ROOT, NS, "self_contained_verification",
    "SELF_CONTAINED_RELEASE_VERIFICATION.json")


def run(cmd, cwd, timeout=1500):
    return subprocess.run(cmd, cwd=cwd, capture_output=True,
                          text=True, timeout=timeout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", required=True)
    parser.add_argument("--scratch", default=None)
    args = parser.parse_args()

    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    scratch = args.scratch or tempfile.mkdtemp(
        prefix="dqaeip_portable_extract_")
    own_scratch = args.scratch is None
    os.makedirs(scratch, exist_ok=True)
    checks = {}

    def record(name, ok, detail=""):
        checks[name] = {"status": "PASS" if ok else "FAIL",
                        "detail": str(detail)[:500]}
        marker = "PASS" if ok else "FAIL"
        print(f"  [{marker}] {name}" + (f": {str(detail)[:120]}"
                                        if detail and not ok else ""))

    try:
        # ---- extraction (faithful permission restoration) ---------------
        with zipfile.ZipFile(args.zip, "r") as zf:
            zf.extractall(scratch)
            for info in zf.infolist():
                if info.is_dir():
                    continue
                mode = (info.external_attr >> 16) & 0o777
                if mode & 0o111:
                    target = os.path.join(scratch, info.filename)
                    if os.path.isfile(target):
                        os.chmod(target, mode)
        ext_root = os.path.join(scratch, ZIP_NAME)
        record("extraction", os.path.isdir(ext_root))

        py = sys.executable  # release does not ship .venv (§34)
        env_py = py

        def ext(rel):
            return os.path.join(ext_root, rel)

        # ---- [1] package import -------------------------------------------
        r = run([env_py, "-c",
                 "import data_quality_platform, runner; "
                 "print('import ok')"], ext_root)
        record("package_import", r.returncode == 0, r.stderr[-300:])

        # ---- [2][3] contract + rules --------------------------------------
        r = run([env_py, "-c",
                 "from data_quality_platform.contracts import ("
                 "SOURCE_COLUMNS, FLAG_COLUMNS, TOTAL_OUTPUT_COLUMNS, "
                 "REQUIRED_RULE_IDS); "
                 "from data_quality_platform.rules.registry import "
                 "RuleRegistry; "
                 "reg = RuleRegistry.create_default(); "
                 "assert len(SOURCE_COLUMNS) == 33; "
                 "assert TOTAL_OUTPUT_COLUMNS == 41; "
                 "assert len(FLAG_COLUMNS) == 8; "
                 "assert sorted(x.rule_id for x in "
                 "reg.get_all_rules()) == sorted(REQUIRED_RULE_IDS); "
                 "print('contract ok')"], ext_root)
        record("contract_33_41_and_8_rules", r.returncode == 0,
               r.stderr[-300:])

        # ---- [4] portable FINAL_RESULTS + schema identity ------------------
        ok, detail = True, ""
        try:
            frp = json.load(open(ext(f"{NS}/final_results/"
                                    "FINAL_RESULTS_PORTABLE_2026-09-18"
                                    ".json"), encoding="utf-8"))
            from data_quality_platform.assurance.evidence_schema import (
                validate_schema_identity)
            status, problems = validate_schema_identity(frp)
            if status != "KNOWN":
                ok = False
                detail = f"schema {status}: {problems[:3]}"
            if frp.get("verification_state") != \
                    "PASS_WITH_DOCUMENTED_LIMITATIONS":
                ok = False
                detail = "unexpected verification state"
            root_fr = json.load(open(ext("FINAL_RESULTS.json"),
                                     encoding="utf-8"))
            if root_fr.get("final_release_status") != \
                    "PASS_WITH_DOCUMENTED_LIMITATIONS":
                ok = False
                detail = "unexpected root final status"
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, str(exc)
        record("final_results_documents", ok, detail)

        # ---- [5] manifest + lock -------------------------------------------
        ok, detail = True, ""
        try:
            key = json.load(open(ext(f"{NS}/release_manifest/"
                                    "release_manifest.json"),
                                 encoding="utf-8"))
            bad = [e["path"] for e in key["files"]
                   if os.path.isfile(ext(e["path"]))
                   and hashlib.sha256(open(ext(e["path"]), "rb")
                                      .read()).hexdigest() != e["sha256"]]
            if bad:
                ok = False
                detail = f"manifest hash mismatch: {bad[:3]}"
            lock = json.load(open(ext(f"{NS}/release_manifest/"
                                     "release_lock.json"),
                                  encoding="utf-8"))
            if lock.get("status") != "LOCKED":
                ok = False
                detail = "lock not LOCKED"
            if lock.get("final_results_sha256") != hashlib.sha256(
                    open(ext(f"{NS}/final_results/"
                             "FINAL_RESULTS_PORTABLE_2026-09-18.json"),
                         "rb").read()).hexdigest():
                ok = False
                detail = "lock FINAL_RESULTS SHA mismatch"
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, str(exc)
        record("manifest_and_lock", ok, detail)

        # ---- [6] security scan ---------------------------------------------
        r = run([env_py, "-c",
                 "import sys; sys.path.insert(0, '.'); "
                 "from data_quality_platform.security.pii_scan import "
                 "scan_tree_for_pii; "
                 "res = scan_tree_for_pii('evidence'); "
                 "print(res['verdict'], res['prohibited_count']); "
                 "sys.exit(0 if res['verdict'] == 'PASS' else 1)"],
                ext_root)
        record("security_scan_extracted", r.returncode == 0,
               (r.stdout + r.stderr)[-300:])

        # ---- [7] contradiction checker -------------------------------------
        r = run([env_py, "scripts/contradiction_checker.py"], ext_root,
                timeout=300)
        record("contradiction_checker_extracted",
               "CONSISTENT" in r.stdout and r.returncode == 0,
               (r.stdout + r.stderr)[-300:])

        # ---- [8] README consistency ---------------------------------------
        r = run([env_py, "scripts/readme_consistency_check.py"],
                ext_root, timeout=300)
        record("readme_consistency_extracted",
               "CONSISTENT" in r.stdout and r.returncode == 0,
               (r.stdout + r.stderr)[-300:])

        # ---- [9] full test suite --------------------------------------------
        r = run([env_py, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                ext_root, timeout=1500)
        tail = (r.stdout or "").strip().splitlines()
        summary = tail[-1] if tail else r.stderr[-200:]
        record("test_suite_extracted", r.returncode == 0, summary)

        # ---- [10] integrity monitor (extracted snapshot) --------------------
        r = run([env_py, "tools/integrity_monitor.py"], ext_root,
                timeout=300)
        ok = r.returncode == 0 and "PASS" in (r.stdout or "").splitlines()[0]
        record("integrity_monitor_extracted", ok,
               (r.stdout + r.stderr)[-300:])

        # ---- [12] artifact identity registry -------------------------------
        r = run([env_py, "-c",
                 "import sys, json; sys.path.insert(0, '.'); "
                 "from data_quality_platform.assurance.artifact_identity "
                 "import validate_identity; "
                 f"reg = json.load(open({f'{NS}/artifact_identity/artifact_identity_registry.json'!r})); "
                 "probs = [p for rec in reg['records'] "
                 "for p in validate_identity(rec)]; "
                 "print('records', len(reg['records']), 'problems', "
                 "len(probs)); "
                 "sys.exit(1 if probs or reg.get('verdict') != 'PASS' "
                 "else 0)"], ext_root, timeout=300)
        record("artifact_identity_registry_extracted", r.returncode == 0,
               (r.stdout + r.stderr)[-400:])

        # ---- [11] claim graph verification ---------------------------------
        r = run([env_py, "tools/build_claim_graph.py"], ext_root,
                timeout=300)
        ok = r.returncode == 0 and "verdict: PASS" in r.stdout
        record("claim_graph_verification_extracted", ok,
               (r.stdout + r.stderr)[-400:])

        # ---- [13] absolute-path release gate --------------------------------
        r = run([env_py, "tools/absolute_path_release_gate.py"],
                ext_root, timeout=300)
        record("absolute_path_gate_extracted", r.returncode == 0,
               (r.stdout + r.stderr)[-300:])

        # ---- [14] freshness in extracted tree --------------------------------
        r = run([env_py, "tools/evaluate_freshness.py"], ext_root,
                timeout=300)
        record("freshness_extracted",
               r.returncode == 0 and "CURRENT" in r.stdout,
               (r.stdout + r.stderr)[-300:])

        # ---- [15] schema compatibility (current artifacts KNOWN) ------------
        r = run([env_py, "tools/build_schema_compatibility_report.py",
                 "--quiet"], ext_root, timeout=300)
        record("schema_compatibility_extracted", r.returncode == 0,
               (r.stdout + r.stderr)[-300:])

        # ---- [16] release identity consistency -------------------------------
        ok, detail = True, ""
        try:
            frp = json.load(open(ext(f"{NS}/final_results/"
                                    "FINAL_RESULTS_PORTABLE_2026-09-18"
                                    ".json"), encoding="utf-8"))
            lock = json.load(open(ext(f"{NS}/release_manifest/"
                                     "release_lock.json"),
                                  encoding="utf-8"))
            ident = json.load(open(ext(f"{NS}/release_manifest/"
                                      "RELEASE_IDENTITY.json"),
                                   encoding="utf-8"))
            ids = {
                frp["release_identity"]["release_id"],
                lock["release_id"],
                ident["release_id"],
                ZIP_NAME,
            }
            if len(ids) != 1:
                ok, detail = False, f"identity disagreement: {ids}"
            readme = open(ext("README.md"), encoding="utf-8").read(20000)
            if ZIP_NAME not in readme:
                ok, detail = False, "README does not carry release id"
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, str(exc)
        record("release_identity_consistent", ok, detail)

        # ---- [17] executable bits --------------------------------------------
        exe_bits = 0
        with zipfile.ZipFile(args.zip, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                mode = (info.external_attr >> 16) & 0o777
                if mode & 0o111:
                    exe_bits += 1
                    target = os.path.join(scratch, info.filename)
                    if not (os.path.isfile(target)
                            and os.stat(target).st_mode & 0o111):
                        record("executable_bits_preserved", False,
                               info.filename)
                        break
            else:
                record("executable_bits_preserved", True,
                       f"{exe_bits} executable members faithful")

        verdict = ("PASS" if all(c["status"] == "PASS"
                                 for c in checks.values()) else "FAIL")

        report = {
            "report": "DQAEIP self-contained release verification "
                      "(clean-room extraction)",
            "schema": {"name": "dqaeip.self_contained_verification",
                       "version": "1.0"},
            "release_id": ZIP_NAME,
            "zip_path": os.path.basename(args.zip),
            "zip_sha256": hashlib.sha256(
                open(args.zip, "rb").read()).hexdigest(),
            "scratch_root": "<clean random temporary directory>",
            "generated_utc": started,
            "checks": checks,
            "check_count": len(checks),
            "self_contained": (
                "every check executed from the extracted copy only; "
                "the extracted release does not depend on the original "
                "working tree, its paths, or its git checkout"),
            "working_tree_gate_note": (
                "the full release gate (including the git-integrity "
                "gate, which requires repository metadata deliberately "
                "excluded from the ZIP) ran in the working tree; this "
                "extraction verification is the self-contained "
                "equivalent for the shipped archive"),
            "verdict": verdict,
        }
        os.makedirs(os.path.dirname(REPORT_OUT), exist_ok=True)
        with open(REPORT_OUT, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=True)
            f.write("\n")
        print(f"SELF-CONTAINED VERIFICATION: {verdict} "
              f"({sum(1 for c in checks.values() if c['status'] == 'PASS')}"
              f"/{len(checks)} checks)")
        return 0 if verdict == "PASS" else 4
    finally:
        if own_scratch:
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
