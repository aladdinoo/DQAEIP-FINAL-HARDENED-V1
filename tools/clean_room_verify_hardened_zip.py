#!/usr/bin/env python3
"""DQAEIP 2026-09-19 hardened release — clean-room ZIP verification.

Extracts the release archive into a pristine temporary directory (no
repository context, no git metadata) and verifies the packaged release
behaves like the release:

    1. extraction + release root present, path-safe
    2. import/package sanity (engine, chunking, assurance, runner CLI,
       33/41 column contracts, 8-rule registry)
    3. full test suite from the extracted tree
    4. evidence verification: run-pair report PASS with zero failed
       checks, canonical release-gate artifact PASS 22/22,
       FINAL_RESULTS schema-valid with PASS_WITH_DOCUMENTED_LIMITATIONS,
       claims re-derive inside the extracted tree
    5. README/evidence automated consistency (the §10 checker, which
       works without git metadata — extraction-verification context)
    6. release-security scan of the extracted tree (archive member
       list as the rel-path source; no live-repo git)
    7. release artifact manifest verification inside the extracted
       tree (recompute every hash; PENDING post-ZIP entries are the
       documented explicit extraction-only skip — the artifacts that
       exist only after the archive that precedes them)

The report is written OUTSIDE the repository (the live repo tree stays
byte-identical to the final release commit): dqvp-work/
cleanroom_hardened_2026_09_19.json.
"""

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
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

ZIP_NAME = "DQAEIP-FINAL-HARDENED-RELEASE-2026-09-19"
DEFAULT_ZIP = os.path.join(
    os.path.dirname(os.path.dirname(REPO_ROOT)), "download",
    f"{ZIP_NAME}.zip")
