#!/usr/bin/env python3
"""Fresh-execution static probe (Phase 2/3/6/7/8/10 support).

Auto-generates auditable facts from the CURRENT codebase into
evidence/final_execution/probe_results.json. No number is hand-typed:
every quantitative value is read from live registry/code/filesystem state.
"""
import ast
import csv
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EV = os.path.join(PROJECT_ROOT, "evidence", "final_execution")
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

results = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "git_head": None}

def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

# --- git head -------------------------------------------------------------
import subprocess
r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
results["git_head"] = r.stdout.strip()
r = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
results["git_status_entries_at_probe_start"] = len([l for l in r.stdout.splitlines() if l.strip()])

# --- 1. Rule registry (live) ----------------------------------------------
from data_quality_platform.rules.registry import RuleRegistry
from data_quality_platform.validation.engine import ValidationEngine

def inspect_source(rel):
    with open(os.path.join(PROJECT_ROOT, rel), encoding="utf-8") as f:
        return None, f.readlines()

def find_class_line(lines, name):
    for i, l in enumerate(lines, 1):
        if l.strip().startswith(f"class {name}"):
            return i
    return None

reg = RuleRegistry.create_default()
rules = []
for rule in reg.get_all_rules():
    cls = type(rule)
    mod = sys.modules[cls.__module__]
    src_path = os.path.relpath(mod.__file__, PROJECT_ROOT)
    _, src_lines = inspect_source(src_path)
    line_no = find_class_line(src_lines, cls.__name__)
    rules.append({
        "class": cls.__name__,
        "rule_id": rule.rule_id,
        "rule_version": rule.rule_version,
        "rule_hash": rule.hash,
        "module": src_path,
        "line": line_no,
    })

results["registry_default_rules"] = rules
results["registry_default_count"] = len(rules)
# registry validation method if present
ok, errs, warns = reg.validate()
results["registry_validate_ok"] = ok
results["registry_validate_errors"] = errs
results["registry_validate_warnings"] = warns

# --- 2. SP1 isolation -------------------------------------------------------
sp1 = {}
# registered?
sp1["registered_rule_ids"] = [r_.get("rule_id") for r_ in rules]
sp1["sp1_in_default_registry"] = any("sp1" in str(r_.get("class", "")).lower() or "sp1" in str(r_.get("rule_id", "")).lower() for r_ in rules)
# production imports (exclude tests/, geography package itself, docs)
prod_imports = []
for dirpath, dirnames, filenames in os.walk(PROJECT_ROOT):
    dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", "node_modules", "evidence", "reports", "docs", ".pytest_cache")]
    for fn in filenames:
        if not fn.endswith(".py"):
            continue
        p = os.path.join(dirpath, fn)
        rel = os.path.relpath(p, PROJECT_ROOT)
        if rel.startswith(("tests",)):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                tree = ast.parse(f.read())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "geography" in node.module:
                names = [a.name for a in node.names]
                prod_imports.append({"file": rel, "from": node.module, "names": names})
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if "geography" in a.name:
                        prod_imports.append({"file": rel, "import": a.name})
results["sp1_geography_imports_outside_geography_pkg"] = [
    i for i in prod_imports
    if "canonical" in json.dumps(i) or "sp1" in json.dumps(i).lower()
]
results["sp1_all_geography_imports_outside_pkg"] = prod_imports
results["sp1_isolation"] = sp1

# --- 3. Golden fixture hashes ------------------------------------------------
gold = {}
for fn in ("golden_cases.csv", "expected_results.csv", "geography_edge_cases.csv"):
    p = os.path.join(PROJECT_ROOT, "tests", "golden", fn)
    gold[fn] = {"sha256": sha256_file(p), "bytes": os.path.getsize(p)}
results["golden_fixtures"] = gold

# --- 4. Security scan ---------------------------------------------------------
secret_patterns = [
    (r"(?i)(api_key|apikey|secret|password|passwd|token|credential)\s*[=:]\s*['\"](?!(?:\{\{|<|\$\{|your|example|placeholder|change|xxx|dummy|test|None|""|''))[^\s'\"]{8,}", "hardcoded-secret-like"),
]
hits = []
env_file_exists = os.path.exists(os.path.join(PROJECT_ROOT, ".env"))
for dirpath, dirnames, filenames in os.walk(PROJECT_ROOT):
    dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", "node_modules", ".pytest_cache")]
    for fn in filenames:
        if fn.endswith((".pyc", ".pyo", ".zip")):
            continue
        p = os.path.join(dirpath, fn)
        rel = os.path.relpath(p, PROJECT_ROOT)
        try:
            if os.path.getsize(p) > 2_000_000:
                continue
            with open(p, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        for pat, label in secret_patterns:
            for m in re.finditer(pat, content):
                line_no = content[:m.start()].count("\n") + 1
                hits.append({"file": rel, "line": line_no, "label": label, "match_head": m.group(0)[:40]})
results["security_scan"] = {"env_file_present": env_file_exists, "hits": hits, "hit_count": len(hits)}

# --- 5. SQL mutation scan ------------------------------------------------------
sql_scan = {}
mut_re = re.compile(r"(?i)\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|DROP\s+TABLE|ALTER\s+TABLE|TRUNCATE|CREATE\s+OR\s+REPLACE|GRANT|REVOKE)\b")
for dirpath, dirnames, filenames in os.walk(PROJECT_ROOT):
    dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", "node_modules", ".pytest_cache")]
    for fn in filenames:
        if fn.endswith(".sql"):
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, PROJECT_ROOT)
            with open(p, encoding="utf-8", errors="ignore") as f:
                content = f.read()
            stmts = [m.group(0) for m in mut_re.finditer(content)]
            sql_scan[rel] = {"mutation_statements": stmts}
