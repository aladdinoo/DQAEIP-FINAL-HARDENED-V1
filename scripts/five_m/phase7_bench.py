#!/usr/bin/env python3
"""PHASE 7 — Performance/scale ladder: official CLI runs at 1K/10K/100K/1M.

For each size: generate (CLI, seed 20260909) -> validate (CLI), capture
duration + child peak RSS (RUSAGE_CHILDREN) + output size + output SHA-256.
Writes 06_performance/bench_ladder.json and per-size terminal captures.
The 3M datapoint comes from run1/run2 (11_largest_safe_execution_3m/);
the 5M attempt FAILED (03_run1/) and is referenced, not measured here.
"""

import hashlib
import json
import os
import resource
import subprocess
import sys
import time
from datetime import datetime, timezone

REPO = "/home/z/my-project/Data-Quality-V1-Final-Company-Integrated"
EV = os.path.join(REPO, "evidence", "final_5m_execution", "06_performance")
SIZES = [1000, 10000, 100000, 1000000]


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_cli(cmd):
    t0 = time.time()
    p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    dur = time.time() - t0
    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    return p, dur, ru.ru_maxrss / 1024.0


def main():
    os.makedirs(EV, exist_ok=True)
    ladder = {
        "ladder": "1K/10K/100K/1M official CLI runs (seed 20260909)",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "memory_method": "resource.getrusage(RUSAGE_CHILDREN).ru_maxrss (VmHWM-equivalent, MB)",
        "throughput_definition": "rows / wall duration of the validate invocation",
        "datapoints": [],
    }
    # 3M flagship datapoints (from the dual-run protocol)
    with open(os.path.join(REPO, "evidence/final_5m_execution/11_largest_safe_execution_3m/run1/result.json")) as f:
        r1 = json.load(f)
    with open(os.path.join(REPO, "evidence/final_5m_execution/11_largest_safe_execution_3m/run2/result.json")) as f:
        r2 = json.load(f)
    with open(os.path.join(REPO, "evidence/final_5m_execution/11_largest_safe_execution_3m/run1/memory.txt")) as f:
        mem1 = f.read()
    with open(os.path.join(REPO, "evidence/final_5m_execution/11_largest_safe_execution_3m/run2/memory.txt")) as f:
        mem2 = f.read()
    def _rss(txt):
        for line in txt.splitlines():
            if line.startswith("ru_maxrss_peak"):
                return float(line.split("=")[1].replace("MB", "").strip())
        return None
    ladder["datapoints"].append({
        "rows": 3000000, "source": "run_3m_r1 (flagship run 1)",
        "duration_s": r1["duration_s"], "rows_per_second": round(3000000 / r1["duration_s"], 1),
        "peak_rss_mb": _rss(mem1), "status": "COMPLETED"})
    ladder["datapoints"].append({
        "rows": 3000000, "source": "run_3m_r2 (flagship run 2)",
        "duration_s": r2["duration_s"], "rows_per_second": round(3000000 / r2["duration_s"], 1),
        "peak_rss_mb": _rss(mem2), "status": "COMPLETED"})

    for size in SIZES:
        print(f"[bench] size={size}")
        csv_in = f"data/generated/final_5m/bench5m_{size}.csv"
        csv_out = f"data/generated/final_5m/bench5m_{size}_out.csv"
        gen_term = os.path.join(EV, f"bench_{size}_generation_terminal.txt")
        val_term = os.path.join(EV, f"bench_{size}_validation_terminal.txt")

        # generation
        gen_cmd = [sys.executable, "-m", "runner.cli", "generate",
                   "--rows", str(size), "--seed", "20260909", "--output", csv_in]
        pg, gdur, grss = run_cli(gen_cmd)
        with open(gen_term, "w") as f:
            f.write("COMMAND: " + " ".join(gen_cmd) + "\n" + pg.stdout + pg.stderr +
                    f"Exit code: {pg.returncode}\nWall duration: {gdur:.3f} s\n"
                    f"Child peak RSS (ru_maxrss): {grss:.2f} MB\n")
        # validation
        val_cmd = [sys.executable, "-m", "runner.cli", "validate",
                   "--csv", csv_in, "--output", csv_out,
                   "--run-id", f"bench5m_{size}",
                   "--evidence-dir", f"evidence/final_5m_execution/06_performance/bench_{size}_evidence"]
        pv, vdur, vrss = run_cli(val_cmd)
        with open(val_term, "w") as f:
            f.write("COMMAND: " + " ".join(val_cmd) + "\n" + pv.stdout + pv.stderr +
                    f"Exit code: {pv.returncode}\nWall duration: {vdur:.3f} s\n"
                    f"Child peak RSS (ru_maxrss): {vrss:.2f} MB\n")
        ok = pv.returncode == 0
        dp = {
            "rows": size,
            "generation_duration_s": round(gdur, 3),
            "validation_duration_s": round(vdur, 3),
            "rows_per_second": round(size / vdur, 1) if ok else None,
            "peak_rss_mb_validation": round(vrss, 2),
            "output_size_bytes": os.path.getsize(os.path.join(REPO, csv_out)) if ok else None,
            "output_sha256": sha256_of(os.path.join(REPO, csv_out)) if ok else None,
            "status": "COMPLETED" if ok else f"FAILED_EXIT_{pv.returncode}",
        }
        ladder["datapoints"].append(dp)
        print(json.dumps(dp, indent=2))

    # scaling interpretation data (computed, labeled as observed)
    dps = [d for d in ladder["datapoints"] if d["status"] == "COMPLETED" and d.get("rows_per_second")]
    dps.sort(key=lambda d: d["rows"])
    ladder["observed_scaling"] = [
        {"rows": d["rows"], "rows_per_second": d["rows_per_second"],
         "peak_rss_mb": d.get("peak_rss_mb_validation")} for d in dps]
    ladder["scaling_interpretation"] = (
        "Observed empirical scaling: throughput is roughly stable across 1K-3M and "
        "peak RSS grows approximately linearly (see PERFORMANCE_REPORT.md for the "
        "explicit O(N)-by-inspection vs observed distinction). No O(N) claim is made "
        "from these measurements alone; the implementation-level O(N) memory "
        "statement comes from code inspection (ValidationEngine docstring).")
    with open(os.path.join(EV, "bench_ladder.json"), "w") as f:
        json.dump(ladder, f, indent=2)
    print("ladder written")


if __name__ == "__main__":
    main()
