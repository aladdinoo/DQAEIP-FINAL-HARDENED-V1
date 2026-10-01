"""FINAL CHECKER HARDENING — focused tests for Dave's review requirements.

These tests pin the fail-closed behavior of the corrected final 3M
validation checker (scripts/final_3m_validation.py v2.0.0):

1.  One run only  => final NOT PASS (two complete runs required).
2.  Run 2 failure => final NOT PASS.
3.  Failed SAVED stage result with process success (exit code 0)
    => final NOT PASS (saved staged results are the authority).
4.  Safety NOT_MEASURED => final NOT PASS (never satisfies PASS).
5.  Wrong SP1 expected hash (vs pinned baseline) => final NOT PASS;
    expected values are pinned, never derived from actual run values.
6.  Comparison counts include BOTH runs (run_1, run_2, combined_total).
7.  combined_total == run_1 + run_2 (and each run == rows x 8).
8.  Deterministic mismatch (or comparison not performed) => NOT PASS.
9.  Valid two-run evidence => final PASS.

Additional hardening pins:
- stale-evidence protection (script SHA-256 / git commit mismatch => FAIL)
- old-format/foreign evidence rejected by load_pass_result
- runtime-safety classifier semantics (PASS / FAIL / NOT_MEASURED)
- audit-hook wrapper end-to-end recording (benign + network cases)
- the pinned baseline loader against the real repository evidence

Nothing here mutates production code, the frozen V1 layer, golden
fixtures, or real evidence directories (all I/O goes to tmp_path).
"""

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

WRAPPER_PATH = os.path.join(REPO_ROOT, "scripts",
                            "final_3m_runtime_safety_wrapper.py")


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


F3M = _load_module("final_3m_validation",
                   os.path.join(REPO_ROOT, "scripts",
                                "final_3m_validation.py"))

# The exact gate set of Dave's fail-closed verdict formula.
DAVE_GATES = {
    "exactly_two_complete_runs", "run1_complete", "run2_complete",
    "run1_all_required_checks_pass", "run2_all_required_checks_pass",
    "deterministic_outputs_verified", "all_staged_results_successful",
    "safety_verified", "sp1_expected_names_verified",
    "sp1_expected_hashes_verified", "evidence_consistent",
}

ROWS = 1_000
SEED = 20260918
COMPARISONS_PER_RUN = ROWS * 8

IN_SHA = "a" * 64
OUT_SHA = "b" * 64
COMMIT = "c" * 40


# ────────────────────────────────────────────────────────────────────
# Synthetic evidence builders
# ────────────────────────────────────────────────────────────────────

def _pinned_hashes():
    return {n: hashlib.sha256(n.encode()).hexdigest()
            for n in F3M.FLAG_COLUMNS}


# ── L-8 valid-events file support ──────────────────────────────────
# A valid PASS run MUST now (after the L-8 fix) carry a real events
# file whose SHA-256 matches the saved events_file_sha256 and whose
# independent re-classification yields PASS. _valid_run stamps each
# run with such a file so that the L-8 consumer verification passes
# for legitimate evidence. The tamper tests below override these
# fields to construct attack scenarios.
_EVENTS_DIR = os.path.join(
    tempfile.gettempdir(), f"f3m_test_events_{os.getpid()}")
os.makedirs(_EVENTS_DIR, exist_ok=True)


def _write_valid_events_file(n=1):
    """Write a PASS-worthy events JSON for run n into the test events
    dir. Returns (events_path, events_file_sha256) — the path and the
    SHA-256 of the exact bytes written. The producer (phase_validate)
    and the L-8 consumer (_per_run_checks) both expect this contract."""
    # A minimal PASS-worthy events file: a single in-repo read-only open.
    # No network, no exec, no ctypes, no out-of-repo mutations.
    in_repo_path = os.path.join(_EVENTS_DIR, f"in_repo_pass{n}.txt")
    with open(in_repo_path, "w") as f:
        f.write("benign")
    payload = {
        "wrapper_version": "1.0.0",
        "python_version": "3.12.14",
        "started_utc": "2026-09-26T00:00:00Z",
        "ended_utc": "2026-09-26T00:00:01Z",
        "module": "runner.cli",
        "argv": [],
        "exit_code": 0,
        "error": None,
        "max_events": 50000,
        "truncated": False,
        "event_count": 1,
        "events": [
            {"event": "open", "path": in_repo_path,
             "mode": "r", "flags": 0},
        ],
    }
    events_path = os.path.join(_EVENTS_DIR, f"pass{n}_events.json")
    raw = json.dumps(payload, indent=1).encode("utf-8")
    with open(events_path, "wb") as f:
        f.write(raw)
    return events_path, hashlib.sha256(raw).hexdigest()


