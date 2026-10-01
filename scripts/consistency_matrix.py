#!/usr/bin/env python3
"""DQAEIP FINAL CONSISTENCY MATRIX (rebuild Phase 24).

Machine-readable cross-artifact consistency matrix:

    README <-> RELEASE_NOTES <-> FINAL_RESULTS <-> RELEASE_MANIFEST
        <-> RELEASE_GATE <-> RUN_1 <-> RUN_2 <-> ORACLE
        <-> RULE_REGISTRY <-> GIT_COMMIT

Checks that every relevant identity matches across all artifacts that
record it. Any mismatch => RELEASE_RECONSTRUCTION_FAILED (exit 1).

Identities compared (when recorded):
    git head, input SHA-256, output SHA-256, schema hash, checker SHA,
    rule hash set, run IDs, rows, final verdict, test counts
"""

import json
import os
import re
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

EV_3M = "evidence/validation/2026-09-19/fresh_3m2"


def sha256_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def maybe_load(rel):
    try:
        with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def read_text(rel):
    try:
        with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def main():
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    head = subprocess.run(
        ["git", "-C", REPO_ROOT, "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False).stdout.strip()

    fr = maybe_load("FINAL_RESULTS.json") or maybe_load("final_result.json")
    rm = maybe_load("release_manifest.json")
    # F-01: route through canonical helper to prevent stale-PASS
    # survival when the .in_progress marker exists.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from data_quality_platform.assurance.release_chain import \
        load_current_release_gate_report
    gate = load_current_release_gate_report(REPO_ROOT)
    fr3m = maybe_load(f"{EV_3M}/FINAL_RESULTS.json")
    m1 = maybe_load(f"{EV_3M}/pass1_engine/manifest.json")
    m2 = maybe_load(f"{EV_3M}/pass2_engine/manifest.json")
    readme = read_text("README.md")
    notes = read_text("RELEASE_NOTES.md")

    from data_quality_platform.rules.registry import RuleRegistry
    registry = RuleRegistry.create_default()
    rule_hashes = {r.rule_id: r.hash for r in registry.get_all_rules()}
    checker_sha = sha256_file(os.path.join(
        REPO_ROOT, "scripts", "final_3m_validation.py"))

    checks = []

    def check(name, values, required=True):
        vals = [v for v in values if v is not None]
        distinct = {json.dumps(v, sort_keys=True) for v in vals}
        if required:
            # every source must record the identity and all must agree
            consistent = len(distinct) == 1 and len(vals) == len(values)
        else:
            # sources that record nothing (None placeholders) do not
            # contradict; recorded values must agree among themselves
            consistent = len(distinct) <= 1
        checks.append({
            "identity": name,
            "recorded_in": len(vals),
            "expected_sources": len(values),
            "consistent": consistent,
            "value_preview": (str(vals[0])[:64] if vals else None),
        })

    # git head: documents record the BUILD COMMIT (the HEAD at
    # evidence-generation time). The release commit (which contains
    # the evidence) is a descendant of the build commit. Therefore
    # the correct check is ANCESTOR: the recorded build commit must
    # be an ancestor of (or equal to) the live HEAD.
    #
    # This is NOT strict equality because:
    #   - evidence cannot contain its own commit's SHA (circular dep)
    #   - build commit is the PARENT of the release commit
    #   - after commit: recorded (parent) != live (child), but ancestor → PASS
    #
    # The ANCESTOR check correctly rejects:
    #   - unreachable SHAs (git merge-base exits 128)
    #   - unrelated histories (not an ancestor → exit 1)
    #   - missing/malformed SHAs (fr_head is None → no subprocess)
    fr_head = fr.get("git_identity", {}).get("head") if fr else None
    rm_head = rm.get("git", {}).get("head") if rm else None
    doc_heads_agree = fr_head is not None and fr_head == rm_head
    # ANCESTOR check: is the recorded build commit an ancestor of live HEAD?
    if fr_head:
        anc = subprocess.run(
            ["git", "-C", REPO_ROOT, "merge-base", "--is-ancestor",
             fr_head, "HEAD"],
            capture_output=True, check=False)
        lineage_ok = anc.returncode == 0
    else:
        lineage_ok = False
    checks.append({
        "identity": "git_head",
        "recorded_in": 2 if doc_heads_agree else (1 if fr_head else 0),
        "expected_sources": 2,
        "consistent": bool(doc_heads_agree and lineage_ok),
        "value_preview": fr_head,
        "detail": {
            "doc_recorded_head": fr_head,
            "release_manifest_head": rm_head,
            "live_head": head,
            "check": "ancestor (recorded build commit must be ancestor of live HEAD)",
            "lineage_ok": lineage_ok,
        },
    })
    # input SHA
    check("input_sha256", [
        fr.get("verification", {}).get("input_sha256") if fr else None,
        fr3m.get("input_sha256"),
        fr3m.get("runs", {}).get("run_1", {}).get("dataset", {})
        .get("sha256"),
        fr3m.get("runs", {}).get("run_2", {}).get("dataset", {})
        .get("sha256"),
    ])
    # output SHA
    check("output_sha256", [
        fr.get("verification", {}).get("output_sha256") if fr else None,
        fr3m.get("output_sha256"),
        fr3m.get("runs", {}).get("run_1", {}).get("output", {})
        .get("sha256"),
        fr3m.get("runs", {}).get("run_2", {}).get("output", {})
        .get("sha256"),
    ])
    # schema hash
    check("schema_hash_run_manifests", [
        m1.get("schema_hash"), m2.get("schema_hash"),
    ])
    # rule identity (registry vs both run manifests vs FINAL_RESULTS)
    check("rule_hash_set", [
        rule_hashes,
        m1.get("rule_hashes"),
        m2.get("rule_hashes"),
        fr.get("rule_identity", {}).get("rule_hashes") if fr else None,
    ])
    # checker identity — CURRENT only
    # Anti-regression: the 3M run evidence (fr3m) records the checker
    # SHA AT THE TIME THE 3M RUN EXECUTED (historical, frozen). Post-B-8,
    # the current checker SHA differs from the 3M run's recorded SHA
    # because B-8 hardened the checker. Comparing them as if they
    # should match is incorrect — they legitimately differ. The
    # current checker SHA is verified against FINAL_RESULTS' claim
    # (which records the current value). The historical 3M run's
    # recorded SHA is verified separately against the frozen_core
    # reference (see historical_checker_sha256 below).
    fr3m_script_sha = fr3m.get("provenance", {}).get("script_sha256")
    fr_claimed_checker = fr.get("claims") and next(
        (c.get("value") for c in fr.get("claims", [])
         if c.get("claim") == "checker script SHA-256"), None)
    check("checker_sha256", [
        checker_sha,
        fr_claimed_checker,
    ])
    # historical checker SHA — the 3M run's recorded checker SHA
    # must match the frozen_core.checker_sha256 (historical certified
    # baseline reference). This is a HISTORICAL consistency check,
    # not a current-vs-historical comparison.
    frozen_checker = (fr.get("frozen_core", {}).get("checker_sha256")
                      if fr else None)
    check("historical_checker_sha256", [
        fr3m_script_sha,
        frozen_checker,
    ], required=False)
    # run IDs: the run manifests record "final_3m_passN" run_ids; the
    # 3M FINAL_RESULTS records the pass markers — normalize to run_id
    # form before comparing
    p1 = fr3m.get("runs", {}).get("run_1", {}).get("pass")
    p2 = fr3m.get("runs", {}).get("run_2", {}).get("pass")
    check("run_ids", [
        [m1.get("run_id"), m2.get("run_id")],
        [f"final_3m_{p1}" if p1 else None,
         f"final_3m_{p2}" if p2 else None],
    ])
    # rows
    check("rows_3m", [
        fr3m.get("rows"),
        fr.get("verification", {}).get("rows") if fr else None,
    ])
    # final verdict values across docs
    fr_verdict = fr.get("final_release_status") if fr else None
    check("final_release_status", [
        fr_verdict,
        rm.get("validation", {}).get("final_verdict") if rm else None,
    ])
    # gate verdict
    gate_verdict = gate.get("overall_verdict") if gate else None
    check("release_gate_verdict", [
        gate_verdict,
        fr.get("verification", {}).get("release_gate_verdict")
        if fr else None,
        rm.get("validation", {}).get("release_gate_verdict")
        if rm else None,
    ], required=False)  # FINAL_RESULTS may carry null pre-refresh
    # test counts
    check("tests_passed", [
        fr.get("test_identity", {}).get("passed") if fr else None,
        rm.get("validation", {}).get("tests", {}).get("passed")
        if rm else None,
    ])
    # oracle math
    check("oracle_comparisons_combined", [
        fr3m.get("comparison_count", {}).get("combined_total"),
        51200000,
    ])
    check("oracle_mismatches_combined", [
        fr3m.get("oracle_mismatches", {}).get("combined_total"), 0,
    ])
    # release identity
    rel_name = rm.get("release_name") if rm else None
    check("release_name", [
        rel_name,
        fr.get("release_identity", {}).get("release_name") if fr else None,
    ])
    # documents carry the core hashes (string presence check)
    inp = fr3m.get("input_sha256", "")
    out = fr3m.get("output_sha256", "")
    doc_checks = {
        "README.md": (inp[:16] in readme and out[:16] in readme),
        "RELEASE_NOTES.md": (inp[:16] in notes and out[:16] in notes),
    }
    for doc, ok in doc_checks.items():
        checks.append({
            "identity": f"{doc} carries I/O hash fingerprints",
            "recorded_in": 1 if ok else 0,
            "expected_sources": 1,
            "consistent": ok,
            "value_preview": f"{inp[:16]}…/{out[:16]}…",
        })

    all_ok = all(c["consistent"] for c in checks)
    matrix = {
        "report": "DQAEIP final consistency matrix",
        "generated_utc": started,
        "git_head": head,
        "verdict": "CONSISTENT" if all_ok
        else "RELEASE_RECONSTRUCTION_FAILED",
        "verdict_note": (
            "any mismatch in any recorded identity is "
            "RELEASE_RECONSTRUCTION_FAILED; identities recorded nowhere "
            "are not compared (None never matches a value)"
        ),
        "checks": checks,
        "checks_total": len(checks),
        "checks_failed": sum(1 for c in checks if not c["consistent"]),
        "failed_identities": [c["identity"] for c in checks
                              if not c["consistent"]],
    }
    out = os.path.join(REPO_ROOT, "evidence", "release",
                       "consistency_matrix.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(matrix, f, indent=2)
        f.write("\n")
    print(f"CONSISTENCY MATRIX: {matrix['verdict']}")
    print(f"  checks: {len(checks)} total, "
          f"{matrix['checks_failed']} failed")
    for c in checks:
        mark = "x" if c["consistent"] else " "
        print(f"  [{mark}] {c['identity']}")
    print(f"  report: evidence/release/consistency_matrix.json")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
