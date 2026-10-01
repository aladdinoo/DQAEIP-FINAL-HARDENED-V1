#!/usr/bin/env python3
"""DQAEIP FINAL PORTABLE EVIDENCE & RELEASE HARDENING — Phase 4.

Builds the ARTIFACT IDENTITY REGISTRY: the cryptographic identity of
every important artifact of the release, using the artifact identity
contract module (data_quality_platform/assurance/artifact_identity.py).

Classes assigned (closed vocabulary, task section 5):

    AUTHORITATIVE  frozen V1 source, official 3M run evidence, the
                  official checker and run-pair verifier
    DERIVED       every current release artifact generated from the
                  authoritative layer (this release's namespace, the
                  verified batteries, the portable derived copies)
    SUPERSEDED    prior-release key artifacts preserved as historical
                  record (FINAL_UPDATE namespace)
    UNKNOWN       protected artifacts not (yet) resolved into a class —
                  never forced into another class; recorded with their
                  protection note
    TEMPORARY     (none at release time)

The registry is fingerprinted deterministically (timestamp-free) and
each record is validated fail-closed: a live-hash mismatch makes the
build FAIL (STALE identity), never "close enough".
"""

import argparse
import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance.artifact_identity import (  # noqa: E402
    ARTIFACT_CLASSES, make_identity, registry_fingerprint,
    validate_identity)

NS = "evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18"
OUT_PATH = os.path.join(REPO_ROOT, NS, "artifact_identity",
                        "artifact_identity_registry.json")

OFFICIAL = "evidence/validation/2026-09-18/fresh_3m2/harness"

AUTHORITATIVE_ARTIFACTS = [
    ("data_quality_platform/rules/v1_rules.py", "1.0",
     "frozen V1 rule source (identity anchor daef1ded…)"),
    (f"{OFFICIAL}/FINAL_RESULTS.json", "1.0",
     "official 3M run-pair record (never regenerate; never modify)"),
    (f"{OFFICIAL}/pass1_result.json", "1.0",
     "official Run 1 result"),
    (f"{OFFICIAL}/pass2_result.json", "1.0",
     "official Run 2 result"),
    (f"{OFFICIAL}/pass1_cli.json", "1.0",
     "official Run 1 CLI capture"),
    (f"{OFFICIAL}/pass2_cli.json", "1.0",
     "official Run 2 CLI capture"),
    (f"{OFFICIAL}/pass1_runtime_safety_events.json", "1.0",
     "official Run 1 runtime-safety audit-hook events"),
    (f"{OFFICIAL}/pass2_runtime_safety_events.json", "1.0",
     "official Run 2 runtime-safety audit-hook events"),
    ("scripts/final_3m_validation.py", "1.0",
     "official fail-closed checker (0ef7c10c…)"),
    ("scripts/verify_run_pair.py", "1.0",
     "official run-pair verifier (0ec07367…)"),
]

