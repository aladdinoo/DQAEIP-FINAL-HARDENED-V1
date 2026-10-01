#!/usr/bin/env python3
"""DQAEIP ASSURANCE-LAYER MUTATION TESTING (rebuild Phase 14).

Proves the assurance layer DETECTS controlled failures — the release
gate must reject every invalid release. Unlike business-rule mutation
testing (scripts/mutation_testing.py, 17/17), this battery mutates the
ASSURANCE-LAYER INPUTS (evidence artifacts + release documents), never
the business rules.

Evidence scenarios (each: mutate -> run the actual verifier -> MUST
detect (FAIL) -> restore original bytes -> verify restoration SHA-256):

  A1  missing run manifest
  A2  modified run manifest (run_id tampered)
  A3  wrong artifact hash (manifest flag_counts tampered)
  A4  tampered covered artifact (lineage.json modified)
  A5  malformed evidence JSON (monitoring.json corrupted)
  A6  wrong input hash (pass1_result dataset.sha256)
  A7  wrong output hash (pass2_result output.sha256)
  A8  mixed Run1/Run2 lineage (pass2 git_commit tampered)
  A9  wrong rule hash (pass1 manifest rule hash set)
  A10 missing evidence file (pass2_result.json removed)
  A11 FINAL_RESULTS final_status tampered

Document scenarios (on synthetic documents / live modules):
  B1  unknown status in release metadata (release_schema)
  B2  machine-local path injection (path_firewall)
  B3  fabricated claim value (claims re-derivation)

Restoration proof: SHA-256 of every touched real file before the
battery == after the battery (byte-for-byte). Output:

  evidence/release/assurance_mutation.json

FAIL CLOSED: any scenario NOT detected, or any restoration mismatch,
is a battery failure (exit 1).
"""

import hashlib
import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EV = os.path.join(REPO_ROOT, "evidence", "validation", "2026-09-18", "fresh_3m2", "harness")
VERIFIER = os.path.join(REPO_ROOT, "scripts", "verify_run_pair.py")
OUT = os.path.join(REPO_ROOT, "evidence", "release", "assurance_mutation.json")

TOUCHED_FILES = [
    f"{EV}/pass1_engine/manifest.json",
    f"{EV}/pass1_engine/lineage.json",
    f"{EV}/pass2_engine/manifest.json",
    f"{EV}/pass2_engine/monitoring.json",
    f"{EV}/pass1_result.json",
    f"{EV}/pass2_result.json",
    f"{EV}/FINAL_RESULTS.json",
]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_verifier():
    """Run the actual run-pair verifier; return (detected, output_tail).

    detected=True means the verifier REJECTED the mutated evidence
    (non-zero exit) — the correct behavior for an invalid release.
    """
    import subprocess
    r = subprocess.run([sys.executable, VERIFIER], capture_output=True,
                       text=True, timeout=300)
    return r.returncode != 0, (r.stdout + r.stderr).strip()[-500:]


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def write_bytes(path, data):
    with open(path, "wb") as f:
        f.write(data)


def mutate_json_file(path, mutator):
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    mutator(doc)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)


def record(results, sid, desc, target, detected, detail):
    results.append({
        "scenario": sid,
        "description": desc,
        "target": target,
        "expected": "REJECTED",
        "actual": "REJECTED" if detected else "ACCEPTED",
        "detected": bool(detected),
        "verifier_output_tail": detail,
    })


def mutated_scenario(results, sid, desc, path, prepare):
    """Apply mutation, run verifier, restore bytes, record result."""
    original = read_bytes(path)
    try:
        prepare(path)
        detected, detail = run_verifier()
    finally:
        write_bytes(path, original)
    record(results, sid, desc,
           os.path.relpath(path, REPO_ROOT).replace(os.sep, "/"),
           detected, detail)


def absent_scenario(results, sid, desc, path):
    """Remove file, run verifier, restore, record."""
    original = read_bytes(path)
    os.remove(path)
    try:
        detected, detail = run_verifier()
    finally:
        write_bytes(path, original)
    record(results, sid, desc,
           os.path.relpath(path, REPO_ROOT).replace(os.sep, "/"),
           detected, detail)


