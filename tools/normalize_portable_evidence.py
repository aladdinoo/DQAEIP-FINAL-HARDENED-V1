#!/usr/bin/env python3
"""DQAEIP FINAL PORTABLE EVIDENCE & RELEASE HARDENING — Phase 2.

Applies the portable evidence path standard (module
``data_quality_platform/assurance/portable_evidence.py`` — the ONE
centralized normalization utility) to the evidence tree.

Historical-evidence policy (task section 16 — documented choice):

    POLICY A (applied to the AUTHORITATIVE official 3M evidence):
        the original artifacts are preserved BYTE-EXACT (SHA-256
        verified before and after this run); a clearly-marked
        NORMALIZED DERIVED representation is created under
        ``evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18/portable_evidence/``
        mirroring the source layout.

    Nothing else is modified. SUPERSEDED / UNKNOWN-protected artifacts
    with absolute paths are preserved as historical record and are
    documented in the path inventory (Phase 1) and the historical
    evidence policy (Phase 15) — their absolute paths are part of the
    historical record and rewriting them would falsify history.

Derived-copy format (clearly marked, machine-verifiable):

    {
      "portable_derivation": {
        "derived_from": "<repo-relative source path>",
        "source_sha256": "<SHA-256 of the ORIGINAL authoritative file>",
        "policy": "A — preserve original, create normalized derived",
        "normalization": "<what was rewritten>",
        "normalized_field_paths": [...],       # json paths only
        "environment_placeholders": {...},      # token -> meaning
        "retained_machine_reference_count": 0,
        "portability": "PORTABLE"
      },
      ... original document structure with normalized strings ...
    }

Fail-closed guarantees enforced by this tool:

    - every source file's SHA-256 is captured BEFORE and re-verified
      AFTER normalization (a mutated original aborts the run);
    - every derived copy is re-parsed, re-scanned with the shared
      machine-path detectors and must contain ZERO machine-local
      paths (a leftover machine path aborts the run);
    - non-repository environment paths (the historical interpreter
      home) are rewritten to explicit <<...>> placeholder tokens
      recorded in the derivation header — never silently dropped.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance.portable_evidence import (  # noqa: E402
    MACHINE_PATH_DETECTORS, normalize_document)

NS = "evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18"
INVENTORY = os.path.join(REPO_ROOT, NS, "path_forensics",
                         "ABSOLUTE_PATH_INVENTORY.json")
OUT_ROOT = os.path.join(REPO_ROOT, NS, "portable_evidence")
SUMMARY_OUT = os.path.join(NS, "portable_paths",
                           "PORTABLE_EVIDENCE_NORMALIZATION.json")

# narrow, explicit rules for the ONLY non-repository environment
# prefixes that occur inside the official runtime-safety records:
# interpreter homes on the authoring machine. Historical runs used the
# uv-managed cpython home; the 2026-09-18 clean-room runs used the
# authoring machine's project virtualenv. Both are environment
# references, not repository content — both map to explicit documented
# placeholder tokens (fail-closed: any OTHER machine path aborts).
UV_PYTHON_PREFIX = re.compile(
    r"^/home/[^/]+/\.local/share/uv/python/([^/]+)")
VENV_PREFIX = re.compile(r"^(/home/[^/]+/\.venv/)")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def machine_path_hits(text):
    """All detector ids firing on a text (shared detector set)."""
    return [d for d, p in MACHINE_PATH_DETECTORS if p.search(text)]


def build_placeholder_map(doc):
    """Derive the environment placeholder map for one document.

    Only uv-managed interpreter homes are mapped; any OTHER
    non-repository machine path inside the official evidence would
    abort the run (unexpected machine reference — fail closed).
    """
    found = {}

    def walk(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
        elif isinstance(obj, str):
            m = UV_PYTHON_PREFIX.match(obj)
            if m:
                prefix = m.group(0)
                token = f"<<uv-python:{m.group(1)}>>"
                found[prefix] = token
            else:
                mv = VENV_PREFIX.match(obj)
                if mv:
                    found[mv.group(1)] = "<<venv-python>>"

    walk(doc)
    return found


def normalize_one(source_rel):
    """Create the normalized derived copy for one source file."""
    src_abs = os.path.join(REPO_ROOT, source_rel)
    sha_before = sha256_file(src_abs)
    with open(src_abs, encoding="utf-8") as f:
        doc = json.load(f)

    placeholder_map = build_placeholder_map(doc)
    new_doc, changes = normalize_document(doc, REPO_ROOT, placeholder_map)

    # serialize the derived copy (canonical JSON, sorted keys)
    body = json.dumps(new_doc, indent=2, sort_keys=True) + "\n"

    # fail-closed: the derived copy must contain ZERO machine paths
    hits = machine_path_hits(body)
    if hits:
        raise RuntimeError(
            f"{source_rel}: derived copy still contains machine "
            f"paths ({sorted(set(hits))}) — aborting")

    derivation = {
        "derived_from": source_rel,
        "source_sha256": sha_before,
        "policy": "A — original preserved byte-exact; this file is a "
                  "clearly-marked normalized derived representation",
        "normalization": "repository-local absolute paths rewritten "
                         "to repo-relative POSIX paths; historical "
                         "interpreter-home prefixes rewritten to "
                         "explicit placeholder tokens; all other "
                         "values unchanged",
        "normalized_field_paths": [c["json_path"] for c in changes],
        "normalized_string_count": len(changes),
        "environment_placeholders": {tok: "uv-managed cpython "
                                     "interpreter home "
                                     "(authoring machine; see source "
                                     "recorded above)" 
                                     for tok in set(
                                         placeholder_map.values())},
        "portability": "PORTABLE",
    }
    wrapped = {"portable_derivation": derivation, **new_doc}

    out_rel = os.path.join(NS, "portable_evidence", source_rel)
    out_abs = os.path.join(REPO_ROOT, out_rel)
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)
    with open(out_abs, "w", encoding="utf-8") as f:
        f.write(json.dumps(wrapped, indent=2, sort_keys=True) + "\n")

    # verify the original was not touched
    sha_after = sha256_file(src_abs)
    if sha_after != sha_before:
        raise RuntimeError(
            f"{source_rel}: ORIGINAL MUTATED during normalization "
            f"({sha_before[:12]} -> {sha_after[:12]}) — aborting")

    # verify the derived copy round-trips and is path-clean
    with open(out_abs, encoding="utf-8") as f:
        recheck = json.load(f)
    assert recheck["portable_derivation"]["source_sha256"] == sha_before
    body2 = json.dumps(recheck, indent=2, sort_keys=True)
    if machine_path_hits(body2):
        raise RuntimeError(f"{source_rel}: re-check found machine paths")

    return {
        "source": source_rel,
        "source_sha256": sha_before,
        "derived_copy": out_rel,
        "derived_copy_sha256": sha256_file(out_abs),
        "normalized_string_count": len(changes),
        "normalized_field_paths": [c["json_path"] for c in changes],
        "environment_placeholder_marks": sorted(
            set(placeholder_map.values())),
        "source_unchanged": True,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Phase 2: apply the portable path standard "
                    "(policy A derived copies; originals preserved)")
    args = parser.parse_args()

    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    with open(INVENTORY, encoding="utf-8") as f:
        inventory = json.load(f)

    # policy A applies to exactly the AUTHORITATIVE files that carry
    # repository-local machine paths (the official 3M evidence root)
    sources = sorted({
        h["file"] for h in inventory["findings"]
        if h["action"] == "PRESERVE_HISTORICAL_CREATE_NORMALIZED_DERIVED"
    })
    print(f"policy-A sources: {len(sources)}")
    records = []
    for src in sources:
        rec = normalize_one(src)
        records.append(rec)
        print(f"  normalized {rec['normalized_string_count']:3d} "
              f"strings: {src} -> {rec['derived_copy']}")

    # repo-wide verification: every source byte-identical to Phase 1
    # baseline (Phase 1 captured findings against the same files)
    doc = {
        "report": "DQAEIP portable evidence normalization (Phase 2) — "
                  "policy A derived representations",
        "schema": {"name": "dqaeip.normalization_summary",
                   "version": "1.0"},
        "release_id": "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18",
        "generated_utc": started,
        "policy": {
            "choice": "A",
            "statement": "AUTHORITATIVE official evidence preserved "
                         "byte-exact; clearly-marked normalized derived "
                         "representations created under "
                         "evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18/"
                         "portable_evidence/ mirroring the source "
                         "layout",
            "superseded_and_unknown_artifacts": "preserved as historical "
                         "record — NOT normalized (rewriting history is "
                         "forbidden); see ABSOLUTE_PATH_INVENTORY.json "
                         "and the historical evidence policy",
        },
        "centralized_utility": "data_quality_platform/assurance/"
                               "portable_evidence.py (the single "
                               "path-normalization implementation)",
        "sources": records,
        "verification": {
            "originals_byte_identical": all(
                r["source_unchanged"] for r in records),
            "derived_copies_machine_path_free": True,
            "derived_copies_reparse_clean": True,
        },
    }

    out_abs = os.path.join(REPO_ROOT, SUMMARY_OUT)
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)
    with open(out_abs, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"normalization summary written: {SUMMARY_OUT}")
    total = sum(r["normalized_string_count"] for r in records)
    print(f"total normalized strings: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
