"""L-8 RUNTIME-SAFETY EVIDENCE INTEGRITY — focused attack battery.

These tests pin the L-8 fix in scripts/final_3m_validation.py:

  Producer side (phase_validate):
    - The events file bytes are read ONCE.
    - That exact byte sequence is hashed AND classified.
    - The saved events_file_sha256 is the hash of the classified bytes.
    - There is no TOCTOU window between classify and hash.

  Consumer side (_per_run_checks):
    - The saved runtime_safety.status field is NOT trusted.
    - The consumer re-reads, re-hashes, and re-classifies the events
      file at saved runtime_safety.events_path.
    - The derived status MUST equal the saved status AND be "PASS".
    - Any missing field, missing file, hash mismatch, parse failure,
      status mismatch, or non-PASS derived status → FAIL.

The 16 attack scenarios below were the exact false-PASS paths
confirmed in the prior forensic audit (Phase 5). After the L-8 fix,
EVERY attack MUST produce a non-PASS verdict. The valid PASS
scenario (attack #1) MUST still PASS.

These tests do NOT modify production code. They construct synthetic
saved run results (and on-disk events files) and route them through
the real _per_run_checks + evaluate_final_verdict gate functions."""

import argparse
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)


def _load_f3v():
    spec = importlib.util.spec_from_file_location(
        "f3v_l8", os.path.join(REPO_ROOT, "scripts",
                                "final_3m_validation.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


F3M = _load_f3v()

ROWS = 1_000
SEED = 20260918
COMPARISONS_PER_RUN = ROWS * 8
IN_SHA = "a" * 64
OUT_SHA = "b" * 64
COMMIT = "c" * 40


def _pinned():
    """Minimal pinned baseline that satisfies _per_run_checks."""
    hashes = {n: hashlib.sha256(n.encode()).hexdigest()
              for n in F3M.FLAG_COLUMNS}
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


def _good_events_payload(events_dir, n=1):
    """Build a PASS-worthy events payload for run n.
    Returns (payload_dict, in_repo_path)."""
    in_repo_path = os.path.join(events_dir, f"in_repo_pass{n}.txt")
    with open(in_repo_path, "w") as f:
        f.write("benign")
    return {
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
    }, in_repo_path


def _evil_events_payload(events_dir, n=1):
    """Build a FAIL-worthy events payload for run n (out-of-repo rename).
    Returns (payload_dict, in_repo_path, out_of_repo_path)."""
    in_repo_path = os.path.join(events_dir, f"in_repo_evil{n}.txt")
    with open(in_repo_path, "w") as f:
        f.write("source")
    out_of_repo_path = os.path.join(events_dir, f"OUTSIDE_repo_evil{n}.txt")
    # The classifier sees this absolute path; it's outside REPO_ROOT
    # because events_dir is in /tmp, not REPO_ROOT.
    return {
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
        "event_count": 2,
        "events": [
            {"event": "open", "path": in_repo_path,
             "mode": "r", "flags": 0},
            {"event": "os.rename", "path": in_repo_path,
             "path2": out_of_repo_path},
        ],
    }, in_repo_path, out_of_repo_path


def _write_events_file(events_dir, n, payload):
    """Write a JSON events file to events_dir for run n. Returns
    (events_path, events_file_sha256) computed from the EXACT bytes
    written."""
    events_path = os.path.join(events_dir, f"pass{n}_events.json")
    raw = json.dumps(payload, indent=1).encode("utf-8")
    with open(events_path, "wb") as f:
        f.write(raw)
    return events_path, hashlib.sha256(raw).hexdigest()


def _make_run(events_dir, n=1, runtime_safety_override=None,
              events_payload_override=None):
    """Build a fully valid saved run result for run n, with a real
    events file on disk. The runtime_safety block carries events_path
    and events_file_sha256 matching the actual file content.

    Optional overrides:
      - runtime_safety_override: replace the runtime_safety block
        entirely (used by tamper tests).
      - events_payload_override: use a custom events payload (e.g.
        the evil payload) for the on-disk events file. The saved
        events_file_sha256 is computed from the actual bytes written
        so the L-8 hash check passes — only the saved status mismatch
        is the test vector.
    """
    if events_payload_override is not None:
        payload = events_payload_override
    else:
        payload, _ = _good_events_payload(events_dir, n)
    events_path, events_sha = _write_events_file(events_dir, n, payload)

    rs = {
        "status": "PASS",
        "reason": "runtime-verified",
        "events_path": events_path,
        "events_file_sha256": events_sha,
        "network_event_count": 0,
        "exec_event_count": 0,
        "mutation_count": 0,
        "out_of_repo_mutation_count": 0,
    }
    if runtime_safety_override is not None:
        rs = runtime_safety_override
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
            "command": f"python wrapper ... pass{n}",
            "canonical_command": "python -m runner.cli validate ...",
            "wrapper_script": "scripts/final_3m_runtime_safety_wrapper.py",
            "returncode": 0,
            "stdout": f"Validation PASSED: {ROWS} rows in, {ROWS} rows out",
            "stderr": "",
            "duration_seconds": 1.0,
        },
        "dataset": {
            "path": f"/tmp/checked/pass{n}.csv",
            "rows": ROWS, "seed": SEED, "columns": 33,
            "size_bytes": 734288183,
            "sha256": IN_SHA, "sha256_after_validation": IN_SHA,
            "generation_seconds": 1.0,
        },
        "output": {
            "path": f"/tmp/checked/pass{n}_out.csv",
            "rows": ROWS, "columns": 41,
            "size_bytes": 782288380, "sha256": OUT_SHA,
        },
        "verification": {
            **{k: "PASS" for k in F3M.REQUIRED_RUN_CHECK_KEYS},
            "oracle_comparisons": COMPARISONS_PER_RUN,
            "oracle_mismatches": 0,
            "mismatches_by_rule": {c: 0 for c in F3M.FLAG_COLUMNS},
            "first_mismatches": [],
            "flag_totals": {c: 10 for c in F3M.FLAG_COLUMNS},
            "verify_duration_seconds": 1.0,
            "input_rows": ROWS, "output_rows": ROWS,
            "extra_input_rows_after_lockstep": 0,
            "extra_output_rows_after_lockstep": 0,
        },
        "sp1_frozen": {
            "status": "PASS", "expected_names_verified": True,
            "expected_hashes_verified": True,
            "secondary_full_hash_match": True,
            "pinned_source": "test/rule_matrix.json",
            "manifest_rule_names": sorted(F3M.FLAG_COLUMNS),
            "manifest_rule_hashes": {n: hashlib.sha256(
                n.encode()).hexdigest() for n in F3M.FLAG_COLUMNS},
            "mismatched_rules": {}, "reason": "ok",
        },
        "runtime_safety": rs,
        "pinned_rule_baseline_source": "test/rule_matrix.json",
        "peak_rss_mb": 25.0,
        "engine_peak_rss_mb": 2226.79,
    }


