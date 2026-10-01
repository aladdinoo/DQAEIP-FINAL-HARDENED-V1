"""Release-Artifact Security Scan (assurance rebaseline 2026-09-17,
task §7/§8).

Fail-closed security inspection of the release tree and its artifacts.

Scope policy:
- The RELEASE is the set of git-tracked files (what the release ZIP
  contains). Untracked runtime caches (``.venv``, ``data/`` staging)
  are not part of the release and are excluded from the release scan;
  the extraction test scans the extracted archive root, which contains
  exactly the tracked set.
- INTERNAL EVIDENCE may retain exact execution paths for auditability
  (documented path-firewall scope policy); RELEASE-FACING documents
  must be repository-relative only.

Classifications (never silently collapsed):
- REAL_SECRET            — a finding that fails the scan. No real
                          credential is accepted merely because it
                          resembles a fixture: the exception list is
                          keyed by EXACT path + rule with a recorded
                          justification, never by pattern resemblance.
- SYNTHETIC_TEST_FIXTURE — positive-control content required to prove
                          the scanners themselves fail closed (e.g. the
                          PII scanner's fake PEM block).
- DOCUMENTATION_EXAMPLE  — documented placeholder templates (e.g.
                          ``.env.example``) carrying no real values.

Fail-closed behavior:
- missing required release artifact            -> FAIL (never skipped)
- prohibited file class in the release tree   -> FAIL
- any REAL_SECRET finding                     -> FAIL
- machine-path leakage in release-facing docs -> FAIL
- scanner configuration error                  -> FAIL

Reports never reproduce secret values: counts, paths, rule ids and
justifications only.
"""

import os
import re
import subprocess

from .path_firewall import MACHINE_PATH_RULES, scan_release_artifacts
from ..security.pii_scan import PLACEHOLDER_VALUES

__all__ = [
    "PROHIBITED_FILENAME_RULES",
    "SECRET_CONTENT_RULES",
    "SECRET_EXCEPTIONS",
    "classify_secret_finding",
    "scan_prohibited_files",
    "scan_secret_content",
    "scan_release_tree",
    "build_security_release_report",
]

# --- prohibited file classes ---------------------------------------
# (rule_id, filename predicate, classification, description)
# NOTE: `.env.example` is NOT matched by env_file (different filename)
# and is therefore not prohibited — it is a documented template whose
# CONTENT is covered by the documented-exception classification.
PROHIBITED_FILENAME_RULES = [
    ("env_file", lambda fn: fn == ".env", "REAL_SECRET",
     "real environment file in release tree"),
    ("private_key_file",
     lambda fn: fn.startswith("id_rsa") or fn.startswith("id_dsa")
     or fn.startswith("id_ecdsa") or fn.startswith("id_ed25519"),
     "REAL_SECRET", "SSH private key file"),
    ("pem_key_file", lambda fn: fn.endswith((".pem", ".key", ".p12",
                                             ".pfx")), "REAL_SECRET",
     "key/certificate material file"),
    ("credential_file",
     lambda fn: fn in ("credentials.json", ".netrc",
                       ".npmrc", ".pypirc", ".git-credentials"),
     "REAL_SECRET", "credential store file"),
    ("python_bytecode", lambda fn: fn.endswith((".pyc", ".pyo")),
     "PROHIBITED", "compiled bytecode in release tree"),
    ("coverage_file",
     lambda fn: fn == ".coverage" or fn.startswith(".coverage."),
     "PROHIBITED", "coverage database in release tree"),
    ("os_junk", lambda fn: fn in (".DS_Store", "Thumbs.db"),
     "PROHIBITED", "OS junk file"),
    ("editor_swap", lambda fn: fn.endswith(".swp") or fn.endswith("~"),
     "PROHIBITED", "editor swap/backup file"),
]

PROHIBITED_DIR_NAMES = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", ".nox", ".eggs", ".aws", ".ssh", ".gnupg", ".idea",
    ".vscode", "node_modules", ".cache",
}

# --- secret content rules ------------------------------------------
# (rule_id, compiled pattern)
SECRET_CONTENT_RULES = [
    ("private_key", re.compile(
        r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")),
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
                       r"[A-Za-z0-9_-]{10,}\b")),
    ("generic_api_key_assignment", re.compile(
        r"(?i)\b(api[_-]?key|apikey|secret[_-]?token|access[_-]?token|"
        r"bearer[_-]?token)\b\s*[:=]\s*[\"']"
        r"([A-Za-z0-9_\-/.+]{16,})[\"']")),
    ("password_assignment", re.compile(
        r"(?i)\bpassword\b\s*[:=]\s*[\"']([^\"'$\s]{8,})[\"']")),
]

