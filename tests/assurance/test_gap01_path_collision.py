"""GAP-01 regression tests: input/output path collision guard.

Tests that the ValidationEngine rejects input/output path collisions
before any destructive file operation, preventing accidental input
destruction.

Coverage:
    TEST 1: same exact input/output path
    TEST 2: relative vs absolute equivalent paths
    TEST 3: normalized equivalent paths (with .. components)
    TEST 4: different input/output paths (accepted)
    TEST 5: existing different output file (accepted)
    TEST 6: direct engine invocation (no CLI)
    TEST 7: input SHA preservation after rejected collision
    TEST 8: symlink alias rejection
"""
import csv
import hashlib
import os
import sys
import tempfile
import shutil

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.validation.engine import ValidationEngine
from data_quality_platform.rules.registry import RuleRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_test_csv(path, rows=10):
    """Write a minimal 33-column test CSV."""
    cols = [
        "id", "email_address", "first_name", "last_name", "address",
        "city", "county_name", "state", "zip", "website_source",
        "phone_number", "gender", "dob", "registration_date",
        "valid", "extra", "email_id", "ethnicity", "ownrent",
        "domain", "main_interest", "sub_interest", "latitude",
        "longitude", "uploaded", "country", "websource_id",
        "interest_ids", "DNC", "source", "first_name_norm",
        "last_name_norm", "zip_norm",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(cols)
        for i in range(1, rows + 1):
            writer.writerow([i] + [""] * 32)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInputOutputPathCollision:
    """GAP-01 regression tests."""

    def test_1_same_exact_path(self, tmp_path):
        """TEST 1: same exact input/output path → rejected."""
        csv_path = str(tmp_path / "data.csv")
        _write_test_csv(csv_path)
        rules = RuleRegistry.create_default()
        engine = ValidationEngine(
            rules=rules,
            run_id="gap01_test1",
            evidence_dir=str(tmp_path / "ev1"),
        )
        with pytest.raises(ValueError, match="must refer to different"):
            engine.validate(csv_path=csv_path, output_path=csv_path)

    def test_2_relative_vs_absolute(self, tmp_path):
        """TEST 2: relative vs absolute equivalent paths → rejected."""
        csv_path = str(tmp_path / "data.csv")
        _write_test_csv(csv_path)
        rules = RuleRegistry.create_default()
        engine = ValidationEngine(
            rules=rules,
            run_id="gap01_test2",
            evidence_dir=str(tmp_path / "ev2"),
        )
        # Change to tmp_path so relative path resolves there
        old_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            with pytest.raises(ValueError, match="must refer to different"):
                engine.validate(
                    csv_path="data.csv",
                    output_path=str(tmp_path / "data.csv"),
                )
        finally:
            os.chdir(old_cwd)

    def test_3_normalized_path(self, tmp_path):
        """TEST 3: path with .. components → rejected."""
        csv_path = str(tmp_path / "data.csv")
        _write_test_csv(csv_path)
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        # ../data.csv from subdir resolves to the same file
        alt_path = str(subdir / ".." / "data.csv")
        rules = RuleRegistry.create_default()
        engine = ValidationEngine(
            rules=rules,
            run_id="gap01_test3",
            evidence_dir=str(tmp_path / "ev3"),
        )
        with pytest.raises(ValueError, match="must refer to different"):
            engine.validate(csv_path=csv_path, output_path=alt_path)

    def test_4_different_paths(self, tmp_path):
        """TEST 4: different input/output paths → accepted."""
        csv_path = str(tmp_path / "input.csv")
        out_path = str(tmp_path / "output.csv")
        _write_test_csv(csv_path)
        rules = RuleRegistry.create_default()
        engine = ValidationEngine(
            rules=rules,
            run_id="gap01_test4",
            evidence_dir=str(tmp_path / "ev4"),
        )
        result = engine.validate(csv_path=csv_path, output_path=out_path)
        assert result.success
        assert os.path.isfile(out_path)

    def test_5_existing_different_output(self, tmp_path):
        """TEST 5: output already exists (different file) → accepted."""
        csv_path = str(tmp_path / "input.csv")
        out_path = str(tmp_path / "output.csv")
        _write_test_csv(csv_path)
        # Pre-create output with different content
        _write_test_csv(out_path, rows=5)
        rules = RuleRegistry.create_default()
        engine = ValidationEngine(
            rules=rules,
            run_id="gap01_test5",
            evidence_dir=str(tmp_path / "ev5"),
        )
        result = engine.validate(csv_path=csv_path, output_path=out_path)
        assert result.success
        # Output should be overwritten with correct content (by design)
        assert os.path.isfile(out_path)

    def test_6_direct_engine_invocation(self, tmp_path):
        """TEST 6: direct engine call without CLI → protected."""
        csv_path = str(tmp_path / "data.csv")
        _write_test_csv(csv_path)
        # Directly instantiate and call engine (no CLI)
        rules = RuleRegistry.create_default()
        engine = ValidationEngine(
            rules=rules,
            run_id="gap01_test6",
            evidence_dir=str(tmp_path / "ev6"),
        )
        with pytest.raises(ValueError, match="must refer to different"):
            engine.validate(csv_path=csv_path, output_path=csv_path)

    def test_7_input_sha_preservation(self, tmp_path):
        """TEST 7: input SHA unchanged after rejected collision."""
        csv_path = str(tmp_path / "data.csv")
        _write_test_csv(csv_path)
        sha_before = _sha256(csv_path)
        rules = RuleRegistry.create_default()
        engine = ValidationEngine(
            rules=rules,
            run_id="gap01_test7",
            evidence_dir=str(tmp_path / "ev7"),
        )
        with pytest.raises(ValueError):
            engine.validate(csv_path=csv_path, output_path=csv_path)
        sha_after = _sha256(csv_path)
        assert sha_before == sha_after, (
            f"Input file was modified! before={sha_before} after={sha_after}"
        )
        assert os.path.isfile(csv_path), "Input file was deleted!"
        # Verify no output was produced (no truncation)
        assert os.path.getsize(csv_path) > 0, "Input file was truncated!"

    def test_8_symlink_alias(self, tmp_path):
        """TEST 8: symlink alias → rejected (if platform supports)."""
        real_path = str(tmp_path / "real.csv")
        alias_path = str(tmp_path / "alias.csv")
        _write_test_csv(real_path)
        try:
            os.symlink(real_path, alias_path)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported on this platform")
        rules = RuleRegistry.create_default()
        engine = ValidationEngine(
            rules=rules,
            run_id="gap01_test8",
            evidence_dir=str(tmp_path / "ev8"),
        )
        # input=real.csv, output=alias.csv (same file via symlink)
        with pytest.raises(ValueError, match="must refer to different"):
            engine.validate(csv_path=real_path, output_path=alias_path)
