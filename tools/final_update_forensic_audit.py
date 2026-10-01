#!/usr/bin/env python3
"""DQAEIP FINAL UPDATE 2026-09-17 — final forensic audit (§38).

Machine-verifies the complete section-38 checklist from the actual
artifacts (never from prose). Every check is derived; PASS requires
every checklist item to be established from evidence.

Verdict is exact: PASS / PASS_WITH_DOCUMENTED_LIMITATIONS /
NOT_VERIFIED / FAIL — never invented, never upgraded.
"""

import hashlib
import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance.integrity import (  # noqa: E402
    FROZEN_V1_EXPECTED_SHA256, FROZEN_V1_SOURCE,
    OFFICIAL_EVIDENCE_DIR, OFFICIAL_INPUT_SHA256, OFFICIAL_OUTPUT_SHA256,
    UPDATE_ID, sha256_file)

NS = "evidence/FINAL_UPDATE_2026-09-17"
OUT = f"{NS}/final_verification/final_forensic_audit.json"

# Phase-0 baseline (pre-update state) for the unchanged checks
BASELINE = f"{NS}/baseline/baseline.json"
BASELINE_MANIFEST = f"{NS}/baseline/tracked_tree_manifest.json"


def load(rel):
    return json.load(open(os.path.join(REPO_ROOT, rel), encoding="utf-8"))


def exists(rel):
    return os.path.isfile(os.path.join(REPO_ROOT, rel))


