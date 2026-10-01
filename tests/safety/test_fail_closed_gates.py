"""Consolidated fail-closed safety tests (DQAVP hardening, Section 17).

Every security/safety gate must have at least one negative test. This
module consolidates the scenarios not already covered elsewhere and
maps the full checklist to its covering test:

Scenario                                Covered by
---------------------------------------------------------------------
corrupted input                         test_input_contract.py (module+CLI)
missing evidence                        test_evidence_validator.py
modified evidence (row counts)          test_evidence_validator.py
modified evidence (lineage repr leak)   test_evidence_validator.py
wrong hash (rule/file format)           test_evidence_validator.py
wrong rule version                      HERE (registry)
missing rule                            HERE (registry + engine path)
invalid schema                          test_schema.py + failure path tests
unexpected column                       test_input_contract.py
malformed configuration                 test_input_contract.py + HERE
missing reference                       HERE (reference registry fail-closed)
invalid reference hash                  test_rule_oracle_consistency.py
                                        (transcription fidelity pins)
altered output                          test_evidence_validator.py
                                        (file hash mismatch)
tampered manifest                       test_evidence_validator.py
unauthorized mutation attempt           HERE (SP1/E1/ClickHouse boundaries)
source mutation attempt                 test_replay.py + 3M harness
determinism violation                    HERE + test_replay.py
"""

import csv
import os

import pytest

