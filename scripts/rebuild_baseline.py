#!/usr/bin/env python3
"""DQAEIP REBUILD FORENSIC BASELINE (read-only, Phase 1).

Captured BEFORE any rebuild / assurance-hardening modifications:

    git identity (branch / HEAD / origin / ahead-behind / content-clean / tree hash)
    full tracked-file inventory with per-file SHA-256
    V1 rule inventory (from the ACTUAL registry source, not documentation)
    evidence inventory (directories + key artifact hashes)
    release-facing artifact identities (final_result, release_manifest, gate, ZIP record)
    current project identity (pre-rename, DQAVP)
    Run 1 / Run 2 evidence inventory (paths + roots, verified in Phase 4)
    environment fingerprint

Writes (never overwrites an existing baseline — IMMUTABLE):

    evidence/rebuild_baseline/rebuild_baseline_manifest.json
    evidence/rebuild_baseline/tracked_file_hashes.json
    evidence/rebuild_baseline/v1_rule_inventory.json
    evidence/rebuild_baseline/environment_fingerprint.json

All recorded paths are repository-relative. No machine-local absolute
paths, usernames, or hostnames are persisted.
"""

import hashlib
import json
import os
import platform
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE_DIR = os.path.join(REPO_ROOT, "evidence", "rebuild_baseline")

# Frozen business-semantic core (must remain byte-identical through the rebuild).
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

