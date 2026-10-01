#!/usr/bin/env python3
"""CONSOLIDATION PACKAGE v2 (2026-09-09 documentation consolidation).

Runs AFTER all documentation edits. Sequence (non-circular by construction):

  1. Regenerate evidence/final_5m_execution/MANIFEST.json over the same scope
     as the task-time manifest (evidence/final_5m_execution/**, docs/**,
     scripts/five_m/**, README.md, commands.txt), excluding itself and the
     three post-write packaging-record files (documented in
     hashing_semantics). Artifact count computed, never hardcoded.
  2. Verify the regenerated manifest 100% and refresh
     13_archive/manifest_verification.txt (the current manifest-verification
     record; the task-time wording described the superseded manifest).
  3. Build the v2 archive (same inclusion/exclusion rules as the task-time
     package), write the .sha256 sidecar and
     13_archive/archive_v2_sha256.txt. The prior package
     (Data-Quality-Validation-Platform-5M-Revalidated-2026-09-09.zip) is NOT
     touched.
  4. Unpack verification (structural + documentation-currency ONLY; the test
     suite is deliberately NOT re-run per the consolidation task scope) ->
     13_archive/unpack_verification_v2.txt.

NO git commit is created (task instruction). No production code is touched.
"""
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone

REPO = "/home/z/my-project/Data-Quality-V1-Final-Company-Integrated"
E = "evidence/final_5m_execution"
DOWNLOAD = "/home/z/my-project/download"
V2 = "Data-Quality-Validation-Platform-5M-Revalidated-2026-09-09-v2.zip"
V1 = "Data-Quality-Validation-Platform-5M-Revalidated-2026-09-09.zip"

# files excluded from the MANIFEST (written after the manifest itself):
POST_WRITE = {
    f"{E}/13_archive/manifest_verification.txt",
    f"{E}/13_archive/archive_v2_sha256.txt",
    f"{E}/13_archive/unpack_verification_v2.txt",
}
# files excluded from the ARCHIVE (written after the archive build; they bind
# the archive externally and cannot live inside it):
ARCHIVE_POST_BUILD = {
    f"{E}/13_archive/archive_v2_sha256.txt",
    f"{E}/13_archive/unpack_verification_v2.txt",
}


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
    for sub, typ, purpose in [
        ("/00_baseline/", "baseline-forensics", "pre-execution forensic baseline"),
        ("/01_reporting_audit/", "reporting-audit", "legacy-report claim audit (A-F classes)"),
        ("/02_dataset/", "dataset-evidence", "5M dataset generation/integrity evidence"),
        ("/03_run1/", "execution-failure-evidence", "5M run attempt + kernel OOM record"),
        ("/04_independent_verification/", "independent-verification", "verifier source + 24M-comparison results"),
        ("/05_run2/", "decision-record", "5M run 2 NOT EXECUTED decision"),
        ("/06_performance/", "performance-evidence", "ladder captures + performance report"),
        ("/07_geography/", "geography-evidence", "V1 geography results + per-state data"),
        ("/08_activation_boundary/", "sp1-boundary", "SP1 negative activation proof"),
        ("/09_consistency/", "consistency-audit", "document consistency sweep"),
        ("/10_final_summary/", "final-summary", "terminal-readable final summary"),
        ("/11_largest_safe_execution_3m/", "flagship-protocol", "3M dual-run protocol evidence"),
        ("/12_test_suite/", "test-evidence", "pytest captures + probe"),
        ("/13_archive/", "archive-verification", "package records (v1 task-time + v2 consolidation)"),
    ]:
        if sub in rel:
            return typ, purpose
    if rel.startswith("docs/"):
        return "report", "current/historical report or documentation"
    if rel.startswith("scripts/five_m/"):
        return "task-script", "executed task harness/verifier script"
    if rel in ("README.md", "commands.txt"):
        return "root-document", "rebuilt README / command index"
    return "other", "task artifact"