from data_quality_platform.contracts import SOURCE_COLUMNS
from data_quality_platform.rules.base import Rule
from data_quality_platform.rules.registry import (
    RuleRegistry, RuleRegistryError,
)
from data_quality_platform.validation.replay import (
    ReplayMismatch, replay_dataset,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


class _StubRule(Rule):
    """A deliberately foreign rule (not in the V1 required set)."""

    @property
    def rule_id(self):
        return "totally_new_rule"

    @property
    def rule_version(self):
        return "9.9.9"

    def execute(self, row):
        return 0

    def execute_sql_template(self):
        return ""

    def description(self):
        return "stub"


class _EmailBlankLike(Rule):
    @property
    def rule_id(self):
        return "email_blank"

    @property
    def rule_version(self):
        return "1.0.0"

    def execute(self, row):
        email = row.get("email_address")
        return 1 if email is None or str(email).strip() == "" else 0

    def execute_sql_template(self):
        return ""

    def description(self):
        return ""


class TestMissingRuleGate:
    def test_registry_without_required_rule_fails_validation(self):
        registry = RuleRegistry()
        valid, errors, _ = registry.validate()
        assert valid is False
        assert any("Missing required rules" in e for e in errors)

    def test_execute_all_with_missing_rule_raises(self):
        registry = RuleRegistry()
        with pytest.raises(RuleRegistryError):
            registry.execute_all({"id": "1"})


class TestWrongRuleVersionGate:
    def test_duplicate_rule_id_with_different_version_rejected(self):
        from data_quality_platform.rules.v1_rules import EmailBlank

        class VersionBumped(EmailBlank):
            @property
            def rule_version(self):
                return "2.0.0"

        registry = RuleRegistry.create_default()
        with pytest.raises(RuleRegistryError, match="different version"):
            registry.register(VersionBumped())

    def test_unexpected_foreign_rule_never_enters_execution_path(self):
        registry = RuleRegistry.create_default()
        registry.register(_StubRule())
        valid, errors, warnings = registry.validate()
        assert valid is True  # required set intact
        assert any("Unexpected rules" in w for w in warnings)
        executed = [r.rule_id for r in registry.get_all_rules()]
        assert _StubRule().rule_id not in executed


class TestMalformedConfigurationGate:
    def test_missing_explicit_config_is_a_hard_error(self, tmp_path):
        """CLI N1 hardening: an explicitly supplied --config path that
        does not exist must block validation (exit 2, no silent
        fallback)."""
        import subprocess
        import sys
        proc = subprocess.run(
            [sys.executable, "-m", "runner.cli", "validate",
             "--csv", "whatever.csv", "--output", str(tmp_path / "o.csv"),
             "--config", str(tmp_path / "nope.yaml")],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=120)
        assert proc.returncode == 2
        assert "explicit --config path does not exist" in proc.stderr

    def test_invalid_thresholds_block_at_preflight(self, tmp_path):
        from data_quality_platform.validation.input_contract import (
            InputContractError, validate_input_contract,
        )

        class BadConfig:
            def get_quality_thresholds(self):
                return {"validity": 42.0}

        p = tmp_path / "ok.csv"
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(SOURCE_COLUMNS)
            w.writerow([""] * 33)
        with pytest.raises(InputContractError):
            validate_input_contract(str(p), config=BadConfig())


class TestMissingReferenceGate:
    def test_reference_registry_records_undelivered_references_honestly(
            self):
        from data_quality_platform.verification.reference_provenance \
            import build_reference_registry
        reg = build_reference_registry()
        dl = reg["references"]["dl_geography_cases_company_fixture"]
        assert dl["status"] == "UNVERIFIED"
        assert dl["sha256"] is None
        assert reg["unverified_count"] >= 1

    def test_sp1_missing_references_fail_closed_not_assessable(self):
        """With no reference data available, SP1 must fail closed to
        'not assessable' (reference_resolved=False) — never fabricate a
        canonical state and never crash into a default decision."""
        from data_quality_platform.geography.canonical import (
            evaluate_geography,
        )
        from data_quality_platform.geography.references import (
            InMemoryTwoReferenceProvider,
        )
        provider = InMemoryTwoReferenceProvider([], [])
        decision = evaluate_geography("12345", "NY", provider)
        assert decision.reference_resolved is False
        assert decision.zip_state_assessable is False
        assert decision.zip_state_mismatch is False
        assert decision.canonical_state is None

    def test_sp1_reference_unavailable_error_is_never_swallowed(self):
        """A physical provider that CANNOT load its authorized reference
        must raise ReferenceUnavailableError, and the evaluation path
        must let that error propagate (never swallow it into a
        fabricated fallback decision)."""
        from data_quality_platform.geography.canonical import (
            evaluate_geography,
        )
        from data_quality_platform.geography.references import (
            ReferenceUnavailableError,
        )

        class ExplodingProvider:
            def canonical_states(self, zip5):
                raise ReferenceUnavailableError(
                    "authorized physical reference not delivered")

            def cross_states(self, zip5):
                raise ReferenceUnavailableError(
                    "authorized physical reference not delivered")

        with pytest.raises(ReferenceUnavailableError):
            evaluate_geography("12345", "NY", ExplodingProvider())


class TestUnauthorizedMutationBoundaries:
    def test_sp1_remains_unregistered_and_non_default(self):
        registry = RuleRegistry.create_default()
        ids = {r.rule_id for r in registry.get_all_rules()}
        assert len(ids) == 8
        assert "geography_canonical" not in ids
        assert not any("sp1" in i for i in ids)

    def test_no_clickhouse_client_or_mutation_code_in_production(self):
        import subprocess
        result = subprocess.run(
            ["grep", "-rln", "-E",
             "clickhouse_driver|ClickHouseClient|ALTER TABLE|INSERT INTO",
             "--include=*.py", "data_quality_platform/", "runner/"],
            cwd=REPO_ROOT, capture_output=True, text=True)
        assert not result.stdout.strip(), (
            f"ClickHouse client / mutation code found: {result.stdout}")

    def test_no_e1_identifiers_in_production_code(self):
        import subprocess
        result = subprocess.run(
            ["grep", "-rln", "-E",
             "e1_|E1Experiment|experiment_e1",
             "--include=*.py", "data_quality_platform/", "runner/",
             "scripts/"],
            cwd=REPO_ROOT, capture_output=True, text=True)
        assert not result.stdout.strip(), result.stdout


class TestDeterminismGateFailClosed:
    def test_non_deterministic_registry_fails_replay(self, tmp_path):
        """A rule whose hash changes between runs must FAIL the replay
        (determinism gate), never pass silently."""

        state = {"n": 0}

        class ShiftingHash(_EmailBlankLike):
            @property
            def hash(self):
                state["n"] += 1
                return f"{state['n']:064d}"

        def factory():
            reg = RuleRegistry()
            for rule in RuleRegistry.create_default().get_all_rules():
                if rule.rule_id == "email_blank":
                    reg.register(ShiftingHash())
                else:
                    reg.register(rule)
            return reg

        p = tmp_path / "in.csv"
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(SOURCE_COLUMNS)
            row = {c: "" for c in SOURCE_COLUMNS}
            row.update({"id": "1", "email_address": ""})
            w.writerow([row[c] for c in SOURCE_COLUMNS])

        with pytest.raises(ReplayMismatch):
            replay_dataset(str(p), runs=2, work_dir=str(tmp_path / "w"),
                           registry_factory=factory)
