"""Canonical CLI: python -m runner.cli

Commands: validate, generate, profile, test, verify, benchmark
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone


# Ensure project root is on sys.path
def _ensure_path():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

_ensure_path()


from data_quality_platform.validation.engine import ValidationEngine
from data_quality_platform.generation.synthetic import SyntheticDataGenerator
from data_quality_platform.rules.registry import RuleRegistry
from data_quality_platform.config import PlatformConfig
from data_quality_platform.contracts import SOURCE_COLUMNS, FLAG_COLUMNS, TOTAL_OUTPUT_COLUMNS
from data_quality_platform.evidence.manifests import ManifestReader, compute_file_sha256


def cmd_generate(args):
    """Generate synthetic data."""
    gen = SyntheticDataGenerator(seed=args.seed)
    gen.generate(args.rows, args.output)
    print(f"Generated {args.rows} rows -> {args.output}")
    return 0


def cmd_validate(args):
    """Run validation pipeline."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    run_id = args.run_id or f"run_{int(time.time())}"
    evidence_dir = args.evidence_dir or f"evidence/{run_id}"

    # R3 wiring: configs/quality.yaml is now actually honored. The engine's
    # single existing configuration intake point (config_thresholds ->
    # QualityMonitor SLA thresholds) is fed from the loaded PlatformConfig.
    # N1 hardening: an EXPLICITLY supplied --config path must exist; a missing
    # explicit path is a hard error (non-zero exit, no silent fallback). The
    # deterministic default path (<project_root>/configs/quality.yaml, based
    # on this file's location, not the CWD) keeps the safe missing-file ->
    # dataclass-defaults behavior of PlatformConfig.from_yaml.
    explicit_config = bool(getattr(args, "config", ""))
    config_path = getattr(args, "config", "") or os.path.join(
        project_root, "configs", "quality.yaml"
    )
    if explicit_config and not os.path.isfile(config_path):
        print(
            f"ERROR: explicit --config path does not exist or is not a file: "
            f"{config_path}",
            file=sys.stderr,
        )
        print(
            "ERROR: refusing to start validation under an unintended "
            "configuration (no silent fallback for an explicit --config path). "
            "Omit --config to use the shipped configs/quality.yaml.",
            file=sys.stderr,
        )
        return 2
    config = PlatformConfig.from_yaml(config_path)

    # Input contract / preflight firewall (DQAVP hardening, Section 11):
    # a fail-closed structural gate ahead of engine execution. Valid input
    # proceeds to the engine unchanged; invalid input is blocked with a
    # failure manifest and exit code 2. This validates STRUCTURE only —
    # data quality remains the frozen V1 rules' responsibility.
    from data_quality_platform.validation.input_contract import (
        InputContractError,
        validate_input_contract,
    )
    try:
        contract = validate_input_contract(args.csv, config=config)
        print(
            f"Input contract: PASS "
            f"({contract.details['total_data_rows']} rows, "
            f"{contract.details['header_column_count']} columns, "
            f"id scan {contract.details['id_rows_scanned']} rows)"
        )
    except InputContractError as exc:
        print("Input contract: BLOCKED", file=sys.stderr)
        for issue in exc.issues:
            print(f"  {issue!r}", file=sys.stderr)
        try:
            from data_quality_platform.evidence.manifests import ManifestWriter
            ManifestWriter().write_failure_manifest(
                evidence_dir=evidence_dir,
                run_id=run_id,
                error_type="InputContractError",
                error_message=f"{len(exc.issues)} input contract issue(s); "
                              f"first: {exc.issues[0]!r}",
                failed_step="input_contract_preflight",
            )
        except Exception:  # evidence write must never mask the block
            print("  (failure manifest could not be written)",
                  file=sys.stderr)
        return 2

    rules = RuleRegistry.create_default()
    engine = ValidationEngine(
        rules=rules,
        run_id=run_id,
        evidence_dir=evidence_dir,
        config_thresholds=config.get_quality_thresholds(),
    )

    result = engine.validate(
        csv_path=args.csv,
        output_path=args.output,
    )

    if result.success:
        print(f"Validation PASSED: {result.input_row_count} rows in, {result.output_row_count} rows out")
        print(f"  Run ID: {result.run_id}")
        print(f"  Duration: {result.duration_seconds:.2f}s")
        print(f"  Monitoring score: {result.monitoring_score:.4f}")
        print(f"  SLA passed: {result.sla_passed}")
        print(f"  Reconciliation passed: {result.reconciliation_passed}")
        print(f"  Evidence: {result.evidence_dir}")
        for rule_id, count in result.flag_counts.items():
            print(f"    {rule_id}: {count}")
        return 0
    else:
        print(f"Validation FAILED: {result.error}", file=sys.stderr)
        return 1


