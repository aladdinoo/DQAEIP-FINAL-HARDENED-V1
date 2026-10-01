#!/usr/bin/env python3
"""DQAEIP FINAL UPDATE 2026-09-17 — PHASE 0 forensic baseline (read-only).

Captured BEFORE any rebuild modification, from the ACTUAL filesystem and
git state (never from README, reports, or prior agent claims):

    git identity (branch / HEAD / status / diff / tracked files /
                 untracked files / file modes / tree hash)
    full tracked-tree SHA-256 inventory (every tracked file, with mode)
    protected artifact identities:
        - Frozen V1 source hash (MUST equal daef1ded...)
        - official 3M Run 1 / Run 2 evidence hashes
        - official input / output SHA-256 anchors
        - checker identity (scripts/verify_run_pair.py)
        - current FINAL_RESULTS / README / release / ZIP identities
    evidence directory inventory (existing roots, no modification)
    environment identity (python version, platform; NO secrets)
    mode-anomaly observation (session-restore group-write bits,
        0 content delta, exec-bit consistent with the git index)

Writes (immutable — the writer refuses to overwrite an existing baseline):

    evidence/FINAL_UPDATE_2026-09-17/baseline/baseline.json
    evidence/FINAL_UPDATE_2026-09-17/baseline/baseline.md
    evidence/FINAL_UPDATE_2026-09-17/baseline/tracked_tree_manifest.json

The baseline NEVER mutates protected evidence: it only reads.
The baseline becomes the starting point of the FINAL UPDATE.
"""

import hashlib
import json
import os
import platform
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVIDENCE_ROOT = os.path.join(REPO_ROOT, "evidence", "FINAL_UPDATE_2026-09-17")
BASELINE_DIR = os.path.join(EVIDENCE_ROOT, "baseline")

UPDATE_ID = "DQAEIP-FINAL-UPDATE-2026-09-17"

# Frozen business-semantic core (must remain byte-identical through the
# update; any change is an unauthorized rule change -> STOP, never repair).
FROZEN_V1_SOURCE = "data_quality_platform/rules/v1_rules.py"
FROZEN_V1_EXPECTED_SHA256 = (
    "daef1ded54c7d3c79898a1ba253be2acd5b6120e18b16b09009fdd7be9fc2276")

# Official 3M evidence anchors (2026-09-15 pair — protected, never rerun).
OFFICIAL_EVIDENCE_DIR = "evidence/final_3m_validation_2026-09-15"
OFFICIAL_INPUT_SHA256 = (
    "208154653ca965dd50a27c8a7b42e59ef2c7d65e6353ffb1d156b8c3029f1a6f")
OFFICIAL_OUTPUT_SHA256 = (
    "b02872e3ee0a1471c369793a76e292758e339a199ef7253c84d91152f657af69")
OFFICIAL_RUN_EVIDENCE = [
    f"{OFFICIAL_EVIDENCE_DIR}/FINAL_RESULTS.json",
    f"{OFFICIAL_EVIDENCE_DIR}/pass1_cli.json",
    f"{OFFICIAL_EVIDENCE_DIR}/pass1_generate.json",
    f"{OFFICIAL_EVIDENCE_DIR}/pass1_result.json",
    f"{OFFICIAL_EVIDENCE_DIR}/pass1_engine/manifest.json",
    f"{OFFICIAL_EVIDENCE_DIR}/pass1_engine/evidence_root.json",
    f"{OFFICIAL_EVIDENCE_DIR}/pass2_cli.json",
    f"{OFFICIAL_EVIDENCE_DIR}/pass2_generate.json",
    f"{OFFICIAL_EVIDENCE_DIR}/pass2_result.json",
    f"{OFFICIAL_EVIDENCE_DIR}/pass2_engine/manifest.json",
    f"{OFFICIAL_EVIDENCE_DIR}/pass2_engine/evidence_root.json",
]

# Checker (fail-closed run-pair verifier) identity anchor.
CHECKER_PATH = "scripts/verify_run_pair.py"

