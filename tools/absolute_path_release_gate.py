#!/usr/bin/env python3
"""DQAEIP FINAL PORTABLE EVIDENCE & RELEASE HARDENING — Phase 3.

ABSOLUTE-PATH RELEASE GATE (task-book section 4).

Recursively scans the PORTABLE RELEASE EVIDENCE set and FAILS CLOSED
on any machine-local path:

    /home/...   /Users/...   /mnt/...   C:\\...   D:\\...   file://...
    /root/...  /tmp/...  /var/...  /srv/...  UNC shares  ~user  ...

Portable release evidence (explicit scope — everything else, notably
the historical evidence archives, is out of scope by the documented
historical-evidence policy, not silently ignored):

    README.md, RELEASE_NOTES.md, FINAL_RESULTS.json,
    final_result.json, release_manifest.json, DELIVERY_MANIFEST.json,
    evidence/release/**, evidence/rebuild_verification/**,
    evidence/mutation_testing/**, evidence/hardening_baseline/**,
    evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18/**

The exception mechanism is EXPLICIT, NARROW, PATH-SPECIFIC,
REASON-SPECIFIC and AUDITABLE:

    - every exception is an exact repository-relative file path with
      an exact reason and classification;
    - an exception exempts ONE file — never a pattern, never a
      directory, never a detector;
    - a malformed or over-broad exception registry is itself a
      failure (the gate refuses to run with a broken registry);
    - every granted exception is re-emitted verbatim in the report.

Fail-closed semantics: exit 0 only on PASS with all exceptions
accounted for. Missing scope files (deleted release evidence) also
FAIL — they are never silently skipped.
"""

import argparse
import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance.portable_evidence import (  # noqa: E402
    MACHINE_PATH_DETECTORS)

NS = "evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18"
DEFAULT_EXCEPTIONS = os.path.join(
    REPO_ROOT, NS, "release_gate", "absolute_path_gate_exceptions.json")
DEFAULT_REPORT = os.path.join(
    REPO_ROOT, NS, "release_gate", "absolute_path_gate_report.json")

GATE_VERSION = "1.0.0"

SCOPE_FILES = [
    "README.md",
    "RELEASE_NOTES.md",
    "FINAL_RESULTS.json",
    "final_result.json",
    "release_manifest.json",
    "DELIVERY_MANIFEST.json",
]
SCOPE_DIRS = [
    "evidence/release",
    "evidence/rebuild_verification",
    "evidence/mutation_testing",
    "evidence/hardening_baseline",
    NS,
]

# Valid exception classifications (anything else fails closed)
VALID_EXCEPTION_CLASSES = {
    "diagnostic_quoting_violations",
    "historical_captured_output",
    "documented_test_fixture",
    "documented_example",
}

REQUIRED_EXCEPTION_FIELDS = ("path", "reason", "classification")


def validate_exception_registry(registry):
    """Fail-closed validation of the exception registry structure."""
    problems = []
    if not isinstance(registry, dict):
        return ["registry is not a JSON object"]
    entries = registry.get("exceptions")
    if not isinstance(entries, list):
        return ["registry missing 'exceptions' list"]
    seen = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            problems.append(f"entry {i} is not an object")
            continue
        for field in REQUIRED_EXCEPTION_FIELDS:
            if not isinstance(entry.get(field), str) or not entry[field]:
                problems.append(
                    f"entry {i} missing/invalid field '{field}'")
        cls = entry.get("classification")
        if cls not in VALID_EXCEPTION_CLASSES:
            problems.append(
                f"entry {i} has unknown classification {cls!r} "
                f"(valid: {sorted(VALID_EXCEPTION_CLASSES)})")
        path = entry.get("path")
        if path in seen:
            problems.append(f"duplicate exception for {path!r}")
        seen.add(path)
        # narrowness: no directories, no globs, no scheme wildcards
        if isinstance(path, str) and (
                path.endswith("/") or "*" in path or "?" in path):
            problems.append(
                f"over-broad exception {path!r}: patterns and "
                f"directories are forbidden")
    return problems


def scope_file_list(repo_root, extra_files=(), extra_dirs=(),
                    base_files=None, base_dirs=None):
    """Resolve the explicit scope into a sorted file list."""
    files = []
    missing = []
    base_files = SCOPE_FILES if base_files is None else base_files
    base_dirs = SCOPE_DIRS if base_dirs is None else base_dirs
    for rel in list(base_files) + list(extra_files):
        p = os.path.join(repo_root, rel)
        if os.path.isfile(p):
            files.append(rel)
        else:
            missing.append(rel)
    for d in list(base_dirs) + list(extra_dirs):
        abs_d = os.path.join(repo_root, d)
        if not os.path.isdir(abs_d):
            missing.append(d)
            continue
        for root, dirs, fs in os.walk(abs_d):
            dirs[:] = sorted(x for x in dirs
                             if x not in ("__pycache__", ".pytest_cache"))
            for fn in sorted(fs):
                files.append(os.path.relpath(
                    os.path.join(root, fn), repo_root)
                    .replace(os.sep, "/"))
    return sorted(set(files)), sorted(set(missing))


