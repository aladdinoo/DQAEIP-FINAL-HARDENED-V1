#!/usr/bin/env python3
"""Evidence manifest generator (Phase 11).

Walks evidence/final_execution/ + the freshly regenerated evidence/benchmarks/
and evidence/final_verification/, computes SHA-256 for every file, and writes
evidence/final_execution/EVIDENCE_MANIFEST.json (which excludes itself to
avoid any self-hash circularity). Also records environment + command provenance.
"""
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EV = os.path.join(PROJECT_ROOT, "evidence", "final_execution")
os.chdir(PROJECT_ROOT)

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()

entries = {}
for root_dir in ("evidence/final_execution", "evidence/benchmarks", "evidence/final_verification"):
    for dirpath, dirnames, filenames in os.walk(os.path.join(PROJECT_ROOT, root_dir)):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, PROJECT_ROOT)
            if rel == "evidence/final_execution/EVIDENCE_MANIFEST.json":
                continue  # self-exclusion: manifest cannot contain its own hash
            entries[rel] = {
                "sha256": sha256_file(p),
                "bytes": os.path.getsize(p),
            }

manifest = {
    "manifest_version": "1.0",
    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    "git_head": git("rev-parse", "HEAD"),
    "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
    "git_clean": git("status", "--porcelain") == "",
    "python_version": subprocess.run([os.sys.executable, "-VV"], capture_output=True, text=True).stdout.strip(),
    "platform": subprocess.run(["uname", "-srmo"], capture_output=True, text=True).stdout.strip(),
    "execution_commands": [
        "python3 -m pytest --collect-only -q",
        "python3 -m pytest -q",
        "python3 -m pytest -q -rs",
        "python3 -m pytest tests/{unit,contract,integration,golden,security,runtime} -q [-rs]",
        "python3 -m pytest tests/unit/test_sp1_geography_contract.py -q",
        "python3 -m pytest tests/integration/test_cli_subprocess.py -q",
        "python3 -m runner.cli generate --rows 1000 --seed 20260821 --output data/generated/fresh_exec_input.csv",
        "python3 -m runner.cli validate --csv data/generated/fresh_exec_input.csv --output data/generated/fresh_exec_output.csv --run-id fresh_exec_1000 --evidence-dir evidence/final_execution/cli_run/evidence",
        "python3 scripts/benchmark.py",
        "python3 scripts/run_final_verification.py",
        "python3 scripts/fresh_execution_probe.py",
        "python3 scripts/fresh_rule_matrix.py",
    ],
    "artifact_count": len(entries),
    "artifacts": entries,
    "self_hash_note": ("This manifest excludes itself (evidence/final_execution/EVIDENCE_MANIFEST.json) "
                       "from its artifact map; the archive-level SHA-256 is reported externally in the "
                       "final delivery response and DELIVERY_MANIFEST.json (null + note, self-reference "
                       "impossible for a file contained in the archive it hashes)."),
}

out_path = os.path.join(EV, "EVIDENCE_MANIFEST.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, default=str)

print(f"manifest written: {out_path}")
print(f"artifacts hashed: {len(entries)}")
print(f"git_head: {manifest['git_head']} clean={manifest['git_clean']}")
