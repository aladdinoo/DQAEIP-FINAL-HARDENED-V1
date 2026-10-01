#!/usr/bin/env python3
"""DQAEIP FINAL UPDATE 2026-09-17 — tamper matrix runner (§20).

Executes the fifteen required tamper scenarios against ISOLATED
temporary fixtures (never against authoritative production evidence)
and records detected / not_detected for each.

Required: 100% detection for the defined critical scenarios. Any
not_detected scenario yields an overall FAIL and a non-zero exit code.
"""

import json
import os
import shutil
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# Import the fixture helpers from the test module by path (the tests
# directory is not a package-importable location for tools).
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "tamper_fixtures",
    os.path.join(REPO_ROOT, "tests", "assurance",
                 "test_integrity_monitoring.py"))
_fix = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fix)
build_good_tree = _fix.build_good_tree
build_snapshot = _fix.build_snapshot

from data_quality_platform.assurance.integrity import (  # noqa: E402
    detect_configuration_drift, detect_evidence_drift,
    detect_release_drift, evaluate_freshness, run_all_monitors, sha256_file,
)

OUT_PATH = os.path.join(
    REPO_ROOT, "evidence", "FINAL_CLEAN_REBUILD_RELEASE_2026-09-18",
    "security", "tamper_matrix.json")

V1_REL = "data_quality_platform/rules/v1_rules.py"
OFFICIAL = "evidence/validation/2026-09-18/fresh_3m2/harness"


def _t_frozen_v1(root, snap):
    p = os.path.join(root, V1_REL)
    open(p, "a", encoding="utf-8").write("\n# tampered\n")
    r = run_all_monitors(root, snap)
    return (r["monitors"]["N_frozen_v1"] == "FAIL"
            and r["monitors"]["A_content_changes"] == "FAIL")


def _t_run1(root, snap):
    p = os.path.join(root, f"{OFFICIAL}/pass1_result.json")
    d = json.load(open(p, encoding="utf-8"))
    d["rows"] = 1
    json.dump(d, open(p, "w", encoding="utf-8"))
    r = run_all_monitors(root, snap)
    return r["monitors"]["O_official_3m_evidence"] == "FAIL"


def _t_run2(root, snap):
    p = os.path.join(root, f"{OFFICIAL}/pass2_result.json")
    d = json.load(open(p, encoding="utf-8"))
    d["oracle"]["mismatches"] = 7
    json.dump(d, open(p, "w", encoding="utf-8"))
    r = run_all_monitors(root, snap)
    return r["monitors"]["O_official_3m_evidence"] == "FAIL"


def _t_final_results(root, snap):
    p = os.path.join(root, snap["final_results_path"])
    d = json.load(open(p, encoding="utf-8"))
    d["injected"] = True
    json.dump(d, open(p, "w", encoding="utf-8"))
    return run_all_monitors(root, snap)["monitors"][
        "L_final_results"] == "FAIL"


def _t_hash(root, snap):
    p = os.path.join(root, f"{OFFICIAL}/FINAL_RESULTS.json")
    d = json.load(open(p, encoding="utf-8"))
    d["input_sha256"] = "f" * 64
    json.dump(d, open(p, "w", encoding="utf-8"))
    return any(f.severity == "CRITICAL"
               for f in detect_evidence_drift(root, snap))


def _t_manifest(root, snap):
    p = os.path.join(root, snap["release_manifest_path"])
    json.dump({"files": []}, open(p, "w", encoding="utf-8"))
    return run_all_monitors(root, snap)["monitors"][
        "I_manifest_changes"] == "FAIL"


def _t_provenance(root, snap):
    p = os.path.join(root, snap["provenance_path"])
    json.dump({"claims": [{"id": "x"}]}, open(p, "w", encoding="utf-8"))
    return run_all_monitors(root, snap)["monitors"][
        "J_provenance_changes"] == "FAIL"


def _t_checker(root, snap):
    open(os.path.join(root, "scripts/final_3m_validation.py"),
         "a", encoding="utf-8").write("# tampered\n")
    return run_all_monitors(root, snap)["monitors"]["P_checker"] == "FAIL"


def _t_readme(root, snap):
    open(os.path.join(root, "README.md"), "a",
         encoding="utf-8").write("\n# tampered metrics\n")
    return run_all_monitors(root, snap)["monitors"][
        "M_readme_metrics"] == "FAIL"


