#!/usr/bin/env python3
"""Run a real terminal command, capture complete stdout/stderr + exit code +
child peak RSS (ru_maxrss via getrusage RUSAGE_CHILDREN), and write an
evidence file. Used for the 5M dataset generation and the two 5M pipeline
runs so that every recorded terminal output is a real captured one.

Usage:
  python run_capture.py --out <evidence-file> -- <command> [args...]

Writes to --out:
  $ python run_capture.py --out X -- <cmd...>
  <command>: <the exact command>
  <full stdout+stderr interleaved as captured>
  Exit code: N
  Child peak RSS (ru_maxrss, VmHWM-equivalent): N.NN MB
  Wall duration: N.NNN s
"""

import argparse
import resource
import subprocess
import sys
import time

def main():
    argv = sys.argv[1:]
    if "--out" not in argv:
        print("missing --out", file=sys.stderr)
        return 2
    i = argv.index("--out")
    out_path = argv[i + 1]
    rest = argv[i + 2:]
    if not rest or rest[0] != "--":
        print("missing -- separator before command", file=sys.stderr)
        return 2
    cmd = rest[1:]

    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    dur = time.time() - t0
    # RUSAGE_CHILDREN ru_maxrss = max over reaped children (Linux: KiB)
    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    peak_mb = ru.ru_maxrss / 1024.0

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("$ python run_capture.py --out %s --\n" % out_path)
        f.write("COMMAND: %s\n" % " ".join(cmd))
        f.write("START_EPOCH: %.3f\n" % t0)
        f.write("--- captured stdout ---\n")
        f.write(proc.stdout)
        if proc.stderr:
            f.write("--- captured stderr ---\n")
            f.write(proc.stderr)
        f.write("--- end ---\n")
        f.write("Exit code: %d\n" % proc.returncode)
        f.write("Child peak RSS (ru_maxrss, VmHWM-equivalent, max over reaped children): %.2f MB\n" % peak_mb)
        f.write("Wall duration: %.3f s\n" % dur)
    print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    print(f"[run_capture] exit={proc.returncode} duration={dur:.3f}s child_peak_rss={peak_mb:.2f}MB -> {out_path}")
    return proc.returncode

if __name__ == "__main__":
    sys.exit(main())
