"""DQAEIP assurance-layer tests: observability status model
(assurance rebaseline 2026-09-17, task §11).

Verifies the five-dimension status separation is structural,
fail-closed, and never collapses independent dimensions into one
ambiguous "PASS":
    VALIDATION_STATUS / DATA_QUALITY_SLA_STATUS /
    RUNTIME_SAFETY_STATUS / EVIDENCE_INTEGRITY_STATUS /
    RELEASE_VERDICT
"""

import copy
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance import status_model


def _final_3m_pass():
    return {
        "final_status": "PASS",
        "gate_failures": [],
        "safety_status": "PASS",
        "runs": {"run_1": {}, "run_2": {}},
    }


def _monitoring_sla_not_met():
    return {
        "scores": {"completeness": 0.86, "uniqueness": 1.0},
        "thresholds": {"completeness": 0.95, "uniqueness": 0.95},
        "sla_results": {"completeness": False, "uniqueness": True},
        "overall_score": 0.87,
    }


def _gate_pass_21():
    return {
        "overall_verdict": "PASS",
        "gate_count": 21,
        "gates": [{"gate": f"g{i}", "status": "PASS"} for i in range(21)],
    }


def _final_results_pwdl():
    return {"final_release_status": "PASS_WITH_DOCUMENTED_LIMITATIONS"}


class TestStatusDimensions:
    def test_five_dimensions_present_and_distinct(self):
        record = status_model.derive_status_record(
            final_3m=_final_3m_pass(),
            monitoring=_monitoring_sla_not_met(),
            gate=_gate_pass_21(),
            final_results=_final_results_pwdl())
        assert set(record) == set(status_model.STATUS_DIMENSIONS)
        assert len(status_model.STATUS_DIMENSIONS) == 5

    def test_validation_pass_independent_of_sla_not_met(self):
        record = status_model.derive_status_record(
            final_3m=_final_3m_pass(),
            monitoring=_monitoring_sla_not_met(),
            gate=_gate_pass_21(),
            final_results=_final_results_pwdl())
        assert record["VALIDATION_STATUS"]["status"] == "PASS"
        assert record["DATA_QUALITY_SLA_STATUS"]["status"] == "NOT_MET"
        # the SLA dimension must NOT drag validation down nor borrow
        # its PASS — independence is structural
        assert record["DATA_QUALITY_SLA_STATUS"]["status"] != \
            record["VALIDATION_STATUS"]["status"]

    def test_sla_not_met_does_not_fail_release_verdict(self):
        record = status_model.derive_status_record(
            final_3m=_final_3m_pass(),
            monitoring=_monitoring_sla_not_met(),
            gate=_gate_pass_21(),
            final_results=_final_results_pwdl())
        assert record["RELEASE_VERDICT"]["status"] == \
            "PASS_WITH_DOCUMENTED_LIMITATIONS"

    def test_all_sla_dimensions_met(self):
        monitoring = {
            "sla_results": {"completeness": True, "uniqueness": True},
            "overall_score": 1.0,
        }
        status, detail = status_model.derive_sla_status(monitoring)
        assert status == "MET"
        assert detail["dimensions_not_met"] == []

    def test_sla_detail_lists_not_met_dimensions(self):
        status, detail = status_model.derive_sla_status(
            _monitoring_sla_not_met())
        assert status == "NOT_MET"
        assert detail["dimensions_not_met"] == ["completeness"]
        assert detail["dimensions_met"] == ["uniqueness"]
        assert detail["overall_score"] == 0.87


