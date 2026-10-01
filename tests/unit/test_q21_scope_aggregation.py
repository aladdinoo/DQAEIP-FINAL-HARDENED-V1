"""Dedicated tests for the Q21 scope aggregation mechanism (Phase 2 remediation).

Contract under test:
    data_quality_platform/verification/scope_aggregator.py

These tests verify the aggregation mechanism and its wiring only. They do not
modify Q18, Q19, historical evidence artifacts, or golden fixtures.

Scenario map (Phase 2 contract):
    T1  all Q1-Q20 PASS                    -> PASS
    T2  Q18 PARTIAL, rest PASS             -> PARTIAL (explicitly != PASS)
    T3  one constituent FAIL               -> PARTIAL, counts["FAIL"] == 1
    T4  missing Q9                         -> FAIL (fail closed)
    T5  invalid status "PASSED"            -> FAIL
    T6  malformed result / non-mapping     -> FAIL
    T7  missing / whitespace-only evidence -> FAIL
    T8  determinism                        -> byte-identical serialization
    T9  wiring: real verification path     -> recorded Q21 == recomputed verdict
        (regression tripwire against reversion to a hardcoded Q21 PASS)
    T10 Q21/Q22 injected into scope window -> FAIL (unexpected IDs)
"""

import json
import os
import subprocess
import sys

import pytest

from data_quality_platform.verification.scope_aggregator import (
    ALLOWED_STATUSES,
    EXPECTED_IDS,
    Q21_SCOPE_POLICY,
    aggregate_scope,
)

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_result(qid, status="PASS", evidence=None, **overrides):
    """Harness-shaped result object (extra `description` field tolerated)."""
    result = {
        "question": qid,
        "description": f"{qid} description",
        "status": status,
        "evidence": f"{qid} evidence" if evidence is None else evidence,
    }
    result.update(overrides)
    return result


def full_scope(status_overrides=None):
    """Complete, structurally valid Q1-Q20 result set."""
    overrides = status_overrides or {}
    return [
        make_result(f"Q{number}", overrides.get(f"Q{number}", "PASS"))
        for number in range(1, 21)
    ]


def assert_valid_counts(aggregate):
    """counts always carries exactly the five allowed statuses (int values)."""
    assert tuple(aggregate.counts.keys()) == ALLOWED_STATUSES
    assert all(isinstance(v, int) for v in aggregate.counts.values())


# ---------------------------------------------------------------------------
# T1 — all Q1-Q20 PASS => PASS
# ---------------------------------------------------------------------------


def test_t1_all_pass_yields_pass():
    aggregate = aggregate_scope(full_scope())
    assert_valid_counts(aggregate)
    assert aggregate.verdict == "PASS"
    assert aggregate.all_pass is True
    assert aggregate.coverage_ok is True
    assert aggregate.counts["PASS"] == 20
    assert aggregate.total_expected == 20
    assert aggregate.total_found == 20
    assert aggregate.scope == "Q1-Q20"
    assert aggregate.missing == ()
    assert aggregate.non_pass_ids() == ()
    assert "PASS" in aggregate.evidence_summary()


# ---------------------------------------------------------------------------
# T2 — Q18 PARTIAL, remaining PASS => PARTIAL, explicitly not PASS
# ---------------------------------------------------------------------------


def test_t2_one_partial_yields_partial_never_pass():
    aggregate = aggregate_scope(full_scope({"Q18": "PARTIAL"}))
    assert_valid_counts(aggregate)
    assert aggregate.verdict == "PARTIAL"
    assert aggregate.verdict != "PASS"  # explicit contract assertion
    assert aggregate.all_pass is False
    assert aggregate.coverage_ok is True
    assert aggregate.counts["PASS"] == 19
    assert aggregate.counts["PARTIAL"] == 1
    assert aggregate.non_pass_ids() == (("Q18", "PARTIAL"),)
    assert "Q18=PARTIAL" in aggregate.verdict_basis
    assert "Q18=PARTIAL" in aggregate.evidence_summary()


# ---------------------------------------------------------------------------
# T3 — one constituent FAIL => PARTIAL with counts.FAIL == 1
# ---------------------------------------------------------------------------


def test_t3_one_fail_constituent_reports_partial_with_fail_count():
    aggregate = aggregate_scope(full_scope({"Q7": "FAIL"}))
    assert_valid_counts(aggregate)
    assert aggregate.verdict == "PARTIAL"
    assert aggregate.verdict != "PASS"
    assert aggregate.counts["FAIL"] == 1
    assert aggregate.counts["PASS"] == 19
    assert aggregate.all_pass is False
    assert aggregate.non_pass_ids() == (("Q7", "FAIL"),)
    assert "Q7=FAIL" in aggregate.evidence_summary()


# ---------------------------------------------------------------------------
# T4 — missing Q9 => FAIL (fail closed)
# ---------------------------------------------------------------------------


