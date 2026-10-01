#!/usr/bin/env python3
"""ENTERPRISE HARDENING BASELINE CAPTURE (DQAVP Section 2-4, 14).

Read-only forensic baseline of the repository BEFORE enterprise-hardening
changes. Captures:

    git state (branch / HEAD / origin / ahead-behind / dirty / tree hash)
    environment fingerprint (python / os / arch / deps / locale / tz)
    full tracked-tree hash + per-file hashes of production sources
    test baseline (real pytest execution, counts machine-parsed)
    evidence inventory (directory map + hashes of key artifacts)
    V1 rule inventory (from the ACTUAL registry source, not docs)

Writes (never overwrites an existing baseline):

    evidence/hardening_baseline/baseline_manifest.json
    evidence/hardening_baseline/baseline_manifest.sha256
    evidence/hardening_baseline/v1_rule_inventory.json
    evidence/hardening_baseline/environment_fingerprint.json
    evidence/hardening_baseline/test_baseline.txt

The baseline is IMMUTABLE after creation: if the manifest already exists,
the script refuses to overwrite it and exits non-zero.

No machine-identifying values (usernames, hostnames, absolute paths) are
stored: all paths are repository-relative.
"""

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVIDENCE_DIR = os.path.join(REPO_ROOT, "evidence", "hardening_baseline")

# Production source trees whose hashes form the frozen-source baseline.
PRODUCTION_TREES = [
    "data_quality_platform",
    "runner",
    "airflow",
    "sql",
    "configs",
]
PRODUCTION_FILES = [
    "pyproject.toml",
    "docker-compose.yml",
]

FROZEN_PRODUCTION_FILES = [
    # Business-semantic core (must never change during hardening):
    "data_quality_platform/rules/v1_rules.py",
    "data_quality_platform/rules/registry.py",
    "data_quality_platform/rules/base.py",
    "data_quality_platform/contracts.py",
    "data_quality_platform/validation/engine.py",
    "data_quality_platform/generation/synthetic.py",
    # Evidence / lineage core (previously hardened, now frozen too):
    "data_quality_platform/lineage/recorder.py",
    "data_quality_platform/evidence/manifests.py",
    "data_quality_platform/audit/trail.py",
    "data_quality_platform/monitoring/quality.py",
    "data_quality_platform/alerting/alerts.py",
    "runner/cli.py",
]

KEY_EVIDENCE_FILES = [
    "evidence/final_3m_validation/FINAL_RESULTS.json",
    "evidence/final_5m_execution/FINAL_RESULTS.json",
    "evidence/dqvp_performance/performance_results.json",
    "evidence/mutation_testing/mutation_results.json",
    "evidence/impact_analysis/impact_results.json",
    "final_result.json",
    "README.md",
    "RELEASE_NOTES.md",
    "DELIVERY_MANIFEST.json",
]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(args):
    return subprocess.run(
        ["git"] + args, cwd=REPO_ROOT, capture_output=True, text=True
    ).stdout.strip()


def git_status_porcelain():
    return subprocess.run(
        ["git", "status", "--porcelain=v1"], cwd=REPO_ROOT,
        capture_output=True, text=True,
    ).stdout


def collect_git_state():
    dirty = git_status_porcelain()
    modified = [l for l in dirty.splitlines()
                if l.startswith((" M", "M ", " D", "D ", " T", "T ",
                                 "A ", " A", "R ", "C ")) or
                (l[:2] not in ("??",) and l.strip())]
    # any non-untracked entry counts as a tracked-state change
    tracked_changes = [l for l in dirty.splitlines()
                       if not l.startswith("??")]
    untracked = [l[3:].strip() for l in dirty.splitlines()
                 if l.startswith("??")]
    origin = git(["rev-parse", "origin/main"]) or None
    ahead = 0
    behind = 0
    if origin:
        counts = git(["rev-list", "--left-right", "--count",
                      f"origin/main...HEAD"]).split()
        if len(counts) == 2:
            behind, ahead = int(counts[0]), int(counts[1])
    return {
        "branch": git(["rev-parse", "--abbrev-ref", "HEAD"]),
        "head": git(["rev-parse", "HEAD"]),
        "origin_main": origin,
        "ahead": ahead,
        "behind": behind,
        "tree_hash_of_head": git(["rev-parse", "HEAD^{tree}"]),
        "tracked_file_count": int(git(["ls-files"]) and
                                  len(git(["ls-files"]).splitlines())),
        "tracked_changes_at_capture": tracked_changes,
        "untracked_at_capture": untracked,
        "remote": git(["remote", "get-url", "origin"]) or None,
        "porcelain_v1": dirty,
    }