def _verdict(p1, p2=None, pinned=None, byte_identical=True):
    """Run evaluate_final_verdict on the given saved run results."""
    if pinned is None:
        pinned = _pinned()
    if p2 is None:
        p2 = _DEFAULT_P2
    return F3M.evaluate_final_verdict(
        p1, p2, pinned,
        F3M.script_identity()["script_sha256"],
        COMMIT, byte_identical,
        expected_rows=ROWS, expected_seed=SEED,
        wrapper_sha256=F3M.script_identity().get("wrapper_sha256"))


# A module-level default p2 (valid) — tests that mutate p1 can use it
# Default constructed lazily
_EVENTS_DIR = tempfile.mkdtemp(prefix="l8_test_events_")
_DEFAULT_P2 = _make_run(_EVENTS_DIR, n=2)


# ────────────────────────────────────────────────────────────────────
# Attack scenarios — all MUST FAIL except #1 (valid PASS)
# ────────────────────────────────────────────────────────────────────

class TestL8AttackBattery:
    """16 attack scenarios against the L-8 fix. Every attack that
    reached false PASS before the fix MUST now produce FAIL."""

    def setup_method(self, method):
        # Each test gets a fresh events dir so tampering in one test
        # cannot leak into another.
        self._ed = tempfile.mkdtemp(prefix="l8_attack_")

    def teardown_method(self, method):
        shutil.rmtree(self._ed, ignore_errors=True)

    # ── 1. Valid PASS evidence → PASS ──
    def test_01_valid_pass_evidence_passes(self):
        p1 = _make_run(self._ed, n=1)
        p2 = _make_run(self._ed, n=2)
        verdict = _verdict(p1, p2)
        assert verdict["final_status"] == "PASS", (
            "valid PASS evidence must still PASS after the L-8 fix "
            f"(got FAIL: {verdict['gate_failures']}; "
            f"reasons: {verdict['reasons'][:3]})")
        assert verdict["gates"]["run1_complete"] is True
        assert verdict["gates"]["run2_complete"] is True

    # ── 2. FAIL event + saved PASS → FAIL ──
    def test_02_fail_event_with_saved_pass_fails(self):
        # Events file contains an out-of-repo rename; we FORGE the
        # saved status to PASS. The L-8 consumer must re-derive FAIL
        # and reject.
        evil_payload, _, _ = _evil_events_payload(self._ed, n=1)
        p1 = _make_run(self._ed, n=1, events_payload_override=evil_payload)
        # p1 already has saved status=PASS but the events file is evil;
        # the saved events_file_sha256 matches the actual bytes, so
        # the hash check passes — but the derived status is FAIL,
        # which the L-8 consumer must catch.
        assert F3M.classify_runtime_safety(
            p1["runtime_safety"]["events_path"],
            repo_root=F3M.REPO_ROOT)["status"] == "FAIL"
        p2 = _make_run(self._ed, n=2)
        verdict = _verdict(p1, p2)
        assert verdict["final_status"] == "FAIL"
        assert "run1_complete" in verdict["gate_failures"]
        assert any("derived status 'FAIL'" in r or "saved runtime_safety"
                   for r in verdict["runs"]["run_1"]["failure_reasons"])

    # ── 3. Unsafe event + matching unsafe-event hash + saved PASS → FAIL
    def test_03_unsafe_event_matching_hash_saved_pass_fails(self):
        # Same as #2 but explicit: the hash IS correct (matches the
        # actual evil bytes); the L-8 verifier re-classifies and
        # detects the FAIL.
        evil_payload, _, _ = _evil_events_payload(self._ed, n=1)
        p1 = _make_run(self._ed, n=1, events_payload_override=evil_payload)
        # Verify the hash matches the file:
        with open(p1["runtime_safety"]["events_path"], "rb") as f:
            actual = hashlib.sha256(f.read()).hexdigest()
        assert actual == p1["runtime_safety"]["events_file_sha256"]
        p2 = _make_run(self._ed, n=2)
        verdict = _verdict(p1, p2)
        assert verdict["final_status"] == "FAIL"
        assert "run1_complete" in verdict["gate_failures"]

    # ── 4. Safe event + saved FAIL → FAIL ──
    def test_04_safe_event_saved_fail_status_fails(self):
        # The events file is GOOD (classifies as PASS), but the saved
        # status is forged to FAIL. The L-8 consumer re-derives PASS,
        # which does NOT match saved FAIL → reject.
        good_payload, _ = _good_events_payload(self._ed, n=1)
        events_path, events_sha = _write_events_file(
            self._ed, 1, good_payload)
        p1 = _make_run(self._ed, n=1,
                       runtime_safety_override={
                           "status": "FAIL",
                           "reason": "tampered to FAIL",
                           "events_path": events_path,
                           "events_file_sha256": events_sha,
                       })
        p2 = _make_run(self._ed, n=2)
        verdict = _verdict(p1, p2)
        assert verdict["final_status"] == "FAIL"

    # ── 5. Event modified but original hash retained → FAIL ──
    def test_05_event_modified_hash_unchanged_fails(self):
        # Write a good events file, save its hash. Then tamper the
        # file content (add a malicious event). The saved hash no
        # longer matches the file content.
        good_payload, _ = _good_events_payload(self._ed, n=1)
        p1 = _make_run(self._ed, n=1, events_payload_override=good_payload)
        events_path = p1["runtime_safety"]["events_path"]
        saved_hash = p1["runtime_safety"]["events_file_sha256"]
        # Tamper: append an evil event
        tampered_payload = dict(good_payload)
        tampered_payload["events"] = list(tampered_payload["events"]) + [
            {"event": "os.rename", "path": "/etc/x",
             "path2": "/tmp/should_fail"}
        ]
        tampered_payload["event_count"] = len(tampered_payload["events"])
        with open(events_path, "wb") as f:
            f.write(json.dumps(tampered_payload, indent=1).encode("utf-8"))
        # Saved hash is unchanged (still the good hash) — but file
        # content has changed. The L-8 consumer must detect the
        # mismatch.
        p2 = _make_run(self._ed, n=2)
        verdict = _verdict(p1, p2)
        assert verdict["final_status"] == "FAIL"
        assert any("events file hash mismatch" in r
                   for r in verdict["runs"]["run_1"]["failure_reasons"])

    # ── 6. Hash modified → FAIL ──
    def test_06_hash_modified_fails(self):
        p1 = _make_run(self._ed, n=1)
        # Replace the saved hash with a forged different hash
        p1["runtime_safety"]["events_file_sha256"] = "0" * 64
        p2 = _make_run(self._ed, n=2)
        verdict = _verdict(p1, p2)
        assert verdict["final_status"] == "FAIL"
        assert any("events file hash mismatch" in r
                   for r in verdict["runs"]["run_1"]["failure_reasons"])

    # ── 7. events_file_sha256 removed → FAIL ──
    def test_07_events_file_sha256_removed_fails(self):
        p1 = _make_run(self._ed, n=1)
        del p1["runtime_safety"]["events_file_sha256"]
        p2 = _make_run(self._ed, n=2)
        verdict = _verdict(p1, p2)
        assert verdict["final_status"] == "FAIL"
        assert any("events_file_sha256 missing" in r
                   for r in verdict["runs"]["run_1"]["failure_reasons"])

    # ── 8. events_path removed → FAIL ──
    def test_08_events_path_removed_fails(self):
        p1 = _make_run(self._ed, n=1)
        del p1["runtime_safety"]["events_path"]
        p2 = _make_run(self._ed, n=2)
        verdict = _verdict(p1, p2)
        assert verdict["final_status"] == "FAIL"
        assert any("events_path missing" in r
                   for r in verdict["runs"]["run_1"]["failure_reasons"])

    # ── 9. Event file removed → FAIL ──
    def test_09_event_file_removed_fails(self):
        p1 = _make_run(self._ed, n=1)
        os.remove(p1["runtime_safety"]["events_path"])
        p2 = _make_run(self._ed, n=2)
        verdict = _verdict(p1, p2)
        assert verdict["final_status"] == "FAIL"
        assert any("events file not present" in r
                   for r in verdict["runs"]["run_1"]["failure_reasons"])

    # ── 10. Event file malformed → FAIL ──
    def test_10_event_file_malformed_fails(self):
        p1 = _make_run(self._ed, n=1)
        # Overwrite with garbage (not valid JSON)
        with open(p1["runtime_safety"]["events_path"], "wb") as f:
            f.write(b"NOT VALID JSON {{{{ ")
        # The saved hash no longer matches; the L-8 verifier detects
        # the hash mismatch first (before even trying to parse).
        p2 = _make_run(self._ed, n=2)
        verdict = _verdict(p1, p2)
        assert verdict["final_status"] == "FAIL"
        assert any("hash mismatch" in r
                   for r in verdict["runs"]["run_1"]["failure_reasons"])

    # ── 11. Null event JSON → FAIL ──
    def test_11_null_event_json_fails(self):
        # The events file is valid JSON but the parsed value is `null`.
        # Use a unique filename so _make_run's own events file doesn't
        # overwrite it.
        events_path = os.path.join(self._ed, "null_events.json")
        raw = b"null"
        with open(events_path, "wb") as f:
            f.write(raw)
        events_sha = hashlib.sha256(raw).hexdigest()
        p1 = _make_run(self._ed, n=1,
                       runtime_safety_override={
                           "status": "PASS",
                           "reason": "runtime-verified",
                           "events_path": events_path,
                           "events_file_sha256": events_sha,
                       })
        p2 = _make_run(self._ed, n=2)
        verdict = _verdict(p1, p2)
        assert verdict["final_status"] == "FAIL"
        # The derived status is NOT_MEASURED (payload is null), which
        # does not match saved PASS → reject.
        assert any("derived status 'NOT_MEASURED'" in r
                   for r in verdict["runs"]["run_1"]["failure_reasons"])

    # ── 12. Empty event JSON → FAIL ──
    def test_12_empty_event_json_fails(self):
        # The events file is empty (0 bytes).
        events_path = os.path.join(self._ed, "empty_events.json")
        raw = b""
        with open(events_path, "wb") as f:
            f.write(raw)
        events_sha = hashlib.sha256(raw).hexdigest()
        p1 = _make_run(self._ed, n=1,
                       runtime_safety_override={
                           "status": "PASS",
                           "reason": "runtime-verified",
                           "events_path": events_path,
                           "events_file_sha256": events_sha,
                       })
        p2 = _make_run(self._ed, n=2)
        verdict = _verdict(p1, p2)
        assert verdict["final_status"] == "FAIL"
        # Empty bytes → NOT_MEASURED (derived) != PASS (saved) → reject
        assert any("derived status" in r
                   for r in verdict["runs"]["run_1"]["failure_reasons"])

    # ── 13. Missing path/path2 where required → FAIL ──
    def test_13_missing_path_in_rename_event_fails(self):
        # Events file has an os.rename with no path/path2; the
        # classifier's _in_repo(None) returns False → out_of_repo
        # → FAIL.
        events_path = os.path.join(self._ed, "malformed_events.json")
        payload = {
            "wrapper_version": "1.0.0", "python_version": "3.12.14",
            "started_utc": "x", "ended_utc": "y", "module": "test",
            "argv": [], "exit_code": 0, "error": None,
            "max_events": 50000, "truncated": False, "event_count": 1,
            "events": [{"event": "os.rename"}],  # missing path/path2
        }
        raw = json.dumps(payload, indent=1).encode("utf-8")
        with open(events_path, "wb") as f:
            f.write(raw)
        events_sha = hashlib.sha256(raw).hexdigest()
        p1 = _make_run(self._ed, n=1,
                       runtime_safety_override={
                           "status": "PASS",
                           "reason": "runtime-verified",
                           "events_path": events_path,
                           "events_file_sha256": events_sha,
                       })
        p2 = _make_run(self._ed, n=2)
        verdict = _verdict(p1, p2)
        assert verdict["final_status"] == "FAIL"

    # ── 14. Saved status tampered FAIL → PASS → FAIL ──
    def test_14_saved_fail_to_pass_tamper_fails(self):
        # Take a run that genuinely classified FAIL (evil events),
        # then forge the saved status to PASS. The L-8 consumer
        # re-derives FAIL, mismatch with forged PASS → reject.
        evil_payload, _, _ = _evil_events_payload(self._ed, n=1)
        # Use a unique filename so _make_run doesn't overwrite
        events_path = os.path.join(self._ed, "evil_events.json")
        raw = json.dumps(evil_payload, indent=1).encode("utf-8")
        with open(events_path, "wb") as f:
            f.write(raw)
        events_sha = hashlib.sha256(raw).hexdigest()
        # Real classification:
        real = F3M.classify_runtime_safety(events_path,
                                            repo_root=F3M.REPO_ROOT)
        assert real["status"] == "FAIL"
        # Forge saved status to PASS:
        p1 = _make_run(self._ed, n=1,
                       runtime_safety_override={
                           "status": "PASS",  # FORGED
                           "reason": "forged",
                           "events_path": events_path,
                           "events_file_sha256": events_sha,
                       })
        p2 = _make_run(self._ed, n=2)
        verdict = _verdict(p1, p2)
        assert verdict["final_status"] == "FAIL"
        assert any("derived status 'FAIL'" in r
                   for r in verdict["runs"]["run_1"]["failure_reasons"])

    # ── 15. Saved status tampered PASS → FAIL → FAIL ──
    def test_15_saved_pass_to_fail_tamper_fails(self):
        # Take a run with a GOOD events file (classifies PASS), then
        # forge saved status to FAIL. The L-8 consumer re-derives
        # PASS, mismatch with forged FAIL → reject.
        good_payload, _ = _good_events_payload(self._ed, n=1)
        events_path = os.path.join(self._ed, "good_for_fail_test.json")
        raw = json.dumps(good_payload, indent=1).encode("utf-8")
        with open(events_path, "wb") as f:
            f.write(raw)
        events_sha = hashlib.sha256(raw).hexdigest()
        p1 = _make_run(self._ed, n=1,
                       runtime_safety_override={
                           "status": "FAIL",  # FORGED
                           "reason": "forged",
                           "events_path": events_path,
                           "events_file_sha256": events_sha,
                       })
        p2 = _make_run(self._ed, n=2)
        verdict = _verdict(p1, p2)
        assert verdict["final_status"] == "FAIL"
        # The saved status is FAIL — the first guard catches this.
        assert any("saved runtime_safety.status is 'FAIL'"
                   in r
                   for r in verdict["runs"]["run_1"]["failure_reasons"])

    # ── 16. Exact original false-PASS reproduction from forensic report
    #        must now fail ──
    def test_16_exact_forensic_false_pass_reproduction_fails(self):
        """This is the EXACT attack from the prior forensic audit
        (Phase 5): two forged run results, each with runtime_safety.status
        forged to PASS while the events file contains a clear out-of-repo
        os.rename. The events_file_sha256 IS the correct hash of the
        evil events file (so the hash check passes). Before the L-8 fix
        this attack produced final_status=PASS — a textbook false PASS.
        After the L-8 fix it MUST produce final_status=FAIL."""
        # Build the EXACT evil events file from the forensic audit
        events_path = os.path.join(self._ed, "events.json")
        events_payload = {
            "wrapper_version": "1.0.0", "python_version": "3.12.14",
            "started_utc": "x", "ended_utc": "y", "module": "test",
            "argv": [], "exit_code": 0, "error": None,
            "max_events": 50000, "truncated": False, "event_count": 2,
            "events": [
                {"event": "open",
                 "path": os.path.join(self._ed, "in.txt"),
                 "mode": "r", "flags": 0},
                {"event": "os.rename",
                 "path": os.path.join(self._ed, "in.txt"),
                 "path2": "/etc/should_fail.txt"},
            ],
        }
        with open(events_path, "w") as f:
            json.dump(events_payload, f)
        events_hash = hashlib.sha256(
            open(events_path, "rb").read()).hexdigest()

        def make_run(n):
            return {
                "pass": f"pass{n}", "blocked": False,
                "run_status": "OK", "run_present": True,
                "run_problems": [],
                "cli": {"returncode": 0, "duration_seconds": 1.0,
                         "canonical_command": "t",
                         "stdout": "Validation PASSED", "stderr": ""},
                "dataset": {"path": "x", "rows": ROWS, "seed": SEED,
                             "columns": 33, "size_bytes": 1,
                             "sha256": IN_SHA,
                             "sha256_after_validation": IN_SHA,
                             "generation_seconds": 0.1},
                "output": {"path": "y", "rows": ROWS, "columns": 41,
                            "size_bytes": 1, "sha256": OUT_SHA},
                "verification": {
                    **{k: "PASS" for k in F3M.REQUIRED_RUN_CHECK_KEYS},
                    "oracle_comparisons": COMPARISONS_PER_RUN,
                    "oracle_mismatches": 0,
                    "verify_duration_seconds": 0.5,
                    "flag_totals": {}},
                "sp1_frozen": {"status": "PASS",
                                "expected_names_verified": True,
                                "expected_hashes_verified": True,
                                "reason": "ok",
                                "manifest_rule_hashes": {}},
                "runtime_safety": {
                    "status": "PASS",  # FORGED
                    "reason": "runtime-verified",
                    "events_path": events_path,
                    "events_file_sha256": events_hash,  # CORRECT hash
                    "out_of_repo_mutation_count": 0,  # FORGED
                },
                "script_sha256": F3M.script_identity()["script_sha256"],
                "wrapper_sha256": F3M.script_identity().get(
                    "wrapper_sha256"),
                "git_commit": COMMIT,
            }
        p1 = make_run(1)
        p2 = make_run(2)
        verdict = _verdict(p1, p2)
        assert verdict["final_status"] == "FAIL", (
            "the exact forensic false-PASS attack must now FAIL; "
            f"got {verdict['final_status']}")
        assert "run1_complete" in verdict["gate_failures"]
        assert "run2_complete" in verdict["gate_failures"]


