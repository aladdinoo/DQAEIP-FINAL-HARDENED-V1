#!/usr/bin/env python3
"""DQAEIP FINAL PORTABLE EVIDENCE & RELEASE HARDENING — Phase 10.

Two-phase FINAL_RESULTS rebuild for the portable release
(task-book section 11):

    AUTHORITATIVE -> STAGING -> SCHEMA VALIDATION ->
    DEPENDENCY VALIDATION -> INTEGRITY VALIDATION -> PROMOTION

Phase 1 (build):   derive FINAL_RESULTS_PORTABLE_2026-09-18.json
                   under evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18/
                   staging/ EXCLUSIVELY from verified authoritative
                   evidence (official 3M run pair, run-pair
                   verification, live registry/contracts imports, test
                   summary, mutation batteries, limitation registry).
                   No value is hand-entered; no previous FINAL_RESULTS
                   is copied.

Phase 2 (verify):  schema identity (dqaeip.final_results v2.0)
                   validation with anchor checks + cross-checks
                   against the authoritative sources. Any problem
                   aborts before promotion (old evidence retained,
                   staging retained, failure recorded).

Phase 3 (promote): atomic move of the verified document to
                   final_results/FINAL_RESULTS_PORTABLE_2026-09-18.json.

The 3M truth remains exactly: 2 complete runs, 3M rows/run,
24M comparisons/run, 48M combined, 0 mismatches, 8 Frozen V1 rules,
33 input columns, 41 output columns.
"""

import argparse
import json
import os
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance.evidence_schema import (  # noqa: E402
    validate_schema_identity)
from data_quality_platform.assurance.integrity import (  # noqa: E402
    OFFICIAL_CHECKER, OFFICIAL_EVIDENCE_DIR, OFFICIAL_INPUT_SHA256,
    OFFICIAL_OUTPUT_SHA256, OFFICIAL_VERIFIER,
    FROZEN_V1_EXPECTED_SHA256, FROZEN_V1_SOURCE,
    dependency_fingerprint, sha256_file)

NS = "evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18"
STAGING_PATH = os.path.join(REPO_ROOT, NS, "staging",
                            "FINAL_RESULTS_PORTABLE_2026-09-18.json")
CURRENT_PATH = os.path.join(REPO_ROOT, NS, "final_results",
                            "FINAL_RESULTS_PORTABLE_2026-09-18.json")
FAILURE_LOG = os.path.join(REPO_ROOT, NS, "staging",
                           "rebuild_failure.log")


def set_repo_root(root):
    """Override the working root (isolated recovery tests only)."""
    global REPO_ROOT, STAGING_PATH, CURRENT_PATH, FAILURE_LOG
    REPO_ROOT = root
    STAGING_PATH = os.path.join(REPO_ROOT, NS, "staging",
                                "FINAL_RESULTS_PORTABLE_2026-09-18.json")
    CURRENT_PATH = os.path.join(REPO_ROOT, NS, "final_results",
                                "FINAL_RESULTS_PORTABLE_2026-09-18.json")
    FAILURE_LOG = os.path.join(REPO_ROOT, NS, "staging",
                               "rebuild_failure.log")

EV_3M = f"{OFFICIAL_EVIDENCE_DIR}/FINAL_RESULTS.json"
RUN_PAIR = "evidence/rebuild_verification/run_pair_verification.json"
TEST_SUMMARY = "evidence/rebuild_verification/test_summary.json"
BUSINESS_MUTATION = "evidence/mutation_testing/mutation_results.json"
ASSURANCE_MUTATION = "evidence/release/assurance_mutation.json"
LIMIT_REGISTRY = "evidence/release/limitation_registry.json"
EVIDENCE_MUTATION_MATRIX = f"{NS}/mutation_testing/" \
                           "evidence_mutation_matrix.json"


def git(args):
    return subprocess.run(["git", "-C", REPO_ROOT] + args,
                          capture_output=True, text=True, check=False)


