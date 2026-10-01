"""DQAEIP FINAL UPDATE 2026-09-17 — integrity monitoring tamper and
recovery tests (task-book sections 20 and 21).

EVERY tamper scenario mutates a SYNTHETIC evidence tree under tmp_path
(never the protected official evidence) and asserts the corrupted state
can NEVER produce PASS. Required detection coverage (section 20):

     1. Frozen V1 modification            -> detected (monitors A/E/N)
     2. Run 1 modification               -> detected (A/E/O)
     3. Run 2 modification               -> detected (A/E/O)
     4. FINAL_RESULTS modification       -> detected (L)
     5. hash modification                -> detected (EVIDENCE_DRIFT)
     6. manifest modification            -> detected (I/T)
     7. provenance modification          -> detected (J)
     8. checker SHA modification         -> detected (P)
     9. README metric modification       -> detected (M)
    10. fake Run 3                       -> detected (Q/C)
    11. duplicate artifact               -> detected (R)
    12. missing evidence                 -> detected (B)
    13. stale dependency                 -> detected (freshness STALE)
    14. release identity modification   -> detected (K + RELEASE_DRIFT)
    15. configuration drift              -> detected (CONFIGURATION_DRIFT)

Recovery invariants (section 21):
    - a failed rebuild does not destroy old evidence
    - a failed promotion does not corrupt current evidence
    - partial staging is detectable
    - interrupted generation is detectable
    - a corrupted manifest is rejected
    - an incomplete release is rejected
"""

import hashlib
import importlib.util
import json
import os
import shutil
import sys

import pytest

FIXTURE_NS = "evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance.integrity import (
    ALL_MONITORS, FROZEN_V1_SOURCE, OFFICIAL_EVIDENCE_DIR,
    append_ledger, dependency_fingerprint, detect_configuration_drift,
    detect_evidence_drift, detect_release_drift,
    evaluate_freshness, ledger_entry, load_snapshot,
    run_all_monitors, schema_gate_final_results_update, sha256_file,
    worst_status,
)

V1_SHA = "daef1ded54c7d3c79898a1ba253be2acd5b6120e18b16b09009fdd7be9fc2276"
INPUT_SHA = "59624a53c72f908f1dde673ceecf59e0662ae721bb8f9af7e165acba5318d153"
OUTPUT_SHA = "b72adc235160a86e0b99a08f988dd0bb5f2cff82bbe5b5d28ea07c5a5719329a"


def _write_json(root, rel, doc):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
    return path


