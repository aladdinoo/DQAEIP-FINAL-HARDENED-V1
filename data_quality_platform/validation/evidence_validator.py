"""Evidence Validator (DQAVP hardening, Section 4).

A fail-closed validation layer for engine-produced evidence directories.
It proves that a recorded run's evidence is INTERNALLY consistent before
anyone is allowed to interpret it as a PASS:

- required evidence files exist and are valid JSON
- manifest schema and required fields are present
- hashes have a valid format (64-char lowercase hex)
- run identifiers are consistent across manifest / lineage / audit
- input/output metadata is internally consistent (row counts, columns)
- row counts agree across manifest, audit, and lineage
- flag counts agree between manifest and audit
- verdicts agree (no success manifest alongside failure records)
- no contradictory status exists anywhere
- lineage serialization is valid (structured dicts, no repr strings)
- evidence references valid artifacts (paths exist; file hashes recompute)

Fail-closed contract:
- ANY missing file, malformed JSON, schema violation, cross-artifact
  disagreement, or contradictory status makes the report invalid.
- Missing evidence is NEVER treated as a pass; a partial scan is a
  partial scan and is reported as such (``checks_performed``).
- The validator is read-only: it never modifies evidence.
"""

import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional

from data_quality_platform.contracts import (
    FLAG_COLUMNS, SOURCE_COLUMNS, TOTAL_OUTPUT_COLUMNS,
)

__all__ = [
    "EvidenceIssue",
    "EvidenceValidationError",
    "validate_evidence_dir",
]

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_LINEAGE_ROW_FIELDS = (
    "run_id", "row_number", "rule_id", "rule_version", "flag_value",
    "row_hash", "timestamp",
)
_REPR_MARKERS = (
    "RowLineageRecord object at",
    "LineageRecord object at",
    "object at 0x",
)


class EvidenceIssue:
    def __init__(self, code: str, message: str, artifact: str = ""):
        self.code = code
        self.message = message
        self.artifact = artifact

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message,
                "artifact": self.artifact}

    def __repr__(self) -> str:  # pragma: no cover - diagnostics
        art = f" [{self.artifact}]" if self.artifact else ""
        return f"[{self.code}]{art}: {self.message}"


class EvidenceValidationError(Exception):
    """Raised by strict callers when evidence is invalid."""

    def __init__(self, issues: List[EvidenceIssue], report: Dict[str, Any]):
        self.issues = issues
        self.report = report
        super().__init__(
            "invalid evidence: " + "; ".join(repr(i) for i in issues[:10]))


def _load_json(path: str, issues: List[EvidenceIssue]):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        issues.append(EvidenceIssue(
            "json_invalid", f"not valid JSON: {exc}", os.path.basename(path)))
    except OSError as exc:
        issues.append(EvidenceIssue(
            "file_unreadable", f"cannot read: {exc}",
            os.path.basename(path)))
    except UnicodeDecodeError as exc:
        issues.append(EvidenceIssue(
            "encoding_invalid", f"not valid UTF-8: {exc}",
            os.path.basename(path)))
    return None


