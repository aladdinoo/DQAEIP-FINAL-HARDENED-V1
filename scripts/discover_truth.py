#!/usr/bin/env python3
"""DQAEIP ZERO-ASSUMPTION REBUILD — Phase 1 truth discovery.

Builds a machine-readable TRUTH INVENTORY of the current repository
from ACTUAL FILES (never from README, reports, badges, filenames, or
prior agent claims). Every identity is derived at discovery time:

    canonical Frozen V1 rule source (actual import + SHA-256)
    rule hashes (per-rule, from the registry itself)
    input/output schema (from contracts.py import + run manifests)
    official 3M evidence (both runs, I/O SHAs, rows, comparisons,
                         mismatches — from the evidence JSONs)
    checker script identity (SHA-256 of the actual checker)
    release gate structure (gate list from the gate record)
    assurance layer inventory (modules + test files on disk)
    manifests (release manifest + artifact manifest identities)
    final verification identity
    limitation registry

Cross-checks task-book expectations and records any discrepancy as a
FINDING (never silently repaired). Output:

    evidence/assurance_rebuild_baseline/truth_inventory.json

Read-only with respect to protected evidence.
"""

import hashlib
import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(
    REPO_ROOT, "evidence", "assurance_rebuild_baseline", "truth_inventory.json")

V1_EVIDENCE_DIR = "evidence/validation/2026-09-18/fresh_3m2/harness"
CHECKER = "scripts/final_3m_validation.py"

EXPECTED = {
    "v1_rule_count": 8,
    "v1_source_sha256":
        "daef1ded54c7d3c79898a1ba253be2acd5b6120e18b16b09009fdd7be9fc2276",
    "input_columns": 33,
    "output_columns": 41,
    "flag_columns": 8,
    "run_count": 2,
    "rows_per_run": 3000000,
    "comparisons_per_run": 24000000,
    "comparisons_combined": 48000000,
    "mismatches_per_run": 0,
    "mismatches_combined": 0,
    "input_sha256":
        "208154653ca965dd50a27c8a7b42e59ef2c7d65e6353ffb1d156b8c3029f1a6f",
    "output_sha256":
        "b02872e3ee0a1471c369793a76e292758e339a199ef7253c84d91152f657af69",
    "gate_count": 21,
}

REQUIRED_V1_RULE_IDS = [
    "first_name_cleaning_candidate",
    "last_name_cleaning_candidate",
    "name_cleaning_candidate",
    "email_blank",
    "email_syntax_failure",
    "proposed_email_export_eligible",
    "zip_state_assessable",
    "geography_mismatch_candidate",
]

ASSURANCE_MODULES = [
    "data_quality_platform/assurance/claims.py",
    "data_quality_platform/assurance/golden_snapshot.py",
    "data_quality_platform/assurance/limitation_registry.py",
    "data_quality_platform/assurance/path_firewall.py",
    "data_quality_platform/assurance/release_chain.py",
    "data_quality_platform/assurance/release_schema.py",
    "data_quality_platform/assurance/release_security.py",
    "data_quality_platform/assurance/stale_evidence.py",
    "data_quality_platform/assurance/status_model.py",
    "data_quality_platform/assurance/truth_model.py",
]

