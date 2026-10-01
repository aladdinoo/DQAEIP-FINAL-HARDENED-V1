#!/usr/bin/env python3
"""DQAEIP FINAL PORTABLE EVIDENCE UPDATE V2 (2026-09-18) — Phase 13.

ABSOLUTE-PATH RELEASE GATE (UPDATE-V2 scope).

Runs the EXISTING fail-closed gate engine
(tools/absolute_path_release_gate.run_gate — the same scanner,
detectors and exception-validation logic; no independent
implementation) against the ACTUAL UPDATE-V2 release scope:

    - root release files (README.md, RELEASE_NOTES.md,
      FINAL_RESULTS.json, final_result.json, release_manifest.json,
      DELIVERY_MANIFEST.json)
    - current evidence directories (evidence/release,
      evidence/rebuild_verification, evidence/mutation_testing,
      evidence/hardening_baseline) — regression check
    - the previous portable-release namespace (regression check)
    - the UPDATE-V2 namespace (new scope)

Exceptions are EXACT FILE + EXACT REASON + CLASSIFICATION — never
directories, never patterns (a broad exception like evidence/** or
/home/** is FORBIDDEN by the task book and by this registry's own
validation). The gate FAILS CLOSED: missing scope files, a broken
registry, stale exceptions or any machine-local path fails it.
"""

import argparse
import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from tools.absolute_path_release_gate import run_gate  # noqa: E402

UPDATE_ID = "DQAEIP-FINAL-UPDATE-V2-2026-09-18"
NS = "evidence/FINAL_PORTABLE_UPDATE_V2_2026-09-18"
EXCEPTIONS_OUT = os.path.join(
    REPO_ROOT, NS, "release_gate",
    "absolute_path_gate_exceptions_UPDATE-V2.json")
REPORT_OUT = os.path.join(
    REPO_ROOT, NS, "release_gate",
    "absolute_path_gate_report_UPDATE-V2.json")

V1_NS = "evidence/FINAL_PORTABLE_RELEASE_2026-09-18"

# V2 scope: the V1 scope (regression) + the UPDATE-V2 namespace.
# evidence/release_gate top-level reports are added as explicit FILES
# (the 24 replay-fixture ORIGINALS stay out of scope under the
# documented historical policy — captured outputs, byte-preserved;
# their portable representations exist in the V2 namespace).
SCOPE_EXTRA_FILES = [
    "evidence/release_gate/final_release_gate.json",
    "evidence/release_gate/final_release_gate_attempt2_pii_"
    "falsepositive.json",
    "evidence/release_gate/performance_results_current.json",
]
SCOPE_EXTRA_DIRS = [NS]
REJECTED_DIR = os.path.join(NS, "release_gate", "rejected_attempts")

EXCEPTIONS = [
    {
        "path": f"{V1_NS}/path_forensics/ABSOLUTE_PATH_INVENTORY.json",
        "reason": "the previous round's Phase-1 forensic inventory "
                  "necessarily QUOTES the machine-local values it "
                  "detected; diagnostic record of violations, not a "
                  "filesystem dependency; originals live in preserved "
                  "historical artifacts and portable derived "
                  "representations exist",
        "classification": "diagnostic_quoting_violations",
    },
    {
        "path": "evidence/hardening_baseline/test_baseline.txt",
        "reason": "historical captured pytest output (2026-09-16 "
                  "hardening round) quoting the authoring machine's "
                  "pytest installation path inside a deprecation "
                  "warning; verbatim capture retained as historical "
                  "record; test counts machine-verified separately",
        "classification": "historical_captured_output",
    },
    {
        "path": f"{NS}/path_forensics/path_inventory_UPDATE-V2.json",
        "reason": "the UPDATE-V2 Phase-1 complete JSON path inventory "
                  "necessarily QUOTES every original machine-local "
                  "value it classified (that is its forensic purpose); "
                  "diagnostic record, not a filesystem dependency; "
                  "every file it quotes is preserved byte-exact and "
                  "has a machine-path-free derived representation "
                  "where the release requires one",
        "classification": "diagnostic_quoting_violations",
    },
    {
        "path": f"{NS}/path_forensics/json_semantic_diff_UPDATE-V2.json",
        "reason": "the UPDATE-V2 Phase-6 semantic diff necessarily "
                  "records the BEFORE (machine-local) and AFTER "
                  "(portable) value of every approved path change so "
                  "auditors can verify that nothing else changed; "
                  "diagnostic record, not a filesystem dependency",
        "classification": "diagnostic_quoting_violations",
    },
    {
        "path": f"{NS}/README.UPDATE-V2.md",
        "reason": "section 4 documents the portability transformation "
                  "with deliberate BEFORE examples of the exact "
                  "machine-local repository prefix the normalizer "
                  "rewrites (the examples ARE the documentation); the "
                  "README has no filesystem dependency on any "
                  "machine-local path and the transformation examples "
                  "are required for auditors to understand what was "
                  "repaired",
        "classification": "documented_example",
    },
]


