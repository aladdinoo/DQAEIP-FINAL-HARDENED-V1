"""N-16 — derive_truth null/meaningless evidence bypass — focused tests.

These tests pin the N-16 fix in data_quality_platform/assurance/
contradiction_checker.py. The fix introduces a new
'is_meaningful_truth_value' helper and a 'meaningless' truth-source
status: a truth source whose JSON document loaded successfully but
whose required truth fields are null/empty/absent is marked
'meaningless' (not 'ok'), so the verdict falls back to NOT_VERIFIED
instead of silently becoming CONSISTENT.

Pre-fix behavior (confirmed in the prior forensic audit):
  - tampered FINAL_RESULTS.json with rows=null → verdict=CONSISTENT
  - empty f3m dict {} → verdict=CONSISTENT
  - all truth sources nulled simultaneously → verdict=CONSISTENT

Post-fix behavior (these tests):
  - ANY malformed/null/empty truth source → verdict=NOT_VERIFIED
  - legitimate complete evidence → verdict=CONSISTENT (unchanged)
  - legitimate rows=0 / gate_count=0 / False → meaningful (unchanged)

Tests do NOT modify production code. Truth sources are synthesized
in a tmp_path that mirrors the repo's evidence layout."""

import json
import os
import shutil
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance import contradiction_checker as cc


# ────────────────────────────────────────────────────────────────────
# Helpers — build a skeleton repo with the truth-source layout
# ────────────────────────────────────────────────────────────────────

def _build_skeleton_repo(tmp):
    """Build a repo skeleton with all directories/files that
    _collect_current_docs and derive_truth expect. Tests inject
    tampered content per-case."""
    for d in (
        os.path.join("evidence", "validation", "2026-09-19", "fresh_3m2"),
        os.path.join("evidence", "rebuild_verification"),
        os.path.join("evidence", "release_gate"),
        os.path.join("evidence", "release"),
        os.path.join("evidence"),
        os.path.join("scripts"),
        os.path.join("data_quality_platform", "rules"),
    ):
        os.makedirs(os.path.join(tmp, d), exist_ok=True)
    # README and RELEASE_NOTES (markdown docs scanned by check_prose):
    with open(os.path.join(tmp, "README.md"), "w") as f:
        f.write("# Test repo\n")
    with open(os.path.join(tmp, "RELEASE_NOTES.md"), "w") as f:
        f.write("# Test release notes\n")
    # rule source + checker files (real files so derive_truth can
    # compute their sha256):
    with open(os.path.join(tmp, "data_quality_platform", "rules",
                            "v1_rules.py"), "w") as f:
        f.write("# placeholder v1_rules\n")
    with open(os.path.join(tmp, "scripts", "final_3m_validation.py"), "w") as f:
        f.write("# placeholder final_3m_validation\n")
    # release_manifest.json:
    with open(os.path.join(tmp, "release_manifest.json"), "w") as f:
        json.dump({"release_name": "TEST", "release_date": "2026-09-26"},
                  f)
    # release_gate final result:
    with open(os.path.join(tmp, "evidence", "release_gate",
                            "final_release_gate.json"), "w") as f:
        json.dump({"gate_count": 22, "overall_verdict": "PASS"}, f)
    # test_summary:
    with open(os.path.join(tmp, "evidence", "rebuild_verification",
                            "test_summary.json"), "w") as f:
        json.dump({"collected": 100, "passed": 100, "skipped": 0,
                    "failed": 0, "errors": 0}, f)


GOOD_F3M = {
    "rows": 3200000, "input_sha256": "a" * 64,
    "output_sha256": "b" * 64, "final_status": "PASS",
    "comparison_count": {"combined_total": 24000000, "run_1": 12000000},
    "oracle_mismatches": {"combined_total": 0},
    "runs": {"run_1": {}, "run_2": {}}
}


def _write_f3m(tmp, payload):
    p = os.path.join(tmp, "evidence", "validation", "2026-09-19",
                     "fresh_3m2", "FINAL_RESULTS.json")
    with open(p, "w") as f:
        if isinstance(payload, str):
            f.write(payload)
        else:
            json.dump(payload, f)


def _write_test_summary(tmp, payload):
    p = os.path.join(tmp, "evidence", "rebuild_verification",
                     "test_summary.json")
    with open(p, "w") as f:
        json.dump(payload, f)


def _write_release_manifest(tmp, payload):
    p = os.path.join(tmp, "release_manifest.json")
    with open(p, "w") as f:
        json.dump(payload, f)