KEY_SOURCES = {
    "final_3m_results": f"{V1_EVIDENCE_DIR}/FINAL_RESULTS.json",
    "run1_manifest": f"{V1_EVIDENCE_DIR}/pass1_engine/manifest.json",
    "run1_evidence_root": f"{V1_EVIDENCE_DIR}/pass1_engine/evidence_root.json",
    "run2_manifest": f"{V1_EVIDENCE_DIR}/pass2_engine/manifest.json",
    "run2_evidence_root": f"{V1_EVIDENCE_DIR}/pass2_engine/evidence_root.json",
    "checker": CHECKER,
    "release_gate": "evidence/release_gate/final_release_gate.json",
    "release_manifest": "release_manifest.json",
    "artifact_manifest": "evidence/release/release_artifact_manifest.json",
    "final_verification": "evidence/final_verification/FINAL_VERIFICATION.json",
    "limitation_registry": "evidence/release/limitation_registry.json",
    "release_evidence_model": "evidence/release/release_evidence_model.json",
    "observability_status": "evidence/release/observability_status.json",
    "test_summary": "evidence/rebuild_verification/test_summary.json",
    "run_pair_verification": "evidence/rebuild_verification/run_pair_verification.json",
}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(rel):
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def main():
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    findings = []

    # ---- Frozen V1 (actual import) ------------------------------------
    sys.path.insert(0, REPO_ROOT)
    from data_quality_platform.rules.registry import RuleRegistry
    registry = RuleRegistry.create_default()
    rules = {}
    for rule in registry.get_all_rules():
        rules[rule.rule_id] = {
            "rule_version": rule.rule_version,
            "rule_hash": rule.hash,
        }
    v1_source_sha = sha256_file(
        os.path.join(REPO_ROOT, "data_quality_platform/rules/v1_rules.py"))

    if sorted(rules) != sorted(REQUIRED_V1_RULE_IDS):
        findings.append({
            "finding": "REGISTRY_RULE_SET_MISMATCH",
            "detail": {
                "actual": sorted(rules),
                "required": sorted(REQUIRED_V1_RULE_IDS),
            },
        })
    if v1_source_sha != EXPECTED["v1_source_sha256"]:
        findings.append({
            "finding": "FROZEN_V1_SOURCE_SHA_MISMATCH",
            "detail": {
                "actual": v1_source_sha,
                "expected": EXPECTED["v1_source_sha256"],
                "policy": "report, never silently repair",
            },
        })

    # ---- Schema (actual import) ---------------------------------------
    from data_quality_platform.contracts import (
        SOURCE_COLUMNS, FLAG_COLUMNS, OUTPUT_COLUMNS,
    )
    schema = {
        "source_of_truth": "data_quality_platform/contracts.py (actual import)",
        "input_columns": len(SOURCE_COLUMNS),
        "flag_columns": len(FLAG_COLUMNS),
        "output_columns": len(OUTPUT_COLUMNS),
        "input_column_names": list(SOURCE_COLUMNS),
        "flag_column_names": list(FLAG_COLUMNS),
    }
    if schema["input_columns"] != EXPECTED["input_columns"]:
        findings.append({"finding": "INPUT_COLUMN_COUNT_MISMATCH",
                         "detail": {"actual": schema["input_columns"],
                                    "expected": EXPECTED["input_columns"]}})
    if schema["output_columns"] != EXPECTED["output_columns"]:
        findings.append({"finding": "OUTPUT_COLUMN_COUNT_MISMATCH",
                         "detail": {"actual": schema["output_columns"],
                                    "expected": EXPECTED["output_columns"]}})

    # ---- Official 3M evidence (from the evidence files themselves) ---
    f3m = load(KEY_SOURCES["final_3m_results"])
    run_manifests = {
        "run_1": load(KEY_SOURCES["run1_manifest"]),
        "run_2": load(KEY_SOURCES["run2_manifest"]),
    }
    runs_evidence = {}
    for i in (1, 2):
        run = f3m["runs"][f"run_{i}"]
        runs_evidence[f"run_{i}"] = {
            "run_id": run_manifests[f"run_{i}"]["run_id"],
            "status": run.get("status"),
            "rows": run_manifests[f"run_{i}"]["source_row_count"],
            "output_rows": run_manifests[f"run_{i}"]["output_row_count"],
            "oracle_comparisons": run.get("oracle", {}).get(
                "comparisons", run.get("oracle_comparisons")),
            "oracle_mismatches": run.get("oracle", {}).get(
                "mismatches", run.get("oracle_mismatches")),
            "manifest_schema_hash": run_manifests[f"run_{i}"]["schema_hash"],
            "manifest_rule_hashes": run_manifests[f"run_{i}"]["rule_hashes"],
            "evidence_root_sha256": load(
                KEY_SOURCES[f"run{i}_evidence_root"])["root_sha256"],
        }
    oracle_raw = f3m.get("oracle_comparisons")
    mism_raw = f3m.get("oracle_mismatches")
    comparisons_combined = (
        oracle_raw.get("combined_total")
        if isinstance(oracle_raw, dict) else oracle_raw)
    mismatches_combined = (
        mism_raw.get("combined_total")
        if isinstance(mism_raw, dict) else mism_raw)
    three_m = {
        "source_of_truth": f"{V1_EVIDENCE_DIR}/FINAL_RESULTS.json + per-run manifests",
        "final_status": f3m.get("final_status"),
        "run_count": len(f3m.get("runs", {})),
        "rows_per_run": f3m.get("rows"),
        "input_sha256": f3m.get("input_sha256"),
        "output_sha256": f3m.get("output_sha256"),
        "seed": f3m.get("seed"),
        "oracle_comparisons_per_run": (
            f3m["runs"]["run_1"]["oracle"]["comparisons"]
            if "runs" in f3m and "run_1" in f3m.get("runs", {}) else None),
        "oracle_comparisons_combined": comparisons_combined,
        "oracle_mismatches_combined": mismatches_combined,
        "runs": runs_evidence,
    }
    # Cross-checks against task-book expectations.
    checks = {
        "run_count_is_2": three_m["run_count"] == EXPECTED["run_count"],
        "rows_3m": three_m["rows_per_run"] == EXPECTED["rows_per_run"],
        "input_sha": three_m["input_sha256"] == EXPECTED["input_sha256"],
        "output_sha": three_m["output_sha256"] == EXPECTED["output_sha256"],
        "comparisons_combined_48m": (
            three_m["oracle_comparisons_combined"]
            == EXPECTED["comparisons_combined"]),
        "mismatches_combined_0": (
            three_m["oracle_mismatches_combined"]
            == EXPECTED["mismatches_combined"]),
    }
    for name, ok in checks.items():
        if not ok:
            findings.append({
                "finding": f"3M_EVIDENCE_{name.upper()}_MISMATCH",
                "detail": {
                    "actual": {
                        "run_count": three_m["run_count"],
                        "rows_per_run": three_m["rows_per_run"],
                        "input_sha256": three_m["input_sha256"],
                        "output_sha256": three_m["output_sha256"],
                        "comparisons_combined":
                            three_m["oracle_comparisons_combined"],
                        "mismatches_combined":
                            three_m["oracle_mismatches_combined"],
                    },
                    "expected": {
                        "run_count": EXPECTED["run_count"],
                        "rows_per_run": EXPECTED["rows_per_run"],
                        "input_sha256": EXPECTED["input_sha256"],
                        "output_sha256": EXPECTED["output_sha256"],
                        "comparisons_combined":
                            EXPECTED["comparisons_combined"],
                        "mismatches_combined": EXPECTED["mismatches_combined"],
                    },
                    "policy": ("official evidence is authoritative; report "
                               "discrepancy, never regenerate"),
                },
            })

    # Run 3 must not exist.
    run3_refs = []
    ev_root = os.path.join(REPO_ROOT, "evidence")
    for dirpath, _dirnames, filenames in os.walk(ev_root):
        for fn in filenames:
            if "run_3" in fn.lower() or "run3" in fn.lower():
                run3_refs.append(os.path.relpath(
                    os.path.join(dirpath, fn), REPO_ROOT))
    if run3_refs:
        findings.append({"finding": "RUN3_REFERENCE_FOUND",
                         "detail": {"paths": run3_refs[:20]}})

    # ---- Checker identity ----------------------------------------------
    checker_sha = sha256_file(os.path.join(REPO_ROOT, CHECKER))

    # ---- Release gate structure ----------------------------------------
    gate = load(KEY_SOURCES["release_gate"])
    gate_names = [g.get("gate") for g in gate.get("gates", [])]

    # ---- Assurance layer inventory -------------------------------------
    assurance = {}
    for rel in ASSURANCE_MODULES:
        p = os.path.join(REPO_ROOT, rel)
        assurance[rel] = sha256_file(p) if os.path.isfile(p) else None

    test_files = []
    tests_root = os.path.join(REPO_ROOT, "tests")
    for dirpath, _dirnames, filenames in os.walk(tests_root):
        for fn in sorted(filenames):
            if fn.startswith("test_") and fn.endswith(".py"):
                test_files.append(os.path.relpath(
                    os.path.join(dirpath, fn), REPO_ROOT).replace(os.sep, "/"))

    # ---- Manifests / verification / limitations ------------------------
    manifests = {
        "release_manifest_sha256": sha256_file(os.path.join(
            REPO_ROOT, "release_manifest.json")),
        "artifact_manifest_entries": len(load(
            KEY_SOURCES["artifact_manifest"]).get("artifacts", [])),
    }
    fv = load(KEY_SOURCES["final_verification"])
    lim = load(KEY_SOURCES["limitation_registry"])

    key_source_hashes = {}
    for name, rel in KEY_SOURCES.items():
        p = os.path.join(REPO_ROOT, rel)
        key_source_hashes[name] = {
            "path": rel,
            "sha256": sha256_file(p) if os.path.isfile(p) else None,
        }

    inventory = {
        "report": "DQAEIP zero-assumption rebuild — truth inventory",
        "generated_utc": started,
        "method": "every value derived from actual files at discovery time",
        "frozen_v1": {
            "canonical_source": "data_quality_platform/rules/v1_rules.py",
            "canonical_source_sha256": v1_source_sha,
            "registry_source": "data_quality_platform/rules/registry.py",
            "rule_count": len(rules),
            "rule_ids": sorted(rules),
            "rules": rules,
            "expected_source_sha256": EXPECTED["v1_source_sha256"],
            "matches_expected": v1_source_sha == EXPECTED["v1_source_sha256"],
        },
        "schema": schema,
        "official_3m_evidence": three_m,
        "run3_absent": not run3_refs,
        "checker": {
            "path": CHECKER,
            "sha256": checker_sha,
        },
        "release_gate": {
            "gate_count": gate.get("gate_count"),
            "gate_names": gate_names,
            "overall_verdict": gate.get("overall_verdict"),
        },
        "assurance_layer": {
            "modules": assurance,
            "test_files": test_files,
            "test_file_count": len(test_files),
        },
        "manifests": manifests,
        "final_verification": {
            "status": fv.get("status") or fv.get("final_status"),
            "checks_total": fv.get("checks_total"),
        },
        "limitations": {
            "count": len(lim.get("limitations", [])),
            "ids": [l.get("id") for l in lim.get("limitations", [])],
        },
        "key_source_identities": key_source_hashes,
        "task_book_crosschecks": checks,
        "findings": findings,
        "findings_count": len(findings),
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(inventory, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"TRUTH INVENTORY written to evidence/assurance_rebuild_baseline/truth_inventory.json")
    print(f"  V1: {len(rules)} rules, source matches expected: "
          f"{v1_source_sha == EXPECTED['v1_source_sha256']}")
    print(f"  Schema: {schema['input_columns']} in / "
          f"{schema['flag_columns']} flags / {schema['output_columns']} out")
    print(f"  3M: {three_m['run_count']} runs, rows/run "
          f"{three_m['rows_per_run']}, combined comparisons "
          f"{three_m['oracle_comparisons_combined']}, mismatches "
          f"{three_m['oracle_mismatches_combined']}")
    print(f"  Run 3 absent: {not run3_refs}")
    print(f"  Gate count: {gate.get('gate_count')}")
    print(f"  Findings: {len(findings)}")
    for fd in findings:
        print(f"    ! {fd['finding']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
