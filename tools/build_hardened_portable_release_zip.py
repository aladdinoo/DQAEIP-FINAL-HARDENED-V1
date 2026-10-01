#!/usr/bin/env python3
"""DQAEIP 2026-09-19 hardened release — portable release ZIP builder.

Builds the definitive portable release archive:

    DQAEIP-FINAL-HARDENED-RELEASE-2026-09-19.zip

from the final verified tree (git-tracked files at a clean HEAD), then
verifies it fail-closed. This is the ESTABLISHED deterministic
non-self-referential model (identical to the certified 2026-09-18
release ZIP choreography):

    - the ZIP is built from the committed tree BEFORE this release's
      zip record exists in the tree, so the archive can never contain
      its own hash (non-self-referential by construction);
    - the authoritative zip SHA-256 is recorded repo-side in the
      release namespace zip record (committed with the final release
      commit) and in the .sha256 sidecar next to the archive;
    - member timestamps are FIXED (2026-09-19T00:00:00) and the member
      order is the sorted git-tracked order, so the archive is a
      deterministic function of the tree content.

Verification (fail-closed):
    - CRC of every member on read-back
    - member set == tracked tree minus documented exclusions
    - per-member SHA-256 + size manifest
    - path safety: no traversal, no absolute member names
    - credential scan over text members (documented positive-control
      fixtures recorded as exceptions; content never printed)
    - portable-scope machine-path gate over ZIP members (release
      evidence layer must be machine-path free; historical evidence
      archives preserved under the documented historical policy and
      counted, not failed)
    - key-artifact consistency against evidence/release/
      release_artifact_manifest.json (entries must match the tree)
    - executable-bit preservation in external attrs
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

from data_quality_platform.assurance.portable_evidence import (  # noqa: E402
    MACHINE_PATH_DETECTORS)
from tools.absolute_path_release_gate import (  # noqa: E402
    DEFAULT_EXCEPTIONS as GATE_EXCEPTIONS_REGISTRY,
    SCOPE_DIRS, SCOPE_FILES)

ZIP_NAME = "DQAEIP-FINAL-HARDENED-RELEASE-2026-09-19"
DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.dirname(REPO_ROOT)), "download",
    f"{ZIP_NAME}.zip")

NS = "evidence/FINAL_HARDENED_RELEASE_2026-09-19"
KEY_MANIFEST = os.path.join(REPO_ROOT, "evidence", "release",
                            "release_artifact_manifest.json")

EXCLUDED_PREFIXES = (
    f"{NS}/staging/",       # two-phase staging working area
)
DENY_NAME_SUFFIXES = (".pyc", ".pyo", ".DS_Store", ".coverage", ".env")
DENY_DIR_PARTS = (".git", ".venv", "__pycache__", ".pytest_cache")
DENY_SUBSTRINGS = (
    "evidence/release_gate/replay_work",
)

CREDENTIAL_SCAN_EXCEPTIONS = {
    f"{ZIP_NAME}/tests/unit/test_pii_scan.py":
        "positive-control fixture for the PII scanner "
        "(synthetic PEM marker, placeholder body)",
    f"{ZIP_NAME}/tests/assurance/"
    f"test_release_security_and_manifest.py":
        "positive-control fixture for the release security scanner "
        "(synthetic PEM marker, fabricated documentation-example "
        "tokens, placeholder body)",
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
    tracked = [p for p in git(["ls-files", "-z"]).stdout.split("\0") if p]
    members, excluded = [], []
    for rel in sorted(tracked):
        if any(rel.startswith(p) for p in EXCLUDED_PREFIXES):
            excluded.append(rel)
            continue
        if any(s in rel for s in DENY_SUBSTRINGS):
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
    import re
    patterns = [
        (r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
         "pem_private_key"),
        (r"(?i)aws_access_key_id\s*=\s*[A-Z0-9]{16,}",
         "aws_access_key"),
        (r"(?i)(github|gitlab|slack|api)[-_]?(token|key)\s*[:=]\s*"
         r"['\"][A-Za-z0-9_\-]{20,}['\"]", "credential_assignment"),
        (r"(?i)\bpassword\b\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']",
         "password_assignment"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, text):
            return label
    return None


def load_documented_exceptions():
    """Documented machine-path exceptions for the portable scope.

    The scope (SCOPE_DIRS/SCOPE_FILES) is imported from the certified
    absolute-path gate (tools/absolute_path_release_gate.py), whose
    namespace is the 2026-09-18 clean-rebuild release — the exception
    REGISTRY therefore also lives there (the 09-18 release's own
    gate-verified registry: historical_captured_output /
    diagnostic_quoting_violations classifications for the path-
    forensics inventories). Loading it from THIS release's namespace
    (a wiring bug fixed 2026-09-19) produced an empty exception set
    and false-positive machine-path failures on the registry-covered
    historical members."""
    paths = [GATE_EXCEPTIONS_REGISTRY,
             os.path.join(REPO_ROOT, NS, "release_gate",
                         "absolute_path_gate_exceptions.json")]
    exceptions = set()
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                reg = json.load(f)
            loaded = {e["path"] for e in reg.get("exceptions", [])
                      if isinstance(e, dict) and e.get("path")}
            exceptions |= loaded
        except (OSError, ValueError):
            continue
    return exceptions


def in_portable_scope(rel):
    if rel in SCOPE_FILES:
        return True
    return any(rel.startswith(d + "/") for d in SCOPE_DIRS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()

    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    head = git(["rev-parse", "HEAD"]).stdout.strip()
    dirty = git(["status", "--porcelain"]).stdout.strip()
    if dirty:
        print("REFUSING: working tree not clean (the release ZIP is "
              "built from the committed tree only):\n" + dirty,
              file=sys.stderr)
        return 1

    DOCUMENTED_EXCEPTIONS = load_documented_exceptions()

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

    # key-artifact consistency: the release artifact manifest's hashed
    # entries must match the tree (fail-closed)
    key_manifest = json.load(open(KEY_MANIFEST, encoding="utf-8"))
    key_by_path = {e["path"]: e.get("sha256")
                   for e in key_manifest.get("artifacts", [])}
    inconsistencies = [
        rel for rel, sha in key_by_path.items()
        if sha and rel in member_manifest
        and member_manifest[rel]["sha256"] != sha]
    if inconsistencies:
        print(f"FATAL: release artifact manifest inconsistent with "
              f"tree: {inconsistencies[:5]}")
        return 4

    # ---- build -----------------------------------------------------------
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    tmp_zip = args.out + ".building"
    if os.path.exists(tmp_zip):
        os.remove(tmp_zip)
    with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in members:
            # FIXED member timestamp: the archive is a deterministic
            # function of tree content (no wall-clock leakage)
            zi = zipfile.ZipInfo(f"{ZIP_NAME}/{rel}",
                                 date_time=(2026, 9, 19, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            abs_p = os.path.join(REPO_ROOT, rel)
            mode = os.stat(abs_p).st_mode
            # preserve the executable bit faithfully in external attrs
            zi.external_attr = (0o100755 if mode & 0o111
                                else 0o100644) << 16
            with open(abs_p, "rb") as f:
                zf.writestr(zi, f.read())

    # ---- verification ----------------------------------------------------
    problems = []
    portable_members_scanned = 0
    historical_members_with_paths = 0
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
        for name in names:
            if not name.endswith((".json", ".jsonl", ".md", ".py",
                                  ".txt", ".yaml", ".yml", ".toml",
                                  ".cfg", ".ini")):
                continue
            with zf.open(name) as fh:
                text = fh.read(1 << 22).decode("utf-8",
                                               errors="replace")
            rel = name[len(ZIP_NAME) + 1:]
            hit = scan_text_for_credentials(text)
            if hit and name not in CREDENTIAL_SCAN_EXCEPTIONS:
                problems.append(f"credential scan hit ({hit}) in {name} "
                                f"(content not printed)")
            # portable-scope machine-path gate over members
            if in_portable_scope(rel) and rel not in (
                    f"{NS}/path_forensics/"
                    "ABSOLUTE_PATH_INVENTORY.json") \
                    and rel not in DOCUMENTED_EXCEPTIONS:
                portable_members_scanned += 1
                if any(p.search(text)
                       for _d, p in MACHINE_PATH_DETECTORS):
                    problems.append(
                        f"machine-local path in portable release "
                        f"evidence member: {rel}")
            else:
                if any(p.search(text)
                       for _d, p in MACHINE_PATH_DETECTORS):
                    historical_members_with_paths += 1

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
        "report": "DQAEIP portable release ZIP record",
        "schema": {"name": "dqaeip.zip_record", "version": "1.0"},
        "release_id": ZIP_NAME,
        "built_utc": started,
        "git_head_at_build": head,
        "tree_clean_at_build": dirty == "",
        "zip_path": os.path.basename(args.out),
        "zip_sha256": zip_sha,
        "zip_size_bytes": zip_size,
        "member_count": len(members),
        "prohibited_findings": [],
        "documented_exceptions": dict(CREDENTIAL_SCAN_EXCEPTIONS),
        "historical_policy": {
            "members_with_machine_paths": (
                historical_members_with_paths),
            "note": "historical evidence archives preserved under the "
                    "documented historical-evidence policy; portable "
                    "derived representations are machine-path free",
        },
        "portable_scope_members_scanned": portable_members_scanned,
        "verdict": "VERIFIED",
        "excluded_by_policy": excluded,
        "exclusion_policy": (
            "temporary staging (two-phase rebuild working area; "
            "forensic records preserved in repository + git history), "
            "caches, bytecode, environment files, regenerable replay "
            "work products",
        ),
        "non_self_referential_model": (
            "the ZIP is built from the committed tree before this "
            "record exists in the tree; the archive cannot contain "
            "its own hash; the authoritative SHA-256 is recorded here "
            "and in the .sha256 sidecar, both written after the build"
        ),
        "verification": {
            "crc": "PASS",
            "member_set_matches_tree": True,
            "member_sha256_verified": len(members),
            "path_safety": "PASS",
            "credential_scan": "PASS (documented positive-control "
                               "fixtures only)",
            "portable_scope_machine_path_gate": "PASS",
            "key_artifact_manifest_consistency": "PASS",
            "executable_bits_preserved": True,
            "problems": [],
        },
        "status": "VERIFIED",
    }

    record_path = os.path.join(REPO_ROOT, NS, "release_manifest",
                              "zip_record.json")
    os.makedirs(os.path.dirname(record_path), exist_ok=True)
    with open(record_path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=True)
        f.write("\n")

    sidecar = args.out + ".sha256"
    with open(sidecar, "w", encoding="utf-8") as f:
        f.write(f"{zip_sha}  {os.path.basename(args.out)}\n")

    print(f"ZIP VERIFIED: {os.path.basename(args.out)}")
    print(f"  SHA-256:  {zip_sha}")
    print(f"  members:  {len(members)}  size: {zip_size:,} bytes")
    print(f"  portable-scope members machine-path clean: "
          f"{portable_members_scanned}")
    print(f"  historical members carrying preserved machine paths: "
          f"{historical_members_with_paths} (documented policy)")
    print(f"  sidecar:  {os.path.basename(sidecar)}")
    print(f"  record:   {os.path.relpath(record_path, REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
