"""Claim graph + evidence schema tests (Phases 5 and 6)."""

import json
import os
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance.claim_graph import (  # noqa: E402
    GraphBuilder, graph_fingerprint, verify_graph)
from data_quality_platform.assurance.evidence_schema import (  # noqa: E402
    SCHEMA_REGISTRY, compatibility_report, validate_schema_identity)


# ------------------------------------------------------------- Phase 5

def _seed_repo(tmpdir, evidence, claims_spec):
    for rel, doc in evidence.items():
        p = os.path.join(tmpdir, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(doc, f)
    b = GraphBuilder(tmpdir)
    for cid, text, value, ev in claims_spec:
        b.add_claim(cid, text, value, "test-derivation", ev)
    return b


def test_reverse_lookup_claim_to_sha():
    with tempfile.TemporaryDirectory() as td:
        b = _seed_repo(td, {
            "evidence/official/FINAL_RESULTS.json": {
                "rows": 3200000, "comparisons": 51200000,
                "mismatches": 0},
            "evidence/official/run1.json": {"rows": 3200000},
            "evidence/checker.py": "print('checker')\n",
        }, [
            ("combined_comparisons", "51.2M comparisons", 51200000,
             ["evidence/official/FINAL_RESULTS.json"]),
        ])
        b.add_evidence("evidence/official/FINAL_RESULTS.json",
                       role="official run-pair record",
                       depends_on=["evidence/official/run1.json",
                                   "evidence/checker.py"])
        graph = b.build()
        chain = graph["reverse_lookup"]["combined_comparisons"]
        assert "evidence:evi的证据" not in str(chain)  # sanity
        assert "evidence:evidence/official/FINAL_RESULTS.json" in chain
        assert "evidence:evidence/official/run1.json" in chain
        assert "evidence:evidence/checker.py" in chain
        # forward: the checker artifact serves the comparison claim
        assert "combined_comparisons" in graph["forward_lookup"][
            "evidence/checker.py"]


def test_verification_pass_when_values_derive():
    with tempfile.TemporaryDirectory() as td:
        # evidence must exist BEFORE provenance is recorded (a claim
        # registered against missing evidence is NOT_VERIFIED by
        # design — fail-closed)
        p = os.path.join(td, "evidence/fr.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            json.dump({"rows": 3000000}, f)
        b = GraphBuilder(td)
        derivs = {"rows": lambda root: json.load(open(
            os.path.join(root, "evidence/fr.json")))["rows"]}
        b.add_claim("rows", "3M rows per run", 3000000,
                    "read rows", ["evidence/fr.json"],
                    derivation_fn=derivs["rows"])
        graph = b.build()
        rep = verify_graph(graph, td, derivs)
        assert rep["verdict"] == "PASS"
        assert rep["claims_verified"] == 1


def test_verification_fails_on_stale_evidence():
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "evidence/fr.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            json.dump({"rows": 3000000}, f)
        b = GraphBuilder(td)
        derivs = {"rows": lambda root: json.load(open(
            os.path.join(root, "evidence/fr.json")))["rows"]}
        b.add_claim("rows", "3M rows", 3000000, "read",
                    ["evidence/fr.json"], derivation_fn=derivs["rows"])
        graph = b.build()  # hashes recorded
        # tamper AFTER graph construction
        with open(p, "w") as f:
            json.dump({"rows": 47}, f)
        rep = verify_graph(graph, td, derivs)
        assert rep["verdict"] == "FAIL"
        assert rep["claims_not_verified"] == 1


def test_verification_not_verified_on_missing_evidence():
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "evidence/fr.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            json.dump({"rows": 3000000}, f)
        b = GraphBuilder(td)
        derivs = {"rows": lambda root: json.load(open(
            os.path.join(root, "evidence/fr.json")))["rows"]}
        b.add_claim("rows", "3M rows", 3000000, "read",
                    ["evidence/fr.json"], derivation_fn=derivs["rows"])
        graph = b.build()
        os.remove(p)
        rep = verify_graph(graph, td, derivs)
        assert rep["claims_not_verified"] == 1
        assert rep["verdict"] in ("FAIL", "NOT_VERIFIED")


def test_claim_without_derivation_never_verifies():
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "evidence/fr.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            json.dump({"rows": 3000000}, f)
        b = GraphBuilder(td)
        b.add_claim("unverifiable", "hand-typed claim", 123,
                    "none", ["evidence/fr.json"])  # no derivation fn
        graph = b.build()
        rep = verify_graph(graph, td, {})
        assert rep["claims_not_verified"] == 1
        assert rep["claims_verified"] == 0


def test_fingerprint_deterministic():
    with tempfile.TemporaryDirectory() as td:
        def build():
            p = os.path.join(td, "evidence/fr.json")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                json.dump({"rows": 3000000}, f)
            b = GraphBuilder(td)
            b.add_claim("c1", "claim", 1, "d",
                        ["evidence/fr.json"])
            return b.build()
        assert graph_fingerprint(build()) == graph_fingerprint(build())


# ------------------------------------------------------------- Phase 6

def test_known_schema_validates():
    doc = {"schema": {"name": "dqaeip.freshness_report",
                      "version": "1.0"},
           "report": "x", "overall_state": "CURRENT"}
    status, problems = validate_schema_identity(doc)
    assert status == "KNOWN" and not problems


def test_unknown_schema_rejected():
    doc = {"schema": {"name": "dqaeip.mystery", "version": "9.9"},
           "report": "x"}
    status, problems = validate_schema_identity(doc)
    assert status == "UNKNOWN_SCHEMA"
    assert any("not in the supported registry" in p for p in problems)


def test_malformed_schema_rejected():
    for bad in ({"schema": "not-an-object"},
                {"schema": {"name": "dqaeip.freshness_report"}},
                {"schema": {"name": "dqaeip.freshness_report",
                            "version": "v1"}},
                {"schema": {"version": "1.0"}}):
        status, _ = validate_schema_identity(bad)
        assert status == "MALFORMED"


def test_missing_schema_is_not_verified_never_pass():
    status, problems = validate_schema_identity({"report": "old"})
    assert status == "MISSING_SCHEMA"
    assert any("NOT_VERIFIED" in p for p in problems)
    assert any("never" in p for p in problems)


def test_final_results_schema_anchors():
    good = {"schema": {"name": "dqaeip.final_results", "version": "2.0"},
            "release_identity": {"release_id": "X"},
            "derived_values": {"combined_comparisons": 51200000,
                               "combined_mismatches": 0,
                               "run_count": 2},
            "verification_state": "PASS_WITH_DOCUMENTED_LIMITATIONS"}
    status, problems = validate_schema_identity(good)
    assert status == "KNOWN" and not problems
    # tampered anchor: 51.2M -> 47M must be rejected by the schema
    bad = json.loads(json.dumps(good))
    bad["derived_values"]["combined_comparisons"] = 47000000
    status, problems = validate_schema_identity(bad)
    assert status == "MALFORMED"
    assert any("anchor" in p for p in problems)


def test_mutation_matrix_schema_requires_no_pass():
    doc = {"schema": {"name": "dqaeip.evidence_mutation_matrix",
                      "version": "1.0"},
           "report": "x",
           "mutations": [{"mutation_id": "m1", "outcome": "FAIL"},
                         {"mutation_id": "m2", "outcome": "NOT_VERIFIED"}]}
    status, problems = validate_schema_identity(doc)
    assert status == "KNOWN"
    bad = {"schema": doc["schema"], "report": "x",
           "mutations": [{"mutation_id": "m1", "outcome": "PASS"}]}
    status, problems = validate_schema_identity(bad)
    assert status == "MALFORMED"
    assert any("neither FAIL nor NOT_VERIFIED" in p for p in problems)


def test_registry_is_non_empty_and_versioned():
    assert ("dqaeip.final_results", "2.0") in SCHEMA_REGISTRY
    for (name, version) in SCHEMA_REGISTRY:
        assert name.startswith("dqaeip.")
        assert version.count(".") == 1


def test_compatibility_report_counts():
    docs = {
        "a.json": {"schema": {"name": "dqaeip.freshness_report",
                              "version": "1.0"},
                   "report": "x", "overall_state": "CURRENT"},
        "b.json": {"schema": {"name": "dqaeip.unknown_thing",
                              "version": "1.0"}},
        "c.json": {"report": "historical"},
    }
    rep = compatibility_report(docs)
    assert rep["document_count"] == 3
    assert rep["status_counts"] == {"KNOWN": 1, "UNKNOWN_SCHEMA": 1,
                                    "MISSING_SCHEMA": 1}
    assert rep["policy"]["missing_schema"].startswith("NOT_VERIFIED")