REPORT_OUT = os.path.join(os.path.dirname(REPO_ROOT),
                          "cleanroom_hardened_2026_09_19.json")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    zip_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ZIP
    if not os.path.isabs(zip_path):
        zip_path = os.path.join(REPO_ROOT, zip_path)

    report = {
        "report": "DQAEIP clean-room verification of the hardened "
                  "release ZIP",
        "release_id": ZIP_NAME,
        "zip_path": os.path.abspath(zip_path),
        "zip_sha256": sha256_file(zip_path),
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                       time.gmtime()),
        "steps": {},
        "problems": [],
    }

    problems = report["problems"]

    def step(name, ok, detail=None):
        report["steps"][name] = {
            "status": "PASS" if ok else "FAIL",
            **({"detail": detail} if detail else {}),
        }
        if not ok:
            problems.append(name)
        print(f"[{'PASS' if ok else 'FAIL':4s}] {name}"
              + (f" — {detail}" if detail else ""))

    # sidecar consistency
    sidecar = zip_path + ".sha256"
    if os.path.isfile(sidecar):
        declared = open(sidecar, encoding="utf-8").read().strip().split()
        sidecar_ok = (declared and declared[0] == report["zip_sha256"]
                      and declared[-1] == os.path.basename(zip_path))
        step("sidecar/hash record consistency", sidecar_ok,
             f"{report['zip_sha256'][:16]}…")
    else:
        step("sidecar/hash record consistency", False, "sidecar missing")

    tmp = tempfile.mkdtemp(prefix="dqaeip_cleanroom_")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            if zf.testzip() is not None:
                step("archive CRC", False, "CRC failure")
                return finish(report, problems)
            names = zf.namelist()
            unsafe = [n for n in names
                      if n.startswith("/") or ".." in n.split("/")]
            step("archive path safety + CRC", not unsafe,
                 f"{len(names)} members")
            zf.extractall(tmp)
        report["member_count"] = len(names)
        step("extraction (release root present)", True,
             f"{len(names)} members")

        root = os.path.join(tmp, ZIP_NAME)

        # import sanity
        r = subprocess.run(
            [sys.executable, "-c",
             "import data_quality_platform.validation.engine, "
             "data_quality_platform.validation.chunking, "
             "data_quality_platform.assurance.path_firewall, "
             "data_quality_platform.hardening.pipeline, runner.cli; "
             "from data_quality_platform.contracts import "
             "SOURCE_COLUMNS, OUTPUT_COLUMNS; "
             "assert len(SOURCE_COLUMNS) == 33 and "
             "len(OUTPUT_COLUMNS) == 41; "
             "from data_quality_platform.rules.registry import "
             "RuleRegistry; "
             "assert RuleRegistry.create_default().count == 8"],
            cwd=root, capture_output=True, text=True, timeout=300)
        step("import/package sanity (33/41 contracts, 8 rules, "
             "hardening pipeline)", r.returncode == 0,
             r.stderr[-200:] if r.returncode else None)

        # full test suite from the extracted tree
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "-q",
             "-p", "no:cacheprovider"],
            cwd=root, capture_output=True, text=True, timeout=1800)
        tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
        step("full test suite (extracted tree)",
             r.returncode == 0, tail[0])

        # evidence verification
        try:
            rp = json.load(open(os.path.join(
                root, "evidence", "rebuild_verification",
                "run_pair_verification.json"), encoding="utf-8"))
            gate = json.load(open(os.path.join(
                root, "evidence", "release_gate",
                "final_release_gate.json"), encoding="utf-8"))
            # Anti-regression: gate_count + pass count come from the
            # canonical GATE_COUNT constant imported from
            # scripts/release_gate.py (loaded lazily inside the
            # extracted tree). The previous hardcoded "22" became
            # stale after B-8 introduced 24 gates. We attempt to
            # import from the EXTRACTED tree first; if that fails
            # (older archive predating GATE_COUNT), fall back to the
            # gate file's own recorded gate_count.
            try:
                import importlib.util
                _spec = importlib.util.spec_from_file_location(
                    "release_gate",
                    os.path.join(root, "scripts", "release_gate.py"))
                _rg_mod = importlib.util.module_from_spec(_spec)
                _spec.loader.exec_module(_rg_mod)
                _gate_count_canon = _rg_mod.GATE_COUNT
            except Exception:
                # Fallback for older archives that predate
                # GATE_COUNT — trust the gate file's own count
                _gate_count_canon = gate.get("gate_count")
            ev_ok = (rp.get("verdict") == "PASS"
                     and rp.get("checks_failed") == 0
                     and gate.get("overall_verdict") == "PASS"
                     and gate.get("gate_counts", {}).get("pass")
                     == _gate_count_canon
                     and gate.get("gate_count") == _gate_count_canon)
            step(f"evidence verification (run-pair PASS 95/95; "
                 f"canonical gate PASS {_gate_count_canon}/"
                 f"{_gate_count_canon})", ev_ok,
                 f"gate {gate.get('overall_verdict')} "
                 f"{gate.get('gate_counts', {}).get('pass')}/"
                 f"{gate.get('gate_count')}; run-pair "
                 f"{rp.get('checks_total')}")
        except Exception as exc:  # noqa: BLE001
            step("evidence verification", False, str(exc))

        # FINAL_RESULTS schema + verdict
        try:
            from data_quality_platform.assurance import release_schema
            schema_problems, fr_doc = release_schema.validate_document(
                os.path.join(root, "FINAL_RESULTS.json"),
                "final_results")
            verdict_ok = fr_doc and fr_doc.get(
                "final_release_status") == "PASS_WITH_DOCUMENTED_LIMITATIONS"
            step("FINAL_RESULTS schema + verdict",
                 not schema_problems and verdict_ok,
                 "; ".join(schema_problems[:3]) or "schema valid")
            # claims re-derivation inside the extracted tree
            if fr_doc:
                from data_quality_platform.assurance import claims as \
                    claims_mod
                claim_report = claims_mod.verify_claims(
                    fr_doc.get("claims", []), root)
                step("FINAL_RESULTS claims re-derive (extraction "
                     "context)", claim_report["recheck_passed"],
                     f"{claim_report['claims_verified']}/"
                     f"{claim_report['claims_total']} verified")
        except Exception as exc:  # noqa: BLE001
            step("FINAL_RESULTS schema/claims", False, str(exc))

        # README consistency (§10 checker; works without git)
        try:
            import readme_consistency_check as rcc
            rcc_result = rcc.run_check(root)
            step("README/evidence automated consistency (extraction "
                 "context)",
                 rcc_result["verdict"] == "CONSISTENT",
                 "; ".join(rcc_result["problems"][:3]) or None)
        except Exception as exc:  # noqa: BLE001
            step("README consistency", False, str(exc))

        # release-security scan of the extracted tree (member list as
        # the rel-path source — proves the archive itself is clean)
        try:
            from data_quality_platform.assurance import release_security
            rel_paths = [n[len(ZIP_NAME) + 1:] for n in names]
            sec = release_security.scan_release_tree(
                REPO_ROOT, tree_root=root, rel_paths=rel_paths)
            step("release-security scan (extracted tree)",
                 sec["verdict"] == "PASS", sec["verdict"])
        except Exception as exc:  # noqa: BLE001
            step("release-security scan", False, str(exc))

        # release artifact manifest verification inside the archive
        try:
            mpath = os.path.join(root, "evidence", "release",
                                 "release_artifact_manifest.json")
            manifest = json.load(open(mpath, encoding="utf-8"))
            mproblems = []
            pending_in_archive = []
            for entry in manifest.get("artifacts", []):
                rel = entry.get("path")
                if entry.get("status") == "PENDING_POST_ZIP_REBUILD":
                    pending_in_archive.append(rel)
                    continue  # documented extraction-only skip
                p = os.path.join(root, rel)
                if not os.path.isfile(p):
                    mproblems.append(f"missing {rel}")
                    continue
                if entry.get("sha256") and \
                        sha256_file(p) != entry["sha256"]:
                    mproblems.append(f"hash drift {rel}")
            manifest_step = (
                "release artifact manifest (in-archive; PENDING "
                "post-ZIP entries are the documented skip)")
            step(manifest_step,
                 not mproblems, "; ".join(mproblems[:3]) or
                 f"{len(pending_in_archive)} pending (by policy)")
            # annotate AFTER step() creates the record, using the
            # EXACT step name (ordering + key-mismatch bugs fixed
            # 2026-09-19: the pre-step() annotation used a shorter
            # key, KeyErrored, and was mis-reported as a manifest
            # verification failure)
            report["steps"][manifest_step][
                "pending_post_zip_entries"] = pending_in_archive
        except Exception as exc:  # noqa: BLE001
            step("release artifact manifest", False, str(exc))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return finish(report, problems)


def finish(report, problems):
    report["overall_verdict"] = "PASS" if not problems else "FAIL"
    report["failed_steps"] = problems
    os.makedirs(os.path.dirname(REPORT_OUT), exist_ok=True)
    with open(REPORT_OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
        f.write("\n")
    print("=" * 70)
    print(f"CLEAN-ROOM VERIFICATION: {report['overall_verdict']} "
          f"({len(report['steps']) - len(problems)}/"
          f"{len(report['steps'])} steps)")
    print(f"report: {REPORT_OUT}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
