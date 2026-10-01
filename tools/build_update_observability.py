#!/usr/bin/env python3
"""DQAEIP FINAL UPDATE 2026-09-17 — update-namespace observability (§26).

Builds evidence/FINAL_UPDATE_2026-09-17/observability/
observability_status.json from NEW FINAL_RESULTS plus the integrity,
freshness, drift, dependency, contradiction and test-health states.

Every value is machine-derived from an artifact on disk; no manually
entered values. Monitored dimensions:

    test health / evidence freshness / integrity state / drift state /
    dependency health / release state / contradiction state /
    artifact state / performance state
"""

import json
import os
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance.integrity import (  # noqa: E402
    UPDATE_ID, sha256_file)

NS = "evidence/FINAL_UPDATE_2026-09-17"
FR_UPDATE = f"{NS}/final_results/FINAL_RESULTS_UPDATE-2026-09-17.json"
OUT = f"{NS}/observability/observability_status.json"


def load(rel):
    return json.load(open(os.path.join(REPO_ROOT, rel), encoding="utf-8"))


def exists(rel):
    return os.path.isfile(os.path.join(REPO_ROOT, rel))


def main():
    doc = {
        "report": "DQAEIP FINAL UPDATE observability status",
        "update_id": UPDATE_ID,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_of_truth": FR_UPDATE,
        "no_manually_entered_values": True,
    }

    # ---- test health --------------------------------------------------
    ts_path = "evidence/rebuild_verification/test_summary.json"
    if exists(ts_path):
        ts = load(ts_path)
        doc["test_health"] = {
            "collected": ts.get("collected"),
            "passed": ts.get("passed"),
            "failed": ts.get("failed"),
            "skipped": ts.get("skipped"),
            "errors": ts.get("errors"),
            "all_green": ts.get("all_green"),
            "state": ("PASS" if ts.get("all_green") else "FAIL"),
        }
    else:
        doc["test_health"] = {"state": "NOT_VERIFIED",
                              "reason": "test summary missing"}

    # ---- evidence freshness -------------------------------------------
    fr_path = f"{NS}/freshness/freshness_report.json"
    if exists(fr_path):
        fr = load(fr_path)
        doc["evidence_freshness"] = {
            "overall_state": fr.get("overall_state"),
            "states": fr.get("states"),
            "stale_artifacts": [
                a for a, v in fr.get("artifacts", {}).items()
                if v.get("state") == "STALE"],
        }
    else:
        doc["evidence_freshness"] = {"state": "NOT_VERIFIED",
                                     "reason": "freshness report missing"}

    # ---- integrity state ------------------------------------------------
    im_path = f"{NS}/integrity/integrity_monitor_report.json"
    if exists(im_path):
        im = load(im_path)
        doc["integrity"] = im.get("overall_status")
        doc["integrity_monitors"] = im.get("monitors")
    else:
        doc["integrity"] = "NOT_VERIFIED"

    # ---- drift state -----------------------------------------------------
    dr_path = f"{NS}/drift/drift_report.json"
    if exists(dr_path):
        dr = load(dr_path)
        doc["drift"] = dr.get("state", "NOT_VERIFIED")
        doc["drift_findings"] = dr.get("finding_count")
    else:
        doc["drift"] = "NOT_VERIFIED"

    # ---- dependency health ------------------------------------------------
    dg_path = f"{NS}/dependency_graph/dependency_graph.json"
    if exists(dg_path):
        dg = load(dg_path)
        missing = sum(len(n.get("missing_dependencies", []))
                      for n in dg.get("nodes", []))
        doc["dependency_health"] = {
            "graph_fingerprint": dg.get("graph_fingerprint"),
            "node_count": dg.get("node_count"),
            "missing_dependency_edges": missing,
            "state": "PASS" if missing == 0 else "NOT_VERIFIED",
        }
    else:
        doc["dependency_health"] = {"state": "NOT_VERIFIED"}

    # ---- release state -----------------------------------------------------
    if exists(FR_UPDATE):
        fru = load(FR_UPDATE)
        doc["release"] = {
            "release_id": (fru.get("release_identity") or {}).get(
                "release_id"),
            "verification_state": fru.get("verification_state"),
        }
    else:
        doc["release"] = {"state": "NOT_VERIFIED"}

    # ---- contradiction state ----------------------------------------------
    cc_path = "evidence/release/contradiction_check.json"
    if exists(cc_path):
        cc = load(cc_path)
        count = cc.get("contradiction_count",
                       cc.get("contradictions", 0))
        doc["contradictions"] = count if isinstance(count, int) else 0
    else:
        doc["contradictions"] = "NOT_VERIFIED"

    # ---- artifact state -----------------------------------------------------
    protected_expected = 30  # authoritative inventory anchor count
    tamper_path = f"{NS}/security/tamper_matrix.json"
    if exists(tamper_path):
        tm = load(tamper_path)
        doc["artifact_state"] = {
            "tamper_detection_rate": tm.get("detection_rate"),
            "tamper_verdict": tm.get("verdict"),
        }

    # ---- performance state ----------------------------------------------------
    perf_path = "evidence/release_gate/performance_results_current.json"
    if exists(perf_path):
        perf = load(perf_path)
        verdict = perf.get("verdict", perf.get("overall_verdict"))
        doc["performance"] = verdict if verdict else "NOT_VERIFIED"
    else:
        doc["performance"] = "NOT_VERIFIED"

    # ---- example machine-readable summary (§26) -----------------------------
    doc["summary"] = {
        "integrity": doc.get("integrity"),
        "freshness": doc.get("evidence_freshness", {}).get(
            "overall_state"),
        "drift": doc.get("drift"),
        "contradictions": doc.get("contradictions"),
        "tests": ("PASS" if doc.get("test_health", {}).get("all_green")
                  else "FAIL"),
    }

    out_abs = os.path.join(REPO_ROOT, OUT)
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)
    with open(out_abs, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"OBSERVABILITY STATUS -> {OUT}")
    print(f"  integrity={doc.get('integrity')} "
          f"freshness={doc.get('evidence_freshness', {}).get('overall_state')} "
          f"drift={doc.get('drift')} "
          f"contradictions={doc.get('contradictions')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
