#!/usr/bin/env python3
"""PHASE 4/6 — Real CLI pipeline execution harness for the 5M runs.

Runs the canonical CLI (python -m runner.cli validate ...) as a subprocess,
captures complete stdout/stderr, exit code, wall duration, and memory by TWO
explicitly labeled methods:
  1. resource.getrusage(RUSAGE_CHILDREN).ru_maxrss  (post-exit, authoritative)
  2. /proc/<pid>/status VmHWM polling every 0.5 s   (in-flight trace)

Writes into the target run directory:
  command.txt, terminal_output.txt, result.json, runtime.txt, memory.txt, hashes.txt

Honest failure handling: OOM kills (negative returncode / SIGKILL) are recorded
verbatim and reflected in result.json["status"].
"""

import hashlib
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

REPO = "/home/z/my-project/Data-Quality-V1-Final-Company-Integrated"


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def free_mb():
    try:
        with open("/proc/meminfo") as f:
            d = {}
            for line in f:
                k, v = line.split(":", 1)
                d[k] = int(v.strip().split()[0]) / 1024.0
        return {"MemTotal_mb": round(d["MemTotal"], 1),
                "MemAvailable_mb": round(d["MemAvailable"], 1)}
    except Exception as e:
        return {"error": str(e)}


def poll_vmhwm(pid, out):
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    out["vmhwm_kib"] = int(line.split()[1])
    except Exception:
        pass