def main():
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    checks = []

    def check(name, ok, detail=""):
        checks.append({"check": name,
                       "status": "PASS" if ok else "FAIL",
                       "detail": str(detail)[:400]})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")

    # ---- protected truth ------------------------------------------------
    baseline = load(BASELINE)
    baseline_manifest = load(BASELINE_MANIFEST)
    v1_now = sha256_file(os.path.join(REPO_ROOT, FROZEN_V1_SOURCE))
    v1_then = baseline_manifest["files"].get(FROZEN_V1_SOURCE, {}).get(
        "sha256")
    check("frozen_v1_unchanged", v1_now == v1_then,
          {"phase0": v1_then, "now": v1_now})
    check("frozen_v1_sha_exact", v1_now == FROZEN_V1_EXPECTED_SHA256)

    run1_then = baseline_manifest["files"].get(
        f"{OFFICIAL_EVIDENCE_DIR}/pass1_result.json", {}).get("sha256")
    run1_now = sha256_file(os.path.join(
        REPO_ROOT, f"{OFFICIAL_EVIDENCE_DIR}/pass1_result.json"))
    check("run_1_unchanged", run1_now == run1_then)
    run2_then = baseline_manifest["files"].get(
        f"{OFFICIAL_EVIDENCE_DIR}/pass2_result.json", {}).get("sha256")
    run2_now = sha256_file(os.path.join(
        REPO_ROOT, f"{OFFICIAL_EVIDENCE_DIR}/pass2_result.json"))
    check("run_2_unchanged", run2_now == run2_then)

    fr3m = load(f"{OFFICIAL_EVIDENCE_DIR}/FINAL_RESULTS.json")
    check("official_input_sha_exact",
          fr3m.get("input_sha256") == OFFICIAL_INPUT_SHA256)
    check("official_output_sha_exact",
          fr3m.get("output_sha256") == OFFICIAL_OUTPUT_SHA256)
    run_ids = sorted(fr3m.get("runs", {}).keys())
    check("exactly_two_official_runs", run_ids == ["run_1", "run_2"],
          run_ids)

    from data_quality_platform.assurance.integrity import monitor_Q_run3
    check("no_run_3",
          monitor_Q_run3(REPO_ROOT).status == "PASS")

    # ---- regenerated results ---------------------------------------------
    fr_update_path = f"{NS}/final_results/FINAL_RESULTS_UPDATE-2026-09-17.json"
    check("final_results_regenerated", exists(fr_update_path))
    from data_quality_platform.assurance.integrity import (
        schema_gate_final_results_update)
    problems = schema_gate_final_results_update(load(fr_update_path))
    check("final_results_schema_pass", not problems, problems[:3])

    graph = load(f"{NS}/dependency_graph/dependency_graph.json")
    graph_ok = (graph.get("graph_fingerprint") is not None
                and all(not n.get("missing_dependencies")
                        for n in graph.get("nodes", [])))
    check("evidence_graph_pass", graph_ok)

    freshness = load(f"{NS}/freshness/freshness_report.json")
    check("freshness_pass", freshness.get("overall_state") == "CURRENT",
          freshness.get("overall_state"))

    monitor = load(f"{NS}/integrity/integrity_monitor_report.json")
    check("integrity_pass", monitor.get("overall_status") == "PASS",
          monitor.get("overall_status"))

    drift = load(f"{NS}/drift/drift_report.json")
    check("drift_pass", drift.get("state") == "NONE", drift.get("state"))

    # ---- configuration / dependency / test health ---------------------------
    snap = load(f"{NS}/integrity/baseline_snapshot.json")
    import platform
    py_ok = (snap.get("configuration_baseline", {}).get(
        "python_version") == platform.python_version())
    check("configuration_pass", py_ok)

    dep_ok = all(not n.get("missing_dependencies")
                 for n in graph.get("nodes", []))
    check("dependency_health_pass", dep_ok)

    ts = load("evidence/rebuild_verification/test_summary.json")
    baseline_counts = snap.get("test_baseline", {})
    test_ok = (ts.get("all_green") is True
               and ts.get("collected", 0) >= baseline_counts.get(
                   "collected", 0)
               and ts.get("passed", 0) >= baseline_counts.get(
                   "passed", 0))
    check("test_health_pass", test_ok,
          {"collected": ts.get("collected"),
           "passed": ts.get("passed")})

    cc = load("evidence/release/contradiction_check.json")
    cc_count = cc.get("contradiction_count", cc.get("contradictions", 0))
    check("contradiction_count_zero", cc_count == 0, cc_count)

    sec = load("evidence/release/security_release_report.json")
    check("security_pass", sec.get("overall_verdict") == "PASS",
          sec.get("overall_verdict"))

    gate = load("evidence/release_gate/final_release_gate.json")
    gate_counts = gate.get("gate_counts", {})
    check("release_gate_21_21",
          gate.get("overall_verdict") == "PASS"
          and gate_counts.get("pass") == 21 and gate_counts.get("fail") == 0,
          gate_counts)

    zip_record = load(f"{NS}/release_manifest/zip_record.json")
    zip_ok = (zip_record.get("status") == "VERIFIED"
              and zip_record.get("verification", {}).get("crc") == "PASS"
              and zip_record.get("verification", {}).get(
                  "member_sha256_verified") == zip_record.get(
                      "member_count"))
    check("zip_integrity_pass", zip_ok,
          {"sha256": zip_record.get("zip_sha256"),
           "members": zip_record.get("member_count")})

    extraction = load(f"{NS}/final_verification/"
                      "clean_extraction_report.json")
    check("clean_extraction_pass", extraction.get("verdict") == "PASS")

    lock = load(f"{NS}/release_manifest/release_lock.json")
    lock_ok = (lock.get("status") == "LOCKED"
               and lock.get("final_results_sha256") == sha256_file(
                   os.path.join(REPO_ROOT, fr_update_path))
               and lock.get("frozen_v1_sha256") == FROZEN_V1_EXPECTED_SHA256
               and lock.get("official_input_sha256") == OFFICIAL_INPUT_SHA256
               and lock.get("official_output_sha256") == OFFICIAL_OUTPUT_SHA256)
    check("release_lock_pass", lock_ok)

    # ---- unsupported claims (README negative scan) ---------------------------
    readme = open(os.path.join(REPO_ROOT, "README.md"),
                  encoding="utf-8").read().lower()
    forbidden = ["3,000,000 real rows", "real rows", "production ready",
                 "bounded memory", "run 3 completed", "kernel-level sandbox"]
    hits = [f for f in forbidden if f in readme]
    check("no_unsupported_claims", not hits, hits)

    total = len(checks)
    passed = sum(1 for c in checks if c["status"] == "PASS")
    verdict = ("PASS" if passed == total else "FAIL")

    doc = {
        "report": "DQAEIP FINAL UPDATE final forensic audit (section 38)",
        "update_id": UPDATE_ID,
        "generated_utc": started,
        "checklist_total": total,
        "checklist_passed": passed,
        "verdict": verdict,
        "verdict_rule": ("PASS only when every checklist item is "
                         "machine-established from artifacts; never "
                         "invented, never upgraded"),
        "checks": checks,
        "zip_identity": {
            "sha256": zip_record.get("zip_sha256"),
            "size_bytes": zip_record.get("zip_size_bytes"),
            "members": zip_record.get("member_count"),
        },
    }
    os.makedirs(os.path.dirname(os.path.join(REPO_ROOT, OUT)), exist_ok=True)
    with open(os.path.join(REPO_ROOT, OUT), "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"FINAL FORENSIC AUDIT: {verdict} ({passed}/{total})")
    return 0 if verdict == "PASS" else 4


if __name__ == "__main__":
    sys.exit(main())