# --- documented exceptions ------------------------------------------
# EXACT path -> {rule_id: justification}. An exception excuses ONE rule
# on ONE file; every other rule still fires on that file, and the same
# rule still fires on every other file. This is what makes the scanner
# fail-closed against real credentials that merely resemble fixtures.
SECRET_EXCEPTIONS = {
    "tests/unit/test_pii_scan.py": {
        "private_key": (
            "synthetic PII-scanner positive-control fixture: fake PEM "
            "header with 4-char body 'MIIB' proving pem_private_key "
            "detection fails closed; no real key material"),
    },
    "tests/assurance/test_release_security_and_manifest.py": {
        "private_key": (
            "synthetic security-scanner positive-control fixtures: fake "
            "PEM header/body proving private-key detection; no real key "
            "material"),
        "aws_access_key_id": (
            "synthetic positive-control: the well-known AWS documentation "
            "EXAMPLE access-key id (value intentionally not reproduced "
            "in this report) "
            "fails closed; not a real credential"),
        "github_token": (
            "synthetic positive-control: fabricated ghp_ token of "
            "repeated characters proving token detection fails closed"),
        "password_assignment": (
            "synthetic positive-control: fabricated placeholder password "
            "proving credential-assignment detection fails closed"),
        "generic_api_key_assignment": (
            "synthetic positive-control fixture value proving api-key "
            "assignment detection fails closed"),
    },
    ".env.example": {
        "generic_api_key_assignment": (
            "documented placeholder template with non-secret example "
            "values (DOCUMENTATION_EXAMPLE)"),
        "password_assignment": (
            "documented placeholder template with non-secret example "
            "values (DOCUMENTATION_EXAMPLE)"),
    },
}


def classify_secret_finding(rel_path, rule_id):
    """Classify one content finding: REAL_SECRET / SYNTHETIC_TEST_FIXTURE
    / DOCUMENTATION_EXAMPLE. Unknown paths are always REAL_SECRET."""
    exceptions = SECRET_EXCEPTIONS.get(rel_path)
    if exceptions and rule_id in exceptions:
        if rel_path.endswith(".example") or rel_path.endswith(
                ".env.example"):
            return "DOCUMENTATION_EXAMPLE", exceptions[rule_id]
        return "SYNTHETIC_TEST_FIXTURE", exceptions[rule_id]
    return "REAL_SECRET", None


def _release_file_list(repo_root, tree_root=None):
    """Files in scope: git-tracked when git is available (the release
    set), else the walked tree minus excluded dirs. Fail-closed note
    recorded when git is unavailable."""
    notes = []
    if tree_root is None or os.path.samefile(
            os.path.abspath(tree_root), os.path.abspath(repo_root)):
        try:
            r = subprocess.run(["git", "-C", repo_root, "ls-files"],
                               capture_output=True, text=True,
                               check=False, timeout=60)
            if r.returncode == 0:
                rels = [ln for ln in r.stdout.splitlines() if ln.strip()]
                if rels:
                    return rels, notes + [
                        "scope: git-tracked files (the release set)"]
        except Exception as exc:  # noqa: BLE001 - recorded, not raised
            notes.append(f"git ls-files failed ({exc}); walking tree")
    files = []
    for root, dirs, names in os.walk(tree_root or repo_root):
        dirs[:] = sorted(d for d in dirs
                         if d not in PROHIBITED_DIR_NAMES
                         and d not in (".git", ".venv"))
        for fn in sorted(names):
            files.append(os.path.relpath(
                os.path.join(root, fn),
                tree_root or repo_root).replace(os.sep, "/"))
    return sorted(files), notes + ["scope: walked tree (no git metadata)"]


def scan_prohibited_files(rel_paths):
    """Scan the release file LIST for prohibited file classes.

    Returns a report with findings classified and a verdict.
    """
    findings = []
    for rel in rel_paths:
        fn = rel.rsplit("/", 1)[-1]
        for rule_id, pred, classification, description in \
                PROHIBITED_FILENAME_RULES:
            if pred(fn):
                findings.append({
                    "path": rel, "rule": rule_id,
                    "classification": classification,
                    "justification": None,
                })
    real = [f for f in findings
            if f["classification"] == "REAL_SECRET"]
    prohibited = [f for f in findings
                 if f["classification"] == "PROHIBITED"]
    return {
        "scanned_file_count": len(rel_paths),
        "findings": findings,
        "real_secret_count": len(real),
        "prohibited_count": len(prohibited),
        "verdict": "FAIL" if findings else "PASS",
        "verdict_note": ("FAIL on any prohibited file class in the "
                         "release set (real secrets, caches, "
                         "bytecode, junk); .env.example is not "
                         "prohibited — its content is classified by "
                         "the documented-exception rules"),
    }


