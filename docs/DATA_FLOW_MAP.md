# DATA FLOW MAP — data-quality-platformV2

**HISTORICAL DOCUMENT (2026-09-05) — SUPERSEDED where it conflicts with the 2026-09-09 FINAL 5M VALIDATION pass.** Known stale wording: "R3 = R1 OR R2 [contract-exact]" — the implemented R3 is an independent predicate (first==last OR both single-char); live counterexamples exist; company decision recorded in FINAL_IMPROVEMENT_REPORT D-06. Authoritative status: evidence/final_5m_execution/FINAL_RESULTS.json.


**Report date:** 2026-09-05. Purpose: trace how data actually moves through the delivered system, flag-by-flag and stage-by-stage, marking verified flows vs blocked flows.

---

## 1. Primary verified flow (local CSV path — the only executed path)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ INPUT: 33-column consumer CSV (source values are IMMUTABLE through the flow) │
└──────────────┬──────────────────────────────────────────────────────────────┘
               ▼
[1] SCHEMA VALIDATION — schema/validator.py
    · enforces 33-column contract (order + presence)
    · reject: missing/duplicate/extra/reordered columns        [VERIFIED: unit + Q1 evidence]
               ▼
[2] RULE ENGINE — validation/engine.py + rules/registry.py
    · fail-closed loading: missing/dup/unknown/invalid ⇒ hard error   [VERIFIED]
    · per-row evaluation (O(1) memory per row), one flag each:
        R1 first_name_cleaning_candidate   (SUSPICIOUS_NAME_PATTERNS ∩ first_name)
        R2 last_name_cleaning_candidate    (SUSPICIOUS_NAME_PATTERNS ∩ last_name)
        R3 name_cleaning_candidate         = R1 OR R2                       [contract-exact]
        R4 email_blank                     (suppression reason)
        R5 email_syntax_failure            (suppression reason)
        R6 proposed_email_export_eligible  (PROPOSED action — not a completed suppression)
        R7 zip_state_assessable            (V1: zip≠'' AND state≠'' AND state∈STATE_ZIP_PREFIXES)
        R8 geography_mismatch_candidate    (V1: assessable-shape AND zip-prefix ∉ state's list;
                                            returns 0 whenever unassessable  ⇒
                                            UNASSESSABLE != MISMATCH)        [VERIFIED: probes+golden]
               ▼
[3] FLAG PREVIEW OUTPUT — 33 source columns (UNCHANGED, exact order) + 8 flags = 41 columns
                                                               [VERIFIED: contract tests]
               ▼
[4] MONITORING / ALERTING — monitoring/quality.py, alerting/alerts.py
    · completeness/validity/accuracy/email_quality/geo-consistency scores
    · SLA-breach alerts (observed in verify run output; expected behavior)
               ▼
[5] EVIDENCE CAPTURE — evidence/manifests.py, audit/trail.py, lineage/recorder.py
    · success/failure manifests (distinct schemas; safety invariants
      production_changed=false · source_write_performed=false · raw_values_printed=false)
    · success-manifest SHA-256 computed AFTER close+re-read (external)          [VERIFIED]
    · audit records; run+row lineage (in-memory, O(N) — documented limit)
               ▼
[6] RECONCILIATION — per-flag expected vs observed; any mismatch FAILS the run
                                                               [VERIFIED: 100 + 1000 + fresh 1K]
               ▼
[7] VERIFICATION HARNESS — runner/cli.py verify  →  Q1–Q22 statuses
    · Q1–Q20 individual checks; Q21 = aggregate_scope(Q1–Q20)  (deterministic,
      fail-closed, no hardcoded verdict — anti-hardcoding tripwire tested)
    · Q22 documentation audit                                                    [VERIFIED]
```

## 2. Geography chain — current (V1, implemented) vs successor (blocked)

**V1 (executed today):**
```
row.zip / row.state
   → [V1 assessability]  state ∈ STATE_ZIP_PREFIXES (51-entry, state-keyed 2-digit prefix map)
   → [V1 mismatch]       zip startswith any listed prefix ? 0 : 1   (0 if unassessable)
   → (no SP1 stage exists; downstream consumers only COUNT flags:
      validation/engine.py:175–177; monitoring/quality.py:80–103 ratios)
