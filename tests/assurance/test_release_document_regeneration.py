"""Live-tree regression tests for the 2026-09-19 release-document
regeneration contracts (builder/source fixes, Phase 1).

These tests enforce, on the LIVE repository tree, the contracts that
were previously only checked by final_verification (which is not part
of the suite): the regenerated release documents must be
schema-conforming, mutually consistent, claim-fresh, and free of the
stale identities that previously failed the contradiction checker.

Mid-transition honesty: while the terminal gate round has not yet
landed its PASS artifact, the gate-derived assertions (gate verdict
PASS) are skipped with an explicit reason — exactly like the other
mid-transition skips in this battery (never a guessed PASS).
"""

import hashlib
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance import (  # noqa: E402
    limitation_registry, release_schema)


def _load(rel):
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def _gate_exists():
    return os.path.isfile(os.path.join(
        REPO_ROOT, "evidence", "release_gate",
        "final_release_gate.json"))


class TestEvidenceBuilderDependencyDirection:
    """Phase 3 bootstrap-circularity fix: the evidence builder CONSUMES
    the canonical test summary (fresh execution by
    scripts/capture_test_summary.py) and must NEVER run the full suite
    in-process — the full suite includes these very document tests,
    which read the release documents generated DOWNSTREAM of the
    evidence namespace:

        fresh test execution -> canonical test_summary
            -> evidence namespace -> release documents
            -> release gate -> observability -> final verification
    """

    BUILDER = "scripts/hardening_evidence_builder.py"
    NS_SUITE = ("evidence/FINAL_HARDENED_RELEASE_2026-09-19/test_suite/"
                "test_suite_results.json")
    LEGACY_JUNIT = ("evidence/FINAL_HARDENED_RELEASE_2026-09-19/"
                    "test_suite/_junit_full.xml")

    def test_builder_never_runs_full_suite_in_process(self):
        src = open(os.path.join(REPO_ROOT, self.BUILDER),
                   encoding="utf-8").read()
        # the removed circular mechanism: an in-process full-suite run
        # whose results depend on the documents this namespace builds
        assert 'run_pytest_junit(["tests/"])' not in src, (
            "circularity regressed: evidence builder runs the full "
            "suite in-process (its document tests read the downstream "
            "release documents)")
        # the battery run is NOT circular (no release-document reads)
        # and stays a fresh in-process run
        assert 'run_pytest_junit(["tests/hardening/"], xml)' in src

    def test_ns_suite_record_consumes_canonical_summary(self):
        if not os.path.isfile(os.path.join(REPO_ROOT, self.NS_SUITE)):
            pytest.skip("evidence namespace not built yet")
        ns_suite = _load(self.NS_SUITE)
        ts = _load("evidence/rebuild_verification/test_summary.json")
        assert ns_suite["source"] == (
            "evidence/rebuild_verification/test_summary.json")
        assert ns_suite["source_sha256"] == hashlib.sha256(
            open(os.path.join(
                REPO_ROOT, "evidence", "rebuild_verification",
                "test_summary.json"), "rb").read()).hexdigest()
        for key in ("collected", "passed", "skipped", "failed",
                    "errors"):
            assert ns_suite["stats"][key] == ts[key], key

    def test_ns_legacy_in_process_junit_artifact_absent(self):
        # the removed mechanism's artifact must not exist (the builder
        # deletes any legacy copy at build time; the canonical capture
        # is the authoritative record)
        if not os.path.isdir(os.path.dirname(os.path.join(
                REPO_ROOT, self.NS_SUITE))):
            pytest.skip("evidence namespace not built yet")
        assert not os.path.isfile(os.path.join(REPO_ROOT,
                                               self.LEGACY_JUNIT))

    def test_builder_fails_closed_on_missing_canonical_summary(
            self, tmp_path, monkeypatch):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "heb_under_test", os.path.join(REPO_ROOT, self.BUILDER))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        monkeypatch.setattr(mod, "CANON_TEST_SUMMARY",
                            tmp_path / "absent.json")
        with pytest.raises(SystemExit, match="FAIL-CLOSED"):
            mod.build_test_suite()

    def test_builder_fails_closed_on_red_canonical_summary(
            self, tmp_path, monkeypatch):
        import importlib.util
        red = tmp_path / "test_summary.json"
        red.write_text(json.dumps({
            "collected": 10, "passed": 8, "skipped": 1, "failed": 1,
            "errors": 0, "all_green": False}), encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "heb_under_test", os.path.join(REPO_ROOT, self.BUILDER))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        monkeypatch.setattr(mod, "CANON_TEST_SUMMARY", red)
        with pytest.raises(SystemExit, match="FAIL-CLOSED"):
            mod.build_test_suite()


