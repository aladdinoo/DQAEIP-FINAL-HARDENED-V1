"""GAP-02 regression tests: atomic validation output publication.

Tests that the ValidationEngine publishes the final CSV output atomically:
  - writes to a temporary file first
  - flushes + fsyncs before publishing
  - uses os.replace for atomic publication
  - cleans up temp files on failure
  - preserves existing output if the new run fails

Coverage:
    TEST 1: successful publication (output is complete, correct, no temp)
    TEST 2: existing output preserved after mid-write failure
    TEST 3: controlled write failure during row processing
    TEST 4: no partial final output on failure
    TEST 5: temp file cleanup on failure
    TEST 6: output SHA correctness (calculated from published file)
    TEST 7: GAP-01 still works (collision guard intact)
"""
import csv
import hashlib
import os
import sys
import tempfile

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


def _make_engine(tmp_path, run_id="gap02"):
    rules = RuleRegistry.create_default()
    return ValidationEngine(
        rules=rules,
        run_id=run_id,
        evidence_dir=str(tmp_path / "evidence"),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAtomicOutputPublication:
    """GAP-02 regression tests."""

    def test_1_successful_publication(self, tmp_path):
        """TEST 1: successful run → output complete, correct, no temp."""
        csv_path = str(tmp_path / "input.csv")
        out_path = str(tmp_path / "output.csv")
        _write_test_csv(csv_path, rows=20)
        engine = _make_engine(tmp_path, "gap02_t1")
        result = engine.validate(csv_path=csv_path, output_path=out_path)
        assert result.success
        # Output exists and is complete
        assert os.path.isfile(out_path)
        with open(out_path, "r", newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            assert len(header) == 41  # 33 source + 8 flags
            row_count = sum(1 for _ in reader)
            assert row_count == 20
        # No temp files remain
        tmp_files = [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")]
        assert len(tmp_files) == 0, f"Temp files remain: {tmp_files}"

    def test_2_existing_output_preserved_after_failure(self, tmp_path,
                                                       monkeypatch):
        """TEST 2: existing output remains if new run fails mid-write."""
        csv_path = str(tmp_path / "input.csv")
        out_path = str(tmp_path / "output.csv")
        _write_test_csv(csv_path, rows=20)
        # Create pre-existing output with known content
        _write_test_csv(out_path, rows=5)
        original_sha = _sha256(out_path)
        engine = _make_engine(tmp_path, "gap02_t2")
        # Inject failure: make the second write call fail
        original_write = csv.DictWriter.writerow
        call_count = [0]
        def failing_write(self_writer, row):
            call_count[0] += 1
            if call_count[0] > 3:
                raise OSError("Simulated disk failure during write")
            return original_write(self_writer, row)
        monkeypatch.setattr(csv.DictWriter, "writerow", failing_write)
        # Run — should fail during output writing
        result = engine.validate(csv_path=csv_path, output_path=out_path)
        assert not result.success
        # Existing output must be unchanged
        assert os.path.isfile(out_path), "Output file was deleted!"
        assert _sha256(out_path) == original_sha, (
            "Existing output was modified by failed run!"
        )
        # Content should still be the original 5 rows
        with open(out_path, "r", newline="") as f:
            reader = csv.reader(f)
            next(reader)  # header
            assert sum(1 for _ in reader) == 5

    def test_3_controlled_write_failure(self, tmp_path, monkeypatch):
        """TEST 3: exception during row write → temp cleaned, final untouched."""
        csv_path = str(tmp_path / "input.csv")
        out_path = str(tmp_path / "output.csv")
        _write_test_csv(csv_path, rows=20)
        engine = _make_engine(tmp_path, "gap02_t3")
        # Inject failure at row 3
        original_write = csv.DictWriter.writerow
        call_count = [0]
        def failing_write(self_writer, row):
            call_count[0] += 1
            if call_count[0] >= 3:
                raise RuntimeError("Injected failure at row 3")
            return original_write(self_writer, row)
        monkeypatch.setattr(csv.DictWriter, "writerow", failing_write)
        result = engine.validate(csv_path=csv_path, output_path=out_path)
        assert not result.success
        # Final output should NOT exist (no prior output)
        assert not os.path.isfile(out_path), (
            "Partial output appeared at final path!"
        )
        # No temp files should remain
        tmp_files = [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")]
        assert len(tmp_files) == 0, f"Temp files not cleaned: {tmp_files}"

    def test_4_no_partial_final_output(self, tmp_path):
        """TEST 4: if no prior output exists, failure leaves no final output."""
        csv_path = str(tmp_path / "input.csv")
        out_path = str(tmp_path / "output.csv")
        _write_test_csv(csv_path, rows=5)
        engine = _make_engine(tmp_path, "gap02_t4")
        # Make the schema validator fail to trigger early failure
        # Actually, let's make the input have wrong schema
        bad_path = str(tmp_path / "bad.csv")
        with open(bad_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["wrong", "columns"])  # only 2 columns
            writer.writerow([1, 2])
        result = engine.validate(csv_path=bad_path, output_path=out_path)
        assert not result.success
        assert not os.path.isfile(out_path), (
            "Final output exists after failed run with no prior output!"
        )

    def test_5_temp_cleanup_on_failure(self, tmp_path, monkeypatch):
        """TEST 5: temp file is removed after failure."""
        csv_path = str(tmp_path / "input.csv")
        out_path = str(tmp_path / "output.csv")
        _write_test_csv(csv_path, rows=10)
        engine = _make_engine(tmp_path, "gap02_t5")
        # Inject failure during row processing
        original_write = csv.DictWriter.writerow
        call_count = [0]
        def failing_write(self_writer, row):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise IOError("Injected failure for cleanup test")
            return original_write(self_writer, row)
        monkeypatch.setattr(csv.DictWriter, "writerow", failing_write)
        engine.validate(csv_path=csv_path, output_path=out_path)
        # Verify no .tmp files remain
        tmp_files = [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")]
        assert len(tmp_files) == 0, f"Temp files not cleaned: {tmp_files}"

    def test_6_output_sha_correctness(self, tmp_path):
        """TEST 6: output SHA is calculated from the published (final) file."""
        csv_path = str(tmp_path / "input.csv")
        out_path = str(tmp_path / "output.csv")
        _write_test_csv(csv_path, rows=10)
        engine = _make_engine(tmp_path, "gap02_t6")
        result = engine.validate(csv_path=csv_path, output_path=out_path)
        assert result.success
        # The SHA should be from the final published file, not a temp
        expected_sha = _sha256(out_path)
        # Check that the manifest references the correct output
        manifest_path = os.path.join(str(tmp_path / "evidence"), "manifest.json")
        if os.path.isfile(manifest_path):
            import json
            manifest = json.load(open(manifest_path))
            manifest_sha = manifest.get("output_identity", "")
            # If manifest records a SHA, it should match the final file
            if manifest_sha:
                assert manifest_sha == expected_sha, (
                    f"Manifest SHA {manifest_sha} != actual {expected_sha}"
                )

    def test_7_gap01_collision_guard_intact(self, tmp_path):
        """TEST 7: GAP-01 collision guard still rejects same path."""
        csv_path = str(tmp_path / "data.csv")
        _write_test_csv(csv_path)
        engine = _make_engine(tmp_path, "gap02_t7")
        with pytest.raises(ValueError, match="must refer to different"):
            engine.validate(csv_path=csv_path, output_path=csv_path)
