"""Two-Level Truth Model (DQAEIP rebuild Phase 13).

Separates FACT from INTERPRETATION in all release-facing claims.

FACT: a measured, machine-derived value from an actual evidence
artifact (e.g. 51,200,000 comparisons, 0 mismatches).

INTERPRETATION: the verification status attached to a fact (e.g.
VERIFIED_LOCALLY). An interpretation can NEVER be turned into a
fabricated measurement, and NOT_VERIFIED can NEVER be reported as
PASS.

Allowed status vocabulary (closed set — unknown statuses fail closed):

    VERIFIED_LOCALLY   executed and measured in this repository
    COMPANY_SUPPLIED   provided by the company; not independently
                       reproduced
    HISTORICAL         preserved evidence of earlier executions; not
                       re-executed now
    NOT_EXECUTED       explicitly not executed in this release
    NOT_AUTHORIZED     explicitly not authorized (e.g. the un-named
                       future enhancement; see the limitation registry
                       LIM-006 for the governed statement)
    REVIEW_REQUIRED    known divergence or ambiguity; pinned, not
                       silently decided
    NOT_VERIFIED       cannot be established from evidence; must never
                       become PASS

Also defines the three-level final-verdict vocabulary:
    PASS / PASS_WITH_DOCUMENTED_LIMITATIONS / NOT_VERIFIED / FAIL
"""

__all__ = [
    "EVIDENCE_STATUSES",
    "FINAL_VERDICTS",
    "VERDICT_POLICY",
    "validate_status",
    "validate_final_verdict",
    "classify_claim",
    "fact",
    "interpretation",
    "worst_status",
    "derive_final_verdict",
]

EVIDENCE_STATUSES = (
    "VERIFIED_LOCALLY",
    "COMPANY_SUPPLIED",
    "HISTORICAL",
    "NOT_EXECUTED",
    "NOT_AUTHORIZED",
    "REVIEW_REQUIRED",
    "NOT_VERIFIED",
)

FINAL_VERDICTS = (
    "PASS",
    "PASS_WITH_DOCUMENTED_LIMITATIONS",
    "NOT_VERIFIED",
    "FAIL",
)

VERDICT_POLICY = {
    "PASS": "every required verification passed with no documented "
            "limitations in scope",
    "PASS_WITH_DOCUMENTED_LIMITATIONS": (
        "all required verifications passed AND a non-empty, structured "
        "limitation registry documents explicitly non-blocking limitations "
        "under the stated release policy"
    ),
    "NOT_VERIFIED": (
        "one or more required claims cannot be established from "
        "evidence; never reported as PASS"
    ),
    "FAIL": "a blocking verification failed",
}


class TruthModelError(ValueError):
    """Raised when a status/verdict value is outside the closed set."""


def validate_status(status):
    if status not in EVIDENCE_STATUSES:
        raise TruthModelError(
            f"unknown evidence status {status!r}; allowed: "
            f"{', '.join(EVIDENCE_STATUSES)} (fail closed)")
    return status


def validate_final_verdict(verdict):
    if verdict not in FINAL_VERDICTS:
        raise TruthModelError(
            f"unknown final verdict {verdict!r}; allowed: "
            f"{', '.join(FINAL_VERDICTS)}")
    return verdict


def fact(value, source_artifact=None, source_sha256=None, derivation=None):
    """Build a FACT record (measurement)."""
    return {
        "level": "FACT",
        "value": value,
        "source_artifact": source_artifact,
        "source_sha256": source_sha256,
        "derivation": derivation or "direct",
    }


def interpretation(status, basis=None):
    """Build an INTERPRETATION record (verification status)."""
    return {
        "level": "INTERPRETATION",
        "status": validate_status(status),
        "basis": basis,
    }


def classify_claim(name, fact_record, interpretation_record):
    """Combine a FACT and its INTERPRETATION into a claim record."""
    return {
        "claim": name,
        "fact": fact_record,
        "interpretation": interpretation_record,
        "consistent": not (
            fact_record.get("value") is None
            and interpretation_record.get("status") == "VERIFIED_LOCALLY"
        ),
    }


def worst_status(statuses):
    """Order statuses by trust-worthiness; return the weakest.

    Weakest to strongest: NOT_VERIFIED < REVIEW_REQUIRED < NOT_EXECUTED
    < NOT_AUTHORIZED < HISTORICAL < COMPANY_SUPPLIED < VERIFIED_LOCALLY.
    """
    order = [
        "NOT_VERIFIED", "REVIEW_REQUIRED", "NOT_EXECUTED",
        "NOT_AUTHORIZED", "HISTORICAL", "COMPANY_SUPPLIED",
        "VERIFIED_LOCALLY",
    ]
    validated = [validate_status(s) for s in statuses] or ["NOT_VERIFIED"]
    return min(validated, key=order.index)


def derive_final_verdict(required_ok, blocking_failures, limitations):
    """Mechanically derive the final verdict from release policy.

    required_ok: iterable of (name, established) for every REQUIRED
                 claim — established means derivable from evidence.
    blocking_failures: non-empty means a blocking verification failed.
    limitations: the structured limitation registry entries.
    """
    if blocking_failures:
        return "FAIL"
    unestablished = [name for name, ok in required_ok if not ok]
    if unestablished:
        return "NOT_VERIFIED"
    blocking = [l for l in limitations if l.get("blocks_release")]
    if blocking:
        return "FAIL"
    if limitations:
        return "PASS_WITH_DOCUMENTED_LIMITATIONS"
    return "PASS"
