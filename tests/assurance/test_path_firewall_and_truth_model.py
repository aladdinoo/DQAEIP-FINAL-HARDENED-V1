"""DQAEIP assurance-layer tests: path firewall + truth model (Phases
11/13/15).

These are FALSE-PASS PREVENTION tests: every scenario that must be
rejected is asserted to be rejected.
"""

import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance import path_firewall, truth_model


class TestPathFirewall:
    """Phase 11: machine-local path detection — false-PASS prevention."""

    @pytest.mark.parametrize("text,rules", [
        ("run /home/z/dev/tool.py", ["posix_home"]),
        ("macos path /Users/alice/data", ["macos_users"]),
        ("root script /root/install.sh", ["root_home"]),
        ("mount /mnt/data/x.csv", ["mounted_volume"]),
        # FINAL HARDENING Phase 5: WSL paths are mounted-volume machine
        # paths (/mnt/c/Users/... = the Windows C: drive via WSL) and
        # MUST be rejected exactly like any other /mnt/ form.
        ("wsl /mnt/c/Users/bob/in.csv", ["mounted_volume"]),
        ("wsl deep \\\\wsl$\\Ubuntu\\home\\bob\\in.csv", ["unc_share"]),
        ("tmp /tmp/build42/out.csv", ["machine_tmp"]),
        ("var /var/lib/platform/db", ["system_var"]),
        ("srv /srv/exports/file.csv", ["service_tree"]),
        ("windows C:\\Users\\bob\\in.csv", ["windows_drive"]),
        ("windows D:\\data\\in.csv", ["windows_drive"]),
        ("windows bare drive C:\\in.csv", ["windows_drive"]),
        ("unc \\\\server\\share\\f.csv", ["unc_share"]),
        ("tilde ~/configs/x.yaml", ["tilde_user"]),
        ("named tilde ~alice/files/x", ["tilde_named_user"]),
        ("dqvp-work marker in /x/dqvp-work/repo", ["dqvp_work_dirname"]),
    ])
    def test_detects_every_machine_path_pattern(self, text, rules):
        violations = path_firewall.scan_text(text)
        detected_rules = {v["rule"] for v in violations}
        for rule in rules:
            assert rule in detected_rules, (rule, text, violations)

    def test_clean_relative_paths_are_accepted(self):
        text = ("evidence/final_execution/run_1/manifest.json\n"
                "scripts/release_gate.py\n"
                "data/generated/final_3m/consumer.csv")
        assert path_firewall.scan_text(text) == []

    def test_json_unicode_escapes_are_not_unc_paths(self):
        """JSON \\uXXXX escape sequences (e.g. serialized em-dashes)
        are serialized characters, never machine paths — no false
        positives allowed."""
        text = ('"note": "recorded as NOT_VERIFIED \\u2014 never '
                'reported as PASS", "em": "\\u2013", "arrow": "\\u2192"')
        assert path_firewall.scan_text(text) == []

    def test_real_unc_path_in_json_escaped_form_detected(self):
        # a real UNC share inside a JSON value appears in the raw file
        # bytes as \\\\server\\share (escaped backslashes)
        raw = r'cmd "\\\\fileserver\\share\\x.csv"'
        violations = path_firewall.scan_text(raw)
        assert any(v["rule"] == "unc_share" for v in violations)

    def test_unc_path_in_plain_text_detected(self):
        raw = "mount point \\\\nas01\\exports$\\file.csv ok"
        violations = path_firewall.scan_text(raw)
        assert any(v["rule"] == "unc_share" for v in violations)

    def test_violations_report_line_and_column(self):
        text = "line one ok\nline two has /home/z/leak here"
        v = path_firewall.scan_text(text)
        assert len(v) == 1
        assert v[0]["line"] == 2
        assert v[0]["column"] >= 1
        assert v[0]["source"] == "<text>"

    def test_scan_file_reports_repo_relative_source(self, tmp_path):
        f = tmp_path / "doc.json"
        f.write_text('{"cmd": "/home/z/x"}')
        v = path_firewall.scan_file(str(f), repo_root=str(tmp_path))
        assert v and v[0]["source"] == "doc.json"

    def test_release_scan_fails_on_missing_artifact(self, tmp_path):
        report = path_firewall.scan_release_artifacts(str(tmp_path),
                                                      ["nope.json"])
        assert report["verdict"] == "FAIL"
        assert report["missing"] == ["nope.json"]

    def test_release_scan_fails_on_leaked_path(self, tmp_path):
        (tmp_path / "FINAL_RESULTS.json").write_text(
            '{"x": "/home/z/leak"}')
        report = path_firewall.scan_release_artifacts(
            str(tmp_path), ["FINAL_RESULTS.json"])
        assert report["verdict"] == "FAIL"
        assert report["violation_count"] >= 1

    def test_release_scan_passes_on_clean_artifact(self, tmp_path):
        (tmp_path / "FINAL_RESULTS.json").write_text(
            '{"input": "evidence/run_1/manifest.json"}')
        report = path_firewall.scan_release_artifacts(
            str(tmp_path), ["FINAL_RESULTS.json"])
        assert report["verdict"] == "PASS"
        assert report["violations"] == []

    def test_actual_repo_release_documents_are_clean(self):
        """The real README/RELEASE_NOTES must contain no machine paths."""
        for rel in ("README.md", "RELEASE_NOTES.md"):
            path = os.path.join(REPO_ROOT, rel)
            if os.path.isfile(path):
                assert path_firewall.scan_file(path, repo_root=REPO_ROOT) == [], rel


