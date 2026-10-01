"""Golden regression corpus tests (DQAVP hardening, Section 12).

Loads tests/golden/regression_corpus.json (built by
scripts/build_regression_corpus.py) and enforces:

1. Every case's expected 8-flag decisions match the CURRENT production
   rules (compatibility baseline — any V1 behavior change fails here).
2. Every case also agrees with the independent oracle (triangulation).
3. review_required cases are explicitly enumerated and never silently
   resolved.
"""

import importlib.util
import json
import os
import sys

import pytest

from data_quality_platform.contracts import FLAG_COLUMNS, SOURCE_COLUMNS
from data_quality_platform.rules.registry import RuleRegistry

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
CORPUS_PATH = os.path.join(REPO_ROOT, "tests", "golden",
                           "regression_corpus.json")

_spec = importlib.util.spec_from_file_location(
    "f3m_corpus_oracle",
    os.path.join(REPO_ROOT, "scripts", "final_3m_validation.py"))
F3M = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("f3m_corpus_oracle", F3M)
_spec.loader.exec_module(F3M)

CORPUS = json.load(open(CORPUS_PATH, encoding="utf-8"))
CASES = CORPUS["cases"]


def _full_row(case):
    row = {c: "" for c in SOURCE_COLUMNS}
    row.update({k: ("" if v is None else v)
                for k, v in case["input"].items()})
    row.setdefault("id", case["case_id"])
    return row


class TestCorpusIntegrity:
    def test_corpus_exists_and_non_empty(self):
        assert CASES, "regression corpus must exist with cases"

    def test_corpus_covers_all_rule_areas(self):
        assert set(CORPUS["areas"]) == {"email", "geography", "name"}

    def test_every_case_has_all_eight_expected_flags(self):
        for case in CASES:
            assert sorted(case["expected"]) == sorted(FLAG_COLUMNS), \
                case["case_id"]

    def test_review_required_cases_are_enumerated(self):
        review = [c["case_id"] for c in CASES if c["review_required"]]
        assert review == ["RC-R01", "RC-R02"], (
            f"review_required set changed: {review} — update the corpus "
            f"policy documentation when resolving or adding reviews")


class TestCorpusDecisions:
    @pytest.mark.parametrize("case", CASES, ids=[c["case_id"]
                                                 for c in CASES])
    def test_production_rules_match_expected(self, case):
        registry = RuleRegistry.create_default()
        row = _full_row(case)
        for rule in registry.get_all_rules():
            actual = rule.execute(row)
            assert actual == case["expected"][rule.rule_id], (
                f"{case['case_id']} / {rule.rule_id}: "
                f"expected {case['expected'][rule.rule_id]}, "
                f"got {actual} — V1 behavior changed or corpus stale")

    @pytest.mark.parametrize("case", CASES, ids=[c["case_id"]
                                                 for c in CASES])
    def test_independent_oracle_matches_expected(self, case):
        row = _full_row(case)
        oracle = F3M.oracle_flags(row)
        for flag in FLAG_COLUMNS:
            assert oracle[flag] == case["expected"][flag], (
                f"{case['case_id']} / {flag}: oracle {oracle[flag]} != "
                f"corpus {case['expected'][flag]} — corpus build "
                f"cross-check was bypassed; rebuild the corpus")


class TestReviewRequiredPolicy:
    def test_review_cases_still_pin_v1_behavior(self):
        """REVIEW_REQUIRED cases pin CURRENT V1 behavior as the
        compatibility baseline; resolving the review is a governed
        change, not a test edit."""
        registry = RuleRegistry.create_default()
        for case in CASES:
            if not case["review_required"]:
                continue
            row = _full_row(case)
            for rule in registry.get_all_rules():
                assert rule.execute(row) == case["expected"][rule.rule_id]

    def test_review_cases_document_their_reason(self):
        for case in CASES:
            if case["review_required"]:
                assert "REVIEW" in case["origin"] or \
                    case["origin"].strip(), case["case_id"]