def _synthetic_pinned():
    hashes = _pinned_hashes()
    return {
        "primary_source": "test/rule_matrix.json",
        "primary_generated_at_utc": "2026-09-07T00:00:00Z",
        "expected_rule_names": sorted(F3M.FLAG_COLUMNS),
        "expected_hash_heads": {n: h[:16] for n, h in hashes.items()},
        "secondary_sources": ["test/run1/manifest.json"],
        "secondary_full_hashes": [
            {"source": "test/run1/manifest.json", "rule_hashes": hashes}],
        "secondary_sources_present": 1,
        "secondary_conflict": False,
    }


def _valid_run(n=1):
    """A fully valid saved run result (as load_pass_result would return
    for an OK result written by the corrected checker).

    L-8: the runtime_safety block carries a real events_path +
    events_file_sha256 referencing a real, hash-matching, classifier-PASS
    events file written by _write_valid_events_file. The L-8 consumer
    (_per_run_checks) re-reads, re-hashes, and re-classifies this file
    and requires the derived status to match the saved status."""
    events_path, events_sha = _write_valid_events_file(n)
    return {
        "run_present": True,
        "run_status": "OK",
        "run_problems": [],
        "pass": f"pass{n}",
        "blocked": False,
        "checker_version": F3M.CHECKER_VERSION,
        "script_sha256": F3M.script_identity()["script_sha256"],
        "wrapper_sha256": F3M.script_identity().get("wrapper_sha256"),
        "git_commit": COMMIT,
        "cli": {
            "command": "python wrapper ... pass" + str(n),
            "canonical_command": "python -m runner.cli validate ...",
            "wrapper_script": "scripts/final_3m_runtime_safety_wrapper.py",
            "returncode": 0,
            "stdout": "Validation PASSED: 1000 rows in, 1000 rows out",
            "stderr": "",
            "duration_seconds": 1.0,
        },
        "dataset": {
            "path": f"/tmp/checked/pass{n}.csv", "rows": ROWS, "seed": SEED,
            "columns": 33, "size_bytes": 734288183,
            "sha256": IN_SHA, "sha256_after_validation": IN_SHA,
            "generation_seconds": 1.0,
        },
        "output": {
            "path": f"/tmp/checked/pass{n}_out.csv", "rows": ROWS,
            "columns": 41, "size_bytes": 782288380, "sha256": OUT_SHA,
        },
        "verification": {
            **{k: "PASS" for k in F3M.REQUIRED_RUN_CHECK_KEYS},
            "oracle_comparisons": COMPARISONS_PER_RUN,
            "oracle_mismatches": 0,
            "mismatches_by_rule": {c: 0 for c in F3M.FLAG_COLUMNS},
            "first_mismatches": [],
            "flag_totals": {c: 10 for c in F3M.FLAG_COLUMNS},
            "verify_duration_seconds": 1.0,
            "input_rows": ROWS,
            "output_rows": ROWS,
            "extra_input_rows_after_lockstep": 0,
            "extra_output_rows_after_lockstep": 0,
        },
        "sp1_frozen": {
            "status": "PASS",
            "expected_names_verified": True,
            "expected_hashes_verified": True,
            "secondary_full_hash_match": True,
            "pinned_source": "test/rule_matrix.json",
            "manifest_rule_names": sorted(F3M.FLAG_COLUMNS),
            "manifest_rule_hashes": _pinned_hashes(),
            "mismatched_rules": {},
            "reason": "ok",
        },
        "runtime_safety": {
            "status": "PASS",
            "reason": "runtime-verified",
            "events_path": events_path,
            "events_file_sha256": events_sha,
            "network_event_count": 0,
            "exec_event_count": 0,
            "mutation_count": 0,
            "out_of_repo_mutation_count": 0,
        },
        "pinned_rule_baseline_source": "test/rule_matrix.json",
        "peak_rss_mb": 25.0,
        "engine_peak_rss_mb": 2226.79,
    }


_DEFAULT = object()


def _verdict(p1=_DEFAULT, p2=_DEFAULT, pinned=_DEFAULT, byte_identical=True,
             script_sha=None, git_commit=COMMIT):
    if p1 is _DEFAULT:
        p1 = _valid_run(1)
    if p2 is _DEFAULT:
        p2 = _valid_run(2)
    if pinned is _DEFAULT:
        pinned = _synthetic_pinned()
    return F3M.evaluate_final_verdict(
        p1, p2, pinned,
        script_sha if script_sha is not None
        else F3M.script_identity()["script_sha256"],
        git_commit,
        byte_identical,
        expected_rows=ROWS, expected_seed=SEED,
        wrapper_sha256=F3M.script_identity().get("wrapper_sha256"))


# ────────────────────────────────────────────────────────────────────
# 1. One run only => NOT PASS
# ────────────────────────────────────────────────────────────────────