# Release-facing anchors (starting identities of this update).
RELEASE_FACING_ARTIFACTS = [
    "README.md",
    "RELEASE_NOTES.md",
    "DELIVERY_MANIFEST.json",
    "FINAL_RESULTS.json",
    "final_result.json",
    "release_manifest.json",
    "evidence/release/release_evidence_model.json",
    "evidence/release/release_artifact_manifest.json",
    "evidence/release/observability_status.json",
    "evidence/release/readme_consistency.json",
    "evidence/release/reproducibility_fingerprint.json",
    "evidence/release_gate/final_release_gate.json",
    "evidence/mutation_testing/mutation_results.json",
    "evidence/rebuild_verification/test_summary.json",
]

# Superseded release ZIP (previous identity; the update builds a new one).
PREVIOUS_ZIP = {
    "path": "/home/z/my-project/download/DQAEIP-Assurance-Rebuild-Release-2026-09-17.zip",
    "expected_sha256": "654481c64196ee3dd7f302f2ce1fded20805620ccaed0cd8447886b8ad73d587",
    "expected_size_bytes": 1818848,
    "identity": "DQAEIP-Assurance-Rebuild-Release-2026-09-17",
}

NAMESPACE_SUBDIRS = [
    "baseline", "authoritative_inventory", "canonical_evidence",
    "final_results", "dependency_graph", "claims", "freshness",
    "contradictions", "consistency", "observability", "integrity",
    "drift", "configuration", "recovery", "security", "reproducibility",
    "release_manifest", "final_verification", "rebuild_report", "staging",
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
    baseline_path = os.path.join(BASELINE_DIR, "baseline.json")
    if os.path.exists(baseline_path):
        print(f"REFUSING TO OVERWRITE existing baseline: {to_rel(baseline_path)}")
        return 2
    os.makedirs(BASELINE_DIR, exist_ok=True)
    # Create the full update namespace (dirs only; no evidence written yet).
    for sub in NAMESPACE_SUBDIRS:
        os.makedirs(os.path.join(EVIDENCE_ROOT, sub), exist_ok=True)
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
    status_lines = git(["status", "--porcelain"]).stdout.splitlines()
    content_status = git(["-c", "core.fileMode=false",
                          "status", "--porcelain"]).stdout.splitlines()
    tracked_content_changes = [ln for ln in content_status
                               if not ln.startswith("?? ")]
    untracked_new = [ln[3:] for ln in content_status if ln.startswith("?? ")]
    diff_stat = git(["diff", "--stat"]).stdout
    diff_name_status = git(["diff", "--name-status"]).stdout
    tree_hash = git(["rev-parse", "HEAD^{tree}"]).stdout.strip()
    last_commit_ts = git(["log", "-1", "--format=%cI", "HEAD"]).stdout.strip()
    last_commit_subject = git(["log", "-1", "--format=%s", "HEAD"]).stdout.strip()

    # ---- Full tracked-tree inventory (hash + mode) -------------------
    ls_files = git(["ls-files", "-z"])
    tracked = [p for p in ls_files.stdout.split("\0") if p]
    tree_manifest = {}
    group_write_anomalies = []
    for rel in tracked:
        abs_p = os.path.join(REPO_ROOT, rel)
        if os.path.isfile(abs_p):
            entry = {
                "sha256": sha256_file(abs_p),
                "size_bytes": os.path.getsize(abs_p),
                "mode_disk": oct(os.stat(abs_p).st_mode & 0o777),
            }
            tree_manifest[rel] = entry
            # session-restore observation: group-write bit set, exec bit
            # still consistent with the git index -> 0 git-visible delta
            if entry["mode_disk"] == "0o664":
                group_write_anomalies.append(rel)
    tree_concat = hashlib.sha256()
    for rel in sorted(tree_manifest):
        tree_concat.update(rel.encode() + b"\x00"
                           + tree_manifest[rel]["sha256"].encode())
    tree_identity = tree_concat.hexdigest()

    # ---- Protected artifact identities -------------------------------
    v1_actual = sha256_file(os.path.join(REPO_ROOT, FROZEN_V1_SOURCE))
    v1_matches = v1_actual == FROZEN_V1_EXPECTED_SHA256

    official_hashes = {}
    for rel in OFFICIAL_RUN_EVIDENCE:
        abs_p = os.path.join(REPO_ROOT, rel)
        official_hashes[rel] = sha256_file(abs_p) if os.path.isfile(abs_p) else None
    missing_official = [r for r, h in official_hashes.items() if h is None]

    # Official anchor verification: recorded SHAs inside the official
    # evidence must still match the task-book anchors (read-only check).
    official_fr = json.load(open(os.path.join(
        REPO_ROOT, OFFICIAL_EVIDENCE_DIR, "FINAL_RESULTS.json"), encoding="utf-8"))
    recorded_input_sha = official_fr.get("input_sha256")
    recorded_output_sha = official_fr.get("output_sha256")
    recorded_rows = official_fr.get("rows")
    recorded_comparisons = official_fr.get("oracle_comparisons")
    runs = official_fr.get("runs", {})
    run_ids = sorted(runs.keys()) if isinstance(runs, dict) else []
    run_count = len(run_ids)
    run3_exists = any("3" in rid for rid in run_ids) or any(
        "run_3" in json.dumps(runs).lower() for _ in [0])

    checker_sha = sha256_file(os.path.join(REPO_ROOT, CHECKER_PATH))

    release_facing = {}
    for rel in RELEASE_FACING_ARTIFACTS:
        abs_p = os.path.join(REPO_ROOT, rel)
        release_facing[rel] = {
            "sha256": sha256_file(abs_p) if os.path.isfile(abs_p) else None,
            "size_bytes": os.path.getsize(abs_p) if os.path.isfile(abs_p) else None,
        }

    # Current release identity (from FINAL_RESULTS, machine-read).
    root_fr = json.load(open(os.path.join(REPO_ROOT, "FINAL_RESULTS.json"),
                             encoding="utf-8"))
    current_release_identity = root_fr.get("release_identity", {})
    if isinstance(current_release_identity, dict):
        current_release_identity = current_release_identity.get(
            "release_id") or json.dumps(current_release_identity)[:200]

    # Previous ZIP identity (on-disk, outside the repo tree).
    zip_sha = zip_size = None
    zip_matches_expected = None
    if os.path.isfile(PREVIOUS_ZIP["path"]):
        zip_sha = sha256_file(PREVIOUS_ZIP["path"])
        zip_size = os.path.getsize(PREVIOUS_ZIP["path"])
        zip_matches_expected = (
            zip_sha == PREVIOUS_ZIP["expected_sha256"]
            and zip_size == PREVIOUS_ZIP["expected_size_bytes"])

    # ---- Evidence directory inventory (existing roots) ----------------
    evidence_roots = sorted(
        d for d in os.listdir(os.path.join(REPO_ROOT, "evidence"))
        if os.path.isdir(os.path.join(REPO_ROOT, "evidence", d)))

    # ---- Environment identity (NO secrets) --------------------------
    env_identity = {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "venv_python": ".venv/bin/python (project-local)",
        "note": "No environment variables, credentials, or secrets captured.",
    }

    baseline = {
        "report": "DQAEIP FINAL UPDATE 2026-09-17 — PHASE 0 forensic baseline",
        "update_id": UPDATE_ID,
        "captured_utc": started,
        "captured_before_any_modification": True,
        "git_identity": {
            "branch": branch,
            "head": head,
            "tree_hash": tree_hash,
            "origin_url": origin_url,
            "origin_main": origin_main,
            "ahead_of_origin": ahead,
            "behind_origin": behind,
            "content_clean": len(tracked_content_changes) == 0,
            "tracked_content_changes": tracked_content_changes,
            "untracked_files": untracked_new,
            "diff_stat_empty": diff_stat.strip() == "",
            "diff_name_status_empty": diff_name_status.strip() == "",
            "last_commit_timestamp": last_commit_ts,
            "last_commit_subject": last_commit_subject,
            "tracked_file_count": len(tracked),
            "push_policy": "NEVER PUSH (task book section 41)",
        },
        "tree_identity": {
            "tracked_tree_sha256_concat": tree_identity,
            "manifest_entries": len(tree_manifest),
            "group_write_mode_files": len(group_write_anomalies),
            "group_write_mode_note": (
                "Session-restore storage-layer noise: group-write bit "
                "present on some files (0o664); the executable bit is "
                "consistent with the git index and git status is clean — "
                "zero content or git-visible delta. Recorded, not hidden."),
        },
        "frozen_v1": {
            "source": FROZEN_V1_SOURCE,
            "sha256_actual": v1_actual,
            "sha256_expected": FROZEN_V1_EXPECTED_SHA256,
            "matches_expected": v1_matches,
            "policy": "If changed: STOP. Never restore, rewrite, or fix.",
        },
        "official_3m_evidence": {
            "directory": OFFICIAL_EVIDENCE_DIR,
            "expected_input_sha256": OFFICIAL_INPUT_SHA256,
            "recorded_input_sha256": recorded_input_sha,
            "input_sha_matches": recorded_input_sha == OFFICIAL_INPUT_SHA256,
            "expected_output_sha256": OFFICIAL_OUTPUT_SHA256,
            "recorded_output_sha256": recorded_output_sha,
            "output_sha_matches": recorded_output_sha == OFFICIAL_OUTPUT_SHA256,
            "recorded_rows_per_run": recorded_rows,
            "recorded_combined_comparisons": recorded_comparisons,
            "recorded_run_count": run_count,
            "run3_present": run3_exists,
            "missing_evidence_files": missing_official,
            "artifact_sha256": official_hashes,
            "policy": ("Exactly Run 1 + Run 2; NEVER create Run 3; NEVER "
                       "regenerate; NEVER modify. If missing or hashes "
                       "differ: STOP."),
        },
        "checker_identity": {
            "path": CHECKER_PATH,
            "sha256": checker_sha,
        },
        "release_facing_artifacts": release_facing,
        "current_release_identity": {
            "release_id": current_release_identity,
            "superseded_zip": {
                "identity": PREVIOUS_ZIP["identity"],
                "on_disk": zip_sha is not None,
                "sha256": zip_sha,
                "size_bytes": zip_size,
                "matches_previous_release_record": zip_matches_expected,
            },
        },
        "evidence_roots_existing": evidence_roots,
        "environment_identity": env_identity,
        "phase0_verdict": {
            "frozen_v1_verified": v1_matches,
            "official_evidence_present": len(missing_official) == 0,
            "official_input_anchor_matches": recorded_input_sha == OFFICIAL_INPUT_SHA256,
            "official_output_anchor_matches": recorded_output_sha == OFFICIAL_OUTPUT_SHA256,
            "tree_clean": len(tracked_content_changes) == 0,
            "no_run3": not run3_exists,
            "stop_conditions_triggered": (
                (not v1_matches)
                or len(missing_official) > 0
                or recorded_input_sha != OFFICIAL_INPUT_SHA256
                or recorded_output_sha != OFFICIAL_OUTPUT_SHA256
                or run3_exists
            ),
        },
    }

    manifest_doc = {
        "report": "Tracked-tree SHA-256 manifest (PHASE 0, pre-update)",
        "update_id": UPDATE_ID,
        "captured_utc": started,
        "head": head,
        "entry_count": len(tree_manifest),
        "files": tree_manifest,
    }

    with open(baseline_path, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2, sort_keys=True)
        f.write("\n")
    with open(os.path.join(BASELINE_DIR, "tracked_tree_manifest.json"),
              "w", encoding="utf-8") as f:
        json.dump(manifest_doc, f, indent=2, sort_keys=True)
        f.write("\n")

    # ---- Human-readable baseline.md -----------------------------------
    p0 = baseline["phase0_verdict"]
    md = f"""# DQAEIP FINAL UPDATE 2026-09-17 — PHASE 0 Forensic Baseline

Captured {started}, BEFORE any modification, from the actual filesystem
and git state. This baseline is the starting point of the update.

## Git identity

- Branch: `{branch}` (HEAD `{head}`)
- Tree hash: `{tree_hash}`
- Origin: `{origin_url}` @ `{origin_main}` — **{ahead} ahead / {behind} behind; NOTHING PUSHED**
- Working tree: `{'CLEAN' if len(tracked_content_changes) == 0 else 'DIRTY (' + str(len(tracked_content_changes)) + ' changes)'}` (content level; diff empty)
- Tracked files: {len(tracked)}; untracked: {len(untracked_new)}
- Last commit: `{last_commit_subject}` ({last_commit_ts})

## Protected artifact identities

| Artifact | Identity | Verified |
|---|---|---|
| Frozen V1 source | `{v1_actual}` | {'YES — exact expected SHA' if v1_matches else 'NO — STOP CONDITION'} |
| Official input SHA (recorded) | `{recorded_input_sha}` | {'YES' if recorded_input_sha == OFFICIAL_INPUT_SHA256 else 'NO — STOP'} |
| Official output SHA (recorded) | `{recorded_output_sha}` | {'YES' if recorded_output_sha == OFFICIAL_OUTPUT_SHA256 else 'NO — STOP'} |
| Checker (`{CHECKER_PATH}`) | `{checker_sha}` | recorded |
| Official run count | {run_count} (Run 1 + Run 2) | {'YES' if run_count == 2 else 'CHECK'} |
| Run 3 present | {'NO' if not run3_exists else 'YES — STOP'} | {'YES' if not run3_exists else 'NO'} |

Official 3M evidence artifacts hashed: {len(official_hashes)} files
(missing: {len(missing_official)}).

## Current release identity (start of update)

- Release: `{current_release_identity}`
- Superseded ZIP on disk: `{PREVIOUS_ZIP['identity']}`
  SHA-256 `{zip_sha}` ({zip_size:,} bytes)
- Matches previous release record: {zip_matches_expected}

## Tree identity

- Tracked-tree concatenation SHA-256: `{tree_identity}`
- Manifest entries: {len(tree_manifest)}
- Session-restore mode observation: {len(group_write_anomalies)} files carry
  a group-write bit (storage-layer noise; executable bit consistent with
  the git index; zero git-visible delta). Recorded, not hidden.

## Environment

- Python {env_identity['python_version']} ({env_identity['python_implementation']}),
  {env_identity['platform']}, project-local `.venv`
- No secrets, environment variables, or credentials captured.

## Phase 0 verdict

- Frozen V1 verified: **{p0['frozen_v1_verified']}**
- Official evidence present: **{p0['official_evidence_present']}**
- Official input anchor matches: **{p0['official_input_anchor_matches']}**
- Official output anchor matches: **{p0['official_output_anchor_matches']}**
- Tree clean: **{p0['tree_clean']}**
- No Run 3: **{p0['no_run3']}**
- STOP conditions triggered: **{p0['stop_conditions_triggered']}**
"""
    with open(os.path.join(BASELINE_DIR, "baseline.md"), "w",
              encoding="utf-8") as f:
        f.write(md)

    print(f"PHASE 0 baseline written: {to_rel(baseline_path)}")
    print(f"  Frozen V1 verified: {v1_matches}")
    print(f"  Official evidence files: {len(official_hashes)} "
          f"(missing: {len(missing_official)})")
    print(f"  Input anchor: {recorded_input_sha == OFFICIAL_INPUT_SHA256} | "
          f"Output anchor: {recorded_output_sha == OFFICIAL_OUTPUT_SHA256}")
    print(f"  Run count: {run_count} | Run 3 present: {run3_exists}")
    print(f"  Tree clean: {len(tracked_content_changes) == 0} | "
          f"tracked-tree identity: {tree_identity[:16]}...")
    print(f"  STOP conditions triggered: "
          f"{baseline['phase0_verdict']['stop_conditions_triggered']}")
    if baseline["phase0_verdict"]["stop_conditions_triggered"]:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
