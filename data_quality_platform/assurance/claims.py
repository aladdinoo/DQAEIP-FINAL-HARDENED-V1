"""Claim-to-Evidence Provenance (DQAEIP rebuild Phase 9).

Every important FINAL_RESULTS claim must be traceable to evidence:

    {
      "claim": "715 tests passed",
      "value": 715,
      "source_artifact": "evidence/tests/test_summary.json",
      "source_sha256": "...",
      "derivation": "direct",
      "verified": true
    }

Rules (fail closed):
- Values are machine-derived from the source artifact — never
  hand-typed, never copied from README.
- A claim that cannot be derived gets value=null and status
  NOT_VERIFIED; it can NEVER be marked verified=true.
- ``verify_claims`` re-derives every claim with its own derivation
  function and compares against the recorded value.
"""

import hashlib
import json
import os
import re

# Phase 13H.16/17 — Self-referential gate claim sentinel.
#
# The release_gate_verdict claim is uniquely self-referential: its
# source is the gate report that the current gate run is itself
# producing. While the gate is mid-execution (the .in_progress marker
# exists), the F-01 canonical helper (release_chain.
# load_current_release_gate_report) correctly returns None to block
# stale PASS. The claim cannot be independently re-derived at that
# instant, but this is NOT a contradiction — it is an honest PENDING
# state.
#
# CRITICAL INVARIANTS (do not weaken):
#   - This special case applies ONLY to the release_gate_verdict
#     derivation; ALL OTHER claims continue through normal F-01
#     derivation and fail-closed verification.
#   - The sentinel returns ok=True (gate does not FAIL) but
#     verified=False (the claim is honestly unverified, NOT PASS).
#     The claim is recorded as PENDING, never as PASS.
#   - Marker existence alone NEVER makes an unrelated claim pass —
#     only this specific self-referential claim receives the PENDING
#     state.
#   - This is interpretation (1) "current gate completes its own
#     self-referential claim", NOT interpretation (2) "current gate
#     trusts a previous gate PASS". F-01 helper still returns None
#     during marker; the sentinel does NOT read previous gate evidence.
SELF_REFERENTIAL_DERIVATION = "release_gate_verdict"
# Must match release_chain._GATE_MARKER_REL (single source of truth).
GATE_MARKER_REL = ("evidence/release_gate/"
                   "final_release_gate.json.in_progress")