class TestLiveReleaseDocumentSchema:
    """Gap 1/2 regression: FINAL_RESULTS + release_manifest conform to
    the certified release schema after the hardening builders run."""

    def test_live_final_results_schema_valid(self):
        problems, _ = release_schema.validate_document(
            os.path.join(REPO_ROOT, "FINAL_RESULTS.json"),
            "final_results")
        assert not problems, problems

    def test_live_final_result_mirror_schema_valid(self):
        problems, _ = release_schema.validate_document(
            os.path.join(REPO_ROOT, "final_result.json"),
            "final_results")
        assert not problems, problems

    def test_live_release_manifest_schema_valid(self):
        problems, _ = release_schema.validate_document(
            os.path.join(REPO_ROOT, "release_manifest.json"),
            "release_manifest")
        assert not problems, problems

    def test_live_final_results_identity_blocks_present(self):
        fr = _load("FINAL_RESULTS.json")
        for key in ("release_identity", "project_identity",
                    "rule_identity", "runs", "test_identity"):
            assert key in fr, f"FINAL_RESULTS missing {key}"
        assert fr["release_identity"]["release_name"] == (
            "DQAEIP-FINAL-HARDENED-RELEASE-2026-09-19")
        assert fr["runs"]["run_1"]["run_id"] == "final_3m_pass1"
        assert fr["runs"]["run_2"]["run_id"] == "final_3m_pass2"

    def test_live_release_manifest_validation_and_environment(self):
        rm = _load("release_manifest.json")
        assert "validation" in rm and isinstance(rm["validation"], dict)
        assert "environment" in rm and isinstance(rm["environment"],
                                                   dict)
        assert rm["validation"].get("tests", {}).get("passed") is not None

    def test_live_doc_heads_agree(self):
        fr = _load("FINAL_RESULTS.json")
        rm = _load("release_manifest.json")
        assert fr["git_identity"]["head"] == rm["git"]["head"]


class TestLiveClaimsFreshness:
    """Gap 3/4 regression: every value-bearing claim in the live
    FINAL_RESULTS re-derives from the current evidence tree."""

    def test_live_claims_rederive(self):
        from data_quality_platform.assurance import claims as claims_mod
        fr = _load("FINAL_RESULTS.json")
        report = claims_mod.verify_claims(fr.get("claims", []), REPO_ROOT)
        assert report["recheck_passed"], [
            r for r in report["results"] if not r["ok"]]

    def test_live_limitation_registry_is_deduplicated_17(self):
        """Verify the canonical limitation registry has exactly 17 unique
        entries (LIM-001 through LIM-017), all deduplicated.

        The count 17 reflects the canonical registry after LIM-017
        (chmod/utime audit-hook blind spot) was added to match the
        README documentation. This is not a frozen invariant — it
        tracks the canonical registry's actual entry count."""
        entries, problems = limitation_registry.load_registry(REPO_ROOT)
        assert not problems, problems
        ids = [e.get("id") for e in entries]
        assert len(ids) == 17, f"expected 17 unique limitations, " \
                               f"got {len(ids)}"
        assert len(set(ids)) == 17, "duplicate limitation ids present"
        assert sorted(ids) == [f"LIM-{i:03d}" for i in range(1, 18)]

    def test_live_final_results_limitation_count_matches_registry(self):
        fr = _load("FINAL_RESULTS.json")
        entries, _ = limitation_registry.load_registry(REPO_ROOT)
        assert len(fr["limitations"]) == len(entries)
        claim = next(c for c in fr["claims"]
                     if c.get("derivation") == "limitation_count")
        assert claim["value"] == len(entries)