def _write_gate(tmp, payload):
    p = os.path.join(tmp, "evidence", "release_gate",
                     "final_release_gate.json")
    with open(p, "w") as f:
        json.dump(payload, f)


def _run_check(tmp):
    return cc.run_contradiction_check(tmp)


# ────────────────────────────────────────────────────────────────────
# _is_meaningful_truth_value unit tests
# ────────────────────────────────────────────────────────────────────

class TestIsMeaningfulTruthValue:
    def test_none_is_meaningless(self):
        assert cc._is_meaningful_truth_value(None) is False

    def test_empty_string_is_meaningless(self):
        assert cc._is_meaningful_truth_value("") is False

    def test_empty_dict_is_meaningless(self):
        assert cc._is_meaningful_truth_value({}) is False

    def test_empty_list_is_meaningless(self):
        assert cc._is_meaningful_truth_value([]) is False

    def test_zero_int_is_meaningful(self):
        # legitimate zero — represents an actual measurement
        assert cc._is_meaningful_truth_value(0) is True

    def test_zero_float_is_meaningful(self):
        assert cc._is_meaningful_truth_value(0.0) is True

    def test_false_boolean_is_meaningful(self):
        # legitimate False — represents an actual flag value
        assert cc._is_meaningful_truth_value(False) is True

    def test_true_boolean_is_meaningful(self):
        assert cc._is_meaningful_truth_value(True) is True

    def test_pass_string_is_meaningful(self):
        assert cc._is_meaningful_truth_value("PASS") is True

    def test_sha256_hex_is_meaningful(self):
        assert cc._is_meaningful_truth_value("a" * 64) is True

    def test_populated_dict_is_meaningful(self):
        assert cc._is_meaningful_truth_value({"k": "v"}) is True

    def test_populated_list_is_meaningful(self):
        assert cc._is_meaningful_truth_value([1, 2]) is True


# ────────────────────────────────────────────────────────────────────
# N-16 attack battery — every malformed case MUST produce NOT_VERIFIED
# ────────────────────────────────────────────────────────────────────

