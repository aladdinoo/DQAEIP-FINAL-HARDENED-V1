"""Observability Status Model (assurance rebaseline 2026-09-17, task §11).

Separates five previously conflatable monitoring dimensions into a
closed, machine-readable vocabulary. Each dimension is derived
INDEPENDENTLY from its own authoritative evidence and can never be
collapsed into a single ambiguous "PASS":

    VALIDATION_STATUS           execution correctness of the validation
                                runs (oracle agreement, determinism,
                                contract) — authoritative source: the
                                official final 3M validation result.
    DATA_QUALITY_SLA_STATUS     data-quality dimension scores against
                                SLA thresholds on the validated
                                dataset — authoritative source: the
                                engine monitoring artifact. This is a
                                property of the DATA, not of the
                                platform: the synthetic 3M dataset
                                contains planted defects, so
                                sub-threshold scores are expected
                                observations, NOT validation failures.
    RUNTIME_SAFETY_STATUS       measured runtime behavior (sockets,
                                process execution, out-of-repository
                                mutations) per run.
    EVIDENCE_INTEGRITY_STATUS   hash-addressed evidence coherence
                                (roots, chain, schemas, provenance).
    RELEASE_VERDICT            the final release-level verdict from
                                the truth model.

Fail-closed rules (mirroring the truth model):
- missing or malformed upstream evidence yields NOT_VERIFIED, never a
  guessed PASS;
- values are drawn from closed per-dimension vocabularies;
- the SLA dimension may be NOT_MET without invalidating
  VALIDATION_STATUS, and vice versa — the dimensions are independent
  by construction.
"""

__all__ = [
    "STATUS_DIMENSIONS",
    "VALIDATION_STATUSES",
    "SLA_STATUSES",
    "SAFETY_STATUSES",
    "INTEGRITY_STATUSES",
    "RELEASE_VERDICTS",
    "derive_sla_status",
    "derive_status_record",
    "validate_status_record",
    "render_status_summary",
]

STATUS_DIMENSIONS = (
    "VALIDATION_STATUS",
    "DATA_QUALITY_SLA_STATUS",
    "RUNTIME_SAFETY_STATUS",
    "EVIDENCE_INTEGRITY_STATUS",
    "RELEASE_VERDICT",
)

VALIDATION_STATUSES = ("PASS", "FAIL", "NOT_VERIFIED")
SLA_STATUSES = ("MET", "NOT_MET", "NOT_VERIFIED")
SAFETY_STATUSES = ("PASS", "FAIL", "NOT_VERIFIED")
INTEGRITY_STATUSES = ("PASS", "FAIL", "NOT_VERIFIED")
RELEASE_VERDICTS = (
    "PASS",
    "PASS_WITH_DOCUMENTED_LIMITATIONS",
    "NOT_VERIFIED",
    "FAIL",
)

_DIMENSION_VOCABULARIES = {
    "VALIDATION_STATUS": VALIDATION_STATUSES,
    "DATA_QUALITY_SLA_STATUS": SLA_STATUSES,
    "RUNTIME_SAFETY_STATUS": SAFETY_STATUSES,
    "EVIDENCE_INTEGRITY_STATUS": INTEGRITY_STATUSES,
    "RELEASE_VERDICT": RELEASE_VERDICTS,
}


def derive_sla_status(monitoring):
    """Derive the SLA dimension from an engine monitoring artifact.

    ``monitoring`` is the parsed monitoring.json of a run (or None).
    Returns (status, detail) where status is MET / NOT_MET /
    NOT_VERIFIED. Fail-closed: any structural problem is NOT_VERIFIED.
    """
    if not isinstance(monitoring, dict):
        return "NOT_VERIFIED", {"reason": "monitoring artifact missing "
                                          "or not an object"}
    sla_results = monitoring.get("sla_results")
    if not isinstance(sla_results, dict) or not sla_results:
        return "NOT_VERIFIED", {"reason": "sla_results missing/empty"}
    met = sorted(k for k, v in sla_results.items() if v is True)
    not_met = sorted(k for k, v in sla_results.items() if v is not True)
    status = "MET" if not not_met else "NOT_MET"
    detail = {
        "dimensions_total": len(sla_results),
        "dimensions_met": met,
        "dimensions_not_met": not_met,
        "overall_score": monitoring.get("overall_score"),
    }
    if not met and not not_met:
        return "NOT_VERIFIED", {"reason": "sla_results has no entries"}
    return status, detail


def _validation_from_3m(final_3m):
    if not isinstance(final_3m, dict):
        return "NOT_VERIFIED", "final 3M result missing/not an object"
    status = final_3m.get("final_status")
    if status == "PASS":
        # PASS requires the full fail-closed gate set to have passed;
        # the artifact's own gate model is authoritative.
        failures = final_3m.get("gate_failures")
        if failures:
            return "FAIL", "final_status PASS contradicted by gate_failures"
        return "PASS", "official 3M final_status PASS (fail-closed gates)"
    if status == "FAIL":
        return "FAIL", "official 3M final_status FAIL"
    return "NOT_VERIFIED", f"final_status {status!r} not in closed set"


