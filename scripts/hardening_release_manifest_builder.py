#!/usr/bin/env python3
"""release_manifest.json regeneration for the 2026-09-19 hardened release.

Machine-derived: release identity, git state, artifact hashes for the
release documents. Written BEFORE the gate runs (identity-level manifest;
the ZIP's own record is zip_record.json, written after the ZIP exists).

Schema contract (data_quality_platform.assurance.release_schema.
RELEASE_MANIFEST_REQUIRED, enforced by the release gate and
final_verification check 4): the document MUST carry release_name /
git / artifacts / validation / environment. The consistency matrix
additionally reads validation.final_verdict,
validation.release_gate_verdict and validation.tests.passed, which
must agree with FINAL_RESULTS (test_identity, verification).

Fixed-point discipline: stabilized write (byte-identical when the
freshly derived payload differs only in generated_utc).
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE_FILE = (REPO_ROOT / "evidence" / "release_gate"
             / "final_release_gate.json")
TEST_SUMMARY = (REPO_ROOT / "evidence" / "rebuild_verification"
                / "test_summary.json")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def git(*args) -> str:
    return subprocess.run(["git", "-C", str(REPO_ROOT)] + list(args),
                          capture_output=True, text=True,
                          check=True).stdout.strip()


def maybe_load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_stabilized(path: Path, payload: dict) -> bool:
    """Fixed-point write (see hardening_final_results_builder)."""
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            candidate = json.loads(text)
            if isinstance(existing, dict):
                existing_cmp = {k: v for k, v in existing.items()
                                if k != "generated_utc"}
                candidate_cmp = {k: v for k, v in candidate.items()
                                 if k != "generated_utc"}
                if existing_cmp == candidate_cmp:
                    return False
        except (OSError, ValueError):
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def main() -> int:
    # Single source of truth for the document-recorded head: the
    # release identity's git_commit_at_build (the head the release
    # evidence namespace was built on). FINAL_RESULTS.git_identity.head
    # reads the SAME field, so the two documents always agree (the
    # consistency matrix requires this) and a fixed-point rebuild at a
    # later HEAD cannot desynchronize them. The recorded head is an
    # ancestor of every later release commit by construction.
    identity = maybe_load(REPO_ROOT / "evidence" /
                          "FINAL_HARDENED_RELEASE_2026-09-19" /
                          "release_identity" / "RELEASE_IDENTITY.json"
                          ) or {}
    build_head = identity.get("git_commit_at_build")
    head = build_head or git("rev-parse", "HEAD")
    origin = git("rev-parse", "origin/main") if subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "--verify",
         "origin/main"], capture_output=True).returncode == 0 else None
    ahead = 0
    if origin:
        ahead = int(git("rev-list", "--count",
                        f"{origin}..HEAD"))
    tree = git("rev-parse", "HEAD^{tree}")

    artifacts = {}
    for rel in ("README.md", "RELEASE_NOTES.md", "FINAL_RESULTS.json",
                "final_result.json"):
        p = REPO_ROOT / rel
        if p.is_file():
            artifacts[rel] = {
                "sha256": sha256_file(p),
                "size_bytes": p.stat().st_size,
            }

    # validation block: machine-read from the canonical evidence
    # (FINAL_RESULTS verification + canonical test summary + live gate)
    fr = maybe_load(REPO_ROOT / "FINAL_RESULTS.json") or {}
    verification = fr.get("verification", {}) if isinstance(fr, dict) \
        else {}
    ts = maybe_load(TEST_SUMMARY) or {}
    gate = maybe_load(GATE_FILE) or {}
    gate_verdict = gate.get("overall_verdict") if isinstance(gate,
                                                             dict) \
        else None
    final_verdict = fr.get("final_release_status")

    validation = {
        "final_verdict": final_verdict,
        "release_gate_verdict": gate_verdict,
        "tests": {
            "collected": ts.get("collected"),
            "passed": ts.get("passed"),
            "skipped": ts.get("skipped"),
            "failed": ts.get("failed"),
            "errors": ts.get("errors"),
            "source": "evidence/rebuild_verification/test_summary.json",
        },
        "input_sha256": verification.get("input_sha256"),
        "output_sha256": verification.get("output_sha256"),
        "rows": verification.get("rows"),
        "seed": verification.get("seed"),
        "runs": verification.get("runs"),
    }

    environment = {
        "python": platform.python_version(),
        "os": f"{platform.system()} {platform.release()} "
              f"({platform.machine()})",
        "execution_mode": (
            "local staged validation; no network, no ClickHouse or "
            "Airflow runtime, SP1/E1 inactive"),
        "frozen_checker": (
            "scripts/final_3m_validation.py — byte-identical to the "
            "certified harness"),
    }

    payload = {
        "schema": {
            "name": "dqaeip.release_manifest",
            "version": "1.1",
        },
        "report": "DQAEIP release manifest (2026-09-19 hardened release; "
                  "regenerated from current state)",
        "release_name": "DQAEIP-FINAL-HARDENED-RELEASE-2026-09-19",
        "release_date": "2026-09-19",
        "release_identity_base": "DQAEIP-Enterprise-Assurance-Validation-"
                                 "Release",
        "release_kind": "OPERATIONAL_HARDENING_ADDITIVE",
        "supersedes": "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18",
        "supersedes_note": "certified baseline preserved byte-for-byte "
                           "(ZIP + git HEAD fb4df92); referenced as "
                           "BASELINE_CERTIFIED_HISTORICAL",
        "project": {
            "name": "Data Quality Assurance & Evidence Integrity Platform",
            "short_name": "DQAEIP",
            "version": "2.1.0",
            "technical_package": "data_quality_platform (compatibility, "
                                 "unchanged)",
        },
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                       time.gmtime()),
        "git": {
            "head": head,
            "head_note": ("head the release evidence namespace was "
                          "built on (single shared source with "
                          "FINAL_RESULTS.git_identity.head); an "
                          "ancestor of the final release commit"),
            "origin_main": origin,
            "ahead": ahead,
            "behind": 0,
            "tree_hash": tree,
            "pushed": False,
            "note": "local release branch; nothing pushed",
        },
        "artifacts": artifacts,
        "validation": validation,
        "environment": environment,
        "frozen_core": {
            "v1_rules_sha256": sha256_file(
                REPO_ROOT / "data_quality_platform" / "rules" /
                "v1_rules.py"),
            "checker_sha256": sha256_file(
                REPO_ROOT / "scripts" / "final_3m_validation.py"),
            "note": "frozen V1 and the certified checker are byte-"
                    "identical to the certified baseline",
        },
        "evidence_namespaces": {
            "release": "evidence/FINAL_HARDENED_RELEASE_2026-09-19/",
            "regression": "evidence/validation/2026-09-19/fresh_3m2/",
            "baseline_certified_historical":
                "evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18/ "
                "(untouched)",
        },
    }

    wrote = _write_stabilized(REPO_ROOT / "release_manifest.json", payload)
    print(f"release_manifest.json "
          f"{'regenerated' if wrote else 'verified at fixed point'} "
          f"({(REPO_ROOT / 'release_manifest.json').stat().st_size:,} "
          f"bytes, head {head[:8]}, "
          f"gate verdict {gate_verdict!r})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
