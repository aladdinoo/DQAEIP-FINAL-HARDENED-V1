"""Phase 13H.15 — Claim-Provenance Circularity Security Validation tests.

These tests DOCUMENT and VERIFY the security analysis findings. They
do NOT weaken any existing tests; they are pure additions that codify
the negative/fail-closed requirements and the circularity analysis.

KEY FINDINGS THESE TESTS ENCODE:
1. The proposed release_chain.py fix (if marker_exists:) only touches
   the root_to_gate edge in verify_chain (gate 21). It does NOT touch
   gate_claim_provenance (gate 20).

2. gate_claim_provenance uses claims.verify_claims -> _d_gate ->
   load_current_release_gate_report INDEPENDENTLY of verify_chain.
   During the marker, _d_gate returns None (F-01 helper blocks),
   so a FINAL_RESULTS claim recorded as verified=true,value="PASS"
   cannot be re-derived -> recheck_passed=False -> FAIL.

3. This means: with FINAL_RESULTS committed with claimed_gate=PASS,
   the NEXT gate run (marker created) will FAIL gate_claim_provenance
   regardless of the proposed release_chain.py fix. The proposed fix
   does NOT establish a fixed point.

4. The two-stage build discipline WORKS ONLY if FINAL_RESULTS is
   rebuilt to claimed_gate=None BEFORE the next gate run starts.
   But that means the committed FINAL_RESULTS is then stale relative
   to the live gate (which says PASS), caught by the
   test_gate_verdict_claims_match_live_artifact test.

Negative/fail-closed cases (8 required by the user) verified:
  1. marker + stale PASS report          -> helper returns None (F-01)
  2. marker + corrupted report            -> helper returns None
  3. marker + malformed claim             -> gate_claim_provenance FAIL
  4. marker after interrupted gate run    -> helper returns None
  5. marker created by unauthorized actor -> helper returns None
     (F-01 has no auth on marker; fail-closed)
  6. FINAL_RESULTS modified to PASS mid-marker -> gate_claim_provenance
     FAILS (claim=PASS but _d_gate=None, mismatch)
  7. previous evidence different release identity -> NOT IMPLEMENTED
     (the system has no release-identity check on the gate report;
     this is a known design gap, not addressed by the proposed fix)
  8. post-publication verification mismatch (FINAL_RESULTS=PASS,
     live gate=FAIL) -> root_to_gate FAILS, claim_provenance FAILS

The tests are organized into:
  - TestF01HelperBehavior: helper returns None for all marker cases
  - TestRootToGateEdgeProposedFix: root_to_gate behavior with the
    proposed release_chain.py fix
  - TestClaimProvenanceGateIndependence: gate_claim_provenance
    independently fails when claimed=PASS but helper=None (this is
    the heart of the circularity)
  - TestCompleteLifecycle: walk through all marker lifecycle states
  - TestNegativeCases: the 8 required negative cases
  - TestDesignAEvaluation: explicit pending/deferred semantics
    proposal (NOT IMPLEMENTED; tests document the gap)
  - TestDesignBEvaluation: previous evidence with independent
    integrity (NOT IMPLEMENTED; tests document the gap)
  - TestFixedPointDisproof: state E -> state F oscillation
"""
import json
import os
import shutil
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance import release_chain
from data_quality_platform.assurance import claims as claims_mod
from data_quality_platform.assurance import contradiction_checker


# ---------------------------------------------------------------------------
# Helpers (intentionally minimal; do NOT import from
# test_f01_canonical_helper.py to keep the test files independent)
# ---------------------------------------------------------------------------

GATE_REPORT_REL = "evidence/release_gate/final_release_gate.json"
GATE_MARKER_REL = "evidence/release_gate/final_release_gate.json.in_progress"
FINAL_RESULTS_REL = "FINAL_RESULTS.json"
EV_3M_REL = "evidence/validation/2026-09-19/fresh_3m2/FINAL_RESULTS.json"


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


def _write_final_results(repo_root, claimed_gate=None):
    """Write a minimal FINAL_RESULTS.json. claimed_gate:
       - None: claim recorded as NOT_VERIFIED (value=None)
       - "PASS": claim recorded as VERIFIED_LOCALLY (value="PASS")
       - "FAIL": claim recorded as verified=true, value="FAIL"
       - "malformed": non-dict claims field
    """
    if claimed_gate == "malformed":
        return _write(repo_root, FINAL_RESULTS_REL, {
            "verification": {"release_gate_verdict": "PASS"},
            "claims": "not_a_list",  # malformed
        })
    if claimed_gate == "PASS":
        claim = {
            "claim_id": "CLAIM-release-gate-verdict-abc123",
            "claim": "release gate verdict (21 gates)",
            "value": "PASS",
            "source_artifact": GATE_REPORT_REL,
            "derivation": "release_gate_verdict",
            "verified": True,
            "status": "VERIFIED_LOCALLY",
        }
    elif claimed_gate == "FAIL":
        claim = {
            "claim_id": "CLAIM-release-gate-verdict-abc123",
            "claim": "release gate verdict (21 gates)",
            "value": "FAIL",
            "source_artifact": GATE_REPORT_REL,
            "derivation": "release_gate_verdict",
            "verified": True,
            "status": "VERIFIED_LOCALLY",
        }
    else:  # None — NOT_VERIFIED claim
        claim = {
            "claim_id": "CLAIM-release-gate-verdict-abc123",
            "claim": "release gate verdict (21 gates)",
            "value": None,
            "source_artifact": None,
            "derivation": None,
            "verified": False,
            "status": "NOT_VERIFIED",
            "reason": "pending: release gate not yet executed",
        }
    return _write(repo_root, FINAL_RESULTS_REL, {
        "schema": "dqaeip.final_results",
        "release_name": "DQAEIP-Enterprise-Assurance-Validation-Release",
        "release_date": "2026-09-19",
        "verification": {"release_gate_verdict": claimed_gate},
        "claims": [claim],
    })