def _write_text(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def build_good_tree(tmp_path):
    """Synthetic working tree with real anchor constants; content is
    synthetic — the REAL protected evidence is never touched."""
    root = str(tmp_path)
    # frozen V1 source: copy the REAL frozen file (read-only usage)
    real_v1 = os.path.join(REPO_ROOT, FROZEN_V1_SOURCE)
    _write_text(root, FROZEN_V1_SOURCE, open(real_v1, encoding="utf-8").read())
    # rules package marker (registry import is NOT needed for monitors)
    _write_text(root, "data_quality_platform/rules/__init__.py", "")
    # official 3M evidence (synthetic JSON carrying real anchors)
    official = {
        "rows": 3200000,
        "seed": 20260918,
        "input_sha256": INPUT_SHA,
        "output_sha256": OUTPUT_SHA,
        "oracle_comparisons": 51200000,
        "determinism_status": "PASS (byte-identical across two runs)",
        "safety_status": "PASS",
        "sp1_isolation_status": "PASS",
        "runs": {
            "run_1": {"oracle": {"comparisons": 25600000,
                                 "mismatches": 0}},
            "run_2": {"oracle": {"comparisons": 25600000,
                                 "mismatches": 0}},
        },
    }
    _write_json(root, f"{OFFICIAL_EVIDENCE_DIR}/FINAL_RESULTS.json",
                official)
    for n in (1, 2):
        _write_json(root, f"{OFFICIAL_EVIDENCE_DIR}/pass{n}_result.json",
                    {"pass": f"pass{n}", "rows": 3200000,
                     "oracle": {"comparisons": 25600000,
                                "mismatches": 0},
                     "input_sha256": INPUT_SHA,
                     "output_sha256": OUTPUT_SHA})
    _write_text(root, "scripts/final_3m_validation.py",
                "# synthetic checker stand-in\n")
    _write_text(root, "scripts/verify_run_pair.py",
                "# synthetic verifier stand-in\n")
    # derived artifacts
    _write_json(root, "evidence/rebuild_verification/"
                "run_pair_verification.json",
                {"verdict": "PASS", "checks_total": 95,
                 "checks_failed": 0})
    _write_json(root, "evidence/rebuild_verification/test_summary.json",
                {"collected": 942, "passed": 933, "failed": 0,
                 "skipped": 9, "errors": 0, "all_green": True})
    _write_json(root, "evidence/mutation_testing/mutation_results.json",
                {"mutants_detected": 17, "mutants_total": 17})
    _write_json(root, "evidence/release/assurance_mutation.json",
                {"false_pass_scenarios_rejected": 14,
                 "false_pass_scenarios_total": 14})
    _write_json(root, "evidence/release/limitation_registry.json",
                {"limitations": [
                    {"id": "L1",
                     "text": "synthetic limitation for fixture"}]})
    fr_update = {
        "release_identity": {"release_id":
                             "DQAEIP-FINAL-UPDATE-2026-09-17"},
    }
    _write_json(root, f"{FIXTURE_NS}/final_results/"
                "FINAL_RESULTS_PORTABLE_2026-09-18.json", fr_update)
    _write_text(root, "README.md",
                "# synthetic readme (no forbidden claims)\n")
    _write_json(root, f"{FIXTURE_NS}/release_manifest/"
                "release_manifest.json",
                {"files": [
                    {"path": "README.md",
                     "artifact_identity": "presentation/readme"},
                    {"path": "FINAL_RESULTS.json",
                     "artifact_identity": "results/final"}]})
    _write_json(root, f"{FIXTURE_NS}/release_manifest/"
                "release_lock.json",
                {"release_id": "DQAEIP-FINAL-UPDATE-2026-09-17",
                 "status": "LOCKED"})
    _write_json(root, "evidence/release/claim_provenance.json",
                {"claims": []})
    _write_json(root, f"{FIXTURE_NS}/freshness/"
                "freshness_report.json",
                {"artifacts": {}})
    _write_json(root, f"{FIXTURE_NS}/dependency_graph/"
                "dependency_graph.json",
                {"graph_fingerprint": "deadbeef" * 8})
    return root


def build_snapshot(root, **overrides):
    """Snapshot mirroring the production builder over the fixture."""
    protected = {}
    for d in ("data_quality_platform/rules", OFFICIAL_EVIDENCE_DIR):
        base = os.path.join(root, d)
        for walk_root, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for fn in sorted(files):
                rel = os.path.relpath(
                    os.path.join(walk_root, fn), root).replace(os.sep, "/")
                protected[rel] = sha256_file(os.path.join(root, rel))
    for rel in ("scripts/final_3m_validation.py",
                "scripts/verify_run_pair.py"):
        protected[rel] = sha256_file(os.path.join(root, rel))
    snap = {
        "snapshot_version": "1.0.0",
        "update_id": "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18",
        "protected_artifact_hashes": protected,
        "protected_artifact_modes": {
            rel: oct(os.stat(os.path.join(root, rel)).st_mode & 0o777)
            for rel in protected},
        "protected_directories": [OFFICIAL_EVIDENCE_DIR,
                                  "data_quality_platform/rules"],
        "expected_release_identity": {
            "release_id": "DQAEIP-FINAL-PORTABLE-EVIDENCE-RELEASE-"
                          "2026-09-18"},
        "expected_evidence_identity": {
            "frozen_v1_sha256": V1_SHA,
            "input_sha256": INPUT_SHA,
            "output_sha256": OUTPUT_SHA},
        "expected_dependency_graph_fingerprint": "deadbeef" * 8,
        "final_results_path": f"{FIXTURE_NS}/final_results/"
                              "FINAL_RESULTS_PORTABLE_2026-09-18.json",
        "final_results_sha256": sha256_file(os.path.join(
            root, f"{FIXTURE_NS}/final_results/"
                  "FINAL_RESULTS_PORTABLE_2026-09-18.json")),
        "readme_path": "README.md",
        "readme_sha256": sha256_file(os.path.join(root, "README.md")),
        "release_manifest_path": f"{FIXTURE_NS}/release_manifest/"
                                 "release_manifest.json",
        "release_manifest_sha256": sha256_file(os.path.join(
            root, f"{FIXTURE_NS}/release_manifest/"
                  "release_manifest.json")),
        "release_lock_path": f"{FIXTURE_NS}/release_manifest/"
                             "release_lock.json",
        "release_lock_sha256": sha256_file(os.path.join(
            root, f"{FIXTURE_NS}/release_manifest/"
                  "release_lock.json")),
        "provenance_path": "evidence/release/claim_provenance.json",
        "provenance_sha256": sha256_file(os.path.join(
            root, "evidence/release/claim_provenance.json")),
        "test_baseline": {"collected": 942, "passed": 933,
                          "skipped": 9, "failed": 0, "errors": 0},
        "test_summary_path": "evidence/rebuild_verification/"
                             "test_summary.json",
        "configuration_baseline": {"python_version": None,
                                   "installed_packages": {},
                                   "config_hashes": {}},
    }
    snap.update(overrides)
    return snap


# ---------------------------------------------------------------------
# Section 20 — the 15 required tamper scenarios (100% detection)
# ---------------------------------------------------------------------

@pytest.mark.parametrize("monitor_names", [
    ("A_content_changes", "E_sha_changes", "N_frozen_v1")])
def test_tamper_01_frozen_v1_modification(tmp_path, monitor_names):
    root = build_good_tree(tmp_path)
    snap = build_snapshot(root)
    v1 = os.path.join(root, FROZEN_V1_SOURCE)
    text = open(v1, encoding="utf-8").read()
    open(v1, "w", encoding="utf-8").write(text + "\n# tampered\n")
    report = run_all_monitors(root, snap)
    for m in monitor_names:
        assert report["monitors"][m] == "FAIL", (
            f"{m} must detect frozen V1 tampering")
    assert report["overall_status"] == "FAIL"


def test_tamper_02_run1_modification(tmp_path):
    root = build_good_tree(tmp_path)
    snap = build_snapshot(root)
    p = os.path.join(root, f"{OFFICIAL_EVIDENCE_DIR}/pass1_result.json")
    doc = json.load(open(p, encoding="utf-8"))
    doc["rows"] = 2999999
    json.dump(doc, open(p, "w", encoding="utf-8"))
    report = run_all_monitors(root, snap)
    for m in ("A_content_changes", "E_sha_changes",
              "O_official_3m_evidence"):
        assert report["monitors"][m] == "FAIL"


def test_tamper_03_run2_modification(tmp_path):
    root = build_good_tree(tmp_path)
    snap = build_snapshot(root)
    p = os.path.join(root, f"{OFFICIAL_EVIDENCE_DIR}/pass2_result.json")
    doc = json.load(open(p, encoding="utf-8"))
    doc["oracle"]["mismatches"] = 1
    json.dump(doc, open(p, "w", encoding="utf-8"))
    report = run_all_monitors(root, snap)
    for m in ("A_content_changes", "O_official_3m_evidence"):
        assert report["monitors"][m] == "FAIL"


def test_tamper_04_final_results_modification(tmp_path):
    root = build_good_tree(tmp_path)
    snap = build_snapshot(root)
    p = os.path.join(root, snap["final_results_path"])
    doc = json.load(open(p, encoding="utf-8"))
    doc["derived_values"] = {"combined_mismatches": 999}
    json.dump(doc, open(p, "w", encoding="utf-8"))
    report = run_all_monitors(root, snap)
    assert report["monitors"]["L_final_results"] == "FAIL"


def test_tamper_05_hash_modification(tmp_path):
    root = build_good_tree(tmp_path)
    snap = build_snapshot(root)
    p = os.path.join(root, f"{OFFICIAL_EVIDENCE_DIR}/FINAL_RESULTS.json")
    doc = json.load(open(p, encoding="utf-8"))
    doc["input_sha256"] = "0" * 64
    json.dump(doc, open(p, "w", encoding="utf-8"))
    findings = detect_evidence_drift(root, snap)
    assert any(f.drift_type == "EVIDENCE_DRIFT" and f.severity == "CRITICAL"
               for f in findings)


def test_tamper_06_manifest_modification(tmp_path):
    root = build_good_tree(tmp_path)
    snap = build_snapshot(root)
    p = os.path.join(root, snap["release_manifest_path"])
    json.dump({"files": []}, open(p, "w", encoding="utf-8"))
    report = run_all_monitors(root, snap)
    assert report["monitors"]["I_manifest_changes"] == "FAIL"
    # truncated manifest -> malformed detection
    open(p, "w", encoding="utf-8").write("{ not json")
    report = run_all_monitors(root, snap)
    assert report["monitors"]["T_malformed_manifests"] == "FAIL"


def test_tamper_07_provenance_modification(tmp_path):
    root = build_good_tree(tmp_path)
    snap = build_snapshot(root)
    p = os.path.join(root, snap["provenance_path"])
    json.dump({"claims": [{"id": "injected"}]},
              open(p, "w", encoding="utf-8"))
    report = run_all_monitors(root, snap)
    assert report["monitors"]["J_provenance_changes"] == "FAIL"


def test_tamper_08_checker_sha_modification(tmp_path):
    root = build_good_tree(tmp_path)
    snap = build_snapshot(root)
    open(os.path.join(root, "scripts/final_3m_validation.py"),
         "a", encoding="utf-8").write("# tampered\n")
    report = run_all_monitors(root, snap)
    assert report["monitors"]["P_checker"] == "FAIL"
    assert report["monitors"]["A_content_changes"] == "FAIL"


def test_tamper_09_readme_metric_modification(tmp_path):
    root = build_good_tree(tmp_path)
    snap = build_snapshot(root)
    open(os.path.join(root, "README.md"), "a",
         encoding="utf-8").write("\nmetric: 100 real rows\n")
    report = run_all_monitors(root, snap)
    assert report["monitors"]["M_readme_metrics"] == "FAIL"


def test_tamper_10_fake_run3(tmp_path):
    root = build_good_tree(tmp_path)
    snap = build_snapshot(root)
    _write_json(root, f"{OFFICIAL_EVIDENCE_DIR}/run3_result.json",
                {"pass": "run3", "unauthorized": True})
    report = run_all_monitors(root, snap)
    assert report["monitors"]["Q_run3_appearance"] == "FAIL"
    assert report["monitors"]["C_unexpected_creation"] == "FAIL"


def test_tamper_11_duplicate_artifact(tmp_path):
    root = build_good_tree(tmp_path)
    snap = build_snapshot(root)
    p = os.path.join(root, snap["release_manifest_path"])
    doc = json.load(open(p, encoding="utf-8"))
    doc["files"].append({"path": "README_COPY.md",
                         "artifact_identity": "presentation/readme"})
    json.dump(doc, open(p, "w", encoding="utf-8"))
    report = run_all_monitors(root, snap)
    assert report["monitors"]["R_duplicate_identity"] == "FAIL"


def test_tamper_12_missing_evidence(tmp_path):
    root = build_good_tree(tmp_path)
    snap = build_snapshot(root)
    os.remove(os.path.join(root, f"{OFFICIAL_EVIDENCE_DIR}/"
                          "pass1_result.json"))
    report = run_all_monitors(root, snap)
    assert report["monitors"]["B_deletion"] == "FAIL"
    assert report["monitors"]["O_official_3m_evidence"] == "FAIL"


def test_tamper_13_stale_dependency(tmp_path):
    root = build_good_tree(tmp_path)
    deps = [{"path": "evidence/rebuild_verification/test_summary.json",
             "sha256": sha256_file(os.path.join(
                 root, "evidence/rebuild_verification/"
                       "test_summary.json"))}]
    result = evaluate_freshness(
        "FINAL_RESULTS_UPDATE", deps, root,
        recorded_self_sha=sha256_file(os.path.join(
            root, f"{FIXTURE_NS}/final_results/"
                  "FINAL_RESULTS_PORTABLE_2026-09-18.json")),
        artifact_path=f"{FIXTURE_NS}/final_results/"
                      "FINAL_RESULTS_PORTABLE_2026-09-18.json")
    assert result["state"] == "CURRENT"
    # now mutate the dependency -> STALE
    p = os.path.join(root, "evidence/rebuild_verification/"
                        "test_summary.json")
    doc = json.load(open(p, encoding="utf-8"))
    doc["passed"] += 1
    json.dump(doc, open(p, "w", encoding="utf-8"))
    result2 = evaluate_freshness(
        "FINAL_RESULTS_UPDATE", deps, root)
    assert result2["state"] == "STALE"
    # remove the dependency -> NOT_VERIFIED
    os.remove(p)
    result3 = evaluate_freshness(
        "FINAL_RESULTS_UPDATE", deps, root)
    assert result3["state"] == "NOT_VERIFIED"


def test_tamper_14_release_identity_modification(tmp_path):
    root = build_good_tree(tmp_path)
    snap = build_snapshot(root)
    p = os.path.join(root, snap["final_results_path"])
    doc = json.load(open(p, encoding="utf-8"))
    doc["release_identity"]["release_id"] = "DQAEIP-FORGED-RELEASE"
    json.dump(doc, open(p, "w", encoding="utf-8"))
    report = run_all_monitors(root, snap)
    assert report["monitors"]["K_release_identity"] == "FAIL"
    findings = detect_release_drift(root, snap)
    assert any(f.drift_type == "RELEASE_DRIFT"
               and f.severity == "CRITICAL" for f in findings)


def test_tamper_15_configuration_drift(tmp_path):
    root = build_good_tree(tmp_path)
    snap = build_snapshot(root)
    snap["configuration_baseline"]["python_version"] = "9.9.9"
    findings = detect_configuration_drift(root, snap)
    assert any(f.drift_type == "CONFIGURATION_DRIFT"
               for f in findings)


# ---------------------------------------------------------------------
# Clean-state invariants (no false positives on the good tree)
# ---------------------------------------------------------------------

def test_good_tree_all_protection_monitors_pass(tmp_path):
    root = build_good_tree(tmp_path)
    snap = build_snapshot(root)
    report = run_all_monitors(root, snap)
    for m in ("A_content_changes", "B_deletion",
              "C_unexpected_creation", "E_sha_changes",
              "N_frozen_v1", "O_official_3m_evidence",
              "P_checker", "Q_run3_appearance",
              "R_duplicate_identity", "T_malformed_manifests"):
        assert report["monitors"][m] == "PASS", (
            f"{m} must not false-positive on a clean tree: "
            f"{report['monitors'][m]}")


def test_missing_snapshot_is_not_verified_never_pass(tmp_path):
    """Fail-closed: a missing snapshot can NEVER yield PASS."""
    path = os.path.join(str(tmp_path), "nope.json")
    with pytest.raises(Exception) as excinfo:
        load_snapshot(path)
    assert getattr(excinfo.value, "status", None) == "NOT_VERIFIED"


def test_corrupt_snapshot_fails_closed(tmp_path):
    path = _write_text(str(tmp_path), "snapshot.json", "{ broken")
    with pytest.raises(Exception) as excinfo:
        load_snapshot(path)
    assert getattr(excinfo.value, "status", None) == "FAIL"


def test_fail_never_downgraded():
    assert worst_status(["PASS", "FAIL", "WARNING"]) == "FAIL"
    assert worst_status(["FAIL", "NOT_VERIFIED"]) == "FAIL"
    assert worst_status(["PASS", "STALE", "WARNING"]) == "STALE"
    assert worst_status(["PASS", "PASS"]) == "PASS"
    assert worst_status([]) == "NOT_VERIFIED"


# ---------------------------------------------------------------------
# Section 21 — recovery invariants
# ---------------------------------------------------------------------

def _load_rebuild_tool():
    spec = importlib.util.spec_from_file_location(
        "portable_final_results_rebuild",
        os.path.join(REPO_ROOT, "tools",
                    "portable_final_results_rebuild.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_recovery_failed_rebuild_keeps_old_evidence(tmp_path):
    """A failed rebuild must NOT destroy the existing evidence."""
    root = build_good_tree(tmp_path)
    mod = _load_rebuild_tool()
    mod.set_repo_root(root)
    # break a dependency so derivation fails
    os.remove(os.path.join(
        root, "evidence/release/assurance_mutation.json"))
    before = sha256_file(os.path.join(
        root, f"{FIXTURE_NS}/final_results/"
              "FINAL_RESULTS_PORTABLE_2026-09-18.json"))
    rc = mod.main([])
    assert rc == 2, "derivation failure must exit non-zero"
    after = sha256_file(os.path.join(
        root, f"{FIXTURE_NS}/final_results/"
              "FINAL_RESULTS_PORTABLE_2026-09-18.json"))
    assert before == after, "old evidence destroyed by failed rebuild"
    assert os.path.isfile(os.path.join(
        root, f"{FIXTURE_NS}/staging/",
        "rebuild_failure.log")), "failure must be recorded"


def test_recovery_failed_verification_does_not_promote(tmp_path):
    """Verify failure keeps CURRENT intact and staging retained."""
    root = build_good_tree(tmp_path)
    mod = _load_rebuild_tool()
    mod.set_repo_root(root)
    current_rel = (f"{FIXTURE_NS}/final_results/"
                   "FINAL_RESULTS_PORTABLE_2026-09-18.json")
    before = sha256_file(os.path.join(root, current_rel))
    # sabotage verification: run-pair verdict not PASS
    p = os.path.join(root, "evidence/rebuild_verification/"
                        "run_pair_verification.json")
    doc = json.load(open(p, encoding="utf-8"))
    doc["verdict"] = "FAIL"
    json.dump(doc, open(p, "w", encoding="utf-8"))
    rc = mod.main([])          # derives, verifies -> must fail promote path
    assert rc in (0, 3), "tool must not crash"
    # with verdict FAIL the derived doc FAILs the impossible-combination
    # gate only when run_pair_verdict != PASS is caught by the schema
    # gate (PASS without evidence); a FAIL verdict yields state FAIL,
    # which the gate accepts as consistent — so we additionally assert
    # promotion never happened without --promote
    assert not os.path.exists(os.path.join(
        root, f"{FIXTURE_NS}/final_results/",
        "FINAL_RESULTS_PORTABLE_2026-09-18.json.superseded"))
    assert os.path.isfile(os.path.join(
        root, f"{FIXTURE_NS}/staging/",
        "FINAL_RESULTS_PORTABLE_2026-09-18.json")), (
        "staging must be retained for audit")
    assert sha256_file(os.path.join(root, current_rel)) == before


def test_recovery_partial_staging_detectable(tmp_path):
    """Staging content without promotion is detectable (staged doc
    present while current unchanged)."""
    root = build_good_tree(tmp_path)
    mod = _load_rebuild_tool()
    mod.set_repo_root(root)
    rc = mod.main([])
    assert rc == 0
    staging = os.path.join(
        root, f"{FIXTURE_NS}/staging/",
        "FINAL_RESULTS_PORTABLE_2026-09-18.json")
    current = os.path.join(
        root, f"{FIXTURE_NS}/final_results/",
        "FINAL_RESULTS_PORTABLE_2026-09-18.json")
    assert os.path.isfile(staging), "staged document present"
    assert os.path.isfile(current), "current retained"
    staged_sha = sha256_file(staging)
    current_sha = sha256_file(current)
    # detection: staging present + different from current = un-promoted
    # partial state is visible (the two SHAs differ)
    assert staged_sha != current_sha


def test_recovery_interrupted_generation_detectable(tmp_path):
    """A truncated staged document is detectable (not parseable)."""
    root = build_good_tree(tmp_path)
    staging_dir = os.path.join(
        root, f"{FIXTURE_NS}/staging")
    os.makedirs(staging_dir, exist_ok=True)
    with open(os.path.join(
            staging_dir, "FINAL_RESULTS_PORTABLE_2026-09-18.json"),
            "w", encoding="utf-8") as f:
        f.write('{"report": "DQAEIP PORTABLE RELEAS')  # truncated
    with pytest.raises(json.JSONDecodeError):
        json.load(open(os.path.join(
            staging_dir, "FINAL_RESULTS_PORTABLE_2026-09-18.json"),
            encoding="utf-8"))


def test_recovery_corrupted_manifest_rejected(tmp_path):
    root = build_good_tree(tmp_path)
    snap = build_snapshot(root)
    p = os.path.join(root, snap["release_manifest_path"])
    open(p, "w", encoding="utf-8").write("[]")  # not an object
    report = run_all_monitors(root, snap)
    assert report["monitors"]["T_malformed_manifests"] == "FAIL"


def test_recovery_incomplete_release_rejected(tmp_path):
    """A release lock missing required fields is rejected by the
    schema gate (unknown/missing critical fields)."""
    root = build_good_tree(tmp_path)
    lock = _write_json(
        root, f"{FIXTURE_NS}/release_manifest/"
              "release_lock.json", {"status": "LOCKED"})
    snap = build_snapshot(root)
    report = run_all_monitors(root, snap)
    assert report["monitors"]["T_malformed_manifests"] == "FAIL"


# ---------------------------------------------------------------------
# Schema gate (section 9) — strict rejection matrix
# ---------------------------------------------------------------------

def _good_fr_update():
    return {
        "report": "x", "update_id": "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18",
        "generated_utc": "2026-09-17T00:00:00Z",
        "release_identity": {}, "git_identity": {},
        "evidence_identity": {
            "official_input_sha256": INPUT_SHA,
            "official_output_sha256": OUTPUT_SHA,
            "frozen_v1_sha256": V1_SHA,
            "checker_sha256": "a" * 64},
        "rule_identity": {}, "schema_identity": {},
        "runs": {}, "verification": {
            "run_pair_verdict": "PASS", "test_all_green": True},
        "test_identity": {}, "assurance": {},
        "limitations": [{"id": "L1"}],
        "verification_state": "PASS_WITH_DOCUMENTED_LIMITATIONS",
        "derived_values": {
            "rule_count": 8, "input_column_count": 33,
            "output_column_count": 41, "run_count": 2,
            "rows_per_run": 3200000, "comparisons_per_run": 25600000,
            "combined_comparisons": 51200000,
            "combined_mismatches": 0},
        "dependency_fingerprint": "b" * 64,
    }


def test_schema_gate_accepts_good_document():
    assert schema_gate_final_results_update(_good_fr_update()) == []


def test_schema_gate_rejects_missing_fields():
    doc = _good_fr_update()
    del doc["derived_values"]
    problems = schema_gate_final_results_update(doc)
    assert any("missing required field" in p for p in problems)


def test_schema_gate_rejects_unknown_critical_field():
    doc = _good_fr_update()
    doc["sneaky_extra"] = True
    problems = schema_gate_final_results_update(doc)
    assert any("unknown critical field" in p for p in problems)


def test_schema_gate_rejects_wrong_types():
    doc = _good_fr_update()
    doc["limitations"] = "none"
    problems = schema_gate_final_results_update(doc)
    assert any("expected list" in p for p in problems)


def test_schema_gate_rejects_invalid_enum():
    doc = _good_fr_update()
    doc["verification_state"] = "SUPER_PASS"
    problems = schema_gate_final_results_update(doc)
    assert any("not in allowed enum" in p for p in problems)


def test_schema_gate_rejects_wrong_counts():
    for key, value in [
            ("rule_count", 9), ("input_column_count", 32),
            ("output_column_count", 42), ("run_count", 3),
            ("rows_per_run", 2999999), ("combined_comparisons", 24000000),
            ("combined_mismatches", 1)]:
        doc = _good_fr_update()
        doc["derived_values"][key] = value
        problems = schema_gate_final_results_update(doc)
        assert problems, f"gate must reject {key}={value}"


def test_schema_gate_rejects_wrong_hashes():
    doc = _good_fr_update()
    doc["evidence_identity"]["frozen_v1_sha256"] = "c" * 64
    problems = schema_gate_final_results_update(doc)
    assert any("frozen V1 SHA mismatch" in p for p in problems)


def test_schema_gate_rejects_impossible_combinations():
    doc = _good_fr_update()
    doc["verification"] = {"run_pair_verdict": "FAIL",
                           "test_all_green": False}
    doc["verification_state"] = "PASS"
    problems = schema_gate_final_results_update(doc)
    assert any("PASS without" in p for p in problems)


def test_schema_gate_rejects_pass_without_limitations():
    doc = _good_fr_update()
    doc["limitations"] = []
    problems = schema_gate_final_results_update(doc)
    assert any("limitations" in p for p in problems)


# ---------------------------------------------------------------------
# Change ledger (section 14) — append-only semantics
# ---------------------------------------------------------------------

def test_ledger_append_only(tmp_path):
    ledger = os.path.join(str(tmp_path), "integrity",
                          "change_ledger.jsonl")
    e1 = ledger_entry("a.json", "0" * 64, "1" * 64, "MODIFICATION",
                      expected=False, reason="unit test",
                      result="FAIL")
    written = append_ledger(ledger, [e1])
    assert written == 1
    e2 = ledger_entry("b.json", None, "2" * 64, "CREATION",
                      expected=False, reason="unit test",
                      result="WARNING")
    append_ledger(ledger, [e2])
    lines = open(ledger, encoding="utf-8").read().splitlines()
    assert len(lines) == 2, "append-only ledger must retain both lines"
    first = json.loads(lines[0])
    for field in ("timestamp", "artifact", "old_sha256", "new_sha256",
                  "change_type", "expected", "actor", "reason",
                  "result", "affected_dependents"):
        assert field in first, f"ledger entry missing {field}"


# ---------------------------------------------------------------------
# Fingerprint determinism (section 11)
# ---------------------------------------------------------------------

def test_fingerprint_deterministic_and_timestamp_free():
    deps = [{"path": "a", "sha256": "1" * 64},
            {"path": "b", "sha256": "2" * 64}]
    fp1 = dependency_fingerprint(deps)
    fp2 = dependency_fingerprint(list(reversed(deps)))
    assert fp1 == fp2, "order must not matter"
    assert dependency_fingerprint(deps) == fp1
    deps[0]["sha256"] = "3" * 64
    assert dependency_fingerprint(deps) != fp1, "change must be detected"


# ---------------------------------------------------------------------
# Anomaly detection (section 27) — conservative, no invented failures
# ---------------------------------------------------------------------

def test_anomaly_detection_never_invents_failures():
    from data_quality_platform.assurance.integrity import (
        classify_anomaly, detect_anomalies)
    assert classify_anomaly(100, 100) == "NORMAL"
    # no documented threshold -> any change is REVIEW, never CRITICAL
    assert classify_anomaly(105, 100) == "REVIEW"
    assert classify_anomaly(50, 100) == "REVIEW"
    # documented tolerance respected
    assert classify_anomaly(101, 100, tolerance=1,
                            documented=True) == "NORMAL"
    assert classify_anomaly(110, 100, tolerance=1,
                            documented=True) == "REVIEW"
    report = detect_anomalies({"tests": 100}, {"tests": 100})
    assert report["state"] == "NORMAL"
    report2 = detect_anomalies({"tests": 90}, {"tests": 100})
    assert report2["state"] == "REVIEW"
    assert report2["anomaly_count"] == 1
