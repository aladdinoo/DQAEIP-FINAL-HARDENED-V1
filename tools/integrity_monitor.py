#!/usr/bin/env python3
"""DQAEIP FINAL UPDATE 2026-09-17 — continuous integrity monitor (§13).

Runs monitors A-T against the baseline snapshot:

    A. content changes          K. release identity changes
    B. deletion                 L. FINAL_RESULTS changes
    C. unexpected creation      M. README metric changes
    D. rename                   N. Frozen V1 changes
    E. SHA changes              O. official 3M evidence changes
    F. permission changes       P. checker changes
    G. dependency changes       Q. Run 3 appearance
    H. stale evidence           R. duplicate artifact identity
    I. manifest changes         S. unauthorized artifacts
    J. provenance changes       T. malformed manifests

Output: PASS / WARNING / STALE / NOT_VERIFIED / FAIL per monitor and
overall. FAIL is never downgraded automatically.

Modes:
    default            run monitors, write the machine-readable report
    --record           additionally append detected changes to the
                       append-only change ledger (change_ledger.jsonl)
    --json             print the full JSON report to stdout
"""

import argparse
import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance.integrity import (  # noqa: E402
    IntegritySnapshotError, UPDATE_ID, append_ledger, ledger_entry,
    load_snapshot, run_all_monitors, sha256_file)

NS = "evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18"
DEFAULT_SNAPSHOT = os.path.join(
    REPO_ROOT, NS, "integrity", "baseline_snapshot.json")
DEFAULT_REPORT = os.path.join(
    REPO_ROOT, NS, "integrity", "integrity_monitor_report.json")
DEFAULT_LEDGER = os.path.join(
    REPO_ROOT, NS, "integrity", "change_ledger.jsonl")

EXIT_CODES = {
    "PASS": 0, "WARNING": 0, "STALE": 1, "INVALID": 2,
    "NOT_VERIFIED": 3, "FAIL": 4,
}


def main():
    parser = argparse.ArgumentParser(
        description="DQAEIP continuous integrity monitor (fail-closed)")
    parser.add_argument("--snapshot", default=DEFAULT_SNAPSHOT)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    parser.add_argument("--ledger", default=DEFAULT_LEDGER)
    parser.add_argument("--record", action="store_true",
                        help="append detected changes to the change ledger")
    parser.add_argument("--json", action="store_true",
                        help="print the full JSON report to stdout")
    args = parser.parse_args()

    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        snapshot = load_snapshot(args.snapshot)
    except IntegritySnapshotError as exc:
        report = {
            "update_id": UPDATE_ID,
            "generated_utc": started,
            "snapshot_path": os.path.relpath(
                args.snapshot, REPO_ROOT),
            "overall_status": exc.status,
            "monitors": {},
            "results": [],
            "error": str(exc),
            "fail_closed_statement": (
                "a missing snapshot is NOT_VERIFIED, never PASS; a "
                "corrupt snapshot is FAIL; FAIL is never downgraded"),
        }
        _write_report(args.report, report)
        print(f"INTEGRITY MONITOR: {exc.status}")
        print(f"  {exc}")
        return EXIT_CODES[exc.status]

    report = run_all_monitors(REPO_ROOT, snapshot)
    report["generated_utc"] = started
    report["snapshot_path"] = os.path.relpath(args.snapshot, REPO_ROOT)

    _write_report(args.report, report)

    if args.record:
        entries = _ledger_entries(report, started)
        written = append_ledger(args.ledger, entries)
        report["ledger_entries_written"] = written

    print(f"INTEGRITY MONITOR: {report['overall_status']}")
    for name, status in sorted(report["monitors"].items()):
        marker = "" if status == "PASS" else "  <-- attention"
        print(f"  [{status:>12}] {name}{marker}")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    return EXIT_CODES.get(report["overall_status"], 4)


def _write_report(path, report):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
        f.write("\n")


def _ledger_entries(report, started):
    """Convert monitor findings into append-only ledger entries."""
    entries = []
    for result in report.get("results", []):
        if result["status"] == "PASS":
            continue
        for finding in result["findings"]:
            entry = ledger_entry(
                artifact=_artifact_from_finding(finding),
                old_sha256=None,
                new_sha256=None,
                change_type=result["monitor"].split("_", 1)[1].upper(),
                expected=False,
                reason=finding,
                result=result["status"],
                actor="integrity_monitor",
                timestamp=started,
            )
            entries.append(entry)
    return entries


def _artifact_from_finding(finding: str):
    for token in finding.replace(":", " ").split():
        if token.startswith(("evidence/", "data_quality_platform/",
                             "scripts/", "tools/", "README",
                             "FINAL_RESULTS", "release_manifest")):
            return token
    return "unknown"


if __name__ == "__main__":
    sys.exit(main())
