"""Platform configuration loader from YAML and environment variables."""

import os
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import yaml


@dataclass
class PlatformConfig:
    """Central configuration for the Data Quality Platform."""

    # SLA thresholds
    completeness_threshold: float = 0.95
    validity_threshold: float = 0.95
    consistency_threshold: float = 0.90
    uniqueness_threshold: float = 0.95
    accuracy_threshold: float = 0.90
    freshness_threshold: float = 0.95
    geography_quality_threshold: float = 0.90
    email_quality_threshold: float = 0.95

    # Evidence settings
    evidence_base_dir: str = "evidence"
    generate_manifests: bool = True
    compute_sha256: bool = True
    fsync_evidence: bool = True

    # Security
    pii_masking_enabled: bool = True
    restrict_output_permissions: bool = False
    audit_access_logging: bool = True

    # Monitoring
    monitoring_enabled: bool = True
    alert_on_sla_breach: bool = True
    alert_on_validation_failure: bool = True
    alert_on_reconciliation_failure: bool = True

    # ClickHouse
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_database: str = "data_quality"

    # Secret placeholders (never hardcode real credentials)
    slack_webhook_url: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    alert_email_recipients: list = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str) -> "PlatformConfig":
        """Load configuration from a YAML file, then apply env overrides.

        Supported YAML structure (all sections optional):

            quality_thresholds:   # <key> maps to the <key>_threshold field
                completeness: 0.95        # short style ...
                validity_threshold: 0.95  # ... or legacy full field-name style
            evidence:             # keys match PlatformConfig field names
                generate_manifests: true
            security:             # keys match PlatformConfig field names
                pii_masking_enabled: true
            monitoring:           # keys match PlatformConfig field names
                monitoring_enabled: true
            clickhouse:           # short keys map to the clickhouse_* fields
                host: localhost
                port: 8123
                user: default
                password: ""
                database: data_quality

        Top-level keys that directly match field names (e.g.
        ``evidence_base_dir: ...``) remain accepted for backwards
        compatibility.

        Precedence: dataclass defaults < YAML file < DQ_* environment
        variables (the DQ_* set is exactly the env_overrides mapping applied
        below; threshold fields have no DQ_* env override). A missing file
        yields pure defaults.

        Null values never override configuration: a null key inside any
        accepted section (quality_thresholds, evidence, security, monitoring,
        clickhouse) or a null legacy top-level field name emits a warning and
        keeps the existing/default value.

        Unknown sections and keys are reported via warnings.warn and ignored -
        never silently dropped, and they never stop recognized values from
        loading. When the same field is provided more than once (legacy
        top-level key and/or section entry), the last non-null occurrence in
        YAML document order wins (deterministic). A null threshold keeps its
        default; a non-numeric threshold value raises ValueError.
        """
        raw: Dict[str, Any] = {}
        if os.path.exists(path):
            with open(path, "r") as f:
                raw = yaml.safe_load(f) or {}

        config_dict: Dict[str, Any] = {}

        # Short-key aliases for sections whose YAML keys are not field names.
        section_aliases: Dict[str, Dict[str, str]] = {
            "clickhouse": {
                "host": "clickhouse_host",
                "port": "clickhouse_port",
                "user": "clickhouse_user",
                "password": "clickhouse_password",
                "database": "clickhouse_database",
            },
        }
        # Sections whose YAML keys already match field names exactly.
        direct_sections = ("evidence", "security", "monitoring")

        for section, values in raw.items():
            if not isinstance(values, dict):
                # Legacy top-level style: the key itself is a field name.
                if section in cls.__dataclass_fields__:
                    if values is None:
                        # F2: null never overrides an existing/default value.
                        warnings.warn(
                            f"PlatformConfig.from_yaml({path!r}): top-level "
                            f"key {section!r} is null; keeping default"
                        )
                        continue
                    config_dict[section] = values
                else:
                    warnings.warn(
                        f"PlatformConfig.from_yaml({path!r}): unknown "
                        f"top-level key {section!r} ignored"
                    )
                continue
            if section == "quality_thresholds":
                for key, val in values.items():
                    field_name = f"{key}_threshold"
                    if field_name not in cls.__dataclass_fields__:
                        # F1: legacy style spells out the full field name
                        # (e.g. "completeness_threshold" instead of
                        # "completeness"). Accepted only for actual threshold
                        # fields; anything else stays an unknown-key warning.
                        if key.endswith("_threshold") and key in cls.__dataclass_fields__:
                            field_name = key
                        else:
                            warnings.warn(
                                f"PlatformConfig.from_yaml({path!r}): unknown "
                                f"quality threshold {key!r} ignored"
                            )
                            continue
                    if val is None:
                        warnings.warn(
                            f"PlatformConfig.from_yaml({path!r}): quality "
                            f"threshold {key!r} is null; keeping default"
                        )
                        continue
                    config_dict[field_name] = float(val)
            elif section in direct_sections or section in section_aliases:
                aliases = section_aliases.get(section, {})
                for key, val in values.items():
                    field_name = aliases.get(key, key)
                    if field_name not in cls.__dataclass_fields__:
                        warnings.warn(
                            f"PlatformConfig.from_yaml({path!r}): unknown "
                            f"key {section}.{key} ignored"
                        )
                        continue
                    if val is None:
                        # F2: null never overrides an existing/default value.
                        warnings.warn(
                            f"PlatformConfig.from_yaml({path!r}): "
                            f"{section}.{key} is null; keeping default"
                        )
                        continue
                    config_dict[field_name] = val
            else:
                warnings.warn(
                    f"PlatformConfig.from_yaml({path!r}): unknown section "
                    f"{section!r} ignored"
                )

        # Environment overrides have the highest precedence (above file values).
        env_overrides = {
            "clickhouse_host": "DQ_CLICKHOUSE_HOST",
            "clickhouse_port": "DQ_CLICKHOUSE_PORT",
            "clickhouse_user": "DQ_CLICKHOUSE_USER",
            "clickhouse_password": "DQ_CLICKHOUSE_PASSWORD",
            "slack_webhook_url": "DQ_SLACK_WEBHOOK_URL",
            "smtp_host": "DQ_SMTP_HOST",
            "smtp_port": "DQ_SMTP_PORT",
            "smtp_user": "DQ_SMTP_USER",
            "smtp_password": "DQ_SMTP_PASSWORD",
        }
        for attr, env_var in env_overrides.items():
            val = os.environ.get(env_var)
            if val is not None:
                if attr == "clickhouse_port" or attr == "smtp_port":
                    config_dict[attr] = int(val)
                else:
                    config_dict[attr] = val

        return cls(**{k: v for k, v in config_dict.items() if k in cls.__dataclass_fields__})

    def get_quality_thresholds(self) -> Dict[str, float]:
        """Return all quality thresholds as a dict."""
        return {
            "completeness": self.completeness_threshold,
            "validity": self.validity_threshold,
            "consistency": self.consistency_threshold,
            "uniqueness": self.uniqueness_threshold,
            "accuracy": self.accuracy_threshold,
            "freshness": self.freshness_threshold,
            "geography_quality": self.geography_quality_threshold,
            "email_quality": self.email_quality_threshold,
        }
