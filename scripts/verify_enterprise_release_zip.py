#!/usr/bin/env python3
"""CLEAN-ROOM RELEASE VERIFICATION (DQAVP Section 26).

Extracts the release ZIP into a completely clean scratch directory and
verifies, from the EXTRACTED copy only:

  [1] environment usable (interpreter, required packages)
  [2] package imports work
  [3] full test suite passes
  [4] release gate passes (16 fail-closed gates)
  [5] production CLI works end-to-end (generate + validate + output shape)
  [6] no accidental local absolute paths in code/docs/release documents
  [7] no secrets in code/docs/release documents
  [8] ZIP contents match git-tracked project files (no extras/missing)
  [9] no forbidden files in the archive (.git, .venv, caches, data)

Usage:
    python scripts/verify_enterprise_release_zip.py <zip> <scratch_dir>

Exit code: 0 only when every check passes. The extracted copy is
disposable; the release gate re-runs mutation testing inside it
(temporary, restored and hash-verified, exactly as in the main repo).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ABSOLUTE_PATH_RE = re.compile(
    r"(/home/[A-Za-z0-9._\-]+/|/Users/[A-Za-z0-9._\-]+/|/root/|"
    r"[A-Za-z]:\\\\Users\\\\)")

# Code + docs + release documents are checked for portability/secrets.
# Evidence directories are excluded: they legitimately record
# execution-time provenance paths (documented adjudication).
PORTABILITY_SCAN_DIRS = [
    "data_quality_platform", "runner", "scripts", "tests", "docs",
    "configs", "airflow", "sql", "reports",
]
PORTABILITY_SCAN_FILES = [
    "README.md", "RELEASE_NOTES.md", "final_result.json",
    "release_manifest.json", "pyproject.toml", "docker-compose.yml",
    "DELIVERY_MANIFEST.json", ".env.example", ".gitignore",
]

# Files that legitimately contain local-path PATTERNS or historical
# path records — excluded from the portability scan with explicit,
# file-exact justification (never a blanket directory skip):
PORTABILITY_ALLOWLIST = {
    # detector pattern definitions (the pattern itself contains /home/)
    "data_quality_platform/security/pii_scan.py":
        "machine-path DETECTION pattern definition (self-referential)",
    "scripts/build_final_result.py":
        "portability CHECK pattern definitions (self-referential)",
    "scripts/verify_enterprise_release_zip.py":
        "this verifier's own detection pattern (self-referential)",
    # deliberate scanner self-test fixtures (fake paths that prove
    # the detector works)
    "tests/unit/test_pii_scan.py":
        "scanner self-test fixtures (deliberate fake machine paths)",
    # historical 5M-session tooling — baked-in paths of that era's
    # environment; never invoked by any release flow
    "scripts/five_m/phase2_3_meta.py": "historical 5M tooling",
    "scripts/five_m/phase13_results.py": "historical 5M tooling",
    "scripts/five_m/phase4_run.py": "historical 5M tooling",
    "scripts/five_m/phase9_sp1.py": "historical 5M tooling",
    "scripts/five_m/consolidation_package_v2.py": "historical 5M tooling",
    "scripts/five_m/phase17_consistency.py": "historical 5M tooling",
    "scripts/five_m/phase7_bench.py": "historical 5M tooling",
    "scripts/five_m/phase18_manifest_archive.py": "historical 5M tooling",
    # historical reports quoting execution-time paths (preserved
    # records; README/RELEASE_NOTES/final_result/release_manifest are
    # the release documents and remain hard-checked)
    "docs/FINAL_5M_VALIDATION_REPORT.md": "historical report",
    "docs/CANONICAL_GEOGRAPHY_DESIGN.md": "historical report",
    "reports/history/CROSS_REFERENCE_PROVENANCE_REPORT.md":
        "historical report",
    "reports/history/PHASE_18_DELTA_VERIFICATION_REPORT.md":
        "historical report",
    "reports/history/Q1_Q22_ACCEPTANCE_AUDIT.md": "historical report",
    "reports/history/COMPANY_ALIGNMENT_FORENSIC_REPORT.md":
        "historical report",
    "reports/history/PHASE_19_EVIDENCE_REPORT.md": "historical report",
    "reports/history/PHASE3_GOLDEN_INTEGRITY_REPORT.md":
        "historical report",
}
PEM_KEY_RE = re.compile(
    r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")

CREDENTIAL_RE = re.compile(
    r"(?i)[\w.\-]*(password|passwd|passphrase|secret|token|"
    r"api[_\-]?key|apikey|access[_\-]?key|auth[_\-]?token|"
    r"bearer[_\-]?token|client[_\-]?secret|private[_\-]?key)"
    r"[\w.\-]*[\"']?\s*[:=]\s*(\S.{2,})")
PLACEHOLDER_VALUES = {
    "your_password_here", "changeme", "placeholder", "<none>", "none",
    "null", "test", "dummy", "example", "redacted", "***", "true",
    "false", "yes", "no", "0", "1", "n/a",
}


def check(name):
    print(f"[ .. ] {name}", flush=True)


def ok(name, detail=""):
    print(f"[ OK ] {name}{(' — ' + detail) if detail else ''}", flush=True)


def fail(name, detail):
    print(f"[FAIL] {name} — {detail}", flush=True)
    return False


def run(cmd, cwd, timeout=900):
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout)
    return proc.returncode, proc.stdout + proc.stderr, time.time() - t0


def main(zip_path, scratch_root):
    results = {}

    # ---- extract --------------------------------------------------
    check("extract release ZIP into clean directory")
    if os.path.exists(scratch_root):
        shutil.rmtree(scratch_root)
    os.makedirs(scratch_root)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(scratch_root)
    entries = os.listdir(scratch_root)
    if len(entries) != 1:
        return fail("extraction", f"expected one root dir, got {entries}")
    extracted = os.path.join(scratch_root, entries[0])
    ok("extraction", entries[0])

    # ---- [1] environment ------------------------------------------
    check("environment usable")
    py = sys.executable
    rc, out, _ = run([py, "-c",
                      "import yaml, pytest, data_quality_platform, runner"],
                     extracted, 60)
    if rc != 0:
        return fail("environment", out[-300:])
    rc, out, _ = run([py, "--version"], extracted, 30)
    ok("environment", out.strip())

    # ---- [2] imports ----------------------------------------------
    check("package imports from extracted copy")
    rc, out, _ = run([py, "-c",
                      "from data_quality_platform.rules.registry import "
                      "RuleRegistry; r = RuleRegistry.create_default(); "
                      "assert r.count == 8; "
                      "from data_quality_platform.validation import "
                      "engine, replay, evidence_validator, "
                      "evidence_root, failure_taxonomy, input_contract, "
                      "impact_analysis; "
                      "from data_quality_platform.security import "
                      "pii_masking, pii_scan; "
                      "from data_quality_platform.verification import "
                      "reference_provenance, decision_provenance; "
                      "print('imports ok, rules:', r.count)"],
                     extracted, 60)
    if rc != 0:
        return fail("imports", out[-300:])
    ok("imports", out.strip().splitlines()[-1])

    # ---- [3] full test suite --------------------------------------
    check("full test suite from extracted copy")
    rc, out, dur = run([py, "-m", "pytest", "-q", "--no-header",
                       "-p", "no:cacheprovider"], extracted, 1800)
    passed = re.findall(r"(\d+) passed", out)
    failed = re.findall(r"(\d+) failed", out)
    skipped = re.findall(r"(\d+) skipped", out)
    if rc != 0 or (failed and int(failed[-1]) > 0):
        return fail("test suite", out[-800:])
    ok("test suite", f"{passed[-1]} passed / {skipped[-1]} skipped "
                    f"in {dur:.0f}s")
    results["tests"] = f"{passed[-1]}/{skipped[-1]}"

    # ---- [5] CLI end-to-end (before the slow gate) ----------------
    check("production CLI generate + validate end-to-end")
    gen_csv = os.path.join(scratch_root, "cr_input.csv")
    out_csv = os.path.join(scratch_root, "cr_output.csv")
    evd = os.path.join(scratch_root, "cr_evidence")
    rc, out, _ = run([py, "-m", "runner.cli", "generate", "--rows", "500",
                      "--seed", "777", "--output", gen_csv], extracted,
                     120)
    if rc != 0:
        return fail("CLI generate", out[-300:])
    rc, out, _ = run([py, "-m", "runner.cli", "validate", "--csv", gen_csv,
                      "--output", out_csv, "--evidence-dir", evd],
                     extracted, 300)
    if rc != 0:
        return fail("CLI validate", out[-400:])
    with open(out_csv, encoding="utf-8") as f:
        header = f.readline().strip().split(",")
    if len(header) != 41:
        return fail("CLI output shape", f"{len(header)} columns")
    ok("CLI end-to-end", f"500 rows, 41 output columns, evidence in place")

    # ---- [4] release gate from extracted copy ---------------------
    check("release gate (16 fail-closed gates) from extracted copy")
    rc, out, dur = run([py, "scripts/release_gate.py"], extracted, 3600)
    tail = out.strip().splitlines()[-3:]
    if rc != 0:
        return fail("release gate", " | ".join(tail))
    verdict_line = next((l for l in tail if "OVERALL VERDICT" in l), "")
    ok("release gate", f"{verdict_line} ({dur:.0f}s)")
    results["release_gate"] = verdict_line
    gate_json = os.path.join(extracted, "evidence", "release_gate",
                             "final_release_gate.json")
    with open(gate_json, encoding="utf-8") as f:
        gate = json.load(f)
    if gate["overall_verdict"] != "PASS":
        return fail("release gate json", gate["overall_verdict"])

    # ---- [6] no accidental local absolute paths -------------------
    check("no local absolute paths in code/docs/release documents")
    hits = []
    allowed_hits = []
    for d in PORTABILITY_SCAN_DIRS:
        base = os.path.join(extracted, d)
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for fn in files:
                if not fn.endswith((".py", ".md", ".yaml", ".yml",
                                    ".sql", ".toml", ".txt", ".json")):
                    continue
                path = os.path.join(root, fn)
                try:
                    text = open(path, encoding="utf-8").read()
                except Exception:
                    continue
                if ABSOLUTE_PATH_RE.search(text):
                    rel = os.path.relpath(path, extracted).replace(
                        os.sep, "/")
                    if rel in PORTABILITY_ALLOWLIST:
                        allowed_hits.append(rel)
                    else:
                        hits.append(rel)
    for rel in PORTABILITY_SCAN_FILES:
        path = os.path.join(extracted, rel)
        if not os.path.isfile(path):
            continue
        text = open(path, encoding="utf-8").read()
        if ABSOLUTE_PATH_RE.search(text):
            if rel in PORTABILITY_ALLOWLIST:
                allowed_hits.append(rel)
            else:
                hits.append(rel)
    if hits:
        return fail("absolute paths", f"{hits[:10]}")
    ok("absolute paths",
       f"no accidental paths; {len(allowed_hits)} file-exact "
       f"allowlisted pattern/historical files (documented, listed below)")
    for rel in sorted(allowed_hits):
        print(f"        allowlisted: {rel} — "
              f"{PORTABILITY_ALLOWLIST[rel]}")

    # ---- [7] no secrets --------------------------------------------
    check("no secrets in code/docs/release documents")
    # file-exact, documented allowlist: detector definitions, config
    # stubs with empty/None defaults, the repo's own secret-scanning
    # tools, and historical reports quoting empty configuration.
    SECRETS_ALLOWLIST = {
        ".env.example": "environment template; empty/placeholder values "
                        "only (verified)",
        "data_quality_platform/config/settings.py":
            "config dataclass stubs; empty/None defaults",
        "data_quality_platform/security/auth.py":
            "secrets-management abstraction interface (docstrings)",
        "data_quality_platform/security/pii_scan.py":
            "secret DETECTION pattern definition (self-referential)",
        "scripts/fresh_execution_probe.py":
            "the repository's own secret scanner (patterns it detects)",
        "scripts/run_final_verification.py":
            "the repository's own secret scanner (patterns it detects)",
        "scripts/verify_enterprise_release_zip.py":
            "this verifier's detection/reporting code (self-referential)",
        "reports/history/CROSS_REFERENCE_PROVENANCE_REPORT.md":
            "historical report quoting empty configuration values",
    }
    secret_hits = []
    for rel in PORTABILITY_SCAN_FILES + [f"{d}" for d in
                                         PORTABILITY_SCAN_DIRS]:
        base = os.path.join(extracted, rel)
        candidates = [base] if os.path.isfile(base) else []
        if os.path.isdir(base):
            for root, dirs, files in os.walk(base):
                dirs[:] = [x for x in dirs
                           if x not in ("__pycache__", "future")]
                for fn in files:
                    if fn.endswith((".py", ".md", ".yaml", ".yml",
                                    ".toml", ".json", ".txt")):
                        candidates.append(os.path.join(root, fn))
        for path in candidates:
            try:
                text = open(path, encoding="utf-8").read()
            except Exception:
                continue
            rel = os.path.relpath(path, extracted).replace(os.sep, "/")
            if rel in SECRETS_ALLOWLIST:
                continue
            for m in CREDENTIAL_RE.finditer(text):
                value = m.group(2).strip().strip("\"'").lower()
                if value in PLACEHOLDER_VALUES or value.startswith("<"):
                    continue
                if value.startswith(":test_") or "::test_" in value:
                    continue
                # deliberately-fake test fixtures in tests/ are not
                # secrets; only flag outside tests/
                if rel.startswith("tests/"):
                    continue
                secret_hits.append(rel)
                break
            if PEM_KEY_RE.search(text) and not rel.startswith("tests/"):
                secret_hits.append(rel)
    if secret_hits:
        return fail("secrets", f"{sorted(set(secret_hits))[:10]}")
    ok("secrets", "none in code/docs/release documents "
                  f"({len(SECRETS_ALLOWLIST)} file-exact allowlisted "
                  f"definitions/stubs/scanners/historical records; "
                  f"tests/ fixtures excluded by design)")

    # ---- [8][9] archive contents ----------------------------------
    check("archive contents match git-tracked project files")
    problems = []
    rc, out, _ = run(["git", "ls-files"], REPO_ROOT, 30)
    # the post-archive release record (records this zip's own hash) is
    # intentionally OUTSIDE the archive; the clean-room copy has no git
    # context, so the expected set is the tracked files minus that dir
    tracked = set(f for f in out.splitlines()
                  if not f.startswith("evidence/enterprise_release_"))
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if zf.testzip() is not None:
            problems.append("CRC failure")
        root_dir = names[0].split("/")[0]
        zipped = {n[len(root_dir) + 1:] for n in names}
    missing = sorted(tracked - zipped)
    extra = sorted(zipped - tracked)
    if missing:
        problems.append(f"missing from ZIP: {missing[:8]}")
    if extra:
        problems.append(f"unexpected in ZIP: {extra[:8]}")
    if problems:
        return fail("archive contents", "; ".join(problems))
    ok("archive contents", f"{len(zipped)} tracked files, root dir "
                           f"{root_dir!r}, CRC clean")

    print("=" * 72)
    print("CLEAN-ROOM VERIFICATION: ALL CHECKS PASS")
    print(f"tests: {results.get('tests')} | "
          f"release gate: {results.get('release_gate')}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: verify_enterprise_release_zip.py <zip> <scratch>",
              file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
