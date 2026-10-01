#!/usr/bin/env python3
"""DQAEIP FINAL PORTABLE EVIDENCE UPDATE V2 (2026-09-18) — Phases 14-15.

Runs the EXISTING checks (never weakened) and records them under the
UPDATE-V2 namespace:

    Phase 15 — full test suite (python -m pytest -q --tb=short from
    the repository root, the platform's canonical invocation), with
    the collected/passed/skipped/failed/errors counts compared
    against the previous known baseline (1025 collected / 1016
    passed / 9 skipped / 0 failed / 0 errors).

    Phase 14 — security/PII scan via the existing fail-closed
    release-artifact security scanner
    (data_quality_platform.assurance.release_security — the same
    module behind scripts/release_artifact_security_scan.py). The
    scanner itself is invoked UNMODIFIED; only the report location is
    UPDATE-V2-namespaced so the canonical evidence/release report of
    the previous round stays untouched.
"""

import json
import os
import re
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance import release_security  # noqa: E402

UPDATE_ID = "DQAEIP-FINAL-UPDATE-V2-2026-09-18"
NS = "evidence/FINAL_PORTABLE_UPDATE_V2_2026-09-18"
TEST_OUT = os.path.join(REPO_ROOT, NS, "tests",
                        "full_suite_UPDATE-V2.json")
SEC_OUT = os.path.join(REPO_ROOT, NS, "security",
                       "security_scan_UPDATE-V2.json")

PREV_BASELINE = {
    "collected": 1025, "passed": 1016, "skipped": 9,
    "failed": 0, "errors": 0,
    "source": "evidence/FINAL_PORTABLE_RELEASE_2026-09-18/final_results/"
              "FINAL_RESULTS_PORTABLE_2026-09-18.json (test_identity), "
              "consistent with the preserved 22-gate re-run "
              "(542 unit + 24 integration + 22 contract + assurance/"
              "golden/property/runtime/safety/security suites)",
}


def run_full_suite():
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    t0 = time.time()
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=1200)
    out = r.stdout + r.stderr
    duration = round(time.time() - t0, 2)

    m = re.search(r"(\d+) passed", out)
    passed = int(m.group(1)) if m else None
    m = re.search(r"(\d+) skipped", out)
    skipped = int(m.group(1)) if m else 0
    m = re.search(r"(\d+) failed", out)
    failed = int(m.group(1)) if m else 0
    m = re.search(r"(\d+) error", out)
    errors = int(m.group(1)) if m else 0
    m = re.search(r"(\d+) deselected", out)
    deselected = int(m.group(1)) if m else 0

    # collected: count test nodes from the progress lines is not
    # reliable; use the terminal summary total when present
    collected = None
    m = re.search(r"(\d+) passed", out)
    if m:
        collected = passed + skipped + failed + errors
    exit_code = r.returncode

    counts = {
        "passed": passed, "skipped": skipped, "failed": failed,
        "errors": errors, "deselected": deselected,
        "collected": collected, "exit_code": exit_code,
        "duration_seconds": duration,
    }
    return counts, out, started


def main():
    # ---- Phase 15: full test suite -----------------------------------
    counts, raw_tail, started = run_full_suite()
    print(f"full suite: {counts}")

    baseline_ok = (
        counts["failed"] == 0 and counts["errors"] == 0
        and counts["skipped"] == PREV_BASELINE["skipped"]
        and counts["passed"] is not None
        and counts["passed"] >= PREV_BASELINE["passed"])

    test_record = {
        "report": "DQAEIP FINAL PORTABLE EVIDENCE UPDATE V2 — Phase 15 "
                  "full test suite record",
        "schema": {"name": "dqaeip.update_v2.test_record", "version": "1.0"},
        "update_id": UPDATE_ID,
        "generated_utc": started,
        "invocation": "python -m pytest -q --tb=short (repository root, "
                      "canonical platform invocation)",
        "counts": counts,
        "previous_known_baseline": PREV_BASELINE,
        "comparison": {
            "passed_delta": (counts["passed"] - PREV_BASELINE["passed"])
            if counts["passed"] is not None else None,
            "skipped_delta": counts["skipped"] - PREV_BASELINE["skipped"],
            "failed_delta": counts["failed"] - PREV_BASELINE["failed"],
            "errors_delta": counts["errors"] - PREV_BASELINE["errors"],
            "expected_delta": "+28 passed = the UPDATE-V2 path "
                              "regression tests (Phase 12, cases 1-12; "
                              "tests/assurance/test_update_v2_path_"
                              "regression.py)",
            "regressions": (counts["failed"] > 0 or counts["errors"] > 0
                            or counts["passed"] < PREV_BASELINE["passed"]
                            or counts["skipped"] != PREV_BASELINE["skipped"]),
        },
        "verdict": "PASS" if (baseline_ok and not counts["failed"]
                              and not counts["errors"]) else "FAIL",
        "summary_line_tail": raw_tail.strip().splitlines()[-3:],
    }
    os.makedirs(os.path.dirname(os.path.join(REPO_ROOT, TEST_OUT)),
                exist_ok=True)
    with open(os.path.join(REPO_ROOT, TEST_OUT), "w", encoding="utf-8") as f:
        json.dump(test_record, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"test record: {TEST_OUT} (verdict {test_record['verdict']})")
    if test_record["verdict"] != "PASS":
        return 4

    # ---- Phase 14: security / PII (existing scanner, unmodified) ----
    sec_started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report = release_security.build_security_release_report(REPO_ROOT)
    sec_wrapped = {
        "report": "DQAEIP FINAL PORTABLE EVIDENCE UPDATE V2 — Phase 14 "
                  "security/PII scan (existing fail-closed scanner, "
                  "unmodified)",
        "schema": {"name": "dqaeip.update_v2.security_scan",
                   "version": "1.0"},
        "update_id": UPDATE_ID,
        "generated_utc": sec_started,
        "scanner": "data_quality_platform.assurance.release_security"
                   ".build_security_release_report (the module behind "
                   "scripts/release_artifact_security_scan.py; invoked "
                   "directly so the canonical evidence/release report "
                   "of the previous round is preserved untouched)",
        "zip_section_note": "ZIP section NOT_VERIFIED at this stage "
                            "(pre-ZIP run); the built ZIP is scanned "
                            "separately by the ZIP builder and the "
                            "clean-room verifier",
        "scanner_report": report,
    }
    verdict = report.get("verdict", report.get("overall_verdict"))
    os.makedirs(os.path.dirname(os.path.join(REPO_ROOT, SEC_OUT)),
                exist_ok=True)
    with open(os.path.join(REPO_ROOT, SEC_OUT), "w", encoding="utf-8") as f:
        json.dump(sec_wrapped, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"security scan: verdict={verdict} -> {SEC_OUT}")
    print("  sections:", {k: (v.get("verdict") if isinstance(v, dict)
                              else v)
                          for k, v in report.items()
                          if isinstance(v, dict) and "verdict" in v})
    return 0


if __name__ == "__main__":
    sys.exit(main())