def load(rel):
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def derive() -> dict:
    """Derive the portable FINAL_RESULTS document from authoritative
    evidence ONLY (no copy of previous FINAL_RESULTS, no manual
    metrics)."""
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    fr3m = load(EV_3M)
    runs = fr3m["runs"]
    run_ids = sorted(runs.keys())
    rows_per_run = fr3m["rows"]
    comparisons_combined = fr3m["oracle_comparisons"]
    mismatches_combined = sum(
        int(r.get("oracle", {}).get("mismatches", -1))
        for r in runs.values())
    comparisons_per_run = [int(runs[r].get("oracle", {}).get(
        "comparisons", -1)) for r in run_ids]

    from data_quality_platform.rules.registry import RuleRegistry
    registry = RuleRegistry.create_default()
    rules = sorted(r.rule_id for r in registry.get_all_rules())
    from data_quality_platform.contracts import (
        SOURCE_COLUMNS, TOTAL_OUTPUT_COLUMNS)
    input_cols = len(SOURCE_COLUMNS)
    output_cols = TOTAL_OUTPUT_COLUMNS

    rp = load(RUN_PAIR)
    ts = load(TEST_SUMMARY)
    bm = load(BUSINESS_MUTATION)
    am = load(ASSURANCE_MUTATION)
    lr = load(LIMIT_REGISTRY)
    emm = load(EVIDENCE_MUTATION_MATRIX) \
        if os.path.isfile(os.path.join(REPO_ROOT,
                                       EVIDENCE_MUTATION_MATRIX)) \
        else {}

    dependencies = [
        {"path": p, "sha256": sha256_file(os.path.join(REPO_ROOT, p))}
        for p in (
            EV_3M, RUN_PAIR, TEST_SUMMARY, BUSINESS_MUTATION,
            ASSURANCE_MUTATION, LIMIT_REGISTRY, FROZEN_V1_SOURCE,
            OFFICIAL_CHECKER,
        )
    ]
    dep_fp = dependency_fingerprint(dependencies)

    doc = {
        "report": "DQAEIP FINAL PORTABLE EVIDENCE RELEASE — "
                  "FINAL_RESULTS (rebuilt exclusively from verified "
                  "authoritative evidence)",
        "schema": {"name": "dqaeip.final_results", "version": "2.0"},
        "release_id": "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18",
        "generated_utc": started,
        "release_identity": {
            "release_id": "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-"
                          "2026-09-18",
            "release_date": "2026-09-18",
            "supersedes": None,
            "product_name": "Data Quality Assurance & Evidence "
                            "Integrity Platform",
        },
        "git_identity": {
            "head": git(["rev-parse", "HEAD"]).stdout.strip(),
            "branch": git(["branch", "--show-current"]).stdout.strip(),
        },
        "evidence_identity": {
            "official_evidence_dir": OFFICIAL_EVIDENCE_DIR,
            "official_run_ids": run_ids,
            "official_input_sha256": fr3m["input_sha256"],
            "official_output_sha256": fr3m["output_sha256"],
            "frozen_v1_sha256": sha256_file(
                os.path.join(REPO_ROOT, FROZEN_V1_SOURCE)),
            "checker_sha256": sha256_file(
                os.path.join(REPO_ROOT, OFFICIAL_CHECKER)),
            "verifier_sha256": sha256_file(
                os.path.join(REPO_ROOT, OFFICIAL_VERIFIER)),
            "seed": fr3m["seed"],
            "portable_evidence_note": (
                "official evidence preserved byte-exact; normalized "
                "derived representations under "
                f"{NS}/portable_evidence/ (policy A)"),
        },
        "rule_identity": {
            "rule_count": len(rules),
            "rule_ids": rules,
            "frozen": True,
            "policy": "exactly 8 V1 rules, versions 1.0.0; any change "
                      "is an unauthorized rule change (STOP)",
        },
        "schema_identity": {
            "input_column_count": input_cols,
            "flag_count": len(rules),
            "output_column_count": output_cols,
            "contract": "33 in / 8 flags / 41 out",
        },
        "runs": {
            rid: {
                "rows": runs[rid].get("rows", rows_per_run),
                "comparisons": runs[rid].get("oracle", {}).get(
                    "comparisons"),
                "mismatches": runs[rid].get("oracle", {}).get(
                    "mismatches"),
                "input_sha256": runs[rid].get("input_sha256"),
                "output_sha256": runs[rid].get("output_sha256"),
            } for rid in run_ids
        },
        "verification": {
            "run_pair_verdict": rp.get("verdict"),
            "run_pair_checks_total": rp.get("checks_total"),
            "run_pair_checks_failed": rp.get("checks_failed"),
            "determinism": fr3m.get("determinism_status"),
            "byte_identical_outputs": (
                fr3m.get("determinism_status", "").startswith("PASS")),
            "runtime_safety": fr3m.get("safety_status"),
            "runtime_safety_note": (
                "PASS only when runtime-verified via audit-hook "
                "instrumentation on BOTH official runs; cooperative "
                "Python instrumentation, NOT kernel-level sandboxing"),
            "sp1_isolation": fr3m.get("sp1_isolation_status"),
            "test_all_green": bool(
                ts.get("all_green")
                and ts.get("failed") == 0 and ts.get("errors") == 0),
            "test_source": TEST_SUMMARY,
            "evidence_mutation_matrix_outcome": emm.get("outcome"),
        },
        "test_identity": {
            "collected": ts.get("collected"),
            "passed": ts.get("passed"),
            "failed": ts.get("failed"),
            "skipped": ts.get("skipped"),
            "errors": ts.get("errors"),
            "duration_seconds": ts.get("duration_seconds"),
        },
        "assurance": {
            "business_mutation_detected": bm.get(
                "mutants_detected", bm.get("scenarios_detected")),
            "business_mutation_total": bm.get(
                "mutants_total", bm.get("scenarios_total")),
            "false_pass_scenarios_rejected": am.get(
                "scenarios_detected",
                am.get("false_pass_scenarios_rejected")),
            "false_pass_scenarios_total": am.get(
                "scenarios_total",
                am.get("false_pass_scenarios_total")),
            "evidence_mutations_rejected": emm.get("outcome") and sum(
                1 for m in emm.get("mutations", [])
                if m.get("rejected")),
            "evidence_mutations_total": emm.get("mutation_count"),
        },
        "limitations": lr.get("limitations") if isinstance(
            lr.get("limitations"), list) else [
            "limitation registry unreadable — NOT VERIFIED"],
        "verification_state": None,  # derived below (never hand-set)
        "derived_values": {
            "run_count": len(run_ids),
            "rows_per_run": rows_per_run,
            "comparisons_per_run": comparisons_per_run[0]
            if len(set(comparisons_per_run)) == 1 else None,
            "combined_comparisons": comparisons_combined,
            "combined_mismatches": mismatches_combined,
            "rule_count": len(rules),
            "input_column_count": input_cols,
            "output_column_count": output_cols,
            "input_sha256": fr3m["input_sha256"],
            "output_sha256": fr3m["output_sha256"],
            "frozen_v1_sha256": sha256_file(
                os.path.join(REPO_ROOT, FROZEN_V1_SOURCE)),
            "checker_sha256": sha256_file(
                os.path.join(REPO_ROOT, OFFICIAL_CHECKER)),
        },
        "dependency_fingerprint": dep_fp,
        "dependencies": dependencies,
        "generation_mode": (
            "two-phase: staging -> verify -> promote; this document was "
            "promoted only after the schema gate passed"),
    }

    doc["verification_state"] = _derive_verdict(doc)
    return doc


