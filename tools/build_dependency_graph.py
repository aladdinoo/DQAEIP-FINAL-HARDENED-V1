#!/usr/bin/env python3
"""DQAEIP FINAL PORTABLE EVIDENCE & RELEASE HARDENING — Phase 9.

Evidence dependency graph for the portable release (task section 10).

Records, for every derived artifact, its direct dependencies,
dependency hashes, dependency fingerprint, generator, generator
SHA-256, generation time, and authority level.

    Frozen V1 ────────┐
    Run 1 ────────────┤
    Run 2 ────────────┤
    Checker ──────────┤
                        ▼
                  Verified batteries
                        ▼
                  FINAL_RESULTS (portable)
                        ▼
        Claim graph / identity registry / evidence model
                        ▼
              README + root release documents

RUNTIME APPARATUS EXCLUSIONS (documented, by design — same
discipline as the prior release round): the release manifest, the
release lock, the integrity baseline snapshot, the freshness report,
the monitor report, the drift report, the ZIP records, the
self-contained verification record and the observability view are
POST-GRAPH runtime outputs. They are verified by RE-EXECUTION
(monitor re-run, clean-room extraction) and by the snapshot's pins —
not by freshness edges, because they are generated after the graph
finalizes (a report cannot pin its own pre-measurement state).

The graph fingerprint is deterministic and timestamp-free (SHA-256
over canonical (artifact, dependency_fingerprint) pairs).
"""

import argparse
import json
import os
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance.integrity import (  # noqa: E402
    OFFICIAL_CHECKER, OFFICIAL_EVIDENCE_DIR, OFFICIAL_VERIFIER,
    FROZEN_V1_SOURCE, canonical_json, dependency_fingerprint,
    directory_fingerprint, sha256_file)

NS = "evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18"
OUT_PATH = os.path.join(REPO_ROOT, NS, "dependency_graph",
                        "dependency_graph.json")
FR = f"{NS}/final_results/FINAL_RESULTS_PORTABLE_2026-09-18.json"

GENERATORS = {
    "run_pair_verification": {
        "generator": "scripts/verify_run_pair.py"},
    "test_summary": {
        "generator": "scripts/capture_test_summary.py"},
    "business_mutation": {
        "generator": "scripts/mutation_testing.py"},
    "assurance_mutation": {
        "generator": "scripts/assurance_mutation.py"},
    "limitation_registry": {
        "generator": "scripts/build_release_evidence_model.py"},
    "final_results": {
        "generator": "tools/portable_final_results_rebuild.py"},
    "claim_graph": {
        "generator": "tools/build_claim_graph.py"},
    "artifact_identity_registry": {
        "generator": "tools/build_artifact_identity_registry.py"},
    "schema_compatibility": {
        "generator": "tools/build_schema_compatibility_report.py"},
    "readme": {
        "generator": "scripts/build_release_evidence_model.py"},
    "integrity_snapshot": {
        "generator": "tools/build_baseline_snapshot.py"},
    "integrity_monitor": {
        "generator": "tools/integrity_monitor.py"},
    "drift_detector": {
        "generator": "tools/drift_detector.py"},
    "absolute_path_gate": {
        "generator": "tools/absolute_path_release_gate.py"},
    "tamper_matrix": {
        "generator": "tools/run_tamper_matrix.py"},
    "evidence_mutation_matrix": {
        "generator": "tools/run_evidence_mutation_matrix.py"},
    "path_inventory": {
        "generator": "tools/absolute_path_forensics.py"},
    "portable_normalization": {
        "generator": "tools/normalize_portable_evidence.py"},
}


