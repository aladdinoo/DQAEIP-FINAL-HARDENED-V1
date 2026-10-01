"""Machine-Path Firewall (DQAEIP rebuild Phase 11).

Release-facing artifacts MUST use repository-relative paths only.
This scanner detects machine-local absolute-path leakage in generated
JSON, Markdown, TXT, manifests and release metadata.

DETECTED PATTERNS (each mapped to a rule id):

    /home/           POSIX home directories (e.g. /home/z/...)
    /Users/          macOS user homes
    /root/           root home
    /mnt/            mounted volumes
    /tmp/            machine-local temp directories
    /var/ /srv/      machine-local system trees
    [A-Za-z]:\\\\     Windows drive letters (C:\\, D:\\, ...)
    \\\\\\\\           UNC network shares (\\\\\\\\server\\\\...)
    ~user            user-specific tilde homes (~/..., ~alice/...)
    dqvp-work        this machine's working-directory name

Policy:
- Violations are REPORTED, never silently hidden.
- The verdict is FAIL when any release-facing artifact contains a
  machine-local path.
- Internal execution logs (e.g. historical run stdout) are NOT scanned
  by the release-facing invocation; the caller decides scope. The
  release-artifact default scope in ``scan_release_artifacts`` is the
  authoritative one for the release gate.

This module never modifies files. Read-only detection, fail-closed
reporting.
"""

import json
import os
import re

__all__ = [
    "MACHINE_PATH_RULES",
    "DEFAULT_RELEASE_ARTIFACTS",
    "scan_text",
    "scan_file",
    "scan_release_artifacts",
]

MACHINE_PATH_RULES = [
    ("posix_home", re.compile(r"/home/")),
    ("macos_users", re.compile(r"/Users/")),
    ("root_home", re.compile(r"/root/")),
    ("mounted_volume", re.compile(r"/mnt/")),
    ("machine_tmp", re.compile(r"/tmp/")),
    ("system_var", re.compile(r"/var/(?:lib|log|tmp|spool)/")),
    ("service_tree", re.compile(r"/srv/")),
    ("windows_drive", re.compile(r"[A-Za-z]:\\")),
    # UNC shares: two or more literal backslashes + host name. Matches
    # both plain text (\\server\share) and JSON-escaped forms
    # (\\\\server\\share in raw file bytes). The negative lookahead
    # excludes JSON unicode escapes (\\u2014 etc.) which are serialized
    # characters, never paths.
    ("unc_share", re.compile(r"\\{2,}(?![uU][0-9a-fA-F]{4})"
                             r"[A-Za-z0-9_.$-]+")),
    ("tilde_user", re.compile(r"(?<![A-Za-z0-9_.-])~/")),
    ("tilde_named_user", re.compile(r"(?<![A-Za-z0-9_.-])~[A-Za-z][A-Za-z0-9_-]*/")),
    ("dqvp_work_dirname", re.compile(r"\bdqvp-work\b")),
]

# Artifacts that are RELEASE-FACING and therefore hard-scanned by default.
# (Internal diagnostics — e.g. scan reports that quote violations — live
# under evidence/rebuild_verification/ and are NOT scanned here.)
DEFAULT_RELEASE_ARTIFACTS = [
    "FINAL_RESULTS.json",
    "final_result.json",
    "release_manifest.json",
    "README.md",
    "RELEASE_NOTES.md",
    "DELIVERY_MANIFEST.json",
    "evidence/release/reproducibility_manifest.json",
    "evidence/release/golden_release_snapshot.json",
    "evidence/release/limitation_registry.json",
    "evidence/release/release_evidence_model.json",
    "evidence/release/claim_provenance.json",
    "evidence/release/consistency_matrix.json",
    "evidence/release/assurance_mutation.json",
]


def scan_text(text, source="<text>"):
    """Scan one text blob; return a list of violation records."""
    violations = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for rule_id, pattern in MACHINE_PATH_RULES:
            for match in pattern.finditer(line):
                start, end = match.span()
                excerpt = line[max(0, start - 30):min(len(line), end + 30)]
                violations.append({
                    "rule": rule_id,
                    "source": source,
                    "line": lineno,
                    "column": start + 1,
                    "matched": match.group(0),
                    "excerpt": excerpt.strip(),
                })
    return violations


def scan_file(path, repo_root=None):
    """Scan one file; ``source`` is repository-relative when possible."""
    source = path
    if repo_root:
        try:
            source = os.path.relpath(path, repo_root).replace(os.sep, "/")
        except ValueError:
            source = path
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return scan_text(f.read(), source=source)


def scan_release_artifacts(repo_root, artifacts=None):
    """Scan the release-facing artifacts. FAIL CLOSED on any violation.

    Returns a report dict:
        {"scanned": [...], "missing": [...], "violations": [...],
         "verdict": "PASS"|"FAIL"}
    """
    artifacts = artifacts or DEFAULT_RELEASE_ARTIFACTS
    scanned, missing, violations = [], [], []
    for rel in artifacts:
        path = os.path.join(repo_root, rel)
        if not os.path.isfile(path):
            missing.append(rel)
            continue
        scanned.append(rel)
        violations.extend(scan_file(path, repo_root=repo_root))
    return {
        "scanned": scanned,
        "missing": sorted(missing),
        "violations": violations,
        "violation_count": len(violations),
        "verdict": "FAIL" if (violations or missing) else "PASS",
        "verdict_note": (
            "PASS only when every release-facing artifact exists and "
            "contains zero machine-local paths; missing artifacts also "
            "fail (fail-closed), they are never silently skipped"
        ),
        "rule_catalog": [rule_id for rule_id, _ in MACHINE_PATH_RULES],
    }
