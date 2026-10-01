"""Rule impact analysis tests (DQAVP hardening, Section 7)."""

import pytest

from data_quality_platform.rules.registry import RuleRegistry
from data_quality_platform.validation.impact_analysis import (
    RuleImpactAnalyzer, load_rows_csv,
)


def _rows():
    return [
        {"id": "1", "email_address": "a@b.co", "zip": "10001",
         "state": "NY", "first_name": "Alice", "last_name": "Doe"},
        {"id": "2", "email_address": "", "zip": "90210",
         "state": "CA", "first_name": "Bo", "last_name": "Bo"},
        {"id": "3", "email_address": "bad..dots@x.com", "zip": "75201",
         "state": "tx", "first_name": "Cy", "last_name": "Ray"},
    ]


class TestImpactAnalysis:
    def setup_method(self):
        self.registry = RuleRegistry.create_default()
        self.analyzer = RuleImpactAnalyzer(self.registry, _rows())

    def test_identical_proposal_yields_zero_changes(self):
        diff = self.analyzer.compare_rule(
            "email_blank", lambda row: self.registry.get("email_blank").execute(row))
        assert diff.rows_evaluated == 3
        assert diff.changed_decisions == 0
        assert diff.additions == 0 and diff.removals == 0
        assert diff.old_flag_count == diff.new_flag_count == 1
        assert diff.proposal_activated is False

    def test_additive_proposal_counted(self):
        # flags everything with an id (superset of blank)
        diff = self.analyzer.compare_rule("email_blank", lambda row: 1)
        assert diff.changed_decisions == 2
        assert diff.additions == 2 and diff.removals == 0
        assert diff.old_flag_count == 1 and diff.new_flag_count == 3
        assert len(diff.changed_row_sample) == 2

    def test_removing_proposal_counted(self):
        diff = self.analyzer.compare_rule("email_blank", lambda row: 0)
        assert diff.changed_decisions == 1
        assert diff.additions == 0 and diff.removals == 1
        assert diff.new_flag_count == 0

    def test_changed_row_sample_has_identity_and_decisions(self):
        diff = self.analyzer.compare_rule("email_blank", lambda row: 1)
        sample = diff.changed_row_sample[0]
        assert sample["row_number"] == 2  # first data row (header offset)
        assert sample["old_decision"] == 0
        assert sample["new_decision"] == 1
        assert "id" in sample["identity"]

    def test_unknown_rule_fails_closed(self):
        with pytest.raises(KeyError):
            self.analyzer.compare_rule("nope_rule", lambda row: 0)

    def test_non_callable_proposal_fails_closed(self):
        with pytest.raises(TypeError):
            self.analyzer.compare_rule("email_blank", "not callable")

    def test_non_binary_proposal_fails_closed(self):
        with pytest.raises(ValueError):
            self.analyzer.compare_rule("email_blank", lambda row: 2)

    def test_raising_proposal_fails_closed(self):
        def boom(row):
            raise RuntimeError("proposal crashed")

        with pytest.raises(RuntimeError):
            self.analyzer.compare_rule("email_blank", boom)

    def test_to_dict_marks_proposal_not_activated(self):
        diff = self.analyzer.compare_rule("email_blank", lambda row: 0)
        assert diff.to_dict()["proposal_activated"] is False

    def test_load_rows_csv(self, tmp_path):
        p = tmp_path / "d.csv"
        p.write_text("id,email_address\n1,a@b.co\n2,\n")
        rows = load_rows_csv(str(p))
        assert len(rows) == 2
        with pytest.raises(FileNotFoundError):
            load_rows_csv(str(tmp_path / "missing.csv"))
        empty = tmp_path / "empty.csv"
        empty.write_text("id\n")
        with pytest.raises(ValueError):
            load_rows_csv(str(empty))
