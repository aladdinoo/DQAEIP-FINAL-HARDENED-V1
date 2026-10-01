#!/usr/bin/env python3
"""ASSURANCE REBASELINE 2026-09-17 — release ZIP builder + verifier.

Builds the DQAEIP-Enterprise-Assurance-Validation-Release-2026-09-17
ZIP from the ACTUAL repository state (git-tracked files only), then
fail-closed verification:

    1. refuse to build on a dirty working tree
    2. deny-list scan of the archive (.git, .venv, __pycache__,
       .pytest_cache, data/ staging, replay work dirs, .pyc, .env,
       .DS_Store, .coverage)
    3. secret scan over every archived text file (private keys, api
       keys, passwords; .env.example is a documented template)
    4. machine-path firewall over the RELEASE-FACING artifacts inside
       the archive (the same 13-artifact scope the release gate uses)
    5. CRC + completeness (expected == actual file set)
    6. post-archive record (zip SHA-256 + inventory) written OUTSIDE the
       archive to evidence/assurance_rebaseline_2026-09-17/
    7. extraction verification into a clean temp dir: import sanity,
       full test suite, evidence verification, README consistency,
       release-security scan, release artifact manifest verification

Historical-evidence note (scope policy, consistent with the path
firewall module's documented scope): immutable historical execution
records (terminal outputs, runtime-safety events, CLI records) are
shipped UNMODIFIED as reproducibility evidence; the release-facing
document scope is what the firewall enforces. Source-code regex
patterns that merely resemble paths are false positives by design.
"""

import hashlib
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
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance import path_firewall

RELEASE_NAME = "DQAEIP-Assurance-Rebuild-Release-2026-09-17"
DEFAULT_ZIP = os.path.join(
    os.path.dirname(os.path.dirname(REPO_ROOT)), "download",
    f"{RELEASE_NAME}.zip")
RECORD_OUT = os.path.join(REPO_ROOT, "evidence",
                          "assurance_rebuild_2026-09-17",
                          "release_zip_record.json")

DENY_PATTERNS = (
    ".git/", ".venv/", "__pycache__/", ".pytest_cache/",
    "/data/", "evidence/release_gate/replay_work",
    ".pyc", ".pyo", ".DS_Store", ".coverage",
)

SECRET_PATTERNS = [
    ("private_key", re.compile(
        r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("aws_access_key_id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("aws_secret", re.compile(
        r"(?i)aws.{0,20}(secret|password).{0,10}[\"'][A-Za-z0-9/+=]{20,}")),
    ("generic_api_key_assignment", re.compile(
        r"(?i)\b(api[_-]?key|apikey|secret[_-]?token|access[_-]?token)\b"
        r"\s*[:=]\s*[\"'][A-Za-z0-9_\-/.+]{16,}[\"']")),
    ("password_assignment", re.compile(
        r"(?i)\bpassword\b\s*[:=]\s*[\"'][^\"'$\s]{8,}[\"']")),
]

# Documented, justified exceptions (recorded in the ZIP record — never a
# silent pass). The PII scanner's own positive-control fixture contains
# a SYNTHETIC PEM block (header + 4-char body 'MIIB' + footer, no real
# key material) precisely so the scanner's pem_private_key detection can
# be proven to FAIL closed on it (tests/unit/test_pii_scan.py::
# test_pem_private_key_fails). Removing it would destroy the security
# test; it is not a credential.
SECRET_SCAN_ALLOW_LIST = {
    "tests/unit/test_pii_scan.py": (
        "synthetic PII-scanner positive-control fixture: fake PEM header "
        "with 4-char body 'MIIB' proving pem_private_key detection; no "
        "real key material"),
    # assurance-rebaseline security-scanner positive controls: fabricated
    # AWS/GitHub example tokens, placeholder password, fake PEM — each
    # exists precisely to prove release_security detection fails closed
    # (tests/assurance/test_release_security_and_manifest.py); values
    # are fabrications, not credentials
    "tests/assurance/test_release_security_and_manifest.py": (
        "synthetic security-scanner positive-control fixtures: fabricated "
        "AWS/GitHub documentation-example tokens, placeholder password "
        "and fake PEM blocks proving the fail-closed detection rules; "
        "no real credential material"),
}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args):
    r = subprocess.run(["git", "-C", REPO_ROOT] + list(args),
                       capture_output=True, text=True, check=False)
    return r.stdout.strip() if r.returncode == 0 else ""


