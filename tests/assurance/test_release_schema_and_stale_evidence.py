"""DQAEIP assurance-layer tests: release schema + stale evidence +
claims (Phases 6/9/10/15).

FALSE-PASS PREVENTION: every invalid release scenario must be rejected
by the schema/anti-stale/claims validators.
"""

import copy
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance import claims, release_schema, \
    stale_evidence


def valid_final_results_doc():
    return {
        "release_identity": {"name": "DQAEIP-Release", "date": "2026-09-16"},
        "project_identity": {"name": "Data Quality Assurance & Evidence "
                            "Integrity Platform"},
        "git_identity": {"head": "a" * 40},
        "rule_identity": {"rules": ["email_blank"]},
        "runs": {
            "run_1": {"run_id": "final_3m_pass1", "status": "PASS"},
            "run_2": {"run_id": "final_3m_pass2", "status": "PASS"},
        },
        "verification": {"release_gate_verdict": "PASS"},
        "limitations": [{"id": "LIM-001"}],
        "final_release_status": "PASS_WITH_DOCUMENTED_LIMITATIONS",
        "claims": [{
            "claim": "rows", "value": 3000000, "verified": True,
            "source_artifact": "x", "derivation": "final_3m_rows",
        }],
    }


def valid_run_record(rid="final_3m_pass1"):
    return {
        "run_id": rid, "status": "PASS",
        "git_commit": "b" * 40, "checker_sha256": "c" * 64,
        "schema_hash": "d" * 64, "input_sha256": "e" * 64,
        "output_sha256": "f" * 64,
        "rule_hashes": {"email_blank": "1" * 64},
        "oracle_mismatches": 0,
    }


class TestReleaseSchema:
    """Phase 6/15: release document validation."""

    def test_valid_document_accepted(self):
        assert release_schema.validate_final_results(
            valid_final_results_doc()) == []

    def test_missing_required_key_rejected(self):
        doc = valid_final_results_doc()
        del doc["git_identity"]
        problems = release_schema.validate_final_results(doc)
        assert any("git_identity" in p for p in problems)

    def test_unknown_final_status_rejected(self):
        doc = valid_final_results_doc()
        doc["final_release_status"] = "looks good"
        problems = release_schema.validate_final_results(doc)
        assert any("final_release_status" in p for p in problems)

    def test_third_run_rejected(self):
        doc = valid_final_results_doc()
        doc["runs"]["run_3"] = {"run_id": "x", "status": "PASS"}
        problems = release_schema.validate_final_results(doc)
        assert any("run_1', 'run_2'" in p for p in problems)

    def test_failing_run_status_rejected(self):
        doc = valid_final_results_doc()
        doc["runs"]["run_2"]["status"] = "FAIL"
        problems = release_schema.validate_final_results(doc)
        assert any("status" in p for p in problems)

    def test_duplicate_run_id_rejected_as_mixing(self):
        doc = valid_final_results_doc()
        doc["runs"]["run_2"]["run_id"] = "final_3m_pass1"
        problems = release_schema.validate_final_results(doc)
        assert any("same run_id" in p for p in problems)

    def test_verified_claim_with_null_value_rejected(self):
        doc = valid_final_results_doc()
        doc["claims"].append({"claim": "x", "value": None, "verified": True,
                              "source_artifact": None, "derivation": "d"})
        problems = release_schema.validate_final_results(doc)
        assert any("NOT_VERIFIED must never become PASS" in p
                  for p in problems)

    def test_claim_missing_provenance_rejected(self):
        doc = valid_final_results_doc()
        doc["claims"].append({"claim": "x", "value": 5})
        problems = release_schema.validate_final_results(doc)
        assert any("claims[" in p for p in problems)

    def test_bad_sha256_format_rejected(self):
        doc = {
            "release_name": "x", "git": {"head": "h"},
            "artifacts": {"readme_sha256": "NOTAHASH"},
            "validation": {}, "environment": {},
        }
        problems = release_schema.validate_release_manifest(doc)
        assert any("readme_sha256" in p for p in problems)

    def test_repro_manifest_unknown_gate_verdict_rejected(self):
        doc = {
            "release_identity": {}, "git_identity": {}, "python": "3",
            "checker_identity": {}, "rule_identity": {},
            "schema_identity": {}, "input_identity": {},
            "output_identity": {}, "run_identities": {},
            "evidence_root": "a" * 64,
            "release_gate_result": "probably fine",
        }
        problems = release_schema.validate_reproducibility_manifest(doc)
        assert any("unknown verdict" in p for p in problems)

    def test_repro_manifest_bad_evidence_root_rejected(self):
        doc = {
            "release_identity": {}, "git_identity": {}, "python": "3",
            "checker_identity": {}, "rule_identity": {},
            "schema_identity": {}, "input_identity": {},
            "output_identity": {}, "run_identities": {},
            "evidence_root": "nothex",
            "release_gate_result": "PASS",
        }
        problems = release_schema.validate_reproducibility_manifest(doc)
        assert any("evidence_root" in p for p in problems)

    def test_malformed_json_document_rejected(self, tmp_path):
        p = tmp_path / "FINAL_RESULTS.json"
        p.write_text("{broken")
        problems, doc = release_schema.validate_document(
            str(p), "final_results")
        assert problems and doc is None

    def test_real_reproducibility_manifest_schema(self):
        """After the model build, the real manifest must validate."""
        path = os.path.join(REPO_ROOT, "evidence", "release",
                            "reproducibility_manifest.json")
        if not os.path.isfile(path):
            pytest.skip("reproducibility manifest not yet built")
        problems, _ = release_schema.validate_document(
            path, "reproducibility_manifest")
        assert problems == []


