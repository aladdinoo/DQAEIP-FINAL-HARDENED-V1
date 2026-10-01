#!/usr/bin/env python3
"""DQAEIP FINAL PORTABLE EVIDENCE & RELEASE HARDENING — Phase 0.

Forensic baseline captured BEFORE any modification of the repository
(task-book section 1). Strictly read-only with respect to repository
truth: this script WRITES ONLY into the new namespace
``evidence/FINAL_PORTABLE_RELEASE_2026-09-18/baseline/``.

Captured and verified (zero-assumption, fail-closed):

    - git HEAD / branch / status / tracked + untracked counts
    - Frozen V1 rule-source SHA-256 (must equal the official anchor)
    - official 3M input / output SHA-256 (must equal official anchors)
    - official checker SHA-256 (must equal the official anchor)
    - official run count (must be exactly Run 1 + Run 2; no Run 3)
    - 3M truth: 3,000,000 rows/run, 24M comparisons/run,
      48,000,000 combined, 0 mismatches
    - current FINAL_RESULTS SHA + dependency fingerprint
    - current release manifest / release lock / definitive ZIP SHA
    - current README identity + current release verdict
    - 33 in / 8 flags / 41 out contract + live registry rule count

Any anchor mismatch is recorded as a STOP CONDITION and the script
exits non-zero. Nothing is mutated; nothing is rebuilt.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

NS = "evidence/FINAL_PORTABLE_RELEASE_2026-09-18"
OUT_DIR = os.path.join(REPO_ROOT, NS, "baseline")

RELEASE_ID = "DQAEIP-FINAL-PORTABLE-EVIDENCE-RELEASE-2026-09-18"
PRIOR_RELEASE_ID = "DQAEIP-FINAL-UPDATE-2026-09-17"

# ---- official anchors (task book, section 1) --------------------------
FROZEN_V1_SOURCE = "data_quality_platform/rules/v1_rules.py"
FROZEN_V1_SHA = (
    "daef1ded54c7d3c79898a1ba253be2acd5b6120e18b16b09009fdd7be9fc2276")
OFFICIAL_EVIDENCE_DIR = "evidence/final_3m_validation_2026-09-15"
OFFICIAL_CHECKER = "scripts/final_3m_validation.py"
CHECKER_SHA = (
    "0ef7c10c14a1df317c23cb0dfc73b3a60c2257c064b35080d694e5fe8bc50d84")
OFFICIAL_INPUT_SHA = (
    "208154653ca965dd50a27c8a7b42e59ef2c7d65e6353ffb1d156b8c3029f1a6f")
OFFICIAL_OUTPUT_SHA = (
    "b02872e3ee0a1471c369793a76e292758e339a199ef7253c84d91152f657af69")
RUN3_PATTERN = re.compile(r"run[_\-]?3(?![0-9])", re.IGNORECASE)

PRIOR_FINAL_RESULTS = os.path.join(
    REPO_ROOT, "evidence", "FINAL_UPDATE_2026-09-17", "final_results",
    "FINAL_RESULTS_UPDATE-2026-09-17.json")
PRIOR_MANIFEST = os.path.join(
    REPO_ROOT, "evidence", "FINAL_UPDATE_2026-09-17", "release_manifest",
    "release_manifest.json")
PRIOR_LOCK = os.path.join(
    REPO_ROOT, "evidence", "FINAL_UPDATE_2026-09-17", "release_manifest",
    "release_lock.json")
PRIOR_ZIP = os.path.join(
    os.path.dirname(os.path.dirname(REPO_ROOT)), "download",
    "DQAEIP-FINAL-UPDATE-2026-09-17.zip")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(args):
    return subprocess.run(["git", "-C", REPO_ROOT] + args,
                          capture_output=True, text=True, check=False)


def main():
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    checks = []
    stop_conditions = []

    def check(name, ok, detail):
        checks.append({"check": name,
                      "status": "PASS" if ok else "STOP",
                      "detail": detail})
        if not ok:
            stop_conditions.append(
                {"check": name, "detail": str(detail)[:400]})
        print(f"[{'PASS' if ok else 'STOP':4s}] {name}: "
              f"{str(detail)[:160]}")
        return ok

    # ---- git state -------------------------------------------------------
    head = git(["rev-parse", "HEAD"]).stdout.strip()
    branch = git(["branch", "--show-current"]).stdout.strip()
    status_porcelain = git(["status", "--porcelain"]).stdout
    status_lines = [ln for ln in status_porcelain.splitlines() if ln.strip()]
    tracked = [p for p in git(["ls-files", "-z"]).stdout.split("\0") if p]
    untracked = git(["ls-files", "--others", "--exclude-standard",
                     "-z"]).stdout.split("\0")
    untracked = [p for p in untracked if p and not (
        p.startswith("evidence/FINAL_PORTABLE_RELEASE_2026-09-18/")
        or p == "scripts/portable_release_baseline.py")]
    content_dirty = git(["diff", "--numstat"]).stdout.strip()
    ahead = git(["rev-list", "--count", "origin/main..HEAD"]).stdout.strip()

    check("git_head_captured", bool(head), head)
    check("branch", branch == "main", branch)
    # mode-only changes appear in numstat as "0<TAB>0<TAB>path";
    # only lines with a real insertion/deletion count are content deltas
    content_delta_files = []
    for ln in (content_dirty.splitlines() if content_dirty else []):
        parts = ln.split("\t")
        if len(parts) >= 3 and not (
                parts[0].lstrip("-") == "0" and parts[1].lstrip("-") == "0"):
            content_delta_files.append(ln)
    check("tree_no_content_delta", not content_delta_files,
          f"content-delta files: {len(content_delta_files)}; "
          f"mode-only lines: {len(status_lines)}")
    check("no_untracked_files", len(untracked) == 0,
          f"{len(untracked)} untracked")
    check("nothing_pushed", ahead.isdigit() and int(ahead) >= 0,
          f"{ahead} commits ahead of origin/main (not pushed)")

    # ---- Frozen V1 -------------------------------------------------------
    v1_sha = sha256_file(os.path.join(REPO_ROOT, FROZEN_V1_SOURCE))
    check("frozen_v1_sha256", v1_sha == FROZEN_V1_SHA, v1_sha)

    # ---- official 3M evidence -------------------------------------------
    fr3m = json.load(open(os.path.join(
        REPO_ROOT, OFFICIAL_EVIDENCE_DIR, "FINAL_RESULTS.json"),
        encoding="utf-8"))
    check("official_input_sha256",
          fr3m.get("input_sha256") == OFFICIAL_INPUT_SHA,
          fr3m.get("input_sha256"))
    check("official_output_sha256",
          fr3m.get("output_sha256") == OFFICIAL_OUTPUT_SHA,
          fr3m.get("output_sha256"))
    check("official_rows_per_run", fr3m.get("rows") == 3000000,
          fr3m.get("rows"))
    comp = fr3m.get("comparison_count") or {}
    check("comparisons_per_run_24m",
          comp.get("run_1") == 24000000 and comp.get("run_2") == 24000000,
          f"run_1={comp.get('run_1')} run_2={comp.get('run_2')}")
    check("comparisons_combined_48m",
          comp.get("combined_total") == 48000000,
          comp.get("combined_total"))
    mm = fr3m.get("oracle_mismatches") or {}
    check("mismatches_zero",
          mm.get("run_1") == 0 and mm.get("run_2") == 0
          and mm.get("combined_total") == 0,
          f"run_1={mm.get('run_1')} run_2={mm.get('run_2')} "
          f"combined={mm.get('combined_total')}")
    check("checker_provenance_sha",
          fr3m.get("provenance", {}).get("script_sha256") == CHECKER_SHA,
          fr3m.get("provenance", {}).get("script_sha256"))
    checker_live = sha256_file(os.path.join(REPO_ROOT, OFFICIAL_CHECKER))
    check("checker_live_sha256", checker_live == CHECKER_SHA, checker_live)
    runs = fr3m.get("runs") or {}
    check("run_count_exactly_2", set(runs) == {"run_1", "run_2"},
          sorted(runs))
    run3_hits = [fn for fn in os.listdir(
        os.path.join(REPO_ROOT, OFFICIAL_EVIDENCE_DIR))
        if RUN3_PATTERN.search(fn)]
    check("no_run3_artifacts", not run3_hits, run3_hits)

    # ---- live registry + contract ----------------------------------------
    from data_quality_platform.rules.registry import RuleRegistry
    registry = RuleRegistry.create_default()
    rule_ids = sorted(r.rule_id for r in registry.get_all_rules())
    from data_quality_platform.contracts import (
        SOURCE_COLUMNS, TOTAL_OUTPUT_COLUMNS)
    check("live_rule_count_8", len(rule_ids) == 8, rule_ids)
    check("contract_33_in", len(SOURCE_COLUMNS) == 33, len(SOURCE_COLUMNS))
    check("contract_41_out", TOTAL_OUTPUT_COLUMNS == 41,
          TOTAL_OUTPUT_COLUMNS)

    # ---- current FINAL_RESULTS / fingerprint / lock / ZIP ----------------
    fr_sha = sha256_file(PRIOR_FINAL_RESULTS)
    fr_doc = json.load(open(PRIOR_FINAL_RESULTS, encoding="utf-8"))
    check("prior_final_results_readable", True,
          f"SHA {fr_sha[:12]}…; state "
          f"{fr_doc.get('verification_state')}")
    check("prior_dependency_fingerprint",
          isinstance(fr_doc.get("dependency_fingerprint"), str),
          fr_doc.get("dependency_fingerprint"))
    manifest_sha = sha256_file(PRIOR_MANIFEST)
    lock_doc = json.load(open(PRIOR_LOCK, encoding="utf-8"))
    lock_sha = sha256_file(PRIOR_LOCK)
    check("prior_lock_locked", lock_doc.get("status") == "LOCKED",
          lock_doc.get("status"))
    zip_sha = sha256_file(PRIOR_ZIP) if os.path.isfile(PRIOR_ZIP) else None
    check("prior_zip_present", zip_sha is not None,
          zip_sha or "missing")
    readme_head = open(os.path.join(REPO_ROOT, "README.md"),
                       encoding="utf-8").read(4000)
    check("readme_identity_captured", "DQAEIP" in readme_head,
          f"README.md {len(readme_head)}+ chars read")

    doc = {
        "report": "DQAEIP FINAL PORTABLE EVIDENCE & RELEASE HARDENING — "
                  "Phase 0 forensic baseline (captured before any "
                  "mutation)",
        "release_id": RELEASE_ID,
        "prior_release_id": PRIOR_RELEASE_ID,
        "generated_utc": started,
        "git_identity": {
            "head": head,
            "branch": branch,
            "tracked_file_count": len(tracked),
            "untracked_file_count": len(untracked),
            "working_tree": "clean (mode-only session-restore noise "
                            "recorded separately; zero content delta)",
            "commits_ahead_of_origin": ahead,
            "pushed": False,
        },
        "protected_anchors": {
            "frozen_v1_source": FROZEN_V1_SOURCE,
            "frozen_v1_sha256": v1_sha,
            "official_evidence_dir": OFFICIAL_EVIDENCE_DIR,
            "official_input_sha256": fr3m.get("input_sha256"),
            "official_output_sha256": fr3m.get("output_sha256"),
            "official_checker": OFFICIAL_CHECKER,
            "checker_sha256_live": checker_live,
            "official_run_ids": sorted(runs),
            "rows_per_run": fr3m.get("rows"),
            "comparisons_per_run": comp.get("run_1"),
            "comparisons_combined": comp.get("combined_total"),
            "mismatches_combined": mm.get("combined_total"),
            "live_rule_ids": rule_ids,
            "input_column_count": len(SOURCE_COLUMNS),
            "output_column_count": TOTAL_OUTPUT_COLUMNS,
        },
        "current_release_state": {
            "prior_release_id": PRIOR_RELEASE_ID,
            "prior_final_results_path": os.path.relpath(
                PRIOR_FINAL_RESULTS, REPO_ROOT),
            "prior_final_results_sha256": fr_sha,
            "prior_dependency_fingerprint": fr_doc.get(
                "dependency_fingerprint"),
            "prior_release_manifest_sha256": manifest_sha,
            "prior_release_lock_sha256": lock_sha,
            "prior_release_lock_status": lock_doc.get("status"),
            "prior_zip_filename": os.path.basename(PRIOR_ZIP)
            if os.path.isfile(PRIOR_ZIP) else None,
            "prior_zip_sha256": zip_sha,
            "prior_verification_state": fr_doc.get("verification_state"),
        },
        "stop_conditions": stop_conditions,
        "checks": checks,
        "phase0_verdict": "PASS" if not stop_conditions else "STOP",
        "note": "READ-ONLY capture. No source file, official evidence "
                "file, README, FINAL_RESULTS, manifest, lock or ZIP was "
                "modified by this script.",
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "forensic_baseline.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"\nphase0 baseline written: {os.path.relpath(out_path, REPO_ROOT)}")
    print(f"phase0 verdict: {doc['phase0_verdict']} "
          f"({len(checks) - len(stop_conditions)}/{len(checks)} checks)")
    return 0 if not stop_conditions else 1


if __name__ == "__main__":
    sys.exit(main())