def regenerate_manifest():
    os.chdir(REPO)
    entries, seen = [], set()

    def add(rel):
        if rel in seen or not os.path.isfile(rel) or rel in POST_WRITE:
            return
        if rel == f"{E}/MANIFEST.json":
            return  # self-exclusion (documented)
        seen.add(rel)
        typ, purpose = classify(rel)
        entries.append({
            "path": rel,
            "size_bytes": os.path.getsize(rel),
            "sha256": sha256_of(rel),
            "type": typ,
            "purpose": purpose,
        })

    for root in (E, "docs", "scripts/five_m"):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".pytest_cache")]
            for fn in filenames:
                add(os.path.join(dirpath, fn).replace("\\", "/"))
    add("README.md")
    add(f"{E}/commands.txt")

    entries.sort(key=lambda e: e["path"])
    n = len(entries)
    manifest = {
        "manifest": "FINAL 5M VALIDATION evidence manifest",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "regeneration_note": (
            "Regenerated during the 2026-09-09 documentation consolidation "
            "(documentation + packaging only; no validation evidence content "
            "changed). Scope and exclusions identical in kind to the "
            "task-time manifest."
        ),
        "hashing_semantics": {
            "self_hash": "EXCLUDED — this manifest does not list or hash itself "
                         "(self-exclusion; non-circular by construction)",
            "post_write_exclusions": {
                "paths": sorted(POST_WRITE),
                "reason": "manifest_verification.txt is written after this "
                          "manifest (it records its verification) and is "
                          "included in the archive; archive_v2_sha256.txt and "
                          "unpack_verification_v2.txt are written after the "
                          "archive build and live outside the archive (repo "
                          "evidence + download sidecar), bound externally via "
                          "README §15 + DELIVERY_MANIFEST.json",
            },
            "v1_task_time_records": "13_archive/archive_sha256.txt and "
                                    "13_archive/unpack_verification.txt are the "
                                    "preserved records of the task-time package "
                                    "(Data-Quality-Validation-Platform-5M-Revalidated-"
                                    "2026-09-09.zip, sha256 51fdf65d…); they are "
                                    "listed here at their preserved content",
            "integrity_anchor": "the manifest is bound into the v2 archive whose "
                                "SHA-256 is recorded in the download/…-v2.zip.sha256 "
                                "sidecar and in 13_archive/archive_v2_sha256.txt",
            "verification": "every listed artifact is hashed at build time; the "
                            "artifact count below is computed from this list, "
                            "never hardcoded",
        },
        "artifact_count": n,
        "artifacts": entries,
    }
    with open(f"{E}/MANIFEST.json", "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    return manifest


def verify_manifest(manifest):
    ok, bad = 0, []
    for e in manifest["artifacts"]:
        if os.path.isfile(e["path"]) and sha256_of(e["path"]) == e["sha256"]:
            ok += 1
        else:
            bad.append(e["path"])
    n = manifest["artifact_count"]
    with open(f"{E}/13_archive/manifest_verification.txt", "w") as f:
        f.write(f"MANIFEST VERIFICATION — {datetime.now(timezone.utc).isoformat()}\n")
        f.write("manifest: regenerated during the 2026-09-09 documentation "
                "consolidation (see hashing_semantics.regeneration_note)\n")
        f.write(f"manifest artifact_count field: {n}\n")
        f.write(f"artifacts actually verified: {ok}\n")
        f.write(f"mismatched/missing: {len(bad)} {bad[:5]}\n")
        f.write("RESULT: " + ("PASS — manifest count == verified count, all hashes match"
                              if not bad and ok == n else "FAIL") + "\n")
    return not bad and ok == n


def build_archive():
    os.makedirs(DOWNLOAD, exist_ok=True)
    archive_path = os.path.join(DOWNLOAD, V2)
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
                if rel in ARCHIVE_POST_BUILD:
                    continue  # post-build binding records live outside the archive
                z.write(full, rel)
                added += 1
    archive_sha = sha256_of(archive_path)
    size = os.path.getsize(archive_path)
    with open(os.path.join(DOWNLOAD, V2 + ".sha256"), "w") as f:
        f.write(f"{archive_sha}  {V2}\n")
    parent = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                            text=True, cwd=REPO).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                           text=True, cwd=REPO).stdout.splitlines()
    with open(f"{E}/13_archive/archive_v2_sha256.txt", "w") as f:
        f.write(f"archive: {V2}\nsha256: {archive_sha}\nsize_bytes: {size}\n"
                f"entries: {added}\n"
                f"built_from: working tree at parent commit {parent} + the "
                f"documented 2026-09-09 documentation-consolidation changes "
                f"(git commit intentionally NOT created per task instruction; "
                f"{len(dirty)} modified paths, all documentation/evidence)\n"
                f"prior_package_preserved: {V1} (sha256 recorded in "
                f"13_archive/archive_sha256.txt) — not overwritten\n"
                f"sidecar: download/{V2}.sha256\n")
    return archive_path, archive_sha, added


