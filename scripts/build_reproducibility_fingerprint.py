#!/usr/bin/env python3
"""DQAEIP ZERO-ASSUMPTION REBUILD — Phase 4F reproducibility
fingerprint.

Builds a DETERMINISTIC cryptographic fingerprint that binds the
release's reproducibility envelope:

    code identity        — SHA-256 over the frozen production sources
    rule-set identity    — SHA-256 of the Frozen V1 rule source
    schema identity      — SHA-256 of contracts.py + the official run
                           manifests' recorded schema hash
    checker identity     — SHA-256 of the 3M checker script
    test identity        — SHA-256 over the test tree (all test files)
    environment identity — python version + platform class (coarse,
                           deterministic)

The composite fingerprint is the SHA-256 over a canonical JSON
serialization (sorted keys, no whitespace) of exactly these
components. NONDETERMINISTIC VALUES (timestamps, durations, paths,
hostnames) ARE EXCLUDED from the cryptographic identity — they are
recorded separately as metadata, never hashed.

Output: evidence/release/reproducibility_fingerprint.json
"""

import hashlib
import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(
    REPO_ROOT, "evidence", "release", "reproducibility_fingerprint.json")

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

V1_SOURCE = "data_quality_platform/rules/v1_rules.py"
CHECKER = "scripts/final_3m_validation.py"
CONTRACTS = "data_quality_platform/contracts.py"
RUN_MANIFESTS = [
    "evidence/validation/2026-09-18/fresh_3m2/harness/pass1_engine/manifest.json",
    "evidence/validation/2026-09-18/fresh_3m2/harness/pass2_engine/manifest.json",
]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def concat_sha(files):
    """Deterministic concatenation hash: sorted relative paths, each
    contributing path + NUL + content SHA (path-stable, order-stable)."""
    h = hashlib.sha256()
    for rel in sorted(files):
        abs_p = os.path.join(REPO_ROOT, rel)
        if not os.path.isfile(abs_p):
            return None, rel
        h.update(rel.encode("utf-8") + b"\x00"
                 + sha256_file(abs_p).encode("ascii") + b"\x00")
    return h.hexdigest(), None


def canonical_hash(doc):
    return hashlib.sha256(
        json.dumps(doc, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")).hexdigest()


def main():
    import platform

    # ---- component identities (deterministic) ------------------------
    code_sha, missing = concat_sha(FROZEN_PRODUCTION_FILES)
    if code_sha is None:
        print(f"FAIL: frozen production file missing: {missing}")
        return 1
    rule_set_sha = sha256_file(os.path.join(REPO_ROOT, V1_SOURCE))
    checker_sha = sha256_file(os.path.join(REPO_ROOT, CHECKER))
    contracts_sha = sha256_file(os.path.join(REPO_ROOT, CONTRACTS))

    schema_hashes = []
    for rel in RUN_MANIFESTS:
        with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
            schema_hashes.append(json.load(f).get("schema_hash"))

    test_files = []
    tests_root = os.path.join(REPO_ROOT, "tests")
    for dirpath, _dirnames, filenames in os.walk(tests_root):
        for fn in sorted(filenames):
            if fn.startswith("test_") and fn.endswith(".py"):
                test_files.append(os.path.relpath(
                    os.path.join(dirpath, fn), REPO_ROOT).replace(
                        os.sep, "/"))
    tests_sha, _ = concat_sha(test_files)

    # ---- composite cryptographic identity -----------------------------
    identity = {
        "fingerprint_version": "1.0.0",
        "code_identity": {
            "algorithm": "sha256-over-sorted-(path,file-sha256)-pairs",
            "files": sorted(FROZEN_PRODUCTION_FILES),
            "sha256": code_sha,
        },
        "rule_set_identity": {
            "canonical_source": V1_SOURCE,
            "sha256": rule_set_sha,
        },
        "schema_identity": {
            "contracts_source": CONTRACTS,
            "contracts_sha256": contracts_sha,
            "official_run_schema_hashes": schema_hashes,
        },
        "checker_identity": {
            "path": CHECKER,
            "sha256": checker_sha,
        },
        "test_identity": {
            "algorithm": "sha256-over-sorted-(path,file-sha256)-pairs",
            "test_file_count": len(test_files),
            "sha256": tests_sha,
        },
        "environment_identity": {
            "python_version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "os_class": platform.system().lower(),
        },
    }
    fingerprint = canonical_hash(identity)

    out = {
        "report": "DQAEIP reproducibility fingerprint",
        "fingerprint_algorithm": (
            "SHA-256 over canonical JSON (sorted keys, no whitespace) of "
            "the six deterministic component identities"),
        "nondeterminism_policy": (
            "timestamps, durations, wall-clock values, machine-local "
            "paths, hostnames, and usernames are EXCLUDED from the "
            "cryptographic identity; they appear only in separate "
            "metadata fields and never participate in the hash"),
        "reproducibility_fingerprint_sha256": fingerprint,
        "components": identity,
        "regeneration_command": (
            ".venv/bin/python scripts/build_reproducibility_fingerprint.py"),
        "recorded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "recorded_utc_note": (
            "informational only; NOT part of the fingerprint hash"),
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"REPRODUCIBILITY FINGERPRINT written to "
          f"evidence/release/reproducibility_fingerprint.json")
    print(f"  fingerprint: {fingerprint}")
    print(f"  rule-set: {rule_set_sha[:16]}...  "
          f"checker: {checker_sha[:16]}...")
    print(f"  tests hashed: {len(test_files)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
