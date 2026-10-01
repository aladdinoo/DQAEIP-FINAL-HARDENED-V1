#!/usr/bin/env python3
"""DQAEIP FINAL PORTABLE EVIDENCE & RELEASE HARDENING — Phase 1.

ABSOLUTE-PATH FORENSICS over ALL evidence JSON/JSONL (task-book
section 2). Strictly READ-ONLY: this tool inventories, it never
modifies.

For every ``evidence/**/*.json`` and ``evidence/**/*.jsonl`` file the
tool parses the document and walks EVERY nested string (keys excluded,
values included — command lines, stdout/stderr captures, dataset
metadata, provenance, manifests, nested dicts and arrays, historical
derived evidence) recording:

    - file (repository-relative)
    - json_path (exact JSON key path, e.g. $.runs.run_1.cli.command,
      or $.[line 12].event for JSONL)
    - original value (the exact embedded string)
    - classification (REPOSITORY_LOCAL / MACHINE_OTHER / WINDOWS /
      WSL / FILE_URI / TEMP)
    - proposed normalized value (repo-relative POSIX path, or
      repo://<relative> logical URI where the field is an artifact
      identity; None when the value must NOT be normalized)
    - artifact_class (AUTHORITATIVE / DERIVED / SUPERSEDED / UNKNOWN
      from the verified full classification inventory)
    - action (see ACTIONS)
    - reason

Normalization policy preview (applied later, never here):
    - AUTHORITATIVE historical evidence is PRESERVED byte-exact; a
      clearly-marked normalized DERIVED representation is created
      alongside it (historical-evidence policy, task section 16).
    - Safely regenerable DERIVED evidence may be normalized in place.
    - External URLs, hashes, emails, documentation examples and
      legitimate non-repository paths are NEVER converted.
"""

import argparse
import glob
import json
import os
import re
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

NS = "evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18"
OUT_DIR = os.path.join(REPO_ROOT, NS, "path_forensics")

CLASSIFICATION_MAP = os.path.join(
    REPO_ROOT, NS, "baseline", "authoritative_inventory.json")

# --- machine-path detectors (decoded strings, not raw bytes) -----------
DETECTORS = [
    ("posix_home", re.compile(r"(?<![A-Za-z0-9])/home/[A-Za-z0-9_.-]+")),
    ("macos_users", re.compile(r"(?<![A-Za-z0-9])/Users/[A-Za-z0-9_.-]+")),
    ("root_home", re.compile(r"(?<![A-Za-z0-9])/root/")),
    ("mounted_volume", re.compile(r"(?<![A-Za-z0-9])/mnt/[A-Za-z0-9_.-]+")),
    ("machine_tmp", re.compile(r"(?<![A-Za-z0-9])/tmp/")),
    ("system_var", re.compile(
        r"(?<![A-Za-z0-9])/var/(?:lib|log|tmp|spool)/")),
    ("service_tree", re.compile(r"(?<![A-Za-z0-9])/srv/")),
    # windows drive: drive letter at a word boundary (NOT part of a URL
    # scheme like https: — the lookbehind rejects letters/digits before
    # the drive letter, so "https://x" can never match)
    ("windows_drive", re.compile(
        r"(?<![A-Za-z0-9])[A-Za-z]:[/\\][A-Za-z0-9_.\\\\/ -]*")),
    ("unc_share", re.compile(r"\\\\[A-Za-z0-9_.$-]+\\[A-Za-z0-9_.$-]+")),
    ("file_uri", re.compile(r"file://[A-Za-z0-9_.:/\\-]+")),
]

# repo-local detection: the machine-specific prefix of THIS repository
REPO_ROOT_ABS = REPO_ROOT.rstrip("/") + "/"
REPO_PARENT_ABS = os.path.dirname(REPO_ROOT.rstrip("/")) + "/"


def decode_escapes(value):
    """Normalize common JSON string escapes for detection purposes
    (the decoded Python string already has \\ un-escaped by json.load;
    this handles double-escaped sequences recorded in stdout text)."""
    return value


def classify_hit(value, detector_id, match_text):
    """Classify one detected machine path string.

    Classification considers the WHOLE embedded string (not just the
    matched fragment): ``/home/z/my-project/dqvp-work/repo/x`` is a
    repository-local path even when the detector matched only the
    ``/home/z`` prefix fragment.
    """
    m = match_text
    # repository-local: the embedded value references THIS repository
    if REPO_ROOT_ABS in value:
        return "REPOSITORY_LOCAL", None
    if detector_id == "file_uri":
        return "FILE_URI", None
    if detector_id in ("windows_drive", "unc_share"):
        return "WINDOWS", None
    if m.startswith("/tmp/") or m.startswith("/var/tmp/"):
        return "TEMP", None
    if m.startswith("/mnt/"):
        return "WSL", None
    return "MACHINE_OTHER", None


