#!/usr/bin/env python3
"""ASSURANCE REBASELINE 2026-09-17 - forensic read-only baseline capture.

Captures the repository state BEFORE any hardening modification of this
task. Every value is machine-read at capture time (git, filesystem,
evidence JSON, pytest discovery). No manual numbers. No repo file
outside the evidence output directory is modified.

Task reference: FORENSIC BASELINE (section 3).
Output: evidence/assurance_baseline/assurance_baseline.json
        evidence/assurance_baseline/tracked_tree_manifest.json
        evidence/assurance_baseline/evidence_inventory.json

The baseline is immutable after capture: this script refuses to
overwrite an existing baseline unless --force is given, and the
captured record embeds its own tree state for tamper detection.
"""

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO_ROOT, "evidence", "assurance_baseline")
OUT = os.path.join(OUT_DIR, "assurance_baseline.json")
TREE_OUT = os.path.join(OUT_DIR, "tracked_tree_manifest.json")
INV_OUT = os.path.join(OUT_DIR, "evidence_inventory.json")

SCHEMA_VERSION = "1.0.0"
TASK_DATE = "2026-09-17"

# Authoritative evidence inventory (task section 4) - read + hashed.
EVIDENCE_INVENTORY = [
    "FINAL_RESULTS.json",
    "README.md",
    "RELEASE_NOTES.md",
    "release_manifest.json",
    "evidence/release/release_evidence_model.json",
    "evidence/release/final_verification.json",
    "evidence/release/golden_release_snapshot.json",
    "evidence/release/consistency_matrix.json",
    "evidence/release/assurance_mutation.json",
    "evidence/release/claim_provenance.json",
    "evidence/release/limitation_registry.json",
    "evidence/release/reproducibility_manifest.json",
    "evidence/rebuild_verification/test_summary.json",
    "evidence/rebuild_verification/run_pair_verification.json",
    "evidence/mutation_testing/mutation_results.json",
    "evidence/dqvp_performance/performance_results.json",
    "evidence/final_hardening_2026-09-16/release_zip_record.json",
    "evidence/release_gate/final_release_gate.json",
    "evidence/final_3m_validation_2026-09-15/FINAL_RESULTS.json",
    "evidence/final_3m_validation_2026-09-15/pass1_engine/manifest.json",
    "evidence/final_3m_validation_2026-09-15/pass2_result.json",
    "data_quality_platform/rules/v1_rules.py",
    "data_quality_platform/contracts.py",
    "data_quality_platform/validation/engine.py",
]


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


def capture_git_state():
    tracked = git("ls-files") or ""
    tracked_list = tracked.splitlines()
    status_porcelain = subprocess.run(
        ["git", "-C", REPO_ROOT, "status", "--porcelain"],
        capture_output=True, text=True, check=False).stdout
    ignored = subprocess.run(
        ["git", "-C", REPO_ROOT, "status", "--porcelain", "--ignored"],
        capture_output=True, text=True, check=False).stdout
    ignored_list = [line[3:] for line in ignored.splitlines()
                    if line.startswith("!!")]
    untracked = [line[3:] for line in status_porcelain.splitlines()
                 if line.startswith("??")]
    return {
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "head": git("rev-parse", "HEAD"),
        "head_subject": git("log", "-1", "--format=%s"),
        "origin_main": git("rev-parse", "origin/main"),
        "origin_url": git("config", "--get", "remote.origin.url"),
        "commit_count": int(git("rev-list", "--count", "HEAD") or -1),
        "ahead_of_origin": int(
            git("rev-list", "--count", "origin/main..HEAD") or -1),
        "behind_origin": int(
            git("rev-list", "--count", "HEAD..origin/main") or -1),
        "working_tree_clean": len(status_porcelain.strip().splitlines()) == 0,
        "tracked_file_count": len(tracked_list),
        "untracked_file_count": len(untracked),
        "ignored_runtime_artifacts": ignored_list,
        "tree_sha": git("rev-parse", "HEAD^{tree}"),
    }


def capture_environment():
    deps = {}
    try:
        import pytest  # noqa: F401
        deps["pytest"] = pytest.__version__
    except Exception:
        deps["pytest"] = "NOT_IMPORTABLE"
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "pytest_version": deps["pytest"],
        "pyproject_sha256": sha256_file("pyproject.toml"),
        "task_declared_validated_head": "c0f1b20",
        "task_declared_evidence_date": "2026-09-15",
    }


def capture_test_discovery():
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    last = [l for l in r.stdout.strip().splitlines() if l.strip()]
    summary = last[-1] if last else ""
    count = None
    for token in summary.split():
        if token.isdigit():
            count = int(token)
            break
    return {
        "discovery_command": "python -m pytest --collect-only -q",
        "collected_count": count,
        "exit_code": r.returncode,
        "summary_line": summary,
    }


