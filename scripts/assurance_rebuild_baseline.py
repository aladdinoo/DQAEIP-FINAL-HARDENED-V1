#!/usr/bin/env python3
"""DQAEIP ZERO-ASSUMPTION REBUILD — Phase 0 forensic baseline (read-only).

Captured BEFORE any rebuild modification, from the ACTUAL filesystem and
git state (never from README, reports, or prior agent claims):

    git identity (branch / HEAD / origin / ahead-behind / content-clean /
                 tree hash / last commit timestamp)
    full tracked-tree SHA-256 inventory (every tracked file)
    tracked-tree concatenation hash (deterministic identity)
    V1 rule inventory (imported from the ACTUAL registry source)
    frozen V1 source hashes (12 protected production files)
    key release-facing artifact identities
    evidence directory inventory
    current release identity
    environment identity

Writes (immutable — the writer refuses to overwrite an existing
baseline):

    evidence/assurance_rebuild_baseline/assurance_rebuild_baseline.json
    evidence/assurance_rebuild_baseline/tracked_tree_manifest.json
    evidence/assurance_rebuild_baseline/v1_rule_inventory.json
    evidence/assurance_rebuild_baseline/environment_fingerprint.json

All recorded paths are repository-relative. No machine-local absolute
paths, usernames, or hostnames are persisted. The baseline NEVER
mutates protected evidence: it only reads.
"""

import hashlib
import json
import os
import platform
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE_DIR = os.path.join(REPO_ROOT, "evidence", "assurance_rebuild_baseline")

# Frozen business-semantic core (must remain byte-identical through the
# rebuild; any change is an unauthorized rule change -> report, never
# silently repair).
FROZEN_PRODUCTION_FILES = [
    "data_quality_platform/rules/v1_rules.py",
    "data_quality_platform/rules/registry.py",
    "data_quality_platform/rules/base.py",
    "data_quality_platform/contracts.py",
    "data_quality_platform/validation/engine.py",
    "data_quality_platform/generation/synthetic.py",
    "data_quality_platform/lineage/recorder.py",
    "data_quality_platform/evidence/manifests.py",
    "data_quality_platform/audit/trail.py",
    "data_quality_platform/monitoring/quality.py",
    "data_quality_platform/alerting/alerts.py",
    "runner/cli.py",
]

# Canonical release-facing artifacts anchoring the rebuild.
KEY_RELEASE_ARTIFACTS = [
    "README.md",
    "RELEASE_NOTES.md",
    "DELIVERY_MANIFEST.json",
    "FINAL_RESULTS.json",
    "final_result.json",
    "release_manifest.json",
    "evidence/final_3m_validation_2026-09-15/FINAL_RESULTS.json",
    "evidence/final_3m_validation_2026-09-15/pass1_engine/manifest.json",
    "evidence/final_3m_validation_2026-09-15/pass1_engine/evidence_root.json",
    "evidence/final_3m_validation_2026-09-15/pass2_engine/manifest.json",
    "evidence/final_3m_validation_2026-09-15/pass2_engine/evidence_root.json",
    "evidence/release_gate/final_release_gate.json",
    "evidence/release/release_evidence_model.json",
    "evidence/release/claim_provenance.json",
    "evidence/release/release_artifact_manifest.json",
    "evidence/release/reproducibility_manifest.json",
    "evidence/release/observability_status.json",
    "evidence/release/readme_consistency.json",
    "evidence/release/security_release_report.json",
    "evidence/assurance_rebaseline_2026-09-17/release_zip_record.json",
    "evidence/mutation_testing/mutation_results.json",
    "evidence/rebuild_verification/test_summary.json",
]

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


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(args):
    return subprocess.run(
        ["git", "-C", REPO_ROOT] + args,
        capture_output=True, text=True, check=False,
    )


def to_rel(path):
    return os.path.relpath(os.path.abspath(path), REPO_ROOT).replace(os.sep, "/")


