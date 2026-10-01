# ARCHITECTURE MAP — data-quality-platformV2

**HISTORICAL DOCUMENT (2026-09-05) — SUPERSEDED where it conflicts with the 2026-09-09 FINAL 5M VALIDATION pass.** Known stale wording: "SP1 successor eligibility NOT IMPLEMENTED" — SP1 semantics are implemented and tested; activation remains withheld. Authoritative status: evidence/final_5m_execution/FINAL_RESULTS.json.


**Report date:** 2026-09-05. Purpose: give reviewers a verified structural picture of the delivered system, including which parts are implemented, which are design-only, and which are blocked.

---

## 1. Repository layout (final delivered state)

```
data-quality-platformV2/
├── runner/cli.py                     # CLI entrypoint (process/verify/benchmark/reconcile/…; q21() = real aggregation)
├── data_quality_platform/
│   ├── contracts.py                  # SOURCE_COLUMNS(33), FLAG_COLUMNS(8), STATE_ZIP_PREFIXES(V1), SUSPICIOUS_NAME_PATTERNS
│   ├── rules/                        # base.py (Rule ABC), v1_rules.py (R1–R8), registry.py (fail-closed loader)
│   ├── validation/engine.py          # orchestration: flags per row, evidence, reconciliation, id_set/lineage buffers
│   ├── evidence/manifests.py         # success/failure manifests (distinct schemas; external success hash)
│   ├── audit/trail.py                # audit records
│   ├── lineage/recorder.py           # run + row lineage (in-memory O(N) — documented)
│   ├── monitoring/quality.py         # scores: completeness/validity/accuracy/email/geo-consistency
│   ├── alerting/alerts.py            # alert rules incl. SLA-breach warnings
│   ├── security/                     # auth.py (RBAC/AuthContext/SecretsManager), pii_masking.py
│   ├── cleaning/                     # opt-in cleaning gate (gate BEFORE clean)
│   ├── generation/synthetic.py       # synthetic test-data generator (consumes STATE_ZIP_PREFIXES for data gen only)
│   ├── schema/validator.py           # 33-column schema validation
│   ├── geography/                    # NEW rev-2: SP1 successor contract (ISOLATED, pure)
│   │   ├── canonical.py              #   zip5, classifiers, 62-code allowlist, two-reference resolution,
│   │   │                             #   assessable/match/mismatch, field_present, sp1_eligibility
│   │   └── references.py             #   TwoReferenceProvider interface + controlled-fixture provider
│   ├── profiling/ · flags/ · storage/· config/ · verification/
│   │      └── verification/scope_aggregator.py   # NEW: deterministic fail-closed Q1–Q20 aggregation (Q21)
├── tests/{unit,contract,golden,integration,runtime,security}/
│   └── golden/{golden_cases.csv, expected_results.csv, geography_edge_cases.csv,
│               test_golden_cases.py, test_golden_fixture_integrity.py, test_dl_canonical_geography.py}
├── airflow/dags/dq_validation_dag.py # single DAG → calls canonical runner (no duplicated logic)
├── sql/001–005                       # DDL: source, flag_preview, reference tables (state_zip_reference designed, unpopulated), audit, lineage
├── scripts/{run_final_verification.py, benchmark.py}
├── configs/quality.yaml · docker-compose.yml · pyproject.toml · .gitignore
├── docs/{CANONICAL_GEOGRAPHY_DESIGN.md, GULNARA_REVIEW.md, FALSE_POSITIVE_REVIEW.md,
│         ARCHITECTURE_MAP.md, DATA_FLOW_MAP.md}                            # ARCHITECTURE/DATA_FLOW = NEW (this phase)
├── evidence/                          # historical verification + benchmark + audit evidence (byte-preserved)
│   └── final/PROOF_MATRIX.md          # NEW (this phase)
├── FINAL_VERIFICATION_REPORT.md       # historical (preserved byte-for-byte)
├── FINAL_{REMEDIATION,TEST,SECURITY,SCALE}_REPORT.md · COMPANY_REQUIREMENTS_ANSWER.md   # NEW (this phase)
└── SECURITY.md · README.md            # README preserved; claim-correction itemized in alignment report (owner pending)
```

## 2. Component status map

| Component | Status | Notes |
|---|---|---|
| Rules engine (R1–R8, Python path) | **IMPLEMENTED / VERIFIED** | 8 rules, registry fail-closed, 50 golden + edge cases green |
| SQL rule templates | **EVIDENCE-ONLY** | contain unresolved placeholders; never rendered; parity BLOCKED (no ClickHouse) |
| Q21 scope aggregation | **IMPLEMENTED / VERIFIED** | deterministic fail-closed; live status PARTIAL (honest) |
| Flag Preview 41-column contract | **IMPLEMENTED / VERIFIED** | contract tests green; source values unchanged |
| Evidence manifests + audit + lineage + monitoring + alerting | **IMPLEMENTED / VERIFIED (unit/integration level)** | O(N) lineage documented |
| Security controls | **IMPLEMENTED (code-level) / PARTIAL** | production IAM absent (Q18) |
| Cleaning gate | **IMPLEMENTED / VERIFIED** | opt-in, gate-before-clean, safe defaults |
| Airflow orchestration | **STATIC DAG ONLY** | runtime DESIGNED_BUT_NOT_RUNTIME_VERIFIED (Airflow not installed) |
| Canonical geography (full 5-digit reference) | **DESIGN-ONLY (BLOCKED)** | `docs/CANONICAL_GEOGRAPHY_DESIGN.md` C1–C6; source unavailable |
| SP1 successor eligibility | **NOT IMPLEMENTED (BLOCKED — by design)** | contract VERIFIED; implementation gate not met |
| ClickHouse integration / parity / scale | **BLOCKED** | server unreachable entire remediation |
| E1 write experiment | **NOT AUTHORIZED** | safety architecture documented; never executed |

## 3. Key architectural invariants (verified)

1. **Fail-closed rule loading** — registry rejects missing/duplicate/unknown/invalid rules; the platform never silently operates with a partial rule set.
2. **Fail-closed Q21** — any structural defect (missing/duplicate/unexpected ID, invalid status, missing evidence) ⇒ verdict FAIL; PASS only when all 20 constituents explicitly PASS; PARTIAL otherwise with disclosed composition.
3. **UNASSESSABLE != MISMATCH** — `GeographyMismatchCandidate` returns 0 for every unassessable shape (blank zip/state, unknown state); mismatch implies assessable.
4. **Flag Preview immutability** — source columns are never cleaned/blanked/rewritten; flags are boolean/binary.
5. **Gate-before-clean** — cleaning is opt-in and authorization precedes invocation.
6. **Evidence safety invariants** — `production_changed=false`, `source_write_performed=false`, `raw_values_printed=false`; success-manifest hash computed externally.
7. **Canonical chain direction** — Canonical Geography → assessable → mismatch → eligibility → downstream; SP1 must consume (never re-derive) geography metadata.

## 4. Deliberate non-implementations (with reasons)

- **SP1 successor logic**: implementation gate unmet (canonical reference + DL table unavailable); implementing would require fabrication — forbidden.
- **sql/006 canonical DDL**: design-only in `docs/CANONICAL_GEOGRAPHY_DESIGN.md`; requires the authoritative reference schema.
- **ClickHouse-native scale path**: blocked on access; Python path is the only executed path.
- **README claim corrections**: itemized and pending owner approval (publication change deliberately not made unilaterally).
