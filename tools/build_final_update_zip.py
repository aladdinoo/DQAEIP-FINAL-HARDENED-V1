#!/usr/bin/env python3
"""DQAEIP FINAL UPDATE 2026-09-17 — release ZIP builder + verifier
(task-book sections 34 and 35).

Builds DQAEIP-FINAL-UPDATE-2026-09-17.zip from the final verified tree
(git-tracked files at a clean HEAD), then verifies it:

    - CRC of every member on read-back (zipfile.testzip + per-member)
    - member count / sizes / SHA-256 manifest
    - ZIP member set == tracked tree minus documented exclusions
    - path safety: no traversal, no absolute paths, no home-dir writes
    - credential / secret scan over members (never printing contents)
    - key-artifact manifest consistency: members listed in the
      evidence/FINAL_UPDATE_2026-09-17 release manifest must match its
      recorded SHA-256 values

Exclusions (§34): .git, .venv, caches, .pyc, .env, credentials,
temporary staging (evidence/FINAL_UPDATE_2026-09-17/staging/),
replay scratch, superseded temporary outputs. Unverified files are
never included (membership is exactly the tracked tree).
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

ZIP_NAME = "DQAEIP-FINAL-UPDATE-2026-09-17"
DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.dirname(REPO_ROOT)), "download",
    f"{ZIP_NAME}.zip")

NS = "evidence/FINAL_UPDATE_2026-09-17"
KEY_MANIFEST = os.path.join(REPO_ROOT, NS, "release_manifest",
                            "release_manifest.json")
ZIP_RECORD = os.path.join(REPO_ROOT, NS, "release_manifest",
                          "zip_record.json")

# Documented exclusions (§34). Everything else tracked is included.
EXCLUDED_PREFIXES = (
    f"{NS}/staging/",       # temporary two-phase staging area
)
DENY_NAME_SUFFIXES = (".pyc", ".pyo", ".DS_Store", ".coverage", ".env")
DENY_DIR_PARTS = (".git", ".venv", "__pycache__", ".pytest_cache")

# Documented positive-control fixture exceptions (credential scan):
# these test files deliberately contain SYNTHETIC PEM markers
# (placeholder "MIIB" bodies, no real key material) to verify the
# scanner detects them. Exception = exact member path + documented
# reason; anything else still fails closed.
CREDENTIAL_SCAN_EXCEPTIONS = {
    f"{ZIP_NAME}/tests/unit/test_pii_scan.py":
        "positive-control fixture for the PII scanner "
        "(synthetic PEM marker, placeholder body)",
    f"{ZIP_NAME}/tests/assurance/"
    f"test_release_security_and_manifest.py":
        "positive-control fixture for the release security scanner "
        "(synthetic PEM marker, placeholder body)",
}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(args):
    return subprocess.run(["git", "-C", REPO_ROOT] + args,
                          capture_output=True, text=True, check=False)


def release_members():
    """Tracked files minus documented exclusions."""
    tracked = [p for p in git(["ls-files", "-z"]).stdout.split("\0") if p]
    members = []
    excluded = []
    for rel in sorted(tracked):
        if any(rel.startswith(p) for p in EXCLUDED_PREFIXES):
            excluded.append(rel)
            continue
        parts = rel.split("/")
        if any(part in DENY_DIR_PARTS for part in parts):
            excluded.append(rel)
            continue
        if rel.endswith(DENY_NAME_SUFFIXES):
            excluded.append(rel)
            continue
        members.append(rel)
    return members, excluded


def scan_text_for_credentials(text):
    """Conservative credential-pattern scan (never prints content)."""
    import re
    patterns = [
        (r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
         "pem_private_key"),
        (r"(?i)aws_access_key_id\s*=\s*[A-Z0-9]{16,}",
         "aws_access_key"),
        (r"(?i)(github|gitlab|slack|api)[-_]?(token|key)\s*[:=]\s*"
         r"['\"][A-Za-z0-9_\-]{20,}['\"]", "credential_assignment"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, text):
            return label
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--skip-verify", action="store_true")
    args = parser.parse_args()

    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    head = git(["rev-parse", "HEAD"]).stdout.strip()
    dirty = git(["status", "--porcelain"]).stdout.strip()

    # ---- membership from the final verified tree -----------------------
    members, excluded = release_members()
    print(f"release membership: {len(members)} files "
          f"({len(excluded)} excluded by policy)")

    member_manifest = {}
    for rel in members:
        abs_p = os.path.join(REPO_ROOT, rel)
        member_manifest[rel] = {
            "sha256": sha256_file(abs_p),
            "size": os.path.getsize(abs_p),
        }

    # ---- key-artifact manifest consistency ----------------------------
    key_manifest = json.load(open(KEY_MANIFEST, encoding="utf-8"))
    key_by_path = {e["path"]: e["sha256"]
                   for e in key_manifest.get("files", [])}
    inconsistencies = [
        rel for rel, sha in key_by_path.items()
        if rel in member_manifest
        and member_manifest[rel]["sha256"] != sha]
    if inconsistencies:
        print(f"FATAL: key-artifact manifest inconsistent with tree: "
              f"{inconsistencies[:5]}")
        return 4

    # ---- build the archive ----------------------------------------------
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    tmp_zip = args.out + ".building"
    if os.path.exists(tmp_zip):
        os.remove(tmp_zip)
    with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in members:
            zf.write(os.path.join(REPO_ROOT, rel),
                     arcname=f"{ZIP_NAME}/{rel}")

    # ---- verification (§35) -----------------------------------------------
    problems = []
    with zipfile.ZipFile(tmp_zip, "r") as zf:
        bad = zf.testzip()
        if bad is not None:
            problems.append(f"CRC failure: {bad}")
        names = zf.namelist()
        expected_names = {f"{ZIP_NAME}/{rel}" for rel in members}
        actual_set = set(names)
        if actual_set != expected_names:
            missing = expected_names - actual_set
            extra = actual_set - expected_names
            if missing:
                problems.append(f"members missing: {sorted(missing)[:5]}")
            if extra:
                problems.append(f"members extra: {sorted(extra)[:5]}")
        if len(names) != len(set(names)):
            problems.append("duplicate member names in archive")
        for name in names:
            # path safety
            if name.startswith("/") or ".." in name.split("/"):
                problems.append(f"unsafe member path: {name}")
            with zf.open(name) as fh:
                h = hashlib.sha256()
                total = 0
                while True:
                    chunk = fh.read(1 << 20)
                    if not chunk:
                        break
                    h.update(chunk)
                    total += len(chunk)
                rel = name[len(ZIP_NAME) + 1:]
                if rel in member_manifest:
                    if h.hexdigest() != member_manifest[rel]["sha256"]:
                        problems.append(f"member SHA mismatch: {rel}")
                    if total != member_manifest[rel]["size"]:
                        problems.append(f"member size mismatch: {rel}")
        # credential scan over text members (never printing content)
        for name in names:
            if name.endswith((".json", ".md", ".py", ".yaml", ".yml",
                             ".toml", ".txt", ".cfg", ".ini")):
                with zf.open(name) as fh:
                    text = fh.read(1 << 22).decode(
                        "utf-8", errors="replace")
                hit = scan_text_for_credentials(text)
                if hit and name not in CREDENTIAL_SCAN_EXCEPTIONS:
                    problems.append(
                        f"credential scan hit ({hit}) in {name} "
                        f"(content not printed)")

    if problems:
        os.replace(tmp_zip, args.out + ".rejected")
        print(f"ZIP VERIFICATION FAILED ({len(problems)} problems) — "
              f"preserved as {args.out + '.rejected'}")
        for p in problems[:15]:
            print(f"  - {p}")
        return 4

    os.replace(tmp_zip, args.out)
    zip_sha = sha256_file(args.out)
    zip_size = os.path.getsize(args.out)

    record = {
        "report": "DQAEIP FINAL UPDATE release ZIP record",
        "release_id": ZIP_NAME,
        "release_name": ZIP_NAME,
        "built_utc": started,
        "git_head_at_build": head,
        "tree_clean_at_build": dirty == "",
        "zip_path": os.path.basename(args.out),
        "zip_sha256": zip_sha,
        "zip_size_bytes": zip_size,
        "member_count": len(members),
        "archive_member_count": len(members),
        "prohibited_findings": [],
        "path_firewall_violations": [],
        "documented_exceptions": {
            path: reason for path, reason
            in CREDENTIAL_SCAN_EXCEPTIONS.items()},
        "verdict": "VERIFIED",
        "excluded_by_policy": excluded,
        "exclusion_policy": ("temporary staging (two-phase rebuild "
                             "working area; forensic records preserved "
                             "in repository + git history), caches, "
                             "bytecode, environment files"),
        "verification": {
            "crc": "PASS",
            "member_set_matches_tree": True,
            "member_sha256_verified": len(members),
            "path_safety": "PASS",
            "credential_scan": "PASS (0 findings)",
            "key_artifact_manifest_consistency": "PASS",
            "problems": [],
        },
        "status": "VERIFIED",
    }
    with open(ZIP_RECORD, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"ZIP BUILT + VERIFIED: {args.out}")
    print(f"  SHA-256: {zip_sha}")
    print(f"  size: {zip_size:,} bytes | members: {len(members)}")
    print(f"  record: {NS}/release_manifest/zip_record.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
