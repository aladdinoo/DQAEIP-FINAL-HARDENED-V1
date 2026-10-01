#!/usr/bin/env python3
"""DQAEIP FINAL UPDATE 2026-09-17 — drift detector (§16).

Detects ten drift classes, each with source, expected value, actual
value, severity, and affected artifacts:

    CONTENT DRIFT        CONFIGURATION DRIFT
    RULE DRIFT           DEPENDENCY DRIFT
    SCHEMA DRIFT         RELEASE DRIFT
    EVIDENCE DRIFT       DOCUMENTATION DRIFT
    PROVENANCE DRIFT     TEST-BASELINE DRIFT

Critical drift blocks release. Detected drift is written to:

    evidence/FINAL_UPDATE_2026-09-17/drift/drift_report.json

Implementation note (documented deviation): task-book §16 names the
detector 'drift/drift_detector.py'. The detector tool lives in tools/
(next to tools/integrity_monitor.py, keeping executable tooling in one
place) while its machine-readable outputs are written to the required
evidence/FINAL_UPDATE_2026-09-17/drift/ namespace. The drift/
evidence directory therefore contains the detector's outputs, and the
tool itself is SHA-anchored in the dependency graph.
"""

import argparse
import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance.integrity import (  # noqa: E402
    IntegritySnapshotError, load_snapshot, run_drift_detection)

DEFAULT_SNAPSHOT = os.path.join(
    REPO_ROOT, "evidence", "FINAL_UPDATE_2026-09-17", "integrity",
    "baseline_snapshot.json")
DEFAULT_REPORT = os.path.join(
    REPO_ROOT, "evidence", "FINAL_UPDATE_2026-09-17", "drift",
    "drift_report.json")


def main():
    parser = argparse.ArgumentParser(
        description="DQAEIP drift detector (10 drift classes)")
    parser.add_argument("--snapshot", default=DEFAULT_SNAPSHOT)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        snapshot = load_snapshot(args.snapshot)
    except IntegritySnapshotError as exc:
        report = {
            "generated_utc": started,
            "overall_status": exc.status,
            "error": str(exc),
            "state": "NOT_VERIFIED" if exc.status == "NOT_VERIFIED"
            else "CRITICAL",
            "blocks_release": True,
        }
        _write(args.report, report)
        print(f"DRIFT DETECTOR: {exc.status}")
        print(f"  {exc}")
        return 4 if exc.status == "FAIL" else 3

    report = run_drift_detection(REPO_ROOT, snapshot)
    report["generated_utc"] = started
    _write(args.report, report)

    print(f"DRIFT DETECTOR: state={report['state']} "
          f"findings={report['finding_count']} "
          f"(critical={report['critical_count']}, "
          f"review={report['review_count']})")
    for f in report["findings"]:
        print(f"  [{f['severity']}] {f['drift_type']}: {f['source']} "
              f"expected={str(f['expected_value'])[:40]} "
              f"actual={str(f['actual_value'])[:40]}")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["state"] == "NONE" else (
        1 if report["state"] == "REVIEW" else 4)


def _write(path, report):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
        f.write("\n")


if __name__ == "__main__":
    sys.exit(main())