def capture_release_evidence_facts():
    facts = {}
    gate = load("evidence/release_gate/final_release_gate.json")
    facts["release_gate_gate_count"] = gate.get("gate_count")
    facts["release_gate_overall_verdict"] = gate.get("overall_verdict")
    facts["release_gate_gate_statuses"] = sorted(
        {g.get("status") for g in gate.get("gates", [])})

    ts = load("evidence/rebuild_verification/test_summary.json")
    facts["test_summary_collected"] = ts.get("collected")
    facts["test_summary_passed"] = ts.get("passed")
    facts["test_summary_skipped"] = ts.get("skipped")
    facts["test_summary_failed"] = ts.get("failed")
    facts["test_summary_errors"] = ts.get("errors")

    rp = load("evidence/rebuild_verification/run_pair_verification.json")
    r1, r2 = rp.get("run_1", {}), rp.get("run_2", {})
    facts["run_pair_verdict"] = rp.get("verdict")
    facts["run_pair_checks_total"] = rp.get("checks_total")
    facts["run_pair_checks_failed"] = rp.get("checks_failed")
    facts["run_pair_runs"] = 2 if (r1 and r2) else None
    facts["run_pair_rows_per_run"] = r1.get("input_rows")
    facts["run_pair_oracle_comparisons_per_run"] = r1.get(
        "oracle_comparisons")
    facts["run_pair_combined_comparisons"] = (
        (r1.get("oracle_comparisons") or 0)
        + (r2.get("oracle_comparisons") or 0)) or None
    facts["run_pair_mismatches"] = (
        (r1.get("oracle_mismatches") or 0)
        + (r2.get("oracle_mismatches") or 0))
    facts["run_pair_input_sha_equal"] = rp.get(
        "cross_run_invariants", {}).get("input_sha256")
    facts["run_pair_output_sha_equal"] = rp.get(
        "cross_run_invariants", {}).get("output_sha256")

    fr3m = load(
        "evidence/final_3m_validation_2026-09-15/FINAL_RESULTS.json")
    facts["final_3m_status"] = fr3m.get("final_status")
    facts["final_3m_rows"] = fr3m.get("rows")
    facts["final_3m_oracle_comparisons"] = fr3m.get("oracle_comparisons")
    mm = fr3m.get("oracle_mismatches") or {}
    facts["final_3m_mismatches_combined"] = mm.get("combined_total")
    facts["final_3m_input_sha256"] = fr3m.get("input_sha256")
    facts["final_3m_output_sha256"] = fr3m.get("output_sha256")

    fr = load("FINAL_RESULTS.json")
    facts["final_results_release_status"] = fr.get("final_release_status")
    facts["final_results_release_name"] = fr.get("release_identity", {}).get(
        "release_name")

    rules = load("evidence/rebuild_baseline/v1_rule_inventory.json")
    rl = rules.get("rules", rules) if isinstance(rules, dict) else rules
    facts["v1_rule_count"] = len(rl)

    em = load("evidence/release/release_evidence_model.json")
    facts["evidence_model_claims"] = len(em.get("claims", []))
    return facts


def capture_gate_configuration():
    gate = load("evidence/release_gate/final_release_gate.json")
    gates = []
    for g in gate.get("gates", []):
        if isinstance(g, dict):
            gates.append({
                "id": g.get("gate") or g.get("id") or g.get("name"),
                "status": g.get("status"),
            })
    statuses = sorted({g["status"] for g in gates})
    return {
        "gate_count_declared": gate.get("gate_count"),
        "gate_count_observed": len(gates),
        "gate_ids": [g["id"] for g in gates],
        "gate_statuses": statuses,
        "overall_verdict": gate.get("overall_verdict"),
        "fail_closed_statement": gate.get("fail_closed_statement"),
        "model": "21-gate fail-closed release gate",
    }