def main():
    manifest_path = os.path.join(
        BASELINE_DIR, "assurance_rebuild_baseline.json")
    if os.path.exists(manifest_path):
        print(f"REFUSING TO OVERWRITE existing baseline: {to_rel(manifest_path)}")
        return 2
    os.makedirs(BASELINE_DIR, exist_ok=True)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # ---- Git identity (actual state, not documented state) -----------
    head = git(["rev-parse", "HEAD"]).stdout.strip()
    branch = git(["branch", "--show-current"]).stdout.strip()
    origin_url = git(["remote", "get-url", "origin"]).stdout.strip()
    origin_main = git(["rev-parse", "origin/main"]).stdout.strip()
    counts = git(["rev-list", "--left-right", "--count",
                  "origin/main...HEAD"]).stdout.split()
    behind, ahead = (int(counts[0]), int(counts[1])) if len(counts) == 2 \
        else (None, None)
    # Content-level cleanliness (ignore exec-bit noise from the storage
    # layer, but RECORD the phenomenon explicitly — never hide it).
    # Tracked-tree cleanliness is judged on tracked files only; untracked
    # files created by the rebuild itself (this script) are recorded
    # separately as new work product, NOT as tree contamination.
    content_status_lines = git(["-c", "core.fileMode=false",
                                "status", "--porcelain"]).stdout.splitlines()
    tracked_content_changes = [ln for ln in content_status_lines
                               if not ln.startswith("?? ")]
    untracked_new = [ln[3:] for ln in content_status_lines
                     if ln.startswith("?? ")]
    mode_status_lines = git(["status", "--porcelain"]).stdout.splitlines()
    mode_only_changes = sum(1 for ln in mode_status_lines if ln.startswith(" M "))
    tree_hash = git(["rev-parse", "HEAD^{tree}"]).stdout.strip()
    last_commit_ts = git(["log", "-1", "--format=%cI", "HEAD"]).stdout.strip()
    last_commit_subject = git(["log", "-1", "--format=%s", "HEAD"]).stdout.strip()

    # ---- Full tracked-tree SHA-256 inventory --------------------------
    ls_files = git(["ls-files", "-z"])
    tracked = [p for p in ls_files.stdout.split("\0") if p]
    file_hashes = {}
    for rel in tracked:
        abs_p = os.path.join(REPO_ROOT, rel)
        if os.path.isfile(abs_p):
            file_hashes[rel] = sha256_file(abs_p)
    tree_concat = hashlib.sha256()
    for rel in sorted(file_hashes):
        tree_concat.update(rel.encode() + b"\x00" + file_hashes[rel].encode())

    # ---- V1 rule inventory (from the ACTUAL registry import) ----------
    sys.path.insert(0, REPO_ROOT)
    from data_quality_platform.rules.registry import RuleRegistry
    registry = RuleRegistry.create_default()
    rule_inventory = {
        "inventory_version": "2.0.0",
        "generated_utc": started,
        "source_of_truth": (
            "data_quality_platform/rules/registry.py + v1_rules.py "
            "(actual import, not documentation)"),
        "frozen_contract_statement": (
            "The production registry MUST remain exactly the approved V1 "
            "registry: 8 rules, versions 1.0.0, predicates unchanged."),
        "required_rule_ids_in_order": REQUIRED_V1_RULE_IDS,
        "rules": [],
    }
    for rid in REQUIRED_V1_RULE_IDS:
        rule = registry.get(rid)
        rule_inventory["rules"].append({
            "rule_id": rule.rule_id,
            "rule_version": rule.rule_version,
            "rule_hash": rule.hash,
            "registry_order_index": REQUIRED_V1_RULE_IDS.index(rid),
        })
    registry_ids = sorted(r.rule_id for r in registry.get_all_rules())
    rule_inventory["registry_rule_ids_actual"] = registry_ids
    rule_inventory["registry_exactly_matches_required"] = (
        registry_ids == sorted(REQUIRED_V1_RULE_IDS))
    rule_inventory["registry_rule_count"] = len(registry_ids)
    # Frozen V1 source hash (authoritative identity anchor).
    v1_source = os.path.join(
        REPO_ROOT, "data_quality_platform/rules/v1_rules.py")
    rule_inventory["frozen_v1_source_sha256"] = sha256_file(v1_source)
    rule_inventory["frozen_v1_source_expected_sha256"] = (
        "daef1ded54c7d3c79898a1ba253be2acd5b6120e18b16b09009fdd7be9fc2276")
    rule_inventory["frozen_v1_source_matches_expected"] = (
        rule_inventory["frozen_v1_source_sha256"]
        == rule_inventory["frozen_v1_source_expected_sha256"])

    # ---- Evidence directory inventory ---------------------------------
    evidence_dirs = {}
    ev_root = os.path.join(REPO_ROOT, "evidence")
    for entry in sorted(os.listdir(ev_root)):
        full = os.path.join(ev_root, entry)
        if os.path.isdir(full):
            n_files = sum(len(fs) for _, _, fs in os.walk(full))
            evidence_dirs[entry] = {"files": n_files}

    # ---- Key artifact hashes (release identity anchors) --------------
    key_hashes = {}
    for rel in KEY_RELEASE_ARTIFACTS:
        abs_p = os.path.join(REPO_ROOT, rel)
        key_hashes[rel] = sha256_file(abs_p) if os.path.isfile(abs_p) else None

    frozen_hashes = {}
    for rel in FROZEN_PRODUCTION_FILES:
        abs_p = os.path.join(REPO_ROOT, rel)
        frozen_hashes[rel] = sha256_file(abs_p) if os.path.isfile(abs_p) else None

    # ---- Current release identity (to be superseded by this rebuild) --
    identity = {
        "current_product_name": (
            "Data Quality Assurance & Evidence Integrity Platform"),
        "current_short_name": "DQAEIP",
        "current_release_name": (
            "DQAEIP-Enterprise-Assurance-Validation-Release-2026-09-17"),
        "python_package": "data_quality_platform",
        "rebuild_target": {
            "new_release_name": (
                "DQAEIP-Zero-Assurance-Rebuild-Release-2026-09-17"),
            "package_policy": (
                "data_quality_platform retained as compatibility package "
                "(no import changes)"),
        },
    }

    manifest = {
        "baseline_type": (
            "DQAEIP zero-assumption rebuild forensic baseline "
            "(Phase 0, pre-modification, read-only)"),
        "generated_utc": started,
        "immutability": (
            "this manifest is written once; the writer refuses to "
            "overwrite it"),
        "operating_rules_honored": [
            "zero assumptions: facts derived from actual files",
            "protected evidence not mutated during capture",
            "no Run 3 created",
            "unknowns recorded as NOT_VERIFIED, never PASS",
        ],
        "git": {
            "head": head,
            "branch": branch,
            "origin_url": origin_url,
            "origin_main": origin_main,
            "ahead": ahead,
            "behind": behind,
            "tree_hash": tree_hash,
            "last_commit_timestamp": last_commit_ts,
            "last_commit_subject": last_commit_subject,
            "tracked_content_clean": len(tracked_content_changes) == 0,
            "tracked_content_changes": tracked_content_changes,
            "untracked_new_work_product": untracked_new,
            "content_clean_note": (
                "tracked-tree content cleanliness with core.fileMode=false; "
                "the storage layer may flip executable bits (644->755) on "
                "tracked files between sessions — zero content difference; "
                "untracked entries are new rebuild work product (this "
                "baseline script), not pre-existing tree state"),
            "mode_only_changes_recorded": mode_only_changes,
        },
        "tracked_files_total": len(tracked),
        "tracked_files_hashed": len(file_hashes),
        "tracked_tree_concat_sha256": tree_concat.hexdigest(),
        "frozen_production_files": frozen_hashes,
        "key_release_artifacts": key_hashes,
        "evidence_directory_inventory": evidence_dirs,
        "identity": identity,
        "environment": {
            "python": platform.python_version(),
            "os": platform.system().lower(),
            "arch": platform.machine(),
        },
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")

    with open(os.path.join(BASELINE_DIR, "tracked_tree_manifest.json"),
              "w", encoding="utf-8") as f:
        json.dump({
            "manifest_type": "tracked-tree SHA-256 inventory",
            "generated_utc": started,
            "git_head": head,
            "tracked_files_total": len(file_hashes),
            "tracked_tree_concat_sha256": tree_concat.hexdigest(),
            "files": file_hashes,
        }, f, indent=0, sort_keys=True)
        f.write("\n")

    with open(os.path.join(BASELINE_DIR, "v1_rule_inventory.json"),
              "w", encoding="utf-8") as f:
        json.dump(rule_inventory, f, indent=2, sort_keys=True)
        f.write("\n")

    with open(os.path.join(
            BASELINE_DIR, "environment_fingerprint.json"),
            "w", encoding="utf-8") as f:
        json.dump({
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "os": platform.system().lower(),
            "os_release": platform.release(),
            "arch": platform.machine(),
            "locale": os.environ.get("LANG", ""),
            "timezone_note": "all timestamps in evidence are UTC",
            "captured_utc": started,
        }, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"BASELINE WRITTEN to {to_rel(BASELINE_DIR)}")
    print(f"  HEAD: {head} (tree {tree_hash[:12]}...)")
    print(f"  tracked files hashed: {len(file_hashes)}")
    print(f"  tracked-tree concat SHA-256: {tree_concat.hexdigest()}")
    print(f"  registry exactly V1 8-rules: "
          f"{rule_inventory['registry_exactly_matches_required']}")
    print(f"  frozen V1 source matches expected: "
          f"{rule_inventory['frozen_v1_source_matches_expected']}")
    print(f"  tracked content clean: {manifest["git"]["tracked_content_clean"]} "
          f"(mode-only flips: {mode_only_changes})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