```
Known V1 map defects (documented, pinned as tripwires, NOT silently changed):
8 territory/military codes absent · DC duplicate "20" · 13 ambiguous prefixes · Austin 733xx false positives (GC011/GC037/GC050 carried conflicts).

**Successor (company-delivered contract, revision 2: pure implementation COMPLETE, production activation DEFERRED):**
```
Canonical Geography (tips_data.tblZipStCtyIB or company-approved snapshot)   ← ✖ PHYSICAL SOURCE UNAVAILABLE (BLOCKED)
        ↓                                            implemented in code via injectable TwoReferenceProvider
zip_state_assessable = reference_resolved AND NOT(blank_state, invalid_state_format,
                                                numeric_state_review, unknown_state_code)
        ↓  data_quality_platform/geography/canonical.py::evaluate_geography          [VERIFIED: 63 tests + independent oracle 7/7]
zip_state_mismatch = assessable AND state_code != canonical_state
        ↓
SP1 eligibility:  mismatch=1 → EXCLUDED
                  assessable=1 ∧ match → ELIGIBLE
                  assessable=0 ∧ requested geography present → ELIGIBLE
                  (UNASSESSABLE != MISMATCH; mismatch ⇒ assessable)
        ↓  data_quality_platform/geography/canonical.py::sp1_eligibility             [VERIFIED: acceptance cases]
              · 7 authoritative cases: CA/90210 ✓ CA/00USA ✓ CA/0 ✓ CA/000CA ✓ CA/"015 8" ✓ WA/99501→AK ✓ GU/96910 ✓
              · field_present PER FIELD: zip→zip5≠''; state→classifiers; city/address→blankness; county/country→NOT DEFINED (refused)
        ↓
downstream selection/export                                                  ← ✖ NOT WIRED (production behavior unchanged;
                                                                               activation requires physical references + authorization)
```
SP1 must CONSUME canonical metadata and must NOT independently decide ZIP/state validity. The canonical stage is blocked on physical reference availability; the SP1 semantics are implemented as an isolated pure module verified with controlled fixtures (the path sanctioned by delivery instruction §6) — production selection behavior is UNCHANGED and no canonical production validation is claimed. Full contract + provenance: `docs/GEOGRAPHY_RULE_SP1_CONTRACT.md`.

## 3. Orchestration flow (Airflow — static only)

```
airflow/dags/dq_validation_dag.py
    params: csv_path · output_path · evidence_dir (passed via context["params"])
    → calls the SAME canonical runner implementation tested outside Airflow
    → runtime status: DESIGNED_BUT_NOT_RUNTIME_VERIFIED (Airflow not installed)
```

## 4. Blocked/nonexistent flows (explicit)

| Flow | Status | Reason |
|---|---|---|
| ClickHouse source read (flag_preview view, state_zip_reference) | NOT EXECUTED | server unreachable; `state_zip_reference` designed-but-unpopulated (sql/003) |
| SQL-rendered rule execution | NOT EXECUTED | templates carry unresolved `{states}`/`{zip_state_conditions}` placeholders; parity BLOCKED |
| Canonical snapshot load (`data/cross_reference_snapshot.csv`) | ABSENT | file does not exist; fabrication forbidden |
| E1 coordinate write | NEVER EXECUTED | NOT AUTHORIZED |
| Production cleaning | NEVER EXECUTED | gate is opt-in; no authorization; safe defaults |

## 5. Data-safety properties of the flow (verified)

1. Source values never mutated at any stage of Flag Preview (only flags appended).
2. No raw consumer values enter evidence/logs/audit (JSON evidence = metadata; CSV evidence = synthetic-by-design).
3. Every evidence artifact is hash-addressable (manifests with SHA-256; external success hash).
4. Reconciliation is exact per-flag and fails the run on any mismatch.
5. The Q21 aggregation consumes Q1–Q20 results only (structural no-self-read: Q21's own entry is appended after `q21()` returns).
