"""PII / Security Evidence Scan tests (DQAVP Section 22).

Proves the scanner fails closed on prohibited PII (non-synthetic
emails, credentials, private keys) and passes on the synthetic
generator's own domain set — and that findings NEVER reproduce the
prohibited content itself.
"""

import json

import pytest

from data_quality_platform.security.pii_scan import scan_tree_for_pii


def _write(tree, rel, content):
    path = tree / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)
    return path


def test_clean_synthetic_evidence_passes(tmp_path):
    _write(tmp_path, "manifest.json",
           json.dumps({"rows": 10, "run": "r1"}))
    _write(tmp_path, "rows.csv",
           "id,email\n1,alice@example.com\n2,bob@test.org\n")
    report = scan_tree_for_pii(str(tmp_path))
    assert report["verdict"] == "PASS"
    assert report["prohibited_count"] == 0
    assert report["scanned_files"] == 2


def test_all_generator_domains_accepted(tmp_path):
    domains = ["example.com", "test.org", "mail.com", "web.net",
               "company.co", "business.io"]
    _write(tmp_path, "data.csv",
           "id,email\n" + "\n".join(
               f"{i},{i}@{d}" for i, d in enumerate(domains)) + "\n")
    report = scan_tree_for_pii(str(tmp_path))
    assert report["verdict"] == "PASS"


def test_non_synthetic_email_fails(tmp_path):
    _write(tmp_path, "lineage.json",
           json.dumps({"note": "row had email someone@acme-corp.net"}))
    report = scan_tree_for_pii(str(tmp_path))
    assert report["verdict"] == "FAIL"
    (finding,) = report["findings"]
    assert finding["category"] == "non_synthetic_email_address"
    # the PII itself must never be reproduced in the report
    assert "someone@acme-corp.net" not in json.dumps(report)


def test_real_looking_personal_email_fails(tmp_path):
    _write(tmp_path, "audit.json",
           "operator jane.doe@gmail.com executed run")
    report = scan_tree_for_pii(str(tmp_path))
    assert report["verdict"] == "FAIL"
    assert "jane.doe@gmail.com" not in json.dumps(report)


def test_credential_assignment_fails(tmp_path):
    _write(tmp_path, "config_echo.json",
           '{"database_password": "S3cr3t-Value-99"}')
    report = scan_tree_for_pii(str(tmp_path))
    assert report["verdict"] == "FAIL"
    (finding,) = [f for f in report["findings"]
                  if f["classification"] == "PROHIBITED"]
    assert finding["category"] == "credential_like_assignment"
    assert "S3cr3t-Value-99" not in json.dumps(report)


def test_placeholder_credentials_pass(tmp_path):
    _write(tmp_path, "env.txt",
           "# password = <none>\napi_key: changeme\n"
           "secret: REDACTED\n")
    report = scan_tree_for_pii(str(tmp_path))
    assert report["verdict"] == "PASS"


def test_pem_private_key_fails(tmp_path):
    _write(tmp_path, "key.txt",
           "-----BEGIN RSA PRIVATE KEY-----\nMIIB\n"
           "-----END RSA PRIVATE KEY-----\n")
    report = scan_tree_for_pii(str(tmp_path))
    assert report["verdict"] == "FAIL"
    (finding,) = [f for f in report["findings"]
                  if f["classification"] == "PROHIBITED"]
    assert finding["category"] == "pem_private_key"


def test_machine_local_paths_flagged_for_review(tmp_path):
    _write(tmp_path, "README.txt",
           "built at /home/devguy/project and tested by /Users/q/")
    report = scan_tree_for_pii(str(tmp_path))
    assert report["verdict"] == "PASS"  # REVIEW_REQUIRED, not prohibited
    assert report["review_required_count"] >= 1


def test_phone_like_strings_in_csv_flagged_for_review(tmp_path):
    _write(tmp_path, "rows.csv", "id,phone\n1,555-010-9999\n")
    report = scan_tree_for_pii(str(tmp_path))
    assert report["verdict"] == "PASS"
    assert any(f["category"] == "phone_like_strings"
               for f in report["findings"])


def test_binary_files_not_decoded_but_counted(tmp_path):
    _write(tmp_path, "blob.bin", b"\x00\x01\x02\xff")
    _write(tmp_path, "ok.json", '{"fine": true}')
    report = scan_tree_for_pii(str(tmp_path))
    assert report["verdict"] == "PASS"
    assert report["skipped_binary_or_archive"] == 1
    assert report["scanned_files"] == 1


def test_non_utf8_evidence_file_fails(tmp_path):
    _write(tmp_path, "broken.txt", b"\xff\xfe invalid utf8")
    report = scan_tree_for_pii(str(tmp_path))
    assert report["verdict"] == "FAIL"


def test_real_repo_evidence_scenarios_categorized(tmp_path):
    """Combined scenario: synthetic CSV + credential JSON + gmail note."""
    _write(tmp_path, "a/rows.csv",
           "id,email\n1,gen@example.com\n")
    _write(tmp_path, "a/creds.json",
           '{"token": "eyJhbGciOiJIUzI1NiJ9.payload.sig"}')
    _write(tmp_path, "a/notes.md", "contact: ops@yahoo.com")
    report = scan_tree_for_pii(str(tmp_path))
    assert report["verdict"] == "FAIL"
    assert report["prohibited_count"] >= 2
    assert "ops@yahoo.com" not in json.dumps(report)
    assert "eyJhbGciOiJIUzI1NiJ9" not in json.dumps(report)
