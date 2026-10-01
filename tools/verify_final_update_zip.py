#!/usr/bin/env python3
"""DQAEIP FINAL UPDATE 2026-09-17 — clean extraction verification (§36).

Extracts the release ZIP into a completely clean scratch directory and
verifies, from the EXTRACTED copy only (never the original working
tree):

    [1]  package import works
    [2]  33/41 schema contract holds
    [3]  exactly 8 frozen V1 rules register
    [4]  FINAL_RESULTS (root) + FINAL_RESULTS_UPDATE parse and the
         update document passes the section-9 schema gate
    [5]  release manifest + release lock verify against extracted files
    [6]  security scan over the extracted evidence tree
    [7]  contradiction checker runs CONSISTENT in the extracted tree
    [8]  README consistency check passes
    [9]  full test suite passes in the extracted tree
    [10] integrity monitor runs (against the extracted baseline
         snapshot) and reports PASS

The extracted release is self-contained: no claim depends on the
original working tree. The full 21-gate (which includes the
git-integrity gate requiring repository metadata that §34 deliberately
excludes from the ZIP) was executed in the working tree and is
referenced as working-tree evidence, not re-derived here.
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

ZIP_NAME = "DQAEIP-FINAL-UPDATE-2026-09-17"
REPORT_OUT = os.path.join(
    REPO_ROOT, "evidence", "FINAL_UPDATE_2026-09-17",
    "final_verification", "clean_extraction_report.json")


def run(cmd, cwd, timeout=900):
    return subprocess.run(cmd, cwd=cwd, capture_output=True,
                          text=True, timeout=timeout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", required=True)
    parser.add_argument("--scratch", default=None)
    args = parser.parse_args()

    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    scratch = args.scratch or tempfile.mkdtemp(
        prefix="dqaeip_final_update_extract_")
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
        # ---- extraction (with faithful permission restoration) ---------
        # Python's zipfile.extractall does NOT restore the executable
        # bit from the archive's external attributes; the integrity
        # monitor's permission check (§13-F) correctly flags the loss.
        # Extraction fidelity is restored explicitly from ZipInfo.
        with zipfile.ZipFile(args.zip, "r") as zf:
            zf.extractall(scratch)
            for info in zf.infolist():
                if info.is_dir():
                    continue
                mode = (info.external_attr >> 16) & 0o777
                if mode & 0o111:  # executable in the source tree
                    target = os.path.join(scratch, info.filename)
                    if os.path.isfile(target):
                        os.chmod(target, mode)
        ext_root = os.path.join(scratch, ZIP_NAME)
        record("extraction", os.path.isdir(ext_root))

        py = os.path.join(ext_root, ".venv", "bin", "python")
        if not os.path.isfile(py):
            # the release does not ship .venv (§34): use the working
            # tree's interpreter against the EXTRACTED sources only
            py = sys.executable
        env_py = py

        def ext(rel):
            return os.path.join(ext_root, rel)

        # ---- [1] package import -----------------------------------------
        r = run([env_py, "-c",
                 "import data_quality_platform, runner; "
                 "print('import ok')"], ext_root)
        record("package_import", r.returncode == 0, r.stderr[-300:])

        # ---- [2] 33/41 contract + [3] 8 rules ----------------------------
        r = run([env_py, "-c",
                 "from data_quality_platform.contracts import ("
                 "SOURCE_COLUMNS, FLAG_COLUMNS, TOTAL_OUTPUT_COLUMNS, "
                 "REQUIRED_RULE_IDS); "
                 "from data_quality_platform.rules.registry import "
                 "RuleRegistry; "
                 "reg = RuleRegistry.create_default(); "
                 "assert len(SOURCE_COLUMNS) == 33, 'input cols'; "
                 "assert TOTAL_OUTPUT_COLUMNS == 41, 'output cols'; "
                 "assert len(FLAG_COLUMNS) == 8, 'flags'; "
                 "assert sorted(x.rule_id for x in "
                 "reg.get_all_rules()) == sorted(REQUIRED_RULE_IDS), "
                 "'rules'; print('contract ok')"], ext_root)
        record("contract_33_41_and_8_rules", r.returncode == 0,
               r.stderr[-300:])

        # ---- [4] FINAL_RESULTS documents ----------------------------------
        ok = True
        detail = ""
        try:
            root_fr = json.load(open(ext("FINAL_RESULTS.json"),
                                     encoding="utf-8"))
            if root_fr.get("final_release_status") != \
                    "PASS_WITH_DOCUMENTED_LIMITATIONS":
                ok = False
                detail = "unexpected root final status"
            upd = json.load(open(ext(
                "evidence/FINAL_UPDATE_2026-09-17/final_results/"
                "FINAL_RESULTS_UPDATE-2026-09-17.json"), encoding="utf-8"))
            sys.path.insert(0, ext_root)
            from data_quality_platform.assurance.integrity import (
                schema_gate_final_results_update)
            problems = schema_gate_final_results_update(upd)
            if problems:
                ok = False
                detail = f"schema gate: {problems[:3]}"
            if upd.get("verification_state") != \
                    "PASS_WITH_DOCUMENTED_LIMITATIONS":
                ok = False
                detail = "unexpected update verification state"
        except Exception as exc:  # noqa: BLE001
            ok = False
            detail = str(exc)
        record("final_results_documents", ok, detail)

        # ---- [5] manifest + lock verify ------------------------------------
        ok = True
        detail = ""
        try:
            key = json.load(open(ext(
                "evidence/FINAL_UPDATE_2026-09-17/release_manifest/"
                "release_manifest.json"), encoding="utf-8"))
            bad = [e["path"] for e in key["files"]
                   if os.path.isfile(ext(e["path"]))
                   and hashlib.sha256(open(ext(e["path"]), "rb")
                                      .read()).hexdigest() != e["sha256"]]
            if bad:
                ok = False
                detail = f"manifest hash mismatch: {bad[:3]}"
            lock = json.load(open(ext(
                "evidence/FINAL_UPDATE_2026-09-17/release_manifest/"
                "release_lock.json"), encoding="utf-8"))
            if lock.get("status") != "LOCKED":
                ok = False
                detail = "lock not LOCKED"
            if lock.get("final_results_sha256") != hashlib.sha256(
                    open(ext("evidence/FINAL_UPDATE_2026-09-17/"
                             "final_results/"
                             "FINAL_RESULTS_UPDATE-2026-09-17.json"),
                         "rb").read()).hexdigest():
                ok = False
                detail = "lock FINAL_RESULTS SHA mismatch"
        except Exception as exc:  # noqa: BLE001
            ok = False
            detail = str(exc)
        record("manifest_and_lock", ok, detail)

        # ---- [6] security scan (extracted evidence tree) --------------------
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

        # ---- [7] contradiction checker ----------------------------------------
        r = run([env_py, "scripts/contradiction_checker.py"], ext_root,
                timeout=300)
        ok = "CONSISTENT" in r.stdout and r.returncode == 0
        record("contradiction_checker_extracted", ok,
               (r.stdout + r.stderr)[-300:])

        # ---- [8] README consistency --------------------------------------------
        r = run([env_py, "scripts/readme_consistency_check.py"],
                ext_root, timeout=300)
        ok = "CONSISTENT" in r.stdout and r.returncode == 0
        record("readme_consistency_extracted", ok,
               (r.stdout + r.stderr)[-300:])

        # ---- [9] full test suite ------------------------------------------------
        r = run([env_py, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                ext_root, timeout=900)
        tail = (r.stdout or "").strip().splitlines()
        summary = tail[-1] if tail else r.stderr[-200:]
        ok = r.returncode == 0
        record("test_suite_extracted", ok, summary)

        # ---- [10] integrity monitor in extracted tree ------------------------------
        r = run([env_py, "tools/integrity_monitor.py"], ext_root,
                timeout=300)
        ok = r.returncode == 0 and "PASS" in r.stdout.splitlines()[0]
        record("integrity_monitor_extracted", ok,
               (r.stdout + r.stderr)[-300:])

        verdict = ("PASS" if all(c["status"] == "PASS"
                                 for c in checks.values()) else "FAIL")

        report = {
            "report": "DQAEIP FINAL UPDATE clean extraction verification",
            "release_id": ZIP_NAME,
            "zip_path": os.path.abspath(args.zip),
            "zip_sha256": hashlib.sha256(
                open(args.zip, "rb").read()).hexdigest(),
            "scratch_root": "<clean temporary directory>" if own_scratch
            else scratch,
            "generated_utc": started,
            "checks": checks,
            "check_count": len(checks),
            "self_contained": ("every check executed from the extracted "
                              "copy only; the extracted release does "
                              "not depend on the original working tree"),
            "working_tree_gate_note": (
                "the full 21/21 release gate (including the "
                "git-integrity gate, which requires repository metadata "
                "deliberately excluded from the ZIP by §34) ran in the "
                "working tree; this extraction verification is the "
                "self-contained equivalent for the shipped archive"),
            "verdict": verdict,
        }
        os.makedirs(os.path.dirname(REPORT_OUT), exist_ok=True)
        with open(REPORT_OUT, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=True)
            f.write("\n")
        print(f"CLEAN EXTRACTION: {verdict} "
              f"({sum(1 for c in checks.values() if c['status']=='PASS')}"
              f"/{len(checks)} checks)")
        return 0 if verdict == "PASS" else 4
    finally:
        if own_scratch:
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