def _stable_claim_id(name):
    """Deterministic claim id from the claim name (stable across runs,
    independent of timestamps)."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:6]
    return f"CLAIM-{slug[:40]}-{digest}"

__all__ = [
    "make_claim",
    "verify_claim",
    "verify_claims",
    "not_verified_claim",
]

# Derivations shipped with the assurance layer. Each takes the repo
# root and returns the derived value (or None when not derivable).
DERIVATIONS = {}


def derivation(name):
    """Register a derivation function under ``name``."""
    def deco(fn):
        DERIVATIONS[name] = fn
        return fn
    return deco


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(repo_root, rel):
    path = os.path.join(repo_root, rel)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ----------------------------------------------------------- derivations

@derivation("final_3m_input_sha256")
def _d_input_sha(repo_root):
    doc = _load_json(repo_root,
                     "evidence/validation/2026-09-19/fresh_3m2/"
                     "FINAL_RESULTS.json")
    return doc.get("input_sha256") if isinstance(doc, dict) else None


@derivation("final_3m_output_sha256")
def _d_output_sha(repo_root):
    doc = _load_json(repo_root,
                     "evidence/validation/2026-09-19/fresh_3m2/"
                     "FINAL_RESULTS.json")
    return doc.get("output_sha256") if isinstance(doc, dict) else None


@derivation("final_3m_rows")
def _d_rows(repo_root):
    doc = _load_json(repo_root,
                     "evidence/validation/2026-09-19/fresh_3m2/"
                     "FINAL_RESULTS.json")
    return doc.get("rows") if isinstance(doc, dict) else None


@derivation("final_3m_status")
def _d_status(repo_root):
    doc = _load_json(repo_root,
                     "evidence/validation/2026-09-19/fresh_3m2/"
                     "FINAL_RESULTS.json")
    return doc.get("final_status") if isinstance(doc, dict) else None


@derivation("oracle_comparisons_combined")
def _d_oracle_comparisons(repo_root):
    doc = _load_json(repo_root,
                     "evidence/validation/2026-09-19/fresh_3m2/"
                     "FINAL_RESULTS.json")
    if not isinstance(doc, dict):
        return None
    comp = doc.get("comparison_count", {})
    if comp.get("run_1") == comp.get("run_2") == 25600000 \
            and comp.get("combined_total") == 51200000:
        return 51200000
    return None


@derivation("oracle_mismatches_combined")
def _d_oracle_mismatches(repo_root):
    doc = _load_json(repo_root,
                     "evidence/validation/2026-09-19/fresh_3m2/"
                     "FINAL_RESULTS.json")
    mm = doc.get("oracle_mismatches", {}) if isinstance(doc, dict) else {}
    if mm.get("run_1") == 0 and mm.get("run_2") == 0 \
            and mm.get("combined_total") == 0:
        return 0
    return None


@derivation("run_pair_verification_verdict")
def _d_run_pair(repo_root):
    doc = _load_json(repo_root,
                     "evidence/rebuild_verification/"
                     "run_pair_verification.json")
    return doc.get("verdict") if isinstance(doc, dict) else None


@derivation("release_gate_verdict")
def _d_gate(repo_root):
    # F-01: route through canonical helper to prevent stale-PASS
    # survival when the .in_progress marker exists. Direct reads
    # of final_release_gate.json are a regression.
    from data_quality_platform.assurance.release_chain import \
        load_current_release_gate_report
    doc = load_current_release_gate_report(repo_root)
    return doc.get("overall_verdict") if isinstance(doc, dict) else None


@derivation("mutation_score")
def _d_mutation(repo_root):
    doc = _load_json(repo_root,
                     "evidence/mutation_testing/mutation_results.json")
    if isinstance(doc, dict):
        return doc.get("mutation_score")
    return None


@derivation("tests_passed")
def _d_tests(repo_root):
    doc = _load_json(repo_root, "evidence/rebuild_verification/"
                     "test_summary.json")
    if isinstance(doc, dict):
        return doc.get("passed")
    return None


@derivation("tests_skipped")
def _d_tests_skipped(repo_root):
    doc = _load_json(repo_root, "evidence/rebuild_verification/"
                     "test_summary.json")
    if isinstance(doc, dict):
        return doc.get("skipped")
    return None


@derivation("tests_collected")
def _d_tests_collected(repo_root):
    doc = _load_json(repo_root, "evidence/rebuild_verification/"
                     "test_summary.json")
    if isinstance(doc, dict):
        return doc.get("collected")
    return None


@derivation("test_summary_all_green")
def _d_tests_green(repo_root):
    doc = _load_json(repo_root, "evidence/rebuild_verification/"
                     "test_summary.json")
    if isinstance(doc, dict):
        return doc.get("all_green")
    return None


@derivation("checker_script_sha256")
def _d_checker(repo_root):
    path = os.path.join(repo_root, "scripts", "final_3m_validation.py")
    if not os.path.isfile(path):
        return None
    return _sha256_file(path)


@derivation("v1_rule_source_sha256")
def _d_rules(repo_root):
    path = os.path.join(repo_root, "data_quality_platform", "rules",
                        "v1_rules.py")
    if not os.path.isfile(path):
        return None
    return _sha256_file(path)


@derivation("final_3m_run_count")
def _d_run_count(repo_root):
    doc = _load_json(repo_root,
                     "evidence/validation/2026-09-19/fresh_3m2/"
                     "FINAL_RESULTS.json")
    if not isinstance(doc, dict):
        return None
    runs = doc.get("runs") or {}
    if set(runs) == {"run_1", "run_2"}:
        return 2
    return None


@derivation("final_3m_determinism_gate")
def _d_determinism(repo_root):
    """Byte-identical double-run outputs flag from the official
    FINAL_RESULTS evidence (never re-derived by re-running)."""
    doc = _load_json(repo_root,
                     "evidence/validation/2026-09-19/fresh_3m2/"
                     "FINAL_RESULTS.json")
    if not isinstance(doc, dict):
        return None
    if doc.get("determinism_status") == "PASS (byte-identical across two complete runs)":
        return True
    det = doc.get("determinism_gate") or doc.get("deterministic")
    if det is True:
        return True
    # Fallback: identical I/O SHAs across both runs implies byte-identity.
    runs = doc.get("runs") or {}
    if "run_1" in runs and "run_2" in runs:
        i1 = (runs["run_1"].get("dataset") or {}).get("input_sha256")
        i2 = (runs["run_2"].get("dataset") or {}).get("input_sha256")
        o1 = (runs["run_1"].get("output") or {}).get("sha256")
        o2 = (runs["run_2"].get("output") or {}).get("sha256")
        if i1 and i1 == i2 and o1 and o1 == o2:
            return True
    return None


@derivation("final_3m_seed")
def _d_seed(repo_root):
    doc = _load_json(repo_root,
                     "evidence/validation/2026-09-19/fresh_3m2/"
                     "FINAL_RESULTS.json")
    if isinstance(doc, dict):
        seed = doc.get("seed")
        if isinstance(seed, int):
            return seed
    return None


@derivation("limitation_count")
def _d_limitation_count(repo_root):
    doc = _load_json(repo_root,
                     "evidence/release/limitation_registry.json")
    if isinstance(doc, dict):
        lims = doc.get("limitations")
        if isinstance(lims, list):
            return len(lims)
    return None


@derivation("v1_rule_count")
def _d_rule_count(repo_root):
    doc = _load_json(repo_root,
                     "evidence/rebuild_baseline/v1_rule_inventory.json")
    if isinstance(doc, dict):
        rules = doc.get("rules")
        if isinstance(rules, list):
            return len(rules)
    return None


@derivation("memory_characteristic")
def _d_memory(repo_root):
    """Documented memory profile from the limitation registry — the
    value is the registry's own classification, never a stronger one."""
    doc = _load_json(repo_root,
                     "evidence/release/limitation_registry.json")
    if not isinstance(doc, dict):
        return None
    for lim in doc.get("limitations", []):
        if lim.get("id") == "LIM-001" and "O(N)" in json.dumps(lim):
            return "O(N)"
    return None


