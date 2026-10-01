#!/usr/bin/env python3
"""DQAEIP FINAL UPDATE 2026-09-17 — FINAL_RESULTS two-phase rebuild
(task-book sections 6, 8, 9).

SAFE REBUILD discipline (never DELETE -> REBUILD):

    AUTHORITATIVE -> STAGING -> VERIFY -> PROMOTE -> CURRENT

Phase 1 (build):   derive FINAL_RESULTS_UPDATE-2026-09-17.json under
                   evidence/FINAL_UPDATE_2026-09-17/staging/ EXCLUSIVELY
                   from verified authoritative evidence (official 3M
                   run pair, run-pair verification, live registry/
                   contracts imports, test summary, limitation
                   registry). No value is hand-entered; no previous
                   FINAL_RESULTS is copied.

Phase 2 (verify):  run the strict section-9 schema gate plus cross-
                   checks against the authoritative sources. Any
                   problem aborts before promotion (old evidence
                   retained, staging retained, failure recorded).

Phase 3 (promote): atomically move the verified document to
                   final_results/FINAL_RESULTS_UPDATE-2026-09-17.json.

If the rebuild fails at any point, the old evidence is retained, the
staging area is retained, the failure is recorded, and the tool stops.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


def set_repo_root(root):
    """Override the working root (isolated recovery tests only)."""
    global REPO_ROOT, STAGING_PATH, CURRENT_PATH, FAILURE_LOG
    REPO_ROOT = root
    STAGING_PATH = os.path.join(REPO_ROOT, NS, "staging",
                                "FINAL_RESULTS_UPDATE-2026-09-17.json")
    CURRENT_PATH = os.path.join(REPO_ROOT, NS, "final_results",
                                "FINAL_RESULTS_UPDATE-2026-09-17.json")
    FAILURE_LOG = os.path.join(REPO_ROOT, NS, "staging",
                               "rebuild_failure.log")

from data_quality_platform.assurance.integrity import (  # noqa: E402
    OFFICIAL_CHECKER, OFFICIAL_EVIDENCE_DIR, OFFICIAL_INPUT_SHA256,
    OFFICIAL_OUTPUT_SHA256, OFFICIAL_VERIFIER, UPDATE_ID,
    FROZEN_V1_EXPECTED_SHA256, FROZEN_V1_SOURCE,
    dependency_fingerprint, schema_gate_final_results_update,
    sha256_file)

NS = "evidence/FINAL_UPDATE_2026-09-17"
STAGING_PATH = os.path.join(REPO_ROOT, NS, "staging",
                           "FINAL_RESULTS_UPDATE-2026-09-17.json")
CURRENT_PATH = os.path.join(REPO_ROOT, NS, "final_results",
                            "FINAL_RESULTS_UPDATE-2026-09-17.json")
FAILURE_LOG = os.path.join(REPO_ROOT, NS, "staging",
                           "rebuild_failure.log")

EV_3M = f"{OFFICIAL_EVIDENCE_DIR}/FINAL_RESULTS.json"
RUN_PAIR = "evidence/rebuild_verification/run_pair_verification.json"
TEST_SUMMARY = "evidence/rebuild_verification/test_summary.json"
BUSINESS_MUTATION = "evidence/mutation_testing/mutation_results.json"
ASSURANCE_MUTATION = "evidence/release/assurance_mutation.json"
LIMIT_REGISTRY = "evidence/release/limitation_registry.json"


def git(args):
    return subprocess.run(["git", "-C", REPO_ROOT] + args,
                          capture_output=True, text=True, check=False)


def load(rel):
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def derive() -> dict:
    """Derive the FINAL_RESULTS_UPDATE document from authoritative
    evidence ONLY (no copy of previous FINAL_RESULTS, no manual
    metrics)."""
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # ---- authoritative: official 3M run pair --------------------------
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

    # ---- authoritative: live rule + schema identity --------------------
    from data_quality_platform.rules.registry import RuleRegistry
    registry = RuleRegistry.create_default()
    rules = sorted(r.rule_id for r in registry.get_all_rules())
    from data_quality_platform.contracts import (
        SOURCE_COLUMNS, TOTAL_OUTPUT_COLUMNS)
    input_cols = len(SOURCE_COLUMNS)
    output_cols = TOTAL_OUTPUT_COLUMNS

    # ---- verified: run-pair verification --------------------------------
    rp = load(RUN_PAIR)

    # ---- verified: test identity (fresh run by the caller) -------------
    ts = load(TEST_SUMMARY)

    # ---- verified: mutation assurance ------------------------------------
    bm = load(BUSINESS_MUTATION)
    am = load(ASSURANCE_MUTATION)

    # ---- verified: limitation registry -----------------------------------
    lr = load(LIMIT_REGISTRY)

    # ---- dependency identity (section 10/11 fingerprint) ----------------
    dependencies = [
        {"path": EV_3M, "sha256": sha256_file(
            os.path.join(REPO_ROOT, EV_3M))},
        {"path": RUN_PAIR, "sha256": sha256_file(
            os.path.join(REPO_ROOT, RUN_PAIR))},
        {"path": TEST_SUMMARY, "sha256": sha256_file(
            os.path.join(REPO_ROOT, TEST_SUMMARY))},
        {"path": BUSINESS_MUTATION, "sha256": sha256_file(
            os.path.join(REPO_ROOT, BUSINESS_MUTATION))},
        {"path": ASSURANCE_MUTATION, "sha256": sha256_file(
            os.path.join(REPO_ROOT, ASSURANCE_MUTATION))},
        {"path": LIMIT_REGISTRY, "sha256": sha256_file(
            os.path.join(REPO_ROOT, LIMIT_REGISTRY))},
        {"path": FROZEN_V1_SOURCE, "sha256": sha256_file(
            os.path.join(REPO_ROOT, FROZEN_V1_SOURCE))},
        {"path": OFFICIAL_CHECKER, "sha256": sha256_file(
            os.path.join(REPO_ROOT, OFFICIAL_CHECKER))},
    ]
    dep_fp = dependency_fingerprint(dependencies)

    doc = {
        "report": "DQAEIP FINAL UPDATE — FINAL_RESULTS_UPDATE "
                  "(rebuilt exclusively from verified authoritative "
                  "evidence)",
        "update_id": UPDATE_ID,
        "generated_utc": started,
        "release_identity": {
            "release_id": "DQAEIP-FINAL-UPDATE-2026-09-17",
            "release_date": "2026-09-17",
            "supersedes": "DQAEIP-Assurance-Rebuild-Release-2026-09-17",
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
                fr3m.get("determinism_status", "").startswith(
                    "PASS")),
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
            "promoted only after the section-9 schema gate passed"),
    }

    # mechanical verdict derivation (never hand-set)
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
    """Section-9 schema gate + cross-checks against sources."""
    problems = schema_gate_final_results_update(doc)
    # cross-check: derived values must equal authoritative records
    fr3m = load(EV_3M)
    if doc["derived_values"]["combined_comparisons"] != fr3m.get(
            "oracle_comparisons"):
        problems.append("combined comparisons differ from official record")
    if doc["derived_values"]["rows_per_run"] != fr3m.get("rows"):
        problems.append("rows per run differ from official record")
    # cross-check: input/output anchors
    if doc["evidence_identity"]["official_input_sha256"] != (
            OFFICIAL_INPUT_SHA256):
        problems.append("input SHA anchor mismatch")
    if doc["evidence_identity"]["official_output_sha256"] != (
            OFFICIAL_OUTPUT_SHA256):
        problems.append("output SHA anchor mismatch")
    if doc["evidence_identity"]["frozen_v1_sha256"] != (
            FROZEN_V1_EXPECTED_SHA256):
        problems.append("frozen V1 anchor mismatch")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Two-phase FINAL_RESULTS rebuild (staging -> "
                    "verify -> promote)")
    parser.add_argument("--promote", action="store_true",
                        help="promote the staged document after "
                             "verification passes")
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
        _record_failure("schema gate / cross-checks failed",
                        problems)
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
        # promote = supersede; keep the previous current as a dated
        # forensic record rather than silently destroying it
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
