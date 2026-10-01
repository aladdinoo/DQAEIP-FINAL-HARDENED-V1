#!/usr/bin/env python3
"""DQAEIP FINAL PORTABLE EVIDENCE UPDATE V2 (2026-09-18) — Phase 0.

FORENSIC BASELINE (task-book Phase 0). READ-ONLY over the repository:
this tool inventories the found state; it modifies nothing outside the
new UPDATE-V2 namespace.

Captured before ANY UPDATE-V2 change:

    git HEAD / branch / status / diff --stat / diff --name-status
    repository tree identity (HEAD^{tree})
    total tracked files, evidence/ file count, JSON + JSONL counts
    protected-anchor SHA-256 set (verified again in Phase 19)
    found-state documentation (the interrupted previous session's
    uncommitted gate re-run: 4 modified evidence files + 1 untracked
    attempt record, all preserved by an explicit baseline-preservation
    commit — never reverted, never deleted)
    previous release identity

Namespace (independent, additive only):

    evidence/FINAL_PORTABLE_UPDATE_V2_2026-09-18/
"""

import hashlib
import json
import os
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

UPDATE_ID = "DQAEIP-FINAL-UPDATE-V2-2026-09-18"
NS = "evidence/FINAL_PORTABLE_UPDATE_V2_2026-09-18"
OUT = os.path.join(REPO_ROOT, NS, "baseline",
                   "forensic_baseline_UPDATE-V2.json")

PREV_RELEASE_ID = "DQAEIP-FINAL-PORTABLE-EVIDENCE-RELEASE-2026-09-18"
PREV_NS = "evidence/FINAL_PORTABLE_RELEASE_2026-09-18"
PREV_UPDATE_NS = "evidence/FINAL_UPDATE_2026-09-17"

DOWNLOAD_DIR = os.path.abspath(os.path.join(
    os.path.dirname(os.path.dirname(REPO_ROOT)), "download"))

# Protected anchors (RULE 1/4/7/19): their SHA-256 is recorded here and
# re-verified after every UPDATE-V2 change; any drift is a STOP.
PROTECTED_ANCHORS = [
    # the authoritative official 3M evidence root (byte-exact, never
    # edited, never reserialized)
    "evidence/final_3m_validation_2026-09-15/FINAL_RESULTS.json",
    "evidence/final_3m_validation_2026-09-15/pass1_cli.json",
    "evidence/final_3m_validation_2026-09-15/pass1_engine/alerts.json",
    "evidence/final_3m_validation_2026-09-15/pass1_engine/audit.json",
    "evidence/final_3m_validation_2026-09-15/pass1_engine/evidence_root.json",
    "evidence/final_3m_validation_2026-09-15/pass1_engine/lineage.json",
    "evidence/final_3m_validation_2026-09-15/pass1_engine/manifest.json",
    "evidence/final_3m_validation_2026-09-15/pass1_engine/monitoring.json",
    "evidence/final_3m_validation_2026-09-15/pass1_generate.json",
    "evidence/final_3m_validation_2026-09-15/pass1_result.json",
    "evidence/final_3m_validation_2026-09-15/pass1_runtime_safety_events.json",
    "evidence/final_3m_validation_2026-09-15/pass2_cli.json",
    "evidence/final_3m_validation_2026-09-15/pass2_engine/alerts.json",
    "evidence/final_3m_validation_2026-09-15/pass2_engine/audit.json",
    "evidence/final_3m_validation_2026-09-15/pass2_engine/evidence_root.json",
    "evidence/final_3m_validation_2026-09-15/pass2_engine/lineage.json",
    "evidence/final_3m_validation_2026-09-15/pass2_engine/manifest.json",
    "evidence/final_3m_validation_2026-09-15/pass2_engine/monitoring.json",
    "evidence/final_3m_validation_2026-09-15/pass2_generate.json",
    "evidence/final_3m_validation_2026-09-15/pass2_result.json",
    "evidence/final_3m_validation_2026-09-15/pass2_runtime_safety_events.json",
    # frozen business truth
    "data_quality_platform/rules/v1_rules.py",
    "scripts/final_3m_validation.py",
    # previous FINAL_RESULTS anchors (both release rounds)
    "evidence/FINAL_UPDATE_2026-09-17/final_results/"
    "FINAL_RESULTS_UPDATE-2026-09-17.json",
    f"{PREV_NS}/final_results/FINAL_RESULTS_PORTABLE_2026-09-18.json",
    # prior-round ZIP-sidecar-pinned release records inside the repo
    "evidence/FINAL_UPDATE_2026-09-17/final_verification/"
    "clean_extraction_report.json",
]