def proposed_normalization(value, hit_class, repo_root_abs):
    """Propose the portable normalized value for a REPOSITORY_LOCAL hit.

    Only repository-local paths are normalized. Everything else keeps
    its original value (external tool paths, system trees, URLs, ...).
    """
    if hit_class != "REPOSITORY_LOCAL":
        return None
    prefix = repo_root_abs.rstrip("/")
    v = value
    norm = None
    if prefix + "/" in v:
        idx = v.index(prefix + "/")
        after = v[idx + len(prefix) + 1:]
        norm = after
    elif v.startswith(prefix):
        norm = ""
    if norm is None:
        return None
    norm = norm.replace("\\", "/").strip()
    return norm or "."


def walk(obj, path, hits, file_rel, repo_root_abs, container):
    """Recursively walk a parsed JSON document collecting path hits."""
    if isinstance(obj, dict):
        for k in sorted(obj.keys()):
            walk(obj[k], f"{path}.{k}", hits, file_rel, repo_root_abs,
                 container)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            walk(item, f"{path}[{i}]", hits, file_rel, repo_root_abs,
                 container)
    elif isinstance(obj, str):
        for detector_id, pattern in DETECTORS:
            for match in pattern.finditer(obj):
                m = match.group(0)
                hit_class, _ = classify_hit(obj, detector_id, m)
                hits.append({
                    "file": file_rel,
                    "json_path": path,
                    "container": container,
                    "original_value": obj,
                    "matched_fragment": m,
                    "detector": detector_id,
                    "classification": hit_class,
                    "proposed_normalized_value": proposed_normalization(
                        obj, hit_class, repo_root_abs),
                })
                break  # one record per string per detector family


def artifact_class_of(rel, classification_map):
    entry = classification_map.get(rel)
    if entry:
        return entry.get("classification", "UNKNOWN")
    # new files created after the verified inventory (this release's
    # namespace) are DERIVED portable evidence by construction
    if rel.startswith(NS + "/"):
        return "DERIVED"
    return "UNKNOWN"


def action_for(art_class, hit_class, file_rel):
    if hit_class != "REPOSITORY_LOCAL":
        return ("RETAIN_NON_REPOSITORY", "value is not a repository-local "
                "path; portability policy forbids converting external "
                "system/tool references")
    if file_rel.startswith("evidence/validation/2026-09-18/fresh_3m2/harness/"):
        return ("PRESERVE_HISTORICAL_CREATE_NORMALIZED_DERIVED",
                "AUTHORITATIVE official run evidence — historical truth "
                "is preserved byte-exact; a clearly-marked normalized "
                "derived representation will be created (policy A, "
                "task section 16)")
    if art_class == "AUTHORITATIVE":
        return ("PRESERVE_HISTORICAL_CREATE_NORMALIZED_DERIVED",
                "AUTHORITATIVE historical evidence — preserve original; "
                "create normalized derived representation (policy A)")
    if art_class == "DERIVED":
        if file_rel.startswith(NS + "/"):
            return ("NORMALIZE_IN_PLACE",
                    "new portable-release namespace is derived evidence "
                    "being generated in this release; must be portable "
                    "from birth")
        return ("NORMALIZE_IF_REGENERABLE",
                "derived evidence; normalize in place only when "
                "explicitly classified safely regenerable, else policy A")
    if art_class == "SUPERSEDED":
        return ("PRESERVE_HISTORICAL",
                "superseded historical evidence; preserved as record "
                "(normalization would rewrite history without adding "
                "portability value)")
    return ("PRESERVE_UNKNOWN_PROTECTED",
            "UNKNOWN artifacts are protected; never auto-normalized")


