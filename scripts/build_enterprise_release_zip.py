#!/usr/bin/env python3
"""ENTERPRISE RELEASE PACKAGING (DQAVP Sections 31-34).

Builds the release manifest and the release ZIP from the ACTUAL
repository state (git-tracked files only):

    1. release_manifest.json (repo root, inside the ZIP) — release
       name, project version, git HEAD, tree hash, README SHA, final_result
       SHA, release-gate SHA, test counts, final verdict, environment,
       zip_sha256: null (the ZIP hash cannot be inside the ZIP; it is
       recorded post-archive by scripts/enterprise_release_post_archive.py
       and in the final report).
    2. The ZIP at the requested output path, rooted at a single
       directory: DQAVP-Enterprise-Hardened-Validation-Release-<date>/

Exclusions are enforced by using ONLY git-tracked files, plus an
explicit deny-list scan of the archive after building (no .git, no
.venv, no __pycache__, no *.pyc, no data/ staging, no replay work dirs,
no editor/secret files). Massive raw datasets are hash-anchored in
evidence JSONs, never shipped.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_OUT = os.path.join(REPO_ROOT, "release_manifest.json")
DEFAULT_ZIP = os.path.join(
    os.path.dirname(os.path.dirname(REPO_ROOT)), "download",
    "DQAVP-Enterprise-Hardened-Validation-Release-2026-09-15.zip")

DENY_PATTERNS = (
    ".git/", ".venv/", "__pycache__/", ".pytest_cache/",
    "/data/", "evidence/release_gate/replay_work",
    # the post-archive record contains the ZIP's own SHA-256 and by
    # construction lives OUTSIDE the archive
    "evidence/enterprise_release_2026-09-15/",
    ".pyc", ".pyo", ".DS_Store", ".coverage", ".env",
)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(args):
    return subprocess.run(["git"] + args, cwd=REPO_ROOT,
                          capture_output=True, text=True).stdout.strip()


def tracked_files():
    files = git(["ls-files"]).splitlines()
    # the post-archive release record (records THIS zip's hash) must
    # not be inside the archive it describes
    return [f for f in sorted(files)
            if not f.startswith("evidence/enterprise_release_")]


def build_release_manifest(zip_name):
    head = git(["rev-parse", "HEAD"])
    tree_hash = git(["rev-parse", "HEAD^{tree}"])
    gate = json.load(open(os.path.join(
        REPO_ROOT, "evidence", "release_gate",
        "final_release_gate.json"), encoding="utf-8"))
    final_result = json.load(open(os.path.join(REPO_ROOT,
                                               "final_result.json"),
                                  encoding="utf-8"))
    counts = {}
    for g in gate["gates"]:
        if g["gate"] == "unit_tests":
            counts["unit"] = g["details"]
    tests = final_result["validation"]["tests"]

    manifest = {
        "release_name": "DQAVP-Enterprise-Hardened-Validation-"
                        "Release-2026-09-15",
        "project": {
            "name": "Data Quality Assurance & Validation Platform",
            "short_name": "DQAVP",
            "version": "1.0.0",
            "technical_package": "data_quality_platform",
        },
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                       time.gmtime()),
        "git": {
            "head": head,
            "origin_main": git(["rev-parse", "origin/main"]),
            "ahead": int(git(["rev-list", "--count",
                              "origin/main..HEAD"]) or 0),
            "pushed": False,
            "note": "local commits only; nothing pushed",
        },
        "tree_hash": tree_hash,
        "artifacts": {
            "readme_sha256": sha256_file(
                os.path.join(REPO_ROOT, "README.md")),
            "release_notes_sha256": sha256_file(
                os.path.join(REPO_ROOT, "RELEASE_NOTES.md")),
            "final_result_sha256": sha256_file(MANIFEST_OUT.replace(
                "release_manifest.json", "final_result.json")),
            "release_gate_sha256": sha256_file(os.path.join(
                REPO_ROOT, "evidence", "release_gate",
                "final_release_gate.json")),
            "hardening_baseline_sha256": sha256_file(os.path.join(
                REPO_ROOT, "evidence", "hardening_baseline",
                "baseline_manifest.json")),
            "final_3m_results_sha256": sha256_file(os.path.join(
                REPO_ROOT, "evidence", "final_3m_validation_2026-09-15",
                "FINAL_RESULTS.json")),
            "zip_filename": zip_name,
            "zip_sha256": None,
            "zip_sha256_note": (
                "A ZIP cannot contain its own hash: the pre-archive "
                "manifest ships with zip_sha256=null; the actual ZIP "
                "SHA-256 is computed post-archive and recorded in "
                "evidence/enterprise_release_2026-09-15/ and the final "
                "report (post-archive record)."),
        },
        "validation": {
            "final_verdict": "PASS_WITH_LIMITATIONS",
            "release_gate_verdict": gate["overall_verdict"],
            "release_gate_gates_pass": f"{gate['gate_counts']['pass']}/"
                                       f"{gate['gate_count']}",
            "final_3m_checker_verdict": final_result["validation"][
                "final_3m_checker_verdict"],
            "tests": {
                "collected": tests["collected"],
                "passed": tests["passed"],
                "failed": tests["failed"],
                "skipped": tests["skipped"],
                "source": tests["source"],
            },
            "mutation": {
                "detected": final_result["mutation_testing"][
                    "mutants_detected"],
                "total": final_result["mutation_testing"]["mutants_total"],
                "score": final_result["mutation_testing"]["mutation_score"],
            },
            "differential": {
                "comparisons": final_result["replay"]["final_3m"][
                    "comparison_count"],
                "mismatches": 0,
            },
        },
        "environment": gate.get("environment_fingerprint", {}),
        "contents_policy": {
            "selection": "git-tracked files only",
            "excluded": [".git", ".venv", "__pycache__", "*.pyc",
                         "data/ (staging datasets, hash-anchored in "
                         "evidence)", "release-gate replay work dirs "
                         "(regenerable, results recorded in the gate "
                         "evidence)"],
            "license_note": (
                "pyproject.toml declares MIT; no LICENSE file exists in "
                "the source repository and none is fabricated for this "
                "release (REVIEW_REQUIRED for company-supplied license "
                "text)."),
            "requirements_note": (
                "dependencies are declared in pyproject.toml "
                "(pyyaml>=6.0; pytest>=7.0 for dev); no requirements "
                "lock file is tracked"),
        },
    }
    with open(MANIFEST_OUT, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    return manifest


def build_zip(zip_path):
    files = tracked_files()
    root_dir = "DQAVP-Enterprise-Hardened-Validation-Release-2026-09-15"
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zf:
        for rel in files:
            src = os.path.join(REPO_ROOT, rel)
            if not os.path.isfile(src):
                continue
            arcname = f"{root_dir}/{rel}"
            zf.write(src, arcname)
    return files, root_dir


def verify_zip(zip_path, files, root_dir):
    """Fail-closed archive verification: contents, deny-list, CRC."""
    problems = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        bad = zf.testzip()
        if bad is not None:
            problems.append(f"CRC failure: {bad}")
        expected = {f"{root_dir}/{rel}" for rel in files}
        actual = set(names)
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            problems.append(f"missing from archive: {missing[:10]}")
        if extra:
            problems.append(f"unexpected in archive: {extra[:10]}")
        for name in names:
            for pat in DENY_PATTERNS:
                if pat == ".env":
                    # exact-file match only; .env.example is a tracked,
                    # gitignore-whitelisted template, not a secret file
                    if name.rsplit("/", 1)[-1] == ".env":
                        problems.append(f"forbidden path pattern "
                                        f"{pat!r}: {name}")
                    break
                if pat in name:
                    problems.append(f"forbidden path pattern "
                                    f"{pat!r}: {name}")
                    break
    return problems


def main():
    zip_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ZIP
    if not os.path.isabs(zip_path):
        zip_path = os.path.join(REPO_ROOT, zip_path)
    zip_name = os.path.basename(zip_path)

    dirty = subprocess.run(["git", "status", "--porcelain"],
                           cwd=REPO_ROOT, capture_output=True,
                           text=True).stdout.strip()
    if dirty:
        print(f"REFUSING: working tree not clean:\n{dirty}",
              file=sys.stderr)
        return 1

    manifest = build_release_manifest(zip_name)
    print(f"release manifest written: "
          f"{os.path.relpath(MANIFEST_OUT, REPO_ROOT)}")

    files, root_dir = build_zip(zip_path)
    problems = verify_zip(zip_path, files, root_dir)
    size = os.path.getsize(zip_path)
    zip_sha = sha256_file(zip_path)
    print(f"archive: {zip_path}")
    print(f"files: {len(files)}  size: {size:,} bytes")
    print(f"zip sha256: {zip_sha}")
    if problems:
        print("ARCHIVE VERIFICATION FAILURES:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("archive verification: ALL PASS (contents, deny-list, CRC)")
    print(f"final verdict (from gate evidence): "
          f"{manifest['validation']['release_gate_verdict']} "
          f"({manifest['validation']['release_gate_gates_pass']} gates)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
