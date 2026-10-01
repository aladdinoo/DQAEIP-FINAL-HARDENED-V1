"""Deterministic scope aggregation for the Q21 "V1 scope assessment" check.

This module implements the Phase 2 remediation contract: it replaces the
historical hardcoded Q21 assertion (``runner/cli.py::q21`` used to return a
literal ``"PASS"``) with a real, fail-closed aggregation over the actual
Q1-Q20 verification results.

Authoritative requirement (verbatim, owner-unresolved semantics):

    requirement: "V1 scope assessment"
    expected:    "All Q1-Q20 verified"

The word "verified" is owner-unresolved between:

    A. all Q1-Q20 must be PASS
    B. all Q1-Q20 must be assessed with evidence-backed statuses

Until the owner adjudicates, the fail-safe policy below applies. It never
manufactures PASS under either reading.

Guarantees (Phase 2 contract):
    - pure function: no I/O, no database access, no ClickHouse access
    - deterministic: same input -> byte-identical serialized output
    - no timestamps, no random values, no floats
    - fails closed on any structural defect
    - PASS only when all 20 questions are explicitly PASS
    - never infers PASS from absence of errors
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------

#: Fail-safe aggregation policy (Phase 1 adjudication, accepted).
#: This is NOT a runtime/environment/user-controlled switch. If a future owner
#: adjudication changes the meaning of "verified", that is a separately
#: documented contract decision that must be implemented as a new revision of
#: this module, never as a configurable override.
Q21_SCOPE_POLICY = "UNIFORM_PASS_REQUIRED"

#: The only statuses the aggregation accepts (exact strings).
ALLOWED_STATUSES = ("PASS", "PARTIAL", "FAIL", "BLOCKED", "NOT AUTHORIZED")

#: The aggregated scope is exactly Q1 through Q20 (Q21 aggregates Q1-Q20; it
#: must never read itself or Q22 as evidence).
SCOPE_START = 1
SCOPE_END = 20
EXPECTED_IDS = tuple(f"Q{number}" for number in range(SCOPE_START, SCOPE_END + 1))

SCOPE_LABEL = f"Q{SCOPE_START}-Q{SCOPE_END}"

# Canonical question identifier: "Q" followed by a positive integer with no
# leading zeros. Anything else is a malformed identifier, not an ID.
_QUESTION_ID_PATTERN = re.compile(r"^Q([1-9][0-9]*)$")

_REQUIRED_FIELDS = ("question", "status", "evidence")


def _in_scope(question_id: str) -> bool:
    return SCOPE_START <= int(question_id[1:]) <= SCOPE_END


def _numeric_id(question_id: str) -> int:
    return int(question_id[1:])


def _sort_ids(ids) -> tuple:
    """Sort question IDs numerically (Q2 before Q10), deterministically."""
    return tuple(sorted(ids, key=_numeric_id))


def _status_descriptor(status: Any) -> str:
    """Deterministic, JSON-safe descriptor for an invalid status value."""
    if isinstance(status, str):
        return status
    return f"<non-string:{type(status).__name__}>"


def _zero_counts() -> dict:
    return {status: 0 for status in ALLOWED_STATUSES}


# ---------------------------------------------------------------------------
# Result object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScopeAggregate:
    """Immutable, JSON-serializable result of the Q1-Q20 scope aggregation.

    All sequence fields are stored as tuples (internal immutability);
    :meth:`to_dict` converts them to lists for JSON friendliness. Key order in
    :meth:`to_dict` is fixed, so serialization is byte-identical for identical
    inputs.
    """

    scope: str
    total_expected: int
    total_found: int
    missing: tuple
    duplicates: tuple
    unexpected: tuple
    invalid_status: tuple
    missing_evidence: tuple
    malformed: tuple
    counts: dict
    all_pass: bool
    coverage_ok: bool
    verdict: str
    verdict_basis: str

    # Derived, attached by the aggregator: {question_id: status} for in-scope
    # entries with a valid allowed status. Used for the non-PASS disclosure.
    _status_by_id: dict = None  # type: ignore[assignment]

    def to_dict(self) -> dict:
        """Fixed-key-order, JSON-serializable representation (contract item 6)."""
        return {
            "scope": self.scope,
            "total_expected": self.total_expected,
            "total_found": self.total_found,
            "missing": list(self.missing),
            "duplicates": list(self.duplicates),
            "unexpected": list(self.unexpected),
            "invalid_status": [dict(item) for item in self.invalid_status],
            "missing_evidence": list(self.missing_evidence),
            "malformed": [dict(item) for item in self.malformed],
            "counts": dict(self.counts),
            "all_pass": self.all_pass,
            "coverage_ok": self.coverage_ok,
            "verdict": self.verdict,
            "verdict_basis": self.verdict_basis,
        }

    def to_json(self) -> str:
        """Byte-identical canonical JSON serialization (contract item 14)."""
        return json.dumps(
            self.to_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=False
        )

    def non_pass_ids(self) -> tuple:
        """(question_id, status) pairs, numeric order, for in-scope non-PASS results."""
        status_map = self._status_by_id or {}
        return tuple(
            (qid, status)
            for qid, status in sorted(status_map.items(), key=lambda kv: _numeric_id(kv[0]))
            if status != "PASS"
        )

    def evidence_summary(self) -> str:
        """Deterministic one-line evidence string for the verification harness.

        Includes (CLI-wiring contract): verdict, status counts, non-PASS
        question IDs, and structural defects if any. Contains no timestamps
        and no floats.
        """
        counts_text = ", ".join(
            f"{status.replace(' ', '_')}={self.counts.get(status, 0)}"
            for status in ALLOWED_STATUSES
        )
        non_pass = self.non_pass_ids()
        if self.verdict == "FAIL" or not self.coverage_ok:
            non_pass_text = "n/a"
        elif non_pass:
            non_pass_text = ", ".join(f"{qid}={status}" for qid, status in non_pass)
        else:
            non_pass_text = "none"
        defects = self._defect_parts()
        defects_text = "; ".join(defects) if defects else "none"
        return (
            f"verdict={self.verdict}; "
            f"counts: {counts_text}; "
            f"non-PASS: {non_pass_text}; "
            f"defects: {defects_text}; "
            f"policy={Q21_SCOPE_POLICY}"
        )

    def _defect_parts(self) -> list:
        parts = []
        if self.missing:
            parts.append(f"missing={list(self.missing)}")
        if self.duplicates:
            parts.append(f"duplicates={list(self.duplicates)}")
        if self.unexpected:
            parts.append(f"unexpected={list(self.unexpected)}")
        if self.malformed:
            parts.append(f"malformed={len(self.malformed)}")
        if self.invalid_status:
            parts.append(f"invalid_status={len(self.invalid_status)}")
        if self.missing_evidence:
            parts.append(f"missing_evidence={list(self.missing_evidence)}")
        return parts


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def aggregate_scope(results) -> ScopeAggregate:
    """Aggregate actual Q1-Q20 verification results into a scope verdict.

    Pure and deterministic: no I/O, no clock, no randomness, no floats, no
    database or ClickHouse access. Fails closed on any structural defect.

    Parameters
    ----------
    results:
        Sequence of per-question result mappings, each expected to carry the
        required fields ``question`` (canonical ID ``Q1``..``Q20``), ``status``
        (one of :data:`ALLOWED_STATUSES`) and ``evidence`` (non-empty string
        after whitespace stripping). Extra fields (e.g. ``description``) are
        tolerated. Inputs that are not iterable produce a FAIL aggregate
        rather than raising.

    Returns
    -------
    ScopeAggregate
        Verdict rules (fail-closed contract):

        - any structural defect (missing / duplicate / unexpected ID,
          malformed entry, invalid status, missing or empty evidence)
          -> ``FAIL``
        - structure valid and all 20 statuses are ``PASS`` -> ``PASS``
        - otherwise -> ``PARTIAL`` (composition fully disclosed)

        PASS is never returned merely because all questions were executed.
    """
    # -- normalize input ------------------------------------------------------
    if results is None:
        entries = None
    else:
        try:
            entries = list(results)
        except TypeError:
            entries = None

    if entries is None:
        basis = (
            "FAIL: structural defects detected (input is not an iterable of results); "
            f"policy={Q21_SCOPE_POLICY}"
        )
        return ScopeAggregate(
            scope=SCOPE_LABEL,
            total_expected=len(EXPECTED_IDS),
            total_found=0,
            missing=EXPECTED_IDS,
            duplicates=(),
            unexpected=(),
            invalid_status=(),
            missing_evidence=(),
            malformed=({"index": None, "reason": "results_not_iterable"},),
            counts=_zero_counts(),
            all_pass=False,
            coverage_ok=False,
            verdict="FAIL",
            verdict_basis=basis,
            _status_by_id={},
        )

    seen: dict = {}
    status_by_id: dict = {}
    counts = _zero_counts()
    malformed: list = []
    invalid_status: list = []
    missing_evidence: list = []
    unexpected: list = []

    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            malformed.append(
                {"index": index, "reason": "not_a_mapping", "type": type(entry).__name__}
            )
            continue

        missing_field = next(
            (name for name in _REQUIRED_FIELDS if name not in entry), None
        )
        if missing_field is not None:
            malformed.append({"index": index, "reason": f"missing_field:{missing_field}"})
            continue

        question = entry["question"]
        if not isinstance(question, str) or not _QUESTION_ID_PATTERN.match(question):
            value = (
                question
                if isinstance(question, str)
                else f"<non-string:{type(question).__name__}>"
            )
            malformed.append(
                {"index": index, "reason": "invalid_question_identifier", "value": value}
            )
            continue

        if not _in_scope(question):
            unexpected.append(question)
            continue

        seen[question] = seen.get(question, 0) + 1

        status = entry["status"]
        if not isinstance(status, str) or status not in ALLOWED_STATUSES:
            invalid_status.append(
                {"question": question, "status": _status_descriptor(status)}
            )
        else:
            counts[status] += 1
            status_by_id[question] = status

        evidence = entry["evidence"]
        if not isinstance(evidence, str) or not evidence.strip():
            missing_evidence.append(question)

    missing = tuple(qid for qid in EXPECTED_IDS if qid not in seen)
    duplicates = _sort_ids(qid for qid, count in seen.items() if count > 1)
    unexpected_t = _sort_ids(unexpected)
    invalid_status_t = tuple(
        sorted(invalid_status, key=lambda item: _numeric_id(item["question"]))
    )
    missing_evidence_t = _sort_ids(set(missing_evidence))

    total_found = len(seen)
    defects_present = bool(
        missing
        or duplicates
        or unexpected_t
        or malformed
        or invalid_status_t
        or missing_evidence_t
    )
    coverage_ok = not defects_present
    all_pass = coverage_ok and counts.get("PASS", 0) == len(EXPECTED_IDS)

    if defects_present:
        verdict = "FAIL"
    elif all_pass:
        verdict = "PASS"
    else:
        verdict = "PARTIAL"

    # -- deterministic verdict basis ------------------------------------------
    defect_parts = []
    if missing:
        defect_parts.append(f"missing={list(missing)}")
    if duplicates:
        defect_parts.append(f"duplicates={list(duplicates)}")
    if unexpected_t:
        defect_parts.append(f"unexpected={list(unexpected_t)}")
    if malformed:
        defect_parts.append(f"malformed={len(malformed)}")
    if invalid_status_t:
        defect_parts.append(f"invalid_status={len(invalid_status_t)}")
    if missing_evidence_t:
        defect_parts.append(f"missing_evidence={list(missing_evidence_t)}")

    if verdict == "FAIL":
        basis = (
            f"FAIL: structural defects detected ({'; '.join(defect_parts)}); "
            f"policy={Q21_SCOPE_POLICY}"
        )
    elif verdict == "PASS":
        basis = (
            f"PASS: all {len(EXPECTED_IDS)} questions in scope {SCOPE_LABEL} are PASS "
            f"(policy={Q21_SCOPE_POLICY})"
        )
    else:
        non_pass_text = ", ".join(
            f"{qid}={status}"
            for qid, status in sorted(
                status_by_id.items(), key=lambda kv: _numeric_id(kv[0])
            )
            if status != "PASS"
        )
        basis = (
            f"PARTIAL: all {len(EXPECTED_IDS)} questions in scope {SCOPE_LABEL} assessed "
            f"with allowed statuses and evidence; non-PASS: {non_pass_text} "
            f"(policy={Q21_SCOPE_POLICY})"
        )

    return ScopeAggregate(
        scope=SCOPE_LABEL,
        total_expected=len(EXPECTED_IDS),
        total_found=total_found,
        missing=missing,
        duplicates=duplicates,
        unexpected=unexpected_t,
        invalid_status=invalid_status_t,
        missing_evidence=missing_evidence_t,
        malformed=tuple(malformed),
        counts=counts,
        all_pass=all_pass,
        coverage_ok=coverage_ok,
        verdict=verdict,
        verdict_basis=basis,
        _status_by_id=dict(status_by_id),
    )