def rejected_attempt_exceptions():
    """Narrow exceptions for preserved failed gate/verification
    attempts.

    A FAILING report necessarily QUOTES machine-local values (violation
    excerpts, the physical clean-room scratch location) — that is its
    forensic purpose. Failed attempts are preserved verbatim under
    rejected_attempts/ (never deleted; the repo's established
    rejected-attempt convention) and each exact file carries this
    narrow, reason-specific exception. PASSING reports are sanitized
    to portable form and need no exception.
    """
    out = []
    for rej_dir in (
            os.path.join(NS, "release_gate", "rejected_attempts"),
            os.path.join(NS, "self_contained_verification",
                         "rejected_attempts")):
        rej_abs = os.path.join(REPO_ROOT, rej_dir)
        if not os.path.isdir(rej_abs):
            continue
        for fn in sorted(os.listdir(rej_abs)):
            if not fn.endswith(".json"):
                continue
            out.append({
                "path": f"{rej_dir}/{fn}",
                "reason": "preserved FAILED attempt — necessarily "
                          "quotes the machine-local values it recorded "
                          "(violation excerpts / physical clean-room "
                          "scratch location) as its forensic record; "
                          "rejected attempt, not a filesystem "
                          "dependency; the passing canonical report is "
                          "machine-path-free",
                "classification": "diagnostic_quoting_violations",
            })
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.parse_args()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    all_exceptions = EXCEPTIONS + rejected_attempt_exceptions()

    # write the narrow exception registry (validated by the gate
    # engine itself: malformed or over-broad entries fail the run)
    registry = {
        "report": "DQAEIP UPDATE-V2 absolute-path gate exception "
                  "registry (narrow, path-specific, auditable)",
        "schema": {"name": "dqaeip.path_gate_exceptions", "version": "1.0"},
        "update_id": UPDATE_ID,
        "release_id": UPDATE_ID,
        "generated_utc": started,
        "policy": "every exception is an exact repository-relative file "
                  "path with an exact reason and classification; one "
                  "file per exception; no directories, no patterns, no "
                  "detector-level exemptions; broad exceptions (whole "
                  "tree or drive-letter glob patterns, extension "
                  "wildcards) are FORBIDDEN; a structurally invalid "
                  "registry fails the gate itself",
        "exceptions": all_exceptions,
    }
    os.makedirs(os.path.dirname(EXCEPTIONS_OUT), exist_ok=True)
    with open(EXCEPTIONS_OUT, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, sort_keys=True)
        f.write("\n")

    # run the gate (existing engine, V2 scope override)
    report = run_gate(exceptions_path=EXCEPTIONS_OUT,
                      extra_files=SCOPE_EXTRA_FILES,
                      extra_dirs=SCOPE_EXTRA_DIRS)

    # FAIL path: preserve the failed report as a rejected attempt and
    # NEVER write it to the canonical path (a failing report quotes
    # machine paths in its violation excerpts — writing it canonically
    # would self-pollute the next run; the attempt is preserved
    # verbatim under rejected_attempts/, nothing is deleted)
    if report["verdict"] != "PASS":
        rej_abs_dir = os.path.join(REPO_ROOT, REJECTED_DIR)
        os.makedirs(rej_abs_dir, exist_ok=True)
        n = 1
        while os.path.exists(os.path.join(
                rej_abs_dir,
                f"absolute_path_gate_attempt{n}_rejected.json")):
            n += 1
        rej_path = os.path.join(
            rej_abs_dir,
            f"absolute_path_gate_attempt{n}_rejected.json")
        report["report"] = ("DQAEIP UPDATE-V2 absolute-path gate — "
                           "REJECTED ATTEMPT (fail-closed; preserved "
                           "verbatim)")
        report["update_id"] = UPDATE_ID
        report["rejected_attempt"] = n
        with open(rej_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, sort_keys=True)
            f.write("\n")
        print(f"absolute-path gate (UPDATE-V2): FAIL — attempt "
              f"preserved as {REJECTED_DIR}/"
              f"absolute_path_gate_attempt{n}_rejected.json")
        for v in report["violations"][:10]:
            print(f"  [VIOLATION] {v['source']}:{v['line']} "
                  f"({v['rule']})")
        return 4

    # annotate the report with the UPDATE-V2 identity + the scope
    # note about what is deliberately outside the gate
    report["report"] = ("DQAEIP FINAL PORTABLE EVIDENCE UPDATE V2 — "
                       "Phase 13 absolute-path release gate "
                       "(fail-closed)")
    report["update_id"] = UPDATE_ID
    report["schema"] = {"name": "dqaeip.absolute_path_gate_report",
                        "version": "1.1"}
    report["scope"]["scope_note"] = (
        "UPDATE-V2 release scope: root release files + current "
        "evidence directories + the previous portable-release "
        "namespace (regression check) + the UPDATE-V2 namespace "
        "(new scope) + the release-gate top-level reports. The 24 "
        "replay-fixture ORIGINALS under evidence/release_gate/"
        "replay_work*/ and repro_check/ are deliberately outside the "
        "gate under the documented historical-evidence policy "
        "(captured engine outputs, byte-preserved; their "
        "machine-path-free portable representations exist in the "
        "UPDATE-V2 namespace); historical archives (dated "
        "namespaces, superseded rounds) are covered by the same "
        "documented policy, not silently ignored — every value is "
        "inventoried in path_inventory_UPDATE-V2.json")
    report["scope"]["update_v2_extra_files"] = SCOPE_EXTRA_FILES
    report["scope"]["update_v2_extra_dirs"] = SCOPE_EXTRA_DIRS

    os.makedirs(os.path.dirname(REPORT_OUT), exist_ok=True)
    with open(REPORT_OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"absolute-path gate (UPDATE-V2): {report['verdict']}")
    print(f"  violations: {report['violation_count']}")
    print(f"  files scanned: {report['scope']['scanned_file_count']}")
    print(f"  exceptions granted: "
          f"{len(report['exception_registry']['granted'])}")
    print(f"  stale exceptions: "
          f"{report['exception_registry']['stale_exceptions']}")
    print(f"  registry problems: "
          f"{report['exception_registry']['registry_problems']}")
    print(f"  report: {REPORT_OUT}")
    return 0 if report["verdict"] == "PASS" else 4


if __name__ == "__main__":
    sys.exit(main())