def test_t4_missing_question_fails_closed():
    results = [r for r in full_scope() if r["question"] != "Q9"]
    assert len(results) == 19
    aggregate = aggregate_scope(results)
    assert_valid_counts(aggregate)
    assert aggregate.verdict == "FAIL"
    assert aggregate.coverage_ok is False
    assert aggregate.all_pass is False
    assert aggregate.missing == ("Q9",)
    assert "missing=['Q9']" in aggregate.verdict_basis
    assert "missing=['Q9']" in aggregate.evidence_summary()


# ---------------------------------------------------------------------------
# T5 — invalid status "PASSED" => FAIL
# ---------------------------------------------------------------------------


def test_t5_invalid_status_fails_closed():
    aggregate = aggregate_scope(full_scope({"Q5": "PASSED"}))
    assert_valid_counts(aggregate)
    assert aggregate.verdict == "FAIL"
    assert aggregate.coverage_ok is False
    assert aggregate.invalid_status == ({"question": "Q5", "status": "PASSED"},)
    assert "invalid_status=1" in aggregate.verdict_basis
    # the invalid status must not be counted in any of the five buckets
    assert sum(aggregate.counts.values()) == 19


# ---------------------------------------------------------------------------
# T6 — malformed result / non-mapping / missing question => FAIL
# ---------------------------------------------------------------------------


def test_t6a_non_mapping_entry_fails_closed():
    results = full_scope()
    results.append("not-a-mapping")
    aggregate = aggregate_scope(results)
    assert aggregate.verdict == "FAIL"
    assert len(aggregate.malformed) == 1
    assert aggregate.malformed[0]["reason"] == "not_a_mapping"
    assert aggregate.malformed[0]["type"] == "str"


def test_t6b_missing_question_field_fails_closed():
    results = full_scope()
    del results[6]["question"]  # Q7 loses its identifier
    aggregate = aggregate_scope(results)
    assert aggregate.verdict == "FAIL"
    assert {"index": 6, "reason": "missing_field:question"} in aggregate.malformed
    assert aggregate.missing == ("Q7",)


def test_t6c_non_string_question_fails_closed():
    results = full_scope()
    results[2]["question"] = 42  # Q3 replaced by a non-string identifier
    aggregate = aggregate_scope(results)
    assert aggregate.verdict == "FAIL"
    assert aggregate.malformed[0]["reason"] == "invalid_question_identifier"
    assert aggregate.malformed[0]["value"] == "<non-string:int>"
    assert aggregate.missing == ("Q3",)


def test_t6d_leading_zero_identifier_is_malformed_not_an_id():
    results = full_scope()
    results[8]["question"] = "Q09"
    aggregate = aggregate_scope(results)
    assert aggregate.verdict == "FAIL"
    assert aggregate.malformed[0]["reason"] == "invalid_question_identifier"
    assert aggregate.missing == ("Q9",)


def test_t6e_non_iterable_input_fails_closed():
    aggregate = aggregate_scope(None)
    assert aggregate.verdict == "FAIL"
    assert aggregate.malformed[0]["reason"] == "results_not_iterable"


# ---------------------------------------------------------------------------
# T7 — missing / whitespace-only / non-string evidence => FAIL
# ---------------------------------------------------------------------------


def test_t7a_empty_evidence_fails_closed():
    results = full_scope()
    results[10]["evidence"] = ""
    aggregate = aggregate_scope(results)
    assert aggregate.verdict == "FAIL"
    assert aggregate.missing_evidence == ("Q11",)


def test_t7b_whitespace_evidence_fails_closed():
    results = full_scope()
    results[19]["evidence"] = "   \t\n "
    aggregate = aggregate_scope(results)
    assert aggregate.verdict == "FAIL"
    assert aggregate.missing_evidence == ("Q20",)


def test_t7c_non_string_evidence_fails_closed():
    results = full_scope()
    results[0]["evidence"] = None
    aggregate = aggregate_scope(results)
    assert aggregate.verdict == "FAIL"
    assert aggregate.missing_evidence == ("Q1",)


# ---------------------------------------------------------------------------
# T8 — determinism: same input => byte-identical serialization
# ---------------------------------------------------------------------------


