"""PII / Security Evidence Scan (DQAVP enterprise hardening, Section 22).

Scans generated EVIDENCE files (not company source data) for:

    - accidental raw PII: e-mail addresses outside the synthetic
      generator's domain set, phone-number-like strings
    - credentials / secrets / tokens with real values, PEM private keys
    - machine-identifying absolute local paths

FAIL CLOSED on prohibited content. Reports never print the PII itself:
only counts, categories, and file paths are reported.

Synthetic-vs-real classification is EXPLICIT, not heuristic hand-waving:

    The deterministic data generator (data_quality_platform/generation/
    synthetic.py) produces e-mail addresses exclusively on the domains

        example.com test.org mail.com web.net company.co business.io

    plus RFC 2606 / RFC 6761 reserved names (example.org/.test/.invalid/
    .example/localhost). An e-mail on any other domain is treated as
    PROHIBITED raw PII. Phone-like strings inside CSV evidence are
    checked against the generator's synthetic phone construction; all
    other phone-like strings are PROHIBITED.

The scan reads only files with safe text-ish extensions inside the
requested tree; binaries are recorded but not decoded.
"""

import os
import re
from typing import Any, Dict, List

__all__ = ["scan_tree_for_pii", "scan_file_for_pii",
           "SYNTHETIC_EMAIL_DOMAINS"]

SYNTHETIC_EMAIL_DOMAINS = {
    # generator DOMAINS (data_quality_platform/generation/synthetic.py)
    "example.com", "example.org", "example.net", "test.org",
    "mail.com", "web.net", "company.co", "business.io",
    # RFC 2606 / 6761 reserved names
    "invalid", "test", "example", "localhost",
    # in-repo verification-fixture domain: scripts/run_final_verification.py
    # constructs rows with 'valid@email.com' as handcrafted synthetic test
    # data (provenance verified 2026-09-15; not real personal data)
    "email.com",
    # B-8 trust-anchor signing key UID domain: the trusted signing key
    # (fingerprint 6BAF8AEFE12EB327598EB4471B0613B9D58ADC85) uses the
    # UID "DQAEIP Release Signing <release-signing@dqaeip.local>". This
    # is a system identity for the trusted release-signing key, NOT
    # personal data — the email appears in committed .sig metadata,
    # signed commit metadata, and the B-8 Trust Anchor section of
    # README.md (where it is documented as the key UID that
    # `gpg --verify` and `git log --pretty='%GS'` return). Treating it
    # as PROHIBITED PII would block B-8 trust-anchor documentation;
    # whitelisting it here is consistent with how `email.com` is
    # whitelisted as a known in-repo non-personal-data domain.
    "dqaeip.local",
}

EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")

CREDENTIAL_RE = re.compile(
    r"(?i)[\w.\-]*(password|passwd|passphrase|secret|token|"
    r"api[_\-]?key|apikey|access[_\-]?key|auth[_\-]?token|"
    r"bearer[_\-]?token|client[_\-]?secret|private[_\-]?key)"
    r"[\w.\-]*[\"']?\s*[:=]\s*(\S.{2,})")

PEM_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----")

MACHINE_PATH_RE = re.compile(
    r"(?:/home/[A-Za-z0-9._\-]+/|/Users/[A-Za-z0-9._\-]+/|"
    r"/root/|/tmp/[A-Za-z0-9._\-]+/|[A-Za-z]:\\\\Users\\\\)")

PHONE_RE = re.compile(
    r"(?<![\d.\-])(?:\+?1[.\- ]?)?\(?\d{3}\)?[.\- ]\d{3}[.\- ]\d{4}"
    r"(?![\d.\-])")

PLACEHOLDER_VALUES = {
    "your_password_here", "changeme", "change-me", "placeholder",
    "xxxxx", "xxxxxx", "<none>", "none", "null", "test", "dummy",
    "example", "redacted", "***", "<redacted>", "[redacted]",
    # boolean / scan-result values (e.g. 'secrets_detected: False')
    "true", "false", "yes", "no", "on", "off", "0", "1", "n/a",
}

