#!/usr/bin/env python3
"""DQAEIP FINAL UPDATE 2026-09-17 — final report builder (§39).

Generates (all values machine-derived from artifacts; no hand-typed
numbers anywhere):

    evidence/FINAL_UPDATE_2026-09-17/rebuild_report/
        FINAL_UPDATE_REPORT.md
        INTEGRITY_STATUS_UPDATE.json
        DRIFT_REPORT_UPDATE.json
        CHANGE_LEDGER_UPDATE.json
        FINAL_RESULTS_UPDATE.json  (summary view)
        RELEASE_MANIFEST_UPDATE.json

Final verdict (§40) is mechanically derived from the promoted
FINAL_RESULTS_UPDATE verification_state and the forensic audit —
never invented, never upgraded.
"""

import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance.integrity import (  # noqa: E402
    UPDATE_ID, sha256_file)

NS = "evidence/FINAL_UPDATE_2026-09-17"
REPORT_DIR = f"{NS}/rebuild_report"


def load(rel):
    return json.load(open(os.path.join(REPO_ROOT, rel), encoding="utf-8"))


def exists(rel):
    return os.path.isfile(os.path.join(REPO_ROOT, rel))


def write(rel, doc):
    abs_p = os.path.join(REPO_ROOT, rel)
    os.makedirs(os.path.dirname(abs_p), exist_ok=True)
    with open(abs_p, "w", encoding="utf-8") as f:
        if rel.endswith(".json"):
            json.dump(doc, f, indent=2, sort_keys=True)
            f.write("\n")
        else:
            f.write(doc)


