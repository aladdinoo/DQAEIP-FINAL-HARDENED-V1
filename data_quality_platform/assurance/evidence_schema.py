"""Evidence Schema Versioning (DQAEIP FINAL PORTABLE EVIDENCE &
RELEASE HARDENING, task section 7 — Phase 6).

Adds explicit schema identity to newly generated evidence:

    "schema": {"name": "dqaeip.final_results", "version": "2.0"}

Fail-closed semantics:

    - supported schema versions are an explicit registry;
    - an UNKNOWN schema name/version is REJECTED (never silently
      parsed);
    - a MALFORMED schema block is REJECTED;
    - a MISSING schema is NOT_VERIFIED — missing schema must never
      automatically become PASS;
    - migration exists only where deterministic and safe; historical
      artifacts are NOT migrated (their schemas are documented in the
      compatibility report as pre-versioning historical records).

Every registered schema carries a structural validator; validation
failure means the document does not belong to its claimed schema.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

__all__ = [
    "SCHEMA_REGISTRY",
    "validate_schema_identity",
    "classify_document",
    "compatibility_report",
]

_VERSION = re.compile(r"^[0-9]+\.[0-9]+$")


def _require(cond: bool, msg: str, problems: List[str]) -> None:
    if not cond:
        problems.append(msg)


# ------------------------------------------------------------- validators

def _v_final_results(doc: dict) -> List[str]:
    p: List[str] = []
    _require(isinstance(doc.get("release_identity"), dict),
             "release_identity missing", p)
    _require(isinstance(doc.get("derived_values"), dict),
             "derived_values missing", p)
    _require(doc.get("verification_state") is None or isinstance(
        doc.get("verification_state"), str), "bad verification_state", p)
    dv = doc.get("derived_values", {})
    _require(dv.get("combined_comparisons") == 51200000,
             "combined comparisons anchor violated", p)
    _require(dv.get("combined_mismatches") == 0,
             "mismatch anchor violated", p)
    _require(dv.get("run_count") == 2, "run count anchor violated", p)
    return p


def _v_claim_graph(doc: dict) -> List[str]:
    p: List[str] = []
    _require(isinstance(doc.get("claims"), list), "claims missing", p)
    _require(isinstance(doc.get("evidence_nodes"), list),
             "evidence_nodes missing", p)
    _require(isinstance(doc.get("reverse_lookup"), dict),
             "reverse_lookup missing", p)
    _require(isinstance(doc.get("verification"), dict),
             "verification report missing", p)
    return p


def _v_identity_registry(doc: dict) -> List[str]:
    p: List[str] = []
    _require(isinstance(doc.get("records"), list), "records missing", p)
    for r in doc.get("records", []):
        _require(isinstance(r.get("logical_path"), str)
                 and r["logical_path"].startswith("repo://"),
                 f"bad logical_path in record {r.get('relative_path')}", p)
        _require(re.match(r"^[0-9a-f]{64}$", str(r.get("sha256", ""))),
                 f"bad sha256 in record {r.get('relative_path')}", p)
    return p


def _v_dependency_graph(doc: dict) -> List[str]:
    p: List[str] = []
    _require(isinstance(doc.get("nodes"), list), "nodes missing", p)
    _require(isinstance(doc.get("graph_fingerprint"), str)
             and len(doc.get("graph_fingerprint", "")) == 64,
             "graph_fingerprint missing", p)
    return p


def _v_generic_list_report(doc: dict) -> List[str]:
    p: List[str] = []
    _require(isinstance(doc.get("report"), str), "report title missing", p)
    return p


def _v_normalization(doc: dict) -> List[str]:
    p: List[str] = []
    _require(isinstance(doc.get("sources"), list), "sources missing", p)
    _require(doc.get("verification", {}).get("originals_byte_identical")
             is True, "originals_byte_identical is not True", p)
    return p


def _v_path_gate(doc: dict) -> List[str]:
    p: List[str] = []
    _require(doc.get("verdict") in ("PASS", "FAIL"),
             "verdict missing/invalid", p)
    return p


def _v_freshness(doc: dict) -> List[str]:
    p: List[str] = []
    _require(doc.get("overall_state") in
             ("CURRENT", "STALE", "NOT_VERIFIED", "INVALID"),
             "overall_state missing/invalid", p)
    return p


def _v_self_contained(doc: dict) -> List[str]:
    p: List[str] = []
    _require(isinstance(doc.get("checks"), dict), "checks missing", p)
    _require(doc.get("verdict") in ("PASS", "FAIL", "NOT_VERIFIED"),
             "verdict missing/invalid", p)
    return p


def _v_mutation_matrix(doc: dict) -> List[str]:
    p: List[str] = []
    _require(isinstance(doc.get("mutations"), list),
             "mutations list missing", p)
    for m in doc.get("mutations", []):
        _require(m.get("outcome") in ("FAIL", "NOT_VERIFIED"),
                 f"tampered evidence produced neither FAIL nor "
                 f"NOT_VERIFIED for {m.get('mutation_id')}", p)
    return p


def _v_tamper_matrix(doc: dict) -> List[str]:
    """Tamper matrix (tools/run_tamper_matrix.py contract): a scenarios
    list where every scenario carries a detection result; fail-closed
    detection outcomes only (detected / not_detected)."""
    p: List[str] = []
    _require(isinstance(doc.get("scenarios"), list),
             "scenarios list missing", p)
    for s in doc.get("scenarios", []):
        _require(s.get("detection") in ("detected", "not_detected"),
                 f"tamper scenario {s.get('scenario')} has no "
                 f"fail-closed detection result", p)
    return p


def _v_inventory(doc: dict) -> List[str]:
    p: List[str] = []
    _require(isinstance(doc.get("findings"), list),
             "findings missing", p)
    _require(isinstance(doc.get("scope"), dict), "scope missing", p)
    return p


# The schema registry: (name, version) -> structural validator.
SCHEMA_REGISTRY: Dict[Tuple[str, str], Callable[[dict], List[str]]] = {
    ("dqaeip.final_results", "2.0"): _v_final_results,
    ("dqaeip.claim_graph", "1.0"): _v_claim_graph,
    ("dqaeip.artifact_identity_registry", "1.0"): _v_identity_registry,
    ("dqaeip.dependency_graph", "1.0"): _v_dependency_graph,
    ("dqaeip.normalization_summary", "1.0"): _v_normalization,
    ("dqaeip.absolute_path_gate_report", "1.0"): _v_path_gate,
    ("dqaeip.absolute_path_inventory", "1.0"): _v_inventory,
    ("dqaeip.freshness_report", "1.0"): _v_freshness,
    ("dqaeip.self_contained_verification", "1.0"): _v_self_contained,
    ("dqaeip.evidence_mutation_matrix", "1.0"): _v_mutation_matrix,
    ("dqaeip.security_report", "1.0"): _v_generic_list_report,
    ("dqaeip.release_manifest", "1.0"): _v_generic_list_report,
    ("dqaeip.release_lock", "1.0"): _v_generic_list_report,
    ("dqaeip.zip_record", "1.0"): _v_generic_list_report,
    ("dqaeip.integrity_snapshot", "1.0"): _v_generic_list_report,
    ("dqaeip.tamper_matrix", "1.0"): _v_tamper_matrix,
    ("dqaeip.path_gate_exceptions", "1.0"): _v_generic_list_report,
    ("dqaeip.historical_policy", "1.0"): _v_generic_list_report,
    ("dqaeip.release_identity", "1.0"): _v_generic_list_report,
}

SUPPORTED_NAMES = sorted({name for name, _ in SCHEMA_REGISTRY})


def validate_schema_identity(doc: dict) -> Tuple[str, List[str]]:
    """Classify + structurally validate one document by its schema
    identity block.

    Returns (status, problems):

        KNOWN            schema registered and structurally valid
        UNKNOWN_SCHEMA   name/version not in the registry (REJECTED)
        MALFORMED        schema block malformed (REJECTED)
        MISSING_SCHEMA   no schema identity (NOT_VERIFIED — never PASS)
    """
    if not isinstance(doc, dict):
        return "MALFORMED", ["document is not a JSON object"]
    schema = doc.get("schema")
    if schema is None:
        return "MISSING_SCHEMA", [
            "no schema identity block; pre-versioning historical "
            "artifact or missing provenance — NOT_VERIFIED, never "
            "silently accepted"]
    if not isinstance(schema, dict):
        return "MALFORMED", ["schema block is not an object"]
    name = schema.get("name")
    version = schema.get("version")
    if not isinstance(name, str) or not name:
        return "MALFORMED", ["schema.name missing"]
    if not isinstance(version, str) or not _VERSION.match(version or ""):
        return "MALFORMED", [f"schema.version must be N.M, got "
                             f"{version!r}"]
    key = (name, version)
    if key not in SCHEMA_REGISTRY:
        return "UNKNOWN_SCHEMA", [
            f"schema {name} v{version} is not in the supported "
            f"registry {sorted(SCHEMA_REGISTRY)}"]
    problems = SCHEMA_REGISTRY[key](doc)
    return ("KNOWN" if not problems else "MALFORMED"), problems


def classify_document(doc: dict) -> Dict[str, Any]:
    status, problems = validate_schema_identity(doc)
    return {
        "schema": doc.get("schema") if isinstance(doc, dict) else None,
        "status": status,
        "problems": problems,
    }


def compatibility_report(docs: Dict[str, dict]) -> dict:
    """Aggregate classification over ``{relative_path: parsed_doc}``."""
    entries = {}
    for rel in sorted(docs):
        entries[rel] = classify_document(docs[rel])
    counts: Dict[str, int] = {}
    for e in entries.values():
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    return {
        "document_count": len(entries),
        "status_counts": counts,
        "entries": entries,
        "policy": {
            "known": "registered schema + structural validation PASS",
            "unknown_schema": "REJECTED — never silently parsed",
            "malformed": "REJECTED — schema block or structure invalid",
            "missing_schema": "NOT_VERIFIED — historical/pre-versioning "
                              "artifact; never automatically PASS; no "
                              "migration is performed (historical "
                              "evidence stays historically accurate)",
            "migration": "none performed; only deterministic, safe "
                         "re-derivation through the two-phase rebuild "
                         "is allowed for derived artifacts",
        },
    }