def _assert_no_floats(node):
    if isinstance(node, float):
        raise AssertionError("float leaked into aggregate output")
    if isinstance(node, dict):
        for value in node.values():
            _assert_no_floats(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _assert_no_floats(value)


def test_t8_byte_identical_deterministic_output():
    input_results = full_scope({"Q18": "PARTIAL", "Q3": "BLOCKED"})
    snapshot_a = aggregate_scope(input_results)
    snapshot_b = aggregate_scope([dict(r) for r in input_results])

    assert snapshot_a.to_json() == snapshot_b.to_json()  # byte-identical
    assert json.loads(snapshot_a.to_json()) == snapshot_a.to_dict()
    assert snapshot_a.evidence_summary() == snapshot_b.evidence_summary()

    # canonical serialization is stable under re-serialization
    assert json.dumps(snapshot_a.to_dict(), separators=(",", ":")) == snapshot_a.to_json()

    _assert_no_floats(snapshot_a.to_dict())
    # no timestamps: no field may contain an ISO-like timestamp pattern
    blob = snapshot_a.to_json()
    assert "T00:" not in blob and "timestamp" not in blob


# ---------------------------------------------------------------------------
# T9 — wiring: real verification path, recomputed vs recorded Q21
# ---------------------------------------------------------------------------


def _run_real_verification(evidence_dir):
    """Run the actual `runner.cli verify` subcommand into an isolated dir."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "runner.cli",
            "verify",
            "--evidence-dir",
            str(evidence_dir),
        ],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=600,
    )
    assert result.returncode == 0, (
        f"verify exited {result.returncode}\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    report_path = os.path.join(str(evidence_dir), "verification_report.json")
    with open(report_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def test_t9_recorded_q21_equals_recomputed_aggregate(tmp_path):
    report = _run_real_verification(tmp_path)

    recorded = {item["question"]: item for item in report["results"]}
    q21_recorded = recorded["Q21"]

    # Scope inputs: the actual Q1-Q20 result objects produced by the run.
    scope_results = [
        report["results"][index] for index in range(0, 20)
    ]
    assert [r["question"] for r in scope_results] == [
        f"Q{number}" for number in range(1, 21)
    ]

    recomputed = aggregate_scope(scope_results)

    # Core invariant: the recorded Q21 verdict is the aggregator verdict.
    assert q21_recorded["status"] == recomputed.verdict

    # Anti-hardcoding tripwires: the evidence string must carry the
    # aggregation format (a reverted `return "PASS", "..."` fails here).
    assert q21_recorded["evidence"].startswith("verdict=")
    assert f"policy={Q21_SCOPE_POLICY}" in q21_recorded["evidence"]
    assert "counts:" in q21_recorded["evidence"]

    # Live-composition tripwire (V1 baseline): Q18 is PARTIAL by design
    # (production IAM not implemented), so the honest aggregate is PARTIAL.
    # If production IAM is ever actually implemented (Q18 -> PASS), this
    # expectation must be consciously updated — it must never be relaxed
    # silently.
    assert recorded["Q18"]["status"] == "PARTIAL"
    assert recomputed.verdict == "PARTIAL"
    assert q21_recorded["status"] == "PARTIAL"


# ---------------------------------------------------------------------------
# T10 — Q21/Q22 injected into the Q1-Q20 window => FAIL (unexpected IDs)
# ---------------------------------------------------------------------------


def test_t10_out_of_scope_ids_fail_closed():
    results = full_scope()
    results.append(make_result("Q21", "PASS"))
    results.append(make_result("Q22", "PASS"))
    aggregate = aggregate_scope(results)
    assert_valid_counts(aggregate)
    assert aggregate.verdict == "FAIL"
    assert aggregate.unexpected == ("Q21", "Q22")
    assert aggregate.total_found == 20  # in-scope distinct found unchanged
    assert "unexpected=['Q21', 'Q22']" in aggregate.verdict_basis


# ---------------------------------------------------------------------------
# Contract pins (auxiliary invariants)
# ---------------------------------------------------------------------------


def test_allowed_statuses_are_exactly_the_contract_five():
    assert ALLOWED_STATUSES == ("PASS", "PARTIAL", "FAIL", "BLOCKED", "NOT AUTHORIZED")


def test_expected_scope_is_exactly_q1_through_q20():
    assert EXPECTED_IDS == tuple(f"Q{number}" for number in range(1, 21))
    assert len(EXPECTED_IDS) == 20


def test_blocked_and_not_authorized_are_recognized_statuses():
    aggregate = aggregate_scope(
        full_scope({"Q4": "BLOCKED", "Q12": "NOT AUTHORIZED"})
    )
    assert aggregate.verdict == "PARTIAL"
    assert aggregate.counts["BLOCKED"] == 1
    assert aggregate.counts["NOT AUTHORIZED"] == 1
    assert ("Q4", "BLOCKED") in aggregate.non_pass_ids()
    assert ("Q12", "NOT AUTHORIZED") in aggregate.non_pass_ids()


def test_duplicate_in_scope_id_fails_closed():
    results = full_scope()
    results.append(make_result("Q2", "PASS"))
    aggregate = aggregate_scope(results)
    assert aggregate.verdict == "FAIL"
    assert aggregate.duplicates == ("Q2",)


def test_scope_aggregate_is_immutable():
    aggregate = aggregate_scope(full_scope())
    with pytest.raises(Exception):
        aggregate.verdict = "PASS"  # frozen dataclass must refuse mutation
