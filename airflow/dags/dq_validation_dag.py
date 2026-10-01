from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import os
import sys

# Ensure project root is on path
DAGS_FOLDER = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(DAGS_FOLDER))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def preflight(**context):
    """Validate environment and configuration."""
    from data_quality_platform.rules import RuleRegistry
    from data_quality_platform.schema.validator import SchemaValidator
    rr = RuleRegistry.create_default()
    valid, errors, warnings = rr.validate()
    assert valid, f"Rule registry invalid: {errors}"
    sv = SchemaValidator()
    assert sv.validate_header(list(sv.expected_columns))[0], "Schema validator broken"
    print(f"Preflight passed: {rr.count} rules, schema OK")
    return {"rule_count": rr.count, "registry_hash": rr.compute_registry_hash()}


def schema_validation(**context):
    """Validate source CSV schema."""
    from data_quality_platform.schema.validator import SchemaValidator
    csv_path = context["params"]["csv_path"]
    sv = SchemaValidator()
    valid, errors = sv.validate_csv_file(csv_path)
    if not valid:
        raise ValueError(f"Schema validation failed: {errors}")
    schema_hash = sv.compute_schema_hash(list(sv.expected_columns))
    print(f"Schema valid, hash={schema_hash[:16]}...")
    return {"schema_hash": schema_hash, "valid": True}


def rule_validation(**context):
    """Validate rule registry."""
    from data_quality_platform.rules import RuleRegistry
    rr = RuleRegistry.create_default()
    valid, errors, warnings = rr.validate()
    if not valid:
        raise ValueError(f"Rule validation failed: {errors}")
    print(f"Rules valid: {rr.count} rules, {len(warnings)} warnings")
    return {"rule_count": rr.count, "warnings": warnings}


def quality_validation(**context):
    """Run full quality validation pipeline."""
    from data_quality_platform.validation.engine import ValidationEngine
    from data_quality_platform.rules.registry import RuleRegistry
    from data_quality_platform.config import PlatformConfig
    params = context["params"]
    # R3 wiring: honor configs/quality.yaml SLA thresholds (lazy import keeps
    # DAG parsing independent of the config file).
    config = PlatformConfig.from_yaml(os.path.join(PROJECT_ROOT, "configs", "quality.yaml"))
    rules = RuleRegistry.create_default()
    engine = ValidationEngine(
        rules=rules,
        run_id=context["run_id"],
        evidence_dir=params["evidence_dir"],
        config_thresholds=config.get_quality_thresholds(),
    )
    result = engine.validate(csv_path=params["csv_path"], output_path=params["output_path"])
    if not result.success:
        raise RuntimeError(f"Validation failed: {result.error}")
    print(f"Validation completed: {result.input_row_count} rows, score={result.monitoring_score}")
    return {"row_count": result.input_row_count, "score": result.monitoring_score}


def monitoring(**context):
    """Evaluate monitoring and SLA."""
    import json
    params = context["params"]
    mon_path = os.path.join(params["evidence_dir"], "monitoring.json")
    if os.path.exists(mon_path):
        with open(mon_path) as f:
            mon = json.load(f)
        print(f"SLA passed: {mon.get('sla_passed')}, Score: {mon.get('overall_score')}")
        return mon
    return {"sla_passed": False, "error": "monitoring.json not found"}


def evidence_finalization(**context):
    """Verify evidence completeness."""
    import json
    params = context["params"]
    manifest_path = os.path.join(params["evidence_dir"], "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)
        print(f"Manifest type: {manifest.get('manifest_type')}")
        return {"manifest_type": manifest.get("manifest_type")}
    raise FileNotFoundError(f"Manifest not found: {manifest_path}")


default_args = {
    "owner": "data-quality",
    "depends_on_past": False,
    "email_on_failure": True,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
    "execution_timeout": timedelta(minutes=30),
}

dag = DAG(
    "dq_validation",
    default_args=default_args,
    description="Data Quality Validation Pipeline",
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["data-quality", "validation"],
)

preflight_task = PythonOperator(
    task_id="preflight",
    python_callable=preflight,
    dag=dag,
)

schema_task = PythonOperator(
    task_id="schema_validation",
    python_callable=schema_validation,
    dag=dag,
)

rule_task = PythonOperator(
    task_id="rule_validation",
    python_callable=rule_validation,
    dag=dag,
)

validation_task = PythonOperator(
    task_id="quality_validation",
    python_callable=quality_validation,
    dag=dag,
)

monitoring_task = PythonOperator(
    task_id="monitoring",
    python_callable=monitoring,
    dag=dag,
)

evidence_task = PythonOperator(
    task_id="evidence_finalization",
    python_callable=evidence_finalization,
    dag=dag,
)

preflight_task >> schema_task >> rule_task >> validation_task >> monitoring_task >> evidence_task