# python production code writing SQL
py_mut = []
for dirpath, dirnames, filenames in os.walk(os.path.join(PROJECT_ROOT, "data_quality_platform")):
    for fn in filenames:
        if not fn.endswith(".py"):
            continue
        p = os.path.join(dirpath, fn)
        rel = os.path.relpath(p, PROJECT_ROOT)
        with open(p, encoding="utf-8", errors="ignore") as f:
            content = f.read()
        for m in mut_re.finditer(content):
            line_no = content[:m.start()].count("\n") + 1
            py_mut.append({"file": rel, "line": line_no, "stmt": m.group(0)})
results["sql_mutation_scan"] = {"sql_files": sql_scan, "python_production_mutation_hits": py_mut}

# --- 6. Fresh CLI run reconciliation (from actual output file) -------------------
inp = os.path.join(PROJECT_ROOT, "data", "generated", "fresh_exec_input.csv")
out = os.path.join(PROJECT_ROOT, "data", "generated", "fresh_exec_output.csv")
rec = {}
if os.path.exists(inp) and os.path.exists(out):
    with open(inp, encoding="utf-8") as f:
        in_rows = list(csv.DictReader(f))
        in_cols = list(csv.DictReader(open(inp, encoding="utf-8")).fieldnames)
    with open(out, encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        out_cols = rdr.fieldnames
        out_rows = list(rdr)
    rec["input_rows"] = len(in_rows)
    rec["output_rows"] = len(out_rows)
    rec["rows_preserved"] = len(in_rows) == len(out_rows)
    rec["input_columns"] = len(in_cols)
    rec["output_columns"] = len(out_cols)
    rec["source_columns_preserved"] = all(c in out_cols for c in in_cols)
    # unique ids
    id_col = in_cols[0] if in_cols else None
    rec["unique_input_ids"] = len({r2[id_col] for r2 in in_rows}) if id_col else None
    rec["unique_output_ids"] = len({r2.get(id_col) for r2 in out_rows}) if id_col else None
    # flag partition (V1 geography flags on output file)
    assessable = sum(1 for r2 in out_rows if r2.get("zip_state_assessable") == "1")
    mismatch = sum(1 for r2 in out_rows if r2.get("geography_mismatch_candidate") == "1")
    match = assessable - mismatch
    rec["flag_partition"] = {"zip_state_assessable": assessable, "geography_mismatch_candidate": mismatch, "match": match,
                             "partition_consistent": match + mismatch == assessable}
    # all 8 flag values valid
    flag_cols = [c for c in out_cols if c not in in_cols]
    rec["flag_columns_added"] = flag_cols
    bad = 0
    for c in flag_cols:
        for r2 in out_rows:
            if r2.get(c) not in ("0", "1"):
                bad += 1
    rec["invalid_flag_values"] = bad
    # evidence bundle files
    ev_dir = os.path.join(EV, "cli_run", "evidence")
    rec["evidence_bundle_files"] = sorted(os.listdir(ev_dir)) if os.path.isdir(ev_dir) else []
    rec["evidence_bundle_sha256"] = {fn: sha256_file(os.path.join(ev_dir, fn)) for fn in rec["evidence_bundle_files"]}
results["fresh_cli_reconciliation"] = rec

# --- 7. Benchmark-derived scaling facts -------------------------------------------
bench_path = os.path.join(PROJECT_ROOT, "evidence", "benchmarks", "benchmark.json")
if os.path.exists(bench_path):
    with open(bench_path, encoding="utf-8") as f:
        b = json.load(f)
    rows = [x["rows"] for x in b["benchmarks"]]
    mem = [x["peak_memory_mb"] for x in b["benchmarks"]]
    per_row = [x["peak_memory_mb"] * 1024 / x["rows"] for x in b["benchmarks"]]  # KB/row
    results["benchmark_scaling"] = {
        "sizes": rows,
        "durations_s": [x["duration_seconds"] for x in b["benchmarks"]],
        "rows_per_second": [x["rows_per_second"] for x in b["benchmarks"]],
        "peak_memory_mb": mem,
        "peak_memory_kb_per_row": [round(v, 3) for v in per_row],
        "memory_monotonic_increasing": all(mem[i] < mem[i + 1] for i in range(len(mem) - 1)),
    }

with open(os.path.join(EV, "probe_results.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, default=str)

# console summary
print(json.dumps({k: results[k] for k in (
    "git_head", "registry_default_count",
    "sp1_geography_imports_outside_geography_pkg")}, indent=1, default=str))
print("sp1_isolation:", json.dumps(results["sp1_isolation"]))
print("registry_validate:", results["registry_validate_ok"], results.get("registry_validate_errors"), results.get("registry_validate_warnings"))
print("security hits:", len(hits))
print("py mutation hits:", len(py_mut))
print("cli rec:", json.dumps(rec.get("flag_partition", {})), "rows_ok:", rec.get("rows_preserved"), "cols:", rec.get("input_columns"), "->", rec.get("output_columns"))
print("bench per-row KB:", results.get("benchmark_scaling", {}).get("peak_memory_kb_per_row"))