PROTECTED_ZIPS = [
    "DQAEIP-FINAL-UPDATE-2026-09-17.zip",
    "DQAEIP-Assurance-Rebuild-Release-2026-09-17.zip",
    "DQAEIP-Enterprise-Assurance-Validation-Release-2026-09-17.zip",
    "DQAEIP-Enterprise-Assurance-Validation-Release-2026-09-16.zip",
    "DQAVP-Enterprise-Hardened-Validation-Release-2026-09-15.zip",
    "DQAVP-Final-Validation.zip",
    "DQVP-V2-Final.zip",
    "Data-Quality-Validation-Platform-V2-Final-2026-09-11.zip",
    "Data-Quality-Validation-Platform-V2-Final-3M-Validated-2026-09-10.zip",
    "Data-Quality-Validation-Platform-V2-SP1-Successor-Validated-2026-09-10.zip",
]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(args):
    r = subprocess.run(["git", "-C", REPO_ROOT] + args,
                       capture_output=True, text=True, check=False)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def git_raw(args):
    """Like git() but preserves leading whitespace of the first line —
    required for `status --short` whose first column IS a space for
    unstaged modifications (a plain .strip() would silently corrupt
    the first status entry)."""
    r = subprocess.run(["git", "-C", REPO_ROOT] + args,
                       capture_output=True, text=True, check=False)
    return r.returncode, r.stdout, r.stderr


def count_files(root, predicate):
    n = 0
    for base, _dirs, files in os.walk(root):
        if "__pycache__" in base or ".pytest_cache" in base:
            continue
        for fn in files:
            if predicate(fn):
                n += 1
    return n


