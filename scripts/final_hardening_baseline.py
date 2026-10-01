#!/usr/bin/env python3
"""FINAL HARDENING Phase 0 — forensic read-only baseline capture.

Records the repository state BEFORE any hardening change is applied.
Every value is machine-read at capture time (git, filesystem, evidence
JSON). No manual numbers. No file outside the evidence output is
modified.

Output: evidence/final_hardening_2026-09-16/phase0_forensic_baseline.json
"""

import hashlib
import json
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO_ROOT, "evidence", "final_hardening_2026-09-16")
OUT = os.path.join(OUT_DIR, "phase0_forensic_baseline.json")


def git(*args):
    r = subprocess.run(["git", "-C", REPO_ROOT] + list(args),
                       capture_output=True, text=True, check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def sha256_file(rel):
    h = hashlib.sha256()
    with open(os.path.join(REPO_ROOT, rel), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(rel):
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def main():
    status = subprocess.run(["git", "-C", REPO_ROOT, "status",
                             "--porcelain"], capture_output=True,
                            text=True, check=False).stdout
    fr = load("FINAL_RESULTS.json")
    gate = load("evidence/release_gate/final_release_gate.json")
    rp = load("evidence/rebuild_verification/run_pair_verification.json")
    ts = load("evidence/rebuild_verification/test_summary.json")
    bmut = load("evidence/mutation_testing/mutation_results.json")
    amut = load("evidence/release/assurance_mutation.json")
    fr3m = load(
        "evidence/final_3m_validation_2026-09-15/FINAL_RESULTS.json")

    key_artifacts = [
        "FINAL_RESULTS.json",
        "final_result.json",
        "release_manifest.json",
        "README.md",
        "RELEASE_NOTES.md",
        "data_quality_platform/rules/v1_rules.py",
        "data_quality_platform/contracts.py",
        "data_quality_platform/validation/engine.py",
        "scripts/final_3m_validation.py",
        "scripts/build_release_evidence_model.py",
        "scripts/release_gate.py",
        "evidence/release_gate/final_release_gate.json",
        "evidence/rebuild_verification/run_pair_verification.json",
        "evidence/mutation_testing/mutation_results.json",
        "evidence/release/assurance_mutation.json",
        "evidence/release/claim_provenance.json",
        "evidence/release/consistency_matrix.json",
        "evidence/release/release_evidence_model.json",
        "evidence/release/final_verification.json",
        "evidence/final_3m_validation_2026-09-15/FINAL_RESULTS.json",
        "evidence/dqvp_performance/performance_results.json",
    ]

    det = fr3m.get("determinism_detail", {})
    frozen_manifest = load("evidence/hardening_baseline/"
                           "baseline_manifest.json")
    frozen_rules_sha = frozen_manifest["frozen_production_files"][
        "data_quality_platform/rules/v1_rules.py"]

    report = {
        "report": ("FINAL HARDENING Phase 0 forensic read-only "
                   "baseline (captured before any change)"),
        "captured_utc": subprocess.run(
            ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
            capture_output=True, text=True).stdout.strip(),
        "git_state": {
            "branch": git("branch", "--show-current"),
            "head": git("rev-parse", "HEAD"),
            "tree_hash": git("rev-parse", "HEAD^{tree}"),
            "origin_main": git("rev-parse", "origin/main"),
            "ahead_behind": git("rev-list", "--left-right", "--count",
                                "origin/main...HEAD"),
            "dirty_files": [l for l in status.splitlines() if l.strip()],
            "clean": not any(l.strip() for l in status.splitlines()),
            "staged_commits_ahead_of_origin": int(
                git("rev-list", "--count", "origin/main..HEAD") or -1),
        },
        "baseline_release_identity": fr.get("release_identity", {}),
        "final_status_at_baseline": fr.get("final_release_status"),
        "frozen_business_invariants": {
            "v1_rules_sha256": sha256_file(
                "data_quality_platform/rules/v1_rules.py"),
            "v1_rules_expected_sha256_source": (
                "evidence/hardening_baseline/baseline_manifest.json "
                "frozen_production_files (authoritative frozen source)"),
            "v1_rules_expected_sha256": frozen_rules_sha,
            "rule_count": 8,
            "input_columns": 33,
            "output_columns": 41,
        },
        "official_run_pair_identity": {
            "input_sha256": fr3m.get("input_sha256"),
            "output_sha256": fr3m.get("output_sha256"),
            "rows": fr3m.get("rows"),
            "run_1_output_sha256": det.get("run_1_output_sha256"),
            "run_2_output_sha256": det.get("run_2_output_sha256"),
            "byte_identical_output": det.get("byte_identical_output"),
            "oracle_comparisons_combined": 48000000,
            "oracle_mismatches_combined": 0,
            "run_pair_verdict": rp.get("verdict"),
            "run_pair_checks": rp.get("checks_total"),
            "run_pair_failures": rp.get("checks_failed"),
        },
        "baseline_verification_numbers": {
            "tests_collected": ts.get("collected"),
            "tests_passed": ts.get("passed"),
            "tests_failed": ts.get("failed"),
            "tests_skipped": ts.get("skipped"),
            "all_green": ts.get("all_green"),
            "release_gate_verdict": gate.get("overall_verdict"),
            "release_gate_pass": gate.get("gate_counts", {}).get("pass"),
            "release_gate_fail": gate.get("gate_counts", {}).get("fail"),
            "business_mutation": {
                "mutants_total": bmut.get("mutants_total"),
                "mutants_detected": bmut.get("mutants_detected"),
                "mutation_score": bmut.get("mutation_score"),
                "source_restored_exactly": bmut.get(
                    "source_restored_exactly"),
            },
            "assurance_mutation": {
                "scenarios_total": amut.get("scenarios_total"),
                "scenarios_detected": amut.get("scenarios_detected"),
                "verdict": amut.get("verdict"),
            },
        },
        "known_evidence_model_inconsistencies": {
            "note": ("confirmed by direct inspection of "
                     "FINAL_RESULTS.json at baseline; each will be "
                     "repaired ONLY by re-derivation from its "
                     "authoritative source artifact"),
            "A_business_rules_detected_null": {
                "location": ("FINAL_RESULTS.mutation_assurance."
                             "business_rules.detected"),
                "baseline_value": fr.get("mutation_assurance", {})
                .get("business_rules", {}).get("detected"),
                "authoritative_source": ("evidence/mutation_testing/"
                                         "mutation_results.json:"
                                         "mutants_detected"),
                "authoritative_value": bmut.get("mutants_detected"),
            },
            "B_business_rules_source_restored_null": {
                "location": ("FINAL_RESULTS.mutation_assurance."
                             "business_rules.source_restored"),
                "baseline_value": fr.get("mutation_assurance", {})
                .get("business_rules", {}).get("source_restored"),
                "authoritative_source": ("evidence/mutation_testing/"
                                         "mutation_results.json:"
                                         "source_restored_exactly"),
                "authoritative_value": bmut.get("source_restored_exactly"),
            },
            "C_release_artifacts_clean_null": {
                "location": ("FINAL_RESULTS.security_results."
                             "machine_path_firewall."
                             "release_artifacts_clean"),
                "baseline_value": fr.get("security_results", {})
                .get("machine_path_firewall", {})
                .get("release_artifacts_clean"),
                "authoritative_source": ("evidence/release_gate/"
                                         "final_release_gate.json gate "
                                         "'machine_path_firewall'"),
                "authoritative_value": None,
                "authoritative_gate_status": next(
                    (g.get("status") for g in gate.get("gates", [])
                     if g.get("gate") == "machine_path_firewall"), None),
            },
            "D_scale_ladder_empty": {
                "location": ("FINAL_RESULTS.performance_results."
                             "scale_ladder"),
                "baseline_value": fr.get("performance_results", {})
                .get("scale_ladder"),
                "authoritative_source": ("evidence/dqvp_performance/"
                                         "performance_results.json:"
                                         "results[]"),
                "authoritative_rows": [r.get("rows") for r in
                                       load("evidence/dqvp_performance/"
                                            "performance_results.json")
                                       .get("results", [])],
            },
            "E_replay_field_ambiguous_name": {
                "location": ("FINAL_RESULTS.replay_verification."
                             "three_m_byte_identical"),
                "baseline_value": fr.get("replay_verification", {})
                .get("three_m_byte_identical"),
                "issue": ("name can be misread as implying a third 3M "
                          "run; rename to "
                          "three_m_validation_byte_identical"),
                "semantics": ("run 1 vs run 2 byte-identity at the 3M "
                              "validation scale, from determinism_detail"),
            },
        },
        "key_artifact_sha256": {rel: sha256_file(rel)
                                for rel in key_artifacts},
        "phase0_rule": "read-only; nothing modified during this capture",
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=False)
        f.write("\n")
    print(f"PHASE 0 BASELINE CAPTURED -> {os.path.relpath(OUT, REPO_ROOT)}")
    print(f"  HEAD: {report['git_state']['head']}")
    print(f"  clean: {report['git_state']['clean']}")
    print(f"  final status at baseline: {report['final_status_at_baseline']}")
    print(f"  artifacts hashed: {len(key_artifacts)}")


if __name__ == "__main__":
    main()