class TestStaleEvidence:
    """Phase 10/15: anti-stale / anti-mixing."""

    def test_valid_run_set_passes(self):
        r1, r2 = valid_run_record("r1"), valid_run_record("r2")
        report = stale_evidence.evaluate_run_set([r1, r2])
        assert report["verdict"] == "PASS"

    def test_single_run_cannot_form_pair(self):
        report = stale_evidence.evaluate_run_set([valid_run_record()])
        problems = report["problems"]
        assert any("requires >= 2" in p for p in problems)
        assert report["verdict"] == "REJECT"

    def test_different_git_lineage_rejected(self):
        r1 = valid_run_record("r1")
        r2 = valid_run_record("r2")
        r2["git_commit"] = "9" * 40  # lineage of release B
        report = stale_evidence.evaluate_run_set([r1, r2])
        assert report["verdict"] == "REJECT"
        assert any("MIXED-LINEAGE" in p and "git_commit" in p
                   for p in report["problems"])

    def test_different_checker_rejected(self):
        r1, r2 = valid_run_record("r1"), valid_run_record("r2")
        r2["checker_sha256"] = "8" * 64
        report = stale_evidence.evaluate_run_set([r1, r2])
        assert any("checker_sha256" in p for p in report["problems"])

    def test_different_rule_hashes_rejected(self):
        r1, r2 = valid_run_record("r1"), valid_run_record("r2")
        r2["rule_hashes"] = {"email_blank": "7" * 64}
        report = stale_evidence.evaluate_run_set([r1, r2])
        assert any("rule_hashes" in p for p in report["problems"])

    def test_duplicate_run_id_rejected(self):
        r1, r2 = valid_run_record("same_id"), valid_run_record("same_id")
        report = stale_evidence.evaluate_run_set([r1, r2])
        assert any("duplicate run_id" in p for p in report["problems"])

    def test_stale_checker_vs_actual_file_rejected(self):
        r1, r2 = valid_run_record("r1"), valid_run_record("r2")
        report = stale_evidence.evaluate_run_set(
            [r1, r2], expected_checker_sha="0" * 64)
        assert any("STALE CHECKER" in p for p in report["problems"])

    def test_pinned_rule_binding_rejects_drift(self):
        r1, r2 = valid_run_record("r1"), valid_run_record("r2")
        report = stale_evidence.evaluate_run_set(
            [r1, r2], pinned_rule_hashes={"email_blank": "6" * 64})
        assert any("STALE RULES" in p for p in report["problems"])

    def test_missing_companion_artifact_rejected(self, tmp_path):
        r1, r2 = valid_run_record("r1"), valid_run_record("r2")
        report = stale_evidence.evaluate_run_set(
            [r1, r2], repo_root=str(tmp_path),
            run_companions=[{"run_id": "r1",
                             "required": ["evidence/missing.json"]}])
        assert any("missing companion artifact" in p
                   for p in report["problems"])

    def test_non_pass_run_rejected(self):
        r1 = valid_run_record("r1")
        r1["status"] = "BLOCKED"
        problems = stale_evidence.check_run_record(r1, 0)
        assert any("not PASS" in p for p in problems)

    def test_missing_key_rejected(self):
        r1 = valid_run_record("r1")
        del r1["input_sha256"]
        problems = stale_evidence.check_run_record(r1, 0)
        assert any("input_sha256" in p for p in problems)


