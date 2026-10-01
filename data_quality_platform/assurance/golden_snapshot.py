"""Golden Release Snapshot (DQAEIP rebuild Phase 16).

A small, PII-free release fingerprint binding the release identity to
the verified execution identities:

    - 33-column input schema hash
    - 41-column output schema hash
    - V1 rule IDs / versions / hashes
    - checker script hash
    - input hash, output hash
    - test summary hash
    - release gate hash
    - evidence roots (per run)

Metadata ONLY. No customer data, no PII, no machine-local paths.
"""

import hashlib
import json
import os

__all__ = ["REQUIRED_SNAPSHOT_KEYS", "build_snapshot", "validate_snapshot"]

REQUIRED_SNAPSHOT_KEYS = (
    "snapshot_type",
    "release_identity",
    "input_schema_hash_33",
    "output_schema_hash_41",
    "v1_rule_ids",
    "v1_rule_versions",
    "v1_rule_hashes",
    "checker_sha256",
    "input_sha256",
    "output_sha256",
    "test_summary_sha256",
    "release_gate_sha256",
    "evidence_roots",
)


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_snapshot(repo_root, release_identity):
    """Build the golden snapshot from ACTUAL artifacts (fail-closed
    on missing sources: missing fields stay null and validation fails).
    """
    import sys
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from data_quality_platform.rules.registry import RuleRegistry

    registry = RuleRegistry.create_default()
    rules = sorted(registry.get_all_rules(), key=lambda r: r.rule_id)

    fr = _load_json(os.path.join(
        repo_root, "evidence/validation/2026-09-19/fresh_3m2",
        "FINAL_RESULTS.json")) or {}

    m1 = _load_json(os.path.join(
        repo_root, "evidence/validation/2026-09-19/fresh_3m2",
        "pass1_engine", "manifest.json")) or {}
    m2 = _load_json(os.path.join(
        repo_root, "evidence/validation/2026-09-19/fresh_3m2",
        "pass2_engine", "manifest.json")) or {}
    er1 = _load_json(os.path.join(
        repo_root, "evidence/validation/2026-09-19/fresh_3m2",
        "pass1_engine", "evidence_root.json")) or {}
    er2 = _load_json(os.path.join(
        repo_root, "evidence/validation/2026-09-19/fresh_3m2",
        "pass2_engine", "evidence_root.json")) or {}

    checker_path = os.path.join(repo_root, "scripts",
                                "final_3m_validation.py")
    gate_path = os.path.join(repo_root, "evidence/release_gate",
                             "final_release_gate.json")
    test_summary_path = os.path.join(repo_root, "evidence",
                                     "rebuild_verification",
                                     "test_summary.json")

    # 41-column output schema identity: deterministic SHA-256 over the
    # frozen OUTPUT_COLUMNS contract (same algorithm as the engine's
    # schema hash: sha256 of comma-joined ordered column names).
    import hashlib as _hl
    from data_quality_platform.contracts import OUTPUT_COLUMNS
    output_schema_hash = _hl.sha256(
        ",".join(OUTPUT_COLUMNS).encode("utf-8")).hexdigest()

    snapshot = {
        "snapshot_type": "golden_release_fingerprint_metadata_only",
        "release_identity": release_identity,
        "input_schema_hash_33": m1.get("schema_hash"),
        "output_schema_hash_41": output_schema_hash,
        "output_column_count_41": len(OUTPUT_COLUMNS),
        "v1_rule_ids": [r.rule_id for r in rules],
        "v1_rule_versions": {r.rule_id: r.rule_version for r in rules},
        "v1_rule_hashes": {r.rule_id: r.hash for r in rules},
        "checker_sha256": (_sha256_file(checker_path)
                           if os.path.isfile(checker_path) else None),
        "input_sha256": fr.get("input_sha256"),
        "output_sha256": fr.get("output_sha256"),
        "test_summary_sha256": (_sha256_file(test_summary_path)
                                 if os.path.isfile(test_summary_path)
                                 else None),
        "release_gate_sha256": (_sha256_file(gate_path)
                                if os.path.isfile(gate_path) else None),
        "evidence_roots": {
            "run_1": er1.get("root_sha256"),
            "run_2": er2.get("root_sha256"),
        },
        "schema_note": (
            "input_schema_hash_33 is the 33-column input schema hash "
            "from the run manifest; output_schema_hash_41 is the "
            "deterministic SHA-256 over the frozen 41 OUTPUT_COLUMNS "
            "contract (comma-joined ordered names, same algorithm as "
            "the engine schema hash)"
        ),
        "pii_statement": (
            "this snapshot is metadata only; it contains no customer "
            "data, no PII, no credentials, no machine-local paths"
        ),
    }
    # include a run-recorded output schema hash when present
    out_schema = (m1.get("output_schema_hash")
                  or fr.get("output_schema_hash"))
    if out_schema:
        snapshot["run_recorded_output_schema_hash"] = out_schema
    return snapshot


def validate_snapshot(snapshot):
    """Validate snapshot completeness; returns problem list (empty=ok)."""
    problems = []
    if not isinstance(snapshot, dict):
        return ["snapshot: not an object"]
    for key in REQUIRED_SNAPSHOT_KEYS:
        if key not in snapshot:
            problems.append(f"snapshot: missing key {key!r}")
        elif snapshot[key] is None:
            problems.append(f"snapshot: key {key!r} is null "
                            f"(NOT_VERIFIED — fail closed)")
    rules = snapshot.get("v1_rule_ids")
    if isinstance(rules, list) and len(rules) != 8:
        problems.append(f"snapshot: expected 8 V1 rule IDs, got "
                        f"{len(rules)}")
    if not snapshot.get("evidence_roots", {}).get("run_1") or \
            not snapshot.get("evidence_roots", {}).get("run_2"):
        problems.append("snapshot: run evidence roots missing")
    return problems
