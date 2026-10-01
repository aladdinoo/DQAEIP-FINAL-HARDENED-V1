"""R3 config-wiring tests: configs/quality.yaml must actually be honored.

Scope (R3 only):
- PlatformConfig.from_yaml maps quality_thresholds.<key> -> <key>_threshold.
- Nested evidence/security/monitoring sections flatten onto field names.
- clickhouse short keys map onto the clickhouse_* fields.
- Precedence: dataclass defaults < YAML file < DQ_* environment variables.
- Unknown keys are reported via warnings.warn, never silently dropped.
- YAML-loaded thresholds change QualityMonitor SLA outcomes.
- CLI `validate` honors the config (end-to-end, thresholds land in
  monitoring.json) and the SHIPPED configs/quality.yaml is behaviorally
  identical to pure defaults (no default drift).

Out of scope (NOT tested here, NOT changed): SP1 semantics, V1 geography
rules, E1, ClickHouse data, registry geography mode, DL001-DL015.

Follow-up coverage (post-review of commit 2a8b7e1, verdict
APPROVED WITH NOTES):
- F1: quality_thresholds accepts BOTH short and legacy full field-name styles.
- F2: null values in any recognized position warn and keep defaults.
- N1: explicit --config missing -> non-zero exit; default path unchanged.
"""

import dataclasses
import json
import os
import subprocess
import sys
import warnings

import yaml

from data_quality_platform.config import PlatformConfig
from data_quality_platform.monitoring.quality import QualityMonitor

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHIPPED_CONFIG = os.path.join(REPO_ROOT, "configs", "quality.yaml")

DEFAULT_THRESHOLDS = {
    "completeness": 0.95,
    "validity": 0.95,
    "consistency": 0.90,
    "uniqueness": 0.95,
    "accuracy": 0.90,
    "freshness": 0.95,
    "geography_quality": 0.90,
    "email_quality": 0.95,
}


def _write_yaml(tmp_path, content: dict) -> str:
    path = tmp_path / "probe.yaml"
    path.write_text(yaml.safe_dump(content), encoding="utf-8")
    return str(path)