def _derive_verdict(doc: dict) -> str:
    """Mechanical derivation of the final verification state."""
    reasons_not_verified = []
    reasons_fail = []
    v = doc["verification"]
    dv = doc["derived_values"]
    if v.get("run_pair_verdict") != "PASS":
        reasons_fail.append("run-pair verification is not PASS")
    if v.get("byte_identical_outputs") is not True:
        reasons_fail.append("official outputs are not byte-identical")
    if v.get("runtime_safety") != "PASS":
        reasons_not_verified.append(
            "runtime safety not PASS (cooperative instrumentation only)")
    if v.get("test_all_green") is not True:
        reasons_fail.append("test suite is not green")
    if dv.get("combined_mismatches") != 0:
        reasons_fail.append("oracle mismatches present")
    if dv.get("run_count") != 2:
        reasons_fail.append("official run count is not exactly 2")
    if reasons_fail:
        return "FAIL"
    if reasons_not_verified or doc.get("limitations"):
        return "PASS_WITH_DOCUMENTED_LIMITATIONS"
    return "PASS"


def verify(doc: dict) -> list:
    """Schema validation (anchor-aware) + cross-checks."""
    problems = []
    status, schema_problems = validate_schema_identity(doc)
    if status != "KNOWN":
        problems.append(f"schema identity {status}: "
                        f"{schema_problems[:3]}")
    fr3m = load(EV_3M)
    if doc["derived_values"]["combined_comparisons"] != fr3m.get(
            "oracle_comparisons"):
        problems.append("combined comparisons differ from official record")
    if doc["derived_values"]["rows_per_run"] != fr3m.get("rows"):
        problems.append("rows per run differ from official record")
    if doc["evidence_identity"]["official_input_sha256"] != (
            OFFICIAL_INPUT_SHA256):
        problems.append("input SHA anchor mismatch")
    if doc["evidence_identity"]["official_output_sha256"] != (
            OFFICIAL_OUTPUT_SHA256):
        problems.append("output SHA anchor mismatch")
    if doc["evidence_identity"]["frozen_v1_sha256"] != (
            FROZEN_V1_EXPECTED_SHA256):
        problems.append("frozen V1 anchor mismatch")
    if doc["derived_values"]["combined_comparisons"] != 51200000:
        problems.append("51.2M combined comparisons anchor violated")
    if doc["derived_values"]["combined_mismatches"] != 0:
        problems.append("zero mismatch anchor violated")
    if doc["derived_values"]["run_count"] != 2:
        problems.append("run count must be exactly 2 (no Run 3)")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Two-phase portable FINAL_RESULTS rebuild "
                    "(staging -> verify -> promote)")
    parser.add_argument("--promote", action="store_true")
    args = parser.parse_args(argv)

    os.makedirs(os.path.dirname(STAGING_PATH), exist_ok=True)

    try:
        doc = derive()
    except Exception as exc:  # noqa: BLE001 — record and stop
        _record_failure(f"derivation failed: {exc}")
        print(f"REBUILD FAILED at derivation: {exc}")
        return 2

    with open(STAGING_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"staged: {os.path.relpath(STAGING_PATH, REPO_ROOT)}")

    problems = verify(doc)
    if problems:
        _record_failure("schema gate / cross-checks failed", problems)
        print(f"VERIFY FAILED ({len(problems)} problems) — staged "
              f"document retained for audit; nothing promoted:")
        for p in problems[:20]:
            print(f"  - {p}")
        return 3

    print(f"verify: schema gate PASS ({len(problems)} problems)")
    doc["verification_state"] = _derive_verdict(doc)
    with open(STAGING_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")

    if not args.promote:
        print("promotion deferred (run with --promote)")
        return 0

    os.makedirs(os.path.dirname(CURRENT_PATH), exist_ok=True)
    if os.path.exists(CURRENT_PATH):
        superseded = CURRENT_PATH + ".superseded"
        os.replace(CURRENT_PATH, superseded)
        print(f"previous current retained as: "
              f"{os.path.relpath(superseded, REPO_ROOT)}")
    os.replace(STAGING_PATH, CURRENT_PATH)
    print(f"PROMOTED: {os.path.relpath(CURRENT_PATH, REPO_ROOT)}")
    print(f"  verification_state: {doc['verification_state']}")
    print(f"  dependency fingerprint: {doc['dependency_fingerprint']}")
    return 0


def _record_failure(reason: str, problems=None):
    os.makedirs(os.path.dirname(FAILURE_LOG), exist_ok=True)
    with open(FAILURE_LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ')} {reason}\n")
        for p in (problems or []):
            f.write(f"  - {p}\n")


if __name__ == "__main__":
    sys.exit(main())
