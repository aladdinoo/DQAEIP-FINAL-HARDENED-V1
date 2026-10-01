#!/usr/bin/env python3
"""DQAEIP portable release — baseline snapshot builder.

(Supersedes the FINAL UPDATE snapshot builder role; same §15 design.)

Creates the integrity snapshot the continuous integrity monitor and the
drift detector compare future states against:

    evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18/integrity/
    baseline_snapshot.json

Contents (no secrets, no machine-local paths, no credentials):
    - protected artifact hashes (frozen V1 sources + official 3M
      evidence + checker chain + rules tree)
    - protected artifact modes (exec-bit monitoring)
    - expected tree identity (tracked-tree concat hash)
    - expected release identity (DQAEIP-FINAL-UPDATE-2026-09-17)
    - expected evidence identity (official Run 1 + Run 2 anchors)
    - expected dependency graph fingerprint (2nd pass; --dep-graph)
    - release-facing artifact pins (FINAL_RESULTS, README, manifests,
      provenance, release lock)
    - configuration baseline (python version, installed packages,
      config file hashes)
    - test baseline (previous verified counts)

Fail-closed: refuses to overwrite an existing snapshot (append a new
snapshot via --force only after an explicit audited decision).
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

NS = "evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18"

from data_quality_platform.assurance.integrity import (  # noqa: E402
    FROZEN_V1_SOURCE, OFFICIAL_EVIDENCE_DIR, UPDATE_ID,
    build_snapshot_protected_hashes, sha256_file)

SNAPSHOT_PATH = os.path.join(
    REPO_ROOT, NS, "integrity", "baseline_snapshot.json")


def git(args):
    return subprocess.run(["git", "-C", REPO_ROOT] + args,
                          capture_output=True, text=True, check=False)


def main():
    parser = argparse.ArgumentParser(
        description="Build the FINAL UPDATE integrity baseline snapshot")
    parser.add_argument("--force", action="store_true",
                        help="overwrite an existing snapshot (audited)")
    parser.add_argument("--dep-graph", default=None,
                        help="path to dependency_graph.json whose graph "
                             "fingerprint to pin")
    args = parser.parse_args()

    if os.path.exists(SNAPSHOT_PATH) and not args.force:
        print(f"REFUSING TO OVERWRITE existing snapshot: "
              f"{os.path.relpath(SNAPSHOT_PATH, REPO_ROOT)}")
        return 2

    os.makedirs(os.path.dirname(SNAPSHOT_PATH), exist_ok=True)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # ---- protected artifacts -----------------------------------------
    protected_hashes = build_snapshot_protected_hashes(REPO_ROOT)
    protected_modes = {
        rel: oct(os.stat(os.path.join(REPO_ROOT, rel)).st_mode & 0o777)
        for rel in protected_hashes
    }

    # ---- tracked tree identity ---------------------------------------
    tracked = [p for p in git(["ls-files", "-z"]).stdout.split("\0") if p]
    tree_concat = hashlib.sha256()
    tracked_set = set()
    for rel in sorted(tracked):
        abs_p = os.path.join(REPO_ROOT, rel)
        if os.path.isfile(abs_p):
            tracked_set.add(rel)
            tree_concat.update(rel.encode() + b"\x00"
                               + sha256_file(abs_p).encode())

    # ---- configuration baseline (NO secrets) -------------------------
    import importlib.metadata as md
    packages = {}
    for dist in md.distributions():
        name = (dist.metadata.get("Name") or "").lower()
        if name:
            packages[name] = dist.version
    config_hashes = {}
    for rel in ("pyproject.toml", "configs/quality.yaml"):
        abs_p = os.path.join(REPO_ROOT, rel)
        if os.path.isfile(abs_p):
            config_hashes[rel] = sha256_file(abs_p)

    # ---- release-facing pins ------------------------------------------
    def pin(rel):
        abs_p = os.path.join(REPO_ROOT, rel)
        return sha256_file(abs_p) if os.path.isfile(abs_p) else None

    dep_fp = None
    if args.dep_graph and os.path.isfile(args.dep_graph):
        graph = json.load(open(args.dep_graph, encoding="utf-8"))
        dep_fp = graph.get("graph_fingerprint")

    snapshot = {
        "report": "DQAEIP FINAL UPDATE integrity baseline snapshot",
        "snapshot_version": "1.0.0",
        "schema": {"name": "dqaeip.integrity_snapshot", "version": "1.0"},
        "update_id": UPDATE_ID,
        "release_id": "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18",
        "created_utc": started,
        "git_head": git(["rev-parse", "HEAD"]).stdout.strip(),
        "protected_artifact_hashes": protected_hashes,
        "protected_artifact_modes": protected_modes,
        "protected_directories": [
            OFFICIAL_EVIDENCE_DIR,
            "data_quality_platform/rules",
        ],
        "expected_tree_identity": {
            "tracked_tree_sha256_concat": tree_concat.hexdigest(),
            "tracked_file_count": len(tracked_set),
        },
        "expected_release_identity": {
            "release_id": "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-"
                          "2026-09-18",
            "release_date": "2026-09-18",
            "supersedes": None,
        },
        "expected_evidence_identity": {
            "official_evidence_dir": OFFICIAL_EVIDENCE_DIR,
            "official_run_count": 2,
            "input_sha256": "59624a53c72f908f1dde673ceecf59e06"
                            "2ae721bb8f9af7e165acba5318d153",
            "output_sha256": "b72adc235160a86e0b99a08f988dd0bb5f2cf"
                             "f82bbe5b5d28ea07c5a5719329a",
            "rows_per_run": 3200000,
            "combined_comparisons": 51200000,
            "combined_mismatches": 0,
            "frozen_v1_source": FROZEN_V1_SOURCE,
            "frozen_v1_sha256": "daef1ded54c7d3c79898a1ba253be2acd"
                                "5b6120e18b16b09009fdd7be9fc2276",
        },
        "expected_dependency_graph_fingerprint": dep_fp,
        "final_results_path": f"{NS}/final_results/"
                              "FINAL_RESULTS_PORTABLE_2026-09-18.json",
        "final_results_sha256": pin(
            f"{NS}/final_results/"
            "FINAL_RESULTS_PORTABLE_2026-09-18.json"),
        "readme_path": "README.md",
        "readme_sha256": pin("README.md"),
        "readme_consistency_path": "evidence/release/"
                                   "readme_consistency.json",
        "release_manifest_path": f"{NS}/release_manifest/"
                                 "release_manifest.json",
        "release_manifest_sha256": pin(
            f"{NS}/release_manifest/release_manifest.json"),
        "release_lock_path": f"{NS}/release_manifest/"
                             "release_lock.json",
        "release_lock_sha256": pin(
            f"{NS}/release_manifest/release_lock.json"),
        "provenance_path": "evidence/release/claim_provenance.json",
        "provenance_sha256": pin(
            "evidence/release/claim_provenance.json"),
        "test_summary_path": "evidence/rebuild_verification/"
                              "test_summary.json",
        "test_baseline": {
            "collected": 942,
            "passed": 933,
            "skipped": 9,
            "failed": 0,
            "errors": 0,
            "note": ("previous verified baseline (zero-assumption "
                     "rebuild, 2026-09-17); counts only ever grow via "
                     "documented additions"),
        },
        "configuration_baseline": {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "installed_packages": packages,
            "config_hashes": config_hashes,
            "disclosure_policy": ("no credentials of any kind are ever "
                                "captured in this snapshot"),
        },
        "change_ledger_path": f"{NS}/integrity/"
                              "change_ledger.jsonl",
        "ledger_policy": ("append-only within the current run; existing "
                          "lines are never rewritten or removed"),
    }

    with open(SNAPSHOT_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"baseline snapshot written: "
          f"{os.path.relpath(SNAPSHOT_PATH, REPO_ROOT)}")
    print(f"  protected artifacts: {len(protected_hashes)}")
    print(f"  tracked tree: {len(tracked_set)} files, identity "
          f"{tree_concat.hexdigest()[:16]}...")
    print(f"  pinned packages: {len(packages)}")
    print(f"  dependency graph fingerprint: "
          f"{'pinned' if dep_fp else 'NOT SET (2nd pass)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