def document_scenarios(results):
    """B-scenarios: synthetic documents + live module validators."""
    sys.path.insert(0, REPO_ROOT)
    from data_quality_platform.assurance import (claims, path_firewall,
                                                 release_schema)

    # B1: unknown status in release metadata
    bad = {
        "release_identity": {"name": "x"},
        "project_identity": {"name": "x"},
        "git_identity": {"head": "x"},
        "rule_identity": {"rules": {}},
        "runs": {
            "run_1": {"run_id": "r1", "status": "PASS"},
            "run_2": {"run_id": "r2", "status": "PASS"},
        },
        "verification": {},
        "limitations": [],
        "final_release_status": "PROBABLY_FINE",
        "claims": [],
    }
    problems = release_schema.validate_final_results(bad)
    record(results, "B1", "unknown status in release metadata "
           "(release_schema)", "<synthetic document>",
           bool(problems), "; ".join(problems[:3]))

    # B2: machine-local path injection
    violations = path_firewall.scan_text(
        "command: /home/z/user/run.py --csv C:\\data\\in.csv --out "
        "\\\\server\\share\\o.csv")
    record(results, "B2", "machine-local path injection (path_firewall)",
           "<synthetic text>", bool(violations),
           f"{len(violations)} violations: "
           + ", ".join(v["rule"] for v in violations[:6]))

    # B3: fabricated claim values (verified=true but wrong/absent values)
    fake_claims = [
        {   # wrong value vs re-derivation
            "claim": "rows", "value": 3000001,
            "source_artifact": "evidence/validation/2026-09-18/fresh_3m2/harness/"
                               "FINAL_RESULTS.json",
            "source_sha256": sha256_file(f"{EV}/FINAL_RESULTS.json"),
            "derivation": "final_3m_rows", "verified": True,
            "status": "VERIFIED_LOCALLY",
        },
        {   # NOT_VERIFIED masquerading as verified with null value
            "claim": "input_sha", "value": None,
            "source_artifact": None, "source_sha256": None,
            "derivation": "final_3m_input_sha256", "verified": True,
            "status": "NOT_VERIFIED",
        },
    ]
    report = claims.verify_claims(fake_claims, REPO_ROOT)
    rejected = not report["recheck_passed"]
    record(results, "B3", "fabricated claim value (claims re-derivation)",
           "<synthetic claims>", rejected,
           json.dumps(report["results"])[:400])


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    pre = {os.path.relpath(p, REPO_ROOT).replace(os.sep, "/"):
           sha256_file(p) for p in TOUCHED_FILES}

    # Baseline: verifier must be PASS on clean evidence right now
    base_detected, base_detail = run_verifier()
    if base_detected:
        print("BASELINE verifier NOT PASS on unmutated evidence; aborting")
        print(base_detail[-500:])
        return 2
    # restore the clean baseline report hash snapshot
    pre_after_baseline = {os.path.relpath(p, REPO_ROOT).replace(os.sep, "/"):
                          sha256_file(p) for p in TOUCHED_FILES}

    results = []

    # A1: missing run manifest
    absent_scenario(results, "A1", "missing run manifest",
                   f"{EV}/pass1_engine/manifest.json")
    # A2: modified run manifest
    mutated_scenario(results, "A2", "modified run manifest (run_id tampered)",
                    f"{EV}/pass1_engine/manifest.json",
                    lambda p: mutate_json_file(
                        p, lambda d: d.__setitem__("run_id", "final_3m_XX")))
    # A3: wrong artifact hash (flag counts tampered)
    mutated_scenario(results, "A3", "wrong artifact hash (flag_counts "
                    "tampered)", f"{EV}/pass1_engine/manifest.json",
                    lambda p: mutate_json_file(
                        p, lambda d: d["flag_counts"]
                        .__setitem__("email_blank", 1)))
    # A4: tampered covered artifact
    mutated_scenario(results, "A4", "tampered covered artifact "
                    "(lineage.json)", f"{EV}/pass1_engine/lineage.json",
                    lambda p: mutate_json_file(
                        p, lambda d: d.__setitem__("tampered", True)))
    # A5: malformed evidence JSON
    mutated_scenario(results, "A5", "malformed evidence JSON "
                    "(monitoring.json)", f"{EV}/pass2_engine/monitoring.json",
                    lambda p: open(p, "w").write("{not valid json"))
    # A6: wrong input hash
    mutated_scenario(results, "A6", "wrong input hash (pass1 dataset)",
                    f"{EV}/pass1_result.json",
                    lambda p: mutate_json_file(
                        p, lambda d: d["dataset"]
                        .__setitem__("sha256", "0" * 64)))
    # A7: wrong output hash
    mutated_scenario(results, "A7", "wrong output hash (pass2 output)",
                    f"{EV}/pass2_result.json",
                    lambda p: mutate_json_file(
                        p, lambda d: d["output"]
                        .__setitem__("sha256", "1" * 64)))
    # A8: mixed lineage
    mutated_scenario(results, "A8", "mixed Run1/Run2 lineage (pass2 "
                    "git_commit tampered)", f"{EV}/pass2_result.json",
                    lambda p: mutate_json_file(
                        p, lambda d: d.__setitem__("git_commit", "f" * 40)))
    # A9: wrong rule hash
    mutated_scenario(results, "A9", "wrong rule hash in run manifest",
                    f"{EV}/pass1_engine/manifest.json",
                    lambda p: mutate_json_file(
                        p, lambda d: d["rule_hashes"]
                        .__setitem__("email_blank", "a" * 64)))
    # A10: missing evidence file
    absent_scenario(results, "A10", "missing evidence file "
                   "(pass2_result.json removed)", f"{EV}/pass2_result.json")
    # A11: FINAL_RESULTS status tampered
    mutated_scenario(results, "A11", "FINAL_RESULTS final_status tampered",
                    f"{EV}/FINAL_RESULTS.json",
                    lambda p: mutate_json_file(
                        p, lambda d: d.__setitem__("final_status",
                                                   "DEFINITELY_PASS")))

    # B scenarios (documents)
    document_scenarios(results)

    # Restoration proof
    post = {os.path.relpath(p, REPO_ROOT).replace(os.sep, "/"):
            sha256_file(p) for p in TOUCHED_FILES}
    restoration_ok = post == pre_after_baseline

    # Final clean verifier run must PASS again
    final_detected, _ = run_verifier()
    final_clean = not final_detected

    detected_count = sum(1 for r in results if r["detected"])
    battery_pass = (detected_count == len(results) and restoration_ok
                    and final_clean)

    out_report = {
        "report": "DQAEIP assurance-layer mutation testing",
        "generated_utc": started,
        "scope": (
            "assurance layer ONLY (evidence artifacts + release "
            "documents); business rules are NEVER mutated here (see "
            "scripts/mutation_testing.py for the rule-suite battery)"
        ),
        "baseline_clean_verifier_pass": True,
        "scenarios_total": len(results),
        "scenarios_detected": detected_count,
        "scenarios_accepted_in_error": [r["scenario"] for r in results
                                        if not r["detected"]],
        "restoration_verified": restoration_ok,
        "restoration_note": (
            "SHA-256 of every touched file equals its pre-battery value "
            "(byte-for-byte restoration proof)"
        ),
        "final_clean_verifier_pass": final_clean,
        "scenarios": results,
        "mutation_score": round(detected_count / len(results), 4)
        if results else 0.0,
        "verdict": "PASS" if battery_pass else "FAIL",
        "verdict_note": (
            "PASS only when every controlled failure is detected AND "
            "every mutated file is restored byte-exactly AND the clean "
            "verifier passes again; target: 100% detection"
        ),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out_report, f, indent=2)
        f.write("\n")

    print(f"ASSURANCE MUTATION: {out_report['verdict']}")
    print(f"  scenarios: {detected_count}/{len(results)} detected")
    for r in results:
        mark = "x" if r["detected"] else " "
        print(f"  [{mark}] {r['scenario']:4s} {r['description']}")
    print(f"  restoration verified: {restoration_ok}")
    print(f"  final clean pass: {final_clean}")
    return 0 if battery_pass else 1


if __name__ == "__main__":
    sys.exit(main())