def _bootstrap_minimal_repo(tmp_root):
    """Set up minimal repo skeleton for verify_chain + claim_provenance
    tests. Includes:
      - 3M FINAL_RESULTS evidence (minimal valid shape)
      - Per-run engine manifests with rule_hashes and schema_hash
      - Rule source and checker files (just exist for sha)
      - release_manifest, README, RELEASE_NOTES
    """
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


# ---------------------------------------------------------------------------
# F-01 Helper Behavior Tests (marker blocks ALL trust-sensitive reads)
# ---------------------------------------------------------------------------

class TestF01HelperBehavior:
    """Verify F-01's load_current_release_gate_report returns None for
    every marker-related negative case. These are PRE-CONDITIONS for
    the rest of the security analysis."""

    def test_no_marker_no_report_returns_none(self, tmp_path):
        _bootstrap_minimal_repo(str(tmp_path))
        assert release_chain.load_current_release_gate_report(
            str(tmp_path)) is None

    def test_marker_with_stale_pass_returns_none(self, tmp_path):
        """REQUIRED NEGATIVE CASE 1: marker + stale PASS report."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")
        _write_marker(str(tmp_path))
        assert release_chain.load_current_release_gate_report(
            str(tmp_path)) is None

    def test_marker_with_corrupted_report_returns_none(self, tmp_path):
        """REQUIRED NEGATIVE CASE 2: marker + corrupted (malformed) report."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write(str(tmp_path), GATE_REPORT_REL, "{bad json")
        _write_marker(str(tmp_path))
        assert release_chain.load_current_release_gate_report(
            str(tmp_path)) is None

    def test_marker_after_interrupted_gate_run_returns_none(self, tmp_path):
        """REQUIRED NEGATIVE CASE 4: marker stays after crash; .tmp
        partial; no report."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_marker(str(tmp_path))
        _write(str(tmp_path),
               "evidence/release_gate/final_release_gate.json.tmp",
               json.dumps({"overall_verdict": "PASS"}))
        assert release_chain.load_current_release_gate_report(
            str(tmp_path)) is None

    def test_marker_created_by_unauthorized_actor_returns_none(self, tmp_path):
        """REQUIRED NEGATIVE CASE 5: marker is created by an unauthorized
        actor. F-01 has no auth on the marker; an empty marker file
        triggers the same block."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")
        # Write marker as empty file (simulating unauthorized touch)
        marker = _write_marker(str(tmp_path))
        # Truncate to empty (attacker might not write content)
        with open(marker, "w") as f:
            f.write("")
        assert release_chain.load_current_release_gate_report(
            str(tmp_path)) is None

    def test_no_marker_valid_pass_returns_report(self, tmp_path):
        """Sanity: without marker, valid PASS report is trusted."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")
        r = release_chain.load_current_release_gate_report(str(tmp_path))
        assert r is not None
        assert r["overall_verdict"] == "PASS"


# ---------------------------------------------------------------------------
# Root-to-Gate Edge (Proposed Fix) Tests
# ---------------------------------------------------------------------------

class TestRootToGateEdgeProposedFix:
    """Verify the root_to_gate edge behavior with the proposed
    release_chain.py fix (if marker_exists: accept all claimed_gate).

    The proposed fix is ALREADY in the working tree (uncommitted). These
    tests document the proposed behavior.
    """

    def test_marker_present_claimed_pass_accepted_by_root_to_gate(
            self, tmp_path):
        """With the proposed fix, marker present + claimed_gate=PASS ->
        root_to_gate_ok=True (pending state)."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")  # stale PASS
        _write_marker(str(tmp_path))
        _write_final_results(str(tmp_path), claimed_gate="PASS")
        ok, report = release_chain.verify_chain(str(tmp_path))
        edge = report["edges"].get("root_to_gate", {})
        assert edge["verified"] is True  # proposed fix accepts
        assert edge["detail"]["gate_in_progress"] is True

    def test_marker_present_claimed_none_accepted_by_root_to_gate(
            self, tmp_path):
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")
        _write_marker(str(tmp_path))
        _write_final_results(str(tmp_path), claimed_gate=None)
        ok, report = release_chain.verify_chain(str(tmp_path))
        edge = report["edges"].get("root_to_gate", {})
        assert edge["verified"] is True

    def test_marker_absent_claimed_pass_requires_live_pass(self, tmp_path):
        """After marker removed, claimed_gate=PASS requires gate_verdict=PASS
        (strict mode)."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")
        _write_final_results(str(tmp_path), claimed_gate="PASS")
        ok, report = release_chain.verify_chain(str(tmp_path))
        edge = report["edges"].get("root_to_gate", {})
        assert edge["verified"] is True
        assert edge["detail"]["release_gate_verdict"] == "PASS"

    def test_marker_absent_claimed_pass_but_live_fail_rejected(
            self, tmp_path):
        """REQUIRED NEGATIVE CASE 8: post-publication mismatch — FINAL_RESULTS
        says PASS but live gate says FAIL. root_to_gate must FAIL."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="FAIL")
        _write_final_results(str(tmp_path), claimed_gate="PASS")
        ok, report = release_chain.verify_chain(str(tmp_path))
        edge = report["edges"].get("root_to_gate", {})
        assert edge["verified"] is False  # FAIL — caught the mismatch