class TestLiveReleaseModelArtifacts:
    """Regression for the three evidence/release model artifacts that
    previously carried the stale 2026-09-18 identity and stale test
    counts (contradiction-checker scope)."""

    def test_live_release_evidence_model_is_current(self):
        model = _load("evidence/release/release_evidence_model.json")
        assert model["release_identity"]["release_name"] == (
            "DQAEIP-FINAL-HARDENED-RELEASE-2026-09-19")
        ts = _load("evidence/rebuild_verification/test_summary.json")
        assert model["test_identity"]["collected"] == ts["collected"]
        assert model["test_identity"]["passed"] == ts["passed"]
        assert model["test_identity"]["skipped"] == ts["skipped"]

    def test_live_reproducibility_manifest_is_current(self):
        repro = _load("evidence/release/reproducibility_manifest.json")
        assert repro["release_identity"]["release_name"] == (
            "DQAEIP-FINAL-HARDENED-RELEASE-2026-09-19")
        problems = release_schema.validate_reproducibility_manifest(repro)
        assert not problems, problems

    def test_live_golden_snapshot_identity_is_current(self):
        snap = _load("evidence/release/golden_release_snapshot.json")
        assert snap["release_identity"] == (
            "DQAEIP-FINAL-HARDENED-RELEASE-2026-09-19")


class TestLiveContradictionCheck:
    """The full contradiction checker (gate 21 scope) must be
    CONSISTENT on the live tree after document regeneration."""

    def test_live_contradiction_check_consistent(self):
        from data_quality_platform.assurance import contradiction_checker
        report = contradiction_checker.run_contradiction_check(REPO_ROOT)
        assert report["verdict"] == "CONSISTENT", \
            report["contradictions"][:10]


class TestLiveDocumentFingerprints:
    """Gap 4/5 regression: RELEASE_NOTES carries the current I/O hash
    fingerprints; README carries the evidence-derived values the §10
    checker requires."""

    def test_release_notes_carry_io_fingerprints(self):
        fr = _load("FINAL_RESULTS.json")
        notes = open(os.path.join(REPO_ROOT, "RELEASE_NOTES.md"),
                     encoding="utf-8").read()
        inp = fr["verification"]["input_sha256"]
        out = fr["verification"]["output_sha256"]
        assert inp[:16] in notes, "RELEASE_NOTES missing input " \
                                  "fingerprint"
        assert out[:16] in notes, "RELEASE_NOTES missing output " \
                                  "fingerprint"

    def test_readme_carry_io_fingerprints(self):
        fr = _load("FINAL_RESULTS.json")
        readme = open(os.path.join(REPO_ROOT, "README.md"),
                      encoding="utf-8").read()
        assert fr["verification"]["input_sha256"][:16] in readme
        assert fr["verification"]["output_sha256"][:16] in readme

    def test_readme_only_authoritative_full_shas(self):
        """The README consistency checker rejects any full 64-hex SHA
        that is not one of the four authoritative hashes (input /
        output / checker / frozen V1)."""
        import re
        readme = open(os.path.join(REPO_ROOT, "README.md"),
                      encoding="utf-8").read()
        fr = _load("FINAL_RESULTS.json")
        rp = _load("evidence/rebuild_verification/"
                   "run_pair_verification.json")
        import hashlib
        v1_sha = hashlib.sha256(open(
            os.path.join(REPO_ROOT, "data_quality_platform", "rules",
                         "v1_rules.py"), "rb").read()).hexdigest()
        authoritative = {
            fr["verification"]["input_sha256"],
            fr["verification"]["output_sha256"],
            rp.get("checker_script_sha256_actual"),
            v1_sha,
        }
        found = set(re.findall(r"\b[0-9a-f]{64}\b", readme))
        stale = found - authoritative
        assert not stale, f"stale/unknown full SHAs in README: " \
                          f"{[s[:12] for s in stale]}"

    def test_readme_consistency_check_live(self):
        # the §10 checker derives its required values from the live
        # evidence — including the release-gate artifact; mid-transition
        # (terminal gate round pending) it honestly reports the missing
        # gate source, so the full CONSISTENT verdict is asserted only
        # once the gate artifact exists (same discipline as the other
        # mid-transition skips; never a guessed PASS)
        if not _gate_exists():
            pytest.skip("live release-gate artifact absent (mid-"
                        "transition): the §10 checker honestly reports "
                        "the gate source missing — CONSISTENT is "
                        "asserted once the terminal gate round lands "
                        "its artifact")
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        import readme_consistency_check as rcc
        result = rcc.run_check(REPO_ROOT)
        assert result["verdict"] == "CONSISTENT", result["problems"][:10]