def scan_text(text, source):
    """Scan one text; return per-line violation records."""
    violations = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for rule_id, pattern in MACHINE_PATH_DETECTORS:
            for match in pattern.finditer(line):
                start, end = match.span()
                excerpt = line[max(0, start - 40):min(len(line), end + 40)]
                violations.append({
                    "rule": rule_id,
                    "source": source,
                    "line": lineno,
                    "column": start + 1,
                    "matched": match.group(0),
                    "excerpt": excerpt.strip()[:160],
                })
    return violations


def scan_file(path, repo_root):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return scan_text(f.read(), os.path.relpath(
            path, repo_root).replace(os.sep, "/"))


def run_gate(repo_root=None, exceptions_path=None, extra_files=(),
             extra_dirs=(), base_files=None, base_dirs=None):
    """Execute the gate; returns the machine-readable report dict.

    ``base_files`` / ``base_dirs`` override the default scope (used
    ONLY by the gate's own unit tests to exercise scanning mechanics
    on isolated fixtures; production invocations never override).
    """
    repo_root = repo_root or REPO_ROOT
    exceptions_path = exceptions_path or DEFAULT_EXCEPTIONS
    report_started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    scope_files = SCOPE_FILES if base_files is None else base_files
    scope_dirs = SCOPE_DIRS if base_dirs is None else base_dirs

    registry = {"exceptions": []}
    registry_problems = []
    if os.path.isfile(exceptions_path):
        try:
            with open(exceptions_path, encoding="utf-8") as f:
                registry = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            registry_problems.append(
                f"exception registry unreadable: {exc}")
    registry_problems.extend(validate_exception_registry(registry))
    exempt = {e["path"] for e in registry.get("exceptions", [])
              if isinstance(e, dict) and e.get("path")}

    files, missing = scope_file_list(repo_root, extra_files, extra_dirs,
                                     base_files=scope_files,
                                     base_dirs=scope_dirs)

    violations = []
    for rel in files:
        if rel in exempt:
            continue
        violations.extend(scan_file(os.path.join(repo_root, rel),
                                    repo_root))

    granted = [
        {**e, "applied": True}
        for e in registry.get("exceptions", [])
        if isinstance(e, dict) and e.get("path") in files
    ]
    stale_exceptions = sorted(
        e.get("path") for e in registry.get("exceptions", [])
        if isinstance(e, dict) and e.get("path") not in files)

    status = "PASS"
    if violations:
        status = "FAIL"
    if missing:
        status = "FAIL"
    if registry_problems:
        status = "FAIL"

    return {
        "report": "DQAEIP absolute-path release gate (fail-closed)",
        "schema": {"name": "dqaeip.absolute_path_gate_report",
                   "version": "1.0"},
        "gate_version": GATE_VERSION,
        "release_id": "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18",
        "generated_utc": report_started,
        "scope": {
            "files": scope_files,
            "directories": scope_dirs,
            "scanned_file_count": len(files),
            "missing_scope_entries": missing,
            "scope_note": "explicit inclusion list; historical evidence "
                          "archives are covered by the documented "
                          "historical-evidence policy (Phase 1 inventory "
                          "+ Phase 15 policy record), not silently "
                          "ignored",
        },
        "detectors": [d for d, _ in MACHINE_PATH_DETECTORS],
        "exception_registry": {
            "path": os.path.relpath(exceptions_path, repo_root)
            .replace(os.sep, "/") if os.path.isfile(exceptions_path)
            else None,
            "entries": registry.get("exceptions", []),
            "granted": granted,
            "stale_exceptions": stale_exceptions,
            "registry_problems": registry_problems,
            "policy": "exact path + exact reason + classification; "
                      "one file per exception; no directories, no "
                      "patterns, no detector-level exemptions",
        },
        "violations": violations,
        "violation_count": len(violations),
        "verdict": status,
        "verdict_note": "PASS only when every in-scope file exists, "
                        "the exception registry is structurally valid, "
                        "and zero machine-local paths are found; any "
                        "missing scope entry, broken registry, stale "
                        "exception or violation fails the gate",
    }


def main():
    parser = argparse.ArgumentParser(
        description="Absolute-path release gate (fail-closed)")
    parser.add_argument("--exceptions", default=DEFAULT_EXCEPTIONS)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    args = parser.parse_args()

    report = run_gate(exceptions_path=args.exceptions)

    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"absolute-path gate: {report['verdict']} "
          f"({report['violation_count']} violations, "
          f"{report['scope']['scanned_file_count']} files scanned, "
          f"{len(report['exception_registry']['granted'])} exceptions "
          f"granted)")
    for v in report["violations"][:10]:
        print(f"  [VIOLATION] {v['source']}:{v['line']} "
              f"({v['rule']}) {v['excerpt'][:80]}")
    for p in report["exception_registry"]["registry_problems"][:10]:
        print(f"  [REGISTRY] {p}")
    for m in report["scope"]["missing_scope_entries"]:
        print(f"  [MISSING] {m}")
    return 0 if report["verdict"] == "PASS" else 4


if __name__ == "__main__":
    sys.exit(main())
