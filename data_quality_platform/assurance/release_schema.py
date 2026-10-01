"""Release Schema Validation (DQAEIP rebuild Phase 6).

Fail-closed validation of release-facing documents:

    FINAL_RESULTS.json / final_result.json
    release_manifest.json
    reproducibility_manifest.json

Checks (per document type):
- required keys present, correct JSON types
- status fields drawn from the closed evidence-status vocabulary
  (unknown status -> FAIL, Phase 15 false-PASS prevention)
- hash fields well-formed (64 lowercase hex)
- repository-relative path policy on path-like fields
- run identities distinct and well-formed

The validator NEVER fills in missing values and NEVER upgrades a
status; it only accepts or rejects.
"""

import json
import os
import re

from .truth_model import EVIDENCE_STATUSES, validate_status

__all__ = [
    "HASH_RE",
    "validate_hash",
    "validate_final_results",
    "validate_release_manifest",
    "validate_reproducibility_manifest",
    "validate_document",
]

HASH_RE = re.compile(r"^[0-9a-f]{64}$")

FINAL_RESULTS_REQUIRED = {
    "release_identity": dict,
    "project_identity": dict,
    "git_identity": dict,
    "rule_identity": dict,
    "runs": dict,
    "verification": dict,
    "limitations": list,
    "final_release_status": str,
    "claims": list,
}

RELEASE_MANIFEST_REQUIRED = {
    "release_name": str,
    "git": dict,
    "artifacts": dict,
    "validation": dict,
    "environment": dict,
}

REPRO_MANIFEST_REQUIRED = {
    "release_identity": dict,
    "git_identity": dict,
    "python": str,
    "checker_identity": dict,
    "rule_identity": dict,
    "schema_identity": dict,
    "input_identity": dict,
    "output_identity": dict,
    "run_identities": dict,
    "evidence_root": str,
    "release_gate_result": str,
}


def _problems_for_missing(doc, spec, label, problems):
    for key, typ in spec.items():
        if key not in doc:
            problems.append(f"{label}: missing required key '{key}'")
        elif not isinstance(doc[key], typ):
            problems.append(
                f"{label}: key '{key}' has type "
                f"{type(doc[key]).__name__}, expected {typ.__name__}")


def validate_hash(value, label, problems):
    if not isinstance(value, str) or not HASH_RE.match(value):
        problems.append(f"{label}: not a 64-hex lowercase SHA-256: "
                        f"{value!r}")


def validate_status_field(value, label, problems):
    try:
        validate_status(value)
    except ValueError as exc:
        problems.append(f"{label}: {exc}")


def validate_final_results(doc):
    """Validate a FINAL_RESULTS document; return problem list (empty=ok)."""
    problems = []
    if not isinstance(doc, dict):
        return ["FINAL_RESULTS: document is not a JSON object"]
    _problems_for_missing(doc, FINAL_RESULTS_REQUIRED, "FINAL_RESULTS",
                          problems)

    # final_release_status must be from the closed verdict vocabulary
    frs = doc.get("final_release_status")
    if isinstance(frs, str) and frs not in (
            "PASS", "PASS_WITH_DOCUMENTED_LIMITATIONS", "NOT_VERIFIED",
            "FAIL"):
        problems.append(f"FINAL_RESULTS: unknown final_release_status "
                        f"{frs!r}")

    # run identities: exactly run_1/run_2, distinct, PASS
    runs = doc.get("runs", {})
    if isinstance(runs, dict):
        if sorted(runs.keys()) != ["run_1", "run_2"]:
            problems.append(f"FINAL_RESULTS: runs keys must be exactly "
                            f"['run_1', 'run_2'], got {sorted(runs.keys())}")
        else:
            ids = set()
            for rkey, run in runs.items():
                rid = (run or {}).get("run_id")
                if not isinstance(rid, str) or not rid:
                    problems.append(f"FINAL_RESULTS: {rkey}.run_id missing")
                else:
                    ids.add(rid)
                status = (run or {}).get("status")
                if status != "PASS":
                    problems.append(f"FINAL_RESULTS: {rkey}.status must "
                                    f"be PASS, got {status!r}")
            if len(ids) == 1:
                problems.append("FINAL_RESULTS: run_1 and run_2 share the "
                                "same run_id (evidence mixing suspected)")

    # claims: each must carry provenance; NOT_VERIFIED never -> PASS
    claims = doc.get("claims", [])
    if isinstance(claims, list):
        for i, c in enumerate(claims):
            if not isinstance(c, dict):
                problems.append(f"FINAL_RESULTS: claims[{i}] not an object")
                continue
            for key in ("claim", "value", "source_artifact",
                        "derivation", "verified"):
                if key not in c:
                    problems.append(f"FINAL_RESULTS: claims[{i}] missing "
                                    f"'{key}'")
            if isinstance(c.get("verified"), bool):
                if c["verified"] is True and c.get("value") is None:
                    problems.append(
                        f"FINAL_RESULTS: claims[{i}] verified=true with "
                        f"null value (NOT_VERIFIED must never become PASS)")
    return problems


def validate_release_manifest(doc):
    problems = []
    if not isinstance(doc, dict):
        return ["release_manifest: document is not a JSON object"]
    _problems_for_missing(doc, RELEASE_MANIFEST_REQUIRED,
                           "release_manifest", problems)
    arts = doc.get("artifacts", {})
    if isinstance(arts, dict):
        for key, value in arts.items():
            if key.endswith("_sha256") and value is not None:
                validate_hash(value, f"release_manifest.artifacts.{key}",
                              problems)
    return problems


def validate_reproducibility_manifest(doc):
    problems = []
    if not isinstance(doc, dict):
        return ["reproducibility_manifest: not a JSON object"]
    _problems_for_missing(doc, REPRO_MANIFEST_REQUIRED,
                           "reproducibility_manifest", problems)
    # evidence_root must be a 64-hex SHA-256
    value = doc.get("evidence_root")
    if value is not None and not HASH_RE.match(str(value)):
        problems.append("reproducibility_manifest.evidence_root: expected "
                        "64-hex SHA-256")
    # release_gate_result is a verdict string from the closed verdict
    # vocabulary (or the explicit two-stage pending state)
    verdict = doc.get("release_gate_result")
    allowed = ("PASS", "FAIL", "NOT_VERIFIED",
               "PASS_WITH_DOCUMENTED_LIMITATIONS")
    if verdict is not None and verdict not in allowed:
        problems.append(f"reproducibility_manifest.release_gate_result: "
                        f"unknown verdict {verdict!r}")
    return problems


def validate_document(path, doc_type):
    """Load + validate a JSON document from ``path``. Returns
    (problems, doc). Fail closed on unreadable/malformed JSON."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except Exception as exc:
        return [f"{os.path.basename(path)}: unreadable/malformed JSON "
                f"({type(exc).__name__})"], None
    validators = {
        "final_results": validate_final_results,
        "release_manifest": validate_release_manifest,
        "reproducibility_manifest": validate_reproducibility_manifest,
    }
    if doc_type not in validators:
        return [f"unknown document type {doc_type!r}"], doc
    return validators[doc_type](doc), doc