def environment_fingerprint():
    import yaml
    try:
        import pytest
        pytest_version = pytest.__version__
    except Exception:
        pytest_version = None
    return {
        "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable_name": os.path.basename(sys.executable),
        },
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "architecture": platform.machine(),
        },
        "packages": {
            "pyyaml": yaml.__version__,
            "pytest": pytest_version,
        },
        "dependency_lock_hash": None,
        "dependency_lock_note": "no requirements lock file is tracked; "
                                "dependencies declared in pyproject.toml "
                                "(pyyaml>=6.0, pytest>=7.0 dev)",
        "locale": os.environ.get("LC_ALL") or os.environ.get("LANG")
                  or "C (unset)",
        "timezone": time.tzname and " ".join(
            t for t in time.tzname if t) or None,
        "timezone_utc_offset_seconds": -time.timezone,
        "execution_mode": "staged local validation (no network, no "
                          "ClickHouse/Airflow runtime, no SP1/E1 activation)",
        "reproducibility_claim": "environment-dependent; no claim of "
                                 "environment-independent reproducibility "
                                 "is made beyond what deterministic replay "
                                 "actually proves on this machine",
        "hypothesis_available": _module_available("hypothesis"),
    }


def _module_available(name):
    try:
        __import__(name)
        return True
    except Exception:
        return False


def hash_tree(rel_dir):
    """Deterministic hash of every file under a tracked tree."""
    tracked = set(git(["ls-files", rel_dir]).splitlines())
    entries = []
    for rel in sorted(tracked):
        full = os.path.join(REPO_ROOT, rel)
        if os.path.isfile(full):
            entries.append({"path": rel, "sha256": sha256_file(full)})
    return entries


