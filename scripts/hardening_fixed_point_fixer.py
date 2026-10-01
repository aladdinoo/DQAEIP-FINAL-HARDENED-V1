#!/usr/bin/env python3
"""Fixed-point fixer for the 2026-09-19 hardened release (one-time).

1. Writes tamper-evident evidence roots for the fresh regression engine
   evidence directories (pass1_engine / pass2_engine).
2. Re-points the gate-exercised assurance truth model from the 2026-09-18
   validation evidence path to the 2026-09-19 regression evidence path
   (the certified authorized re-pointing discipline: current validation
   location changes; historical namespaces are untouched).
3. Normalizes the session-restore mode-bit drift (100755 -> 100644) on
   tracked files with zero content delta, restoring the committed modes.

Fail-closed: any anomaly aborts.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from data_quality_platform.validation.evidence_root import (  # noqa: E402
    write_evidence_root,
)

REG = REPO_ROOT / "evidence" / "validation" / "2026-09-19" / "fresh_3m2"

OLD = "evidence/validation/2026-09-18/fresh_3m2/harness"
NEW = "evidence/validation/2026-09-19/fresh_3m2"

REPOINT_FILES = [
    "data_quality_platform/assurance/claims.py",
    "data_quality_platform/assurance/contradiction_checker.py",
    "data_quality_platform/assurance/golden_snapshot.py",
    "data_quality_platform/assurance/evidence_quarantine.py",
    "data_quality_platform/assurance/release_chain.py",
    "data_quality_platform/assurance/integrity.py",
    "scripts/consistency_matrix.py",
    "scripts/build_release_evidence_model.py",
    "scripts/readme_consistency_check.py",
]


def step_evidence_roots() -> None:
    for pass_dir in ("pass1_engine", "pass2_engine"):
        d = REG / pass_dir
        if not d.is_dir():
            raise SystemExit(f"FAIL-CLOSED: missing {d}")
        out = write_evidence_root(str(d))
        print(f"evidence root written: {d}/evidence_root.json")


def step_repoint() -> None:
    for rel in REPOINT_FILES:
        p = REPO_ROOT / rel
        if not p.is_file():
            raise SystemExit(f"FAIL-CLOSED: missing {rel}")
        text = p.read_text(encoding="utf-8")
        count = text.count(OLD)
        if count == 0:
            print(f"  [skip] {rel}: no current-validation pins")
            continue
        p.write_text(text.replace(OLD, NEW), encoding="utf-8")
        print(f"  [re-point] {rel}: {count} pin(s) -> 2026-09-19")


def step_mode_normalization() -> None:
    rc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "diff", "--numstat"],
        capture_output=True, text=True, check=True)
    mode_only = []
    for line in rc.stdout.splitlines():
        adds, dels, path = line.split("\t")
        if adds == "0" and dels == "0":
            mode_only.append(path)
    for path in mode_only:
        target = REPO_ROOT / path
        if target.is_file():
            os.chmod(target, 0o644)
    print(f"  [modes] normalized {len(mode_only)} mode-only drifted files"
          f" to 0644")


def main() -> int:
    print("step 1: evidence roots")
    step_evidence_roots()
    print("step 2: assurance truth-model re-point (2026-09-18 harness "
          "-> 2026-09-19 regression)")
    step_repoint()
    print("step 3: mode-bit drift normalization")
    step_mode_normalization()
    print("fixed-point fixer complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
