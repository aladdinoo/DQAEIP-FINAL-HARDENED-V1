#!/usr/bin/env python3
"""DQAEIP FINAL PORTABLE EVIDENCE & RELEASE HARDENING — Phase 6.

Builds the SCHEMA COMPATIBILITY REPORT (task-book section 7):

    - every CURRENT release artifact of the portable release is
      classified: KNOWN / UNKNOWN_SCHEMA / MALFORMED / MISSING_SCHEMA
    - historical artifacts are classified as MISSING_SCHEMA (pre-
      versioning records) — they are NOT migrated; their historical
      accuracy is preserved
    - unknown schema rejection and malformed schema rejection are
      exercised by the evidence mutation matrix (Phase 8) and the
      schema unit tests

Fail-closed: the report FAILs (exit 4) when any CURRENT release
artifact is not KNOWN. Historical artifacts never affect the verdict
beyond being counted.
"""

import argparse
import glob
import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance.evidence_schema import (  # noqa: E402
    compatibility_report)

NS = "evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18"
OUT_PATH = os.path.join(REPO_ROOT, NS, "schema_versioning",
                        "SCHEMA_COMPATIBILITY_REPORT.json")

# current portable-release artifacts (must all be KNOWN)
# core portable layer artifacts (all exist when this report runs in
# the finalize chain); runtime verification apparatus (manifest, lock,
# snapshot, freshness, monitor report, zip records, self-contained
# verification) is generated later in the chain and is excluded —
# documented, not silently skipped)
CURRENT_ARTIFACTS = [
    f"{NS}/path_forensics/ABSOLUTE_PATH_INVENTORY.json",
    f"{NS}/portable_paths/PORTABLE_EVIDENCE_NORMALIZATION.json",
    f"{NS}/release_gate/absolute_path_gate_report.json",
    f"{NS}/release_gate/absolute_path_gate_exceptions.json",
    f"{NS}/artifact_identity/artifact_identity_registry.json",
    f"{NS}/claim_graph/claim_graph.json",
    f"{NS}/final_results/FINAL_RESULTS_PORTABLE_2026-09-18.json",
    f"{NS}/dependency_graph/dependency_graph.json",
    f"{NS}/mutation_testing/evidence_mutation_matrix.json",
    f"{NS}/security/tamper_matrix.json",
    f"{NS}/release_manifest/RELEASE_IDENTITY.json",
    f"{NS}/historical_policy/HISTORICAL_EVIDENCE_POLICY.json",
    "FINAL_RESULTS.json",
    "final_result.json",
    "release_manifest.json",
]

HISTORICAL_GLOBS = [
    "evidence/validation/2026-09-18/fresh_3m2/harness/*.json",
    "evidence/FINAL_UPDATE_2026-09-17/**/*.json",
    "evidence/release/*.json",
    "evidence/rebuild_verification/*.json",
    "evidence/mutation_testing/*.json",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=OUT_PATH)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    docs = {}
    missing = []
    for rel in CURRENT_ARTIFACTS:
        p = os.path.join(REPO_ROOT, rel)
        if not os.path.isfile(p):
            missing.append(rel)
            continue
        try:
            with open(p, encoding="utf-8") as f:
                docs[rel] = json.load(f)
        except (OSError, json.JSONDecodeError):
            docs[rel] = {"broken": True}

    historical = []
    for pattern in HISTORICAL_GLOBS:
        for p in sorted(glob.glob(os.path.join(REPO_ROOT, pattern))):
            rel = os.path.relpath(p, REPO_ROOT).replace(os.sep, "/")
            if rel in docs:
                continue
            historical.append(rel)

    rep = compatibility_report(docs)

    current_status = {}
    for rel in CURRENT_ARTIFACTS:
        if rel in rep["entries"]:
            current_status[rel] = rep["entries"][rel]["status"]
    bad_current = {rel: st for rel, st in current_status.items()
                   if st != "KNOWN"}

    doc = {
        "report": "DQAEIP evidence schema compatibility report",
        "release_id": "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18",
        "generated_utc": started,
        "current_artifact_count": len(CURRENT_ARTIFACTS),
        "current_artifacts_classified": len(current_status),
        "current_artifacts_not_known": bad_current,
        "current_artifacts_missing": missing,
        "historical_artifacts_examined": len(historical),
        "historical_policy": (
            "historical and pre-versioning artifacts are documented as "
            "MISSING_SCHEMA records; they are never migrated and "
            "never automatically become PASS"),
        "status_counts": rep["status_counts"],
        "entries": rep["entries"],
        "policy": rep["policy"],
        "verdict": ("PASS" if not bad_current and not missing
                    else "FAIL"),
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")

    if not args.quiet:
        print(f"schema compatibility: {doc['verdict']}")
        print(f"  current artifacts: {len(current_status)}/"
              f"{len(CURRENT_ARTIFACTS)} classified, "
              f"{len(bad_current)} not KNOWN, {len(missing)} missing")
        print(f"  status counts: {rep['status_counts']}")
        for rel, st in sorted(bad_current.items()):
            print(f"  [NOT KNOWN] {rel}: {st}")
        for rel in missing:
            print(f"  [MISSING] {rel}")
    return 0 if doc["verdict"] == "PASS" else 4


if __name__ == "__main__":
    sys.exit(main())