class TestTruthModel:
    """Phase 13: closed status vocabulary + verdict derivation."""

    def test_unknown_status_rejected(self):
        with pytest.raises(truth_model.TruthModelError):
            truth_model.validate_status("PROBABLY_FINE")

    @pytest.mark.parametrize("status", truth_model.EVIDENCE_STATUSES)
    def test_all_seven_statuses_accepted(self, status):
        assert truth_model.validate_status(status) == status

    def test_unknown_final_verdict_rejected(self):
        with pytest.raises(truth_model.TruthModelError):
            truth_model.validate_final_verdict("probably PASS")

    def test_not_verified_never_becomes_verified_claim(self):
        """Honest NOT_VERIFIED recording is consistent; a null fact
        masquerading as VERIFIED_LOCALLY is inconsistent (rejected)."""
        honest = truth_model.classify_claim(
            "missing measurement",
            truth_model.fact(None),
            truth_model.interpretation("NOT_VERIFIED"))
        assert honest["consistent"] is True  # honest recording allowed
        assert honest["fact"]["value"] is None
        masquerade = truth_model.classify_claim(
            "missing measurement",
            truth_model.fact(None),
            truth_model.interpretation("VERIFIED_LOCALLY"))
        assert masquerade["consistent"] is False  # false-PASS prevented

    def test_worst_status_orders_correctly(self):
        assert truth_model.worst_status(
            ["VERIFIED_LOCALLY", "HISTORICAL"]) == "HISTORICAL"
        assert truth_model.worst_status(
            ["VERIFIED_LOCALLY", "NOT_VERIFIED"]) == "NOT_VERIFIED"
        assert truth_model.worst_status(
            ["REVIEW_REQUIRED", "HISTORICAL"]) == "REVIEW_REQUIRED"

    def test_derive_final_verdict_blocking_failure(self):
        v = truth_model.derive_final_verdict(
            [("a", True)], ["gate failed"], [])
        assert v == "FAIL"

    def test_derive_final_verdict_unestablished_claim(self):
        v = truth_model.derive_final_verdict(
            [("required_claim", False)], [], [])
        assert v == "NOT_VERIFIED"

    def test_derive_final_verdict_blocking_limitation(self):
        v = truth_model.derive_final_verdict(
            [("a", True)], [], [{"blocks_release": True}])
        assert v == "FAIL"

    def test_derive_final_verdict_documented_limitations(self):
        v = truth_model.derive_final_verdict(
            [("a", True)], [], [{"blocks_release": False}])
        assert v == "PASS_WITH_DOCUMENTED_LIMITATIONS"

    def test_derive_final_verdict_clean_pass(self):
        v = truth_model.derive_final_verdict([("a", True)], [], [])
        assert v == "PASS"

    def test_interpretation_of_measurement_is_not_a_measurement(self):
        """A status is never accepted where a value is required."""
        fact = truth_model.fact(48000000)
        interp = truth_model.interpretation("VERIFIED_LOCALLY")
        assert fact["level"] == "FACT"
        assert interp["level"] == "INTERPRETATION"
        assert fact["value"] != interp["status"]  # levels never mix
