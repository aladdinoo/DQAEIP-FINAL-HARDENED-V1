#!/usr/bin/env python3
"""DQAEIP ZERO-ASSUMPTION REBUILD — Phase 4C evidence quarantine
screening runner.

Screens the release evidence set through the assurance-layer
classifier:

    expected inventory  = the release artifact manifest (path ->
                           SHA-256; every pinned entry)
    trusted set         = the official 3M evidence roots
    current identities  = the actual checker file hash + the recorded
                           gate count (for STALE detection)

Output: evidence/release/evidence_quarantine_screen.json

Exit code 0 only when the screening verdict is CLEAN (no STALE /
FOREIGN / TAMPERED / QUARANTINED artifact). Untrusted evidence can
never raise a release verdict — the report states this explicitly.
"""

import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(
    REPO_ROOT, "evidence", "release", "evidence_quarantine_screen.json")

MANIFEST = "evidence/release/release_artifact_manifest.json"
TRUSTED_SET = [
    "evidence/validation/2026-09-18/fresh_3m2/harness/FINAL_RESULTS.json",
    "evidence/validation/2026-09-18/fresh_3m2/harness/pass1_engine/manifest.json",
    "evidence/validation/2026-09-18/fresh_3m2/harness/pass1_engine/evidence_root.json",
    "evidence/validation/2026-09-18/fresh_3m2/harness/pass2_engine/manifest.json",
    "evidence/validation/2026-09-18/fresh_3m2/harness/pass2_engine/evidence_root.json",
]


def main():
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)
    from data_quality_platform.assurance.evidence_quarantine import (
        EvidenceQuarantine,
    )

    with open(os.path.join(REPO_ROOT, MANIFEST), encoding="utf-8") as f:
        manifest = json.load(f)

    expected = {}
    for entry in manifest.get("artifacts", []):
        rel = entry.get("path")
        sha = entry.get("sha256")
        if rel and entry.get("status") != "PENDING_POST_ZIP_REBUILD":
            expected[rel] = sha

    # Current identities for STALE detection.
    import hashlib
    checker_path = os.path.join(
        REPO_ROOT, "scripts", "final_3m_validation.py")
    checker_sha = None
    if os.path.isfile(checker_path):
        h = hashlib.sha256()
        with open(checker_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        checker_sha = h.hexdigest()

    gate_count = None
    gate_path = os.path.join(
        REPO_ROOT, "evidence/release_gate/final_release_gate.json")
    if os.path.isfile(gate_path):
        with open(gate_path, encoding="utf-8") as f:
            gate_count = json.load(f).get("gate_count")

    q = EvidenceQuarantine(
        expected, trusted_set=TRUSTED_SET,
        current_identities={
            "checker_sha256": checker_sha,
            "gate_count": gate_count,
        })
    # SELF-EXCLUSION (documented): the screening report cannot verify
    # its own pre-measurement state — every re-run rewrites this file
    # (fresh timestamp), so classifying it against the manifest pin
    # would always self-flag as TAMPERED. The screen file's integrity
    # is instead enforced by the release artifact manifest (which pins
    # its exact SHA-256) and by the manifest's zero-drift verification.
    self_path = os.path.relpath(OUT, REPO_ROOT).replace(os.sep, "/")
    screen_paths = [p for p in sorted(expected) if p != self_path]
    report = q.screen(REPO_ROOT, paths=screen_paths)
    report["self_exclusion"] = {
        "path": self_path,
        "reason": ("the screening report cannot pin its own "
                   "pre-measurement state; its integrity is enforced "
                   "by the release artifact manifest pin and zero-drift "
                   "verification"),
    }
    report["report"] = (
        "DQAEIP evidence quarantine screening (release evidence set "
        "from the release artifact manifest)")
    report["expected_inventory_source"] = MANIFEST
    report["trusted_set"] = TRUSTED_SET
    report["current_identities"] = {
        "checker_sha256": checker_sha,
        "gate_count": gate_count,
    }
    report["generated_utc"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"EVIDENCE QUARANTINE SCREEN: {report['verdict']}")
    print(f"  screened: {report['screened']}")
    for cls, n in sorted(report["classification_counts"].items()):
        print(f"  {cls}: {n}")
    if report["rejected"]:
        for r in report["rejected"][:10]:
            print(f"    ! [{r['classification']}] {r['path']}: "
                  f"{r['reason']}")
    return 0 if report["verdict"] == "CLEAN" else 1


if __name__ == "__main__":
    sys.exit(main())