def main():
    parser = argparse.ArgumentParser(
        description="Phase 1: absolute-path forensics inventory "
                    "(READ-ONLY)")
    parser.add_argument("--out-dir", default=OUT_DIR)
    args = parser.parse_args()

    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    with open(CLASSIFICATION_MAP, encoding="utf-8") as f:
        classification_map = json.load(f)["full_classification"]

    json_files = sorted(glob.glob(
        os.path.join(REPO_ROOT, "evidence", "**", "*.json"),
        recursive=True))
    jsonl_files = sorted(glob.glob(
        os.path.join(REPO_ROOT, "evidence", "**", "*.jsonl"),
        recursive=True))

    # the scanner's own output directory is EXCLUDED from scope: a
    # forensics report necessarily QUOTES the violations it found;
    # scanning it back would be self-referential (the report cannot
    # audit its own pre-measurement state — same principle as the
    # quarantine-screen exclusion documented in the rebuild round)
    scan_exclusions = (os.path.join(REPO_ROOT, NS, "path_forensics"),)
    json_files = [p for p in json_files if not any(
        p.startswith(ex + os.sep) or p == ex for ex in scan_exclusions)]
    jsonl_files = [p for p in jsonl_files if not any(
        p.startswith(ex + os.sep) or p == ex for ex in scan_exclusions)]

    findings = []
    parse_errors = []
    scanned = 0

    for abs_path in json_files + jsonl_files:
        rel = os.path.relpath(abs_path, REPO_ROOT).replace(os.sep, "/")
        scanned += 1
        is_jsonl = abs_path.endswith(".jsonl")
        try:
            if is_jsonl:
                with open(abs_path, encoding="utf-8") as f:
                    docs = []
                    for ln, line in enumerate(f, start=1):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            docs.append((ln, json.loads(line)))
                        except json.JSONDecodeError:
                            parse_errors.append(
                                {"file": rel, "line": ln,
                                 "error": "malformed JSONL line"})
                for ln, doc in docs:
                    walk(doc, f"$[line {ln}]", findings, rel,
                         REPO_ROOT_ABS, "jsonl")
            else:
                with open(abs_path, encoding="utf-8") as f:
                    doc = json.load(f)
                walk(doc, "$", findings, rel, REPO_ROOT_ABS, "json")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            parse_errors.append({"file": rel, "error": str(exc)[:200]})
            continue

    # attach artifact classification + action + reason
    for hit in findings:
        art_class = artifact_class_of(hit["file"], classification_map)
        hit["artifact_class"] = art_class
        action, reason = action_for(
            art_class, hit["classification"], hit["file"])
        hit["action"] = action
        hit["reason"] = reason

    by_class = {}
    by_action = {}
    by_artifact_class = {}
    by_file = {}
    for hit in findings:
        by_class[hit["classification"]] = by_class.get(
            hit["classification"], 0) + 1
        by_action[hit["action"]] = by_action.get(hit["action"], 0) + 1
        by_artifact_class[hit["artifact_class"]] = by_artifact_class.get(
            hit["artifact_class"], 0) + 1
        by_file[hit["file"]] = by_file.get(hit["file"], 0) + 1

    doc = {
        "report": "DQAEIP absolute-path inventory — complete JSON "
                  "forensics (READ-ONLY; nothing modified)",
        "schema": {"name": "dqaeip.absolute_path_inventory",
                   "version": "1.0"},
        "release_id": "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18",
        "generated_utc": started,
        "scope": {
            "globs": ["evidence/**/*.json", "evidence/**/*.jsonl"],
            "files_matched": scanned,
            "json_files": len(json_files),
            "jsonl_files": len(jsonl_files),
            "parse_errors": parse_errors,
        },
        "detection_policy": {
            "detectors": [d for d, _ in DETECTORS],
            "notes": [
                "detection runs on DECODED string values (not raw "
                "bytes), so JSON-escaped backslashes cannot hide a "
                "Windows path",
                "one record per (string value, detector) pair; the "
                "matched fragment is recorded verbatim",
                "strings inside nested dicts, arrays, command lines, "
                "stdout/stderr captures, provenance, dataset metadata "
                "and manifests are all walked",
            ],
        },
        "summary": {
            "total_findings": len(findings),
            "by_classification": by_class,
            "by_action": by_action,
            "by_artifact_class": by_artifact_class,
            "distinct_files_with_findings": len(by_file),
            "top_files": sorted(
                by_file.items(), key=lambda kv: -kv[1])[:25],
        },
        "findings": findings,
        "normalization_policy_preview": {
            "REPOSITORY_LOCAL": "repo-relative POSIX paths (or repo:// "
            "URIs for artifact identity fields)",
            "MACHINE_OTHER": "never converted (external system/tool "
            "reference; not a repository artifact path)",
            "WINDOWS": "never auto-converted unless value is a "
            "repository artifact path (documentation examples kept)",
            "WSL": "same as REPOSITORY_LOCAL when it resolves inside "
            "the repository, else retained",
            "FILE_URI": "converted only when it points inside the "
            "repository",
            "TEMP": "retained in historical records; portable "
            "evidence must not depend on temp paths",
        },
    }

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, "ABSOLUTE_PATH_INVENTORY.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"scanned {scanned} files "
          f"({len(json_files)} json, {len(jsonl_files)} jsonl)")
    print(f"parse errors: {len(parse_errors)}")
    print(f"total findings: {len(findings)}")
    print("by classification:", json.dumps(by_class, sort_keys=True))
    print("by action:", json.dumps(by_action, sort_keys=True))
    print("by artifact class:",
          json.dumps(by_artifact_class, sort_keys=True))
    print(f"distinct files with findings: {len(by_file)}")
    print(f"inventory written: "
          f"{os.path.relpath(out_path, REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