def _is_hex64(value: Any) -> bool:
    return isinstance(value, str) and bool(_HEX64.match(value))


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_evidence_dir(
    evidence_dir: str,
    *,
    expected_rule_ids: Optional[List[str]] = None,
    expect_success: bool = True,
) -> Dict[str, Any]:
    """Validate an engine evidence directory. Read-only, fail closed.

    Returns a report dict:
        {"valid": bool, "issues": [...], "checks_performed": [...],
         "run_id": str|None, "details": {...}}
    ``valid`` is True if and only if zero issues were found AND the
    directory contained the required complete evidence set.
    """
    issues: List[EvidenceIssue] = []
    checks: List[str] = []
    details: Dict[str, Any] = {"evidence_dir_present": False}
    report: Dict[str, Any] = {
        "valid": False, "issues": [], "checks_performed": checks,
        "run_id": None, "details": details,
    }
    rule_ids = list(expected_rule_ids or FLAG_COLUMNS)

    if not evidence_dir or not os.path.isdir(evidence_dir):
        issues.append(EvidenceIssue(
            "evidence_dir_missing",
            f"evidence directory does not exist: {evidence_dir!r}"))
        report["issues"] = [i.to_dict() for i in issues]
        return report
    details["evidence_dir_present"] = True

    required = ["manifest.json", "lineage.json", "audit.json"]
    optional = ["monitoring.json", "alerts.json"]
    for name in required:
        if not os.path.isfile(os.path.join(evidence_dir, name)):
            issues.append(EvidenceIssue(
                "required_file_missing",
                f"required evidence file absent: {name}", name))
    checks.append("required_files_exist")

    # ---- load artifacts ----------------------------------------------------
    manifest = _load_json(os.path.join(evidence_dir, "manifest.json"), issues)
    lineage = _load_json(os.path.join(evidence_dir, "lineage.json"), issues)
    audit = _load_json(os.path.join(evidence_dir, "audit.json"), issues)
    monitoring = _load_json(os.path.join(evidence_dir, "monitoring.json"),
                            issues) if os.path.isfile(
        os.path.join(evidence_dir, "monitoring.json")) else None
    alerts = _load_json(os.path.join(evidence_dir, "alerts.json"),
                        issues) if os.path.isfile(
        os.path.join(evidence_dir, "alerts.json")) else None
    checks.append("json_parseable")

    # ---- manifest schema -----------------------------------------------------
    if manifest is not None:
        checks.append("manifest_schema")
        for field in ("manifest_type", "run_id", "timestamp",
                      "source_row_count", "output_row_count", "schema_hash",
                      "rule_hashes", "sql_hashes", "flag_counts",
                      "reconciliation", "safety_invariants",
                      "generated_files"):
            if field not in manifest:
                issues.append(EvidenceIssue(
                    "manifest_field_missing",
                    f"manifest missing required field: {field}",
                    "manifest.json"))
        if manifest.get("manifest_type") not in ("success", "failure"):
            issues.append(EvidenceIssue(
                "manifest_type_invalid",
                f"manifest_type must be 'success' or 'failure', got "
                f"{manifest.get('manifest_type')!r}", "manifest.json"))
        if expect_success and manifest.get("manifest_type") != "success":
            issues.append(EvidenceIssue(
                "manifest_not_success",
                f"expected a success manifest, got "
                f"{manifest.get('manifest_type')!r}", "manifest.json"))
        if not _is_hex64(manifest.get("schema_hash")):
            issues.append(EvidenceIssue(
                "hash_format_invalid",
                "schema_hash is not 64-char lowercase hex",
                "manifest.json"))
        rh = manifest.get("rule_hashes")
        if not isinstance(rh, dict) or sorted(rh) != sorted(rule_ids):
            issues.append(EvidenceIssue(
                "rule_hashes_incomplete",
                f"rule_hashes keys {sorted(rh) if isinstance(rh, dict) else rh}"
                f" != required {sorted(rule_ids)}", "manifest.json"))
        elif not all(_is_hex64(v) for v in rh.values()):
            issues.append(EvidenceIssue(
                "hash_format_invalid",
                "one or more rule_hashes values are not 64-char hex",
                "manifest.json"))
        fc = manifest.get("flag_counts")
        if not isinstance(fc, dict) or sorted(fc) != sorted(rule_ids):
            issues.append(EvidenceIssue(
                "flag_counts_incomplete",
                "flag_counts must contain exactly the 8 rule ids",
                "manifest.json"))
        elif not all(_is_int(v) and v >= 0 for v in fc.values()):
            issues.append(EvidenceIssue(
                "flag_counts_invalid",
                "flag_counts values must be non-negative integers",
                "manifest.json"))
        for count_field in ("source_row_count", "output_row_count"):
            v = manifest.get(count_field)
            if not _is_int(v) or v < 0:
                issues.append(EvidenceIssue(
                    "row_count_invalid",
                    f"{count_field} must be a non-negative integer, got {v!r}",
                    "manifest.json"))
        rec = manifest.get("reconciliation")
        if not isinstance(rec, dict) or "passed" not in rec:
            issues.append(EvidenceIssue(
                "reconciliation_missing",
                "reconciliation.passed must be recorded", "manifest.json"))
        si = manifest.get("safety_invariants")
        if not isinstance(si, list) or not si:
            issues.append(EvidenceIssue(
                "safety_invariants_missing",
                "safety_invariants must be a non-empty list",
                "manifest.json"))

    # ---- run id consistency --------------------------------------------------
    if manifest is not None:
        checks.append("run_id_consistency")
        run_id = manifest.get("run_id")
        report["run_id"] = run_id
        if not isinstance(run_id, str) or not run_id:
            issues.append(EvidenceIssue(
                "run_id_invalid", "manifest.run_id missing/empty",
                "manifest.json"))
        else:
            if lineage is not None and lineage.get("run_id") != run_id:
                issues.append(EvidenceIssue(
                    "run_id_mismatch",
                    f"lineage.run_id {lineage.get('run_id')!r} != "
                    f"manifest.run_id {run_id!r}", "lineage.json"))
            if audit is not None and audit.get("run_id") != run_id:
                issues.append(EvidenceIssue(
                    "run_id_mismatch",
                    f"audit.run_id {audit.get('run_id')!r} != "
                    f"manifest.run_id {run_id!r}", "audit.json"))

    # ---- row count agreement --------------------------------------------------
    if manifest is not None:
        checks.append("row_count_agreement")
        src = manifest.get("source_row_count")
        out = manifest.get("output_row_count")
        if _is_int(src) and _is_int(out) and src != out:
            issues.append(EvidenceIssue(
                "row_count_mismatch",
                f"source_row_count {src} != output_row_count {out}",
                "manifest.json"))
        if audit is not None:
            completed = [e for e in audit.get("events", [])
                         if isinstance(e, dict)
                         and e.get("event_type") == "validation_completed"]
            if not completed:
                issues.append(EvidenceIssue(
                    "audit_event_missing",
                    "audit has no validation_completed event", "audit.json"))
            else:
                det = completed[-1].get("details") or {}
                for key, val in (("input_rows", src),
                                 ("output_rows", out)):
                    a = det.get(key)
                    if _is_int(val) and _is_int(a) and a != val:
                        issues.append(EvidenceIssue(
                            "row_count_mismatch",
                            f"audit {key}={a} != manifest {val}",
                            "audit.json"))
        if lineage is not None:
            run_records = lineage.get("run_records") or []
            if run_records:
                last = run_records[-1]
                lr = last.get("row_count") if isinstance(last, dict) else None
                if _is_int(src) and _is_int(lr) and lr != src:
                    issues.append(EvidenceIssue(
                        "row_count_mismatch",
                        f"lineage final row_count {lr} != manifest "
                        f"source_row_count {src}", "lineage.json"))

    # ---- flag count agreement --------------------------------------------------
    if manifest is not None and audit is not None:
        checks.append("flag_count_agreement")
        completed = [e for e in audit.get("events", [])
                     if isinstance(e, dict)
                     and e.get("event_type") == "validation_completed"]
        if completed:
            a_fc = (completed[-1].get("details") or {}).get("flag_counts") or {}
            m_fc = manifest.get("flag_counts") or {}
            if sorted(a_fc) != sorted(m_fc) or any(
                    a_fc.get(k) != m_fc.get(k) for k in m_fc):
                issues.append(EvidenceIssue(
                    "flag_count_mismatch",
                    "audit validation_completed flag_counts != manifest "
                    "flag_counts", "audit.json"))
        src = manifest.get("source_row_count")
        m_fc = manifest.get("flag_counts") or {}
        if _is_int(src) and m_fc:
            total_flags = sum(v for v in m_fc.values()
                              if isinstance(v, int))
            if total_flags > src * len(rule_ids):
                issues.append(EvidenceIssue(
                    "flag_count_impossible",
                    f"total flags {total_flags} exceeds rows x rules "
                    f"({src} x {len(rule_ids)})", "manifest.json"))

    # ---- verdict agreement / contradictions ------------------------------------
    if manifest is not None:
        checks.append("verdict_agreement")
        if audit is not None:
            failed_events = [e for e in audit.get("events", [])
                             if isinstance(e, dict)
                             and e.get("event_type") == "run_failed"]
            if manifest.get("manifest_type") == "success" and failed_events:
                issues.append(EvidenceIssue(
                    "contradictory_status",
                    "success manifest coexists with audit run_failed event",
                    "audit.json"))
        if alerts is not None:
            # alerts.json persists a top-level LIST of alert dicts.
            alert_list = alerts if isinstance(alerts, list) else (
                alerts.get("alerts") if isinstance(alerts, dict) else [])
            alert_list = alert_list if isinstance(alert_list, list) else []
            rec_fail_alerts = [a for a in alert_list
                               if isinstance(a, dict)
                               and "reconciliation" in str(
                                   a.get("type", ""))]
            rec = manifest.get("reconciliation") or {}
            if rec.get("passed") is True and rec_fail_alerts:
                issues.append(EvidenceIssue(
                    "contradictory_status",
                    "reconciliation passed but reconciliation failure alert "
                    "recorded", "alerts.json"))
        if monitoring is not None:
            mon_sla = monitoring.get("sla_passed")
            m_sla = (manifest.get("sla_results") or {})
            if isinstance(mon_sla, bool) and isinstance(m_sla, dict) \
                    and mon_sla is False and all(m_sla.values()):
                issues.append(EvidenceIssue(
                    "contradictory_status",
                    "monitoring says SLA failed but manifest sla_results "
                    "all passed", "monitoring.json"))

    # ---- lineage serialization ------------------------------------------------
    if lineage is not None:
        checks.append("lineage_serialization")
        raw_path = os.path.join(evidence_dir, "lineage.json")
        try:
            with open(raw_path, "r", encoding="utf-8") as f:
                raw = f.read()
        except OSError:
            raw = ""
        for marker in _REPR_MARKERS:
            if marker in raw:
                issues.append(EvidenceIssue(
                    "lineage_repr_leak",
                    f"lineage file contains Python repr artifact: {marker!r}",
                    "lineage.json"))
        rr = lineage.get("run_records")
        if not isinstance(rr, list) or not rr:
            issues.append(EvidenceIssue(
                "lineage_run_records_missing",
                "lineage has no run_records", "lineage.json"))
        else:
            for r in rr:
                if not isinstance(r, dict):
                    issues.append(EvidenceIssue(
                        "lineage_record_not_dict",
                        "run_records entries must be JSON objects",
                        "lineage.json"))
                    break
        row_records = lineage.get("row_records")
        if not isinstance(row_records, list):
            issues.append(EvidenceIssue(
                "lineage_row_records_missing",
                "row_records must be a list (missing = invalid)",
                "lineage.json"))
        else:
            bad_struct = [r for r in row_records if not isinstance(r, dict)]
            if bad_struct:
                issues.append(EvidenceIssue(
                    "lineage_record_not_dict",
                    f"{len(bad_struct)} row_records entries are not JSON "
                    f"objects", "lineage.json"))
            for r in row_records:
                if isinstance(r, dict):
                    missing = [f for f in _LINEAGE_ROW_FIELDS if f not in r]
                    if missing:
                        issues.append(EvidenceIssue(
                            "lineage_field_missing",
                            f"row record missing fields: {missing}",
                            "lineage.json"))
                        break
                    if r.get("rule_id") not in rule_ids:
                        issues.append(EvidenceIssue(
                            "lineage_unknown_rule",
                            f"row record references unknown rule "
                            f"{r.get('rule_id')!r}", "lineage.json"))
                        break
            total = lineage.get("total_row_records")
            if not _is_int(total) or total < len(row_records):
                issues.append(EvidenceIssue(
                    "lineage_total_invalid",
                    f"total_row_records {total!r} < persisted "
                    f"{len(row_records)}", "lineage.json"))
            truncated = lineage.get("truncated")
            if truncated is True and len(row_records) > 1000:
                issues.append(EvidenceIssue(
                    "lineage_truncation_violated",
                    "truncated=True but more than 1000 row_records "
                    "persisted", "lineage.json"))

    # ---- referenced artifacts + hash recomputation --------------------------------
    if manifest is not None:
        checks.append("referenced_artifacts")
        gf = manifest.get("generated_files") or {}
        if not isinstance(gf, dict) or not gf:
            issues.append(EvidenceIssue(
                "generated_files_missing",
                "manifest generated_files must be a non-empty mapping",
                "manifest.json"))
        for name, path in gf.items():
            if not path or not os.path.isfile(path):
                issues.append(EvidenceIssue(
                    "referenced_artifact_missing",
                    f"generated_files.{name} path absent: {path!r}",
                    "manifest.json"))
                continue
            fh = (manifest.get("file_hashes") or {}).get(name)
            if fh is None:
                issues.append(EvidenceIssue(
                    "file_hash_missing",
                    f"file_hashes missing entry for {name!r}",
                    "manifest.json"))
            else:
                actual = hashlib.sha256(
                    open(path, "rb").read()).hexdigest()
                if actual != fh:
                    issues.append(EvidenceIssue(
                        "file_hash_mismatch",
                        f"generated_files.{name} hash mismatch: recorded "
                        f"{fh[:12]}... != actual {actual[:12]}...",
                        "manifest.json"))
        lr_path = manifest.get("lineage_reference")
        if not lr_path or not os.path.isfile(lr_path):
            issues.append(EvidenceIssue(
                "referenced_artifact_missing",
                f"lineage_reference path absent: {lr_path!r}",
                "manifest.json"))
        # Output column contract (only when the output file is available).
        out_path = gf.get("output")
        if out_path and os.path.isfile(out_path):
            try:
                with open(out_path, "r", newline="", encoding="utf-8") as f:
                    header = f.readline().rstrip("\r\n").split(",")
                if len(header) != TOTAL_OUTPUT_COLUMNS:
                    issues.append(EvidenceIssue(
                        "output_column_count_invalid",
                        f"output has {len(header)} columns, expected "
                        f"{TOTAL_OUTPUT_COLUMNS}", gf["output"]))
                else:
                    details["output_column_count"] = len(header)
            except OSError:
                pass

    details["issue_count"] = len(issues)
    details["optional_files_present"] = {
        n: os.path.isfile(os.path.join(evidence_dir, n)) for n in optional}
    report["issues"] = [i.to_dict() for i in issues]
    report["valid"] = not issues
    return report


def require_valid_evidence(evidence_dir: str, **kwargs) -> Dict[str, Any]:
    """Strict wrapper: raises EvidenceValidationError when invalid."""
    report = validate_evidence_dir(evidence_dir, **kwargs)
    if not report["valid"]:
        raise EvidenceValidationError(
            [EvidenceIssue(i["code"], i["message"], i["artifact"])
             for i in report["issues"]], report)
    return report