def git_head():
    return subprocess.run(
        ["git", "-C", REPO_ROOT, "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False).stdout.strip()


def dep(path, role):
    abs_p = os.path.join(REPO_ROOT, path)
    if os.path.isdir(abs_p):
        return {"path": path, "role": role,
                "sha256": directory_fingerprint(abs_p)}
    return {"path": path, "role": role,
            "sha256": sha256_file(abs_p) if os.path.isfile(abs_p)
            else None}


def node(artifact, authority, generator_key, dependencies, note=""):
    gen = GENERATORS.get(generator_key, {})
    gen_path = gen.get("generator")
    gen_sha = None
    if gen_path:
        abs_g = os.path.join(REPO_ROOT, gen_path)
        if os.path.isfile(abs_g):
            gen_sha = sha256_file(abs_g)
    present = [d for d in dependencies if d["sha256"]]
    missing = [d["path"] for d in dependencies if not d["sha256"]]
    fp = dependency_fingerprint(present)
    return {
        "artifact": artifact,
        "authority_level": authority,
        "generator": gen_path,
        "generator_sha256": gen_sha,
        "generation_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                       time.gmtime()),
        "dependencies": dependencies,
        "missing_dependencies": missing,
        "dependency_fingerprint": fp,
        "note": note,
    }


def build_graph():
    v1 = dep(FROZEN_V1_SOURCE, "frozen V1 rule source")
    checker = dep(OFFICIAL_CHECKER, "official fail-closed checker")
    verifier = dep(OFFICIAL_VERIFIER, "run-pair verifier")
    run1 = dep(f"{OFFICIAL_EVIDENCE_DIR}/pass1_result.json",
               "official Run 1 evidence")
    run2 = dep(f"{OFFICIAL_EVIDENCE_DIR}/pass2_result.json",
               "official Run 2 evidence")
    fr3m = dep(f"{OFFICIAL_EVIDENCE_DIR}/FINAL_RESULTS.json",
               "official run-pair record")
    run_pair = dep("evidence/rebuild_verification/"
                   "run_pair_verification.json", "run-pair verdict")
    test_summary = dep("evidence/rebuild_verification/"
                       "test_summary.json", "test identity")
    business_mutation = dep("evidence/mutation_testing/"
                            "mutation_results.json", "business mutation")
    assurance_mutation = dep("evidence/release/assurance_mutation.json",
                             "assurance mutation")
    limitations = dep("evidence/release/limitation_registry.json",
                      "limitations")
    # NOTE: the release-gate report and the integrity monitor report
    # are regenerated by every gate/monitor run BY DESIGN. They are
    # value-anchored claims in the claim graph (never hash-pinned) and
    # are NOT freshness dependencies here — their stability is proven
    # by re-execution (clean-room verification) and the manifest pin
    # of the terminal gate report.
    tamper_matrix = dep(f"{NS}/security/tamper_matrix.json",
                        "artifact tamper matrix")
    evidence_mutations = dep(f"{NS}/mutation_testing/"
                             "evidence_mutation_matrix.json",
                             "evidence mutation matrix")
    path_gate = dep(f"{NS}/release_gate/"
                    "absolute_path_gate_report.json",
                    "absolute-path gate report")

    # NOTE (finalize-pass ordering): the claim graph, the artifact
    # identity registry and the schema compatibility report are
    # POST-MANIFEST finalize outputs (the claim graph value-anchors
    # the integrity monitor report, which is generated after the
    # snapshot; the manifest is finalized before the snapshot). They
    # are hash-pinned by the ZIP member manifest and validated by the
    # clean-room extraction verification.
    nodes = [
        node(FROZEN_V1_SOURCE, "AUTHORITATIVE", None, [],
             "frozen V1 rule source (identity anchor)"),
        node(f"{OFFICIAL_EVIDENCE_DIR}/pass1_result.json",
             "AUTHORITATIVE", None, [],
             "official Run 1 (never regenerate; never modify)"),
        node(f"{OFFICIAL_EVIDENCE_DIR}/pass2_result.json",
             "AUTHORITATIVE", None, [],
             "official Run 2 (never regenerate; never modify)"),
        node(OFFICIAL_CHECKER, "AUTHORITATIVE", None, [],
             "checker identity anchored in run evidence"),
        node("evidence/rebuild_verification/run_pair_verification.json",
             "VERIFIED", "run_pair_verification",
             [v1, checker, verifier, run1, run2, fr3m],
             "95-check fail-closed verification of the official pair"),
        node("evidence/rebuild_verification/test_summary.json",
             "VERIFIED", "test_summary",
             [dep("tests", "full test tree")],
             "actual collected/passed/skipped counts; never fabricated"),
        node("evidence/mutation_testing/mutation_results.json",
             "VERIFIED", "business_mutation",
             [v1, dep("data_quality_platform/validation/engine.py",
                      "deterministic engine")],
             "17/17 business mutants detected; source restored"),
        node("evidence/release/assurance_mutation.json",
             "VERIFIED", "assurance_mutation",
             [v1, dep("data_quality_platform/assurance/claims.py",
                      "claim verification engine")],
             "false-PASS prevention battery results"),
        node("evidence/release/limitation_registry.json",
             "VERIFIED", "limitation_registry", [],
             "machine-readable documented limitations"),
        node(f"{NS}/security/tamper_matrix.json",
             "VERIFIED", "tamper_matrix",
             [v1, dep("tests/assurance/test_integrity_monitoring.py",
                      "fixture definitions")],
             "15/15 artifact tamper scenarios detected (isolated "
             "fixtures only)"),
        node(f"{NS}/mutation_testing/evidence_mutation_matrix.json",
             "VERIFIED", "evidence_mutation_matrix",
             [v1, dep("data_quality_platform/assurance/"
                      "evidence_schema.py", "schema validators"),
              dep("data_quality_platform/assurance/claim_graph.py",
                  "claim verification engine")],
             "16/16 evidence-layer controlled mutations rejected "
             "(isolated fixtures only)"),
        node(f"{NS}/release_gate/absolute_path_gate_report.json",
             "VERIFIED", "absolute_path_gate",
             [dep("data_quality_platform/assurance/"
                  "portable_evidence.py", "shared detectors"),
              dep(f"{NS}/release_gate/"
                  "absolute_path_gate_exceptions.json",
                  "narrow exception registry")],
             "portable evidence machine-path gate (fail-closed)"),
        node(FR, "DERIVED", "final_results",
             [v1, fr3m, run_pair, test_summary, business_mutation,
              assurance_mutation, limitations],
             "two-phase rebuild; promoted only after the schema gate "
             "passed"),
        node(f"{NS}/claim_graph/claim_graph.json",
             "DERIVED", "claim_graph",
             [dep(FR, "final results"),
              dep(fr3m["path"], "official run-pair record"),
              dep(run_pair["path"], "run-pair verdict"),
              dep(tamper_matrix["path"], "tamper matrix"),
              dep(evidence_mutations["path"], "evidence mutations"),
              dep(path_gate["path"], "path gate report")],
             "claim→evidence→hash provenance graph; monitor-report "
             "and release-gate-report claims are VALUE-anchored "
             "(volatile runtime outputs, never hash-pinned)"),
        node(f"{NS}/artifact_identity/artifact_identity_registry.json",
             "DERIVED", "artifact_identity_registry",
             [dep(FR, "final results"),
              dep(f"{NS}/release_gate/"
                  "absolute_path_gate_report.json",
                  "path gate report"),
              dep("evidence/release/release_evidence_model.json",
                  "canonical evidence model")],
             "cryptographic artifact identity contract (also "
             "registers the claim graph and mutation matrices, "
             "built in the same finalize pass — hash-pinned by the "
             "ZIP member manifest and validated by the clean-room "
             "extraction)"),
        node(f"{NS}/schema_versioning/"
             "SCHEMA_COMPATIBILITY_REPORT.json",
             "DERIVED", "schema_compatibility",
             [dep(FR, "final results"),
              dep("evidence/release/release_evidence_model.json",
                  "canonical evidence model")],
             "schema identity classification of current artifacts "
             "(classifies the claim graph and registry built in the "
             "same finalize pass)"),
        node(f"{NS}/portable_paths/"
             "PORTABLE_EVIDENCE_NORMALIZATION.json",
             "DERIVED", "portable_normalization",
             [dep(fr3m["path"], "official run-pair record"),
              dep(f"{NS}/path_forensics/"
                  "ABSOLUTE_PATH_INVENTORY.json", "phase-1 inventory")],
             "policy-A normalization summary; originals preserved "
             "byte-exact"),
        node("evidence/release/release_evidence_model.json",
             "DERIVED", "limitation_registry",
             [dep(FR, "final results (portable)"),
              dep("FINAL_RESULTS.json", "final results (root)")],
             "canonical evidence model (regenerated at release "
             "identity)"),
        node("README.md", "DERIVED", "readme",
             [dep("FINAL_RESULTS.json", "final results (root)"),
              dep(FR, "final results (portable)")],
             "presentation only; never a source of truth"),
        node("tools/integrity_monitor.py", "TOOL", "integrity_monitor",
             [],
             "continuous integrity monitor (A-T); leaf tool — the "
             "snapshot is a runtime input, not a build dependency"),
        node("tools/drift_detector.py", "TOOL", "drift_detector",
             [],
             "ten-class drift detector; leaf tool"),
        node("tools/absolute_path_release_gate.py", "TOOL",
             "absolute_path_gate",
             [],
             "portable-evidence path gate; leaf tool"),
    ]
    return nodes


def main():
    parser = argparse.ArgumentParser(
        description="Build the evidence dependency graph")
    parser.add_argument("--out", default=OUT_PATH)
    args = parser.parse_args()

    nodes = build_graph()

    import hashlib
    pairs = sorted((n["artifact"], n["dependency_fingerprint"])
                  for n in nodes)
    h = hashlib.sha256()
    for artifact, fp in pairs:
        h.update(artifact.encode() + b"\x00" + fp.encode())
    graph_fp = h.hexdigest()

    dependents = {}
    for n in nodes:
        for d in n["dependencies"]:
            dependents.setdefault(d["path"], []).append(n["artifact"])

    missing = [d for n in nodes for d in n["missing_dependencies"]]

    doc = {
        "report": "DQAEIP portable release evidence dependency graph",
        "schema": {"name": "dqaeip.dependency_graph", "version": "1.0"},
        "release_id": "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                       time.gmtime()),
        "git_head": git_head(),
        "node_count": len(nodes),
        "nodes": nodes,
        "dependents_map": dependents,
        "graph_fingerprint": graph_fp,
        "missing_dependencies": missing,
        "runtime_apparatus_exclusions": {
            "release_manifest": "generated after the graph (the "
                                "manifest lists the graph)",
            "release_lock": "generated after the manifest",
            "integrity_snapshot": "pins the graph fingerprint — "
                                  "listing it here would be circular",
            "freshness_report": "post-snapshot runtime evaluation",
            "monitor_report": "regenerated on every verification run "
                              "by design",
            "drift_report": "runtime output",
            "zip_records": "post-archive runtime records",
            "self_contained_verification": "post-archive runtime record",
            "release_identity": "pinned by the manifest",
            "policy": "runtime apparatus is verified by RE-EXECUTION "
                      "(monitor re-run, clean-room extraction) and by "
                      "the snapshot pins — never by freshness edges "
                      "(a report cannot pin its own pre-measurement "
                      "state)",
        },
        "fingerprint_policy": (
            "deterministic; timestamps, durations, temporary paths and "
            "environment noise are excluded; any dependency change "
            "changes the fingerprint (DRIFT DETECTED)"),
    }

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"dependency graph written: "
          f"{os.path.relpath(args.out, REPO_ROOT)}")
    print(f"  nodes: {len(nodes)}")
    print(f"  graph fingerprint: {graph_fp}")
    if missing:
        print(f"  MISSING DEPENDENCIES: {missing}")
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
