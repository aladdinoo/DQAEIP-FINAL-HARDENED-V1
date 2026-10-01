#!/usr/bin/env python3
"""PHASE 18 — evidence manifest + final archive + unpack verification.

Manifest semantics (documented inside the manifest itself):
  - MANIFEST.json lists every artifact under evidence/final_5m_execution/ plus
    the rebuilt docs, README.md, commands.txt and the task scripts, with
    relative path, byte size, SHA-256, artifact type and evidence purpose.
  - The manifest does NOT contain its own hash (non-circular by construction).
    Its integrity is anchored by (a) the archive SHA-256 sidecar and (b) the
    final summary/report quoting the manifest's artifact count + aggregate.
  - Verification pass: every listed artifact is re-hashed at build time and
    the count is taken from the manifest itself (never hardcoded).
"""

import hashlib
import json
import os
import re
import subprocess
import zipfile
from datetime import datetime, timezone

REPO = "/home/z/my-project/Data-Quality-V1-Final-Company-Integrated"
E = "evidence/final_5m_execution"
ARCHIVE_NAME = "Data-Quality-Validation-Platform-5M-Revalidated-2026-09-09.zip"
DOWNLOAD = "/home/z/my-project/download"


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def classify(rel):
    if rel.endswith("FINAL_RESULTS.json"):
        return "single-source-of-truth", "authoritative machine-readable result"
    if rel.endswith("MANIFEST.json"):
        return "manifest", "evidence manifest (self-excluded, non-circular)"
    if "/00_baseline/" in rel:
        return "baseline-forensics", "pre-execution forensic baseline"
    if "/01_reporting_audit/" in rel:
        return "reporting-audit", "legacy-report claim audit (A-F classes)"
    if "/02_dataset/" in rel:
        return "dataset-evidence", "5M dataset generation/integrity evidence"
    if "/03_run1/" in rel:
        return "execution-failure-evidence", "5M run attempt + kernel OOM record"
    if "/04_independent_verification/" in rel:
        return "independent-verification", "verifier source + 24M-comparison results"
    if "/05_run2/" in rel:
        return "decision-record", "5M run 2 NOT EXECUTED decision"
    if "/06_performance/" in rel:
        return "performance-evidence", "ladder captures + performance report"
    if "/07_geography/" in rel:
        return "geography-evidence", "V1 geography results + per-state data"
    if "/08_activation_boundary/" in rel:
        return "sp1-boundary", "SP1 negative activation proof"
    if "/09_consistency/" in rel:
        return "consistency-audit", "document consistency sweep"
    if "/10_final_summary/" in rel:
        return "final-summary", "terminal-readable final summary"
    if "/11_largest_safe_execution_3m/" in rel:
        return "flagship-protocol", "3M dual-run protocol evidence"
    if "/12_test_suite/" in rel:
        return "test-evidence", "pytest captures + probe"
    if "/13_archive/" in rel:
        return "archive-verification", "manifest + unpack verification"
    if rel.startswith("docs/"):
        return "report", "rebuilt report/documentation"
    if rel.startswith("scripts/five_m/"):
        return "task-script", "executed task harness/verifier script"
    if rel in ("README.md", "commands.txt"):
        return "root-document", "rebuilt README / command index"
    return "other", "task artifact"