DERIVED_ARTIFACTS = [
    # verified batteries (current chain)
    ("evidence/rebuild_verification/run_pair_verification.json", "1.0",
     "95-check fail-closed verification of the official pair"),
    ("evidence/rebuild_verification/test_summary.json", "1.0",
     "full-suite collection/pass/skip counts"),
    ("evidence/mutation_testing/mutation_results.json", "1.0",
     "business-rule mutation battery"),
    ("evidence/release/assurance_mutation.json", "1.0",
     "false-PASS prevention battery"),
    ("evidence/release/limitation_registry.json", "1.0",
     "machine-readable documented limitations"),
    ("evidence/release/release_evidence_model.json", "2.0",
     "canonical evidence model"),
    ("evidence/release/claim_provenance.json", "1.0",
     "claim-level provenance records"),
    ("evidence/release/golden_release_snapshot.json", "1.0",
     "golden release snapshot"),
    ("evidence/release/reproducibility_manifest.json", "1.0",
     "reproducibility manifest"),
    ("evidence/release/consistency_matrix.json", "1.0",
     "consistency matrix"),
    # this release's portable layer (built by phases 1-10)
    (f"{NS}/path_forensics/ABSOLUTE_PATH_INVENTORY.json", "1.0",
     "Phase-1 absolute-path inventory (diagnostic quoting record)"),
    (f"{NS}/portable_paths/PORTABLE_EVIDENCE_NORMALIZATION.json", "1.0",
     "Phase-2 policy-A normalization summary"),
    (f"{NS}/release_gate/absolute_path_gate_report.json", "1.0",
     "Phase-3 absolute-path release gate report"),
    (f"{NS}/schema_versioning/SCHEMA_COMPATIBILITY_REPORT.json", "1.0",
     "Phase-6 schema compatibility report"),
    (f"{NS}/final_results/FINAL_RESULTS_PORTABLE_2026-09-18.json",
     "2.0", "Phase-10 two-phase rebuilt FINAL_RESULTS (portable)"),
    (f"{NS}/claim_graph/claim_graph.json", "1.0",
     "Phase-5 claim→evidence→hash provenance graph"),
    (f"{NS}/mutation_testing/evidence_mutation_matrix.json", "1.0",
     "Phase-8 evidence mutation matrix (16/16 rejected)"),
    (f"{NS}/security/tamper_matrix.json", "1.0",
     "artifact tamper matrix (15/15 detected)"),
    # portable derived representations of the official evidence
    (f"{NS}/portable_evidence/{OFFICIAL}/FINAL_RESULTS.json", "1.0",
     "normalized derived copy (policy A)"),
    (f"{NS}/portable_evidence/{OFFICIAL}/pass1_result.json", "1.0",
     "normalized derived copy (policy A)"),
    (f"{NS}/portable_evidence/{OFFICIAL}/pass2_result.json", "1.0",
     "normalized derived copy (policy A)"),
    (f"{NS}/portable_evidence/{OFFICIAL}/pass1_cli.json", "1.0",
     "normalized derived copy (policy A)"),
    (f"{NS}/portable_evidence/{OFFICIAL}/pass2_cli.json", "1.0",
     "normalized derived copy (policy A)"),
    (f"{NS}/portable_evidence/{OFFICIAL}/"
     f"pass1_runtime_safety_events.json", "1.0",
     "normalized derived copy (policy A)"),
    (f"{NS}/portable_evidence/{OFFICIAL}/"
     f"pass2_runtime_safety_events.json", "1.0",
     "normalized derived copy (policy A)"),
    # presentation layer (regenerated from the model)
    ("README.md", "1.0", "presentation only; never a source of truth"),
    ("RELEASE_NOTES.md", "1.0", "presentation only"),
    ("FINAL_RESULTS.json", "2.0", "root final results (generated)"),
    ("final_result.json", "2.0", "root final results (copy)"),
    ("release_manifest.json", "1.0", "root release manifest (generated)"),
]

SUPERSEDED_ARTIFACTS = [
    # clean-room rebuild 2026-09-18: the prior-release namespace
    # (evidence/FINAL_UPDATE_2026-09-17/) was deleted with the entire
    # old evidence tree; no prior-release artifacts are preserved in
    # this release. The SUPERSEDED class remains in the closed
    # vocabulary; this list is intentionally empty.
]

# runtime verification apparatus (release manifest, lock, snapshot,
# freshness, monitor report, zip records, self-contained verification)
# is INTENTIONALLY not registered here: those artifacts are generated
# after the registry in the finalize chain and are hash-pinned by the
# manifest/snapshot instead (a registry cannot contain artifacts that
# do not exist at registration time).
UNKNOWN_PROTECTED = [
    # deliberately NOT forced into another class; protected per the
    # classification inventory's UNKNOWN policy
    ("evidence/hardening_baseline/test_baseline.txt",
     "historical captured pytest output; not a release-truth source; "
     "retained under the UNKNOWN-protection policy with a narrow "
     "absolute-path-gate exception"),
]