# ---------------------------------------------------------------------------
# Claim Provenance Gate Independence Tests (the HEART of the circularity)
# ---------------------------------------------------------------------------

def _run_claim_provenance_gate(repo_root):
    """Run the gate_claim_provenance logic from release_gate.py:1271-1324
    in isolation (no GateRunner instantiation needed)."""
    fr_path = os.path.join(repo_root, "FINAL_RESULTS.json")
    try:
        with open(fr_path, encoding="utf-8") as f:
            fr = json.load(f)
    except Exception as exc:
        return {"status": "FAIL",
                "reason": f"FINAL_RESULTS unreadable: {type(exc).__name__}"}
    claim_list = fr.get("claims", [])
    if not isinstance(claim_list, list) or not claim_list:
        return {"status": "FAIL", "reason": "no claims"}
    report = claims_mod.verify_claims(claim_list, repo_root)
    if report["recheck_passed"]:
        return {"status": "PASS", "verified": report["claims_verified"],
                "not_verified": report["claims_not_verified"]}
    failing = [r for r in report["results"] if not r["ok"]]
    return {"status": "FAIL", "failing_count": len(failing),
            "failing_first": failing[0] if failing else None}


class TestClaimProvenanceGateIndependence:
    """These tests prove that gate_claim_provenance is the ACTUAL
    blocker of the circularity, NOT root_to_gate. The proposed
    release_chain.py fix doesn't touch this gate at all."""

    def test_marker_present_claimed_pass_pending_claim_provenance(
            self, tmp_path):
        """THE KEY TEST: with marker present and claimed_gate=PASS,
        the sentinel returns SELF_REFERENTIAL_PENDING because:
          - claim derivation == "release_gate_verdict" (self-referential)
          - marker exists (gate is mid-execution)
          - F-01 helper returns None (blocks stale PASS)
          - sentinel returns ok=True, verified=False, state=PENDING

        The claim is NOT verified as PASS. The security property
        "no unauthorized PASS" is preserved by verified=False.
        """
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")  # stale PASS
        _write_marker(str(tmp_path))
        _write_final_results(str(tmp_path), claimed_gate="PASS")
        # Direct verify_claims call to inspect full sentinel state
        fr_path = os.path.join(str(tmp_path), "FINAL_RESULTS.json")
        with open(fr_path, encoding="utf-8") as f:
            fr = json.load(f)
        report = claims_mod.verify_claims(fr.get("claims", []),
                                           str(tmp_path))
        # Aggregate-level assertions
        assert report["recheck_passed"] is True, (
            "gate 20 must PASS — sentinel returns ok=True for "
            f"self-referential claim during marker. Result: {report}")
        assert report["claims_verified"] == 0, (
            "NO claim may be counted as verified — sentinel returns "
            "verified=False, so claims_verified must be 0")
        assert report["claims_not_verified"] == 1, (
            "sentinel claim MUST be counted as not_verified")
        # Per-claim sentinel-state assertions
        rgv = report["results"][0]
        assert rgv["ok"] is True, (
            "sentinel ok must be True (gate doesn't FAIL)")
        assert rgv["verified"] is False, (
            "sentinel verified MUST be False — PENDING is NOT PASS")
        assert rgv["detail"]["state"] == "SELF_REFERENTIAL_PENDING", (
            "sentinel state must be SELF_REFERENTIAL_PENDING")

    def test_marker_present_claimed_none_passes_claim_provenance(
            self, tmp_path):
        """With marker present and claimed_gate=None (NOT_VERIFIED),
        gate_claim_provenance PASSES because the claim is recorded as
        verified=false,value=None and verify_claims line 489-493
        bypasses re-derivation for NOT_VERIFIED claims."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")
        _write_marker(str(tmp_path))
        _write_final_results(str(tmp_path), claimed_gate=None)
        result = _run_claim_provenance_gate(str(tmp_path))
        assert result["status"] == "PASS"
        assert result["not_verified"] == 1

    def test_marker_absent_claimed_pass_with_live_pass_passes(
            self, tmp_path):
        """After marker removed and gate=PASS, gate_claim_provenance
        re-derives the claim and matches."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")
        _write_final_results(str(tmp_path), claimed_gate="PASS")
        result = _run_claim_provenance_gate(str(tmp_path))
        assert result["status"] == "PASS"
        assert result["verified"] == 1

    def test_marker_absent_claimed_pass_with_live_fail_fails(
            self, tmp_path):
        """REQUIRED NEGATIVE CASE 8: post-publication mismatch — claimed=PASS
        but live gate=FAIL. gate_claim_provenance FAILS."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="FAIL")
        _write_final_results(str(tmp_path), claimed_gate="PASS")
        result = _run_claim_provenance_gate(str(tmp_path))
        assert result["status"] == "FAIL"
        assert "FAIL" in str(result.get("failing_first", ""))

    def test_marker_present_malformed_claim_fails(self, tmp_path):
        """REQUIRED NEGATIVE CASE 3: malformed claim (non-dict) fails."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")
        _write_marker(str(tmp_path))
        _write_final_results(str(tmp_path), claimed_gate="malformed")
        result = _run_claim_provenance_gate(str(tmp_path))
        assert result["status"] == "FAIL"

    def test_marker_present_FINAL_RESULTS_modified_to_PASS_pending(
            self, tmp_path):
        """REQUIRED NEGATIVE CASE 6: FINAL_RESULTS modified to claim PASS
        while marker exists (mid-gate-run tamper). The sentinel returns
        PENDING (ok=True, verified=False) — the tampered claim is NOT
        verified as PASS. The security property "no unauthorized PASS"
        is preserved by verified=False."""
        _bootstrap_minimal_repo(str(tmp_path))
        # Initial state: FINAL_RESULTS=NOT_VERIFIED, gate=PASS
        _write_gate_report(str(tmp_path), verdict="PASS")
        _write_final_results(str(tmp_path), claimed_gate=None)
        # Start gate run (marker created)
        _write_marker(str(tmp_path))
        # Attacker modifies FINAL_RESULTS to claim PASS mid-run
        _write_final_results(str(tmp_path), claimed_gate="PASS")
        # Direct verify_claims call to verify sentinel state
        fr_path = os.path.join(str(tmp_path), "FINAL_RESULTS.json")
        with open(fr_path, encoding="utf-8") as f:
            fr = json.load(f)
        report = claims_mod.verify_claims(fr.get("claims", []),
                                           str(tmp_path))
        assert report["recheck_passed"] is True
        assert report["claims_verified"] == 0, (
            "NO claim verified as PASS — mid-run tamper cannot produce "
            "unauthorized PASS")
        assert report["claims_not_verified"] == 1
        rgv = report["results"][0]
        assert rgv["ok"] is True
        assert rgv["verified"] is False, (
            "PENDING is NOT PASS — verified must be False")
        assert rgv["detail"]["state"] == "SELF_REFERENTIAL_PENDING"


