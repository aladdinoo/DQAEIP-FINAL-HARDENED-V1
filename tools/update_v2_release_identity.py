#!/usr/bin/env python3
"""DQAEIP FINAL PORTABLE EVIDENCE UPDATE V2 (2026-09-18) — release
identity (pre-ZIP terminal authority).

The machine-readable release identity pinning the UPDATE-V2 layer:

    release_id / update_id / git_commit / tree identity
    final_results_sha256  (the portable flagship derived copy)
    manifest_sha256 / registry_sha256 / graph_sha256
    dependency_fingerprint (content fingerprint of the portability
                            layer: every source + derived pair)
    verification_state    (path gate, tests, security, claims — all
                           read LIVE from the artifacts that own them)

The zip_sha256 is necessarily absent here (an archive cannot embed
its own hash); the authoritative ZIP SHA lives in the repo-side ZIP
record and the .sha256 sidecar, per the established pattern.
"""

import hashlib
import json
import os
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

UPDATE_ID = "DQAEIP-FINAL-UPDATE-V2-2026-09-18"
NS = "evidence/FINAL_PORTABLE_UPDATE_V2_2026-09-18"
OUT = os.path.join(NS, "release_manifest",
                   "release_identity_UPDATE-V2.json")

FLAGSHIP = os.path.join(NS, "portable_evidence",
                        "FINAL_3M_VALIDATION_RESULTS.UPDATE-V2.portable.json")
MANIFEST = os.path.join(NS, "release_manifest",
                        "RELEASE_MANIFEST.UPDATE-V2.json")
REGISTRY = os.path.join(NS, "artifact_identity",
                        "artifact_identity_registry.UPDATE-V2.json")
GRAPH = os.path.join(NS, "claim_graph",
                     "claim_evidence_hash_graph.UPDATE-V2.json")
SUMMARY = os.path.join(NS, "portable_paths",
                       "UPDATE_V2_NORMALIZATION_SUMMARY.json")
GATE_REP = os.path.join(NS, "release_gate",
                        "absolute_path_gate_report_UPDATE-V2.json")
TEST_RECORD = os.path.join(NS, "tests", "full_suite_UPDATE-V2.json")
SEC_RECORD = os.path.join(NS, "security", "security_scan_UPDATE-V2.json")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(rel):
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def main():
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    head = subprocess.run(["git", "-C", REPO_ROOT, "rev-parse", "HEAD"],
                          capture_output=True, text=True,
                          check=False).stdout.strip()
    tree_id = subprocess.run(
        ["git", "-C", REPO_ROOT, "rev-parse", "HEAD^{tree}"],
        capture_output=True, text=True, check=False).stdout.strip()

    summary = load(SUMMARY)
    gate = load(GATE_REP)
    tests = load(TEST_RECORD)
    sec = load(SEC_RECORD)
    graph = load(GRAPH)

    # fail-closed: the terminal state must actually be PASS
    problems = []
    if gate["verdict"] != "PASS":
        problems.append(f"absolute-path gate: {gate['verdict']}")
    if tests["verdict"] != "PASS":
        problems.append(f"test record: {tests['verdict']}")
    if graph["summary"]["claims_failed"]:
        problems.append(
            f"claim graph failures: {graph['summary']['claims_failed']}")
    sec_sections = {k: v.get("verdict")
                    for k, v in sec["scanner_report"].items()
                    if isinstance(v, dict) and "verdict" in v}
    for must_pass in ("credential_scan_result", "path_leakage_result",
                      "artifact_inventory_result",
                      "environment_leakage_result"):
        if sec_sections.get(must_pass) != "PASS":
            problems.append(f"security section {must_pass}: "
                            f"{sec_sections.get(must_pass)}")
    if sec_sections.get("fail_closed_behavior_status") != "VERIFIED":
        problems.append("fail-closed behavior not VERIFIED")
    if problems:
        print(f"FATAL: terminal state not PASS: {problems}")
        return 4

    # dependency fingerprint: content fingerprint over every
    # (source, derived) pair of the portability layer
    fp = hashlib.sha256()
    for rec in sorted(summary["sources"], key=lambda r: r["source"]):
        fp.update(rec["source"].encode())
        fp.update(rec["source_sha256"].encode())
        fp.update(rec["derived_portable"].encode())
        fp.update(rec["derived_portable_sha256"].encode())
    dep_fp = fp.hexdigest()

    identity = {
        "report": "DQAEIP FINAL PORTABLE EVIDENCE UPDATE V2 — release "
                  "identity (terminal, pre-ZIP)",
        "schema": {"name": "dqaeip.update_v2.release_identity",
                   "version": "1.0"},
        "release_id": UPDATE_ID,
        "update_id": UPDATE_ID,
        "generated_utc": started,
        "git_commit": head,
        "repository_tree_identity": tree_id,
        "final_results_sha256": sha256_file(
            os.path.join(REPO_ROOT, FLAGSHIP)),
        "final_results_portable": FLAGSHIP,
        "final_results_source_authoritative": (
            "evidence/final_3m_validation_2026-09-15/FINAL_RESULTS.json"),
        "final_results_source_sha256": summary["sources"][0][
            "source_sha256"] if summary["sources"][0]["source"] == (
            "evidence/final_3m_validation_2026-09-15/FINAL_RESULTS.json"
        ) else next(
            r["source_sha256"] for r in summary["sources"]
            if r["source"] == ("evidence/final_3m_validation_2026-09-15/"
                               "FINAL_RESULTS.json")),
        "manifest_sha256": sha256_file(os.path.join(REPO_ROOT, MANIFEST)),
        "artifact_registry_sha256": sha256_file(
            os.path.join(REPO_ROOT, REGISTRY)),
        "claim_graph_sha256": sha256_file(os.path.join(REPO_ROOT, GRAPH)),
        "dependency_fingerprint": dep_fp,
        "zip_sha256": None,
        "zip_sha256_note": "an archive cannot embed its own hash; the "
                           "authoritative ZIP SHA-256 is recorded "
                           "repo-side in the ZIP record "
                           "(release_manifest/zip_record_UPDATE-V2.json) "
                           "and the .sha256 sidecar beside the archive",
        "verification_state": {
            "absolute_path_gate": {
                "verdict": gate["verdict"],
                "violations": gate["violation_count"],
                "files_scanned": gate["scope"]["scanned_file_count"],
                "exceptions_granted": len(
                    gate["exception_registry"]["granted"]),
                "report": GATE_REP,
            },
            "tests": {
                "verdict": tests["verdict"],
                "counts": tests["counts"],
                "record": TEST_RECORD,
            },
            "security_pii": {
                "sections": sec_sections,
                "record": SEC_RECORD,
            },
            "claim_graph": graph["summary"],
            "official_3m_rerun": False,
            "business_rule_changes": "NONE",
            "authoritative_evidence_modified": "NO",
        },
        "verdict": "PASS_WITH_DOCUMENTED_LIMITATIONS",
        "verdict_note": "honest terminal verdict; no production-ready / "
                        "enterprise-ready / scalability claims",
    }

    out = os.path.join(REPO_ROOT, OUT)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(identity, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"release identity written: {OUT}")
    print(f"  git_commit:           {head}")
    print(f"  final_results (portable flagship) SHA: "
          f"{identity['final_results_sha256'][:16]}...")
    print(f"  manifest SHA:         "
          f"{identity['manifest_sha256'][:16]}...")
    print(f"  dependency fp:        {dep_fp[:16]}...")
    print(f"  verification state:   all terminal gates PASS (see report)")
    print(f"  verdict:              {identity['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