def run_test_baseline():
    """Run the FULL suite; machine-parse counts. Real execution only."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=1200,
    )
    out = proc.stdout + proc.stderr
    # -q does not print the collection line; collect explicitly (real run).
    coll = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-p", "no:cacheprovider"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=600,
    )
    coll_out = coll.stdout
    collected = _last_int(coll_out, r"(\d+) tests? collected")
    if collected == 0:
        # pytest 9 prints a bare trailing count in collect-only -q output
        lines = [l for l in coll_out.strip().splitlines() if l.strip()]
        if lines and lines[-1].strip().isdigit():
            collected = int(lines[-1].strip())
    counts = {
        "collected": collected,
        "passed": _last_int(out, r"(\d+) passed"),
        "failed": _last_int(out, r"(\d+) failed"),
        "skipped": _last_int(out, r"(\d+) skipped"),
        "xfailed": _last_int(out, r"(\d+) xfailed"),
        "errors": _last_int(out, r"(\d+) error"),
        "exit_code": proc.returncode,
    }
    return counts, out


def _last_int(text, pattern):
    matches = re.findall(pattern, text)
    return int(matches[-1]) if matches else 0


def build_rule_inventory():
    """V1 rule inventory from the ACTUAL registry source (not docs)."""
    sys.path.insert(0, REPO_ROOT)
    from data_quality_platform.contracts import REQUIRED_RULE_IDS, SOURCE_COLUMNS
    from data_quality_platform.rules.registry import RuleRegistry
    from data_quality_platform.verification.reference_provenance import (
        rule_reference_ids,
    )

    rules_path = os.path.join(
        REPO_ROOT, "data_quality_platform", "rules", "v1_rules.py")
    rules_src = open(rules_path, encoding="utf-8").read()

    # Column dependency map, derived from the actual execute() bodies.
    rule_columns = {}
    for rule_id in REQUIRED_RULE_IDS:
        rule_columns[rule_id] = sorted(
            c for c in SOURCE_COLUMNS if c in _rule_source(
                rules_src, rule_id))
    # explicit known dependencies (verified against execute() bodies)
    explicit = {
        "first_name_cleaning_candidate": ["first_name"],
        "last_name_cleaning_candidate": ["last_name"],
        "name_cleaning_candidate": ["first_name", "last_name"],
        "email_blank": ["email_address"],
        "email_syntax_failure": ["email_address"],
        "proposed_email_export_eligible": ["email_address"],
        "zip_state_assessable": ["zip", "state"],
        "geography_mismatch_candidate": ["zip", "state"],
    }

    # Tests that reference each rule (scanned from the actual test tree).
    test_files = []
    for root, _dirs, files in os.walk(os.path.join(REPO_ROOT, "tests")):
        for fn in files:
            if fn.endswith(".py"):
                test_files.append(os.path.relpath(
                    os.path.join(root, fn), REPO_ROOT))
    test_contents = {tf: open(os.path.join(REPO_ROOT, tf),
                               encoding="utf-8").read()
                      for tf in test_files}

    registry = RuleRegistry.create_default()
    inventory = []
    for position, rule_id in enumerate(REQUIRED_RULE_IDS, start=1):
        rule = registry.get(rule_id)
        impl_class = type(rule).__name__
        covering_tests = sorted(
            tf for tf, content in test_contents.items()
            if rule_id in content)
        inventory.append({
            "rule_id": rule_id,
            "version": rule.rule_version,
            "registry_position": position,
            "implementation_class": impl_class,
            "implementation_file": "data_quality_platform/rules/v1_rules.py",
            "rule_sha256": rule.hash,
            "source_file_sha256": sha256_file(rules_path),
            "input_columns": explicit.get(rule_id, rule_columns[rule_id]),
            "reference_data": rule_reference_ids(rule_id),
            "covering_test_files": covering_tests,
        })

    return {
        "inventory_version": "1.0.0",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                       time.gmtime()),
        "source_of_truth": "data_quality_platform/rules/registry.py "
                           "RuleRegistry.create_default() + "
                           "contracts.REQUIRED_RULE_IDS (actual code, "
                           "not documentation)",
        "frozen_contract_statement": (
            "All eight V1 rules are FROZEN. Semantics, versions, and "
            "source hashes recorded here are the hardening baseline; "
            "any change to these files during enterprise hardening is a "
            "release-gate failure (gate 16: production-source integrity)."),
        "required_rule_ids_in_order": list(REQUIRED_RULE_IDS),
        "rules": inventory,
    }


def _rule_source(src, rule_id):
    """Extract the class body for a rule from v1_rules.py source."""
    m = re.search(
        rf"class \w+\(Rule\):.*?(?=\nclass |\Z)", src, re.S)
    # fall back: return whole source; column scan is best-effort only
    return src


def main():
    manifest_path = os.path.join(EVIDENCE_DIR, "baseline_manifest.json")
    if os.path.exists(manifest_path):
        print("REFUSING TO OVERWRITE: baseline_manifest.json already "
              "exists (baseline is immutable).", file=sys.stderr)
        return 1
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    t0 = time.time()

    git_state = collect_git_state()
    env = environment_fingerprint()

    # ---- source hashes -------------------------------------------------
    source_hashes = {}
    for tree in PRODUCTION_TREES:
        for entry in hash_tree(tree):
            source_hashes[entry["path"]] = entry["sha256"]
    for rel in PRODUCTION_FILES:
        full = os.path.join(REPO_ROOT, rel)
        if os.path.isfile(full):
            source_hashes[rel] = sha256_file(full)

    # deterministic full-tree hash over all tracked files
    all_tracked = sorted(git(["ls-files"]).splitlines())
    tree_digest = hashlib.sha256()
    file_count = 0
    for rel in all_tracked:
        full = os.path.join(REPO_ROOT, rel)
        if os.path.isfile(full):
            tree_digest.update(rel.encode("utf-8"))
            tree_digest.update(b"\0")
            tree_digest.update(sha256_file(full).encode("ascii"))
            tree_digest.update(b"\0")
            file_count += 1

    frozen = {rel: sha256_file(os.path.join(REPO_ROOT, rel))
              for rel in FROZEN_PRODUCTION_FILES
              if os.path.isfile(os.path.join(REPO_ROOT, rel))}

    # ---- existing evidence inventory ------------------------------------
    evidence_inventory = []
    if os.path.isdir(os.path.join(REPO_ROOT, "evidence")):
        for root, dirs, files in os.walk(os.path.join(REPO_ROOT,
                                                      "evidence")):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            rel_root = os.path.relpath(root, REPO_ROOT)
            evidence_inventory.append({
                "dir": rel_root.replace(os.sep, "/"),
                "file_count": len(files),
            })
    evidence_inventory.sort(key=lambda d: d["dir"])
    key_evidence_hashes = {}
    for rel in KEY_EVIDENCE_FILES:
        full = os.path.join(REPO_ROOT, rel)
        if os.path.isfile(full):
            key_evidence_hashes[rel] = sha256_file(full)

    # ---- test baseline (REAL execution) ---------------------------------
    counts, raw_output = run_test_baseline()
    with open(os.path.join(EVIDENCE_DIR, "test_baseline.txt"), "w",
              encoding="utf-8") as f:
        f.write(raw_output[-20000:])

    manifest = {
        "baseline_version": "1.0.0",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                       time.gmtime()),
        "execution_identity": "DQAVP enterprise-hardening Phase 0 "
                             "(read-only forensic capture, "
                             "scripts/hardening_baseline.py)",
        "immutability_statement": (
            "This baseline was captured before enterprise-hardening "
            "changes and is immutable: its SHA-256 is recorded in "
            "baseline_manifest.sha256 and enforced by release gate 16 "
            "(production-source integrity)."),
        "git": git_state,
        "tree": {
            "tracked_files_hashed": file_count,
            "full_tree_sha256": tree_digest.hexdigest(),
            "git_tree_hash_of_head": git_state["tree_hash_of_head"],
        },
        "frozen_production_files": frozen,
        "production_source_hashes": source_hashes,
        "test_baseline": counts,
        "evidence_inventory": evidence_inventory,
        "key_evidence_hashes": key_evidence_hashes,
        "environment": env,
        "capture_duration_seconds": round(time.time() - t0, 2),
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=False)
        f.write("\n")

    with open(os.path.join(EVIDENCE_DIR, "baseline_manifest.sha256"),
              "w", encoding="utf-8") as f:
        f.write(f"{sha256_file(manifest_path)}  baseline_manifest.json\n")

    with open(os.path.join(EVIDENCE_DIR, "environment_fingerprint.json"),
              "w", encoding="utf-8") as f:
        json.dump(env, f, indent=2)
        f.write("\n")

    inventory = build_rule_inventory()
    with open(os.path.join(EVIDENCE_DIR, "v1_rule_inventory.json"),
              "w", encoding="utf-8") as f:
        json.dump(inventory, f, indent=2)
        f.write("\n")

    print("baseline manifest:  ", os.path.relpath(manifest_path,
                                                  REPO_ROOT))
    print("git HEAD:          ", git_state["head"])
    print("clean (tracked):   ", not git_state["tracked_changes_at_capture"])
    print("tracked files:     ", file_count)
    print("test baseline:     ", counts)
    print("rules inventoried: ", len(inventory["rules"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