def main():
    os.chdir(REPO)
    entries = []
    roots = [E, "docs", "scripts/five_m"]
    extra = ["README.md", f"{E}/../final_5m_execution/commands.txt"]
    seen = set()

    def add(rel, purpose=None):
        if rel in seen or not os.path.isfile(rel):
            return
        if rel == f"{E}/MANIFEST.json":
            return  # self-exclusion — non-circular by construction (documented)
        seen.add(rel)
        typ, default_purpose = classify(rel)
        entries.append({
            "path": rel,
            "size_bytes": os.path.getsize(rel),
            "sha256": sha256_of(rel),
            "type": typ,
            "purpose": purpose or default_purpose,
        })

    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".pytest_cache")]
            for fn in filenames:
                add(os.path.join(dirpath, fn))
    for x in extra:
        add(x)

    # sort for stability
    entries.sort(key=lambda e: e["path"])
    n = len(entries)
    manifest = {
        "manifest": "FINAL 5M VALIDATION evidence manifest",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "hashing_semantics": {
            "self_hash": "EXCLUDED — this manifest does not list or hash itself "
                         "(self-exclusion; non-circular by construction)",
            "integrity_anchor": "the manifest is bound into the final archive whose "
                                "SHA-256 is recorded in the .sha256 sidecar, in "
                                "13_archive/archive_sha256.txt and in "
                                "10_final_summary/FINAL_TERMINAL_SUMMARY.txt",
            "verification": "every listed artifact is hashed at build time; the "
                            "artifact count below is computed from this list, "
                            "never hardcoded",
        },
        "artifact_count": n,
        "artifacts": entries,
    }
    with open(f"{E}/MANIFEST.json", "w") as f:
        json.dump(manifest, f, indent=2)

    # verification pass — re-hash every listed artifact, count from manifest
    ok = 0
    bad = []
    for e_ in manifest["artifacts"]:
        if os.path.isfile(e_["path"]) and sha256_of(e_["path"]) == e_["sha256"]:
            ok += 1
        else:
            bad.append(e_["path"])
    with open(f"{E}/13_archive/manifest_verification.txt", "w") as f:
        f.write(f"MANIFEST VERIFICATION — {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"manifest artifact_count field: {n}\n")
        f.write(f"artifacts actually verified: {ok}\n")
        f.write(f"mismatched/missing: {len(bad)} {bad[:5]}\n")
        f.write("RESULT: " + ("PASS — manifest count == verified count, all hashes match"
                              if not bad and ok == n else "FAIL") + "\n")
    print(f"manifest: {n} artifacts, verified {ok}, bad {len(bad)}")

    # ---- final git commit (docs/evidence only; no production code) ----
    rc = subprocess.run(["git", "add", "-A"], capture_output=True, text=True)
    rc2 = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    content_changes = [l for l in rc2.stdout.splitlines()
                       if not l.endswith("")]  # all staged lines
    numstat = subprocess.run(
        ["git", "diff", "--cached", "--numstat", "--", "data_quality_platform", "runner",
         "tests", "sql", "airflow"], capture_output=True, text=True).stdout.strip()
    content_changes = [l for l in numstat.splitlines()
                       if l and not re.match(r"^0\t0\t", l)]
    if content_changes:
        print("PRODUCTION PATH CONTENT CHANGES DETECTED — aborting:", content_changes)
        return 1
    msg = ("FINAL 5M VALIDATION: 5M dataset+OOM-evidenced attempt, 3M flagship dual-run "
           "protocol (byte-identical, 48M independent comparisons, 0 mismatches), "
           "reports/README rebuilt from FINAL_RESULTS.json, SP1 boundary proof, "
           "consistency audit 0 contradictions, evidence manifest")
    c = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    print("commit:", head, "|", (c.stdout or c.stderr).splitlines()[:1])

    # ---- archive ----
    os.makedirs(DOWNLOAD, exist_ok=True)
    archive_path = os.path.join(DOWNLOAD, ARCHIVE_NAME)
    # exclusion rules: no .git, no caches, no data/ CSVs (hash+command anchored),
    # no download/ recursively, no probe scratch
    exclude_prefixes = (".git/", "data/", "download/", "__pycache__", ".pytest_cache",
                        "htmlcov/")
    exclude_names = {".DS_Store"}
    added = 0
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirnames, filenames in os.walk("."):
            rel_dir = os.path.relpath(dirpath, ".").replace("\\", "/")
            dirnames[:] = [d for d in dirnames
                           if f"{rel_dir}/{d}".strip("./") not in
                           tuple(p.rstrip('/') for p in exclude_prefixes)
                           and d not in ("__pycache__", ".pytest_cache", ".git")]
            if any(rel_dir == p.rstrip('/') or rel_dir.startswith(p) for p in exclude_prefixes):
                continue
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, ".").replace("\\", "/")
                if any(rel.startswith(p) for p in exclude_prefixes) or fn in exclude_names:
                    continue
                if rel == f"download/{ARCHIVE_NAME}":
                    continue
                z.write(full, rel)
                added += 1
    archive_sha = sha256_of(archive_path)
    archive_size = os.path.getsize(archive_path)
    with open(os.path.join(DOWNLOAD, ARCHIVE_NAME + ".sha256"), "w") as f:
        f.write(f"{archive_sha}  {ARCHIVE_NAME}\n")
    with open(f"{E}/13_archive/archive_sha256.txt", "w") as f:
        f.write(f"archive: {ARCHIVE_NAME}\nsha256: {archive_sha}\nsize_bytes: {archive_size}\n"
                f"entries: {added}\nbuilt_at_commit: {head}\n")

    # ---- unpack verification (fresh dir, suite re-run, spot checks) ----
    unpack_dir = "/tmp/unpack_5m_check"
    subprocess.run(["rm", "-rf", unpack_dir])
    os.makedirs(unpack_dir)
    with zipfile.ZipFile(archive_path) as z:
        bad = z.testzip()
        z.extractall(unpack_dir)
    pt = subprocess.run(["python", "-m", "pytest", "-q"], cwd=unpack_dir,
                        capture_output=True, text=True, timeout=900)
    spot = []
    for rel, needle in [
        ("evidence/final_5m_execution/FINAL_RESULTS.json", '"verdict": "PASS WITH DOCUMENTED LIMITATIONS"'),
        ("evidence/final_5m_execution/02_dataset/dataset_sha256.txt", "44e41bb8cfe1c0d2fbafbff5e91bb40b100f8331ef26f946532b84c57409fb9d"),
        ("evidence/final_5m_execution/03_run1/oom_kernel_log.txt", "Out of memory"),
        ("docs/FINAL_5M_VALIDATION_REPORT.md", "48,000,000"),
        ("README.md", "Data Quality Validation Platform"),
    ]:
        p = os.path.join(unpack_dir, rel)
        content = open(p, errors="ignore").read() if os.path.exists(p) else ""
        spot.append((rel, needle in content))
    with open(f"{E}/13_archive/unpack_verification.txt", "w") as f:
        f.write("UNPACK VERIFICATION (fresh directory, archive as shipped)\n")
        f.write(f"unpacked to: {unpack_dir}\n")
        f.write(f"zip integrity (testzip): {'OK' if bad is None else f'CORRUPT: {bad}'}\n")
        f.write(f"pytest in unpacked copy: {pt.stdout.strip().splitlines()[-1] if pt.stdout else pt.stderr}\n")
        for rel, okk in spot:
            f.write(f"spot-check {rel}: {'PRESENT' if okk else 'MISSING'}\n")
    print("unpack verification done; pytest:", pt.stdout.strip().splitlines()[-1] if pt.stdout else "n/a")
    print("archive:", ARCHIVE_NAME, archive_sha[:16], f"{added} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