def _safety_from_3m(final_3m):
    if not isinstance(final_3m, dict):
        return "NOT_VERIFIED", "final 3M result missing/not an object"
    safety = final_3m.get("safety_status")
    if safety == "PASS":
        return "PASS", "runtime safety measured PASS per official run"
    if safety == "FAIL":
        return "FAIL", "runtime safety measured FAIL"
    return "NOT_VERIFIED", f"safety_status {safety!r} not in closed set"


def _integrity_from_gate(gate):
    if not isinstance(gate, dict):
        return "NOT_VERIFIED", "release gate evidence missing/not an object"
    verdict = gate.get("overall_verdict")
    if verdict == "PASS":
        count = gate.get("gate_count")
        gates = gate.get("gates", [])
        statuses = {g.get("status") for g in gates}
        # self-consistency: the declared count must match the gate
        # list, and every listed gate must PASS (a truncated or
        # inconsistent PASS is a FAIL — fail closed). The gate count
        # itself is whatever the current gate version defines
        # (21 in the FINAL UPDATE round, 22 since the portable
        # release added the absolute-path gate).
        if count == len(gates) and statuses == {"PASS"}:
            return "PASS", f"{count}/{count} fail-closed gates PASS"
        return "FAIL", ("overall PASS inconsistent "
                        f"(count={count}, listed={len(gates)}, "
                        f"statuses={sorted(statuses)})")
    if verdict == "FAIL":
        return "FAIL", "release gate FAIL"
    return "NOT_VERIFIED", f"overall_verdict {verdict!r} not in closed set"


def _verdict_from_final_results(final_results):
    if not isinstance(final_results, dict):
        return "NOT_VERIFIED", "FINAL_RESULTS missing/not an object"
    v = final_results.get("final_release_status")
    if v in RELEASE_VERDICTS:
        return v, "FINAL_RESULTS.final_release_status (truth model)"
    return "NOT_VERIFIED", f"final_release_status {v!r} not in closed set"


def derive_status_record(final_3m=None, monitoring=None, gate=None,
                         final_results=None):
    """Derive the five-dimension status record from evidence inputs.

    Each parameter is the parsed authoritative artifact (or None).
    Missing/malformed inputs yield NOT_VERIFIED for their dimension —
    never a guessed value, never a borrowed value from another
    dimension.
    """
    validation, validation_note = _validation_from_3m(final_3m)
    sla, sla_detail = derive_sla_status(monitoring)
    safety, safety_note = _safety_from_3m(final_3m)
    integrity, integrity_note = _integrity_from_gate(gate)
    verdict, verdict_note = _verdict_from_final_results(final_results)
    return {
        "VALIDATION_STATUS": {
            "status": validation,
            "note": validation_note,
        },
        "DATA_QUALITY_SLA_STATUS": {
            "status": sla,
            "note": ("data-quality dimension scores on the validated "
                     "SYNTHETIC dataset (planted defects) — a property "
                     "of the data, NOT of validation correctness; SLA "
                     "PASS is not the same thing as validation PASS"),
            "detail": sla_detail,
        },
        "RUNTIME_SAFETY_STATUS": {
            "status": safety,
            "note": safety_note,
        },
        "EVIDENCE_INTEGRITY_STATUS": {
            "status": integrity,
            "note": integrity_note,
        },
        "RELEASE_VERDICT": {
            "status": verdict,
            "note": verdict_note,
        },
    }


def validate_status_record(record):
    """Validate structure + closed vocabularies; returns problem list."""
    problems = []
    if not isinstance(record, dict):
        return ["status record is not an object"]
    for dim in STATUS_DIMENSIONS:
        if dim not in record:
            problems.append(f"missing dimension {dim}")
            continue
        entry = record[dim]
        if not isinstance(entry, dict) or "status" not in entry:
            problems.append(f"dimension {dim} malformed (no status)")
            continue
        if entry["status"] not in _DIMENSION_VOCABULARIES[dim]:
            problems.append(
                f"dimension {dim} status {entry['status']!r} outside "
                f"closed vocabulary")
    extra = [k for k in record if k not in STATUS_DIMENSIONS
             and not k.startswith("_")]
    if extra:
        problems.append(f"unexpected extra dimensions: {extra}")
    return problems


def render_status_summary(record):
    """Render the one-line machine summary (one line per dimension)."""
    lines = []
    for dim in STATUS_DIMENSIONS:
        entry = (record or {}).get(dim, {})
        status = entry.get("status", "NOT_VERIFIED")
        lines.append(f"{dim}={status}")
    return "\n".join(lines)