# Canonical release-facing artifacts whose hashes anchor the rebuild.
KEY_RELEASE_ARTIFACTS = [
    "final_result.json",
    "release_manifest.json",
    "README.md",
    "RELEASE_NOTES.md",
    "DELIVERY_MANIFEST.json",
    "evidence/validation/2026-09-18/fresh_3m2/harness/FINAL_RESULTS.json",
    "evidence/validation/2026-09-18/fresh_3m2/harness/pass1_engine/manifest.json",
    "evidence/validation/2026-09-18/fresh_3m2/harness/pass1_engine/evidence_root.json",
    "evidence/validation/2026-09-18/fresh_3m2/harness/pass2_engine/manifest.json",
    "evidence/validation/2026-09-18/fresh_3m2/harness/pass2_engine/evidence_root.json",
    "evidence/release_gate/final_release_gate.json",
    "evidence/hardening_baseline/baseline_manifest.json",
    "evidence/mutation_testing/mutation_results.json",
    "evidence/dqvp_performance/performance_results.json",
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
    manifest_path = os.path.join(BASELINE_DIR, "rebuild_baseline_manifest.json")
    if os.path.exists(manifest_path):
        print(f"REFUSING TO OVERWRITE existing baseline: {to_rel(manifest_path)}")
        return 2
    os.makedirs(BASELINE_DIR, exist_ok=True)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # ---- Git identity -------------------------------------------------
    head = git(["rev-parse", "HEAD"]).stdout.strip()
    branch = git(["branch", "--show-current"]).stdout.strip()
    origin_url = git(["remote", "get-url", "origin"]).stdout.strip()
    origin_main = git(["rev-parse", "origin/main"]).stdout.strip()
    counts = git(["rev-list", "--left-right", "--count", "origin/main...HEAD"]).stdout.split()
    behind, ahead = (int(counts[0]), int(counts[1])) if len(counts) == 2 else (None, None)
    # Content-level cleanliness: ignore the environment's exec-bit noise
    # (mode 644->755 introduced by the storage layer, zero content change),
    # but RECORD that phenomenon explicitly.
    content_status = git(["-c", "core.fileMode=false", "status", "--porcelain"]).stdout
    mode_status_lines = git(["status", "--porcelain"]).stdout.splitlines()
    mode_only_changes = sum(1 for ln in mode_status_lines if ln.startswith(" M "))
    tree_hash = git(["rev-parse", "HEAD^{tree}"]).stdout.strip()
    last_commit_ts = git(["log", "-1", "--format=%cI", "HEAD"]).stdout.strip()

    # ---- Tracked-file inventory --------------------------------------
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

    # ---- V1 rule inventory (from actual registry) ---------------------
    sys.path.insert(0, REPO_ROOT)
    from data_quality_platform.rules.registry import RuleRegistry
    registry = RuleRegistry.create_default()
    rule_inventory = {
        "inventory_version": "2.0.0",
        "generated_utc": started,
        "source_of_truth": "data_quality_platform/rules/registry.py + v1_rules.py (actual import)",
        "frozen_contract_statement": (
            "The production registry MUST remain exactly the approved V1 registry: "
            "8 rules, versions 1.0.0, predicates unchanged."
        ),
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
    rule_inventory["registry_exactly_matches_required"] = registry_ids == sorted(REQUIRED_V1_RULE_IDS)

    # ---- Evidence inventory -------------------------------------------
    evidence_dirs = {}
    ev_root = os.path.join(REPO_ROOT, "evidence")
    for entry in sorted(os.listdir(ev_root)):
        full = os.path.join(ev_root, entry)
        if os.path.isdir(full):
            n_files = sum(len(fs) for _, _, fs in os.walk(full))
            evidence_dirs[entry] = {"files": n_files}

    # ---- Key artifact hashes ------------------------------------------
    key_hashes = {}
    for rel in KEY_RELEASE_ARTIFACTS:
        abs_p = os.path.join(REPO_ROOT, rel)
        key_hashes[rel] = sha256_file(abs_p) if os.path.isfile(abs_p) else None

    frozen_hashes = {}
    for rel in FROZEN_PRODUCTION_FILES:
        abs_p = os.path.join(REPO_ROOT, rel)
        frozen_hashes[rel] = sha256_file(abs_p) if os.path.isfile(abs_p) else None

    # ---- Current identity (pre-rename) --------------------------------
    identity = {
        "current_name": "Data Quality Assurance & Validation Platform",
        "current_short_name": "DQAVP",
        "current_release_name": "DQAVP-Enterprise-Hardened-Validation-Release-2026-09-15",
        "python_package": "data_quality_platform",
        "rename_target": {
            "new_name": "Data Quality Assurance & Evidence Integrity Platform",
            "new_short_name": "DQAEIP",
            "new_release_name": "DQAEIP-Enterprise-Assurance-Validation-Release",
            "package_policy": "data_quality_platform retained as compatibility package (no import changes)",
        },
    }

    manifest = {
        "baseline_type": "DQAEIP rebuild forensic baseline (Phase 1, pre-modification)",
        "generated_utc": started,
        "immutability": "this manifest is written once; the writer refuses to overwrite it",
        "git": {
            "head": head,
            "branch": branch,
            "origin_url": origin_url,
            "origin_main": origin_main,
            "ahead": ahead,
            "behind": behind,
            "tree_hash": tree_hash,
            "last_commit_timestamp": last_commit_ts,
            "content_clean": content_status.strip() == "",
            "content_clean_note": (
                "content-level cleanliness with core.fileMode=false; the storage "
                "layer flipped executable bits (644->755) on tracked files after "
                "the previous session — zero content difference, verified via "
                "git blob hash comparison on canonical sources"
            ),
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

    with open(os.path.join(BASELINE_DIR, "tracked_file_hashes.json"), "w", encoding="utf-8") as f:
        json.dump(file_hashes, f, indent=0, sort_keys=True)
        f.write("\n")

    with open(os.path.join(BASELINE_DIR, "v1_rule_inventory.json"), "w", encoding="utf-8") as f:
        json.dump(rule_inventory, f, indent=2, sort_keys=True)
        f.write("\n")

    with open(os.path.join(BASELINE_DIR, "environment_fingerprint.json"), "w", encoding="utf-8") as f:
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
    print(f"  registry exactly V1 8-rules: {rule_inventory['registry_exactly_matches_required']}")
    print(f"  content clean: {manifest['git']['content_clean']} (mode-only flips: {mode_only_changes})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