@derivation("clickhouse_runtime_status")
def _d_clickhouse(repo_root):
    """ClickHouse runtime validation status from the limitation
    registry (LIM-002). Absence of runtime evidence can only ever
    derive NOT_VERIFIED — never PASS."""
    doc = _load_json(repo_root,
                     "evidence/release/limitation_registry.json")
    if not isinstance(doc, dict):
        return None
    for lim in doc.get("limitations", []):
        if lim.get("id") == "LIM-002":
            return "NOT_VERIFIED (not executed; static SQL only)"
    return None


@derivation("airflow_runtime_status")
def _d_airflow(repo_root):
    """Airflow runtime validation status from the limitation
    registry (LIM-003)."""
    doc = _load_json(repo_root,
                     "evidence/release/limitation_registry.json")
    if not isinstance(doc, dict):
        return None
    for lim in doc.get("limitations", []):
        if lim.get("id") == "LIM-003":
            return "NOT_VERIFIED (not executed; DAG definitions only)"
    return None


@derivation("validation_scale")
def _d_scale(repo_root):
    """Validated scale from the official 3M evidence — the maximum
    scale for which execution evidence exists (no extrapolation)."""
    doc = _load_json(repo_root,
                     "evidence/validation/2026-09-19/fresh_3m2/"
                     "FINAL_RESULTS.json")
    if isinstance(doc, dict) and doc.get("rows") == 3200000 \
            and doc.get("final_status") == "PASS":
        return "3,200,000 rows (validated); no 100M/800M claim"
    return None


# ---- portable-release layer (2026-09-18) ---------------------------

_NSP = "evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18"


@derivation("absolute_path_gate_violations")
def _d_path_gate(repo_root):
    doc = _load_json(repo_root,
                    f"{_NSP}/release_gate/"
                    "absolute_path_gate_report.json")
    if isinstance(doc, dict) and doc.get("verdict") == "PASS":
        return doc.get("violation_count")
    return None


@derivation("tamper_detection_rate")
def _d_tamper_rate(repo_root):
    doc = _load_json(repo_root, f"{_NSP}/security/tamper_matrix.json")
    if isinstance(doc, dict) and doc.get("verdict") == "PASS":
        return doc.get("detection_rate")
    return None


@derivation("evidence_mutation_outcome")
def _d_evidence_mutations(repo_root):
    doc = _load_json(repo_root,
                     f"{_NSP}/mutation_testing/"
                     "evidence_mutation_matrix.json")
    if isinstance(doc, dict):
        return doc.get("outcome")
    return None


@derivation("artifact_identity_registry_verdict")
def _d_identity_registry(repo_root):
    doc = _load_json(repo_root,
                     f"{_NSP}/artifact_identity/"
                     "artifact_identity_registry.json")
    if isinstance(doc, dict):
        return doc.get("verdict")
    return None


@derivation("claim_graph_verdict")
def _d_claim_graph(repo_root):
    doc = _load_json(repo_root, f"{_NSP}/claim_graph/claim_graph.json")
    if isinstance(doc, dict):
        return (doc.get("verification") or {}).get("verdict")
    return None


@derivation("schema_compatibility_verdict")
def _d_schema_compat(repo_root):
    doc = _load_json(repo_root,
                     f"{_NSP}/schema_versioning/"
                     "SCHEMA_COMPATIBILITY_REPORT.json")
    if isinstance(doc, dict):
        return doc.get("verdict")
    return None