def main():
    csv_in = sys.argv[1]
    csv_out = sys.argv[2]
    run_id = sys.argv[3]
    ev_dir = sys.argv[4]
    os.makedirs(ev_dir, exist_ok=True)

    cmd = [sys.executable, "-m", "runner.cli", "validate",
           "--csv", csv_in, "--output", csv_out,
           "--run-id", run_id, "--evidence-dir", ev_dir]

    # --- command.txt (exact command) ---
    with open(os.path.join(ev_dir, "command.txt"), "w") as f:
        f.write(f"$ cd {REPO}\n")
        f.write(f"$ {' '.join(shlex.quote(c) for c in cmd)}\n")

    # --- runtime pre-state ---
    pre_free = free_mb()
    start_utc = datetime.now(timezone.utc).isoformat()
    t0 = time.time()

    proc = subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    # VmHWM poller
    trace = {"vmhwm_kib": 0}
    stop = threading.Event()
    def _poll():
        while not stop.is_set():
            poll_vmhwm(proc.pid, trace)
            stop.wait(0.5)
    th = threading.Thread(target=_poll, daemon=True)
    th.start()

    stdout, stderr = proc.communicate()
    rc = proc.returncode
    stop.set()
    th.join(timeout=2)
    dur = time.time() - t0
    end_utc = datetime.now(timezone.utc).isoformat()
    post_free = free_mb()

    import resource
    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    peak_children_mb = ru.ru_maxrss / 1024.0
    vmhwm_mb = trace["vmhwm_kib"] / 1024.0

    # --- terminal_output.txt ---
    with open(os.path.join(ev_dir, "terminal_output.txt"), "w") as f:
        f.write("$ cd %s\n$ %s\n\n" % (REPO, " ".join(shlex.quote(c) for c in cmd)))
        f.write("--- captured stdout ---\n")
        f.write(stdout)
        if stderr:
            f.write("--- captured stderr ---\n")
            f.write(stderr)
        f.write("--- end of captured output ---\n")
        f.write("Exit code: %d\n" % rc)
        if rc < 0:
            f.write("TERMINATED BY SIGNAL %d%s\n" % (-rc, " (SIGKILL — probable OOM)" if -rc == 9 else ""))
        if rc == 0:
            f.write("Status: COMPLETED\n")

    # --- result.json (structured) ---
    result = {
        "run_id": run_id,
        "command": " ".join(shlex.quote(c) for c in cmd),
        "cwd": REPO,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "duration_s": round(dur, 3),
        "exit_code": rc,
        "status": ("COMPLETED" if rc == 0
                   else f"FAILED_TERMINATED_BY_SIGNAL_{-rc}" if rc < 0
                   else f"FAILED_EXIT_{rc}"),
        "input_csv": csv_in,
        "output_csv": csv_out,
        "evidence_dir": ev_dir,
        "stdout_lines": stdout.count("\n") + (1 if stdout and not stdout.endswith("\n") else 0),
    }
    # parse flag counts from stdout if present
    flags = {}
    for line in stdout.splitlines():
        parts = line.strip().split(":")
        if len(parts) == 2 and parts[0].strip() in (
            "first_name_cleaning_candidate", "last_name_cleaning_candidate",
            "name_cleaning_candidate", "email_blank", "email_syntax_failure",
            "proposed_email_export_eligible", "zip_state_assessable",
            "geography_mismatch_candidate"):
            try:
                flags[parts[0].strip()] = int(parts[1].strip())
            except ValueError:
                pass
    if flags:
        result["flag_counts_from_stdout"] = flags
        result["flag_sum_from_stdout"] = sum(flags.values())
    for key in ("Validation PASSED", "Validation FAILED"):
        if key in stdout:
            result["cli_verdict_line"] = key
    if "rows in," in stdout:
        try:
            seg = stdout.split("Validation PASSED:", 1)[1]
            result["input_row_count"] = int(seg.split("rows in,")[0].strip())
            result["output_row_count"] = int(seg.split("rows out")[0].split("rows in,")[1].strip())
        except Exception:
            pass
    with open(os.path.join(ev_dir, "result.json"), "w") as f:
        json.dump(result, f, indent=2)

    # --- runtime.txt ---
    with open(os.path.join(ev_dir, "runtime.txt"), "w") as f:
        f.write(f"run_id: {run_id}\n")
        f.write(f"command: {' '.join(shlex.quote(c) for c in cmd)}\n")
        f.write(f"start_utc: {start_utc}\n")
        f.write(f"end_utc: {end_utc}\n")
        f.write(f"wall_duration_s: {dur:.3f}\n")
        f.write(f"exit_code: {rc}\n")
        f.write(f"memory_free_before: {pre_free}\n")
        f.write(f"memory_free_after: {post_free}\n")

    # --- memory.txt (both methods labeled) ---
    with open(os.path.join(ev_dir, "memory.txt"), "w") as f:
        f.write("MEMORY MEASUREMENT — METHODS EXPLICITLY LABELED\n")
        f.write("=" * 60 + "\n")
        f.write(f"run_id: {run_id}\n\n")
        f.write("METHOD 1 (authoritative, post-exit): resource.getrusage(\n")
        f.write("  RUSAGE_CHILDREN).ru_maxrss — process peak resident set size of the\n")
        f.write(f"  CLI child process (Linux reports KiB; VmHWM-equivalent):\n")
        f.write(f"  ru_maxrss_peak = {peak_children_mb:.2f} MB\n\n")
        f.write("METHOD 2 (in-flight, polling): /proc/<pid>/status VmHWM sampled\n")
        f.write(f"  every 0.5 s while the CLI process ran (last observed peak):\n")
        f.write(f"  vmhwm_peak_observed = {vmhwm_mb:.2f} MB\n\n")
        f.write("NOTE: neither figure is tracemalloc. tracemalloc measures Python\n")
        f.write("object allocations only and is NOT comparable to process RSS.\n")
        f.write(f"MemAvailable before: {pre_free.get('MemAvailable_mb')} MB; "
                f"after: {post_free.get('MemAvailable_mb')} MB\n")

    # --- hashes.txt ---
    with open(os.path.join(ev_dir, "hashes.txt"), "w") as f:
        f.write(f"input_csv: {csv_in}\n")
        f.write(f"input_sha256: {sha256_of(os.path.join(REPO, csv_in))}\n")
        f.write(f"input_size_bytes: {os.path.getsize(os.path.join(REPO, csv_in))}\n")
        if rc == 0 or os.path.exists(os.path.join(REPO, csv_out)):
            out_abs = os.path.join(REPO, csv_out)
            f.write(f"output_csv: {csv_out}\n")
            f.write(f"output_sha256: {sha256_of(out_abs)}\n")
            f.write(f"output_size_bytes: {os.path.getsize(out_abs)}\n")

    print(json.dumps(result, indent=2))
    return 0 if rc == 0 else rc


if __name__ == "__main__":
    sys.exit(main() or 0)