def build_registry():
    records = []
    errors = []

    def add(rel, cls, schema, note, optional=False):
        try:
            rec = make_identity(
                rel, cls, schema_version=schema, repo_root=REPO_ROOT,
                provenance={"role": note,
                            "producer": "DQAEIP-FINAL-PORTABLE-"
                                        "EVIDENCE-RELEASE-2026-09-18"})
            records.append(rec)
        except (ValueError, FileNotFoundError) as exc:
            if optional:
                return None
            errors.append(str(exc))
            return None
        return rec

    for rel, schema, note in AUTHORITATIVE_ARTIFACTS:
        add(rel, "AUTHORITATIVE", schema, note)
    for rel, schema, note in DERIVED_ARTIFACTS:
        add(rel, "DERIVED", schema, note)
    for rel, schema, note in SUPERSEDED_ARTIFACTS:
        add(rel, "SUPERSEDED", schema, note)
    for rel, note in UNKNOWN_PROTECTED:
        # identity WITH class UNKNOWN and no forced reclassification
        try:
            rec = make_identity(rel, "UNKNOWN", schema_version="1.0",
                                repo_root=REPO_ROOT,
                                provenance={"protection_note": note})
            records.append(rec)
        except (ValueError, FileNotFoundError) as exc:
            errors.append(str(exc))

    return records, errors


def main():
    parser = argparse.ArgumentParser(
        description="Phase 4: build the artifact identity registry")
    parser.add_argument("--out", default=OUT_PATH)
    args = parser.parse_args()

    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    records, errors = build_registry()

    # self-identity: the registry cannot contain its own final SHA
    # (the file does not exist yet / would change when written). The
    # registry therefore carries an explicit self-reference note; the
    # caller (integrity snapshot) pins the WRITTEN file's SHA.
    self_rel = os.path.relpath(args.out, REPO_ROOT).replace(os.sep, "/")
    records = [r for r in records if r["relative_path"] != self_rel]

    problems = []
    for r in records:
        problems.extend(validate_identity(r, repo_root=REPO_ROOT))
    if errors:
        problems.extend(f"build error: {e}" for e in errors)

    counts = {}
    for r in records:
        counts[r["artifact_class"]] = counts.get(
            r["artifact_class"], 0) + 1

    doc = {
        "schema": {"name": "dqaeip.artifact_identity_registry", "version": "1.0"},
        "report": "DQAEIP artifact identity registry "
                  "(cryptographic identity contract)",
        "release_id": "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18",
        "generated_utc": started,
        "artifact_class_vocabulary": list(ARTIFACT_CLASSES),
        "record_count": len(records),
        "class_counts": counts,
        "identity_contract": {
            "logical_identity": "repo:// URI (stable across machines)",
            "physical_path": "repository-relative POSIX path",
            "cryptographic_identity": "SHA-256 of exact bytes",
            "artifact_class": "AUTHORITATIVE | DERIVED | SUPERSEDED | "
                              "UNKNOWN | TEMPORARY",
            "provenance": "producer + role per record",
            "unknown_policy": "UNKNOWN artifacts are never forced into "
                              "another class; reclassification requires "
                              "an explicit resolution record",
            "self_reference": "this registry's own SHA is pinned by "
                              "the integrity baseline snapshot, not by "
                              "itself (a file cannot contain its own "
                              "hash)",
        },
        "registry_fingerprint": registry_fingerprint(records),
        "fingerprint_policy": "deterministic, timestamp-free: SHA-256 "
                              "over canonical (logical_path, sha256, "
                              "artifact_class) triples",
        "validation_problems": problems,
        "records": records,
    }

    verdict = "PASS" if not problems else "FAIL"
    doc["verdict"] = verdict

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"artifact identity registry: {verdict} "
          f"({len(records)} records, {len(problems)} problems)")
    for c, n in sorted(counts.items()):
        print(f"  {c}: {n}")
    for p in problems[:15]:
        print(f"  [PROBLEM] {p}")
    print(f"registry fingerprint: {doc['registry_fingerprint']}")
    return 0 if verdict == "PASS" else 4


if __name__ == "__main__":
    sys.exit(main())