class TestN16AttackBattery:
    """14 attack scenarios against the N-16 fix. Every malformed/null/
    empty case MUST produce verdict=NOT_VERIFIED. The legitimate
    complete evidence case MUST still produce CONSISTENT."""

    def setup_method(self, method):
        self._tmp = tempfile.mkdtemp(prefix="n16_test_")
        _build_skeleton_repo(self._tmp)

    def teardown_method(self, method):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _check(self):
        return _run_check(self._tmp)

    # ── 14. valid complete evidence → CONSISTENT (baseline) ──
    def test_14_valid_complete_evidence_consistent(self):
        _write_f3m(self._tmp, GOOD_F3M)
        rep = self._check()
        assert rep["verdict"] == "CONSISTENT", (
            "valid complete evidence must still produce CONSISTENT "
            f"(got {rep['verdict']}; sources_failed="
            f"{rep['truth_sources_failed']}; truth="
            f"{rep['truth']})")
        assert not rep["truth_sources_failed"]

    # ── 1. rows=null ──
    def test_01_rows_null_not_verified(self):
        payload = dict(GOOD_F3M)
        payload["rows"] = None
        _write_f3m(self._tmp, payload)
        rep = self._check()
        assert rep["verdict"] == "NOT_VERIFIED"
        assert rep["truth_sources_failed"].get("official_3m2") == \
            "meaningless"

    # ── 2. input_sha256=null ──
    def test_02_input_sha256_null_not_verified(self):
        payload = dict(GOOD_F3M)
        payload["input_sha256"] = None
        _write_f3m(self._tmp, payload)
        rep = self._check()
        assert rep["verdict"] == "NOT_VERIFIED"
        assert rep["truth_sources_failed"].get("official_3m2") == \
            "meaningless"

    # ── 3. output_sha256=null ──
    def test_03_output_sha256_null_not_verified(self):
        payload = dict(GOOD_F3M)
        payload["output_sha256"] = None
        _write_f3m(self._tmp, payload)
        rep = self._check()
        assert rep["verdict"] == "NOT_VERIFIED"
        assert rep["truth_sources_failed"].get("official_3m2") == \
            "meaningless"

    # ── 4. final_status=null ──
    def test_04_final_status_null_not_verified(self):
        payload = dict(GOOD_F3M)
        payload["final_status"] = None
        _write_f3m(self._tmp, payload)
        rep = self._check()
        assert rep["verdict"] == "NOT_VERIFIED"
        assert rep["truth_sources_failed"].get("official_3m2") == \
            "meaningless"

    # ── 5. all truth fields=null ──
    def test_05_all_f3m_fields_null_not_verified(self):
        payload = {
            "rows": None, "input_sha256": None,
            "output_sha256": None, "final_status": None,
            "comparison_count": None, "oracle_mismatches": None,
            "runs": None
        }
        _write_f3m(self._tmp, payload)
        rep = self._check()
        assert rep["verdict"] == "NOT_VERIFIED"
        assert rep["truth_sources_failed"].get("official_3m2") == \
            "meaningless"

    # ── 6. empty string in input_sha256 ──
    def test_06_empty_string_sha_not_verified(self):
        payload = dict(GOOD_F3M)
        payload["input_sha256"] = ""
        _write_f3m(self._tmp, payload)
        rep = self._check()
        assert rep["verdict"] == "NOT_VERIFIED"
        assert rep["truth_sources_failed"].get("official_3m2") == \
            "meaningless"

    # ── 7. empty dict f3m ──
    def test_07_empty_dict_f3m_not_verified(self):
        _write_f3m(self._tmp, {})
        rep = self._check()
        assert rep["verdict"] == "NOT_VERIFIED"
        assert rep["truth_sources_failed"].get("official_3m2") == \
            "meaningless"

    def test_07b_empty_dict_f3m_meaninglessness_check_runs(self):
        """Verify the empty-dict f3m case is caught. The fix uses
        an `elif s == "ok":` branch after `if f3m:` to catch
        empty-dict / JSON-null sources that loaded syntactically
        but carry no meaningful content."""
        _write_f3m(self._tmp, {})
        rep = self._check()
        f3m_source_status = rep["truth_sources_status"].get(
            "official_3m2")
        assert f3m_source_status == "meaningless", (
            "empty-dict f3m must be marked meaningless, not "
            f"{f3m_source_status!r}")
        assert rep["verdict"] == "NOT_VERIFIED"

    # ── 8. empty list in runs ──
    def test_08_empty_list_runs_not_verified(self):
        payload = dict(GOOD_F3M)
        payload["runs"] = []
        _write_f3m(self._tmp, payload)
        rep = self._check()
        # runs=[] → empty list → meaningless → source marked meaningless
        assert rep["verdict"] == "NOT_VERIFIED"
        assert rep["truth_sources_failed"].get("official_3m2") == \
            "meaningless"

    # ── 9. partially populated truth source ──
    def test_09_partially_populated_f3m_not_verified(self):
        # only rows present, others missing → meaningless
        _write_f3m(self._tmp, {"rows": 3200000})
        rep = self._check()
        # Same caveat as test_07 — `if f3m:` is truthy (non-empty
        # dict), so the meaningfulness check DOES run. Required
        # fields like input_sha256 are absent (truth.get returns
        # None) → meaningless.
        assert rep["verdict"] == "NOT_VERIFIED"
        assert rep["truth_sources_failed"].get("official_3m2") == \
            "meaningless"

    # ── 10. nested meaningless (comparison_count.combined_total=null) ──
    def test_10_nested_meaningless_not_verified(self):
        payload = dict(GOOD_F3M)
        payload["comparison_count"] = {"combined_total": None,
                                       "run_1": None}
        payload["oracle_mismatches"] = {"combined_total": None}
        _write_f3m(self._tmp, payload)
        rep = self._check()
        # comparison_count is a dict, but `comp.get("combined_total")`
        # is None → falsy → the `if isinstance(comp, dict) and
        # comp.get("combined_total"):` check in derive_truth fails →
        # truth["comparisons_combined"] is NEVER SET. So
        # truth.get("comparisons_combined") is None → the
        # meaningfulness check catches it.
        assert rep["verdict"] == "NOT_VERIFIED"
        assert rep["truth_sources_failed"].get("official_3m2") == \
            "meaningless"

    # ── 11. legitimate rows=0 → CONSISTENT (not meaningless) ──
    def test_11_legitimate_rows_zero_consistent(self):
        # rows=0 is meaningful (zero is a real measurement)
        payload = dict(GOOD_F3M)
        payload["rows"] = 0
        _write_f3m(self._tmp, payload)
        rep = self._check()
        # rows=0 is meaningful — should NOT trigger the meaningless
        # check on official_3m2 alone
        # However, the gate source has gate_count=22 (from skeleton)
        # and tests source has collected=100, passed=100, failed=0
        # — all meaningful.
        # So the verdict should be CONSISTENT (assuming no other
        # contradictions in the documents).
        assert rep["truth_sources_status"].get("official_3m2") == "ok", (
            "rows=0 is meaningful; official_3m2 should be 'ok'")

    # ── 12. legitimate gate_count=0 → CONSISTENT (not meaningless) ──
    def test_12_legitimate_gate_count_zero_consistent(self):
        _write_gate(self._tmp, {"gate_count": 0,
                                 "overall_verdict": "PASS"})
        _write_f3m(self._tmp, GOOD_F3M)
        rep = self._check()
        # gate_count=0 is meaningful
        assert rep["truth_sources_status"].get("gate") == "ok"

    # ── 13. legitimate False boolean in final_status (not "PASS" str)
    #        → meaningful as a value, but final_status=False is NOT
    #        "PASS" — this would be a genuine failure record. Verify
    #        that the meaningfulness check doesn't reject False. ──
    def test_13_legitimate_false_boolean_meaningful(self):
        payload = dict(GOOD_F3M)
        # Set final_status to a non-PASS string that's still meaningful.
        # False is not a string but is meaningful.
        payload["final_status"] = False
        _write_f3m(self._tmp, payload)
        rep = self._check()
        # final_status=False is meaningful per _is_meaningful_truth_value.
        # The meaningfulness check should NOT mark the source meaningless.
        # (The contradiction checker may still find a value conflict
        # between docs claiming PASS and truth having False — that's
        # a separate concern.)
        assert rep["truth_sources_status"].get("official_3m2") == "ok", (
            "final_status=False is meaningful; the source should not "
            "be marked meaningless")

    # ── Extra: all truth sources nulled simultaneously ──
    def test_all_truth_sources_nulled_not_verified(self):
        _write_f3m(self._tmp, {"rows": None, "input_sha256": None,
                                "output_sha256": None,
                                "final_status": None})
        _write_test_summary(self._tmp, {"collected": None,
                                         "passed": None,
                                         "failed": None})
        _write_release_manifest(self._tmp, {"release_name": None,
                                              "release_date": None})
        _write_gate(self._tmp, {"gate_count": None,
                                 "overall_verdict": None})
        rep = self._check()
        assert rep["verdict"] == "NOT_VERIFIED"
        # At least one source should be meaningless
        assert any(v == "meaningless"
                   for v in rep["truth_sources_status"].values())

    # ── Extra: f3m file content = JSON null ──
    def test_f3m_file_content_null_not_verified(self):
        _write_f3m(self._tmp, "null")
        rep = self._check()
        assert rep["verdict"] == "NOT_VERIFIED"
        # _load_json returns (None, "ok") for JSON null. `if f3m:`
        # is falsy for None, so the `elif s == "ok":` branch fires
        # and marks the source "meaningless".
        assert rep["truth_sources_failed"].get("official_3m2") == \
            "meaningless"

    # ── Extra: tests source with null required fields ──
    def test_tests_source_null_fields_not_verified(self):
        _write_f3m(self._tmp, GOOD_F3M)
        _write_test_summary(self._tmp, {"collected": None,
                                         "passed": None,
                                         "failed": None,
                                         "skipped": 0, "errors": 0})
        rep = self._check()
        assert rep["verdict"] == "NOT_VERIFIED"
        assert rep["truth_sources_failed"].get("tests") == \
            "meaningless"

    # ── Extra: gate source with null fields ──
    def test_gate_source_null_fields_not_verified(self):
        _write_f3m(self._tmp, GOOD_F3M)
        _write_gate(self._tmp, {"gate_count": None,
                                 "overall_verdict": None})
        rep = self._check()
        assert rep["verdict"] == "NOT_VERIFIED"
        assert rep["truth_sources_failed"].get("gate") == \
            "meaningless"

    # ── Extra: release_manifest with null fields ──
    def test_release_manifest_null_fields_not_verified(self):
        _write_f3m(self._tmp, GOOD_F3M)
        _write_release_manifest(self._tmp, {"release_name": None,
                                              "release_date": None})
        rep = self._check()
        assert rep["verdict"] == "NOT_VERIFIED"
        assert rep["truth_sources_failed"].get("release_identity") == \
            "meaningless"