class TestTwoRunRequirement:
    def test_one_run_only_not_pass(self):
        verdict = _verdict(p2=None)
        assert verdict["final_status"] == "FAIL"
        assert verdict["gates"]["exactly_two_complete_runs"] is False
        assert any("TWO" in r for r in verdict["runs"]["run_2"]
                   ["failure_reasons"])

    def test_gate_set_is_exactly_daves_formula(self):
        verdict = _verdict()
        assert set(verdict["gates"]) == DAVE_GATES

    def test_run2_result_file_missing_orchestration(self, tmp_path,
                                                     monkeypatch):
        monkeypatch.setattr(F3M, "git_commit_id", lambda: COMMIT)
        monkeypatch.setattr(F3M, "load_pinned_rule_baseline",
                            lambda *a, **k: _synthetic_pinned())
        ev = tmp_path / "ev"
        ev.mkdir()
        (ev / "pass1_result.json").write_text(json.dumps(_valid_run(1)))
        args = argparse.Namespace(evidence_dir=str(ev), rows=ROWS,
                                  seed=SEED, keep_pass2=False)
        rc = F3M.phase_finalize(args)
        assert rc == 1
        final = json.loads((ev / "FINAL_RESULTS.json").read_text())
        assert final["final_status"] == "FAIL"
        assert final["runs"]["run_2"]["status"] == "MISSING"


# ────────────────────────────────────────────────────────────────────
# 2. Run 2 failure => NOT PASS (a passing Run 1 hides nothing)
# ────────────────────────────────────────────────────────────────────

class TestRun2FailurePropagates:
    def test_run2_verification_failure_not_pass(self):
        p2 = _valid_run(2)
        p2["verification"]["row_count_status"] = "FAIL"
        verdict = _verdict(p2=p2)
        assert verdict["final_status"] == "FAIL"
        assert verdict["gates"]["run2_all_required_checks_pass"] is False

    def test_run2_oracle_mismatches_not_pass(self):
        p2 = _valid_run(2)
        p2["verification"]["oracle_mismatches"] = 3
        verdict = _verdict(p2=p2)
        assert verdict["final_status"] == "FAIL"

    def test_run2_cli_failure_saved_not_pass(self):
        p2 = _valid_run(2)
        p2["cli"]["returncode"] = 1
        verdict = _verdict(p2=p2)
        assert verdict["final_status"] == "FAIL"
        assert verdict["gates"]["all_staged_results_successful"] is False

    def test_run2_blocked_not_pass(self):
        p2 = _valid_run(2)
        p2["blocked"] = True
        verdict = _verdict(p2=p2)
        assert verdict["final_status"] == "FAIL"


# ────────────────────────────────────────────────────────────────────
# 3. Failed SAVED stage with process success => NOT PASS
# ────────────────────────────────────────────────────────────────────

class TestSavedStageAuthority:
    def test_failed_saved_stage_with_process_success_not_pass(self):
        # Process succeeded (cli returncode 0, run not blocked) but the
        # SAVED verification says FAIL — the saved result is the authority.
        p2 = _valid_run(2)
        p2["cli"]["returncode"] = 0
        p2["blocked"] = False
        p2["verification"]["flag_domain_status"] = "FAIL"
        verdict = _verdict(p2=p2)
        assert verdict["final_status"] == "FAIL"
        reasons = " ".join(verdict["runs"]["run_2"]["failure_reasons"])
        assert "flag_domain_status" in reasons

    def test_saved_oracle_fail_with_process_success_not_pass(self):
        p2 = _valid_run(2)
        p2["cli"]["returncode"] = 0
        p2["verification"]["oracle_mismatches"] = 7
        verdict = _verdict(p2=p2)
        assert verdict["final_status"] == "FAIL"
        assert verdict["comparison_count"]["run_2"] == COMPARISONS_PER_RUN

    def test_run1_saved_failure_not_pass(self):
        p1 = _valid_run(1)
        p1["cli"]["returncode"] = 0
        p1["verification"]["schema_status"] = "FAIL"
        verdict = _verdict(p1=p1)
        assert verdict["final_status"] == "FAIL"


# ────────────────────────────────────────────────────────────────────
# 4. Safety NOT_MEASURED => NOT PASS
# ────────────────────────────────────────────────────────────────────