# ----------------------------------------------------------- claim API

def make_claim(name, value, source_artifact, derivation_name,
               repo_root, verified, claim_id=None):
    """Build a claim record with live source-hash provenance.

    A claim whose source artifact does not exist on disk is recorded
    as NOT_VERIFIED regardless of the requested ``verified`` flag —
    provenance cannot be established without a source.
    ``claim_id`` is a stable machine identifier (explicit or derived
    deterministically from the claim name; never from a timestamp).
    """
    src_sha = None
    source_exists = True
    if source_artifact and repo_root:
        p = os.path.join(repo_root, source_artifact)
        if os.path.isfile(p):
            src_sha = _sha256_file(p)
        else:
            source_exists = False
    elif source_artifact:
        source_exists = False
    claim_verified = bool(verified) and value is not None and source_exists
    return {
        "claim_id": claim_id or _stable_claim_id(name),
        "claim": name,
        "value": value,
        "source_artifact": source_artifact,
        "source_sha256": src_sha,
        "derivation": derivation_name,
        "verified": claim_verified,
        "status": "VERIFIED_LOCALLY" if claim_verified else "NOT_VERIFIED",
    }


def not_verified_claim(name, reason, claim_id=None):
    return {
        "claim_id": claim_id or _stable_claim_id(name),
        "claim": name,
        "value": None,
        "source_artifact": None,
        "source_sha256": None,
        "derivation": None,
        "verified": False,
        "status": "NOT_VERIFIED",
        "reason": reason,
    }


def verify_claim(claim, repo_root):
    """Re-derive one claim from its source; returns (ok, detail)."""
    dname = claim.get("derivation")
    if dname not in DERIVATIONS:
        return False, {"reason": f"unknown derivation {dname!r}"}
    derived = DERIVATIONS[dname](repo_root)
    recorded = claim.get("value")
    if derived is None:
        return False, {"reason": "derivation returned NOT_VERIFIED "
                                "(source missing or not derivable)"}
    if derived != recorded:
        return False, {"reason": "recorded value does not match "
                                "re-derived value",
                       "recorded": recorded, "derived": derived}
    return True, {"derived": derived}


def verify_claims(claims, repo_root):
    """Verify a list of claims; returns a report with per-claim state.

    NOT_VERIFIED claims never become PASS: a claim recorded with
    verified=false and value=null stays unverified; a claim recorded
    verified=true MUST re-derive identically or the whole report fails.
    """
    results = []
    all_ok = True
    for c in claims:
        if not isinstance(c, dict):
            results.append({"claim": "<malformed>", "verified": False,
                            "ok": False,
                            "detail": {"reason": "claim not an object"}})
            all_ok = False
            continue
        name = c.get("claim", "<unnamed>")
        if c.get("status") == "NOT_VERIFIED" or c.get("value") is None:
            results.append({"claim": name, "verified": False, "ok": True,
                            "detail": {"reason": "recorded as NOT_VERIFIED "
                                                 "— never reported as PASS"}})
            continue
        # Phase 13H.16/17 — Self-referential claim sentinel.
        #
        # ONLY for the release_gate_verdict derivation, when the gate
        # is mid-execution (marker exists), return an honest PENDING
        # state. The F-01 helper still returns None (it is unchanged);
        # this sentinel is at the verify_claims consumer level and does
        # NOT read any previous/stale gate evidence. The claim is NOT
        # marked as verified (verified=False); it is honestly PENDING.
        if (c.get("derivation") == SELF_REFERENTIAL_DERIVATION
                and os.path.exists(os.path.join(repo_root,
                                                 GATE_MARKER_REL))):
            results.append({
                "claim": name,
                "verified": False,
                "ok": True,
                "detail": {
                    "reason": (
                        "self-referential claim: gate in progress; "
                        "F-01 helper returned None (marker blocks stale "
                        "PASS); claim is honestly PENDING — will be "
                        "re-derived after marker removal"
                    ),
                    "state": "SELF_REFERENTIAL_PENDING",
                },
            })
            continue
        ok, detail = verify_claim(c, repo_root)
        results.append({"claim": name, "verified": c.get("verified", False),
                        "ok": ok, "detail": detail})
        if not ok:
            all_ok = False
    return {
        "claims_total": len(results),
        "claims_verified": sum(1 for r in results if r["verified"]),
        "claims_not_verified": sum(1 for r in results
                                   if not r["verified"]),
        "recheck_passed": all_ok,
        "results": results,
    }