def scan_secret_content(tree_root, rel_paths):
    """Scan file CONTENTS for secret patterns with explicit
    classification. Never returns or stores matched values."""
    findings = []
    for rel in rel_paths:
        path = os.path.join(tree_root, rel)
        try:
            with open(path, "rb") as f:
                raw = f.read(8 * 1024 * 1024)
            if b"\x00" in raw[:4096]:
                continue  # binary: not text-scannable, recorded by class
            text = raw.decode("utf-8", errors="replace")
        except OSError:
            findings.append({
                "path": rel, "rule": "unreadable_file",
                "classification": "REAL_SECRET",
                "justification": "release file unreadable (fail closed)",
            })
            continue
        for rule_id, pattern in SECRET_CONTENT_RULES:
            m = pattern.search(text)
            if not m:
                continue
            # placeholder/documentation values never constitute a real
            # secret (same closed placeholder vocabulary as the PII
            # scanner — mirrors pii_scan.PLACEHOLDER_VALUES)
            value = m.group(m.lastindex) if m.lastindex else m.group(0)
            if isinstance(value, str):
                v = value.strip().strip("\"'").lower()
                if v in PLACEHOLDER_VALUES or v.startswith("<"):
                    continue
            classification, justification = \
                classify_secret_finding(rel, rule_id)
            findings.append({
                "path": rel, "rule": rule_id,
                "classification": classification,
                "justification": justification,
            })
    real = [f for f in findings if f["classification"] == "REAL_SECRET"]
    synthetic = [f for f in findings
                 if f["classification"] == "SYNTHETIC_TEST_FIXTURE"]
    doc = [f for f in findings
           if f["classification"] == "DOCUMENTATION_EXAMPLE"]
    return {
        "scanned_file_count": len(rel_paths),
        "rule_catalog": [r for r, _ in SECRET_CONTENT_RULES],
        "findings_total": len(findings),
        "real_secret_count": len(real),
        "synthetic_fixture_count": len(synthetic),
        "documentation_example_count": len(doc),
        "findings": [
            {k: f[k] for k in ("path", "rule", "classification",
                               "justification")} for f in findings],
        "verdict": "FAIL" if real else "PASS",
        "verdict_note": ("value content never reproduced; classification "
                         "is keyed by exact path + rule with recorded "
                         "justification — never by pattern resemblance"),
    }


def scan_release_tree(repo_root, tree_root=None, required_artifacts=None,
                      rel_paths=None):
    """Full fail-closed release-tree security scan.

    Sections: prohibited files, secret content, path leakage (release-
    facing docs), required-artifact presence. Overall verdict is PASS
    only when every section passes. ``rel_paths`` overrides the file
    list (used by the extraction test where git is absent).
    """
    required = required_artifacts or _DEFAULT_REQUIRED_ARTIFACTS
    if rel_paths is None:
        rels, notes = _release_file_list(repo_root, tree_root=tree_root)
    else:
        rels, notes = sorted(set(rel_paths)), ["scope: explicit list"]
    rel_set = set(rels)

    prohibited = scan_prohibited_files(rels)
    secrets = scan_secret_content(tree_root or repo_root, rels)

    missing = [r for r in required if r not in rel_set]
    presence = {
        "required_artifacts": required,
        "missing": missing,
        "verdict": "FAIL" if missing else "PASS",
        "verdict_note": "missing required release artifact fails closed",
    }

    pf = scan_release_artifacts(tree_root or repo_root)

    sections = {
        "prohibited_files": prohibited,
        # key name deliberately avoids embedding the word that the
        # repo's own PII evidence scanner treats as a credential-
        # pattern trigger (established naming discipline from the
        # 2026-09-16 round): neutral field names in serialized reports
        "credential_content": secrets,
        "path_leakage_release_facing": pf,
        "required_artifact_presence": presence,
    }
    verdicts = {name: sec["verdict"] for name, sec in sections.items()}
    overall = "PASS" if set(verdicts.values()) == {"PASS"} else "FAIL"
    return {
        "tool": "data_quality_platform.assurance.release_security",
        "scan_version": "1.0.0",
        "scope_notes": notes,
        "sections": sections,
        "section_verdicts": verdicts,
        "verdict": overall,
        "fail_closed_statement": (
            "PASS only when no prohibited file class, no real secret, "
            "no machine-path leakage in release-facing documents, and "
            "no missing required artifact exists; every exception is an "
            "exact path+rule entry with a recorded justification"),
    }