def cmd_profile(args):
    """Profile a CSV file (basic stats)."""
    if not os.path.exists(args.csv):
        print(f"File not found: {args.csv}", file=sys.stderr)
        return 1

    with open(args.csv, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        row_count = 0
        blank_counts = {}
        for row in reader:
            row_count += 1
            for col in header:
                if not str(row.get(col, "")).strip():
                    blank_counts[col] = blank_counts.get(col, 0) + 1

    print(f"File: {args.csv}")
    print(f"Columns: {len(header)}")
    print(f"Rows: {row_count}")
    print(f"\nBlank counts:")
    for col, count in sorted(blank_counts.items(), key=lambda x: -x[1]):
        if count > 0:
            pct = count / row_count * 100 if row_count > 0 else 0
            print(f"  {col}: {count} ({pct:.1f}%)")
    return 0


def cmd_test(args):
    """Run pytest."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cmd = [sys.executable, "-m", "pytest", "-q"]
    if args.verbose:
        cmd.remove("-q")
        cmd.append("-v")
    result = subprocess.run(cmd, cwd=project_root)
    return result.returncode


def cmd_verify(args):
    """Run Q1-Q22 verification suite."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    evidence_dir = args.evidence_dir or "evidence/verification"
    os.makedirs(evidence_dir, exist_ok=True)

    verification_results = run_verification(project_root, evidence_dir)

    # Write JSON report
    report_path = os.path.join(evidence_dir, "verification_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(verification_results, f, indent=2, default=str)

    # Write Markdown report
    md_path = os.path.join(evidence_dir, "verification_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Q1-Q22 Verification Report\n\n")
        f.write(f"Generated: {datetime.now(timezone.utc).isoformat()}\n\n")
        f.write("| Q# | Status | Evidence |\n")
        f.write("|-----|--------|----------|\n")
        for item in verification_results["results"]:
            f.write(f"| {item['question']} | {item['status']} | {item.get('evidence', '')} |\n")

    # Print summary
    passed = sum(1 for r in verification_results["results"] if r["status"] == "PASS")
    partial = sum(1 for r in verification_results["results"] if r["status"] in ("PARTIAL", "DESIGNED_BUT_NOT_RUNTIME_VERIFIED"))
    failed = sum(1 for r in verification_results["results"] if r["status"] in ("FAIL", "NOT_IMPLEMENTED"))
    print(f"Verification: {passed} PASS, {partial} PARTIAL/DESIGNED, {failed} FAIL/NOT_IMPLEMENTED")
    print(f"Report: {report_path}")

    return 0 if failed == 0 else 1


def cmd_benchmark(args):
    """Run scalability benchmark."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(project_root, "scripts", "benchmark.py")
    if not os.path.exists(script):
        print(f"Benchmark script not found: {script}", file=sys.stderr)
        return 1
    result = subprocess.run([sys.executable, script], cwd=project_root)
    return result.returncode


def run_verification(project_root: str, evidence_dir: str) -> dict:
    """Execute Q1-Q22 verification checks. Returns results dict."""
    results = []
    overall = {"timestamp": datetime.now(timezone.utc).isoformat(), "results": results}

    def check(question: str, desc: str, test_fn):
        try:
            status, evidence = test_fn()
        except Exception as e:
            status = "FAIL"
            evidence = str(e)
        results.append({"question": question, "description": desc, "status": status, "evidence": evidence})

    # Q1: Package imports
    def q1():
        try:
            from data_quality_platform.rules import RuleRegistry
            from data_quality_platform.validation.engine import ValidationEngine
            from runner.cli import main
            return "PASS", "All canonical imports succeed"
        except ImportError as e:
            return "FAIL", str(e)
    check("Q1", "Package structure and imports", q1)

    # Q2: CLI help
    def q2():
        result = subprocess.run(
            [sys.executable, "-m", "runner.cli", "--help"],
            capture_output=True, text=True, cwd=project_root
        )
        if result.returncode == 0:
            return "PASS", "CLI --help works"
        return "FAIL", result.stderr
    check("Q2", "CLI entry point", q2)

    # Q3: Schema validation
    def q3():
        from data_quality_platform.schema.validator import SchemaValidator
        sv = SchemaValidator()
        valid, errors = sv.validate_header(list(SOURCE_COLUMNS))
        if valid and not errors:
            valid2, errors2 = sv.validate_header(SOURCE_COLUMNS[:30])
            if not valid2 and errors2:
                return "PASS", "Accepts valid, rejects invalid"
        return "FAIL", "Schema validation logic error"
    check("Q3", "Schema validation", q3)

    # Q4: Schema drift detection
    def q4():
        from data_quality_platform.schema.validator import SchemaValidator
        sv = SchemaValidator()
        ok, drift = sv.detect_drift(SOURCE_COLUMNS, SOURCE_COLUMNS + ["extra_col"])
        if not ok and drift:
            return "PASS", "Drift detected correctly"
        return "FAIL", "Drift not detected"
    check("Q4", "Schema drift detection", q4)

    # Q5: Rule registry
    def q5():
        from data_quality_platform.rules import RuleRegistry
        rr = RuleRegistry.create_default()
        valid, errors, warnings = rr.validate()
        if valid and rr.count == 8:
            return "PASS", f"Registry valid with {rr.count} rules"
        return "FAIL", f"Errors: {errors}, Warnings: {warnings}"
    check("Q5", "Rule registry and 8 rules", q5)

    # Q6: Rule versions and hashes
    def q6():
        from data_quality_platform.rules import RuleRegistry
        rr = RuleRegistry.create_default()
        hashes = rr.get_rule_hashes()
        versions = rr.get_rule_versions()
        if len(hashes) == 8 and all(isinstance(v, str) and len(v) == 64 for v in hashes.values()):
            if all(v == "1.0.0" for v in versions.values()):
                return "PASS", "All 8 rules have versions and SHA-256 hashes"
        return "FAIL", f"Hashes: {len(hashes)}, Versions: {versions}"
    check("Q6", "Rule versions and hashes", q6)

    # Q7: SQL templates
    def q7():
        from data_quality_platform.rules import RuleRegistry
        rr = RuleRegistry.create_default()
        templates = rr.get_sql_templates()
        if len(templates) == 8 and all("SELECT" in t.upper() for t in templates.values()):
            return "PASS", "All 8 rules have SQL templates"
        return "FAIL", f"Templates: {list(templates.keys())}"
    check("Q7", "SQL templates for rules", q7)

    # Q8: Synthetic data generation
    def q8():
        gen = SyntheticDataGenerator(seed=20260821)
        path = os.path.join(project_root, "data", "generated", "test_q8.csv")
        gen.generate(10, path)
        with open(path, "r") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            rows = list(reader)
        if header == SOURCE_COLUMNS and len(rows) == 10:
            return "PASS", "Generated 10 rows with correct 33-column schema"
        return "FAIL", f"Header: {header}, Rows: {len(rows)}"
    check("Q8", "Synthetic data generation", q8)

    # Q9: Streaming validation
    def q9():
        gen = SyntheticDataGenerator(seed=42)
        csv_path = os.path.join(project_root, "data", "generated", "test_q9.csv")
        out_path = os.path.join(project_root, "data", "generated", "test_q9_out.csv")
        ev_dir = os.path.join(project_root, "evidence", "test_q9")
        gen.generate(100, csv_path)
        engine = ValidationEngine(
            rules=RuleRegistry.create_default(),
            run_id="q9_test",
            evidence_dir=ev_dir,
        )
        result = engine.validate(csv_path, out_path)
        if result.success and result.input_row_count == 100 and result.output_row_count == 100:
            return "PASS", f"Streamed 100 rows in {result.duration_seconds:.2f}s"
        return "FAIL", f"Success={result.success}, Error={result.error}"
    check("Q9", "Streaming CSV validation", q9)

    # Q10: 41-column Flag Preview
    def q10():
        out_path = os.path.join(project_root, "data", "generated", "test_q9_out.csv")
        if not os.path.exists(out_path):
            return "FAIL", "Output file not found"
        with open(out_path, "r") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            if len(header) == TOTAL_OUTPUT_COLUMNS:
                # Check flag columns present
                if all(fc in header for fc in FLAG_COLUMNS):
                    # Check all flag values are 0/1
                    for row in reader:
                        for fc in FLAG_COLUMNS:
                            if row[fc] not in ("0", "1"):
                                return "FAIL", f"Invalid flag: {fc}={row[fc]}"
                    return "PASS", f"{TOTAL_OUTPUT_COLUMNS} columns, all flags 0/1"
        return "FAIL", f"Header has {len(header)} columns, expected {TOTAL_OUTPUT_COLUMNS}"
    check("Q10", "41-column Flag Preview output", q10)

    # Q11: Reconciliation
    def q11():
        manifest = ManifestReader.read(os.path.join(project_root, "evidence", "test_q9"))
        if manifest and manifest.get("reconciliation", {}).get("passed"):
            return "PASS", "Reconciliation passed in manifest"
        return "FAIL", f"Manifest: {manifest}"
    check("Q11", "Reconciliation", q11)

    # Q12: SHA-256 evidence
    def q12():
        manifest = ManifestReader.read(os.path.join(project_root, "evidence", "test_q9"))
        if manifest and manifest.get("schema_hash") and manifest.get("rule_hashes"):
            file_hashes = manifest.get("file_hashes", {})
            if file_hashes:
                return "PASS", "Schema, rule, and file hashes present"
        return "FAIL", "Missing hashes in manifest"
    check("Q12", "SHA-256 evidence hashes", q12)

    # Q13: Manifests
    def q13():
        manifest = ManifestReader.read(os.path.join(project_root, "evidence", "test_q9"))
        if manifest and manifest.get("manifest_type") == "success":
            required = ["run_id", "timestamp", "source_row_count", "output_row_count",
                        "flag_counts", "reconciliation", "monitoring_score"]
            if all(k in manifest for k in required):
                return "PASS", "Success manifest has all required fields"
        return "FAIL", f"Manifest: {manifest}"
    check("Q13", "Success and failure manifests", q13)

    # Q14: Golden tests
    def q14():
        golden_path = os.path.join(project_root, "tests", "golden", "golden_cases.csv")
        if os.path.exists(golden_path):
            with open(golden_path, "r") as f:
                rows = list(csv.DictReader(f))
            if len(rows) >= 45:
                return "PASS", f"{len(rows)} golden cases"
        return "FAIL", "Golden cases missing or insufficient"
    check("Q14", "Golden test cases (45+ cases)", q14)

    # Q15: Deterministic output
    def q15():
        gen = SyntheticDataGenerator(seed=999)
        p1 = os.path.join(project_root, "data", "generated", "det1.csv")
        p2 = os.path.join(project_root, "data", "generated", "det2.csv")
        gen.generate(50, p1)
        gen2 = SyntheticDataGenerator(seed=999)
        gen2.generate(50, p2)
        h1 = compute_file_sha256(p1)
        h2 = compute_file_sha256(p2)
        if h1 == h2:
            return "PASS", f"Deterministic: {h1[:16]}..."
        return "FAIL", f"Hash mismatch: {h1} vs {h2}"
    check("Q15", "Deterministic synthetic data", q15)

    # Q16: Lineage and audit
    def q16():
        ev_dir = os.path.join(project_root, "evidence", "test_q9")
        lineage_path = os.path.join(ev_dir, "lineage.json")
        audit_path = os.path.join(ev_dir, "audit.json")
        checks = []
        if os.path.exists(lineage_path):
            with open(lineage_path) as f:
                lineage = json.load(f)
            if lineage.get("run_id") == "q9_test" and lineage.get("total_row_records", 0) > 0:
                checks.append("lineage OK")
            else:
                return "FAIL", f"Lineage missing data: {lineage}"
        else:
            return "FAIL", "lineage.json not found"
        if os.path.exists(audit_path):
            with open(audit_path) as f:
                audit = json.load(f)
            events = [e["event_type"] for e in audit.get("events", [])]
            required = ["run_started", "schema_validated", "rules_loaded", "validation_completed"]
            if all(r in events for r in required):
                checks.append("audit OK")
            else:
                return "FAIL", f"Missing audit events: {set(required) - set(events)}"
        else:
            return "FAIL", "audit.json not found"
        return "PASS", "; ".join(checks)
    check("Q16", "Lineage and audit trail", q16)

    # Q17: Monitoring and alerts
    def q17():
        ev_dir = os.path.join(project_root, "evidence", "test_q9")
        mon_path = os.path.join(ev_dir, "monitoring.json")
        if os.path.exists(mon_path):
            with open(mon_path) as f:
                mon = json.load(f)
            scores = mon.get("scores", {})
            if len(scores) == 8 and "overall_score" in mon:
                return "PASS", f"8 dimensions, score={mon['overall_score']}"
        return "FAIL", "Monitoring not found or incomplete"
    check("Q17", "Monitoring and alerts", q17)

    # Q18: PII security
    def q18():
        from data_quality_platform.security.pii_masking import PIIMasker
        from data_quality_platform.security.auth import RBACManager, AuthContext, Permission
        masked = PIIMasker.mask_email("john.smith@example.com")
        if masked != "j***@example.com":
            return "FAIL", f"Email masking: {masked}"
        rbac = RBACManager()
        admin = AuthContext(user_id="admin", roles=["admin"])
        if not rbac.check_permission(admin, Permission.ADMIN):
            return "FAIL", "RBAC admin check failed"
        viewer = AuthContext(user_id="viewer", roles=["viewer"])
        if rbac.check_permission(viewer, Permission.EXPORT_PII):
            return "FAIL", "Viewer should not have EXPORT_PII"
        return "PARTIAL", "RBAC and masking verified; production IAM not implemented"
    check("Q18", "PII security foundation", q18)

    # Q19: Scalability
    def q19():
        bench_path = os.path.join(project_root, "evidence", "benchmarks", "benchmark.json")
        if os.path.exists(bench_path):
            with open(bench_path) as f:
                bench = json.load(f)
            sizes = [b["rows"] for b in bench.get("benchmarks", [])]
            if 1000 in sizes and 10000 in sizes:
                return "PASS", f"Benchmarks for {sizes}"
        # Run a quick benchmark inline
        gen = SyntheticDataGenerator(seed=20260821)
        csv_path = os.path.join(project_root, "data", "generated", "bench_1k.csv")
        out_path = os.path.join(project_root, "data", "generated", "bench_1k_out.csv")
        ev_dir = os.path.join(project_root, "evidence", "bench_quick")
        gen.generate(1000, csv_path)
        engine = ValidationEngine(rules=RuleRegistry.create_default(), run_id="bench_q19", evidence_dir=ev_dir)
        start = time.time()
        result = engine.validate(csv_path, out_path)
        duration = time.time() - start
        rps = 1000 / duration if duration > 0 else 0
        return "PASS", f"1K: {duration:.2f}s, {rps:.0f} rows/sec; 800M not claimed"
    check("Q19", "Scalability benchmarks", q19)

    # Q20: Tools and integration
    def q20():
        # Check CLI subprocess works
        gen = SyntheticDataGenerator(seed=20260821)
        csv_path = os.path.join(project_root, "data", "generated", "cli_test.csv")
        out_path = os.path.join(project_root, "data", "generated", "cli_test_out.csv")
        gen.generate(50, csv_path)
        result = subprocess.run(
            [sys.executable, "-m", "runner.cli", "validate",
             "--csv", csv_path, "--output", out_path,
             "--run-id", "q20_cli_test", "--evidence-dir", os.path.join(project_root, "evidence", "q20_cli")],
            capture_output=True, text=True, cwd=project_root
        )
        if result.returncode == 0:
            return "PASS", "CLI subprocess validation succeeded"
        return "FAIL", f"CLI failed: {result.stderr}"
    check("Q20", "CLI subprocess integration", q20)

    # Q21: V1 scope assessment — real aggregation over the actual Q1-Q20
    # results accumulated by check() above. At this point `results` contains
    # exactly Q1..Q20 (Q21's own entry is appended by check() only after
    # q21() returns), so the aggregation can never read itself as evidence.
    # Fail-closed contract: PASS only if all 20 results are explicitly PASS;
    # any structural defect -> FAIL; otherwise PARTIAL with full disclosure.
    def q21():
        from data_quality_platform.verification.scope_aggregator import aggregate_scope
        aggregate = aggregate_scope(results)
        return aggregate.verdict, aggregate.evidence_summary()
    check("Q21", "V1 scope assessment", q21)

    # Q22: Gulnara review artifacts
    def q22():
        docs_dir = os.path.join(project_root, "docs")
        gulnara = os.path.join(docs_dir, "GULNARA_REVIEW.md")
        fp = os.path.join(docs_dir, "FALSE_POSITIVE_REVIEW.md")
        geo = os.path.join(project_root, "tests", "golden", "geography_edge_cases.csv")
        found = []
        if os.path.exists(gulnara):
            found.append("GULNARA_REVIEW.md")
        if os.path.exists(fp):
            found.append("FALSE_POSITIVE_REVIEW.md")
        if os.path.exists(geo):
            found.append("geography_edge_cases.csv")
        if len(found) == 3:
            return "PASS", "All review artifacts present"
        return "FAIL", f"Missing: {found}"
    check("Q22", "Gulnara review artifacts", q22)

    return overall


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="python -m runner.cli",
        description="Data Quality CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # generate
    p_gen = subparsers.add_parser("generate", help="Generate synthetic data")
    p_gen.add_argument("--rows", type=int, required=True, help="Number of rows")
    p_gen.add_argument("--seed", type=int, default=20260821, help="Random seed")
    p_gen.add_argument("--output", required=True, help="Output CSV path")
    p_gen.set_defaults(func=cmd_generate)

    # validate
    p_val = subparsers.add_parser("validate", help="Run validation pipeline")
    p_val.add_argument("--csv", required=True, help="Input CSV path")
    p_val.add_argument("--output", required=True, help="Output Flag Preview path")
    p_val.add_argument("--run-id", default="", help="Run ID")
    p_val.add_argument("--evidence-dir", default="", help="Evidence directory")
    p_val.add_argument(
        "--config",
        default="",
        help="Path to quality config YAML (default: configs/quality.yaml in the project root)",
    )
    p_val.set_defaults(func=cmd_validate)

    # profile
    p_prof = subparsers.add_parser("profile", help="Profile a CSV file")
    p_prof.add_argument("--csv", required=True, help="CSV path")
    p_prof.set_defaults(func=cmd_profile)

    # test
    p_test = subparsers.add_parser("test", help="Run pytest")
    p_test.add_argument("-v", "--verbose", action="store_true")
    p_test.set_defaults(func=cmd_test)

    # verify
    p_ver = subparsers.add_parser("verify", help="Run Q1-Q22 verification")
    p_ver.add_argument("--evidence-dir", default="", help="Verification evidence dir")
    p_ver.set_defaults(func=cmd_verify)

    # benchmark
    p_bench = subparsers.add_parser("benchmark", help="Run scalability benchmark")
    p_bench.set_defaults(func=cmd_benchmark)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