class TestLiveGateDocumentState:
    """The documents' gate verdict claims must match the live gate
    artifact state (never a premature PASS; PASS claimed only from the
    live artifact)."""

    def test_gate_verdict_claims_match_live_artifact(self):
        fr = _load("FINAL_RESULTS.json")
        claimed = fr["verification"].get("release_gate_verdict")
        rm = _load("release_manifest.json")
        rm_claimed = rm["validation"].get("release_gate_verdict")
        if not _gate_exists():
            assert claimed in (None, "NOT_VERIFIED")
            assert rm_claimed in (None, "NOT_VERIFIED")
        else:
            gate = _load("evidence/release_gate/"
                         "final_release_gate.json")
            live = gate.get("overall_verdict")
            if live == "PASS":
                # terminal state: the documents MUST carry the live
                # PASS (a stale NOT_VERIFIED after the gate lands is
                # caught here)
                assert claimed == "PASS"
                assert rm_claimed == "PASS"
            else:
                # two-stage build discipline (the same semantics
                # release_chain encodes on the root_to_gate edge): a
                # live FAIL round is a NON-terminal state — the
                # documents must stay pending. Claiming PASS here
                # would be an overclaim (caught); claiming FAIL is
                # forbidden by the chain's gate_to_results edge
                # (only PASS or pending are valid document claims).
                assert claimed in (None, "NOT_VERIFIED")
                assert rm_claimed in (None, "NOT_VERIFIED")

    def test_readme_gate_claim_matches_live_artifact(self):
        readme = open(os.path.join(REPO_ROOT, "README.md"),
                      encoding="utf-8").read()
        if _gate_exists():
            gate = _load("evidence/release_gate/"
                         "final_release_gate.json")
            n = gate.get("gate_count")
            # the gate-count identity strings are required whenever a
            # live gate artifact exists (verdict-independent: the
            # count is a structural property of the gate; a pending
            # README row carries them too)
            assert f"{n} fail-closed gates" in readme
            assert f"{n}-gate" in readme
            if gate.get("overall_verdict") == "PASS":
                # terminal PASS is claimed from the live artifact only
                assert f"PASS — {n}/{n} fail-closed gates" in readme
        else:
            # Anti-regression: when no live gate artifact exists,
            # README must not claim ANY "PASS — N/N fail-closed gates"
            # string (any N). The previous hardcoded "22/22" check
            # became stale after B-8 introduced 24 gates; we now use a
            # regex pattern to catch any premature PASS claim.
            import re
            pattern = re.compile(
                r"PASS\s+—\s+\d+/\d+\s+fail-closed\s+gates")
            assert not pattern.search(readme), \
                "README claims a gate PASS without the live artifact"