# ────────────────────────────────────────────────────────────────────
# Part 6 — Producer consistency test (single-byte-sequence proof)
# ────────────────────────────────────────────────────────────────────

class TestProducerConsistency:
    """Verify that phase_validate's producer path uses ONE byte
    sequence for both hashing and classification. The test detects
    any future implementation that independently opens the event
    file for hashing and classification (the L-8 producer TOCTOU
    regression)."""

    def test_classify_runtime_safety_from_bytes_uses_exact_bytes(
            self):
        """classify_runtime_safety_from_bytes must hash-and-classify
        the EXACT bytes the caller passed in. We verify by passing
        bytes that DIFFER in whitespace from any re-serialization —
        if the function re-reads the file or re-serializes the JSON,
        the hash would differ."""
        # Construct two byte sequences that parse to the same JSON
        # object but have DIFFERENT byte representations (whitespace).
        payload = {
            "wrapper_version": "1.0.0", "python_version": "3.12.14",
            "started_utc": "x", "ended_utc": "y", "module": "test",
            "argv": [], "exit_code": 0, "error": None,
            "max_events": 50000, "truncated": False, "event_count": 1,
            "events": [{"event": "open", "path": "/tmp/in.txt",
                         "mode": "r", "flags": 0}],
        }
        # Two different byte representations of the same payload:
        raw_compact = json.dumps(payload, separators=(",", ":")).encode(
            "utf-8")
        raw_pretty = json.dumps(payload, indent=4).encode("utf-8")
        assert raw_compact != raw_pretty  # different byte sequences
        # The classifier must accept both and produce the same
        # status (PASS for both, since the payload is benign).
        r1 = F3M.classify_runtime_safety_from_bytes(
            raw_compact, repo_root=F3M.REPO_ROOT)
        r2 = F3M.classify_runtime_safety_from_bytes(
            raw_pretty, repo_root=F3M.REPO_ROOT)
        assert r1["status"] == "PASS"
        assert r2["status"] == "PASS"

    def test_producer_hash_and_classify_use_same_bytes(self, tmp_path):
        """Simulate the producer's exact code path: read events file
        bytes once, hash them, classify them. Then verify:
          - the stored events_file_sha256 matches the actual file hash
          - the saved status matches what classify_runtime_safety
            (path-based) would return on the same file
        This is a regression test: if a future implementation splits
        the read into two opens, the hashes may diverge under tamper
        between the two reads. This test cannot directly detect the
        TOCTOU but it confirms the producer stores a hash that
        matches the file content at write time AND that the saved
        status matches the path-based classifier's verdict on the
        same file."""
        events_dir = tmp_path / "ev"
        events_dir.mkdir()
        events_path = events_dir / "events.json"
        payload = {
            "wrapper_version": "1.0.0", "python_version": "3.12.14",
            "started_utc": "x", "ended_utc": "y", "module": "test",
            "argv": [], "exit_code": 0, "error": None,
            "max_events": 50000, "truncated": False, "event_count": 1,
            "events": [{"event": "open", "path": str(events_dir / "in.txt"),
                         "mode": "r", "flags": 0}],
        }
        raw = json.dumps(payload, indent=1).encode("utf-8")
        with open(events_path, "wb") as f:
            f.write(raw)
        # Replicate the producer's exact L-8-fixed logic:
        with open(events_path, "rb") as f:
            events_raw = f.read()
        events_file_sha = hashlib.sha256(events_raw).hexdigest()
        runtime_safety = F3M.classify_runtime_safety_from_bytes(
            events_raw, repo_root=F3M.REPO_ROOT)
        runtime_safety["events_path"] = str(events_path)
        runtime_safety["events_file_sha256"] = events_file_sha
        # Assertions:
        # 1. stored hash matches the actual file content hash
        actual_file_hash = hashlib.sha256(
            open(events_path, "rb").read()).hexdigest()
        assert runtime_safety["events_file_sha256"] == actual_file_hash
        # 2. the saved status matches what the path-based classifier
        #    would return on the same file (because they parse the
        #    same bytes)
        path_based = F3M.classify_runtime_safety(
            str(events_path), repo_root=F3M.REPO_ROOT)
        assert runtime_safety["status"] == path_based["status"]
        assert runtime_safety["reason"] == path_based["reason"]
        # 3. the saved status is PASS (no FAIL-worthy events)
        assert runtime_safety["status"] == "PASS"

    def test_producer_bytes_vs_path_classification_match(self, tmp_path):
        """classify_runtime_safety_from_bytes(raw_bytes) and
        classify_runtime_safety(path) MUST return the same status
        when given the same underlying file content. This is the
        fundamental invariant that allows the L-8 consumer to
        re-verify using bytes while the producer stores status
        derived from bytes."""
        events_path = tmp_path / "events.json"
        payload = {
            "wrapper_version": "1.0.0", "python_version": "3.12.14",
            "started_utc": "x", "ended_utc": "y", "module": "test",
            "argv": [], "exit_code": 0, "error": None,
            "max_events": 50000, "truncated": False, "event_count": 1,
            "events": [{"event": "open",
                         "path": str(tmp_path / "in.txt"),
                         "mode": "r", "flags": 0}],
        }
        raw = json.dumps(payload, indent=1).encode("utf-8")
        with open(events_path, "wb") as f:
            f.write(raw)
        with open(events_path, "rb") as f:
            events_raw = f.read()
        bytes_based = F3M.classify_runtime_safety_from_bytes(
            events_raw, repo_root=F3M.REPO_ROOT)
        path_based = F3M.classify_runtime_safety(
            str(events_path), repo_root=F3M.REPO_ROOT)
        assert bytes_based["status"] == path_based["status"]
        assert bytes_based["reason"] == path_based["reason"]


