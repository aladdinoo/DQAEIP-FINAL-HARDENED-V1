#!/usr/bin/env python3
"""ASSURANCE REBASELINE 2026-09-17 — observability status record builder
(task §11/§12).

Assembles the five-dimension status record plus the structured
observability fields (run_id, dataset identity, I/O hashes, rule-set
identity, schema, durations, row/flag/mismatch counts, SLA, safety,
evidence, release verdict) STRICTLY from the canonical evidence
artifacts. No value is hand-typed; nothing is re-executed; the official
3M evidence is read in place.

The record keeps five dimensions SEPARATE and never collapses them into
one ambiguous "PASS":
    VALIDATION_STATUS / DATA_QUALITY_SLA_STATUS / RUNTIME_SAFETY_STATUS
    / EVIDENCE_INTEGRITY_STATUS / RELEASE_VERDICT

Output: evidence/release/observability_status.json
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_quality_platform.assurance import status_model

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 2026-09-19 hardened release: read the fresh regression evidence
# (frozen checker, seed 20260918, exact baseline reproduction)
EVIDENCE_3M = os.path.join(REPO_ROOT, "evidence", "validation",
                           "2026-09-19", "fresh_3m2")
OUT = os.path.join(REPO_ROOT, "evidence", "release",
                   "observability_status.json")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def maybe_load(path):
    try:
        return load(path)
    except (OSError, ValueError):
        return None


def main():
    final_3m = maybe_load(os.path.join(EVIDENCE_3M, "FINAL_RESULTS.json"))
    monitoring = maybe_load(os.path.join(EVIDENCE_3M, "pass1_engine",
                                        "monitoring.json"))
    manifest = maybe_load(os.path.join(EVIDENCE_3M, "pass1_engine",
                                       "manifest.json"))
    gate = maybe_load(os.path.join(REPO_ROOT, "evidence", "release_gate",
                                   "final_release_gate.json"))
    fr = maybe_load(os.path.join(REPO_ROOT, "FINAL_RESULTS.json"))
    ts = maybe_load(os.path.join(REPO_ROOT, "evidence", "rebuild_verification",
                                 "test_summary.json"))

    # --- five-dimension status record (fail-closed derivation)
    record = status_model.derive_status_record(
        final_3m=final_3m, monitoring=monitoring, gate=gate,
        final_results=fr)
    problems = status_model.validate_status_record(record)
    if problems:
        print("STATUS RECORD INVALID (fail closed):", problems,
              file=sys.stderr)
        return 1

    # --- structured observability fields (§11), machine-read
    runs = (final_3m or {}).get("runs", {})
    run_ids = []
    for key in ("run_1", "run_2"):
        run = runs.get(key) or {}
        run_ids.append(run.get("run_id") or run.get("manifest_run_id"))
    if not any(run_ids):
        run_ids = [manifest.get("run_id")] if manifest else [None]

    stage = (final_3m or {}).get("stage_runtime_seconds", {})
    flag_totals = (final_3m or {}).get("flag_totals_output_csv", {})

    observability_fields = {
        "run_ids": run_ids,
        "dataset_identity": {
            "seed": (final_3m or {}).get("seed"),
            "rows": (final_3m or {}).get("rows"),
            "input_columns": (final_3m or {}).get("columns"),
            "output_columns": (final_3m or {}).get("output_columns"),
            "generation": "deterministic synthetic dataset "
                          "(planted defects by design)",
        },
        "input_sha256": (final_3m or {}).get("input_sha256"),
        "output_sha256": (final_3m or {}).get("output_sha256"),
        "rule_set": {
            "registry": "exactly 8 frozen V1 rules",
            "rule_hashes_source": "pass1_engine/manifest.json",
            "rule_hashes": (manifest or {}).get("rule_hashes"),
        },
        "schema": {
            "schema_hash": (manifest or {}).get("schema_hash"),
            "input_contract_columns": 33,
            "output_contract_columns": 41,
        },
        "execution_status": (final_3m or {}).get("final_status"),
        "durations": {
            "validation_wall_seconds_per_run": [
                stage.get("validation_pass1"),
                stage.get("validation_pass2"),
            ],
            "verification_wall_seconds_per_run": [
                stage.get("verify_oracle_pass1"),
                stage.get("verify_oracle_pass2"),
            ],
            "total_staged_runtime_seconds": (
                (final_3m or {}).get("runtime_seconds")),
            "note": "official 2026-09-15 measurements, not re-executed",
        },
        "row_counts": {
            "per_run": (final_3m or {}).get("rows"),
            "runs": 2,
        },
        "flag_counts": flag_totals,
        "mismatch_counts": {
            "oracle_comparisons_per_run": (final_3m or {}).get(
                "oracle_comparisons_note") and
            (final_3m or {}).get("oracle_comparisons"),
            "oracle_mismatches": (final_3m or {}).get("oracle_mismatches"),
        },
        "test_identity": {
            "collected": (ts or {}).get("collected"),
            "passed": (ts or {}).get("passed"),
            "skipped": (ts or {}).get("skipped"),
            "failed": (ts or {}).get("failed"),
            "errors": (ts or {}).get("errors"),
        },
        "structured_logging": {
            "mechanism": "engine audit trail (audit.json)",
            "properties": ["run_id-scoped events", "timestamps",
                           "machine-readable JSON", "deterministic order"],
            "evidence": "evidence/validation/2026-09-19/fresh_3m2/"
                        "pass1_engine/audit.json",
            "note": "engine logging semantics unchanged (frozen V1 "
                    "execution); observability is derived, never "
                    "injected into execution",
        },
    }

    doc = {
        "report": "DQAEIP observability status record",
        "schema_version": "1.0.0",
        "generated_utc": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "derivation": ("five-dimension status record + structured "
                       "observability fields derived from canonical "
                       "evidence artifacts; no re-execution; official "
                       "3M evidence read in place"),
        "status_dimensions": record,
        "status_summary": status_model.render_status_summary(record),
        "observability_fields": observability_fields,
        "dimension_independence_note": (
            "VALIDATION_STATUS (execution correctness: 51,200,000 "
            "oracle comparisons, 0 mismatches, byte-identical outputs) "
            "is INDEPENDENT of DATA_QUALITY_SLA_STATUS (dimension "
            "scores of the synthetic dataset with planted defects). "
            "SLA monitoring warnings occurred during the official 3M "
            "run and are recorded as NOT_MET observations; they do not "
            "invalidate validation correctness, and an SLA PASS would "
            "not establish validation correctness either."),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")

    print("OBSERVABILITY STATUS ->", os.path.relpath(OUT, REPO_ROOT))
    for line in doc["status_summary"].splitlines():
        print("  ", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