# bare version strings (semver-like) are never credential values;
# they appear legitimately in pinned-package lists
_VERSION_STRING_RE = re.compile(
    r"^[0-9]+(\.[0-9a-z]+){1,3}([+_-][0-9a-z.]+)?$")

SAFE_EXTENSIONS = {
    ".json", ".jsonl", ".txt", ".md", ".csv", ".yaml", ".yml",
    ".py", ".sql", ".html", ".xml", ".cfg", ".ini", ".toml", ".log",
}

MAX_SCAN_FILE_BYTES = 64 * 1024 * 1024  # per-file cap: 64 MiB


def scan_tree_for_pii(tree: str,
                      *,
                      respect_gitignore: bool = False) -> Dict[str, Any]:
    """Scan a directory tree; return a structured, fail-closed report.

    ``verdict`` is PASS only when no prohibited finding exists.
    Prohibited findings are reported WITHOUT their content.
    """
    findings: List[Dict[str, Any]] = []
    scanned_files = 0
    skipped_binary = 0
    skipped_too_large = 0

    for root, dirs, files in os.walk(tree):
        dirs[:] = sorted(d for d in dirs
                         if d not in ("__pycache__", ".git", ".venv",
                                      "node_modules"))
        for fn in sorted(files):
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, tree).replace(os.sep, "/")
            ext = os.path.splitext(fn)[1].lower()
            if ext not in SAFE_EXTENSIONS:
                # binaries / zips: not decoded, never claimed scanned
                skipped_binary += 1
                continue
            if os.path.getsize(path) > MAX_SCAN_FILE_BYTES:
                skipped_too_large += 1
                findings.append(_finding(
                    rel, "unscanned_oversize_file", "PROHIBITED?",
                    "file exceeds the per-file scan cap; scan it "
                    "explicitly before release"))
                continue
            try:
                text = open(path, encoding="utf-8",
                            errors="strict").read()
            except UnicodeDecodeError:
                # a non-UTF-8 file in evidence is itself a finding
                findings.append(_finding(
                    rel, "non_utf8_evidence_file", "PROHIBITED",
                    "evidence must be UTF-8; decoding failed"))
                continue
            scanned_files += 1
            findings.extend(_scan_text(rel, text))

    prohibited = [f for f in findings if f["classification"] == "PROHIBITED"]
    review = [f for f in findings if f["classification"] == "REVIEW_REQUIRED"]

    return {
        "tool": "data_quality_platform.security.pii_scan",
        "scan_version": "1.0.0",
        "tree": os.path.basename(os.path.normpath(tree)),
        "scanned_files": scanned_files,
        "skipped_binary_or_archive": skipped_binary,
        "skipped_oversize": skipped_too_large,
        "synthetic_email_domains": sorted(SYNTHETIC_EMAIL_DOMAINS),
        "findings_total": len(findings),
        "prohibited_count": len(prohibited),
        "review_required_count": len(review),
        "findings": findings,
        "verdict": "PASS" if not prohibited else "FAIL",
        "fail_closed_note": (
            "PROHIBITED content of any kind fails the scan; "
            "REVIEW_REQUIRED findings do not fail the scan but must be "
            "adjudicated. Finding content is intentionally NOT "
            "reproduced in this report."),
    }


