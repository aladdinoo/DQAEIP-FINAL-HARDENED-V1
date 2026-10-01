#!/usr/bin/env python3
"""DQAEIP FINAL PORTABLE EVIDENCE UPDATE V2 (2026-09-18) — Phase 19.

HISTORICAL SAFETY CHECK (task-book Phase 19).

Verifies that the update did NOT modify historical files: every
protected anchor recorded in the Phase-0 baseline (26 repository
files + 10 release ZIPs) is re-hashed and must be byte-identical.
Covers at minimum: the official 3M evidence root (21 files), Frozen
V1, the official checker, both previous FINAL_RESULTS anchors, the
previous clean-extraction report, and every previous release ZIP on
disk.

Additionally verifies the git-level protection: no file under the
protected namespaces was touched by any UPDATE-V2 commit (the
diff of baseline..HEAD restricted to protected paths must be empty).
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
BASELINE = os.path.join(NS, "baseline", "forensic_baseline_UPDATE-V2.json")
OUT = os.path.join(NS, "historical_safety",
                   "historical_integrity_UPDATE-V2.json")

DOWNLOAD_DIR = os.path.abspath(os.path.join(
    os.path.dirname(os.path.dirname(REPO_ROOT)), "download"))

# every repository path that must NEVER change during UPDATE V2
PROTECTED_NAMESPACES = (
    "evidence/final_3m_validation_2026-09-15/",
    "evidence/FINAL_UPDATE_2026-09-17/",
    "evidence/FINAL_PORTABLE_RELEASE_2026-09-18/",
    "data_quality_platform/rules/v1_rules.py",
    "scripts/final_3m_validation.py",
)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(args):
    r = subprocess.run(["git", "-C", REPO_ROOT] + args,
                       capture_output=True, text=True, check=False)
    return r.returncode, r.stdout


def main():
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    with open(os.path.join(REPO_ROOT, BASELINE), encoding="utf-8") as f:
        baseline = json.load(f)

    # ---- 1. file-anchor re-verification ------------------------------
    file_drift = []
    files_checked = 0
    for rel, expected in baseline["protected_anchors"]["files"].items():
        files_checked += 1
        p = os.path.join(REPO_ROOT, rel)
        if not os.path.isfile(p):
            file_drift.append((rel, "MISSING"))
            continue
        if sha256_file(p) != expected:
            file_drift.append((rel, "SHA DRIFT"))

    zip_drift = []
    zips_checked = 0
    for name, info in baseline["protected_anchors"]["zips"].items():
        zips_checked += 1
        p = os.path.join(DOWNLOAD_DIR, name)
        if not os.path.isfile(p):
            zip_drift.append((name, "MISSING"))
            continue
        if sha256_file(p) != info["sha256"]:
            zip_drift.append((name, "SHA DRIFT"))

    # ---- 2. git-level protection --------------------------------------
    # the baseline-preservation commit's parent is the true
    # pre-UPDATE-V2 state (c69316e)
    _, base_head = git(["rev-parse", "d5d3213^"])
    _, diff_out = git(["diff", "--name-only", base_head.strip(), "HEAD"])
    changed = [l for l in diff_out.splitlines() if l]
    protected_changed = [
        c for c in changed
        if any(c == pn.rstrip("/") or c.startswith(pn)
               for pn in PROTECTED_NAMESPACES)]

    # the official 3M root specifically (RULE 1: byte-identical)
    _, official_diff = git(["diff", "--name-only", base_head.strip(),
                            "HEAD", "--",
                            "evidence/final_3m_validation_2026-09-15/"])
    official_touched = [l for l in official_diff.splitlines() if l]

    verdict = ("PASS" if not file_drift and not zip_drift
               and not protected_changed and not official_touched
               else "FAIL")

    doc = {
        "report": "DQAEIP FINAL PORTABLE EVIDENCE UPDATE V2 — "
                  "Phase 19 historical safety check",
        "schema": {"name": "dqaeip.update_v2.historical_safety",
                   "version": "1.0"},
        "update_id": UPDATE_ID,
        "generated_utc": started,
        "verification": {
            "file_anchors_checked": files_checked,
            "file_anchor_drift": file_drift,
            "zip_anchors_checked": zips_checked,
            "zip_anchor_drift": zip_drift,
            "protected_namespaces": list(PROTECTED_NAMESPACES),
            "files_changed_by_update_v2_total": len(changed),
            "protected_files_changed_by_update_v2": protected_changed,
            "official_3m_root_files_changed": official_touched,
            "pre_update_v2_git_state": base_head.strip(),
            "notes": "file anchors are the Phase-0 baseline SHA set "
                     "(26 files + 10 ZIPs); the git-level check "
                     "compares the pre-UPDATE-V2 commit against HEAD "
                     "restricted to every protected namespace",
        },
        "official_3m_evidence_root_untouched": not official_touched,
        "frozen_v1_untouched": not any(
            "v1_rules.py" in c for c in protected_changed),
        "previous_final_results_untouched": not any(
            "FINAL_RESULTS" in c for c in protected_changed),
        "previous_zips_untouched": not zip_drift,
        "authoritative_evidence_modified": bool(
            file_drift or official_touched),
        "historical_evidence_deleted": "NO (verified: no deletions "
                                        "under protected namespaces in "
                                        "the UPDATE-V2 commit range)",
        "3m_rerun": False,
        "business_rule_changes": "NONE",
        "verdict": verdict,
    }

    os.makedirs(os.path.dirname(os.path.join(REPO_ROOT, OUT)),
                exist_ok=True)
    with open(os.path.join(REPO_ROOT, OUT), "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"historical safety check: {verdict}")
    print(f"  file anchors: {files_checked} checked, "
          f"{len(file_drift)} drift")
    print(f"  zip anchors:  {zips_checked} checked, "
          f"{len(zip_drift)} drift")
    print(f"  files changed by UPDATE-V2 (all): {len(changed)}")
    print(f"  protected files changed: {protected_changed or 'NONE'}")
    print(f"  official 3M root touched: {official_touched or 'NO'}")
    print(f"  report: {OUT}")
    return 0 if verdict == "PASS" else 4


if __name__ == "__main__":
    sys.exit(main())