class TestFailClosed:
    def test_missing_everything_is_all_not_verified(self):
        record = status_model.derive_status_record()
        for dim in status_model.STATUS_DIMENSIONS:
            assert record[dim]["status"] == "NOT_VERIFIED"

    def test_missing_evidence_never_passes(self):
        # no gate evidence at all -> integrity NOT_VERIFIED (not PASS,
        # not a borrowed value)
        record = status_model.derive_status_record(
            final_3m=_final_3m_pass(),
            monitoring=_monitoring_sla_not_met(),
            gate=None,
            final_results=_final_results_pwdl())
        assert record["EVIDENCE_INTEGRITY_STATUS"]["status"] == \
            "NOT_VERIFIED"

    def test_malformed_evidence_is_not_verified(self):
        record = status_model.derive_status_record(
            final_3m="not-a-dict",
            monitoring=42,
            gate=[],
            final_results=None)
        for dim in status_model.STATUS_DIMENSIONS:
            assert record[dim]["status"] == "NOT_VERIFIED"

    def test_validation_fail_propagates(self):
        f3m = _final_3m_pass()
        f3m["final_status"] = "FAIL"
        record = status_model.derive_status_record(final_3m=f3m)
        assert record["VALIDATION_STATUS"]["status"] == "FAIL"

    def test_pass_contradicted_by_gate_failures_is_fail(self):
        f3m = _final_3m_pass()
        f3m["gate_failures"] = ["some gate"]
        record = status_model.derive_status_record(final_3m=f3m)
        assert record["VALIDATION_STATUS"]["status"] == "FAIL"

    def test_gate_overall_pass_with_wrong_count_is_fail(self):
        gate = _gate_pass_21()
        gate["gate_count"] = 16  # superseded model
        record = status_model.derive_status_record(gate=gate)
        assert record["EVIDENCE_INTEGRITY_STATUS"]["status"] == "FAIL"

    def test_gate_with_one_failing_gate_is_fail(self):
        gate = _gate_pass_21()
        gate["gates"][7]["status"] = "FAIL"
        record = status_model.derive_status_record(gate=gate)
        assert record["EVIDENCE_INTEGRITY_STATUS"]["status"] == "FAIL"

    def test_unknown_verdict_rejected(self):
        record = status_model.derive_status_record(
            final_results={"final_release_status": "ALL_GOOD"})
        assert record["RELEASE_VERDICT"]["status"] == "NOT_VERIFIED"

    def test_empty_sla_results_is_not_verified(self):
        status, _ = status_model.derive_sla_status(
            {"sla_results": {}})
        assert status == "NOT_VERIFIED"


class TestValidation:
    def test_validate_ok_record(self):
        record = status_model.derive_status_record(
            final_3m=_final_3m_pass(),
            monitoring=_monitoring_sla_not_met(),
            gate=_gate_pass_21(),
            final_results=_final_results_pwdl())
        assert status_model.validate_status_record(record) == []

    def test_validate_missing_dimension(self):
        record = status_model.derive_status_record()
        del record["RUNTIME_SAFETY_STATUS"]
        problems = status_model.validate_status_record(record)
        assert any("RUNTIME_SAFETY_STATUS" in p for p in problems)

    def test_validate_out_of_vocabulary_status(self):
        record = status_model.derive_status_record()
        record["VALIDATION_STATUS"]["status"] = "PROBABLY_FINE"
        problems = status_model.validate_status_record(record)
        assert any("closed vocabulary" in p for p in problems)

    def test_validate_extra_dimension_rejected(self):
        record = status_model.derive_status_record()
        record["EXTRA_STATUS"] = {"status": "PASS"}
        problems = status_model.validate_status_record(record)
        assert any("extra dimensions" in p for p in problems)

    def test_validate_non_object_rejected(self):
        assert status_model.validate_status_record(None)

    def test_render_summary_five_lines(self):
        record = status_model.derive_status_record(
            final_3m=_final_3m_pass(),
            monitoring=_monitoring_sla_not_met(),
            gate=_gate_pass_21(),
            final_results=_final_results_pwdl())
        lines = status_model.render_status_summary(record).splitlines()
        assert len(lines) == 5
        assert lines[0] == "VALIDATION_STATUS=PASS"
        assert lines[1] == "DATA_QUALITY_SLA_STATUS=NOT_MET"
        assert lines[4] == \
            "RELEASE_VERDICT=PASS_WITH_DOCUMENTED_LIMITATIONS"