class TestClaims:
    """Phase 9/15: claim-to-evidence provenance."""

    def test_known_derivation_rederives_from_real_evidence(self):
        claim = {
            "claim": "3.2M rows", "value": 3200000,
            "source_artifact": "evidence/validation/2026-09-18/"
                               "fresh_3m2/harness/FINAL_RESULTS.json",
            "derivation": "final_3m_rows", "verified": True,
        }
        ok, detail = claims.verify_claim(claim, REPO_ROOT)
        assert ok, detail

    def test_wrong_value_detected(self):
        claim = {
            "claim": "3.2M rows", "value": 3199999,
            "derivation": "final_3m_rows", "verified": True,
        }
        ok, detail = claims.verify_claim(claim, REPO_ROOT)
        assert not ok
        assert "does not match" in detail["reason"]

    def test_unknown_derivation_rejected(self):
        claim = {"claim": "x", "value": 1, "derivation": "hand_typed",
                 "verified": True}
        ok, detail = claims.verify_claim(claim, REPO_ROOT)
        assert not ok

    def test_not_verified_claims_stay_not_verified(self):
        claim = claims.not_verified_claim("missing company data",
                                         "fixture never supplied")
        report = claims.verify_claims([claim], REPO_ROOT)
        assert report["recheck_passed"] is True  # honestly recorded
        assert report["claims_not_verified"] == 1
        assert report["claims_verified"] == 0

    def test_mixed_claims_report(self):
        good = {
            "claim": "rows", "value": 3200000,
            "source_artifact": "evidence/validation/2026-09-18/"
                               "fresh_3m2/harness/FINAL_RESULTS.json",
            "derivation": "final_3m_rows", "verified": True,
        }
        bad = {
            "claim": "status", "value": "FAIL",
            "derivation": "final_3m_status", "verified": True,
        }
        nv = claims.not_verified_claim("dl fixture", "not supplied")
        report = claims.verify_claims([good, bad, nv], REPO_ROOT)
        assert report["recheck_passed"] is False
        assert report["claims_not_verified"] == 1

    def test_make_claim_records_source_sha(self):
        src = "evidence/validation/2026-09-19/fresh_3m2/FINAL_RESULTS.json"
        claim = claims.make_claim("rows", 3200000, src, "final_3m_rows",
                                  REPO_ROOT, verified=True)
        assert claim["source_sha256"] and len(claim["source_sha256"]) == 64
        assert claim["status"] == "VERIFIED_LOCALLY"

    def test_make_claim_missing_source_is_not_verified(self):
        claim = claims.make_claim("x", 1, "nope/missing.json", "final_3m_rows",
                                  REPO_ROOT, verified=True)
        assert claim["status"] == "NOT_VERIFIED"
        assert claim["source_sha256"] is None
