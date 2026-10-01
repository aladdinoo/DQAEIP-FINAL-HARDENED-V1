"""Phase 13H.16/17 — Self-referential gate claim sentinel tests.

These tests verify the SELF_REFERENTIAL_PENDING sentinel implemented
in data_quality_platform/assurance/claims.py::verify_claims().

The sentinel:
  - Returns ok=True, verified=False, state="SELF_REFERENTIAL_PENDING"
  - ONLY for the release_gate_verdict derivation
  - ONLY when the .in_progress marker exists
  - Does NOT bypass F-01 (helper still returns None during marker)
  - Does NOT make unrelated claims pass
  - Does NOT mark the claim as verified PASS

Critical invariant: "marker existence alone MUST NEVER make an
unrelated claim pass."

These 10 tests are the conversion of the Phase 13H.16 forensic tests
into a proper pytest file in tests/assurance/.
"""
import json
import os
import sys
import tempfile
import shutil

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance import claims as claims_mod
from data_quality_platform.assurance import release_chain
from data_quality_platform.assurance import contradiction_checker


# ---------------------------------------------------------------------------
# Constants (must match production in release_chain.py and claims.py)
# ---------------------------------------------------------------------------

GATE_REPORT_REL = "evidence/release_gate/final_release_gate.json"
GATE_MARKER_REL = "evidence/release_gate/final_release_gate.json.in_progress"
FINAL_RESULTS_REL = "FINAL_RESULTS.json"
EV_3M_REL = "evidence/validation/2026-09-19/fresh_3m2/FINAL_RESULTS.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(repo_root, rel, content):
    p = os.path.join(repo_root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        if isinstance(content, (dict, list)):
            json.dump(content, f, indent=2)
        else:
            f.write(content)
    return p


def _remove(repo_root, rel):
    p = os.path.join(repo_root, rel)
    if os.path.exists(p):
        os.remove(p)


def _write_marker(repo_root):
    return _write(repo_root, GATE_MARKER_REL, "in-progress\n")


def _remove_marker(repo_root):
    _remove(repo_root, GATE_MARKER_REL)


def _write_gate_report(repo_root, verdict="PASS", gate_count=24,
                       gate_version="4.0.0"):
    return _write(repo_root, GATE_REPORT_REL, {
        "release_gate": "dqavp-unified-release-gate",
        "gate_version": gate_version,
        "gate_count": gate_count,
        "gates": [],
        "overall_verdict": verdict,
        "gate_counts": {"pass": gate_count, "fail": 0},
    })


def _make_claim(name, derivation, value, verified=True,
                status="VERIFIED_LOCALLY", source_artifact=GATE_REPORT_REL):
    return {
        "claim_id": f"CLAIM-{derivation}-abc123",
        "claim": name,
        "value": value,
        "source_artifact": source_artifact,
        "derivation": derivation,
        "verified": verified,
        "status": status,
    }


def _make_not_verified_claim(name, derivation, reason="pending"):
    return {
        "claim_id": f"CLAIM-{derivation}-abc123",
        "claim": name,
        "value": None,
        "source_artifact": None,
        "derivation": None,
        "verified": False,
        "status": "NOT_VERIFIED",
        "reason": reason,
    }


def _write_final_results(repo_root, claims_list):
    claimed_gate = None
    for c in claims_list:
        if c.get("derivation") == "release_gate_verdict":
            claimed_gate = c.get("value")
            break
    return _write(repo_root, FINAL_RESULTS_REL, {
        "schema": "dqaeip.final_results",
        "release_name": "DQAEIP-Enterprise-Assurance-Validation-Release",
        "release_date": "2026-09-19",
        "verification": {"release_gate_verdict": claimed_gate},
        "claims": claims_list,
    })


def _bootstrap_minimal_repo(tmp_root):
    """Set up minimal repo skeleton for verify_chain + claim_provenance
    testing."""
    _write(tmp_root, EV_3M_REL, {
        "input_sha256": "a"*64,
        "output_sha256": "b"*64,
        "rows": 3200000,
        "final_status": "PASS",
        "comparison_count": {"run_1": 25600000, "run_2": 25600000,
                              "combined_total": 51200000},
        "oracle_mismatches": {"run_1": 0, "run_2": 0,
                              "combined_total": 0},
        "runs": {"run_1": {"dataset": {"sha256": "a"*64},
                           "output": {"sha256": "b"*64},
                           "oracle": {"comparisons": 25600000,
                                       "mismatches": 0}},
                 "run_2": {"dataset": {"sha256": "a"*64},
                           "output": {"sha256": "b"*64},
                           "oracle": {"comparisons": 25600000,
                                       "mismatches": 0}}},
        "determinism_detail": {"byte_identical_output": True,
                               "input_hash_equal": True,
                               "output_hash_equal": True},
    })
    ev_dir = EV_3M_REL.replace("FINAL_RESULTS.json", "")
    for pdir in ("pass1_engine", "pass2_engine"):
        _write(tmp_root, f"{ev_dir}{pdir}/manifest.json", {
            "rule_hashes": {},
            "schema_hash": "c"*64,
        })
        for fname in ("lineage.json", "audit.json",
                      "monitoring.json", "alerts.json"):
            _write(tmp_root, f"{ev_dir}{pdir}/{fname}", {})
    _write(tmp_root, "data_quality_platform/rules/v1_rules.py", "# stub\n")
    _write(tmp_root, "scripts/final_3m_validation.py", "# stub\n")
    _write(tmp_root, "release_manifest.json", {
        "release_name": "DQAEIP-Enterprise-Assurance-Validation-Release",
        "release_date": "2026-09-19",
    })
    _write(tmp_root, "README.md", "stub\n")
    _write(tmp_root, "RELEASE_NOTES.md", "stub\n")


def _run_real_verify_claims(repo_root):
    """Run the REAL production verify_claims against the FINAL_RESULTS
    on disk in repo_root. Returns the report dict."""
    fr_path = os.path.join(repo_root, "FINAL_RESULTS.json")
    with open(fr_path, encoding="utf-8") as f:
        fr = json.load(f)
    return claims_mod.verify_claims(fr.get("claims", []), repo_root)


# ---------------------------------------------------------------------------
# Test 1: release_gate_verdict + marker → PENDING
# ---------------------------------------------------------------------------

class TestSelfReferentialPendingSentinel:
    """Tests 1, 2, 5, 6, 7: sentinel behavior for the
    release_gate_verdict claim."""

    def test_1_release_gate_verdict_marker_present_returns_pending(
            self, tmp_path):
        """Test 1: release_gate_verdict + marker → PENDING.

        The sentinel returns ok=True, verified=False,
        state=SELF_REFERENTIAL_PENDING.
        """
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")  # stale
        _write_marker(str(tmp_path))
        claims = [
            _make_claim("release gate verdict (21 gates)",
                        "release_gate_verdict", "PASS"),
        ]
        _write_final_results(str(tmp_path), claims)
        report = _run_real_verify_claims(str(tmp_path))
        assert report["recheck_passed"] is True, (
            "gate 20 must PASS — sentinel returns ok=True for "
            "self-referential claim during marker")
        rgv = report["results"][0]
        assert rgv["ok"] is True
        assert rgv["verified"] is False, (
            "verified MUST be False — PENDING is not PASS")
        assert rgv["detail"].get("state") == "SELF_REFERENTIAL_PENDING"
        assert "PENDING" in rgv["detail"]["reason"]

    def test_2_release_gate_verdict_no_marker_normal_verification(
            self, tmp_path):
        """Test 2: release_gate_verdict + no marker → normal F-01
        verification.

        Without marker, verify_claim() re-derives via _d_gate → F-01
        helper. If gate=PASS and claimed=PASS, match → verified=True.
        """
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")
        # NO marker
        claims = [
            _make_claim("release gate verdict (21 gates)",
                        "release_gate_verdict", "PASS"),
        ]
        _write_final_results(str(tmp_path), claims)
        report = _run_real_verify_claims(str(tmp_path))
        rgv = report["results"][0]
        assert rgv["ok"] is True
        assert rgv["verified"] is True, (
            "Without marker, gate=PASS, claimed=PASS → verified=True")
        assert rgv["detail"].get("state") != "SELF_REFERENTIAL_PENDING"

    def test_5_malformed_release_gate_verdict_marker_does_not_become_pass(
            self, tmp_path):
        """Test 5: malformed release_gate_verdict + marker → must NOT
        become PASS. The sentinel handles the malformed case BEFORE
        the sentinel check (malformed = not a dict)."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_marker(str(tmp_path))
        # Call verify_claims directly with a malformed list
        report = claims_mod.verify_claims(
            ["not_a_dict"], str(tmp_path))
        assert report["recheck_passed"] is False
        assert report["results"][0]["ok"] is False
        assert "claim not an object" in report["results"][0]["detail"]["reason"]

    def test_6_corrupted_gate_evidence_marker_pending_only_for_self_ref(
            self, tmp_path):
        """Test 6: corrupted gate evidence + marker → PENDING only for
        self-reference. F-01 helper returns None; sentinel returns
        PENDING. The corrupted evidence is NOT trusted as PASS."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write(str(tmp_path), GATE_REPORT_REL, "{bad json")
        _write_marker(str(tmp_path))
        claims = [
            _make_claim("release gate verdict (21 gates)",
                        "release_gate_verdict", "PASS"),
        ]
        _write_final_results(str(tmp_path), claims)
        report = _run_real_verify_claims(str(tmp_path))
        rgv = report["results"][0]
        assert rgv["ok"] is True
        assert rgv["verified"] is False
        assert rgv["detail"].get("state") == "SELF_REFERENTIAL_PENDING"
        # Also verify F-01 helper returns None
        helper = release_chain.load_current_release_gate_report(str(tmp_path))
        assert helper is None, (
            "F-01 helper MUST return None for corrupted + marker")

    def test_7_stale_marker_self_ref_pending_unrelated_claims_fail(
            self, tmp_path):
        """Test 7: stale marker → self-reference PENDING, unrelated
        claims fail normally if their values are wrong."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_marker(str(tmp_path))  # stale marker from crash
        # Unrelated claim with WRONG value (source says 3200000)
        claims = [
            _make_claim("final 3M rows", "final_3m_rows", 9999,
                        source_artifact=EV_3M_REL),
            _make_claim("release gate verdict (21 gates)",
                        "release_gate_verdict", "PASS"),
        ]
        _write_final_results(str(tmp_path), claims)
        report = _run_real_verify_claims(str(tmp_path))
        # Unrelated claim must FAIL
        rows_result = next(r for r in report["results"]
                           if "3M rows" in r.get("claim", ""))
        assert rows_result["ok"] is False, (
            "Unrelated claim with wrong value MUST FAIL — sentinel "
            "does NOT help unrelated claims")
        # Self-referential claim must be PENDING
        rgv = next(r for r in report["results"]
                   if "release gate" in r.get("claim", ""))
        assert rgv["ok"] is True
        assert rgv["verified"] is False
        assert rgv["detail"].get("state") == "SELF_REFERENTIAL_PENDING"
        # Overall gate 20 must FAIL (unrelated claim failed)
        assert report["recheck_passed"] is False


# ---------------------------------------------------------------------------
# Test 3, 4, 8: unrelated claims behavior during marker
# ---------------------------------------------------------------------------

class TestUnrelatedClaimsDuringMarker:
    """Tests 3, 4, 8: unrelated claims MUST continue through normal
    F-01 derivation and fail-closed verification during marker."""

    def test_3_unrelated_claim_marker_f01_still_applies(self, tmp_path):
        """Test 3: unrelated claim + marker → F-01 still applies
        (the claim is re-derived normally; the marker doesn't bypass)."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_marker(str(tmp_path))
        # Unrelated claim with CORRECT value (source says 3200000)
        claims = [
            _make_claim("final 3M rows", "final_3m_rows", 3200000,
                        source_artifact=EV_3M_REL),
        ]
        _write_final_results(str(tmp_path), claims)
        report = _run_real_verify_claims(str(tmp_path))
        rows = report["results"][0]
        assert rows["ok"] is True, (
            "Correct unrelated claim MUST pass — marker doesn't bypass "
            "but also doesn't block unrelated derivations")
        assert rows["verified"] is True
        assert rows["detail"].get("state") != "SELF_REFERENTIAL_PENDING"

    def test_4_unrelated_wrong_claim_marker_FAIL(self, tmp_path):
        """Test 4: unrelated wrong claim + marker → FAIL.

        The sentinel does NOT help unrelated claims. Wrong value →
        mismatch → ok=False → gate 20 FAILS.
        """
        _bootstrap_minimal_repo(str(tmp_path))
        _write_marker(str(tmp_path))
        claims = [
            _make_claim("final 3M rows", "final_3m_rows", 9999,
                        source_artifact=EV_3M_REL),  # wrong
        ]
        _write_final_results(str(tmp_path), claims)
        report = _run_real_verify_claims(str(tmp_path))
        rows = report["results"][0]
        assert rows["ok"] is False, (
            "Wrong unrelated claim MUST FAIL even with marker")
        assert "does not match" in rows["detail"]["reason"]
        assert report["recheck_passed"] is False

    def test_8_attacker_modified_unrelated_FINAL_RESULTS_FAIL(self, tmp_path):
        """Test 8: attacker-modified unrelated FINAL_RESULTS → FAIL.

        Attacker modifies an unrelated claim to a wrong value while
        marker exists. The sentinel does NOT help — the unrelated
        claim still fails re-derivation.
        """
        _bootstrap_minimal_repo(str(tmp_path))
        _write_marker(str(tmp_path))
        # Attacker modifies final_3m_rows to wrong value
        claims = [
            _make_claim("final 3M rows", "final_3m_rows", 9999,
                        source_artifact=EV_3M_REL),
            _make_claim("release gate verdict (21 gates)",
                        "release_gate_verdict", "PASS"),
        ]
        _write_final_results(str(tmp_path), claims)
        report = _run_real_verify_claims(str(tmp_path))
        rows_result = next(r for r in report["results"]
                           if "3M rows" in r.get("claim", ""))
        assert rows_result["ok"] is False, (
            "Attacker-modified unrelated claim MUST FAIL")
        assert report["recheck_passed"] is False


# ---------------------------------------------------------------------------
# Test 9, 10: post-publication + fixed point
# ---------------------------------------------------------------------------

class TestPostPublicationAndFixedPoint:
    """Tests 9, 10: post-publication strict verification + fixed point."""

    def test_9_post_publication_PASS_strict_verification(self, tmp_path):
        """Test 9: post-publication PASS → strict verification.

        After marker removal, normal strict verify_claim() applies.
        Match → verified=True; mismatch → ok=False (FAIL).
        """
        _bootstrap_minimal_repo(str(tmp_path))

        # Sub-test A: match → verified=True
        _write_gate_report(str(tmp_path), verdict="PASS")
        # NO marker
        claims = [
            _make_claim("release gate verdict (21 gates)",
                        "release_gate_verdict", "PASS"),
        ]
        _write_final_results(str(tmp_path), claims)
        report = _run_real_verify_claims(str(tmp_path))
        rgv = report["results"][0]
        assert rgv["ok"] is True
        assert rgv["verified"] is True, (
            "Post-publication: gate=PASS, claimed=PASS → verified=True")

        # Sub-test B: mismatch → ok=False
        _write_gate_report(str(tmp_path), verdict="FAIL")  # live FAIL
        # NO marker
        report2 = _run_real_verify_claims(str(tmp_path))
        rgv2 = report2["results"][0]
        assert rgv2["ok"] is False, (
            "Post-publication: gate=FAIL, claimed=PASS → ok=False (FAIL)")

    def test_10_second_gate_run_PASS_without_regeneration(self, tmp_path):
        """Test 10: second gate run → PASS without regenerating
        FINAL_RESULTS.

        Round 1: FINAL_RESULTS=PASS, marker absent, gate=PASS → PASS
        Round 2: marker created, FINAL_RESULTS UNCHANGED → PASS
        (with release_gate_verdict in PENDING state)
        """
        _bootstrap_minimal_repo(str(tmp_path))

        # Round 1: FINAL_RESULTS=PASS, marker absent, gate=PASS
        _write_gate_report(str(tmp_path), verdict="PASS")
        claims = [
            _make_claim("release gate verdict (21 gates)",
                        "release_gate_verdict", "PASS"),
        ]
        _write_final_results(str(tmp_path), claims)
        round1 = _run_real_verify_claims(str(tmp_path))
        assert round1["recheck_passed"] is True, (
            "Round 1 (state E) MUST PASS")
        rgv1 = round1["results"][0]
        assert rgv1["verified"] is True, (
            "Round 1: release_gate_verdict verified=True (match)")

        # Round 2: marker created, FINAL_RESULTS UNCHANGED
        _write_marker(str(tmp_path))
        # DO NOT regenerate FINAL_RESULTS — read from disk
        round2 = _run_real_verify_claims(str(tmp_path))
        assert round2["recheck_passed"] is True, (
            "Round 2 (state F) MUST PASS — fixed point established")
        rgv2 = round2["results"][0]
        assert rgv2["ok"] is True
        assert rgv2["verified"] is False, (
            "Round 2: release_gate_verdict verified=False (PENDING)")
        assert rgv2["detail"].get("state") == "SELF_REFERENTIAL_PENDING"


# ---------------------------------------------------------------------------
# Security invariants (always-on checks)
# ---------------------------------------------------------------------------

class TestSecurityInvariants:
    """Verify the security invariants are preserved."""

    def test_F01_helper_remains_fail_closed_during_marker(self, tmp_path):
        """F-01 helper MUST still return None during marker for ALL
        trust-sensitive consumers."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")  # stale
        _write_marker(str(tmp_path))

        # Consumer 1: release_chain
        helper = release_chain.load_current_release_gate_report(str(tmp_path))
        assert helper is None, "release_chain: helper returns None"

        # Consumer 2: claims._d_gate
        d_gate_result = claims_mod._d_gate(str(tmp_path))
        assert d_gate_result is None, "claims._d_gate: returns None"

        # Consumer 3: contradiction_checker
        truth, sources = contradiction_checker.derive_truth(str(tmp_path))
        assert sources.get("gate") == "missing"
        assert truth.get("gate_verdict") is None

    def test_GATE_COUNT_remains_24(self):
        """GATE_COUNT MUST remain 24 — no new gate added."""
        import importlib.util
        spec_path = os.path.join(REPO_ROOT, "scripts", "release_gate.py")
        spec = importlib.util.spec_from_file_location("rg_check", spec_path)
        rg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rg)
        assert rg.GATE_COUNT == 24
        assert rg.GATE_VERSION == "4.0.0"

    def test_sentinel_does_not_create_verified_PASS(self, tmp_path):
        """The sentinel MUST NOT produce verified=True. PENDING is
        verified=False, NOT PASS."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_marker(str(tmp_path))
        claims = [
            _make_claim("release gate verdict (21 gates)",
                        "release_gate_verdict", "PASS"),
        ]
        _write_final_results(str(tmp_path), claims)
        report = _run_real_verify_claims(str(tmp_path))
        rgv = report["results"][0]
        # PENDING is NOT verified=True
        assert rgv["verified"] is False
        # PENDING is NOT reported in claims_verified count
        assert report["claims_verified"] == 0
        # PENDING IS reported in claims_not_verified count
        assert report["claims_not_verified"] == 1
        # gate 20 passes (ok=True) but claim is honestly unverified
        assert report["recheck_passed"] is True

    def test_sentinel_only_for_release_gate_verdict(self, tmp_path):
        """The sentinel applies ONLY to release_gate_verdict derivation.
        Any other derivation + marker goes through normal verify_claim."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_marker(str(tmp_path))
        # Use a derivation that reads the 3M FINAL_RESULTS (not the
        # gate report). The marker doesn't affect this derivation.
        # Claim recorded with correct value → PASS (normal path)
        claims = [
            _make_claim("final 3M rows", "final_3m_rows", 3200000,
                        source_artifact=EV_3M_REL),
        ]
        _write_final_results(str(tmp_path), claims)
        report = _run_real_verify_claims(str(tmp_path))
        rows = report["results"][0]
        assert rows["ok"] is True
        assert rows["verified"] is True
        # NOT PENDING
        assert rows["detail"].get("state") != "SELF_REFERENTIAL_PENDING"