class TestLiveEvidence:
    """The live record must carry the honest five-way separation."""

    def test_live_observability_record_is_valid_and_separated(self):
        path = os.path.join(REPO_ROOT, "evidence", "release",
                            "observability_status.json")
        if not os.path.isfile(path):
            pytest.skip("observability record not generated yet "
                        "(built by scripts/build_observability_status.py)")
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        dims = doc["status_dimensions"]
        assert status_model.validate_status_record(dims) == []
        assert dims["VALIDATION_STATUS"]["status"] == "PASS"
        assert dims["DATA_QUALITY_SLA_STATUS"]["status"] in ("MET",
                                                             "NOT_MET")
        assert dims["RUNTIME_SAFETY_STATUS"]["status"] == "PASS"
        # EVIDENCE_INTEGRITY and RELEASE_VERDICT must match the LIVE
        # evidence EXACTLY — in BOTH directions:
        #   - a record claiming PASS while the live gate evidence
        #     fails (or is missing) is STALE -> caught;
        #   - a record showing FAIL/pending while the live evidence
        #     passes is LAGGING -> caught.
        # (The previous formulation asserted the terminal state
        # unconditionally, which made the FIRST run of a new gate
        # version mathematically impossible: the record can only say
        # PASS after a passing gate run exists, and a passing gate run
        # required the record to already say PASS. The evidence-match
        # formulation is strictly stronger against staleness while
        # allowing an honest mid-transition record.)
        gate_path = os.path.join(REPO_ROOT, "evidence", "release_gate",
                                 "final_release_gate.json")
        if os.path.isfile(gate_path):
            with open(gate_path, encoding="utf-8") as f:
                gate = json.load(f)
            expected_integrity, _ = status_model._integrity_from_gate(gate)
            live_gate_verdict = gate.get("overall_verdict")
        else:
            # Gate-round ledger discipline (2026-09-19 hardened
            # release): after a FAIL round is ledgered (full content
            # embedded in evidence/FINAL_HARDENED_RELEASE_2026-09-19/
            # release_gate/gate_rounds.json) the live gate file is
            # intentionally purged so the next round starts without
            # stale self-referential contradiction samples. Between
            # rounds (no live gate file) the honest expected status is
            # the fail-closed NOT_VERIFIED — exactly what
            # status_model derives for a missing gate artifact. A
            # record claiming anything else with no live gate file is
            # STALE -> still caught. Historical FAIL rounds live ONLY
            # in the ledger and are never current contradiction inputs.
            gate = None
            expected_integrity = "NOT_VERIFIED"
            live_gate_verdict = None
        assert dims["EVIDENCE_INTEGRITY_STATUS"]["status"] == \
            expected_integrity, {
                "record": dims["EVIDENCE_INTEGRITY_STATUS"],
                "live_gate_verdict": live_gate_verdict,
            }
        with open(os.path.join(REPO_ROOT, "FINAL_RESULTS.json"),
                  encoding="utf-8") as f:
            fr = json.load(f)
        verdict = fr.get("final_release_status")
        expected_verdict = verdict if verdict in \
            status_model.RELEASE_VERDICTS else "NOT_VERIFIED"
        assert dims["RELEASE_VERDICT"]["status"] == expected_verdict, {
            "record": dims["RELEASE_VERDICT"],
            "live_final_release_status": verdict,
        }
        # terminal no-lagging guarantee: when the live gate evidence
        # shows a fully passing CURRENT run, the release verdict MUST
        # be established (PASS_WITH_DOCUMENTED_LIMITATIONS) and the
        # record MUST show both dimensions PASS — never lagging.
        if expected_integrity == "PASS":
            assert expected_verdict == \
                "PASS_WITH_DOCUMENTED_LIMITATIONS"
            assert dims["EVIDENCE_INTEGRITY_STATUS"]["status"] == "PASS"
            assert dims["RELEASE_VERDICT"]["status"] == \
                "PASS_WITH_DOCUMENTED_LIMITATIONS"
