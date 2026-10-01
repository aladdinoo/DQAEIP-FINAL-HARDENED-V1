"""Decision Provenance (DQAVP hardening, Section 10).

Strengthens traceability so a reviewer can answer

    "Why did this row receive this flag?"

WITHOUT guessing, by resolving the complete chain from evidence the
engine already produces (existing architecture, no new heavyweight
graph layer):

    ROW -> FLAG -> RULE -> RULE VERSION -> RULE HASH
        -> REFERENCE -> REFERENCE HASH -> INPUT -> RUN -> ENGINE
        -> OUTPUT -> EVIDENCE

The resolver joins, read-only and fail closed:
    lineage.json  (row-level: run_id, row_number, rule_id, rule_version,
                   flag_value, row_hash)
    manifest.json (run-level: rule_hashes, schema_hash, generated_files,
                   file_hashes, run_id)
    audit.json    (execution events: run_started ... manifest_written)
    reference registry (reference identity + hash per rule)

Fail-closed contract: any missing link in the chain is reported as an
unresolved link — never silently omitted.
"""

import json
import os
from typing import Any, Dict, List, Optional

from data_quality_platform.verification.reference_provenance import (
    build_reference_registry, rule_reference_ids,
)

__all__ = ["DecisionProvenanceResolver", "resolve_decision"]


class DecisionProvenanceResolver:
    """Read-only resolver over one engine evidence directory."""

    def __init__(self, evidence_dir: str,
                 reference_registry: Optional[Dict[str, Any]] = None):
        if not os.path.isdir(evidence_dir):
            raise FileNotFoundError(
                f"evidence directory does not exist: {evidence_dir!r}")
        self.evidence_dir = evidence_dir
        self.registry = reference_registry or build_reference_registry()
        self._manifest = self._load("manifest.json")
        self._lineage = self._load("lineage.json")
        self._audit = self._load("audit.json")
        self._row_index = {}
        for rec in (self._lineage or {}).get("row_records", []):
            if isinstance(rec, dict):
                self._row_index.setdefault(
                    (rec.get("row_number"), rec.get("rule_id")), rec)

    def _load(self, name: str) -> Optional[Dict[str, Any]]:
        path = os.path.join(self.evidence_dir, name)
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_flagged(self, rule_id: Optional[str] = None,
                     limit: int = 50) -> List[Dict[str, Any]]:
        """List flagged row decisions (optionally for one rule)."""
        out = []
        for rec in (self._lineage or {}).get("row_records", []):
            if not isinstance(rec, dict):
                continue
            if rule_id and rec.get("rule_id") != rule_id:
                continue
            out.append(rec)
            if len(out) >= limit:
                break
        return out

    def resolve(self, row_number: int, rule_id: str) -> Dict[str, Any]:
        """Resolve the full provenance chain for one (row, rule) flag."""
        unresolved: List[str] = []

        rec = self._row_index.get((row_number, rule_id))
        if rec is None:
            raise KeyError(
                f"no lineage row_record for row_number={row_number}, "
                f"rule_id={rule_id!r} (row may be unflagged or beyond the "
                f"persisted 1000-record window)")

        chain: Dict[str, Any] = {
            "row": {"row_number": row_number,
                    "row_hash": rec.get("row_hash")},
            "flag": {"rule_id": rule_id,
                     "flag_value": rec.get("flag_value")},
            "rule": {"rule_id": rule_id,
                     "rule_version": rec.get("rule_version")},
        }

        # rule hash from the run manifest
        if self._manifest is not None:
            rh = (self._manifest.get("rule_hashes") or {}).get(rule_id)
            if rh:
                chain["rule"]["rule_sha256"] = rh
            else:
                unresolved.append(f"rule_hashes missing rule {rule_id!r}")
        else:
            unresolved.append("manifest.json missing")

        # reference(s) + hashes
        refs = []
        for ref_id in rule_reference_ids(rule_id):
            entry = self.registry["references"].get(ref_id)
            if entry is None:
                unresolved.append(f"reference {ref_id!r} not in registry")
                continue
            refs.append({"identity": entry["identity"],
                         "status": entry["status"],
                         "sha256": entry.get("sha256"),
                         "source": entry.get("source")})
        chain["references"] = refs

        # run / input / output / engine / evidence
        if self._manifest is not None:
            gf = self._manifest.get("generated_files") or {}
            chain["run"] = {"run_id": self._manifest.get("run_id"),
                            "timestamp": self._manifest.get("timestamp")}
            chain["input"] = {
                "schema_sha256": self._manifest.get("schema_hash"),
                "row_count": self._manifest.get("source_row_count")}
            chain["output"] = {
                "artifact": gf.get("output"),
                "sha256": (self._manifest.get("file_hashes") or {})
                    .get("output"),
                "row_count": self._manifest.get("output_row_count")}
            chain["evidence"] = {
                "evidence_dir": self.evidence_dir,
                "artifacts": {k: (self._manifest.get("file_hashes") or {})
                              .get(k) for k in sorted(gf)},
                "manifest_type": self._manifest.get("manifest_type"),
                "reconciliation_passed":
                    (self._manifest.get("reconciliation") or {})
                    .get("passed"),
            }
        else:
            unresolved.append("manifest.json missing")

        # engine execution events from audit
        if self._audit is not None:
            events = [e.get("event_type") for e in
                      self._audit.get("events", [])
                      if isinstance(e, dict)]
            chain["engine"] = {
                "audit_event_sequence": events,
                "run_failed_events": events.count("run_failed"),
                "note": ("the engine records the manifest_written audit "
                         "event in memory after audit.json is persisted; "
                         "manifest.json existence and integrity are "
                         "verified independently (see the evidence "
                         "validator)"),
            }
            if chain["engine"]["run_failed_events"]:
                unresolved.append("audit records run_failed events")
            if "validation_completed" not in events:
                unresolved.append(
                    "audit lacks validation_completed event")
        else:
            unresolved.append("audit.json missing")

        chain["unresolved_links"] = unresolved
        chain["chain_complete"] = not unresolved
        return chain

    def explain(self, row_number: int, rule_id: str) -> str:
        """Human-readable explanation of one flag decision."""
        c = self.resolve(row_number, rule_id)
        rule = c["rule"]
        refs = ", ".join(
            f"{r['identity']}({r['sha256'][:12]}...)"
            if r.get("sha256") else f"{r['identity']}(no hash)"
            for r in c["references"]) or "no external reference"
        out = (
            f"Row {c['row']['row_number']} (identity hash "
            f"{c['row']['row_hash']}) received flag "
            f"'{rule['rule_id']}'={c['flag']['flag_value']} in run "
            f"{c.get('run', {}).get('run_id')}: decided by rule "
            f"{rule['rule_id']} v{rule['rule_version']} "
            f"(implementation sha256 {rule.get('rule_sha256', 'UNRESOLVED')}) "
            f"evaluated against reference(s) [{refs}]; input schema "
            f"{c.get('input', {}).get('schema_sha256')} with "
            f"{c.get('input', {}).get('row_count')} rows; output artifact "
            f"{c.get('output', {}).get('artifact')} "
            f"(sha256 {c.get('output', {}).get('sha256')}); recorded in "
            f"evidence under {self.evidence_dir}.")
        if not c["chain_complete"]:
            out += (f" UNRESOLVED LINKS: {c['unresolved_links']}")
        return out


def resolve_decision(evidence_dir: str, row_number: int,
                     rule_id: str) -> Dict[str, Any]:
    """Convenience wrapper: full chain for one (row, rule) decision."""
    return DecisionProvenanceResolver(evidence_dir).resolve(
        row_number, rule_id)