class TestSafetyFailClosed:
    def test_safety_not_measured_not_pass(self):
        p2 = _valid_run(2)
        p2["runtime_safety"] = {
            "status": "NOT_MEASURED",
            "reason": "runtime safety event record not present"}
        verdict = _verdict(p2=p2)
        assert verdict["final_status"] == "FAIL"
        assert verdict["safety"]["overall_status"] == "NOT_MEASURED"
        assert verdict["gates"]["safety_verified"] is False

    def test_safety_run1_not_measured_not_pass(self):
        p1 = _valid_run(1)
        p1["runtime_safety"] = {"status": "NOT_MEASURED", "reason": "x"}
        verdict = _verdict(p1=p1)
        assert verdict["final_status"] == "FAIL"

    def test_safety_run2_fail_not_pass(self):
        p2 = _valid_run(2)
        p2["runtime_safety"] = {
            "status": "FAIL", "reason": "network activity observed"}
        verdict = _verdict(p2=p2)
        assert verdict["final_status"] == "FAIL"
        assert verdict["safety"]["overall_status"] == "FAIL"

    def test_safety_missing_key_treated_not_measured(self):
        p2 = _valid_run(2)
        del p2["runtime_safety"]["status"]
        verdict = _verdict(p2=p2)
        assert verdict["final_status"] == "FAIL"
        assert verdict["safety"]["overall_status"] == "NOT_MEASURED"


# ────────────────────────────────────────────────────────────────────
# 5. Wrong SP1 expected hash => NOT PASS (pinned expectations)
# ────────────────────────────────────────────────────────────────────

class TestSp1PinnedVerification:
    def _pinned_with_wrong_head(self):
        pinned = _synthetic_pinned()
        name = pinned["expected_rule_names"][0]
        pinned["expected_hash_heads"][name] = "0" * 16
        return pinned

    def test_wrong_sp1_expected_hash_not_pass(self):
        verdict = _verdict(pinned=self._pinned_with_wrong_head())
        assert verdict["final_status"] == "FAIL"
        assert verdict["gates"]["sp1_expected_hashes_verified"] is False

    def test_saved_boolean_true_but_manifest_mismatch_not_pass(self):
        # Tamper case: saved sp1 booleans claim True, but the SAVED manifest
        # hashes do not match the pinned heads — re-derivation catches it.
        p2 = _valid_run(2)
        tampered = dict(_pinned_hashes())
        name = sorted(F3M.FLAG_COLUMNS)[0]
        tampered[name] = "f" * 64
        p2["sp1_frozen"]["manifest_rule_hashes"] = tampered
        verdict = _verdict(p2=p2)
        assert verdict["final_status"] == "FAIL"
        assert verdict["gates"]["sp1_expected_hashes_verified"] is False

    def test_sp1_names_mismatch_not_pass(self):
        p2 = _valid_run(2)
        hashes = dict(_pinned_hashes())
        hashes["sp1_successor_geography"] = "e" * 64  # foreign rule appears
        p2["sp1_frozen"]["manifest_rule_hashes"] = hashes
        verdict = _verdict(p2=p2)
        assert verdict["final_status"] == "FAIL"
        assert verdict["gates"]["sp1_expected_names_verified"] is False

    def test_sp1_frozen_verification_direct_manifest_mismatch(self,
                                                               tmp_path):
        manifest = {"rule_hashes": dict(_pinned_hashes())}
        name = sorted(F3M.FLAG_COLUMNS)[1]
        manifest["rule_hashes"][name] = "9" * 64
        mpath = tmp_path / "manifest.json"
        mpath.write_text(json.dumps(manifest))
        result = F3M.sp1_frozen_verification(str(tmp_path),
                                             _synthetic_pinned())
        assert result["status"] == "FAIL"
        assert result["expected_hashes_verified"] is False
        assert name in result["mismatched_rules"]
        # The expected value comes from the PIN, not from the manifest:
        assert result["mismatched_rules"][name]["expected_head"] == \
            _synthetic_pinned()["expected_hash_heads"][name]

    def test_sp1_frozen_verification_pinned_unavailable(self, tmp_path):
        manifest = {"rule_hashes": dict(_pinned_hashes())}
        (tmp_path / "manifest.json").write_text(json.dumps(manifest))
        result = F3M.sp1_frozen_verification(str(tmp_path), None)
        assert result["status"] == "FAIL"
        assert "never invented" in result["reason"] or \
            "refusing" in result["reason"]

    def test_sp1_frozen_verification_manifest_missing(self, tmp_path):
        result = F3M.sp1_frozen_verification(str(tmp_path / "nope"),
                                             _synthetic_pinned())
        assert result["status"] == "FAIL"

    def test_pinned_unavailable_not_pass(self):
        verdict = _verdict(pinned=None)
        assert verdict["final_status"] == "FAIL"
        assert any("pinned frozen baseline unavailable" in r
                   for r in verdict["reasons"])


# ────────────────────────────────────────────────────────────────────
# 6/7. Comparison counts: BOTH runs + combined total math
# ────────────────────────────────────────────────────────────────────