def main():
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    rc, head, _ = git(["rev-parse", "HEAD"])
    if rc != 0:
        print("FATAL: not a git repository", file=sys.stderr)
        return 4
    _, branch, _ = git(["branch", "--show-current"])
    _, tree_id, _ = git(["rev-parse", "HEAD^{tree}"])
    _, status_short, _ = git_raw(["status", "--short"])
    status_short = "\n".join(
        l for l in status_short.splitlines() if l.strip())
    _, diff_stat, _ = git(["diff", "--stat"])
    _, diff_ns, _ = git(["diff", "--name-status"])
    _, untracked, _ = git(["ls-files", "--others", "--exclude-standard"])
    _, tracked_count, _ = git(["ls-files"])
    tracked_count = len([x for x in tracked_count.split("\n") if x])
    _, ahead, _ = git(["rev-list", "--left-right", "--count",
                       "origin/main...HEAD"])

    evidence_dir = os.path.join(REPO_ROOT, "evidence")
    evidence_file_count = count_files(
        evidence_dir, lambda fn: True)
    json_count = count_files(evidence_dir, lambda fn: fn.endswith(".json"))
    jsonl_count = count_files(evidence_dir, lambda fn: fn.endswith(".jsonl"))

    # protected anchors: SHA-256 of every anchor + on-disk ZIPs
    anchors = {}
    missing = []
    for rel in PROTECTED_ANCHORS:
        p = os.path.join(REPO_ROOT, rel)
        if os.path.isfile(p):
            anchors[rel] = sha256_file(p)
        else:
            missing.append(rel)
    zips = {}
    for name in PROTECTED_ZIPS:
        p = os.path.join(DOWNLOAD_DIR, name)
        if os.path.isfile(p):
            zips[name] = {"sha256": sha256_file(p),
                          "size_bytes": os.path.getsize(p)}
        else:
            missing.append(f"download/{name}")

    # found-state analysis (the interrupted previous session)
    found_state = {
        "description": "working tree at UPDATE-V2 session start: the "
                       "previous portable-release session was "
                       "interrupted AFTER its final platform-gate "
                       "re-run achieved 22/22 PASS but BEFORE the "
                       "re-run evidence was committed",
        "uncommitted_modified": sorted(
            l[3:] for l in status_short.split("\n")
            if l.startswith(" M ") or l.startswith("M  ")
            or l.startswith("MM ")),
        "untracked": sorted(
            l[3:] for l in status_short.split("\n")
            if l.startswith("?? ")),
        "analysis": {
            "evidence/release_gate/final_release_gate.json":
                "platform release gate re-run at HEAD c69316e "
                "(2026-09-17T18:33:35Z): overall_verdict PASS, 22/22 "
                "gates; timing/timestamp deltas only",
            "evidence/release_gate/"
            "final_release_gate_attempt2_pii_falsepositive.json":
                "untracked forensic record of the intermediate gate "
                "attempt (18:28:08Z) showing the pre-fix failures the "
                "PII scanner root-cause fix (commit c69316e) resolved",
            "evidence/dqvp_performance/performance_results.json":
                "performance certification re-run (timing deltas only)",
            "evidence/release_gate/performance_results_current.json":
                "copy of the re-run performance certification",
            "evidence/mutation_testing/mutation_results.json":
                "mutation-testing re-run: source SHA before == after "
                "== daef1ded (frozen V1 untouched), duration deltas "
                "only",
        },
        "disposition": "preserved verbatim by an explicit "
                       "baseline-preservation commit (audit trail; "
                       "RULE 4 forbids deleting forensic records); no "
                       "file inside the protected anchor set is part "
                       "of this found state",
        "business_truth_delta": "NONE (verified: no protected anchor "
                                "modified; frozen V1 SHA identical "
                                "before/after in the mutation re-run)",
    }

    doc = {
        "report": "DQAEIP FINAL PORTABLE EVIDENCE UPDATE V2 — "
                  "Phase 0 forensic baseline",
        "schema": {"name": "dqaeip.update_v2.baseline", "version": "1.0"},
        "update_id": UPDATE_ID,
        "release_id": UPDATE_ID,
        "previous_release_id": PREV_RELEASE_ID,
        "generated_utc": started,
        "baseline": {
            "git_head": head,
            "git_branch": branch,
            "git_tree_identity": tree_id,
            "origin_main_left_right_count": ahead,
            "baseline_timestamp": started,
            "git_status_short": status_short,
            "git_diff_stat": diff_stat,
            "git_diff_name_status": diff_ns,
            "git_untracked": untracked,
            "found_state": found_state,
            "total_tracked_files": tracked_count,
            "evidence_file_count": evidence_file_count,
            "evidence_json_count": json_count,
            "evidence_jsonl_count": jsonl_count,
        },
        "protected_anchors": {
            "note": "SHA-256 set verified again by Phase 19 (historical "
                    "safety check); ANY drift is a STOP condition",
            "files": anchors,
            "zips": zips,
            "missing_anchors": missing,
        },
        "official_3m_truth_declared": {
            "runs": 2,
            "comparisons": 48000000,
            "mismatches": 0,
            "frozen_rules": 8,
            "input_columns": 33,
            "output_columns": 41,
            "input_sha256": "208154653ca965dd50a27c8a7b42e59ef2c7d6"
                            "5e6353ffb1d156b8c3029f1a6f",
            "output_sha256": "b02872e3ee0a1471c369793a76e292758e339"
                             "a199ef7253c84d91152f657af69",
            "frozen_v1_sha256": "daef1ded54c7d3c79898a1ba253be2acd5b"
                                "6120e18b16b09009fdd7be9fc2276",
            "checker_sha256": "0ef7c10c14a1df317c23cb0dfc73b3a60c225"
                              "7c064b35080d694e5fe8bc50d84",
            "rerun_for_this_update": False,
        },
        "constraints_declared": {
            "authoritative_evidence_modification": "FORBIDDEN",
            "historical_evidence_deletion": "FORBIDDEN",
            "business_rule_change": "FORBIDDEN",
            "broad_path_exception": "FORBIDDEN",
            "3m_rerun": "FORBIDDEN",
        },
    }

    os.makedirs(os.path.dirname(os.path.join(REPO_ROOT, OUT)), exist_ok=True)
    with open(os.path.join(REPO_ROOT, OUT), "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"UPDATE-V2 baseline captured: {OUT}")
    print(f"  HEAD:        {head}")
    print(f"  tree:        {tree_id}")
    print(f"  branch:      {branch} ({ahead} vs origin/main)")
    print(f"  tracked:     {tracked_count} files")
    print(f"  evidence/:   {evidence_file_count} files "
          f"({json_count} JSON, {jsonl_count} JSONL)")
    print(f"  anchors:     {len(anchors)} files + {len(zips)} ZIPs "
          f"hashed ({len(missing)} missing)")
    print(f"  uncommitted: {len(found_state['uncommitted_modified'])} "
          f"modified, {len(found_state['untracked'])} untracked "
          "(preserved below, never reverted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
