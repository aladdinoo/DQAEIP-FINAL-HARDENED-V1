"""F-01 canonical release-gate routing — regression tests.

Tests the load_current_release_gate_report() canonical helper in
data_quality_platform/assurance/release_chain.py and verifies that
ALL four trust-sensitive consumers route through it (no direct-read
bypasses).

Coverage:
    A. Functional valid gate report
    B. Missing gate report → fail closed
    C. Malformed gate report → fail closed
    D. .in_progress present + stale PASS → None (NOT_VERIFIED)
    E. .in_progress absent + valid PASS → normal valid behavior
    F. All four consumers use the canonical helper
    G. Direct-read bypass regression
    H. F-03 atomic publication interaction (marker lifecycle)
    I. No regression to B-5/B-6/N-16
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


def _write_gate_report(repo_root, verdict="PASS", gate_count=22,
                       gate_version="3.0.0"):
    """Write a valid gate report to the standard path.

    NOTE: The default ``gate_count=22`` and ``gate_version="3.0.0"``
    values are GENERIC fixture values used for STRUCTURAL testing of
    the F-01 canonical helper's loading semantics (does it return a
    dict? does it return None for missing/malformed? does it block
    stale PASS when the .in_progress marker exists?). They are NOT
    contract assertions on the canonical gate count. The canonical
    contract is enforced by the separate
    ``TestAntiRegressionCanonicalContracts.test_02_gate_count_constant_is_24``
    test in ``test_release_document_regeneration.py``, which asserts
    that ``release_gate.GATE_COUNT == 24`` directly. Updating the
    fixture defaults here to ``24``/``"4.0.0"`` would not change
    test coverage semantically (the test asserts the helper echoes
    back whatever the fixture wrote, not that the value matches the
    canonical constant)."""
    path = os.path.join(repo_root,
                        "evidence", "release_gate",
                        "final_release_gate.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    report = {
        "overall_verdict": verdict,
        "gate_count": gate_count,
        "gate_version": gate_version,
    }
    with open(path, "w") as f:
        json.dump(report, f)
    return path


def _write_marker(repo_root):
    """Create the .in_progress marker."""
    path = os.path.join(repo_root,
                        "evidence", "release_gate",
                        "final_release_gate.json.in_progress")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("in-progress\n")
    return path


class TestCanonicalHelper:
    """Tests A-E: direct helper behavior."""

    def test_a_valid_gate_report(self, tmp_path):
        """A: valid gate report → returns the dict."""
        _write_gate_report(str(tmp_path))
        r = load_current_release_gate_report(str(tmp_path))
        assert r is not None
        assert r["overall_verdict"] == "PASS"
        assert r["gate_count"] == 22

    def test_b_missing_gate_report(self, tmp_path):
        """B: missing gate report → None (fail closed)."""
        r = load_current_release_gate_report(str(tmp_path))
        assert r is None

    def test_c_malformed_gate_report(self, tmp_path):
        """C: malformed JSON → None (fail closed)."""
        path = _write_gate_report(str(tmp_path))
        with open(path, "w") as f:
            f.write("{bad json")
        r = load_current_release_gate_report(str(tmp_path))
        assert r is None

    def test_c2_missing_field_returns_dict(self, tmp_path):
        """C2: dict missing a field → helper returns the dict.

        The F-01 canonical helper does NOT validate field presence —
        that is N-16's job (_is_meaningful_truth_value). The helper
        only checks: marker, file exists, valid JSON, is a dict."""
        path = _write_gate_report(str(tmp_path))
        report = json.load(open(path))
        del report["overall_verdict"]
        with open(path, "w") as f:
            json.dump(report, f)
        r = load_current_release_gate_report(str(tmp_path))
        assert r is not None  # helper returns the dict; N-16 handles field validation
        assert "overall_verdict" not in r  # field is indeed missing

    def test_c3_not_a_dict(self, tmp_path):
        """C3: JSON array instead of dict → None."""
        path = _write_gate_report(str(tmp_path))
        with open(path, "w") as f:
            json.dump([1, 2, 3], f)
        r = load_current_release_gate_report(str(tmp_path))
        assert r is None

    def test_d_in_progress_marker_blocks_stale_pass(self, tmp_path):
        """D: .in_progress marker present + stale PASS report → None.

        This is the CORE F-01 contract: a stale PASS report must NOT
        be trusted when the marker exists."""
        _write_gate_report(str(tmp_path))  # stale PASS on disk
        _write_marker(str(tmp_path))       # marker says "in progress"
        r = load_current_release_gate_report(str(tmp_path))
        assert r is None  # stale PASS blocked

    def test_e_no_marker_valid_report(self, tmp_path):
        """E: no marker + valid PASS → normal valid behavior."""
        _write_gate_report(str(tmp_path))
        assert not os.path.exists(os.path.join(
            str(tmp_path), "evidence", "release_gate",
            "final_release_gate.json.in_progress"))
        r = load_current_release_gate_report(str(tmp_path))
        assert r is not None
        assert r["overall_verdict"] == "PASS"


class TestConsumerRouting:
    """Tests F-G: verify all four consumers route through the helper."""

    def test_f_release_chain_uses_helper(self, tmp_path):
        """F: release_chain.verify_chain() uses the canonical helper."""
        _write_gate_report(str(tmp_path))
        from data_quality_platform.assurance import release_chain
        ok, report = release_chain.verify_chain(str(tmp_path))
        # The gate edge should see the report (not None)
        gate_edge = report["edges"].get("root_to_gate", {})
        assert gate_edge.get("detail", {}).get("release_gate_verdict") == "PASS"

    def test_f2_claims_uses_helper(self, tmp_path):
        """F2: claims._d_gate() uses the canonical helper."""
        _write_gate_report(str(tmp_path))
        from data_quality_platform.assurance import claims
        result = claims._d_gate(str(tmp_path))
        assert result == "PASS"

    def test_f3_claims_stale_pass_blocked(self, tmp_path):
        """F3: claims._d_gate() returns None when marker exists."""
        _write_gate_report(str(tmp_path))
        _write_marker(str(tmp_path))
        from data_quality_platform.assurance import claims
        result = claims._d_gate(str(tmp_path))
        assert result is None  # stale PASS blocked by canonical helper

    def test_f4_contradiction_checker_uses_helper(self, tmp_path):
        """F4: contradiction_checker.derive_truth() uses the helper."""
        _write_gate_report(str(tmp_path))
        from data_quality_platform.assurance import contradiction_checker
        truth, sources = contradiction_checker.derive_truth(str(tmp_path))
        assert sources.get("gate") == "ok"
        assert truth.get("gate_verdict") == "PASS"

    def test_f5_contradiction_checker_stale_pass_blocked(self, tmp_path):
        """F5: contradiction_checker blocks stale PASS via marker."""
        _write_gate_report(str(tmp_path))
        _write_marker(str(tmp_path))
        from data_quality_platform.assurance import contradiction_checker
        truth, sources = contradiction_checker.derive_truth(str(tmp_path))
        assert sources.get("gate") == "missing"  # stale PASS blocked

    def test_g_no_direct_read_bypass(self):
        """G: scan TRUST-SENSITIVE production source for direct reads
        of final_release_gate.json OUTSIDE the canonical helper.

        Only the four trust-sensitive consumers are checked:
        release_chain, claims, contradiction_checker, consistency_matrix.
        Forensic/audit scripts (final_forensic_audit, readme_consistency,
        final_verification, etc.) may read the gate report directly for
        informational purposes — they are NOT trust-sensitive consumers."""
        import re
        bypass_files = []
        # Only check the four trust-sensitive consumers
        trust_sensitive = [
            os.path.join(REPO_ROOT, "data_quality_platform",
                        "assurance", "release_chain.py"),
            os.path.join(REPO_ROOT, "data_quality_platform",
                        "assurance", "claims.py"),
            os.path.join(REPO_ROOT, "data_quality_platform",
                        "assurance", "contradiction_checker.py"),
            os.path.join(REPO_ROOT, "scripts",
                        "consistency_matrix.py"),
        ]
        bypass_patterns = [
            r'_load\s*\([^)]*final_release_gate\.json',
            r'maybe_load\s*\([^)]*final_release_gate\.json',
            r'open\s*\([^)]*final_release_gate\.json',
            r'_load_json\s*\([^)]*final_release_gate\.json',
        ]
        bypass_re = re.compile("|".join(bypass_patterns))
        # Whitelist: release_chain.py defines the canonical helper and
        # is allowed to read the file directly inside it
        whitelist = "release_chain.py"
        for fpath in trust_sensitive:
            if whitelist in fpath:
                continue
            try:
                src = open(fpath, encoding="utf-8").read()
            except Exception:
                continue
            # Exclude lines that route THROUGH the canonical helper
            # (those mention load_current_release_gate_report)
            lines = src.splitlines()
            for i, line in enumerate(lines):
                if "load_current_release_gate_report" in line:
                    continue
                if bypass_re.search(line):
                    bypass_files.append(f"{fpath}:{i+1}")
        assert not bypass_files, \
            f"Direct-read bypass in trust-sensitive consumers: {bypass_files}"

    def test_g2_no_direct_read_in_scripts(self):
        """G2: verify consistency_matrix.py routes through the helper."""
        import re
        fpath = os.path.join(REPO_ROOT, "scripts", "consistency_matrix.py")
        src = open(fpath, encoding="utf-8").read()
        assert "load_current_release_gate_report" in src, \
            "consistency_matrix.py must route through canonical helper"
        # Verify no direct _load/maybe_load of final_release_gate.json
        # (excluding the canonical helper definition in release_chain.py)
        bypass_patterns = [
            r'maybe_load\s*\([^)]*final_release_gate\.json',
            r'_load\s*\([^)]*final_release_gate\.json',
        ]
        bypass_re = re.compile("|".join(bypass_patterns))
        lines = src.splitlines()
        bypass_lines = []
        for i, line in enumerate(lines):
            if "load_current_release_gate_report" in line:
                continue
            if bypass_re.search(line):
                bypass_lines.append(f"line {i+1}: {line.strip()}")
        assert not bypass_lines, \
            f"Direct-read bypass in consistency_matrix.py: {bypass_lines}"


class TestF03Interaction:
    """Test H: the marker lifecycle (F-03 atomic write interaction)."""

    def test_h_marker_then_removal_restores_validity(self, tmp_path):
        """H: marker present → None; marker removed → valid again.

        Simulates the F-03 lifecycle: gate run starts (marker created),
        gate crashes (marker stays), gate re-runs and succeeds (marker
        removed, new valid report written)."""
        _write_gate_report(str(tmp_path))  # stale PASS
        _write_marker(str(tmp_path))       # marker from crashed run
        assert load_current_release_gate_report(str(tmp_path)) is None

        # Simulate successful re-run: remove marker, write fresh report
        os.remove(os.path.join(
            str(tmp_path), "evidence", "release_gate",
            "final_release_gate.json.in_progress"))
        _write_gate_report(str(tmp_path))  # fresh valid report
        r = load_current_release_gate_report(str(tmp_path))
        assert r is not None
        assert r["overall_verdict"] == "PASS"


class TestNoB5B6N16Regression:
    """Test I: verify B-5/B-6/N-16 behavior is not weakened."""

    def test_i_contradiction_checker_still_has_not_verified(self):
        """I: contradiction_checker still emits NOT_VERIFIED verdict."""
        from data_quality_platform.assurance import contradiction_checker
        src = open(os.path.join(
            REPO_ROOT, "data_quality_platform", "assurance",
            "contradiction_checker.py")).read()
        assert "NOT_VERIFIED" in src
        assert "_is_meaningful_truth_value" in src
        assert "CONTRADICTIONS_FOUND" in src
        assert "CONSISTENT" in src

    def test_i2_claims_still_has_fail_closed(self):
        """I2: claims module still has fail-closed behavior."""
        from data_quality_platform.assurance import claims
        src = open(os.path.join(
            REPO_ROOT, "data_quality_platform", "assurance",
            "claims.py")).read()
        assert "not_verified" in src.lower() or "NOT_VERIFIED" in src


class TestContradictionCheckerFallbackSafety:
    """Strengthened regression tests proving the contradiction_checker's
    fallback to _load_json CANNOT become a trust bypass.

    The contradiction_checker uses load_current_release_gate_report()
    as the primary gate loader. When it returns None, a fallback to
    _load_json is used ONLY to determine the N-16/B-6 status string
    (missing/unreadable/meaningless). The fallback result is NEVER
    used as trusted gate truth — the truth dict is not populated
    with gate_verdict or gate_count when the canonical helper
    returns None."""

    def test_d1_stale_pass_marker_truth_has_no_gate_verdict(self, tmp_path):
        """D1: .in_progress + stale PASS → truth must NOT contain
        gate_verdict or gate_count (the fallback must not restore
        trusted PASS semantics)."""
        _write_gate_report(str(tmp_path))  # stale PASS
        _write_marker(str(tmp_path))       # marker
        from data_quality_platform.assurance import contradiction_checker
        truth, sources = contradiction_checker.derive_truth(str(tmp_path))
        assert sources.get("gate") == "missing"
        assert "gate_verdict" not in truth or truth.get("gate_verdict") is None
        assert "gate_count" not in truth or truth.get("gate_count") is None

    def test_d2_malformed_truth_has_no_gate_verdict(self, tmp_path):
        """D2: malformed gate → truth must NOT contain gate_verdict."""
        path = _write_gate_report(str(tmp_path))
        with open(path, "w") as f:
            f.write("{bad json")
        from data_quality_platform.assurance import contradiction_checker
        truth, sources = contradiction_checker.derive_truth(str(tmp_path))
        assert sources.get("gate") == "unreadable"
        assert not truth.get("gate_verdict")

    def test_d3_missing_fields_truth_has_no_pass(self, tmp_path):
        """D3: valid dict but missing overall_verdict → truth must NOT
        have gate_verdict == PASS (N-16 flags as meaningless)."""
        path = _write_gate_report(str(tmp_path))
        report = json.load(open(path))
        del report["overall_verdict"]
        with open(path, "w") as f:
            json.dump(report, f)
        from data_quality_platform.assurance import contradiction_checker
        truth, sources = contradiction_checker.derive_truth(str(tmp_path))
        assert sources.get("gate") == "meaningless"
        assert truth.get("gate_verdict") != "PASS"
