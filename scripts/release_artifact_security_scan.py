#!/usr/bin/env python3
"""ASSURANCE REBASELINE 2026-09-17 — release artifact security scan
(task §7/§8/§19).

Runs the fail-closed release-artifact security scan and writes the
machine-readable security/privacy release report:

    evidence/release/security_release_report.json

Sections (task §19): secret scan result, path leakage result, artifact
inventory result, ZIP scan result, environment leakage result,
synthetic fixture classifications, fail-closed behavior status.

No actual secret values appear in the report (counts, paths, rule ids
and justifications only).

Usage:
    python scripts/release_artifact_security_scan.py [--zip-record PATH]

With --zip-record, the ZIP section records the built release ZIP's scan
result; without it (pre-ZIP run) the ZIP section is NOT_VERIFIED and
the post-ZIP regeneration must supply it.
Exit code 0 only when the overall verdict is PASS.
"""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_quality_platform.assurance import release_security

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO_ROOT, "evidence", "release",
                   "security_release_report.json")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    zip_record = None
    if "--zip-record" in argv:
        idx = argv.index("--zip-record")
        try:
            path = argv[idx + 1]
        except IndexError:
            print("--zip-record requires a path", file=sys.stderr)
            return 2
        try:
            with open(path, encoding="utf-8") as f:
                zip_record = json.load(f)
        except (OSError, ValueError) as exc:
            print(f"FAIL-CLOSED: zip record unreadable: {exc}",
                  file=sys.stderr)
            return 2

    report = release_security.build_security_release_report(
        REPO_ROOT, zip_record=zip_record)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
        f.write("\n")

    print("SECURITY RELEASE REPORT ->", os.path.relpath(OUT, REPO_ROOT))
    print("  overall verdict:", report["overall_verdict"])
    print("  secret scan:", report["credential_scan_result"]["verdict"],
          f'({report["credential_scan_result"]["real_secret_count"]} real, '
          f'{report["credential_scan_result"]["synthetic_fixture_count"]} '
          "synthetic, "
          f'{report["credential_scan_result"]["documentation_example_count"]}'
          " documented)")
    print("  path leakage:", report["path_leakage_result"]["verdict"])
    print("  artifact inventory:",
          report["artifact_inventory_result"]["verdict"])
    print("  zip scan:", report["zip_scan_result"]["verdict"])
    print("  fail-closed behavior:",
          report["fail_closed_behavior_status"]["verdict"])
    return 0 if report["overall_verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
