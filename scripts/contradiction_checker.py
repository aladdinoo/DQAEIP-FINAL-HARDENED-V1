#!/usr/bin/env python3
"""DQAEIP contradiction checker CLI (Phase 6).

Runs the assurance-layer contradiction check over the current
release-facing documents and writes the machine-readable report:

    evidence/release/contradiction_check.json

Exit code 0 only when verdict == CONSISTENT.
"""

import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(
    REPO_ROOT, "evidence", "release", "contradiction_check.json")


def main():
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)
    from data_quality_platform.assurance import contradiction_checker
    report = contradiction_checker.run_contradiction_check(REPO_ROOT)
    report["generated_utc"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"CONTRADICTION CHECK: {report['verdict']}")
    print(f"  docs scanned: {report['docs_scanned_count']}")
    print(f"  contradictions: {report['contradiction_count']}")
    for c in report["contradictions"][:25]:
        print(f"    ! [{c['type']}] {c['doc']}: "
              f"{str(c.get('recorded', c.get('match', '')))[:80]}")
    return 0 if report["verdict"] == "CONSISTENT" else 1


if __name__ == "__main__":
    sys.exit(main())
