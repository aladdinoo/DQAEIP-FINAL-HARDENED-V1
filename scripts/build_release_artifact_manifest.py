#!/usr/bin/env python3
"""ASSURANCE REBASELINE 2026-09-17 — release artifact manifest builder
(task §9).

Builds a release-level, machine-readable integrity manifest for every
authoritative release artifact:

    evidence/release/release_artifact_manifest.json

Each entry records: repository-relative path, file size, SHA-256,
artifact role, and evidence classification. No absolute paths are
stored (fail-closed: a machine-local path anywhere in the manifest
aborts the build). Verification mode recomputes every hash and fails on
any drift (task §21 step 5).

Roles/classifications are declared in a reviewed table; unknown files
are NOT silently included — the required set is explicit and missing
files fail the build.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_quality_platform.assurance.path_firewall import scan_text

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO_ROOT, "evidence", "release",
                   "release_artifact_manifest.json")

# Authoritative release artifacts (task §9 minimum set).
# (path, role, evidence classification, phase)
# phase "core"     — must exist whenever the manifest is built
# phase "post_zip" — produced only after the release ZIP exists; the
#                     pre-ZIP manifest records them as PENDING (never
#                     silently skipped); --finalize requires them.
ARTIFACT_TABLE = [
    ("README.md", "release documentation",
     "RELEASE_DOCUMENT", "core"),
    ("RELEASE_NOTES.md", "release changelog",
     "RELEASE_DOCUMENT", "core"),
    ("FINAL_RESULTS.json", "rebuilt canonical release result",
     "RELEASE_DOCUMENT_DERIVED_FROM_EVIDENCE", "core"),
    ("final_result.json", "compatibility mirror of FINAL_RESULTS",
     "RELEASE_DOCUMENT_DERIVED_FROM_EVIDENCE", "core"),
    ("release_manifest.json", "release identity + artifact hashes",
     "RELEASE_DOCUMENT_DERIVED_FROM_EVIDENCE", "core"),
    ("evidence/release/release_evidence_model.json",
     "canonical evidence model", "AUTHORITATIVE_EVIDENCE", "core"),
    ("evidence/release/golden_release_snapshot.json",
     "PII-free release fingerprint", "AUTHORITATIVE_EVIDENCE", "core"),
    ("evidence/release/consistency_matrix.json",
     "cross-document consistency check", "AUTHORITATIVE_EVIDENCE",
     "core"),
    ("evidence/release/assurance_mutation.json",
     "negative release gate evidence", "AUTHORITATIVE_EVIDENCE", "core"),
    ("evidence/release/claim_provenance.json",
     "claim-level provenance", "AUTHORITATIVE_EVIDENCE", "core"),
    ("evidence/release/limitation_registry.json",
     "structured limitation registry", "AUTHORITATIVE_EVIDENCE",
     "core"),
    ("evidence/release/reproducibility_manifest.json",
     "reproducibility capsule", "AUTHORITATIVE_EVIDENCE", "core"),
    ("evidence/release/reproducibility_fingerprint.json",
     "deterministic composite reproducibility fingerprint",
     "AUTHORITATIVE_EVIDENCE_DERIVED", "core"),
    ("evidence/release/rule_impact_graph.json",
     "Frozen V1 rule impact graph (metadata only)",
     "AUTHORITATIVE_EVIDENCE_DERIVED", "core"),
    ("evidence/release/contradiction_check.json",
     "dedicated contradiction checker report",
     "AUTHORITATIVE_EVIDENCE_DERIVED", "core"),
    ("evidence/release/evidence_quarantine_screen.json",
     "evidence quarantine screening report",
     "AUTHORITATIVE_EVIDENCE_DERIVED", "bootstrap_screen"),
    ("evidence/release/observability_status.json",
     "five-dimension observability status record",
     "AUTHORITATIVE_EVIDENCE_DERIVED", "core"),
    ("evidence/release/readme_consistency.json",
     "README/evidence automated consistency check",
     "AUTHORITATIVE_EVIDENCE_DERIVED", "core"),
    ("evidence/release_gate/final_release_gate.json",
     "unified 21-gate fail-closed release gate result",
     "AUTHORITATIVE_EVIDENCE", "core"),
    ("evidence/rebuild_verification/test_summary.json",
     "machine-parsed full-suite test identity",
     "AUTHORITATIVE_EVIDENCE", "core"),
    ("evidence/rebuild_verification/run_pair_verification.json",
     "Run 1 + Run 2 pair verification (95/95)",
     "AUTHORITATIVE_EVIDENCE", "core"),
    ("evidence/mutation_testing/mutation_results.json",
     "business mutation testing evidence (17/17)",
     "AUTHORITATIVE_EVIDENCE", "core"),
    ("evidence/dqvp_performance/performance_results.json",
     "measured performance ladder", "AUTHORITATIVE_EVIDENCE", "core"),
    ("data_quality_platform/rules/v1_rules.py",
     "frozen V1 rule source", "FROZEN_PRODUCTION_SOURCE", "core"),
    ("data_quality_platform/contracts.py",
     "frozen contract source", "FROZEN_PRODUCTION_SOURCE", "core"),
    ("data_quality_platform/validation/engine.py",
     "frozen validation engine", "FROZEN_PRODUCTION_SOURCE", "core"),
    # post-ZIP artifacts (regenerated after the release ZIP exists)
    ("evidence/release/final_verification.json",
     "final verification report (regenerated at terminal state)",
     "AUTHORITATIVE_EVIDENCE_DERIVED", "post_zip"),
    ("evidence/release/security_release_report.json",
     "security/privacy release report (zip section post-ZIP)",
     "AUTHORITATIVE_EVIDENCE_DERIVED", "post_zip"),
    # 2026-09-19 hardened release: the post-ZIP record is THIS
    # release's zip record (written after the ZIP exists, committed
    # with the final release commit; non-self-referential model)
    ("evidence/FINAL_HARDENED_RELEASE_2026-09-19/release_manifest/"
     "zip_record.json",
     "hardened release ZIP record (non-self-referential; repo-side)",
     "AUTHORITATIVE_EVIDENCE", "post_zip"),
]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(include_self=False, finalize=False):
    """Build manifest entries. ``finalize`` requires post-ZIP artifacts;
    otherwise they are recorded as PENDING_POST_ZIP_REBUILD (explicit,
    never silently skipped)."""
    entries = []
    missing_core = []
    pending = []
    for rel, role, classification, phase in ARTIFACT_TABLE:
        path = os.path.join(REPO_ROOT, rel)
        if not os.path.isfile(path):
            if phase in ("core", "bootstrap_screen") and os.path.isfile(path):
                pass  # present: hashed below like core
            elif phase == "core":
                missing_core.append(rel)
            elif finalize:
                missing_core.append(rel)  # finalize requires everything
            else:
                pending.append(rel)
                entries.append({
                    "path": rel,
                    "size_bytes": None,
                    "sha256": None,
                    "artifact_role": role,
                    "evidence_classification": classification,
                    "status": "PENDING_POST_ZIP_REBUILD",
                    "note": ("artifact exists only after the release "
                             "ZIP is built; the post-ZIP manifest "
                             "rebuild (--finalize) must hash it — "
                             "never silently skipped"),
                })
            continue
        entries.append({
            "path": rel,
            "size_bytes": os.path.getsize(path),
            "sha256": sha256_file(path),
            "artifact_role": role,
            "evidence_classification": classification,
        })
    if include_self and os.path.isfile(OUT):
        entries.append({
            "path": "evidence/release/release_artifact_manifest.json",
            "size_bytes": os.path.getsize(OUT),
            "sha256": None,  # self-hash written post-serialization
            "artifact_role": "this manifest (self entry)",
            "evidence_classification": "AUTHORITATIVE_EVIDENCE_DERIVED",
            "note": "sha256_self recorded at manifest top level; the "
                    "in-file self sha256 field is intentionally null",
        })
    return entries, missing_core, pending


def verify(manifest, require_complete=False):
    """Fail-closed verification of an existing manifest (task §21-5).

    Recomputes every hash; fails on drift, on missing artifacts, on
    duplicate artifact identities, and (with ``require_complete``) on
    any PENDING entry — a non-terminal manifest must never be reported
    as fully verified.
    """
    problems = []
    seen_paths = set()
    for entry in manifest.get("artifacts", []):
        rel = entry.get("path")
        if rel in seen_paths:
            problems.append(f"duplicate artifact identity: {rel}")
            continue
        seen_paths.add(rel)
        path = os.path.join(REPO_ROOT, rel)
        if entry.get("status") == "PENDING_POST_ZIP_REBUILD":
            if require_complete:
                problems.append(f"pending (non-terminal) entry: {rel}")
            continue
        if not os.path.isfile(path):
            problems.append(f"missing artifact {rel}")
            continue
        if entry.get("sha256") and sha256_file(path) != entry["sha256"]:
            problems.append(f"hash drift: {rel}")
        if entry.get("size_bytes") != os.path.getsize(path):
            problems.append(f"size drift: {rel}")
    declared = {e["path"] for e in manifest.get("artifacts", [])}
    for rel, _, _, phase in ARTIFACT_TABLE:
        if rel not in declared:
            problems.append(f"required artifact absent from manifest: {rel}")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true",
                        help="verify the existing manifest (recompute "
                             "hashes; fail on any drift or missing)")
    parser.add_argument("--require-complete", action="store_true",
                        help="with --verify: PENDING entries also fail "
                             "(terminal-state verification)")
    parser.add_argument("--finalize", action="store_true",
                        help="build the terminal manifest (post-ZIP "
                             "artifacts must exist and be hashed)")
    parser.add_argument("--include-self", action="store_true",
                        help="add the manifest itself as an entry with "
                             "null in-file sha256")
    args = parser.parse_args(argv)

    if args.verify:
        try:
            with open(OUT, encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, ValueError) as exc:
            print(f"FAIL-CLOSED: manifest unreadable: {exc}",
                  file=sys.stderr)
            return 1
        problems = verify(manifest,
                          require_complete=args.require_complete)
        if problems:
            print("MANIFEST VERIFICATION FAILURES:", file=sys.stderr)
            for p in problems:
                print(f"  - {p}", file=sys.stderr)
            return 1
        n_pending = sum(1 for e in manifest["artifacts"]
                        if e.get("status") == "PENDING_POST_ZIP_REBUILD")
        print(f"MANIFEST VERIFIED: {len(manifest['artifacts'])} "
              f"artifacts, zero drift"
              + (f" ({n_pending} pending post-ZIP rebuild)"
                 if n_pending else " (terminal, complete)"))
        return 0

    entries, missing, pending = build_manifest(
        include_self=args.include_self, finalize=args.finalize)
    if missing:
        print("FAIL-CLOSED: missing required artifacts:", file=sys.stderr)
        for rel in missing:
            print(f"  - {rel}", file=sys.stderr)
        return 1

    manifest = {
        "report": "DQAEIP release artifact manifest",
        "schema_version": "1.0.0",
        "generated_utc": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "manifest_phase": ("terminal (post-ZIP; all artifacts hashed)"
                           if args.finalize else
                           "pre-ZIP (post-ZIP artifacts PENDING, never "
                           "silently skipped)"),
        "path_policy": "repository-relative paths only; any "
                       "machine-local path aborts the build",
        "hash_policy": "SHA-256 recomputed from file bytes at build "
                       "time; verification recomputes and fails closed "
                       "on drift",
        "artifact_count": len(entries),
        "pending_artifacts": pending,
        "artifacts": entries,
    }

    # fail-closed: no machine-local paths anywhere in the manifest
    leaks = scan_text(json.dumps(manifest))
    if leaks:
        print("FAIL-CLOSED: machine-local path in manifest:",
              [l["matched"] for l in leaks], file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")

    # record the manifest's own hash at top level (outside the file)
    manifest_sha = sha256_file(OUT)
    manifest["manifest_sha256_self"] = manifest_sha
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"RELEASE ARTIFACT MANIFEST -> "
          f"{os.path.relpath(OUT, REPO_ROOT)}")
    print(f"  artifacts: {len(entries)} (+ self-hash "
          f"{manifest_sha[:16]}...)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