class TestComparisonCounts:
    def test_comparison_counts_include_both_runs(self):
        verdict = _verdict()
        cc = verdict["comparison_count"]
        assert cc["run_1"] == COMPARISONS_PER_RUN
        assert cc["run_2"] == COMPARISONS_PER_RUN
        assert cc["combined_total"] == 2 * COMPARISONS_PER_RUN
        assert "rows x 8" in cc["definition"]

    def test_combined_total_equals_run1_plus_run2(self):
        p2 = _valid_run(2)
        p2["verification"]["oracle_comparisons"] = COMPARISONS_PER_RUN + 1
        verdict = _verdict(p2=p2)
        cc = verdict["comparison_count"]
        # The math identity itself holds ...
        assert cc["combined_total"] == cc["run_1"] + cc["run_2"]
        # ... but a per-run count inconsistent with rows x 8 refuses PASS.
        assert verdict["final_status"] == "FAIL"
        assert cc["run_2_matches_rows_times_rules"] is False

    def test_per_run_counts_are_each_expected(self):
        verdict = _verdict()
        cc = verdict["comparison_count"]
        assert cc["run_1"] == ROWS * 8
        assert cc["run_2"] == ROWS * 8
        assert cc["combined_total_equals_run_1_plus_run_2"] is True

    def test_missing_run2_counts_not_pass(self):
        verdict = _verdict(p2=None)
        cc = verdict["comparison_count"]
        assert cc["run_2"] is None
        assert cc["combined_total"] is None
        assert verdict["final_status"] == "FAIL"


# ────────────────────────────────────────────────────────────────────
# 8. Determinism mismatch / not performed => NOT PASS
# ────────────────────────────────────────────────────────────────────

class TestDeterminism:
    def test_deterministic_output_hash_mismatch_not_pass(self):
        p2 = _valid_run(2)
        p2["output"]["sha256"] = "d" * 64
        verdict = _verdict(p2=p2, byte_identical=False)
        assert verdict["final_status"] == "FAIL"
        det = verdict["determinism"]
        assert det["output_hash_equal"] is False
        assert det["run_2_output_sha256"] == "d" * 64

    def test_deterministic_input_hash_mismatch_not_pass(self):
        p2 = _valid_run(2)
        p2["dataset"]["sha256"] = "e" * 64
        verdict = _verdict(p2=p2)
        assert verdict["final_status"] == "FAIL"
        assert verdict["determinism"]["input_hash_equal"] is False

    def test_byte_comparison_not_performed_not_pass(self):
        verdict = _verdict(byte_identical=None)
        assert verdict["final_status"] == "FAIL"
        assert verdict["determinism"]["byte_comparison_performed"] is False
        assert verdict["determinism"]["byte_identical_output"] is None

    def test_byte_identical_false_not_pass(self):
        verdict = _verdict(byte_identical=False)
        assert verdict["final_status"] == "FAIL"

    def test_flag_totals_inequality_not_pass(self):
        p2 = _valid_run(2)
        p2["verification"]["flag_totals"] = {
            c: 11 for c in F3M.FLAG_COLUMNS}
        verdict = _verdict(p2=p2)
        assert verdict["final_status"] == "FAIL"
        assert verdict["determinism"]["flag_totals_equal"] is False

    def test_all_four_run_hashes_reported(self):
        verdict = _verdict()
        det = verdict["determinism"]
        assert det["run_1_input_sha256"] == IN_SHA
        assert det["run_2_input_sha256"] == IN_SHA
        assert det["run_1_output_sha256"] == OUT_SHA
        assert det["run_2_output_sha256"] == OUT_SHA


# ────────────────────────────────────────────────────────────────────
# 9. Valid two-run evidence => PASS (+ stale-evidence protection)
# ────────────────────────────────────────────────────────────────────

class TestValidEvidencePasses:
    def test_valid_two_run_evidence_pass(self):
        verdict = _verdict()
        assert verdict["final_status"] == "PASS"
        assert all(verdict["gates"].values())
        assert verdict["gate_failures"] == []

    def test_stale_script_sha_not_pass(self):
        verdict = _verdict(script_sha="0" * 64)
        assert verdict["final_status"] == "FAIL"
        assert any("stale evidence" in r
                   for r in verdict["runs"]["run_1"]["failure_reasons"])

    def test_stale_git_commit_not_pass(self):
        verdict = _verdict(git_commit=None)
        assert verdict["final_status"] == "FAIL"

    def test_run2_stale_git_commit_not_pass(self):
        p2 = _valid_run(2)
        p2["git_commit"] = "9" * 40
        verdict = _verdict(p2=p2)
        assert verdict["final_status"] == "FAIL"

    def test_secondary_pinned_conflict_not_pass(self):
        pinned = _synthetic_pinned()
        pinned["secondary_conflict"] = True
        verdict = _verdict(pinned=pinned)
        assert verdict["final_status"] == "FAIL"
        assert verdict["gates"]["evidence_consistent"] is False