# ============================================================
# Anti-regression contract tests (B-8 remediation)
# ============================================================
# These tests enforce the canonical-source architecture:
#   - GATE_VERSION and GATE_COUNT constants in release_gate.py
#     are the single source of truth for gate identity
#   - README current checker SHA must match the live sha256 of
#     scripts/final_3m_validation.py (not a stale hardcoded value)
#   - README gate count must match GATE_COUNT (not hardcoded 22)
#   - README test counts must match evidence/rebuild_verification/
#     test_summary.json
#   - README build HEAD must match RELEASE_IDENTITY.json
#     .git_commit_at_build (H-4 ANCESTOR semantics)
#   - README must document the B-8 trusted fingerprint
#   - If GATE_COUNT != 22, README must NOT contain "22/22"
#   - Historical checker SHA must remain distinguishable from current
#   - H-4 release identity must remain ancestor-based, not equality
# ============================================================


def _import_release_gate_constants():
    """Helper: import GATE_VERSION and GATE_COUNT from
    scripts/release_gate.py (load dynamically so test fails clearly
    if release_gate.py is broken)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "release_gate",
        os.path.join(REPO_ROOT, "scripts", "release_gate.py"))
    rg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rg)
    return rg.GATE_VERSION, rg.GATE_COUNT, rg.TRUSTED_SIGNING_KEY_FINGERPRINT


class TestAntiRegressionCanonicalContracts:
    """Anti-regression: enforce that README and canonical evidence
    agree on every current release fact. These tests catch the
    specific class of regression where a release commit modifies
    release_gate.py (or final_3m_validation.py) but forgets to
    regenerate the canonical evidence files and README.
    """

    def test_01_gate_version_constant_is_4_0_0(self):
        """1: GATE_VERSION in release_gate.py is '4.0.0' (B-8
        release gate version)."""
        gv, _, _ = _import_release_gate_constants()
        assert gv == "4.0.0", (
            f"GATE_VERSION drifted from 4.0.0 to {gv!r}; if this is "
            f"intentional, update this test to the new version")

    def test_02_gate_count_constant_is_24(self):
        """2: GATE_COUNT in release_gate.py is 24 (22 original
        + 2 B-8: commit_signature + baseline_signature)."""
        _, gc, _ = _import_release_gate_constants()
        assert gc == 24, (
            f"GATE_COUNT drifted from 24 to {gc!r}; if this is "
            f"intentional (e.g. a new gate was added or removed), "
            f"update this test and the GATE_COUNT constant in "
            f"release_gate.py together")

    def test_03_readme_current_checker_sha_matches_live(self):
        """3: README's current checker SHA prefix must match the
        live sha256 of scripts/final_3m_validation.py. The previous
        hardcoded `0ef7c10c...` (historical certified) became stale
        after B-8 hardened the checker to `d216dbca...`."""
        checker_path = os.path.join(
            REPO_ROOT, "scripts", "final_3m_validation.py")
        with open(checker_path, "rb") as f:
            actual_sha = hashlib.sha256(f.read()).hexdigest()
        actual_prefix = actual_sha[:16]
        readme = open(os.path.join(REPO_ROOT, "README.md"),
                      encoding="utf-8").read()
        # README must contain the current SHA prefix somewhere
        assert actual_prefix in readme, (
            f"README does not contain the current checker SHA prefix "
            f"{actual_prefix}; the README may be presenting the stale "
            f"historical SHA 0ef7c10c... as the current SHA. Update "
            f"README to mention '{actual_prefix}...' as the current "
            f"hardened checker SHA, with 0ef7c10c... explicitly "
            f"labeled as the historical certified baseline")

    def test_04_readme_gate_count_matches_canonical(self):
        """4: README must contain the canonical GATE_COUNT/N
        fail-closed gates string (not the stale '22/22')."""
        _, gate_count, _ = _import_release_gate_constants()
        readme = open(os.path.join(REPO_ROOT, "README.md"),
                      encoding="utf-8").read()
        expected = f"{gate_count}/{gate_count} fail-closed gates"
        assert expected in readme, (
            f"README does not contain '{expected}'; it may still "
            f"contain the stale '22/22 fail-closed gates' from before "
            f"B-8. Update README to use {gate_count}/{gate_count}")

    def test_05_readme_test_counts_match_canonical(self):
        """5: README's test counts must match the canonical
        evidence/rebuild_verification/test_summary.json (not stale
        1098/1089)."""
        ts = _load("evidence/rebuild_verification/test_summary.json")
        readme = open(os.path.join(REPO_ROOT, "README.md"),
                      encoding="utf-8").read()
        assert f"{ts['collected']} collected" in readme, (
            f"README does not mention '{ts['collected']} collected'; "
            f"it may still contain the stale '1098 collected' from "
            f"before the B-8 remediation. Update README to use the "
            f"current test count {ts['collected']}")
        assert f"{ts['passed']} passed" in readme, (
            f"README does not mention '{ts['passed']} passed'; it "
            f"may still contain the stale '1089 passed' from before "
            f"the B-8 remediation. Update README to use the current "
            f"test count {ts['passed']}")

    def test_06_readme_build_head_matches_release_identity(self):
        """6: README must mention the build HEAD recorded in
        RELEASE_IDENTITY.json.git_commit_at_build (H-4 ANCESTOR
        semantics — the build commit is the parent of the release
        commit, NOT strict equality with live HEAD)."""
        ident = _load(
            "evidence/FINAL_HARDENED_RELEASE_2026-09-19/"
            "release_identity/RELEASE_IDENTITY.json")
        build_head = ident.get("git_commit_at_build", "")
        assert build_head, (
            "RELEASE_IDENTITY.json git_commit_at_build is missing or "
            "empty; cannot verify README build HEAD")
        readme = open(os.path.join(REPO_ROOT, "README.md"),
                      encoding="utf-8").read()
        # README must contain at least the first 16 chars of the build HEAD
        assert build_head[:16] in readme, (
            f"README does not contain build HEAD prefix "
            f"'{build_head[:16]}'; it may still contain the stale "
            f"970b57f7... from before B-8. Update README to use the "
            f"current build HEAD {build_head[:16]}...")

    def test_07_readme_contains_b8_trusted_fingerprint(self):
        """7: README must document the B-8 trusted fingerprint
        (currently undocumented — Phase 11 adds B-8 Trust Anchor
        section)."""
        _, _, trusted_fp = _import_release_gate_constants()
        readme = open(os.path.join(REPO_ROOT, "README.md"),
                      encoding="utf-8").read()
        assert trusted_fp in readme, (
            f"README does not document the B-8 trusted fingerprint "
            f"{trusted_fp}; the B-8 Trust Anchor section is missing "
            f"or incomplete. Add a 'B-8 Trust Anchor' section to "
            f"README documenting GATE_VERSION=4.0.0, "
            f"GATE_COUNT={24 if _import_release_gate_constants()[1] == 24 else '(see release_gate.py)'}, "
            f"the trusted fingerprint, the public key path, and the "
            f"detached signature paths")

    def test_08_readme_does_not_claim_stale_22_when_canonical_is_24(self):
        """8: Anti-regression — if GATE_COUNT is 24, README must NOT
        contain '22/22 fail-closed gates' (which would be a stale
        claim). The previous README contained '22/22' in 6 places
        even after B-8 introduced 24 gates."""
        _, gate_count, _ = _import_release_gate_constants()
        readme = open(os.path.join(REPO_ROOT, "README.md"),
                      encoding="utf-8").read()
        if gate_count != 22:
            assert "22/22 fail-closed gates" not in readme, (
                f"README still contains '22/22 fail-closed gates' "
                f"but GATE_COUNT is {gate_count}; update README to "
                f"use {gate_count}/{gate_count} consistently")

    def test_09_historical_checker_sha_distinguishable_from_current(self):
        """9: README must explicitly distinguish the historical
        certified checker SHA (0ef7c10c...) from the current hardened
        checker SHA. The previous README conflated them in 4 places
        (lines 432, 515, 574, 694 presented 0ef7c10c as 'current')."""
        readme = open(os.path.join(REPO_ROOT, "README.md"),
                      encoding="utf-8").read()
        # The historical SHA prefix must be labeled historical
        historical_prefix = "0ef7c10c"
        # README must contain the word "historical" near the historical SHA
        # OR explicitly call out "current" + "historical" for the checker
        assert (("historical" in readme.lower() and
                 historical_prefix in readme) or
                ("current" in readme.lower() and
                 "d216dbca" in readme)), (
            "README does not explicitly distinguish historical vs "
            "current checker SHA; both must be present and clearly "
            "labeled (current=d216dbca..., historical=0ef7c10c...)")

    def test_10_h4_release_identity_remains_ancestor_based(self):
        """10: H-4 release identity must remain ANCESTOR-based, not
        equality-based. The build commit (recorded in
        RELEASE_IDENTITY.json.git_commit_at_build) must be an ancestor
        of the live HEAD, NOT equal to it. The previous H-4 fix
        established this; this test guards against regression to
        strict equality (which would create a circular dependency:
        evidence cannot record its own commit's SHA)."""
        import subprocess
        ident = _load(
            "evidence/FINAL_HARDENED_RELEASE_2026-09-19/"
            "release_identity/RELEASE_IDENTITY.json")
        build_commit = ident.get("git_commit_at_build", "")
        assert build_commit, "RELEASE_IDENTITY.json git_commit_at_build missing"
        # The build commit must be an ancestor of HEAD (or equal,
        # which is the trivial case). What is FORBIDDEN is requiring
        # strict equality AND failing when they differ — that would
        # create circularity. The ancestor check is the correct
        # semantic.
        anc = subprocess.run(
            ["git", "-C", REPO_ROOT, "merge-base", "--is-ancestor",
             build_commit, "HEAD"],
            capture_output=True)
        assert anc.returncode == 0, (
            f"H-4 ANCESTOR check failed: build commit {build_commit} "
            f"is NOT an ancestor of live HEAD. This breaks the "
            f"release-identity model. Either the recorded build "
            f"commit is wrong, or HEAD has been rewound/rewritten "
            f"to a state where the recorded build commit is no "
            f"longer in the ancestry")


class TestCanonicalGateCountContract:
    """Anti-regression: GATE_COUNT constant in release_gate.py must
    match the structural count of gate_*() calls in the run() method.
    This catches the case where a developer adds or removes a gate
    from run() but forgets to update GATE_COUNT."""

    def test_gate_count_constant_matches_structural_run_count(self):
        """The GATE_COUNT constant must equal the number of gate_*()
        invocations in the GateRunner.run() method."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "release_gate",
            os.path.join(REPO_ROOT, "scripts", "release_gate.py"))
        rg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rg)
        # The run() method should produce exactly GATE_COUNT gates
        # when executed. We verify the structural count by parsing
        # the source and counting self.gate_*() invocations inside
        # the run() method (excluding self.fail calls).
        import re
        src = open(os.path.join(
            REPO_ROOT, "scripts", "release_gate.py"),
            encoding="utf-8").read()
        # Find the run() method body
        run_match = re.search(
            r"def run\(self\):.*?(?=\n    def |\nclass |\Z)",
            src, re.DOTALL)
        assert run_match, "Could not find run() method in release_gate.py"
        run_body = run_match.group(0)
        # Count distinct self.gate_X() calls (NOT self.fail() which is a
        # different method). gate_test_category is called multiple times
        # with different args; we count those as separate invocations.
        gate_calls = re.findall(
            r"self\.(gate_[a-z_]+)\s*\(", run_body)
        # Remove self.fail() — not a gate
        gate_calls = [c for c in gate_calls if c != "fail"]
        # Note: gate_test_category appears 5 times (5 test categories),
        # each counts as a separate gate. The structural count is
        # the number of self.gate_X() invocations, not unique method
        # names.
        structural_count = len(gate_calls)
        assert structural_count == rg.GATE_COUNT, (
            f"GATE_COUNT drift: structural run() count is "
            f"{structural_count} but GATE_COUNT constant is "
            f"{rg.GATE_COUNT}. Update GATE_COUNT in release_gate.py "
            f"to match the number of gate_*() invocations in run()")