def unpack_verification(archive_path, archive_sha):
    unpack_dir = "/tmp/unpack_v2_check"
    subprocess.run(["rm", "-rf", unpack_dir])
    os.makedirs(unpack_dir)
    with zipfile.ZipFile(archive_path) as z:
        bad = z.testzip()
        names = z.namelist()
        z.extractall(unpack_dir)
    required = [
        "README.md",
        "DELIVERY_MANIFEST.json",
        "docs/FINAL_5M_VALIDATION_REPORT.md",
        "docs/EVIDENCE_COVERAGE.md",
        "docs/FINAL_AUDIT_DECISION_MATRIX.md",
        "docs/REPRODUCIBILITY.md",
        "evidence/final_5m_execution/FINAL_RESULTS.json",
        "evidence/final_5m_execution/MANIFEST.json",
        "evidence/final_5m_execution/13_archive/archive_sha256.txt",
        "evidence/final_5m_execution/13_archive/unpack_verification.txt",
        "evidence/final_5m_execution/13_archive/manifest_verification.txt",
        "evidence/final_5m_execution/03_run1/oom_kernel_log.txt",
        "evidence/final_5m_execution/12_test_suite/pytest_full_rs.txt",
        "reports/history/HISTORY_INDEX.md",
    ]
    missing = [r for r in required
               if not os.path.isfile(os.path.join(unpack_dir, r))]

    def read(rel):
        p = os.path.join(unpack_dir, rel)
        return open(p, errors="ignore").read() if os.path.isfile(p) else ""

    currency = {
        "README verdict string": "PASS WITH DOCUMENTED LIMITATIONS" in read("README.md"),
        "README v2 package reference": "Data-Quality-Validation-Platform-5M-Revalidated-2026-09-09-v2.zip" in read("README.md"),
        "README 2026-09-09 current": "2026-09-09" in read("README.md"),
        "historical banner present (LIMITATIONS.md)": "HISTORICAL / SUPERSEDED — 2026-09-07" in read("LIMITATIONS.md"),
        "historical banner present (BENCHMARK_REPORT.md)": "HISTORICAL / SUPERSEDED — 2026-09-07" in read("BENCHMARK_REPORT.md"),
        "reports/history preserved (index present)": "HISTORICAL REPORT INDEX" in read("reports/history/HISTORY_INDEX.md")
                                                      and "2026-09-09 documentation-consolidation update" in read("reports/history/HISTORY_INDEX.md"),
        "FINAL_RESULTS verdict": '"verdict": "PASS WITH DOCUMENTED LIMITATIONS"' in read("evidence/final_5m_execution/FINAL_RESULTS.json"),
    }
    # manifest verification inside the unpacked copy (all listed artifacts)
    m = json.load(open(os.path.join(unpack_dir, f"{E}/MANIFEST.json")))
    ok_in, bad_in = 0, []
    for e in m["artifacts"]:
        p = os.path.join(unpack_dir, e["path"])
        if os.path.isfile(p) and sha256_of(p) == e["sha256"]:
            ok_in += 1
        else:
            bad_in.append(e["path"])

    lines = [
        "UNPACK VERIFICATION — v2 PACKAGE (2026-09-09 documentation consolidation)",
        f"unpacked to: {unpack_dir}",
        f"zip integrity (testzip): {'OK' if bad is None else f'CORRUPT: {bad}'}",
        f"entries: {len(names)}",
        f"required files: {'ALL PRESENT (' + str(len(required)) + ')' if not missing else 'MISSING: ' + str(missing)}",
    ]
    for k, v in currency.items():
        lines.append(f"currency/history check — {k}: {'PASS' if v else 'FAIL'}")
    lines.append(f"manifest verification inside unpacked copy: {ok_in}/{m['artifact_count']} matched"
                 + ("" if not bad_in else f"; MISMATCHED: {bad_in[:5]}"))
    lines.append("test suite re-run: intentionally NOT executed during the "
                 "documentation consolidation (outside task scope); the verified "
                 "2026-09-09 result stands (12_test_suite/pytest_full_rs.txt: "
                 "322 passed / 9 skipped / 0 failed / 0 errors); the preserved "
                 "task-time package's unpack check re-ran the suite inside the "
                 "extracted copy with the same result (13_archive/unpack_verification.txt)")
    all_pass = (bad is None and not missing and all(currency.values())
                and ok_in == m["artifact_count"])
    lines.append("RESULT: " + ("PASS" if all_pass else "FAIL"))
    with open(f"{E}/13_archive/unpack_verification_v2.txt", "w") as f:
        f.write("\n".join(lines) + "\n")
    return all_pass, len(names)


def main():
    manifest = regenerate_manifest()
    print(f"manifest regenerated: {manifest['artifact_count']} artifacts")
    ok = verify_manifest(manifest)
    print("manifest verification:", "PASS" if ok else "FAIL")
    archive_path, archive_sha, added = build_archive()
    print(f"archive built: {V2} | sha256 {archive_sha} | entries {added}")
    sidecar_sha = open(os.path.join(DOWNLOAD, V2 + ".sha256")).read().split()[0]
    print("sidecar matches:", sidecar_sha == archive_sha)
    up_ok, n_entries = unpack_verification(archive_path, archive_sha)
    print(f"unpack verification: {'PASS' if up_ok else 'FAIL'} ({n_entries} entries)")
    return 0 if (ok and up_ok and sidecar_sha == archive_sha) else 1


if __name__ == "__main__":
    sys.exit(main())
