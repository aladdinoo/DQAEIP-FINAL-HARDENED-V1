"""DQAEIP assurance-layer tests: release chain + limitation registry +
golden snapshot (Phases 7/16/18) — integration with the real repo.
"""

import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance import (golden_snapshot,
                                            limitation_registry,
                                            release_chain)


class TestReleaseChain:
    """Phase 7: every chain edge must be verifiable from actual
    artifacts (integration with the real repo)."""

    def test_chain_edges_catalog_complete(self):
        assert set(release_chain.CHAIN_EDGES) == {
            "source_to_git", "git_to_rules", "rules_to_input",
            "input_to_runs", "run_to_run", "runs_to_oracle",
            "oracle_to_replay", "replay_to_evidence", "evidence_to_root",
            "root_to_gate", "gate_to_results", "results_to_docs",
        }

    def test_real_chain_core_edges_verified(self):
        # FINAL HARDENING (§22 extraction check): live git lineage is a
        # REPOSITORY-state fact. In a git-less extraction of the release
        # archive (the ZIP intentionally excludes .git), git context is
        # genuinely NOT VERIFIABLE — this test skips with an explicit
        # reason (consistent with the repo's skip policy: environment
        # limitations are never converted to PASS, and never silently
        # ignored). In a live checkout the git edges are always asserted.
        if not os.path.isdir(os.path.join(REPO_ROOT, ".git")):
            pytest.skip("no git repository present (release-archive "
                        "extraction): live git-lineage edges are not "
                        "verifiable without .git — NOT_VERIFIED, "
                        "never PASS")
        ok, report = release_chain.verify_chain(REPO_ROOT)
        edges = report["edges"]
        # Core evidence edges must hold on the real repo right now:
        for core in ("source_to_git", "git_to_rules", "rules_to_input",
                     "input_to_runs", "run_to_run", "runs_to_oracle",
                     "oracle_to_replay", "replay_to_evidence",
                     "evidence_to_root"):
            assert edges[core]["verified"], (core, edges[core])
        # root_to_gate requires a live release-gate round artifact. Under
        # the 2026-09-19 gate-round ledger discipline a FAIL round is
        # ledgered (full content embedded in
        # evidence/FINAL_HARDENED_RELEASE_2026-09-19/release_gate/
        # gate_rounds.json) and its file is purged so the next round
        # starts without stale self-referential samples. Between rounds
        # the chain must honestly report the edge as NOT verified
        # (fail-closed — never a guessed PASS); once the next round's
        # artifact lands on disk the edge is asserted verified as
        # before.
        if os.path.isfile(os.path.join(REPO_ROOT, "evidence",
                                       "release_gate",
                                       "final_release_gate.json")):
            assert edges["root_to_gate"]["verified"], edges[
                "root_to_gate"]
        else:
            assert edges["root_to_gate"]["verified"] is False, edges[
                "root_to_gate"]
            assert edges["root_to_gate"]["detail"][
                "release_gate_verdict"] is None, edges["root_to_gate"]
        # gate_to_results may be pending until FINAL_RESULTS.json is
        # rebuilt; when the doc exists it must be verified
        if os.path.isfile(os.path.join(REPO_ROOT, "FINAL_RESULTS.json")):
            assert edges["gate_to_results"]["verified"], edges[
                "gate_to_results"]

    def test_chain_fails_closed_when_gate_evidence_missing(self, tmp_path):
        ok, report = release_chain.verify_chain(str(tmp_path))
        assert ok is False
        assert report["verdict"] == "FAIL_CLOSED"
        # every edge unverified on an empty tree
        assert all(not e["verified"] for e in report["edges"].values())


