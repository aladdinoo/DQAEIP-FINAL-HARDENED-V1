"""Artifact identity contract tests (Phase 4, task section 5)."""

import os
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance.artifact_identity import (  # noqa: E402
    ARTIFACT_CLASSES, make_identity, registry_fingerprint,
    resolve_logical_path, validate_identity)


def test_identity_shape(tmp_path):
    f = tmp_path / "scripts" / "checker.py"
    f.parent.mkdir()
    f.write_text("print('x')\n")
    rec = make_identity("scripts/checker.py", "AUTHORITATIVE",
                        schema_version="1.0", repo_root=str(tmp_path))
    assert rec["logical_path"] == "repo://scripts/checker.py"
    assert rec["relative_path"] == "scripts/checker.py"
    assert len(rec["sha256"]) == 64
    assert rec["artifact_class"] == "AUTHORITATIVE"
    assert rec["schema_version"] == "1.0"
    assert validate_identity(rec, repo_root=str(tmp_path)) == []


def test_class_vocabulary_is_closed(tmp_path):
    f = tmp_path / "a.json"
    f.write_text("{}")
    for cls in ARTIFACT_CLASSES:
        rec = make_identity("a.json", cls, repo_root=str(tmp_path))
        assert rec["artifact_class"] == cls
    with pytest.raises(ValueError):
        make_identity("a.json", "TRUSTED", repo_root=str(tmp_path))


def test_absolute_paths_rejected(tmp_path):
    with pytest.raises(ValueError):
        make_identity("/home/z/repo/scripts/x.py", "DERIVED",
                      repo_root=str(tmp_path))
    with pytest.raises(ValueError):
        make_identity("C:\\repo\\x.py", "DERIVED",
                      repo_root=str(tmp_path))
    with pytest.raises(ValueError):
        make_identity("../outside/x.py", "DERIVED",
                      repo_root=str(tmp_path))


def test_stale_identity_detected(tmp_path):
    f = tmp_path / "a.json"
    f.write_text("{}")
    rec = make_identity("a.json", "DERIVED", repo_root=str(tmp_path))
    f.write_text('{"changed": true}')
    problems = validate_identity(rec, repo_root=str(tmp_path))
    assert any("STALE" in p for p in problems)


def test_missing_artifact_detected(tmp_path):
    rec = {"logical_path": "repo://gone.json",
           "relative_path": "gone.json",
           "sha256": "0" * 64, "artifact_class": "DERIVED",
           "schema_version": "1.0"}
    problems = validate_identity(rec, repo_root=str(tmp_path))
    assert any("missing" in p for p in problems)


def test_unknown_class_not_silently_coerced(tmp_path):
    f = tmp_path / "mystery.bin"
    f.write_bytes(b"\x00\x01")
    rec = make_identity("mystery.bin", "UNKNOWN",
                        repo_root=str(tmp_path))
    # a valid UNKNOWN record stays UNKNOWN
    assert rec["artifact_class"] == "UNKNOWN"
    assert validate_identity(rec, repo_root=str(tmp_path)) == []


def test_logical_path_must_resolve_to_relative(tmp_path):
    rec = {"logical_path": "repo://a.json",
           "relative_path": "b.json",  # mismatch
           "sha256": "0" * 64, "artifact_class": "DERIVED",
           "schema_version": "1.0"}
    problems = validate_identity(rec, repo_root=str(tmp_path))
    assert any("does not resolve" in p for p in problems)


def test_bad_schema_version_rejected(tmp_path):
    f = tmp_path / "a.json"
    f.write_text("{}")
    with pytest.raises(ValueError):
        make_identity("a.json", "DERIVED", schema_version="v2",
                      repo_root=str(tmp_path))


def test_registry_fingerprint_deterministic_and_sensitive(tmp_path):
    a = tmp_path / "a.json"
    a.write_text("{}")
    b = tmp_path / "b.json"
    b.write_text("{}")
    r1 = make_identity("a.json", "DERIVED", repo_root=str(tmp_path))
    r2 = make_identity("b.json", "DERIVED", repo_root=str(tmp_path))
    fp1 = registry_fingerprint([r1, r2])
    fp2 = registry_fingerprint([r2, r1])  # order-insensitive
    assert fp1 == fp2
    a.write_text('{"x":1}')  # content change -> different SHA -> fp
    r1b = make_identity("a.json", "DERIVED", repo_root=str(tmp_path))
    assert registry_fingerprint([r1b, r2]) != fp1


def test_real_repo_frozen_v1_identity():
    """The frozen V1 anchor keeps its official identity in the
    contract model."""
    rec = make_identity(
        "data_quality_platform/rules/v1_rules.py", "AUTHORITATIVE",
        repo_root=REPO_ROOT)
    assert rec["sha256"] == (
        "daef1ded54c7d3c79898a1ba253be2acd5b6120e18b16b09009f"
        "dd7be9fc2276")
    assert resolve_logical_path(rec["logical_path"]) == \
        "data_quality_platform/rules/v1_rules.py"