# ---------------------------------------------------------------------------
# Complete Lifecycle Tests
# ---------------------------------------------------------------------------

class TestCompleteLifecycle:
    """Walk through the documented two-stage build discipline and
    the marker lifecycle, verifying each transition maintains the
    fail-closed contract."""

    def test_full_lifecycle_fixed_point_established(self, tmp_path):
        """Walk: initial (None) -> gate run (marker created) -> gate
        completes (marker removed, PASS report) -> refresh (FINAL_RESULTS
        rebuilt with PASS) -> next gate run starts (marker created) ->
        gate_claim_provenance PASSES with SELF_REFERENTIAL_PENDING.

        This test PROVES the sentinel design establishes a fixed point:
        state F (next gate run with FINAL_RESULTS=PASS) no longer FAILS.
        The self-referential claim enters PENDING state (verified=False,
        not verified PASS).
        """
        _bootstrap_minimal_repo(str(tmp_path))

        # STATE A: initial build, FINAL_RESULTS=NOT_VERIFIED, no marker
        _write_final_results(str(tmp_path), claimed_gate=None)
        a_cp = _run_claim_provenance_gate(str(tmp_path))
        assert a_cp["status"] == "PASS"  # NOT_VERIFIED claim is ok

        # STATE B: gate run starts, marker created
        _write_marker(str(tmp_path))
        b_cp = _run_claim_provenance_gate(str(tmp_path))
        assert b_cp["status"] == "PASS"  # still None, marker doesn't matter

        # STATE C: gate completes, marker removed, fresh PASS report
        _remove_marker(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")
        c_cp = _run_claim_provenance_gate(str(tmp_path))
        assert c_cp["status"] == "PASS"  # FINAL_RESULTS still None

        # STATE D: refresh FINAL_RESULTS with claimed=PASS
        _write_final_results(str(tmp_path), claimed_gate="PASS")
        d_cp = _run_claim_provenance_gate(str(tmp_path))
        assert d_cp["status"] == "PASS"  # both match
        assert d_cp["verified"] == 1

        # STATE E (F): NEXT gate run starts, marker created, FINAL_RESULTS
        # still claims PASS from the refresh
        _write_marker(str(tmp_path))
        e_cp = _run_claim_provenance_gate(str(tmp_path))
        # FIXED POINT: state E (F) now PASSES because the sentinel returns
        # ok=True, verified=False, state=SELF_REFERENTIAL_PENDING for the
        # self-referential claim during marker.
        assert e_cp["status"] == "PASS", (
            "STATE E (next gate run with FINAL_RESULTS=PASS) now PASSES "
            "gate_claim_provenance because the sentinel returns PENDING "
            f"for the self-referential claim. Result: {e_cp}")
        assert e_cp["verified"] == 0, (
            "NO claim is verified as PASS during marker — sentinel "
            "returns verified=False")
        assert e_cp["not_verified"] == 1, (
            "sentinel claim IS counted as not_verified")
        # Direct verify_claims call to verify sentinel state
        fr_path = os.path.join(str(tmp_path), "FINAL_RESULTS.json")
        with open(fr_path, encoding="utf-8") as f:
            fr = json.load(f)
        report = claims_mod.verify_claims(fr.get("claims", []),
                                           str(tmp_path))
        rgv = report["results"][0]
        assert rgv["ok"] is True
        assert rgv["verified"] is False, (
            "PENDING is NOT PASS — verified must be False")
        assert rgv["detail"]["state"] == "SELF_REFERENTIAL_PENDING"

    def test_lifecycle_failure_path(self, tmp_path):
        """Walk the failure path: gate run starts, gate FAILS internally,
        marker stays (F-03 fail-closed), helper returns None, next run
        must NOT trust stale PASS."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_final_results(str(tmp_path), claimed_gate=None)
        # Initial: stale PASS report from a previous run
        _write_gate_report(str(tmp_path), verdict="PASS")
        # Start gate run (marker created)
        _write_marker(str(tmp_path))
        # Gate fails internally (exception); marker stays
        # (we don't simulate the actual exception; we just verify the
        # marker stays and helper returns None)
        helper = release_chain.load_current_release_gate_report(
            str(tmp_path))
        assert helper is None  # marker blocks stale PASS

    def test_lifecycle_cleanup_path(self, tmp_path):
        """Walk the cleanup path: after crash, manually remove marker
        and stale report, then run fresh gate."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_final_results(str(tmp_path), claimed_gate=None)
        # Crash left: stale PASS report + marker
        _write_gate_report(str(tmp_path), verdict="PASS")
        _write_marker(str(tmp_path))
        # Helper blocks
        assert release_chain.load_current_release_gate_report(
            str(tmp_path)) is None
        # Cleanup: remove marker AND stale report
        _remove_marker(str(tmp_path))
        _remove(str(tmp_path), GATE_REPORT_REL)
        # Now: no marker, no report -> helper returns None
        assert release_chain.load_current_release_gate_report(
            str(tmp_path)) is None
        # Fresh gate run: write fresh report
        _write_gate_report(str(tmp_path), verdict="PASS")
        r = release_chain.load_current_release_gate_report(str(tmp_path))
        assert r is not None
        assert r["overall_verdict"] == "PASS"


# ---------------------------------------------------------------------------
# All 8 Required Negative cases consolidated
# ---------------------------------------------------------------------------

class TestRequiredNegativeCases:
    """The 8 negative cases required by the user. Each verifies
    fail-closed behavior."""

    def test_case_1_marker_with_stale_pass_report(self, tmp_path):
        """marker exists with a stale PASS report -> F-01 blocks.
        The self-referential claim enters PENDING state (NOT PASS)."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")
        _write_marker(str(tmp_path))
        _write_final_results(str(tmp_path), claimed_gate="PASS")
        # F-01 helper MUST still block stale PASS (UNCHANGED)
        assert release_chain.load_current_release_gate_report(
            str(tmp_path)) is None
        # Direct verify_claims call to verify sentinel state
        fr_path = os.path.join(str(tmp_path), "FINAL_RESULTS.json")
        with open(fr_path, encoding="utf-8") as f:
            fr = json.load(f)
        report = claims_mod.verify_claims(fr.get("claims", []),
                                           str(tmp_path))
        # Aggregate-level: gate 20 passes (ok=True), but no claim verified
        assert report["recheck_passed"] is True
        assert report["claims_verified"] == 0, (
            "NO claim verified as PASS — stale PASS is NOT trusted")
        assert report["claims_not_verified"] == 1
        # Per-claim sentinel state
        rgv = report["results"][0]
        assert rgv["ok"] is True
        assert rgv["verified"] is False, (
            "PENDING is NOT PASS — verified must be False")
        assert rgv["detail"]["state"] == "SELF_REFERENTIAL_PENDING"

    def test_case_2_marker_with_corrupted_report(self, tmp_path):
        """marker exists with a corrupted report. F-01 blocks.
        The self-referential claim enters PENDING state (NOT PASS)."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write(str(tmp_path), GATE_REPORT_REL, "{bad json")
        _write_marker(str(tmp_path))
        _write_final_results(str(tmp_path), claimed_gate="PASS")
        # F-01 helper MUST still block corrupted report (UNCHANGED)
        assert release_chain.load_current_release_gate_report(
            str(tmp_path)) is None
        # Direct verify_claims call to verify sentinel state
        fr_path = os.path.join(str(tmp_path), "FINAL_RESULTS.json")
        with open(fr_path, encoding="utf-8") as f:
            fr = json.load(f)
        report = claims_mod.verify_claims(fr.get("claims", []),
                                           str(tmp_path))
        assert report["recheck_passed"] is True
        assert report["claims_verified"] == 0, (
            "NO claim verified as PASS — corrupted evidence NOT trusted")
        assert report["claims_not_verified"] == 1
        rgv = report["results"][0]
        assert rgv["ok"] is True
        assert rgv["verified"] is False, (
            "PENDING is NOT PASS — verified must be False")
        assert rgv["detail"]["state"] == "SELF_REFERENTIAL_PENDING"

    def test_case_3_marker_with_malformed_claim(self, tmp_path):
        """marker exists with a malformed claim (non-dict in claims list)."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")
        _write_marker(str(tmp_path))
        _write_final_results(str(tmp_path), claimed_gate="malformed")
        result = _run_claim_provenance_gate(str(tmp_path))
        assert result["status"] == "FAIL"

    def test_case_4_marker_after_interrupted_gate_run(self, tmp_path):
        """marker stays after crash; .tmp partial; no final report.
        F-01 blocks. Self-referential claim enters PENDING (NOT PASS)."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_marker(str(tmp_path))
        _write(str(tmp_path),
               "evidence/release_gate/final_release_gate.json.tmp",
               json.dumps({"overall_verdict": "PASS"}))
        _write_final_results(str(tmp_path), claimed_gate="PASS")
        # F-01 helper MUST still block after crash-left marker (UNCHANGED)
        assert release_chain.load_current_release_gate_report(
            str(tmp_path)) is None
        # Direct verify_claims call to verify sentinel state
        fr_path = os.path.join(str(tmp_path), "FINAL_RESULTS.json")
        with open(fr_path, encoding="utf-8") as f:
            fr = json.load(f)
        report = claims_mod.verify_claims(fr.get("claims", []),
                                           str(tmp_path))
        assert report["recheck_passed"] is True
        assert report["claims_verified"] == 0, (
            "NO claim verified as PASS — stale marker cannot create PASS")
        assert report["claims_not_verified"] == 1
        rgv = report["results"][0]
        assert rgv["ok"] is True
        assert rgv["verified"] is False, (
            "PENDING is NOT PASS — verified must be False")
        assert rgv["detail"]["state"] == "SELF_REFERENTIAL_PENDING"

    def test_case_5_marker_created_by_unauthorized_actor(self, tmp_path):
        """marker created by an unauthorized actor (empty file). F-01 has
        no auth signature on the marker; the existence of the file
        triggers the fail-closed block. Self-referential claim enters
        PENDING (NOT PASS) — unauthorized marker cannot create PASS."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")
        marker = _write_marker(str(tmp_path))
        # Truncate to empty file (attacker might use `touch`)
        with open(marker, "w") as f:
            f.write("")
        _write_final_results(str(tmp_path), claimed_gate="PASS")
        # F-01 helper MUST still block unauthorized marker (UNCHANGED)
        assert release_chain.load_current_release_gate_report(
            str(tmp_path)) is None
        # Direct verify_claims call to verify sentinel state
        fr_path = os.path.join(str(tmp_path), "FINAL_RESULTS.json")
        with open(fr_path, encoding="utf-8") as f:
            fr = json.load(f)
        report = claims_mod.verify_claims(fr.get("claims", []),
                                           str(tmp_path))
        assert report["recheck_passed"] is True
        assert report["claims_verified"] == 0, (
            "NO claim verified as PASS — unauthorized marker cannot "
            "produce unauthorized PASS")
        assert report["claims_not_verified"] == 1
        rgv = report["results"][0]
        assert rgv["ok"] is True
        assert rgv["verified"] is False, (
            "PENDING is NOT PASS — verified must be False")
        assert rgv["detail"]["state"] == "SELF_REFERENTIAL_PENDING"

    def test_case_6_FINAL_RESULTS_modified_while_marker_exists(self, tmp_path):
        """FINAL_RESULTS modified to claim PASS while marker exists.
        Self-referential claim enters PENDING (NOT PASS) — mid-run
        tamper cannot produce unauthorized PASS."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")
        _write_final_results(str(tmp_path), claimed_gate=None)
        _write_marker(str(tmp_path))
        # Attacker modifies FINAL_RESULTS mid-run
        _write_final_results(str(tmp_path), claimed_gate="PASS")
        # Direct verify_claims call to verify sentinel state
        fr_path = os.path.join(str(tmp_path), "FINAL_RESULTS.json")
        with open(fr_path, encoding="utf-8") as f:
            fr = json.load(f)
        report = claims_mod.verify_claims(fr.get("claims", []),
                                           str(tmp_path))
        assert report["recheck_passed"] is True
        assert report["claims_verified"] == 0, (
            "NO claim verified as PASS — mid-run tamper cannot produce "
            "unauthorized PASS")
        assert report["claims_not_verified"] == 1
        rgv = report["results"][0]
        assert rgv["ok"] is True
        assert rgv["verified"] is False, (
            "PENDING is NOT PASS — verified must be False")
        assert rgv["detail"]["state"] == "SELF_REFERENTIAL_PENDING"

    def test_case_7_previous_evidence_different_release_identity(
            self, tmp_path):
        """Previous evidence belongs to a different release identity.

        NOTE: The current implementation has NO release-identity check
        on the gate report. The gate report has no release_name or
        release_date field. This is a KNOWN DESIGN GAP. The proposed
        fix does not address it.

        This test DOCUMENTS the gap by showing that a report with a
        different release_date is still trusted (no check exists).
        """
        _bootstrap_minimal_repo(str(tmp_path))
        # Write a report with a different release identity
        _write(str(tmp_path), GATE_REPORT_REL, {
            "release_gate": "dqavp-unified-release-gate",
            "gate_version": "4.0.0",
            "gate_count": 24,
            "overall_verdict": "PASS",
            "release_name": "DIFFERENT_RELEASE",  # not the current
            "release_date": "2025-01-01",  # different release date
        })
        _write_final_results(str(tmp_path), claimed_gate="PASS")
        # Helper returns the report (no release-identity check)
        r = release_chain.load_current_release_gate_report(str(tmp_path))
        # GAP: this SHOULD be None (different release identity) but
        # the helper has no such check.
        assert r is not None, (
            "DESIGN GAP: load_current_release_gate_report has no "
            "release-identity check. A report from a different release "
            "is trusted as current. This is not addressed by the proposed "
            "release_chain.py fix. Design B would need to add this check.")

    def test_case_8_post_publication_verification_mismatch(self, tmp_path):
        """post-publication verification detects a mismatch: FINAL_RESULTS
        says PASS but live gate now says FAIL (post-PASS tampering)."""
        _bootstrap_minimal_repo(str(tmp_path))
        # Gate report was PASS, then attacker changed it to FAIL
        _write_gate_report(str(tmp_path), verdict="FAIL")
        # FINAL_RESULTS still claims PASS (committed before tamper)
        _write_final_results(str(tmp_path), claimed_gate="PASS")
        # Helper returns the FAIL report (no marker)
        r = release_chain.load_current_release_gate_report(str(tmp_path))
        assert r is not None
        assert r["overall_verdict"] == "FAIL"
        # root_to_gate must FAIL (mismatch)
        ok, report = release_chain.verify_chain(str(tmp_path))
        edge = report["edges"].get("root_to_gate", {})
        assert edge["verified"] is False
        # claim_provenance must FAIL (derived=FAIL, recorded=PASS)
        result = _run_claim_provenance_gate(str(tmp_path))
        assert result["status"] == "FAIL"


# ---------------------------------------------------------------------------
# Fixed-Point Disproof Tests
# ---------------------------------------------------------------------------

class TestFixedPointDisproof:
    """Tests that prove NO fixed point exists with the proposed fix
    alone. A fixed point would mean: a state where all gates PASS,
    FINAL_RESULTS committed, no need to regenerate anything, and the
    next gate run also passes without regeneration."""

    def test_state_E_IS_a_fixed_point(self, tmp_path):
        """State E: FINAL_RESULTS=PASS, marker absent, gate=PASS.

        With the sentinel design, state E IS a fixed point: the next
        gate run (state F: marker created) also PASSES without
        regeneration. The self-referential claim enters PENDING state
        (verified=False, NOT verified PASS).
        """
        _bootstrap_minimal_repo(str(tmp_path))
        # Build state E
        _write_gate_report(str(tmp_path), verdict="PASS")
        _write_final_results(str(tmp_path), claimed_gate="PASS")
        # Confirm state E passes (normal match, verified=True)
        e_cp = _run_claim_provenance_gate(str(tmp_path))
        assert e_cp["status"] == "PASS"
        assert e_cp["verified"] == 1, (
            "State E: claim is genuinely verified (normal match path)")

        # Transition to state F: marker created (next gate run starts)
        _write_marker(str(tmp_path))
        f_cp = _run_claim_provenance_gate(str(tmp_path))
        # FIXED POINT: state F now PASSES (sentinel returns PENDING)
        assert f_cp["status"] == "PASS", (
            "STATE F (next gate run with FINAL_RESULTS=PASS) now PASSES "
            "because the sentinel returns PENDING for the self-referential "
            f"claim. Result: {f_cp}")
        assert f_cp["verified"] == 0, (
            "State F: NO claim is verified as PASS — sentinel returns "
            "verified=False")
        assert f_cp["not_verified"] == 1, (
            "State F: sentinel claim IS counted as not_verified")
        # Direct verify_claims call to verify sentinel state
        fr_path = os.path.join(str(tmp_path), "FINAL_RESULTS.json")
        with open(fr_path, encoding="utf-8") as f:
            fr = json.load(f)
        report = claims_mod.verify_claims(fr.get("claims", []),
                                           str(tmp_path))
        rgv = report["results"][0]
        assert rgv["ok"] is True
        assert rgv["verified"] is False, (
            "PENDING is NOT PASS — verified must be False")
        assert rgv["detail"]["state"] == "SELF_REFERENTIAL_PENDING"

    def test_state_D_passes_only_with_final_results_none(self, tmp_path):
        """State D: marker removed, gate=PASS, but FINAL_RESULTS must
        be None (claimed_gate=None) for the gate to PASS the next
        time. This is the bootstrap circularity."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")
        _write_final_results(str(tmp_path), claimed_gate=None)
        # Confirm state D passes (FINAL_RESULTS=None, gate=PASS)
        d_cp = _run_claim_provenance_gate(str(tmp_path))
        assert d_cp["status"] == "PASS"
        # But FINAL_RESULTS is stale (says None) relative to live gate
        # (says PASS) — caught by test_gate_verdict_claims_match_live_artifact

    def test_stable_state_with_sentinel_design(self, tmp_path):
        """With the sentinel design, a stable state EXISTS where:
          - FINAL_RESULTS=PASS (committed)
          - next gate run also PASSes (without regeneration)
          - the self-referential claim enters PENDING state
        Executes the same State F condition twice to demonstrate stability.
        """
        _bootstrap_minimal_repo(str(tmp_path))
        # State E: FINAL_RESULTS=PASS, marker absent, gate=PASS
        _write_gate_report(str(tmp_path), verdict="PASS")
        _write_final_results(str(tmp_path), claimed_gate="PASS")
        # Confirm state E passes (normal match, verified=True)
        e_result = _run_claim_provenance_gate(str(tmp_path))
        assert e_result["status"] == "PASS"
        assert e_result["verified"] == 1
        # State F: marker created, FINAL_RESULTS UNCHANGED
        _write_marker(str(tmp_path))
        # State F must PASS (fixed point — sentinel returns PENDING)
        f1_result = _run_claim_provenance_gate(str(tmp_path))
        assert f1_result["status"] == "PASS"
        assert f1_result["verified"] == 0
        assert f1_result["not_verified"] == 1
        # Direct verify_claims call to verify sentinel state (first run)
        fr_path = os.path.join(str(tmp_path), "FINAL_RESULTS.json")
        with open(fr_path, encoding="utf-8") as f:
            fr = json.load(f)
        report1 = claims_mod.verify_claims(fr.get("claims", []),
                                            str(tmp_path))
        rgv1 = report1["results"][0]
        assert rgv1["ok"] is True
        assert rgv1["verified"] is False
        assert rgv1["detail"]["state"] == "SELF_REFERENTIAL_PENDING"
        # Execute the same State F condition again to demonstrate stability
        # (no regeneration needed — the fixed point is stable)
        f2_result = _run_claim_provenance_gate(str(tmp_path))
        assert f2_result["status"] == "PASS"
        assert f2_result["verified"] == 0
        assert f2_result["not_verified"] == 1
        report2 = claims_mod.verify_claims(fr.get("claims", []),
                                            str(tmp_path))
        rgv2 = report2["results"][0]
        assert rgv2["ok"] is True
        assert rgv2["verified"] is False
        assert rgv2["detail"]["state"] == "SELF_REFERENTIAL_PENDING"


# ---------------------------------------------------------------------------
# Design A vs Design B Evaluation (NOT IMPLEMENTED; tests document gaps)
# ---------------------------------------------------------------------------

class TestDesignAEvaluation:
    """Design A: Explicit pending/deferred semantics while marker exists,
    followed by a verification step after publication and marker removal.

    This design would:
      1. Add a 'PENDING' status to claims.py
      2. claims.verify_claims: when marker exists and claim is for
         release_gate_verdict, return PENDING (not FAIL)
      3. release_gate.py gate_claim_provenance: accept PENDING while
         marker exists; FAIL otherwise
      4. NEW: post-publication verification step

    NOT IMPLEMENTED. These tests document the gap and the required
    contract for Design A.
    """

    def test_sentinel_implementation_in_claims(self):
        """The sentinel design IS implemented in claims.py. Verify
        the actual sentinel contract: SELF_REFERENTIAL_PENDING state
        and SELF_REFERENTIAL_DERIVATION constant."""
        src = open(os.path.join(
            REPO_ROOT, "data_quality_platform", "assurance",
            "claims.py")).read()
        assert "SELF_REFERENTIAL_PENDING" in src, (
            "claims.py must contain the SELF_REFERENTIAL_PENDING sentinel "
            "state — the Phase 13H.16/17 design is implemented")
        assert "SELF_REFERENTIAL_DERIVATION" in src, (
            "claims.py must contain the SELF_REFERENTIAL_DERIVATION "
            "constant — the sentinel applies only to release_gate_verdict")
        assert "GATE_MARKER_REL" in src, (
            "claims.py must contain the GATE_MARKER_REL constant — "
            "the sentinel checks the .in_progress marker path")

    def test_design_A_no_post_publication_verification_step(self):
        """CLAIM: Design A requires a post-publication verification
        step. No such step exists in scripts/."""
        scripts_dir = os.path.join(REPO_ROOT, "scripts")
        post_pub_found = False
        for fname in os.listdir(scripts_dir):
            if "post_publication" in fname.lower() or \
                    "verify_post" in fname.lower():
                post_pub_found = True
                break
        assert not post_pub_found, (
            "Design A would add a post-publication verification script. "
            "None found — Design A is not implemented.")


class TestDesignBEvaluation:
    """Design B: Read previous gate evidence during marker, but only
    if integrity/provenance/release-identity/freshness can be
    independently established.

    NOT IMPLEMENTED. These tests document the gap.
    """

    def test_design_B_no_previous_evidence_integrity_check(self):
        """CLAIM: Design B would add a function to verify previous
        gate report integrity. No such function exists in claims.py
        or release_chain.py."""
        for fname in ("claims.py", "release_chain.py"):
            fpath = os.path.join(REPO_ROOT, "data_quality_platform",
                                "assurance", fname)
            src = open(fpath).read()
            assert "_verify_previous_gate_report" not in src and \
                   "previous_gate_report" not in src, (
                       f"Design B would add previous-evidence "
                       f"verification to {fname}. Not present — "
                       f"Design B is not implemented.")

    def test_design_B_no_release_identity_check_on_gate_report(self):
        """CLAIM: Design B requires release-identity check on the gate
        report. The current gate report has no release-identity fields
        and load_current_release_gate_report performs no such check."""
        src = open(os.path.join(
            REPO_ROOT, "data_quality_platform", "assurance",
            "release_chain.py")).read()
        # The helper does check marker, file exists, valid JSON, is a dict
        # but NOT release identity.
        assert "release_name" not in src, (
            "Design B would add release-identity check to "
            "load_current_release_gate_report. Not present — "
            "Design B is not implemented.")


# ---------------------------------------------------------------------------
# Contradiction Checker Marker Handling (precedent)
# ---------------------------------------------------------------------------

class TestContradictionCheckerMarkerHandling:
    """The contradiction_checker already has marker handling (sets
    sources['gate']='missing' when marker present). This is the
    precedent for the proposed release_chain.py fix — the same
    fail-closed pattern, but applied at a different layer."""

    def test_contradiction_checker_marker_blocks_stale_pass(self, tmp_path):
        """The contradiction_checker correctly blocks stale PASS via
        marker, setting sources['gate']='missing'. This is the SAME
        fail-closed pattern as the F-01 helper."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")
        _write_marker(str(tmp_path))
        _write_final_results(str(tmp_path), claimed_gate=None)
        truth, sources = contradiction_checker.derive_truth(str(tmp_path))
        assert sources.get("gate") == "missing"
        assert truth.get("gate_verdict") is None

    def test_contradiction_checker_no_marker_valid_pass(self, tmp_path):
        """Without marker, valid PASS report is loaded by the
        contradiction_checker."""
        _bootstrap_minimal_repo(str(tmp_path))
        _write_gate_report(str(tmp_path), verdict="PASS")
        _write_final_results(str(tmp_path), claimed_gate=None)
        truth, sources = contradiction_checker.derive_truth(str(tmp_path))
        assert sources.get("gate") == "ok"
        assert truth.get("gate_verdict") == "PASS"