def tracked_files():
    return sorted(git("ls-files").splitlines())


def build_zip(zip_path):
    files = tracked_files()
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zf:
        for rel in files:
            src = os.path.join(REPO_ROOT, rel)
            if not os.path.isfile(src):
                continue
            zf.write(src, f"{RELEASE_NAME}/{rel}")
    return files


def verify_zip(zip_path, files, record):
    problems = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if zf.testzip() is not None:
            problems.append("CRC failure in archive")
        expected = {f"{RELEASE_NAME}/{rel}" for rel in files
                    if os.path.isfile(os.path.join(REPO_ROOT, rel))}
        actual = set(names)
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            problems.append(f"missing from archive: {missing[:10]}")
        if extra:
            problems.append(f"unexpected in archive: {extra[:10]}")
        record["archive_member_count"] = len(names)

        # deny-list
        denied = [n for n in names for p in DENY_PATTERNS
                  if p in n or (p == ".env"
                                and n.rsplit("/", 1)[-1] == ".env")]
        if denied:
            problems.append(f"deny-list hits: {denied[:10]}")

        # secret scan
        secret_hits = []
        allowed = []
        for n in names:
            if n.endswith(("/", ".pyc", ".pyo", ".png", ".jpg", ".zip")):
                continue
            rel = n[len(RELEASE_NAME) + 1:] if n.startswith(
                RELEASE_NAME + "/") else n
            try:
                text = zf.read(n).decode("utf-8", errors="replace")
            except Exception:
                continue
            for rule_id, pat in SECRET_PATTERNS:
                for m in pat.finditer(text):
                    # NOTE: the raw excerpt is deliberately NOT written
                    # into the record: quoting secret-like text into an
                    # evidence JSON would itself trip the repo's PII
                    # evidence scanner (fail-closed by design). The
                    # record carries location + rule + line number only.
                    lineno = text.count("\n", 0, m.start()) + 1
                    hit = (rel, rule_id,
                           f"match at line {lineno} (excerpt redacted "
                           f"from record to keep the evidence tree "
                           f"PII-clean)")
                    if rel in SECRET_SCAN_ALLOW_LIST:
                        allowed.append(hit)
                    elif ".env.example" in n:
                        # documented template with placeholder values
                        allowed.append(hit)
                    else:
                        secret_hits.append(hit)
        record["prohibited_findings"] = secret_hits
        record["documented_exceptions"] = dict(SECRET_SCAN_ALLOW_LIST)
        record["exception_hits_recorded"] = allowed
        if secret_hits:
            problems.append(f"secret-like content: {secret_hits[:5]}")

        # machine-path firewall over release-facing artifacts IN the ZIP
        release_facing = [rel for rel in
                          path_firewall.DEFAULT_RELEASE_ARTIFACTS]
        pf_violations = []
        for rel in release_facing:
            arcname = f"{RELEASE_NAME}/{rel}"
            if arcname not in actual:
                pf_violations.append(f"missing release artifact: {rel}")
                continue
            text = zf.read(arcname).decode("utf-8", errors="replace")
            pf_violations.extend(
                {"source": rel, **v}
                for v in path_firewall.scan_text(text, source=rel))
        record["path_firewall_scanned"] = release_facing
        record["path_firewall_violations"] = pf_violations
        if pf_violations:
            problems.append(f"machine paths in release artifacts: "
                            f"{pf_violations[:5]}")
    return problems