class TestLimitationRegistry:
    """Phase 18: structured limitation registry."""

    def test_registry_structurally_valid(self):
        entries, load_problems = limitation_registry.load_registry(
            REPO_ROOT)
        assert load_problems == []
        assert limitation_registry.validate_registry(
            entries, REPO_ROOT) == []

    def test_registry_has_expected_core_limitations(self):
        for lid in ("LIM-001", "LIM-002", "LIM-003", "LIM-004", "LIM-005",
                    "LIM-006"):
            assert limitation_registry.get_limitation(REPO_ROOT, lid) \
                is not None, lid

    def test_limitations_have_stable_unique_ids(self):
        entries, _ = limitation_registry.load_registry(REPO_ROOT)
        ids = [l["id"] for l in entries]
        assert len(ids) == len(set(ids))
        assert all(lid.startswith("LIM-") for lid in ids)

    def test_every_limitation_has_all_required_fields(self):
        entries, _ = limitation_registry.load_registry(REPO_ROOT)
        for l in entries:
            for field in limitation_registry.REQUIRED_FIELDS:
                assert field in l, (l.get("id"), field)

    def test_no_limitation_is_hidden_or_silent(self):
        entries, _ = limitation_registry.load_registry(REPO_ROOT)
        states = {l["verification_state"] for l in entries}
        assert states <= set(
            limitation_registry.ALLOWED_VERIFICATION_STATES)

    def test_unknown_verification_state_rejected(self):
        problems = limitation_registry.validate_registry([
            {"id": "LIM-099", "title": "x", "status": "OPEN",
             "description": "x", "evidence_reference": [],
             "verification_state": "PROBABLY_FINE",
             "affected_scope": "x", "blocks_release": False},
        ])
        assert any("unknown verification_state" in p for p in problems)

    def test_malformed_registry_file_fail_closed(self, tmp_path):
        problems = limitation_registry.validate_registry(
            repo_root=str(tmp_path))
        assert problems  # missing file -> problems, never silent pass

    def test_non_blocking_limitations_do_not_fail_policy(self):
        from data_quality_platform.assurance import truth_model
        entries, _ = limitation_registry.load_registry(REPO_ROOT)
        limits = [{"blocks_release": l["blocks_release"]}
                  for l in entries]
        assert truth_model.derive_final_verdict([("core", True)], [],
                                                limits) == \
            "PASS_WITH_DOCUMENTED_LIMITATIONS"

    def test_registry_summary_counts(self):
        s = limitation_registry.registry_summary(REPO_ROOT)
        assert s["total"] >= 11
        assert s["blocking"] == 0  # stated release policy
        assert s["open"] == s["total"]


class TestGoldenSnapshot:
    """Phase 16: PII-free release fingerprint."""

    def test_snapshot_builds_from_real_evidence(self):
        snap = golden_snapshot.build_snapshot(
            REPO_ROOT, "DQAEIP-Enterprise-Assurance-Validation-Release")
        assert snap["snapshot_type"] == \
            "golden_release_fingerprint_metadata_only"
        assert len(snap["v1_rule_ids"]) == 8
        assert snap["input_sha256"] and len(snap["input_sha256"]) == 64
        assert snap["output_sha256"] and len(snap["output_sha256"]) == 64
        assert snap["checker_sha256"] and len(snap["checker_sha256"]) == 64
        assert snap["evidence_roots"]["run_1"]
        assert snap["evidence_roots"]["run_2"]

    def test_snapshot_contains_no_pii_or_paths(self):
        from data_quality_platform.assurance import path_firewall
        snap = golden_snapshot.build_snapshot(
            REPO_ROOT, "DQAEIP-Enterprise-Assurance-Validation-Release")
        text = json.dumps(snap)
        assert path_firewall.scan_text(text) == []
        # no email addresses (simple heuristic for PII absence)
        assert "@" not in text.replace("@property", "")

    def test_snapshot_validation_fails_on_null_fields(self):
        problems = golden_snapshot.validate_snapshot({})
        assert len(problems) >= 10

    def test_snapshot_validation_fails_on_wrong_rule_count(self):
        snap = golden_snapshot.build_snapshot(
            REPO_ROOT, "DQAEIP-Enterprise-Assurance-Validation-Release")
        snap["v1_rule_ids"] = snap["v1_rule_ids"][:7]
        problems = golden_snapshot.validate_snapshot(snap)
        assert any("8 V1 rule IDs" in p for p in problems)

    def test_snapshot_validation_fails_on_missing_roots(self):
        snap = golden_snapshot.build_snapshot(
            REPO_ROOT, "DQAEIP-Enterprise-Assurance-Validation-Release")
        snap["evidence_roots"]["run_2"] = None
        problems = golden_snapshot.validate_snapshot(snap)
        assert any("run evidence roots missing" in p for p in problems)

    def test_valid_snapshot_passes_validation(self):
        # Terminal-state assertion: a fully valid snapshot requires the
        # live release-gate round artifact (release_gate_sha256). Under
        # the 2026-09-19 gate-round ledger discipline a FAIL round is
        # ledgered then purged, so between rounds the snapshot honestly
        # carries a null release_gate_sha256 (fail-closed) and cannot
        # pass validation — this test asserts the full terminal shape
        # only when a current gate artifact exists; mid-transition it
        # skips with this explicit reason (never a guessed PASS).
        if not os.path.isfile(os.path.join(
                REPO_ROOT, "evidence", "release_gate",
                "final_release_gate.json")):
            pytest.skip("live release-gate artifact absent (mid-"
                        "transition under the gate-round ledger "
                        "discipline: FAIL rounds ledgered then purged): "
                        "snapshot release_gate_sha256 is honestly null — "
                        "terminal snapshot validation deferred until the "
                        "next gate round lands its current artifact")
        snap = golden_snapshot.build_snapshot(
            REPO_ROOT, "DQAEIP-Enterprise-Assurance-Validation-Release")
        problems = golden_snapshot.validate_snapshot(snap)
        assert problems == [], problems