def _t_run3(root, snap):
    p = os.path.join(root, f"{OFFICIAL}/run_3_result.json")
    json.dump({"pass": "run_3"}, open(p, "w", encoding="utf-8"))
    r = run_all_monitors(root, snap)
    return (r["monitors"]["Q_run3_appearance"] == "FAIL"
            and r["monitors"]["C_unexpected_creation"] == "FAIL")


def _t_duplicate(root, snap):
    p = os.path.join(root, snap["release_manifest_path"])
    d = json.load(open(p, encoding="utf-8"))
    d["files"].append({"path": "COPY.md",
                       "artifact_identity": "presentation/readme"})
    json.dump(d, open(p, "w", encoding="utf-8"))
    return run_all_monitors(root, snap)["monitors"][
        "R_duplicate_identity"] == "FAIL"


def _t_missing(root, snap):
    os.remove(os.path.join(root, f"{OFFICIAL}/pass1_result.json"))
    r = run_all_monitors(root, snap)
    return (r["monitors"]["B_deletion"] == "FAIL"
            and r["monitors"]["O_official_3m_evidence"] == "FAIL")


def _t_stale(root, snap):
    deps = [{"path": "evidence/rebuild_verification/test_summary.json",
             "sha256": sha256_file(os.path.join(
                 root, "evidence/rebuild_verification/"
                       "test_summary.json"))}]
    p = os.path.join(root, "evidence/rebuild_verification/"
                        "test_summary.json")
    d = json.load(open(p, encoding="utf-8"))
    d["passed"] += 1
    json.dump(d, open(p, "w", encoding="utf-8"))
    return evaluate_freshness("X", deps, root)["state"] == "STALE"


def _t_release(root, snap):
    p = os.path.join(root, snap["final_results_path"])
    d = json.load(open(p, encoding="utf-8"))
    d["release_identity"]["release_id"] = "FORGED"
    json.dump(d, open(p, "w", encoding="utf-8"))
    r = run_all_monitors(root, snap)
    return (r["monitors"]["K_release_identity"] == "FAIL"
            and any(f.severity == "CRITICAL"
                    for f in detect_release_drift(root, snap)))


def _t_config(root, snap):
    snap["configuration_baseline"]["python_version"] = "0.0.0"
    return any(f.drift_type == "CONFIGURATION_DRIFT"
               for f in detect_configuration_drift(root, snap))


SCENARIOS = [
    ("01_frozen_v1_modification", _t_frozen_v1),
    ("02_run1_modification", _t_run1),
    ("03_run2_modification", _t_run2),
    ("04_final_results_modification", _t_final_results),
    ("05_hash_modification", _t_hash),
    ("06_manifest_modification", _t_manifest),
    ("07_provenance_modification", _t_provenance),
    ("08_checker_sha_modification", _t_checker),
    ("09_readme_metric_modification", _t_readme),
    ("10_fake_run3", _t_run3),
    ("11_duplicate_artifact", _t_duplicate),
    ("12_missing_evidence", _t_missing),
    ("13_stale_dependency", _t_stale),
    ("14_release_identity_modification", _t_release),
    ("15_configuration_drift", _t_config),
]


def main():
    results = []
    for name, fn in SCENARIOS:
        tmp = tempfile.mkdtemp(prefix="dqaeip_tamper_")
        try:
            root = build_good_tree(tmp)
            snap = build_snapshot(root)
            detected = bool(fn(root, snap))
            results.append({
                "scenario": name,
                "detection": "detected" if detected else "not_detected",
            })
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    detected_count = sum(
        1 for r in results if r["detection"] == "detected")
    doc = {
        "report": "DQAEIP FINAL UPDATE tamper matrix (section 20)",
        "update_id": "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18",
        "schema": {"name": "dqaeip.tamper_matrix", "version": "1.0"},
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "isolation": ("every scenario ran against an isolated temporary "
                      "fixture; authoritative production evidence was "
                      "never touched"),
        "scenario_count": len(results),
        "detected_count": detected_count,
        "detection_rate": f"{detected_count}/{len(results)}",
        "required_detection_rate": "100%",
        "verdict": "PASS" if detected_count == len(results) else "FAIL",
        "scenarios": results,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"TAMPER MATRIX: {doc['verdict']} "
          f"({detected_count}/{len(results)} detected)")
    for r in results:
        marker = "OK " if r["detection"] == "detected" else "!!!"
        print(f"  [{marker}] {r['scenario']}: {r['detection']}")
    return 0 if doc["verdict"] == "PASS" else 4


if __name__ == "__main__":
    sys.exit(main())
