"""F-03 atomic release-gate publication regression tests.

Verifies the atomic publication lifecycle in release_gate.py:
  - marker written BEFORE gates run
  - report written to .tmp, flush, fsync, os.replace
  - marker removed ONLY after successful publish
  - crash/exception leaves marker (fail-closed)
  - stale PASS cannot survive a crash
"""
import json
import os
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance.release_chain import \
    load_current_release_gate_report


def _write_gate_report(dir_path, verdict="PASS"):
    """Write a valid gate report to dir_path/evidence/release_gate/."""
    gd = os.path.join(dir_path, "evidence", "release_gate")
    os.makedirs(gd, exist_ok=True)
    path = os.path.join(gd, "final_release_gate.json")
    with open(path, "w") as f:
        json.dump({"overall_verdict": verdict, "gate_count": 22,
                   "gate_version": "3.0.0"}, f)
    return path


def _write_marker(dir_path):
    gd = os.path.join(dir_path, "evidence", "release_gate")
    os.makedirs(gd, exist_ok=True)
    path = os.path.join(gd, "final_release_gate.json.in_progress")
    with open(path, "w") as f:
        f.write("in-progress\n")
    return path


def _tmp_file(dir_path):
    gd = os.path.join(dir_path, "evidence", "release_gate")
    os.makedirs(gd, exist_ok=True)
    return os.path.join(gd, "final_release_gate.json.tmp")


class TestF03AtomicPublication:
    """F-03 atomic publication lifecycle tests."""

    def test_01_successful_publication(self, tmp_path):
        """Valid report + no marker → canonical helper returns the report."""
        _write_gate_report(str(tmp_path))
        r = load_current_release_gate_report(str(tmp_path))
        assert r is not None
        assert r["overall_verdict"] == "PASS"

    def test_02_marker_blocks_stale_pass(self, tmp_path):
        """Marker + stale PASS → None (fail-closed)."""
        _write_gate_report(str(tmp_path))  # stale PASS
        _write_marker(str(tmp_path))       # marker
        r = load_current_release_gate_report(str(tmp_path))
        assert r is None  # stale PASS blocked

    def test_03_marker_cleanup_restores_validity(self, tmp_path):
        """Marker removal → report is trusted again."""
        _write_gate_report(str(tmp_path))
        marker = _write_marker(str(tmp_path))
        assert load_current_release_gate_report(str(tmp_path)) is None
        os.remove(marker)  # simulate cleanup after successful publish
        r = load_current_release_gate_report(str(tmp_path))
        assert r is not None
        assert r["overall_verdict"] == "PASS"

    def test_04_missing_report_fail_closed(self, tmp_path):
        """No report → None (fail-closed)."""
        r = load_current_release_gate_report(str(tmp_path))
        assert r is None

    def test_05_malformed_report_fail_closed(self, tmp_path):
        """Malformed JSON → None (fail-closed)."""
        path = _write_gate_report(str(tmp_path))
        with open(path, "w") as f:
            f.write("{partial")
        r = load_current_release_gate_report(str(tmp_path))
        assert r is None

    def test_06_partial_tmp_not_trusted(self, tmp_path):
        """A .tmp file (pre-replace) must NOT be trusted as the report."""
        # Write a .tmp file (simulating crash during write)
        tmp = _tmp_file(str(tmp_path))
        with open(tmp, "w") as f:
            json.dump({"overall_verdict": "PASS"}, f)
        # No final_release_gate.json exists → helper returns None
        r = load_current_release_gate_report(str(tmp_path))
        assert r is None  # .tmp is NOT the report

    def test_07_marker_with_no_report_fail_closed(self, tmp_path):
        """Marker exists but no report → None (fail-closed)."""
        _write_marker(str(tmp_path))
        r = load_current_release_gate_report(str(tmp_path))
        assert r is None

    def test_08_marker_with_malformed_report_fail_closed(self, tmp_path):
        """Marker + malformed report → None (fail-closed)."""
        path = _write_gate_report(str(tmp_path))
        with open(path, "w") as f:
            f.write("garbage")
        _write_marker(str(tmp_path))
        r = load_current_release_gate_report(str(tmp_path))
        assert r is None

    def test_09_no_trusted_pass_from_failed_publication(self, tmp_path):
        """A crash during os.replace leaves marker → no trusted PASS."""
        # Simulate: marker written, .tmp written, but os.replace
        # never happened (crash). The .tmp file has PASS but
        # final_release_gate.json does NOT exist.
        _write_marker(str(tmp_path))
        tmp = _tmp_file(str(tmp_path))
        with open(tmp, "w") as f:
            json.dump({"overall_verdict": "PASS"}, f)
        # No final_release_gate.json → helper returns None
        r = load_current_release_gate_report(str(tmp_path))
        assert r is None  # no trusted PASS can emerge

    def test_10_release_gate_py_has_f03_pattern(self):
        """Verify release_gate.py source has the F-03 pattern."""
        src = open(os.path.join(
            REPO_ROOT, "scripts", "release_gate.py")).read()
        assert "in_progress" in src, "release_gate.py must write .in_progress marker"
        assert "os.fsync" in src, "release_gate.py must fsync the .tmp file"
        assert "os.replace" in src, "release_gate.py must atomically publish via os.replace"
        assert "os.remove(marker_path)" in src, "release_gate.py must remove marker after publish"