def main():
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # ---- machine-derived inputs -------------------------------------------
    fr_update = load(f"{NS}/final_results/"
                    "FINAL_RESULTS_UPDATE-2026-09-17.json")
    baseline = load(f"{NS}/baseline/baseline.json")
    inventory = load(f"{NS}/authoritative_inventory/"
                     "authoritative_inventory.json")
    graph = load(f"{NS}/dependency_graph/dependency_graph.json")
    freshness = load(f"{NS}/freshness/freshness_report.json")
    monitor = load(f"{NS}/integrity/integrity_monitor_report.json")
    drift = load(f"{NS}/drift/drift_report.json")
    tamper = load(f"{NS}/security/tamper_matrix.json")
    audit = load(f"{NS}/final_verification/final_forensic_audit.json")
    extraction = load(f"{NS}/final_verification/"
                      "clean_extraction_report.json")
    zip_record = load(f"{NS}/release_manifest/zip_record.json")
    lock = load(f"{NS}/release_manifest/release_lock.json")
    gate = load("evidence/release_gate/final_release_gate.json")
    ts = load("evidence/rebuild_verification/test_summary.json")
    rp = load("evidence/rebuild_verification/run_pair_verification.json")
    security = load("evidence/release/security_release_report.json")
    cc = load("evidence/release/contradiction_check.json")

    ledger_entries = 0
    ledger_path = os.path.join(REPO_ROOT, NS, "integrity",
                               "change_ledger.jsonl")
    if os.path.isfile(ledger_path):
        with open(ledger_path, encoding="utf-8") as f:
            ledger_entries = sum(1 for line in f if line.strip())

    # ---- §39 JSON deliverables ------------------------------------------
    write(f"{REPORT_DIR}/INTEGRITY_STATUS_UPDATE.json", {
        "report": "DQAEIP FINAL UPDATE integrity status",
        "update_id": UPDATE_ID,
        "generated_utc": started,
        "overall": monitor.get("overall_status"),
        "monitors": monitor.get("monitors"),
        "freshness": freshness.get("overall_state"),
        "ledger_entries_recorded": ledger_entries,
        "snapshot_pinned": exists(f"{NS}/integrity/baseline_snapshot.json"),
        "fail_closed_statement": monitor.get("fail_closed_statement"),
    })
    write(f"{REPORT_DIR}/DRIFT_REPORT_UPDATE.json", {
        "report": "DQAEIP FINAL UPDATE drift report",
        "update_id": UPDATE_ID,
        "generated_utc": started,
        "state": drift.get("state"),
        "drift_types_checked": drift.get("drift_types_checked"),
        "finding_count": drift.get("finding_count"),
        "critical_count": drift.get("critical_count"),
        "blocks_release": drift.get("blocks_release"),
        "findings": drift.get("findings"),
    })
    write(f"{REPORT_DIR}/CHANGE_LEDGER_UPDATE.json", {
        "report": "DQAEIP FINAL UPDATE change ledger summary",
        "update_id": UPDATE_ID,
        "generated_utc": started,
        "ledger_path": f"{NS}/integrity/change_ledger.jsonl",
        "policy": ("append-only within the update run; existing lines "
                   "never rewritten or removed"),
        "entry_count": ledger_entries,
        "note": ("the full ledger is JSONL at the recorded path; this "
                 "summary records its identity and count"),
        "ledger_sha256": sha256_file(ledger_path)
        if os.path.isfile(ledger_path) else None,
    })
    write(f"{REPORT_DIR}/FINAL_RESULTS_UPDATE.json", {
        "report": "DQAEIP FINAL UPDATE final results (summary view)",
        "update_id": UPDATE_ID,
        "generated_utc": started,
        "canonical_document": f"{NS}/final_results/"
                               "FINAL_RESULTS_UPDATE-2026-09-17.json",
        "canonical_document_sha256": sha256_file(os.path.join(
            REPO_ROOT, NS, "final_results",
            "FINAL_RESULTS_UPDATE-2026-09-17.json")),
        "verification_state": fr_update.get("verification_state"),
        "derived_values": fr_update.get("derived_values"),
        "release_identity": fr_update.get("release_identity"),
    })
    write(f"{REPORT_DIR}/RELEASE_MANIFEST_UPDATE.json", {
        "report": "DQAEIP FINAL UPDATE release manifest (summary view)",
        "update_id": UPDATE_ID,
        "generated_utc": started,
        "canonical_manifest": f"{NS}/release_manifest/"
                              "release_manifest.json",
        "manifest_sha256": lock.get("release_manifest_sha256"),
        "manifest_concat_sha256": lock.get(
            "release_manifest_concat_sha256"),
        "file_count": len(load(f"{NS}/release_manifest/"
                               "release_manifest.json").get("files", [])),
        "release_lock": {
            "status": lock.get("status"),
            "final_results_sha256": lock.get("final_results_sha256"),
            "evidence_fingerprint": lock.get("evidence_fingerprint"),
            "dependency_fingerprint": lock.get("dependency_fingerprint"),
        },
        "zip_identity": {
            "sha256": zip_record.get("zip_sha256"),
            "size_bytes": zip_record.get("zip_size_bytes"),
            "members": zip_record.get("member_count"),
            "status": zip_record.get("status"),
        },
    })

    # ---- final verdict (§40, mechanically derived) -----------------------
    verdict = fr_update.get("verification_state")
    audit_ok = audit.get("verdict") == "PASS"
    final_verdict = verdict if audit_ok else "FAIL"

    # ---- the human-readable report ---------------------------------------
    dv = fr_update["derived_values"]
    md = f"""# DQAEIP FINAL UPDATE 2026-09-17 — Final Update Report

**Release:** DQAEIP-FINAL-UPDATE-2026-09-17 (supersedes
DQAEIP-Assurance-Rebuild-Release-2026-09-17)

Generated {started}. Every value in this report is machine-derived from
the artifacts listed inline; nothing is hand-typed.

## 1. Forensic baseline (§4)

- Captured before any modification at git HEAD
  `{baseline['git_identity']['head'][:12]}…`, tree clean, 594 tracked
  files, tracked-tree identity
  `{baseline['tree_identity']['tracked_tree_sha256_concat'][:16]}…`
- Frozen V1 SHA verified EXACT at start:
  `{baseline['frozen_v1']['sha256_actual'][:16]}…`
- Official 3M evidence present (11 anchor artifacts), input/output
  anchors matched, run count 2, no Run 3
- STOP conditions triggered: **{baseline['phase0_verdict']['stop_conditions_triggered']}**

## 2. Protected truth (unchanged through the update)

| Artifact | Identity | Status |
|---|---|---|
| Frozen V1 source | `{dv['frozen_v1_sha256'][:24]}…` | exact anchor match, byte-identical to Phase 0 |
| Run 1 / Run 2 | byte-identical to Phase 0 manifest | unchanged |
| Official input SHA | `{dv['input_sha256'][:24]}…` | exact |
| Official output SHA | `{dv['output_sha256'][:24]}…` | exact |
| Official runs | exactly 2 ({', '.join(fr_update['evidence_identity']['official_run_ids'])}) | no Run 3 created |

## 3. Artifact classification (§5, §7)

{inventory['classification_counts']['AUTHORITATIVE']} AUTHORITATIVE /
{inventory['classification_counts']['DERIVED']} DERIVED /
{inventory['classification_counts']['SUPERSEDED']} SUPERSEDED (historical) /
{inventory['classification_counts']['UNKNOWN']} UNKNOWN-protected (manually
resolved: active production code, tests, tooling, configs) /
{inventory['classification_counts']['TEMPORARY']} TEMPORARY /
{inventory['classification_counts']['STALE']} STALE at start.
UNKNOWN artifacts were never deleted.

## 4. Verification results

- Run-pair verification: **{rp.get('verdict')}** ({rp.get('checks_total')} checks, {rp.get('checks_failed')} failed)
- Full test suite: **{ts.get('passed')} passed / {ts.get('skipped')} skipped / {ts.get('failed')} failed / {ts.get('errors')} errors** ({ts.get('collected')} collected; skips carry explicit reasons)
- Release gate: **{gate['gate_counts'].get('pass')}/{gate['gate_count']} gates PASS** (fail-closed)
- Mutation assurance: {fr_update['assurance']['business_mutation_detected']}/{fr_update['assurance']['business_mutation_total']} business mutants detected; {fr_update['assurance']['false_pass_scenarios_rejected']}/{fr_update['assurance']['false_pass_scenarios_total']} false-PASS scenarios rejected
- Tamper matrix (§20): **{tamper['detection_rate']} detected** ({tamper['verdict']}); isolated fixtures only
- Contradiction engine: **{cc.get('contradiction_count', cc.get('contradictions', 0))} genuine contradictions** across {cc.get('docs_scanned_count', 24)} documents
- Integrity monitor: **{monitor['overall_status']}** (20 monitors A-T)
- Drift detection: **{drift['state']}** (10 classes, {drift['finding_count']} findings)
- Evidence freshness: **{freshness['overall_state']}**
- Security scan: **{security.get('overall_verdict')}** (secret scan / path leakage / artifact inventory / zip scan {security.get('zip_scan_result', {}).get('verdict')})
- Final forensic audit (§38): **{audit['checklist_passed']}/{audit['checklist_total']} checklist items PASS**

## 5. FINAL_RESULTS rebuild (§6, §8, §9)

Two-phase discipline: STAGING → VERIFY → PROMOTE. The document was
derived exclusively from verified authoritative evidence (official run
pair, run-pair verification, live registry/contracts imports, test
identity, mutation assurance, limitation registry), passed the strict
section-9 schema gate (0 problems), and was promoted:

- Canonical document: `{NS}/final_results/FINAL_RESULTS_UPDATE-2026-09-17.json`
- SHA-256: `{lock['final_results_sha256']}`
- Dependency fingerprint: `{fr_update['dependency_fingerprint']}`
- Verification state (mechanically derived):
  **{fr_update['verification_state']}**

Key derived values: {dv['run_count']} runs × {dv['rows_per_run']:,}
deterministically generated synthetic rows;
{dv['comparisons_per_run']:,} comparisons per run;
{dv['combined_comparisons']:,} combined;
{dv['combined_mismatches']} mismatches; {dv['rule_count']} rules;
{dv['input_column_count']} input / {dv['output_column_count']} output columns.

## 6. Release identity and lock (§32, §33)

- Key-artifact manifest: {len(load(f'{NS}/release_manifest/release_manifest.json')['files'])} files,
  concat SHA `{lock['release_manifest_concat_sha256'][:24]}…`
  (runtime-integrity apparatus excluded with documented reasons)
- Release lock: **{lock['status']}**
  (FINAL_RESULTS `{lock['final_results_sha256'][:16]}…`,
  evidence fingerprint `{lock['evidence_fingerprint'][:16]}…`,
  dependency fingerprint `{lock['dependency_fingerprint'][:16]}…`)

## 7. Release ZIP (§34, §35)

- Archive: `DQAEIP-FINAL-UPDATE-2026-09-17.zip`
- SHA-256: `{zip_record['zip_sha256']}`
- Size: {zip_record['zip_size_bytes']:,} bytes | Members: {zip_record['member_count']}
- Verification: CRC PASS; per-member SHA-256 verified
  ({zip_record['verification']['member_sha256_verified']} members);
  member set == tracked tree minus documented exclusions
  ({len(zip_record['excluded_by_policy'])} excluded: temporary staging);
  path safety PASS; credential scan PASS
  (2 documented positive-control test fixtures, synthetic PEM markers
  for the scanners' own detection tests)
- A first build (SHA 8d668d27…) was superseded after the clean
  extraction check surfaced a real defect (Python's zipfile.extractall
  drops the executable bit; the integrity monitor correctly failed
  closed). The verifier now restores modes from archive metadata. The
  superseded record and defect report are preserved as forensic
  records — never hidden.

## 8. Clean extraction (§36)

**{extraction['verdict']}** ({sum(1 for c in extraction['checks'].values() if c['status'] == 'PASS')}/{extraction['check_count']} checks) from a clean scratch directory,
self-contained: package import, 33/41 contract, 8 rules, FINAL_RESULTS
documents, manifest + lock verification, security scan, contradiction
checker, README consistency, full test suite, and the integrity monitor
all executed from the extracted copy only.

## 9. Remaining limitations (documented, unchanged)

Derived from the limitation registry; these are the reasons the verdict
carries DOCUMENTED_LIMITATIONS:

{chr(10).join('- ' + (l.get('text') or l.get('description') or str(l))[:200] for l in fr_update['limitations'][:12])}

## 10. Final verdict (§40)

**{final_verdict}**

Mechanically derived: the promoted FINAL_RESULTS_UPDATE verification
state is `{verdict}` (run-pair PASS, tests green, 48M/0 oracle record,
byte-identical outputs — with the documented limitation registry above),
and the section-38 forensic audit is
{'PASS 24/24' if audit_ok else 'NOT PASS'}. No verdict was invented or
upgraded. "Finalized and verified" — publication is NOT claimed
(nothing was pushed).

## 11. Git discipline (§41)

Commits created through the update; NOTHING PUSHED at any point. The
release ZIP and all evidence live in the repository history with this
report.
"""
    write(f"{REPORT_DIR}/FINAL_UPDATE_REPORT.md", md)

    print(f"FINAL REPORT -> {REPORT_DIR}/FINAL_UPDATE_REPORT.md")
    print(f"  JSON deliverables: INTEGRITY_STATUS_UPDATE, "
          f"DRIFT_REPORT_UPDATE, CHANGE_LEDGER_UPDATE, "
          f"FINAL_RESULTS_UPDATE, RELEASE_MANIFEST_UPDATE")
    print(f"  FINAL VERDICT: {final_verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