class TestPlatformConfigFromYaml:
    def test_shipped_yaml_equals_pure_defaults(self):
        """Requirement 7: with the shipped configs/quality.yaml (no overrides),
        the loaded config must be identical to pure defaults (net-zero change)."""
        loaded = PlatformConfig.from_yaml(SHIPPED_CONFIG)
        assert dataclasses.asdict(loaded) == dataclasses.asdict(PlatformConfig())
        assert loaded.get_quality_thresholds() == DEFAULT_THRESHOLDS

    def test_missing_file_returns_pure_defaults(self, tmp_path):
        loaded = PlatformConfig.from_yaml(str(tmp_path / "absent.yaml"))
        assert dataclasses.asdict(loaded) == dataclasses.asdict(PlatformConfig())

    def test_yaml_thresholds_override_defaults(self, tmp_path):
        path = _write_yaml(
            tmp_path,
            {"quality_thresholds": {"completeness": 0.11, "validity": 0.22}},
        )
        cfg = PlatformConfig.from_yaml(path)
        assert cfg.completeness_threshold == 0.11
        assert cfg.validity_threshold == 0.22
        # Per-key override: untouched thresholds keep their defaults.
        assert cfg.consistency_threshold == 0.90
        assert cfg.geography_quality_threshold == 0.90
        # And the values flow out in the QualityMonitor key space.
        assert cfg.get_quality_thresholds()["completeness"] == 0.11
        assert cfg.get_quality_thresholds()["validity"] == 0.22

    def test_nested_evidence_security_monitoring_flatten(self, tmp_path):
        path = _write_yaml(
            tmp_path,
            {
                "evidence": {
                    "generate_manifests": False,
                    "compute_sha256": False,
                    "fsync_evidence": False,
                },
                "security": {
                    "pii_masking_enabled": False,
                    "restrict_output_permissions": True,
                    "audit_access_logging": False,
                },
                "monitoring": {
                    "monitoring_enabled": False,
                    "alert_on_sla_breach": False,
                    "alert_on_validation_failure": False,
                    "alert_on_reconciliation_failure": False,
                },
            },
        )
        cfg = PlatformConfig.from_yaml(path)
        assert cfg.generate_manifests is False
        assert cfg.compute_sha256 is False
        assert cfg.fsync_evidence is False
        assert cfg.pii_masking_enabled is False
        assert cfg.restrict_output_permissions is True
        assert cfg.audit_access_logging is False
        assert cfg.monitoring_enabled is False
        assert cfg.alert_on_sla_breach is False
        assert cfg.alert_on_validation_failure is False
        assert cfg.alert_on_reconciliation_failure is False

    def test_clickhouse_short_keys_map_to_fields(self, tmp_path):
        path = _write_yaml(
            tmp_path,
            {
                "clickhouse": {
                    "host": "10.1.2.3",
                    "port": 9123,
                    "user": "svc",
                    "password": "pw",
                    "database": "dbx",
                }
            },
        )
        cfg = PlatformConfig.from_yaml(path)
        assert cfg.clickhouse_host == "10.1.2.3"
        assert cfg.clickhouse_port == 9123
        assert cfg.clickhouse_user == "svc"
        assert cfg.clickhouse_password == "pw"
        assert cfg.clickhouse_database == "dbx"

    def test_env_overrides_beat_yaml(self, tmp_path, monkeypatch):
        path = _write_yaml(
            tmp_path,
            {"clickhouse": {"host": "10.9.9.9", "port": 9999}},
        )
        monkeypatch.setenv("DQ_CLICKHOUSE_HOST", "10.255.255.1")
        monkeypatch.setenv("DQ_CLICKHOUSE_PORT", "19000")
        cfg = PlatformConfig.from_yaml(path)
        assert cfg.clickhouse_host == "10.255.255.1"
        assert cfg.clickhouse_port == 19000

    def test_top_level_field_names_still_accepted(self, tmp_path):
        """Legacy behavior preserved: a top-level key matching a field name
        loads without warnings."""
        path = tmp_path / "legacy.yaml"
        path.write_text("evidence_base_dir: custom_evidence\n", encoding="utf-8")
        with warnings.catch_warnings():
            warnings.simplefilter("error")  # any warning -> failure
            cfg = PlatformConfig.from_yaml(str(path))
        assert cfg.evidence_base_dir == "custom_evidence"

    def test_unknown_keys_warn_and_do_not_load(self, tmp_path):
        path = tmp_path / "bogus.yaml"
        path.write_text(
            "bogus_top_level: 1\n"
            "evidence:\n"
            "  not_a_real_field: false\n"
            "quality_thresholds:\n"
            "  completness: 0.5\n",  # deliberate typo
            encoding="utf-8",
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cfg = PlatformConfig.from_yaml(str(path))
        messages = [str(w.message) for w in caught]
        unknown = [m for m in messages if "unknown" in m]
        assert len(unknown) == 3, messages
        # Nothing loaded from the unknown keys.
        assert dataclasses.asdict(cfg) == dataclasses.asdict(PlatformConfig())


class TestConfigChangesMonitoringBehavior:
    def _compute(self, monitor):
        return monitor.compute(
            total_rows=100,
            flag_counts={
                "email_blank": 0,
                "email_syntax_failure": 50,
                "first_name_cleaning_candidate": 0,
                "last_name_cleaning_candidate": 0,
                "proposed_email_export_eligible": 100,
            },
            blank_counts={"registration_date": 0},
            unique_id_count=100,
            zip_state_mismatch_count=0,
            zip_state_assessable_count=80,
        )

    def test_yaml_threshold_flip_validity_sla(self, tmp_path):
        """validity score = 1 - 50/100 = 0.50: fails the default 0.95 SLA,
        passes a YAML-overridden 0.22 SLA. Same inputs, different config."""
        path = _write_yaml(tmp_path, {"quality_thresholds": {"validity": 0.22}})
        cfg = PlatformConfig.from_yaml(path)

        from_yaml_monitor = self._compute(QualityMonitor(thresholds=cfg.get_quality_thresholds()))
        assert from_yaml_monitor["scores"]["validity"] == 0.5
        assert from_yaml_monitor["sla_results"]["validity"] is True
        assert from_yaml_monitor["sla_passed"] is True
        assert from_yaml_monitor["thresholds"]["validity"] == 0.22

        default_monitor = self._compute(QualityMonitor())
        assert default_monitor["sla_results"]["validity"] is False
        assert default_monitor["sla_passed"] is False
        assert default_monitor["thresholds"] == DEFAULT_THRESHOLDS


class TestCliHonorsConfig:
    def _run_validate(self, tmp_path, csv_path, evidence_dir, config_path=None):
        cmd = [
            sys.executable, "-m", "runner.cli", "validate",
            "--csv", str(csv_path),
            "--output", str(tmp_path / "out.csv"),
            "--run-id", "cfg_test",
            "--evidence-dir", str(evidence_dir),
        ]
        if config_path is not None:
            cmd += ["--config", str(config_path)]
        return subprocess.run(
            cmd, capture_output=True, text=True, cwd=REPO_ROOT,
            env={**os.environ, "PYTHONPATH": REPO_ROOT},
        )

    def test_cli_validate_honors_config_thresholds(self, tmp_path):
        from data_quality_platform.generation.synthetic import SyntheticDataGenerator

        csv_path = tmp_path / "in.csv"
        SyntheticDataGenerator(seed=20260821).generate(50, str(csv_path))

        # Probe config: accuracy threshold 0.99 can never be met by this
        # dataset (deterministic accuracy score 0.98 for seed 20260821
        # at 50 rows) -> deterministic SLA failure. NOTE: thresholds must
        # stay within [0, 1] — the input-contract preflight (DQAVP
        # hardening Section 11) now blocks out-of-range configurations
        # fail-closed, which is why the historical 1.01 probe value was
        # replaced by a valid-but-unachievable threshold.
        probe = tmp_path / "probe.yaml"
        probe.write_text("quality_thresholds:\n  accuracy: 0.99\n", encoding="utf-8")

        ev_probe = tmp_path / "ev_probe"
        r1 = self._run_validate(tmp_path, csv_path, ev_probe, config_path=probe)
        assert r1.returncode == 0, r1.stderr
        mon_probe = json.loads((ev_probe / "monitoring.json").read_text())
        assert mon_probe["thresholds"]["accuracy"] == 0.99
        assert mon_probe["thresholds"]["validity"] == 0.95  # per-key override only
        assert mon_probe["sla_results"]["accuracy"] is False
        assert mon_probe["sla_passed"] is False

        # Default run (shipped configs/quality.yaml): thresholds are the
        # shipped values, proving default behavior is preserved.
        ev_def = tmp_path / "ev_def"
        r2 = self._run_validate(tmp_path, csv_path, ev_def)
        assert r2.returncode == 0, r2.stderr
        mon_def = json.loads((ev_def / "monitoring.json").read_text())
        assert mon_def["thresholds"] == DEFAULT_THRESHOLDS
        assert mon_def["thresholds"] != mon_probe["thresholds"]


# ---------------------------------------------------------------------------
# R3 review follow-up (F1 / F2 / N1) — added after the independent review of
# commit 2a8b7e1 (verdict: APPROVED WITH NOTES). Scope: legacy threshold-key
# compatibility, null-handling consistency, explicit --config missing-file
# safety. No rule/registry/SP1/E1/ClickHouse/production behavior touched.
# ---------------------------------------------------------------------------

def _run_cli_validate(tmp_path, csv_path, evidence_dir, extra_args=(), cwd=None):
    """Run `runner.cli validate` in a subprocess (cwd defaults to REPO_ROOT)."""
    cmd = [
        sys.executable, "-m", "runner.cli", "validate",
        "--csv", str(csv_path),
        "--output", str(tmp_path / "out.csv"),
        "--run-id", "cfg_test",
        "--evidence-dir", str(evidence_dir),
    ]
    cmd += list(extra_args)
    return subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=cwd if cwd is not None else REPO_ROOT,
        env={**os.environ, "PYTHONPATH": REPO_ROOT},
    )