class TestLoadPassResultFailClosed:
    def test_missing_file_fail(self, tmp_path):
        result = F3M.load_pass_result(str(tmp_path / "absent.json"))
        assert result["run_status"] == "FAIL"
        assert result["run_present"] is False

    def test_malformed_json_fail(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json")
        result = F3M.load_pass_result(str(p))
        assert result["run_status"] == "FAIL"

    def test_old_format_evidence_rejected(self, tmp_path):
        # Evidence written by the PREVIOUS (pre-hardening) checker lacks
        # script_sha256 / git_commit / sp1_frozen / runtime_safety keys:
        # stale/foreign format must never be interpreted as PASS.
        old = {
            "pass": "pass1", "blocked": False, "cli": {"returncode": 0},
            "dataset": {"sha256": IN_SHA,
                        "sha256_after_validation": IN_SHA},
            "output": {"sha256": OUT_SHA},
            "verification": {k: "PASS" for k in
                             F3M.REQUIRED_RUN_CHECK_KEYS},
            "sp1_isolation": {"status": "PASS"},
        }
        p = tmp_path / "pass1_result.json"
        p.write_text(json.dumps(old))
        result = F3M.load_pass_result(str(p))
        assert result["run_status"] == "FAIL"
        problems = " ".join(result["run_problems"])
        assert "stale or foreign format" in problems

    def test_valid_format_ok(self, tmp_path):
        p = tmp_path / "pass1_result.json"
        p.write_text(json.dumps(_valid_run(1)))
        result = F3M.load_pass_result(str(p))
        assert result["run_status"] == "OK"


# ────────────────────────────────────────────────────────────────────
# Runtime-safety classifier semantics
# ────────────────────────────────────────────────────────────────────

def _write_events(tmp_path, events, truncated=False, name="events.json"):
    payload = {"wrapper_version": "1.0.0", "truncated": truncated,
               "max_events": 50000, "event_count": len(events),
               "exit_code": 0, "events": events}
    p = tmp_path / name
    p.write_text(json.dumps(payload))
    return str(p)


class TestRuntimeSafetyClassifier:
    def test_clean_run_pass(self, tmp_path):
        events = [
            {"event": "open", "path": str(tmp_path / "in.csv"),
             "mode": "r", "flags": 0},
            {"event": "open", "path": str(tmp_path / "out.csv"),
             "mode": "w", "flags": 524865},
            {"event": "open", "path": str(tmp_path / "ev.json"),
             "mode": "w", "flags": 524865},
        ]
        result = F3M.classify_runtime_safety(
            _write_events(tmp_path, events), repo_root=str(tmp_path))
        assert result["status"] == "PASS"
        assert result["network_event_count"] == 0
        assert result["mutation_count"] == 2
        assert result["out_of_repo_mutation_count"] == 0

    def test_socket_event_fail(self, tmp_path):
        events = [{"event": "socket.__new__", "args": "()"},
                  {"event": "socket.connect", "args": "('host', 80)"}]
        result = F3M.classify_runtime_safety(
            _write_events(tmp_path, events), repo_root=str(tmp_path))
        assert result["status"] == "FAIL"
        assert result["network_event_count"] == 2

    def test_subprocess_event_fail(self, tmp_path):
        events = [{"event": "subprocess.Popen",
                   "args": "('ls', ['ls'])"}]
        result = F3M.classify_runtime_safety(
            _write_events(tmp_path, events), repo_root=str(tmp_path))
        assert result["status"] == "FAIL"
        assert result["exec_event_count"] == 1

    def test_out_of_repo_write_fail(self, tmp_path):
        events = [{"event": "open", "path": "/etc/passwd",
                   "mode": "w", "flags": 524865}]
        result = F3M.classify_runtime_safety(
            _write_events(tmp_path, events), repo_root=str(tmp_path))
        assert result["status"] == "FAIL"
        assert result["out_of_repo_mutation_count"] == 1

    def test_out_of_repo_remove_fail(self, tmp_path):
        events = [{"event": "os.remove", "path": "/etc/hosts"}]
        result = F3M.classify_runtime_safety(
            _write_events(tmp_path, events), repo_root=str(tmp_path))
        assert result["status"] == "FAIL"

    def test_relative_path_resolved_against_repo_root(self, tmp_path):
        events = [{"event": "open", "path": "outputs/x.csv",
                   "mode": "w", "flags": 524865}]
        result = F3M.classify_runtime_safety(
            _write_events(tmp_path, events), repo_root=str(tmp_path))
        assert result["status"] == "PASS"
        assert result["mutation_count"] == 1

    def test_missing_events_file_not_measured(self, tmp_path):
        result = F3M.classify_runtime_safety(
            str(tmp_path / "missing.json"), repo_root=str(tmp_path))
        assert result["status"] == "NOT_MEASURED"

    def test_malformed_events_file_not_measured(self, tmp_path):
        p = tmp_path / "broken.json"
        p.write_text("not json at all")
        result = F3M.classify_runtime_safety(str(p),
                                             repo_root=str(tmp_path))
        assert result["status"] == "NOT_MEASURED"

    def test_truncated_events_not_measured(self, tmp_path):
        events = [{"event": "open", "path": str(tmp_path / "x"),
                   "mode": "w", "flags": 524865}]
        result = F3M.classify_runtime_safety(
            _write_events(tmp_path, events, truncated=True),
            repo_root=str(tmp_path))
        assert result["status"] == "NOT_MEASURED"
        assert "truncated" in result["reason"]


# ────────────────────────────────────────────────────────────────────
# Audit-hook wrapper end-to-end (real subprocess, synthetic module)
# ────────────────────────────────────────────────────────────────────

class TestWrapperEndToEnd:
    @staticmethod
    def _run_wrapper(tmp_path, module_body, extra_env=None):
        mod = tmp_path / "wraptest_mod.py"
        mod.write_text(module_body)
        events = tmp_path / "events.json"
        env = dict(os.environ, PYTHONPATH=str(tmp_path))
        env.update(extra_env or {})
        proc = subprocess.run(
            [sys.executable, WRAPPER_PATH,
             "--events-out", str(events),
             "--module", "wraptest_mod", "--"],
            capture_output=True, text=True, env=env,
            cwd=str(tmp_path), timeout=120)
        return proc, events

    def test_benign_in_dir_run_records_and_passes(self, tmp_path):
        body = (
            "import os\n"
            "out = os.path.join(os.environ['WRAPTEST_DIR'], 'out.txt')\n"
            "with open(out, 'w') as fh:\n"
            "    fh.write('x')\n"
        )
        proc, events = self._run_wrapper(
            tmp_path, body, {"WRAPTEST_DIR": str(tmp_path)})
        assert proc.returncode == 0
        assert events.exists()
        assert (tmp_path / "out.txt").exists()
        result = F3M.classify_runtime_safety(str(events),
                                             repo_root=str(tmp_path))
        assert result["status"] == "PASS"
        assert result["network_event_count"] == 0
        assert result["mutation_count"] >= 1

    def test_socket_activity_recorded_and_fails(self, tmp_path):
        body = (
            "import socket\n"
            "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "s.close()\n"
        )
        proc, events = self._run_wrapper(tmp_path, body)
        assert proc.returncode == 0
        result = F3M.classify_runtime_safety(str(events),
                                             repo_root=str(tmp_path))
        assert result["status"] == "FAIL"
        assert result["network_event_count"] >= 1

    def test_wrapper_propagates_nonzero_exit_code(self, tmp_path):
        body = "import sys\nsys.exit(3)\n"
        proc, events = self._run_wrapper(tmp_path, body)
        assert proc.returncode == 3
        payload = json.loads(events.read_text())
        assert payload["exit_code"] == 3

    def test_wrapper_records_engine_error(self, tmp_path):
        body = "raise RuntimeError('boom')\n"
        proc, events = self._run_wrapper(tmp_path, body)
        assert proc.returncode == 1
        payload = json.loads(events.read_text())
        assert "RuntimeError" in payload["error"]
        # Fail-closed: events still dumped; classifier can still consume.
        result = F3M.classify_runtime_safety(str(events),
                                             repo_root=str(tmp_path))
        assert result["status"] in ("PASS", "FAIL", "NOT_MEASURED")


# ────────────────────────────────────────────────────────────────────
# Real-repo pinned baseline (read-only integration)
# ────────────────────────────────────────────────────────────────────

class TestRealPinnedBaseline:
    def test_load_pinned_rule_baseline_real_repo(self):
        pinned = F3M.load_pinned_rule_baseline()
        assert pinned is not None
        assert pinned["primary_source"] == \
            "evidence/final_execution/rule_matrix.json"
        assert len(pinned["expected_rule_names"]) == 8
        assert pinned["expected_rule_names"] == sorted(F3M.FLAG_COLUMNS)
        assert pinned["secondary_conflict"] is False
        # Full 64-char hashes pinned by the secondary historical manifests:
        for sec in pinned["secondary_full_hashes"]:
            assert all(len(h) == 64 for h in sec["rule_hashes"].values())

    def test_expected_heads_are_prefixes_of_secondary_full_hashes(self):
        pinned = F3M.load_pinned_rule_baseline()
        assert pinned is not None
        for sec in pinned["secondary_full_hashes"]:
            for rid, full in sec["rule_hashes"].items():
                assert full.startswith(pinned["expected_hash_heads"][rid])

    def test_pinned_baseline_path_constants(self):
        assert F3M.PINNED_RULE_MATRIX_REL == \
            "evidence/final_execution/rule_matrix.json"
        assert len(F3M.PINNED_SECONDARY_RELS) == 2
        assert os.path.exists(os.path.join(
            REPO_ROOT, F3M.PINNED_RULE_MATRIX_REL))


# ────────────────────────────────────────────────────────────────────
# Full phase_finalize orchestration on synthetic evidence
# ────────────────────────────────────────────────────────────────────

class TestPhaseFinalizeOrchestration:
    @staticmethod
    def _prepare(tmp_path, monkeypatch, write_run2=True, run2_mutator=None):
        monkeypatch.setattr(F3M, "git_commit_id", lambda: COMMIT)
        monkeypatch.setattr(F3M, "load_pinned_rule_baseline",
                            lambda *a, **k: _synthetic_pinned())
        ev = tmp_path / "ev"
        ev.mkdir(exist_ok=True)
        out1 = tmp_path / "pass1_out.csv"
        out1.write_text("id,flag\n1,0\n")
        r1 = _valid_run(1)
        r1["output"]["path"] = str(out1)
        r1["dataset"]["path"] = str(tmp_path / "pass1.csv")
        (ev / "pass1_result.json").write_text(json.dumps(r1))
        if write_run2:
            out2 = tmp_path / "pass2_out.csv"
            out2.write_text("id,flag\n1,0\n")
            r2 = _valid_run(2)
            r2["output"]["path"] = str(out2)
            r2["dataset"]["path"] = str(tmp_path / "pass2.csv")
            if run2_mutator:
                run2_mutator(r2)
            (ev / "pass2_result.json").write_text(json.dumps(r2))
        args = argparse.Namespace(evidence_dir=str(ev), rows=ROWS,
                                  seed=SEED, keep_pass2=False)
        return ev, args

    def test_valid_two_run_orchestration_pass(self, tmp_path, monkeypatch):
        ev, args = self._prepare(tmp_path, monkeypatch)
        rc = F3M.phase_finalize(args)
        assert rc == 0
        final = json.loads((ev / "FINAL_RESULTS.json").read_text())
        assert final["final_status"] == "PASS"
        assert final["comparison_count"]["run_1"] == COMPARISONS_PER_RUN
        assert final["comparison_count"]["run_2"] == COMPARISONS_PER_RUN
        assert final["comparison_count"]["combined_total"] == \
            2 * COMPARISONS_PER_RUN
        assert final["safety_status"] == "PASS"
        assert final["gates"]["sp1_expected_names_verified"] is True
        assert final["gates"]["sp1_expected_hashes_verified"] is True
        assert final["gates"]["deterministic_outputs_verified"] is True
        assert final["determinism_detail"]["byte_identical_output"] is True
        assert final["provenance"]["script_sha256"] == \
            F3M.script_identity()["script_sha256"]
        assert final["provenance"]["git_commit"] == COMMIT
        assert final["oracle_comparisons"] == 2 * COMPARISONS_PER_RUN

    def test_run2_fail_orchestration_not_pass(self, tmp_path, monkeypatch):
        def break_run2(r2):
            r2["verification"]["source_values_preserved_status"] = "FAIL"
        ev, args = self._prepare(tmp_path, monkeypatch,
                                 run2_mutator=break_run2)
        rc = F3M.phase_finalize(args)
        assert rc == 1
        final = json.loads((ev / "FINAL_RESULTS.json").read_text())
        assert final["final_status"] == "FAIL"
        assert "run2_all_required_checks_pass" in final["gate_failures"]

    def test_determinism_mismatch_orchestration_not_pass(self, tmp_path,
                                                         monkeypatch):
        out2 = None

        def differ(r2):
            r2["output"]["sha256"] = "5" * 64
        ev, args = self._prepare(tmp_path, monkeypatch,
                                 run2_mutator=differ)
        # Also make the actual files differ so filecmp reports False:
        (tmp_path / "pass2_out.csv").write_text("id,flag\n1,1\n")
        rc = F3M.phase_finalize(args)
        assert rc == 1
        final = json.loads((ev / "FINAL_RESULTS.json").read_text())
        assert final["final_status"] == "FAIL"
        assert final["determinism_detail"]["byte_identical_output"] is False

    def test_stale_evidence_orchestration_not_pass(self, tmp_path,
                                                   monkeypatch):
        # Run results stamped with a DIFFERENT script hash (old checker).
        def stale(r2):
            r2["script_sha256"] = "0" * 64
        ev, args = self._prepare(tmp_path, monkeypatch,
                                 run2_mutator=stale)
        rc = F3M.phase_finalize(args)
        assert rc == 1
        final = json.loads((ev / "FINAL_RESULTS.json").read_text())
        assert final["final_status"] == "FAIL"
        assert any("stale" in r.lower() for r in final["failure_reasons"])
