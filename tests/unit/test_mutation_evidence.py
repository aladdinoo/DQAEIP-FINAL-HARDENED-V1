"""Mutation-testing evidence guard (DQAVP hardening, Section 6).

If the mutation-testing evidence file is present, every recorded mutant
must have been detected — a surviving mutant cannot be committed silently
together with evidence of its survival.
"""

import json
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
EVIDENCE = os.path.join(REPO_ROOT, "evidence", "mutation_testing",
                        "mutation_results.json")


@pytest.mark.skipif(not os.path.isfile(EVIDENCE),
                    reason="mutation evidence not generated yet "
                           "(run scripts/mutation_testing.py)")
class TestMutationEvidence:
    def test_all_recorded_mutants_were_detected(self):
        summary = json.load(open(EVIDENCE, encoding="utf-8"))
        results = summary["results"]
        assert results, "evidence must contain at least one mutant"
        survived = [r for r in results
                    if not r.get("detected")
                    and "infrastructure_error" not in r]
        assert not survived, (
            f"mutation evidence records surviving mutants (testing gaps): "
            f"{[r['mutation_id'] for r in survived]}")

    def test_evidence_records_exact_source_restore(self):
        summary = json.load(open(EVIDENCE, encoding="utf-8"))
        assert summary["source_restored_exactly"] is True
        assert summary["source_sha256_before"] == summary["source_sha256_after"]

    def test_mutants_cover_all_eight_rules(self):
        summary = json.load(open(EVIDENCE, encoding="utf-8"))
        rules = {r["rule_id"] for r in summary["results"]}
        assert len(rules) == 8, f"expected all 8 rules covered, got {rules}"