class TestF1LegacyThresholdSyntax:
    """F1: quality_thresholds accepts BOTH short and legacy field-name styles."""

    def test_f1_short_threshold_syntax(self, tmp_path):  # TEST 1
        path = _write_yaml(tmp_path, {"quality_thresholds": {"completeness": 0.50}})
        cfg = PlatformConfig.from_yaml(path)
        assert cfg.completeness_threshold == 0.50

    def test_f1_legacy_threshold_syntax(self, tmp_path):  # TEST 2
        path = _write_yaml(
            tmp_path, {"quality_thresholds": {"completeness_threshold": 0.50}}
        )
        cfg = PlatformConfig.from_yaml(path)
        assert cfg.completeness_threshold == 0.50

    def test_f1_generic_across_all_thresholds_mixed_styles(self, tmp_path):  # TEST 3
        """Compatibility is generic: every threshold field accepts both styles."""
        path = _write_yaml(tmp_path, {"quality_thresholds": {
            "completeness_threshold": 0.50,        # legacy style
            "validity": 0.60,                      # short style
            "consistency_threshold": 0.70,         # legacy
            "uniqueness": 0.80,                    # short
            "accuracy_threshold": 0.85,            # legacy
            "freshness": 0.75,                     # short
            "geography_quality_threshold": 0.65,   # legacy
            "email_quality": 0.55,                 # short
        }})
        cfg = PlatformConfig.from_yaml(path)
        assert cfg.completeness_threshold == 0.50
        assert cfg.validity_threshold == 0.60
        assert cfg.consistency_threshold == 0.70
        assert cfg.uniqueness_threshold == 0.80
        assert cfg.accuracy_threshold == 0.85
        assert cfg.freshness_threshold == 0.75
        assert cfg.geography_quality_threshold == 0.65
        assert cfg.email_quality_threshold == 0.55

    def test_f1_unknown_threshold_key_warns_and_neighbors_load(self, tmp_path):  # TEST 4
        path = _write_yaml(tmp_path, {"quality_thresholds": {
            "bogus_threshold": 0.50,
            "validity": 0.33,
        }})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cfg = PlatformConfig.from_yaml(path)
        messages = [str(w.message) for w in caught]
        assert any("unknown" in m and "bogus_threshold" in m for m in messages)
        assert cfg.validity_threshold == 0.33      # neighbor still loads
        assert cfg.completeness_threshold == 0.95  # untouched default

    def test_f1_non_threshold_field_name_under_thresholds_warns(self, tmp_path):
        """The legacy fallback is limited to real threshold fields: a
        non-threshold field name under quality_thresholds stays an
        unknown-key warning (no silent cross-field coercion)."""
        path = _write_yaml(
            tmp_path, {"quality_thresholds": {"evidence_base_dir": "oops"}}
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cfg = PlatformConfig.from_yaml(path)
        messages = [str(w.message) for w in caught]
        assert any("unknown" in m and "evidence_base_dir" in m for m in messages)
        assert cfg.evidence_base_dir == "evidence"  # default preserved


class TestF2NullValueHandling:
    """F2: null never overrides defaults for recognized fields, anywhere."""

    def test_f2_null_threshold_preserves_default(self, tmp_path):  # TEST 5
        path = _write_yaml(tmp_path, {"quality_thresholds": {"completeness": None}})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cfg = PlatformConfig.from_yaml(path)
        assert any("null" in str(w.message) for w in caught)
        assert cfg.completeness_threshold == 0.95

    def test_f2_null_evidence_field(self, tmp_path):  # TEST 6
        path = _write_yaml(tmp_path, {"evidence": {"generate_manifests": None}})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cfg = PlatformConfig.from_yaml(path)
        assert any("null" in str(w.message) for w in caught)
        assert cfg.generate_manifests is True

    def test_f2_null_security_field(self, tmp_path):  # TEST 7
        path = _write_yaml(tmp_path, {"security": {"pii_masking_enabled": None}})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cfg = PlatformConfig.from_yaml(path)
        assert any("null" in str(w.message) for w in caught)
        assert cfg.pii_masking_enabled is True

    def test_f2_null_monitoring_field(self, tmp_path):  # TEST 8
        path = _write_yaml(tmp_path, {"monitoring": {"monitoring_enabled": None}})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cfg = PlatformConfig.from_yaml(path)
        assert any("null" in str(w.message) for w in caught)
        assert cfg.monitoring_enabled is True

    def test_f2_null_clickhouse_field(self, tmp_path):  # TEST 9
        path = _write_yaml(tmp_path, {"clickhouse": {"host": None}})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cfg = PlatformConfig.from_yaml(path)
        assert any("null" in str(w.message) for w in caught)
        assert cfg.clickhouse_host == "localhost"

    def test_f2_null_legacy_top_level_field(self, tmp_path):
        """Null handling is consistent for the legacy top-level style too."""
        path = tmp_path / "legacy_null.yaml"
        path.write_text("evidence_base_dir: null\n", encoding="utf-8")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cfg = PlatformConfig.from_yaml(str(path))
        assert any("null" in str(w.message) for w in caught)
        assert cfg.evidence_base_dir == "evidence"

    def test_f2_mixed_unknown_null_valid_in_one_file(self, tmp_path):  # TEST 10
        path = _write_yaml(tmp_path, {
            "bogus_top_level": 1,
            "quality_thresholds": {"validity": None, "completeness": 0.33},
            "evidence": {"generate_manifests": False, "fsync_evidence": None},
        })
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cfg = PlatformConfig.from_yaml(path)
        messages = [str(w.message) for w in caught]
        # unknown key warned
        assert any("unknown top-level key" in m and "bogus_top_level" in m
                   for m in messages)
        # both nulls warned
        assert any("validity" in m and "null" in m for m in messages)
        assert any("fsync_evidence" in m and "null" in m for m in messages)
        # nulls preserved defaults
        assert cfg.validity_threshold == 0.95
        assert cfg.fsync_evidence is True
        # valid values still applied
        assert cfg.completeness_threshold == 0.33
        assert cfg.generate_manifests is False


class TestN1ExplicitConfigPath:
    """N1: explicit --config missing -> hard failure; default path unchanged."""

    def test_n1_explicit_missing_config_fails(self, tmp_path):  # TEST 11
        from data_quality_platform.generation.synthetic import SyntheticDataGenerator

        csv_path = tmp_path / "in.csv"
        SyntheticDataGenerator(seed=20260821).generate(50, str(csv_path))
        ev = tmp_path / "ev_missing"
        r = _run_cli_validate(
            tmp_path, csv_path, ev,
            extra_args=["--config", str(tmp_path / "nope.yaml")],
        )
        assert r.returncode != 0, (r.stdout, r.stderr)
        assert "does not exist" in r.stderr
        assert not ev.exists()  # validation never started (no silent fallback)

    def test_n1_default_path_cwd_independent(self, tmp_path):  # TEST 12
        """Without --config the shipped config is used regardless of CWD."""
        from data_quality_platform.generation.synthetic import SyntheticDataGenerator

        csv_path = tmp_path / "in.csv"
        SyntheticDataGenerator(seed=20260821).generate(50, str(csv_path))
        ev = tmp_path / "ev_cwd"
        r = _run_cli_validate(tmp_path, csv_path, ev, cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        mon = json.loads((ev / "monitoring.json").read_text())
        assert mon["thresholds"] == DEFAULT_THRESHOLDS

    def test_n1_explicit_existing_config_still_loads(self, tmp_path):
        """Valid explicit paths behave exactly as before N1."""
        from data_quality_platform.generation.synthetic import SyntheticDataGenerator

        probe = tmp_path / "probe.yaml"
        probe.write_text("quality_thresholds:\n  validity: 0.22\n", encoding="utf-8")
        csv_path = tmp_path / "in.csv"
        SyntheticDataGenerator(seed=20260821).generate(50, str(csv_path))
        ev = tmp_path / "ev_valid"
        r = _run_cli_validate(
            tmp_path, csv_path, ev, extra_args=["--config", str(probe)]
        )
        assert r.returncode == 0, r.stderr
        mon = json.loads((ev / "monitoring.json").read_text())
        assert mon["thresholds"]["validity"] == 0.22


class TestPrecedenceAndRobustness:
    def test_precedence_defaults_then_yaml_then_env(self, tmp_path, monkeypatch):  # TEST 14
        """defaults < YAML < DQ_* environment (proven layer by layer).

        The platform's DQ_* env contract is exactly the env_overrides mapping
        in settings.py (clickhouse_*/slack/smtp); threshold fields have no
        DQ_* env override, so thresholds participate as defaults < YAML only.
        """
        assert PlatformConfig().clickhouse_host == "localhost"  # layer 1: defaults
        path = _write_yaml(tmp_path, {"clickhouse": {"host": "10.9.9.9", "port": 9999}})
        cfg_yaml = PlatformConfig.from_yaml(path)               # layer 2: YAML
        assert cfg_yaml.clickhouse_host == "10.9.9.9"
        assert cfg_yaml.clickhouse_port == 9999
        monkeypatch.setenv("DQ_CLICKHOUSE_HOST", "10.255.255.1")  # layer 3: env
        monkeypatch.setenv("DQ_CLICKHOUSE_PORT", "19000")
        cfg_env = PlatformConfig.from_yaml(path)
        assert cfg_env.clickhouse_host == "10.255.255.1"
        assert cfg_env.clickhouse_port == 19000
        # YAML still beats defaults for thresholds (no threshold env var exists)
        thr = tmp_path / "thr.yaml"
        thr.write_text(
            yaml.safe_dump({"quality_thresholds": {"completeness": 0.50}}),
            encoding="utf-8",
        )
        assert PlatformConfig.from_yaml(str(thr)).completeness_threshold == 0.50

    def test_unknown_keys_do_not_stop_loading(self, tmp_path):  # TEST 15
        path = _write_yaml(tmp_path, {
            "totally_unknown_section": {"x": 1},
            "quality_thresholds": {"validity": 0.22},
            "monitoring": {"monitoring_enabled": False},
        })
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            cfg = PlatformConfig.from_yaml(path)
        assert any("unknown section" in str(w.message) for w in caught)
        assert cfg.validity_threshold == 0.22
        assert cfg.monitoring_enabled is False