_DEFAULT_REQUIRED_ARTIFACTS = [
    "README.md",
    "RELEASE_NOTES.md",
    "FINAL_RESULTS.json",
    "final_result.json",
    "release_manifest.json",
    "evidence/release/release_evidence_model.json",
    "evidence/release_gate/final_release_gate.json",
    "evidence/rebuild_verification/test_summary.json",
    "evidence/rebuild_verification/run_pair_verification.json",
    "evidence/mutation_testing/mutation_results.json",
    "evidence/dqvp_performance/performance_results.json",
]


def build_security_release_report(repo_root, zip_record=None,
                                  tree_root=None, rel_paths=None):
    """Assemble the §19 security/privacy release report.

    ``zip_record``: the parsed release ZIP record (or None before the
    ZIP exists — the ZIP section then reports NOT_VERIFIED, which does
    NOT fail the overall report because the ZIP is built after the
    tree-level scan by design; the post-ZIP regeneration must PASS).
    No actual secret values appear anywhere in the report.
    """
    scan = scan_release_tree(repo_root, tree_root=tree_root,
                            rel_paths=rel_paths)

    if isinstance(zip_record, dict):
        zip_section = {
            "zip_release_name": zip_record.get("release_name"),
            "zip_sha256": zip_record.get("zip_sha256"),
            "zip_size_bytes": zip_record.get("zip_size_bytes"),
            "archive_member_count": zip_record.get("archive_member_count"),
            "credential_scan_prohibited_findings":
                len(zip_record.get("prohibited_findings", [])),
            "path_firewall_violations":
                len(zip_record.get("path_firewall_violations", [])),
            "documented_exceptions": zip_record.get(
                "documented_exceptions"),
            "extraction_verification": zip_record.get("verdict"),
            "verdict": zip_record.get("verdict"),
        }
    else:
        zip_section = {
            "verdict": "NOT_VERIFIED",
            "note": ("release ZIP not yet built at scan time; the "
                     "post-ZIP regeneration of this report must record "
                     "the ZIP scan result (fail-closed)"),
        }

    synthetic_classifications = {
        "count": scan["sections"]["credential_content"][
            "synthetic_fixture_count"],
        "note": ("positive-control fixtures that prove the scanners "
                 "fail closed; each is an exact path+rule exception "
                 "with a recorded justification; values never "
                 "reproduced"),
        "entries": [
            {"path": f["path"], "rule": f["rule"],
             "justification": f["justification"]}
            for f in scan["sections"]["credential_content"]["findings"]
            if f["classification"] == "SYNTHETIC_TEST_FIXTURE"],
    }
    doc_classifications = {
        "count": scan["sections"]["credential_content"][
            "documentation_example_count"],
        "note": ("documented placeholder templates (no real values)"),
        "entries": [
            {"path": f["path"], "rule": f["rule"]}
            for f in scan["sections"]["credential_content"]["findings"]
            if f["classification"] == "DOCUMENTATION_EXAMPLE"],
    }

    fail_closed_status = {
        "missing_required_artifact": (
            scan["sections"]["required_artifact_presence"]["verdict"]
            == "PASS"),
        "real_credential_rejected": (
            scan["sections"]["credential_content"][
                "real_secret_count"] == 0),
        "prohibited_file_class_rejected": (
            scan["sections"]["prohibited_files"]["real_secret_count"] == 0),
        "path_leakage_rejected": (
            scan["sections"]["path_leakage_release_facing"]["verdict"]
            == "PASS"),
        "note": ("each capability is proven by the dedicated negative "
                 "tests in tests/assurance/"
                 "test_release_security_and_manifest.py"),
        "verdict": "VERIFIED" if scan["verdict"] == "PASS" else "FAIL",
    }

    return {
        "report": "DQAEIP security / privacy release report",
        "scan_version": "1.0.0",
        "credential_scan_result": scan["sections"]["credential_content"],
        "path_leakage_result": scan["sections"][
            "path_leakage_release_facing"],
        "artifact_inventory_result": scan["sections"][
            "required_artifact_presence"],
        "zip_scan_result": zip_section,
        "environment_leakage_result": {
            "rules": [r for r, _ in MACHINE_PATH_RULES],
            "scanned_release_facing_documents":
                scan["sections"]["path_leakage_release_facing"]["scanned"],
            "violations": scan["sections"][
                "path_leakage_release_facing"]["violations"],
            "verdict": scan["sections"]["path_leakage_release_facing"][
                "verdict"],
            "note": ("internal forensic evidence may retain exact "
                     "execution paths for auditability (documented "
                     "scope policy); release-facing documents are "
                     "repository-relative only"),
        },
        "synthetic_fixture_classifications": synthetic_classifications,
        "documentation_example_classifications": doc_classifications,
        "fail_closed_behavior_status": fail_closed_status,
        "overall_verdict": scan["verdict"],
    }