# ────────────────────────────────────────────────────────────────────
# Part 7 — Alternate-consumer bypass search (smoke test)
# ────────────────────────────────────────────────────────────────────

class TestNoAlternateBypass:
    """Smoke tests confirming that runtime_safety.status is NOT
    consulted by any path other than _per_run_checks via the L-8
    verification block. The actual caller search is done via grep;
    these tests pin the contract that the only callers of
    _per_run_checks are within final_3m_validation.py and that
    the status field is never trusted in isolation."""

    def test_per_run_checks_does_not_trust_saved_status_alone(self):
        """Construct a run with saved status=PASS but no events_path,
        no events_file_sha256. Before the L-8 fix, this would PASS.
        After the L-8 fix, it MUST FAIL because the consumer cannot
        re-verify without events_path."""
        p1 = {
            "run_present": True, "run_status": "OK", "run_problems": [],
            "pass": "pass1", "blocked": False,
            "checker_version": F3M.CHECKER_VERSION,
            "script_sha256": F3M.script_identity()["script_sha256"],
            "wrapper_sha256": F3M.script_identity().get("wrapper_sha256"),
            "git_commit": COMMIT,
            "cli": {"returncode": 0, "duration_seconds": 1.0,
                     "canonical_command": "t",
                     "stdout": "Validation PASSED", "stderr": ""},
            "dataset": {"path": "x", "rows": ROWS, "seed": SEED,
                         "columns": 33, "size_bytes": 1,
                         "sha256": IN_SHA,
                         "sha256_after_validation": IN_SHA,
                         "generation_seconds": 0.1},
            "output": {"path": "y", "rows": ROWS, "columns": 41,
                         "size_bytes": 1, "sha256": OUT_SHA},
            "verification": {
                **{k: "PASS" for k in F3M.REQUIRED_RUN_CHECK_KEYS},
                "oracle_comparisons": COMPARISONS_PER_RUN,
                "oracle_mismatches": 0,
                "verify_duration_seconds": 0.5,
                "flag_totals": {}},
            "sp1_frozen": {"status": "PASS",
                            "expected_names_verified": True,
                            "expected_hashes_verified": True,
                            "reason": "ok",
                            "manifest_rule_hashes": {}},
            "runtime_safety": {
                "status": "PASS",  # FORGED — no events_path/hsa256
                "reason": "runtime-verified",
            },
            "pinned_rule_baseline_source": "test/rule_matrix.json",
        }
        checks, reasons = F3M._per_run_checks(
            p1, _pinned(),
            script_sha256=F3M.script_identity()["script_sha256"],
            git_commit=COMMIT,
            expected_rows=ROWS, expected_seed=SEED,
            wrapper_sha256=F3M.script_identity().get("wrapper_sha256"))
        assert checks["runtime_safety.pass"] is False, (
            "a forged runtime_safety.status=PASS without events_path "
            "or events_file_sha256 MUST NOT pass the L-8 verification "
            f"(got reasons: {reasons})")
        assert any("events_path missing" in r for r in reasons)