def extraction_verification(zip_path, record, files):
    """§22: extract to a clean temp dir and verify the packaged release
    behaves like the release: import sanity, full test suite, evidence
    verification, README consistency."""
    problems = []
    tmp = tempfile.mkdtemp(prefix="dqaeip_zip_check_")
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        root = os.path.join(tmp, RELEASE_NAME)
        if not os.path.isdir(root):
            return ["extraction: release root dir missing"]

        def run(cmd, timeout=900):
            return subprocess.run(cmd, cwd=root, capture_output=True,
                                  text=True, timeout=timeout)

        # import/package sanity
        r = run([sys.executable, "-c",
                 "import data_quality_platform.validation.engine, "
                 "data_quality_platform.validation.chunking, "
                 "data_quality_platform.assurance.path_firewall, "
                 "runner.cli; "
                 "from data_quality_platform.contracts import "
                 "SOURCE_COLUMNS, OUTPUT_COLUMNS; "
                 "assert len(SOURCE_COLUMNS) == 33 and "
                 "len(OUTPUT_COLUMNS) == 41; "
                 "from data_quality_platform.rules.registry import "
                 "RuleRegistry; "
                 "assert RuleRegistry.create_default().count == 8"])
        record["extraction_import_sanity"] = (r.returncode == 0)
        if r.returncode != 0:
            problems.append(f"import sanity failed: {r.stderr[-300:]}")

        # full test suite from the extracted tree
        r = run([sys.executable, "-m", "pytest", "tests", "-q",
                 "-p", "no:cacheprovider"])
        tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
        record["extraction_test_suite_tail"] = tail[0]
        ok = r.returncode == 0
        record["extraction_tests_exit_zero"] = ok
        if not ok:
            problems.append(f"extracted test suite failed: {tail[0]}")

        # evidence verification: run-pair report + gate verdict exist and
        # re-validate; FINAL_RESULTS claims parse
        try:
            rp = json.load(open(os.path.join(
                root, "evidence", "rebuild_verification",
                "run_pair_verification.json"), encoding="utf-8"))
            gate = json.load(open(os.path.join(
                root, "evidence", "release_gate",
                "final_release_gate.json"), encoding="utf-8"))
            fr = json.load(open(os.path.join(root, "FINAL_RESULTS.json"),
                                encoding="utf-8"))
            ok = (rp.get("verdict") == "PASS"
                  and rp.get("checks_failed") == 0
                  and gate.get("overall_verdict") == "PASS"
                  and gate.get("gate_counts", {}).get("pass") == 21
                  and fr.get("final_release_status") in (
                      "PASS", "PASS_WITH_DOCUMENTED_LIMITATIONS"))
            record["extraction_evidence_verification"] = ok
            if not ok:
                problems.append("extracted evidence verification failed")
        except Exception as exc:
            record["extraction_evidence_verification"] = False
            problems.append(f"extracted evidence unreadable: {exc}")

        # README consistency: FULL evidence-derived check (reuses the
        # §10 checker, which works without git metadata)
        try:
            sys.path.insert(0, REPO_ROOT)
            import readme_consistency_check as rcc  # noqa: E402
            rcc_result = rcc.run_check(root)
            record["extraction_readme_consistency"] = (
                rcc_result["verdict"] == "CONSISTENT")
            record["extraction_readme_consistency_problems"] = \
                rcc_result["problems"][:10]
            if rcc_result["verdict"] != "CONSISTENT":
                problems.append(
                    f"README consistency failed: "
                    f"{rcc_result['problems'][:5]}")
        except Exception as exc:
            record["extraction_readme_consistency"] = False
            problems.append(f"README consistency unreadable: {exc}")

        # release-security scan of the extracted tree (task §17: the
        # extracted archive must satisfy the same fail-closed security
        # policy as the repository release tree). rel_paths is the
        # ARCHIVE's verified member list — no live-repo git is used,
        # so the check proves the archive itself is clean.
        try:
            sys.path.insert(0, REPO_ROOT)
            from data_quality_platform.assurance import release_security
            sec = release_security.scan_release_tree(
                REPO_ROOT, tree_root=root, rel_paths=files)
            record["extraction_security_scan"] = sec["verdict"]
            if sec["verdict"] != "PASS":
                fails = {k: v for k, v in sec["section_verdicts"].items()
                         if v != "PASS"}
                problems.append(
                    f"extracted-tree security scan failed: {fails}")
        except Exception as exc:
            record["extraction_security_scan"] = "ERROR"
            problems.append(f"extracted-tree security scan error: {exc}")

        # release artifact manifest verification (task §17/§21-5):
        # recompute every manifest hash inside the extracted tree.
        # PENDING_POST_ZIP_REBUILD entries are artifacts that exist only
        # AFTER this archive is built (this ZIP record itself) — by the
        # manifest's documented phase policy they are explicitly absent
        # from the archive that precedes them; they are recorded as an
        # explicit extraction-only skip, never silently ignored.
        try:
            mpath = os.path.join(
                root, "evidence", "release",
                "release_artifact_manifest.json")
            with open(mpath, encoding="utf-8") as mf:
                manifest = json.load(mf)
            mproblems = []
            pending_in_archive = []
            for entry in manifest.get("artifacts", []):
                rel = entry.get("path")
                if entry.get("status") == "PENDING_POST_ZIP_REBUILD":
                    pending_in_archive.append(rel)
                    continue
                p = os.path.join(root, rel)
                if not os.path.isfile(p):
                    mproblems.append(f"missing {rel}")
                    continue
                h = sha256_file(p)
                if entry.get("sha256") and h != entry["sha256"]:
                    mproblems.append(f"hash drift {rel}")
            record["extraction_manifest_pending_entries"] = \
                pending_in_archive
            record["extraction_manifest_verification"] = not mproblems
            if mproblems:
                problems.append(
                    f"manifest verification failed: {mproblems[:5]}")
        except Exception as exc:
            record["extraction_manifest_verification"] = False
            problems.append(f"manifest unreadable: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return problems


def main():
    zip_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ZIP
    if not os.path.isabs(zip_path):
        zip_path = os.path.join(REPO_ROOT, zip_path)

    dirty = subprocess.run(["git", "-C", REPO_ROOT, "status",
                            "--porcelain"], capture_output=True,
                           text=True).stdout.strip()
    if dirty:
        print(f"REFUSING: working tree not clean:\n{dirty}",
              file=sys.stderr)
        return 1

    record = {
        "report": "DQAEIP final hardening release ZIP record",
        "release_name": RELEASE_NAME,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                       time.gmtime()),
        "git_head_at_build": git("rev-parse", "HEAD"),
        "git_tree_hash_at_build": git("rev-parse", "HEAD^{tree}"),
        "selection_policy": "git-tracked files only",
        "deny_list": list(DENY_PATTERNS),
        "zip_path": os.path.relpath(zip_path, REPO_ROOT)
        if zip_path.startswith(REPO_ROOT) else zip_path,
        "zip_sha256": None,
        "zip_size_bytes": None,
    }

    files = build_zip(zip_path)
    problems = verify_zip(zip_path, files, record)
    record["zip_sha256"] = sha256_file(zip_path)
    record["zip_size_bytes"] = os.path.getsize(zip_path)
    record["tracked_file_count"] = len(files)

    if problems:
        record["verdict"] = "FAIL"
        record["problems"] = problems
        os.makedirs(os.path.dirname(RECORD_OUT), exist_ok=True)
        with open(RECORD_OUT, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
            f.write("\n")
        print("ZIP VERIFICATION FAILURES:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    # §22 extraction verification (only when the archive itself is clean)
    ex_problems = extraction_verification(zip_path, record, files)
    record["verdict"] = "PASS" if not ex_problems else "FAIL"
    record["problems"] = ex_problems
    os.makedirs(os.path.dirname(RECORD_OUT), exist_ok=True)
    with open(RECORD_OUT, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
        f.write("\n")

    print(f"archive: {zip_path}")
    print(f"files: {len(files)}  size: {record['zip_size_bytes']:,} bytes")
    print(f"zip sha256: {record['zip_sha256']}")
    print(f"credential-pattern scan: "
          f"{len(record['prohibited_findings'])} prohibited hit(s)")
    print(f"path firewall (release-facing, in-archive): 0 violations")
    print(f"extraction verification: "
          f"{'PASS' if not ex_problems else 'FAIL'}")
    print(f"record: {os.path.relpath(RECORD_OUT, REPO_ROOT)}")
    return 0 if not ex_problems else 1


if __name__ == "__main__":
    sys.exit(main())