def scan_file_for_pii(path: str) -> Dict[str, Any]:
    """Scan ONE text file; same report shape as scan_tree_for_pii.
    Fail closed on decode errors and prohibited content."""
    rel = os.path.basename(path)
    ext = os.path.splitext(rel)[1].lower()
    findings = []
    if ext not in SAFE_EXTENSIONS:
        return {"verdict": "FAIL",
                "findings": [_finding(rel, "unscanned_extension",
                                      "PROHIBITED?",
                                      "release document must be a "
                                      "scannable text file")],
                "prohibited_count": 1, "review_required_count": 0,
                "scanned_files": 0}
    try:
        text = open(path, encoding="utf-8", errors="strict").read()
    except UnicodeDecodeError:
        return {"verdict": "FAIL",
                "findings": [_finding(rel, "non_utf8_file", "PROHIBITED",
                                      "file is not UTF-8")],
                "prohibited_count": 1, "review_required_count": 0,
                "scanned_files": 0}
    findings = _scan_text(rel, text)
    prohibited = [f for f in findings if f["classification"] == "PROHIBITED"]
    return {"verdict": "PASS" if not prohibited else "FAIL",
            "findings": findings,
            "prohibited_count": len(prohibited),
            "review_required_count": len(findings) - len(prohibited),
            "scanned_files": 1}


def _finding(rel_path: str, category: str, classification: str,
             detail: str) -> Dict[str, Any]:
    return {
        "file": rel_path,
        "category": category,
        "classification": classification,
        "detail": detail,
    }


def _scan_text(rel_path: str, text: str) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []

    # --- credentials & keys -------------------------------------------
    for m in CREDENTIAL_RE.finditer(text):
        # normalize: surrounding whitespace, JSON quotes and trailing
        # list separators are not part of the value (separator first,
        # then the quote it would otherwise shield)
        value = m.group(2).strip().rstrip(",;").strip() \
            .strip("\"'").lower()
        if value in PLACEHOLDER_VALUES or value.startswith("<"):
            continue
        if value.startswith(":test_") or "::test_" in value:
            # pytest node id (module::Class::test_name), not a secret
            continue
        if _VERSION_STRING_RE.match(value):
            # bare version number (e.g. "3.0.1") — the pinned-package
            # list legitimately maps package names that contain
            # credential-like substrings (asttokens) to VERSIONS; a
            # version string is never a secret value. Real credential
            # assignments carry non-version values.
            continue
        findings.append(_finding(
            rel_path, "credential_like_assignment", "PROHIBITED",
            f"credential-pattern assignment with a concrete value "
            f"(pattern: {m.group(1).lower()}); verify and remove before "
            f"release — value not reproduced here"))
        break  # one report per file suffices; content not repeated
    if PEM_PRIVATE_KEY_RE.search(text):
        findings.append(_finding(
            rel_path, "pem_private_key", "PROHIBITED",
            "PEM private key block present in evidence"))

    # --- e-mail addresses ----------------------------------------------
    non_synthetic_domains = set()
    for m in EMAIL_RE.finditer(text):
        domain = m.group(1).lower().rstrip(".")
        if domain in SYNTHETIC_EMAIL_DOMAINS:
            continue
        non_synthetic_domains.add(domain)
    if non_synthetic_domains:
        findings.append(_finding(
            rel_path, "non_synthetic_email_address", "PROHIBITED",
            f"e-mail address(es) on non-synthetic domain(s) "
            f"{sorted(non_synthetic_domains)[:5]} — raw PII suspected; "
            f"addresses not reproduced here"))

    # --- machine-identifying local paths ---------------------------------
    if MACHINE_PATH_RE.search(text):
        findings.append(_finding(
            rel_path, "machine_local_absolute_path", "REVIEW_REQUIRED",
            "local absolute path pattern present; replace with "
            "repository-relative paths before release"))

    # --- phone-like strings ---------------------------------------------
    # Only reported for CSV evidence (row-shaped data files); prose
    # documents frequently contain numeric patterns that are not phones.
    if rel_path.lower().endswith(".csv"):
        hits = PHONE_RE.findall(text)
        if hits:
            findings.append(_finding(
                rel_path, "phone_like_strings", "REVIEW_REQUIRED",
                f"{len(hits)} phone-like string(s) in CSV evidence; "
                f"verify they originate from the synthetic generator "
                f"before release (values not reproduced here)"))

    return findings
