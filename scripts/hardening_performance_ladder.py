#!/usr/bin/env python3
"""Performance ladder for the 2026-09-19 hardened release.

Measures, for N in {1K, 10K, 100K, 1M}:
  * ENGINE-ONLY baseline: canonical `runner.cli validate` subprocess
    (wall seconds, peak RSS via monitor, output size)
  * HARDENED pipeline: full layers A-H orchestration around the same
    engine command (wall seconds, peak RSS, output size)
  * hardening overhead = hardened wall - engine wall (absolute + %)

The 3.2M rung is filled from the certified regression evidence (engine
validate phase wall time) + a full hardened-pipeline execution on the
regression input — no numbers are invented.

Output: evidence/FINAL_HARDENED_RELEASE_2026-09-19/performance/
        performance_ladder.json
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from data_quality_platform.contracts import SOURCE_COLUMNS          # noqa: E402
from data_quality_platform.hardening.authorization import (          # noqa: E402
    AuthorizationScope,
    observe_scope,
)
from data_quality_platform.hardening.pipeline import (               # noqa: E402
    HardenedExecutionSpec,
    default_software_paths,
    run_hardened_execution,
)
from data_quality_platform.hardening.resource_guard import (         # noqa: E402
    ExecutionMonitor,
    ResourceLimits,
)

ENGINE_PY = sys.executable
V1_RULES = REPO_ROOT / "data_quality_platform" / "rules" / "v1_rules.py"
CONTRACTS = REPO_ROOT / "data_quality_platform" / "contracts.py"
REFERENCE_PATHS = {"state_zip_prefixes": str(CONTRACTS)}
CONFIG = {"release": "DQAEIP-FINAL-HARDENED-RELEASE-2026-09-19",
          "purpose": "performance_ladder"}
OUT_DIR = (REPO_ROOT / "evidence" / "FINAL_HARDENED_RELEASE_2026-09-19" /
           "performance")
LADDER_WORK = REPO_ROOT / "data" / "generated" / "perf_ladder_20260919"
SEED = 20260919

LADDER_SIZES = [1_000, 10_000, 100_000, 1_000_000]

LADDER_JSON = OUT_DIR / "performance_ladder.json"


def persist(rungs) -> None:
    payload = {
        "schema": "dqaeip.hardening.performance.ladder/1.0",
        "release": "DQAEIP-FINAL-HARDENED-RELEASE-2026-09-19",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                       time.gmtime()),
        "measurement_method": {
            "engine_only": "canonical `python -m runner.cli validate` "
                           "subprocess; wall time via perf_counter; peak "
                           "RSS via /proc/<pid>/status monitor thread "
                           "(Layer H monitor, no limits tripped)",
            "hardened": "full layers A-H pipeline "
                        "(data_quality_platform.hardening.pipeline."
                        "run_hardened_execution) around the identical "
                        "engine command",
            "ladder_seed": SEED,
            "engine_3m2_source": "certified regression pass1 CLI "
                                 "duration (frozen checker evidence)",
        },
        "rungs": rungs,
    }
    LADDER_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp = LADDER_JSON.with_suffix(".json.tmp-write")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, LADDER_JSON)


def generate_input(rows: int, path: Path) -> None:
    r = subprocess.run(
        [ENGINE_PY, "-m", "runner.cli", "generate", "--rows", str(rows),
         "--seed", str(SEED), "--output", str(path)],
        cwd=str(REPO_ROOT), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"generate failed for {rows} rows: {r.stderr}")


def sha256_file(path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def engine_only_run(input_path: Path, out_path: Path, evidence_dir: Path):
    argv = [ENGINE_PY, "-m", "runner.cli", "validate",
            "--csv", str(input_path), "--output", str(out_path),
            "--run-id", "perf-engine-only",
            "--evidence-dir", str(evidence_dir)]
    t0 = time.perf_counter()
    proc = subprocess.Popen(argv, cwd=str(REPO_ROOT),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)
    monitor = ExecutionMonitor(
        ResourceLimits(max_wall_seconds=3600.0,
                       max_peak_rss_bytes=8 * 1024 ** 3))
    monitor.start(proc)
    stdout, stderr = proc.communicate()
    wall = time.perf_counter() - t0
    guard = monitor.finish(proc.returncode)
    if proc.returncode != 0:
        raise RuntimeError(
            f"engine-only run failed rc={proc.returncode}: "
            f"{stderr[-500:]}")
    return {
        "wall_seconds": round(wall, 3),
        "peak_rss_bytes": guard.details.get("peak_rss_bytes"),
        "output_size_bytes": out_path.stat().st_size,
        "returncode": proc.returncode,
    }


def hardened_run(input_path: Path, work_dir: Path, final_dir: Path):
    granted = observe_scope(
        input_path=str(input_path),
        authorized_columns=SOURCE_COLUMNS,
        v1_rules_path=str(V1_RULES),
        reference_data_paths=REFERENCE_PATHS,
        config=CONFIG,
        execution_mode="benchmark",
        software_paths=default_software_paths(str(V1_RULES)),
    )
    spec = HardenedExecutionSpec(
        input_path=str(input_path),
        expected_input_sha256=sha256_file(input_path),
        authorized_columns=SOURCE_COLUMNS,
        v1_rules_path=str(V1_RULES),
        reference_data_paths=REFERENCE_PATHS,
        config=CONFIG,
        execution_mode="benchmark",
        engine_argv=[
            "-m", "runner.cli", "validate",
            "--csv", "{INPUT}",
            "--output", "{OUTPUT_DIR}/flagged_preview.csv",
            "--run-id", "perf-hardened",
            "--evidence-dir", str(work_dir / "engine_evidence"),
        ],
        engine_cwd=str(REPO_ROOT),
        engine_python=ENGINE_PY,
        output_member_names=["flagged_preview.csv"],
        work_dir=str(work_dir),
        final_dir=str(final_dir),
        granted_scope=granted,
        limits=ResourceLimits(
            max_input_bytes=2 * 1024 ** 3,
            max_rows=4_000_000,
            max_wall_seconds=3600.0,
            max_peak_rss_bytes=8 * 1024 ** 3,
            max_output_bytes=8 * 1024 ** 3,
        ),
        run_label=f"perf-ladder-{input_path.stem}",
    )
    t0 = time.perf_counter()
    report = run_hardened_execution(spec)
    wall = time.perf_counter() - t0
    runtime_layer = [l for l in report.layers
                     if l["layer_id"] == "H" and "wall_seconds" in
                     l.get("details", {})]
    peak_rss = (runtime_layer[0]["details"].get("peak_rss_bytes")
                if runtime_layer else None)
    out_csv = Path(final_dir) / "flagged_preview.csv"
    return {
        "verdict": report.verdict,
        "wall_seconds": round(wall, 3),
        "peak_rss_bytes": peak_rss,
        "output_size_bytes": (out_csv.stat().st_size
                              if out_csv.exists() else None),
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LADDER_WORK.mkdir(parents=True, exist_ok=True)
    # CLI: rung selection — "small" (1K..1M), "3m2", or "all" (default)
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    existing = []
    if LADDER_JSON.exists():
        try:
            existing = json.loads(
                LADDER_JSON.read_text(encoding="utf-8")).get("rungs", [])
        except json.JSONDecodeError:
            existing = []
    rungs = list(existing)
    done_labels = {r["label"] for r in rungs}

    if mode in ("small", "all"):
        for rows in LADDER_SIZES:
            label = {1_000: "1K", 10_000: "10K", 100_000: "100K",
                     1_000_000: "1M"}[rows]
            if label in done_labels:
                print(f"[ladder {label}] already measured, skipping",
                      flush=True)
                continue
            input_path = LADDER_WORK / f"input_{label}.csv"
            if not input_path.exists():
                generate_input(rows, input_path)
            with open(input_path, encoding="utf-8", newline="") as f:
                header = next(csv.reader(f))
            assert header == SOURCE_COLUMNS, header

            engine_out = LADDER_WORK / f"engine_out_{label}.csv"
            engine_ev = LADDER_WORK / f"engine_ev_{label}"
            if engine_out.exists():
                engine_out.unlink()
            engine = engine_only_run(input_path, engine_out, engine_ev)

            work_dir = LADDER_WORK / f"hard_work_{label}"
            final_dir = LADDER_WORK / f"hard_final_{label}"
            if final_dir.exists():
                import shutil
                shutil.rmtree(final_dir)
                (work_dir / "execution_ledger.json").unlink(missing_ok=True)
            hardened = hardened_run(input_path, work_dir, final_dir)

            overhead_abs = round(
                hardened["wall_seconds"] - engine["wall_seconds"], 3)
            overhead_pct = round(
                100.0 * overhead_abs / engine["wall_seconds"], 2) \
                if engine["wall_seconds"] > 0 else None
            rung = {
                "rows": rows,
                "label": label,
                "input_sha256": sha256_file(input_path),
                "engine_only": engine,
                "hardened_pipeline": hardened,
                "hardening_overhead_seconds": overhead_abs,
                "hardening_overhead_percent": overhead_pct,
                "rows_per_second_engine_only": round(
                    rows / engine["wall_seconds"], 1),
                "rows_per_second_hardened": round(
                    rows / hardened["wall_seconds"], 1),
            }
            rungs.append(rung)
            persist(rungs)
            print(f"[ladder {label}] engine {engine['wall_seconds']}s / "
                  f"hardened {hardened['wall_seconds']}s / "
                  f"overhead {overhead_abs}s ({overhead_pct}%)",
                  flush=True)

    # ── 3.2M rung: certified regression engine numbers + fresh hardened
    #    pipeline execution on the regression input ─────────────────────
    if mode in ("3m2", "all") and "3.2M" not in done_labels:
        reg_input = (REPO_ROOT / "data" / "generated" /
                     "fresh_3m2_regression" /
                     "consumer_3m_seed_20260918_pass1.csv")
        reg_cli = (REPO_ROOT / "evidence" / "validation" / "2026-09-19" /
                   "fresh_3m2" / "pass1_cli.json")
        engine_3m2 = None
        if reg_cli.exists():
            cli = json.loads(reg_cli.read_text())
            engine_3m2 = {
                "wall_seconds": cli["cli"]["duration_seconds"],
                "peak_rss_mb": cli.get("engine_peak_rss_mb"),
                "output_size_bytes": cli.get("output_size_bytes"),
                "source": "evidence/validation/2026-09-19/fresh_3m2/"
                          "pass1_cli.json (certified frozen checker)",
            }
        hardened_3m2 = None
        if reg_input.exists():
            work_dir = LADDER_WORK / "hard_work_3M2"
            final_dir = LADDER_WORK / "hard_final_3M2"
            if final_dir.exists():
                import shutil
                shutil.rmtree(final_dir)
                (work_dir / "execution_ledger.json").unlink(
                    missing_ok=True)
            hardened_3m2 = hardened_run(reg_input, work_dir, final_dir)
            print(f"[ladder 3.2M] hardened "
                  f"{hardened_3m2['wall_seconds']}s", flush=True)
        if engine_3m2 and hardened_3m2:
            ov = round(hardened_3m2["wall_seconds"]
                       - engine_3m2["wall_seconds"], 3)
            rung = {
                "rows": 3_200_000,
                "label": "3.2M",
                "input_sha256": sha256_file(reg_input),
                "engine_only": engine_3m2,
                "hardened_pipeline": hardened_3m2,
                "hardening_overhead_seconds": ov,
                "hardening_overhead_percent": round(
                    100.0 * ov / engine_3m2["wall_seconds"], 2),
                "rows_per_second_engine_only": round(
                    3_200_000 / engine_3m2["wall_seconds"], 1),
                "rows_per_second_hardened": round(
                    3_200_000 / hardened_3m2["wall_seconds"], 1),
            }
            rungs.append(rung)
            persist(rungs)

    persist(rungs)
    print(f"wrote {LADDER_JSON} with {len(rungs)} rungs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