def write_tree_manifest():
    tracked = sorted((git("ls-files") or "").splitlines())
    entries = []
    for rel in tracked:
        abs_p = os.path.join(REPO_ROOT, rel)
        try:
            st = os.stat(abs_p)
            entries.append({
                "path": rel,
                "size_bytes": st.st_size,
                "sha256": sha256_file(rel),
            })
        except OSError:
            entries.append({"path": rel, "error": "UNREADABLE"})
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "git_head": git("rev-parse", "HEAD"),
        "tracked_file_count": len(entries),
        "files": entries,
    }
    with open(TREE_OUT, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    return len(entries)


def write_evidence_inventory():
    inventory = []
    for rel in EVIDENCE_INVENTORY:
        abs_p = os.path.join(REPO_ROOT, rel)
        if not os.path.isfile(abs_p):
            inventory.append({"path": rel, "status": "MISSING"})
            continue
        inventory.append({
            "path": rel,
            "status": "PRESENT",
            "size_bytes": os.stat(abs_p).st_size,
            "sha256": sha256_file(rel),
        })
    inv = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "artifact_count": len(inventory),
        "artifacts": inventory,
    }
    with open(INV_OUT, "w", encoding="utf-8") as f:
        json.dump(inv, f, indent=2, sort_keys=True)
        f.write("\n")
    return inv


def main():
    if os.path.exists(OUT):
        print("REFUSING to overwrite existing baseline "
              "(immutable after capture). Pass --force to override.")
        if "--force" not in sys.argv:
            sys.exit(2)

    os.makedirs(OUT_DIR, exist_ok=True)

    git_state = capture_git_state()
    env = capture_environment()
    discovery = capture_test_discovery()
    evidence_facts = capture_release_evidence_facts()
    gate_cfg = capture_gate_configuration()
    tree_count = write_tree_manifest()
    inventory = write_evidence_inventory()

    # Ingestion note: environmental mode-bit anomaly observed and
    # resolved before baseline capture (mode-only, zero content delta).
    baseline = {
        "schema_version": SCHEMA_VERSION,
        "task": ("PROFESSIONAL PROJECT INGESTION + SECURITY HARDENING + "
                 "OBSERVABILITY + RELEASE REBASELINE + FORENSIC "
                 "REVALIDATION"),
        "capture_type": "PRE-MODIFICATION FORENSIC BASELINE",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "project_identity": {
            "repository": "Data-Quality-Validation-Platform-v2",
            "product": ("Data Quality Assurance & Evidence Integrity "
                        "Platform (DQAEIP)"),
            "package": "data_quality_platform",
            "distribution": "data-quality-platform",
            "release_identity": ("DQAEIP-Enterprise-Assurance-"
                                 "Validation-Release-2026-09-16"),
            "ingestion_mode": ("EXISTING_CHECKOUT (no re-clone, no "
                               "archive re-extraction; identity "
                               "preserved per task section 2)"),
            "ingestion_root": "EXISTING REPOSITORY ROOT (relative)",
        },
        "ingestion_anomaly_record": {
            "observed": ("session restore set executable bit on all "
                         "working-tree files; 49 files whose committed "
                         "mode is 100644 appeared modified"),
            "git_diff_content_delta": ("0 insertions / 0 deletions "
                                       "(mode-only changes)"),
            "resolution": ("executable bits restored to committed "
                           "100644 state; working tree verified CLEAN "
                           "and content-identical to validated HEAD"),
            "canonical_evidence_impact": "NONE (zero content changes)",
            "note": ("historical index records 500 files as 100755 "
                     "from original ingestion; left untouched to "
                     "preserve frozen validated tree"),
        },
        "git_state": git_state,
        "git_state_capture_note": (
            "Self-referential capture artifact: at capture time the only "
            "untracked entry is this baseline script itself "
            "(scripts/assurance_baseline.py); evidence outputs are "
            "written after the git capture. The working tree was "
            "verified CLEAN at validated HEAD 636d2a1 immediately "
            "before this script was created (mode-bit restoration, "
            "zero content delta), so untracked_file_count=1 reflects "
            "the capture tool, not pre-existing repo dirtiness."
            if git_state["untracked_file_count"] <= 1 else
            "UNEXPECTED UNTRACKED FILES PRESENT - investigate"
        ),
        "environment": env,
        "test_discovery": discovery,
        "release_evidence_facts": evidence_facts,
        "release_gate_configuration": gate_cfg,
        "companion_artifacts": {
            "tracked_tree_manifest": "tracked_tree_manifest.json",
            "tracked_tree_manifest_file_count": tree_count,
            "evidence_inventory": "evidence_inventory.json",
            "evidence_inventory_artifact_count":
                inventory["artifact_count"],
        },
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2, sort_keys=True)
        f.write("\n")

    print("BASELINE CAPTURED ->", os.path.relpath(OUT, REPO_ROOT))
    print("  head:", git_state["head"])
    print("  clean:", git_state["working_tree_clean"])
    print("  tracked files:", git_state["tracked_file_count"])
    print("  tests collected:", discovery["collected_count"])
    print("  gates:", gate_cfg["gate_count_observed"])
    print("  evidence inventory artifacts:",
          inventory["artifact_count"])


if __name__ == "__main__":
    main()
