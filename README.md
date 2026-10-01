# DQAEIP — Data Quality Assurance & Evidence Integrity Platform

## README — Company-Facing Documentation

> **Documentation kind:** Company-facing README, rebuilt from the actual repository state and authoritative evidence present in the repository.
>
> **Authoritative evidence date (3.3M validation):** 2026-09-29
>
> **Final verdict:** `PASS_WITH_DOCUMENTED_LIMITATIONS`

---

## 1. Executive Summary

DQAEIP is a deterministic consumer data-quality validation platform. Its single production job is:

> Read a 33-column input CSV → apply 8 frozen V1 validation rules → write a 41-column output CSV (33 source columns + 8 flag columns) → emit tamper-evident evidence → produce a final verdict.

The platform is **fail-closed**: any unrecoverable inconsistency in the input, schema, rule set, evidence chain, or release gate blocks release rather than producing a degraded output.

The latest validation was a **3,300,000-row synthetic controlled run** (seed `20260929`) that produced byte-identical output across two independent runs, with **0 false negatives** on all 8 rules. The release gate (version `4.0.0`) recorded **24/24 PASS** at the validation Build HEAD.

DQAEIP performs **validation only**. It does **not** modify, clean, or delete source records. No customer (production) data has been processed in any certified run — all validations used deterministic synthetic data.

---

## 2. Repository and Provenance Identity

| Property | Value | Verified from |
|----------|-------|---------------|
| Repository | `DQAEIP-FINAL-HARDENED` | Working copy |
| Branch | `main` | `git branch --show-current` |
| Remote (fetch/push) | `https://github.com/aladdinoo/DQAEIP-FINAL-HARDENED-V1.git` | `git remote -v` |
| **Build HEAD used for the 3.3M validation** | `95abd860354d4239fecb01d722355a8a1d4a25cc` (`95abd86`) | `FINAL_RESULTS.json` → `release_gate.head_recorded_by_gate` |
| Initial 3.3M documentation commit | `f594e10f3e8b0b19b3e86d0ab1dd0a9c78208a6b` (`f594e10`) | `FINAL_RESULTS.json` → `repository.documentation_commit` |
| Architecture-provenance documentation commit | `2a8c146899c261c1c46ec59a41a2eb310ef8bc59` (`2a8c146`) | `docs/DQAEIP_ARCHITECTURE_GUIDE.md` |
| **Current repository HEAD** | `190a95684e247c385ec26d5998ebb9401dd5cd15` (`190a956`) | `git rev-parse HEAD` |
| `origin/main` | `3c7e0852cfdabf114ca28d16319040f0819bae65` (`3c7e085`) | `git rev-parse origin/main` |
| Provenance chain (H-4 ANCESTOR verified at each step) | `3c7e0852` → `95abd86` → `f594e10` → `2a8c146` → `190a956` | `git merge-base --is-ancestor` |
| Commit signature status | `G` (Good signature) | `git show -s --format='%G?' HEAD` |
| Signing fingerprint | `6BAF8AEFE12EB327598EB4471B0613B9D58ADC85` | `git show -s --format='%GF' HEAD` |
| Signer | `DQAEIP Release Signing <release-signing@dqaeip.local>` | `git show -s --format='%GS' HEAD` |

### Current Git divergence

The 3.3M validation documentation was produced during an earlier repository state. The historical fact that the repository was not pushed to GitHub at the time of the 3.3M validation is preserved as historical provenance. **Current Git divergence must be determined from the repository's actual Git state rather than a hard-coded count in this document.**

To determine the current divergence, run from the repository root:

```bash
git rev-parse HEAD
git rev-parse origin/main
git rev-list --count origin/main..HEAD   # commits ahead of origin/main
git rev-list --count HEAD..origin/main   # commits behind origin/main
```

The repository must not be presented as pushed unless `git rev-list --count HEAD..origin/main` is `0` **and** `git ls-remote origin refs/heads/main` matches `git rev-parse HEAD` at the time of inspection.

---

## 3. Current Validation Status

| Property | Value | Source |
|----------|-------|--------|
| Final verdict | **`PASS_WITH_DOCUMENTED_LIMITATIONS`** | `FINAL_RESULTS.json` |
| Release gate | **24/24 PASS** (v4.0.0, exit `0`) | `evidence/release_gate/final_release_gate.json` |
| 3.3M validation | **PASS** — 100% rule recall, 0 false negatives, byte-identical independent runs | `FINAL_RESULTS.json` |
| Security findings | **0 confirmed exploitable findings within the documented forensic audit scope** | `evidence/release/security_release_report.json` |
| Confirmed engine defects | **0 confirmed engine defects within the documented validation and audit scope** | `FINAL_RESULTS.json` + release gate |
| Customer data processed | **No** — synthetic only | `FINAL_RESULTS.json` → `validation.customer_data_processed` |

These statements are **scope-bounded**, not universal. They do not claim "zero security risk", "fully secure", "bug-free", "guaranteed secure", or "universally production-ready".

---

## 4. 3.3M Synthetic Validation

All values below are taken verbatim from `FINAL_RESULTS.json` (root), which is the authoritative 3.3M validation result. The validation was performed against **Build HEAD `95abd86`** — this identity must not be replaced with the current HEAD.

### Input / output metrics

| Metric | Value |
|--------|-------|
| Rows | `3,300,000` |
| Input columns | `33` |
| Output columns | `41` (33 source + 8 flag) |
| Rules tested | `8` |
| Seed | `20260929` |
| Input SHA-256 | `37b74de296f66135cb3897b28a13d2faecb0f093ef3f29a124db7684674d7c7b` |
| Output SHA-256 | `469c55907a3757d81f53af32bfa0afa37868456e909db6d08d012c10ebd908de` |
| Input bytes | `887,357,286` |
| Output bytes | `943,457,484` |
| Run 1 duration | `119.35` seconds |
| Run 2 duration | `119.18` seconds |
| Average duration | `119.27` seconds |
| Throughput | ~`27,669` rows/sec |
| Byte-identical output (Run 1 SHA == Run 2 SHA) | **YES** |
| Input immutable (input SHA identical pre/post validation) | **YES** |
| Rows preserved (input rows == output rows) | `3,300,000 / 3,300,000` |
| Dataset type | `synthetic_controlled_validation` |
| Customer data processed | `false` |

### Defect / recall metrics

| Metric | Value |
|--------|-------|
| Clean rows | `3,200,999` (97.00%) |
| Injected defective rows | `99,001` (3.00%) |
| False negatives | `0` (100% recall on all 8 rules) |
| Non-assessable geography cases | `5,562` (NOT clean — see §12 Known Limitations) |
| Confirmed engine defects (scope-bounded) | `0` |

---

## 5. Rule Coverage

The frozen V1 business core consists of exactly **8 rules**, defined in `data_quality_platform/rules/v1_rules.py` and registered through `data_quality_platform/rules/registry.py`. The rule set is **hash-pinned**: any unauthorized modification to a rule's source changes its SHA-256 and is rejected by the release gate.

| Rule ID | Rule type | Injected / engine flags (3.3M run) | False negatives | Recall |
|---------|-----------|----------------------|------------------|--------|
| `first_name_cleaning_candidate` | defect detection | 39,001 / 195,127 | 0 | 1.0 |
| `last_name_cleaning_candidate` | defect detection | 26,000 / 108,802 | 0 | 1.0 |
| `name_cleaning_candidate` | defect detection | 33,000 / 33,797 | 0 | 1.0 |
| `email_blank` | defect detection | 16,000 / 16,000 | 0 | 1.0 |
| `email_syntax_failure` | defect detection | 32,000 / 32,000 | 0 | 1.0 |
| `geography_mismatch_candidate` | defect detection | 32,000 / 32,000 | 0 | 1.0 |
| `proposed_email_export_eligible` | eligibility flag (positive) | — / 3,252,000 | 0 | 1.0 |
| `zip_state_assessable` | assessability flag (positive) | — / 3,294,000 | 0 | 1.0 |

Authoritative V1 rules SHA-256: `daef1ded54c7d3c79898a1ba253be2acd5b6120e18b16b09009fdd7be9fc2276` (computed over `data_quality_platform/rules/v1_rules.py`).

### Rule semantics — frozen V1 substring matching

The `first_name_cleaning_candidate`, `last_name_cleaning_candidate`, and `name_cleaning_candidate` rules use **case-insensitive substring matching** per the frozen V1 contract. The pattern `na` will therefore match ordinary names such as **Anna**, **Donna**, and **Hannah**. This is **intended frozen-rule semantics**, not an engine defect. Any rule modification requires a new rule version and a re-issued release identity.

### Geography semantics — assessability gate

`geography_mismatch_candidate` is **conditional on `zip_state_assessable = 1`**. Non-assessable records (invalid US state) return `0` for both flags — these records are **NOT clean**, they are **NOT ASSESSABLE / NOT EVALUATED**. The 5,562 non-assessable geography cases in the 3.3M run are correctly excluded from the geography mismatch count and must never be reported as clean.

---

## 6. Architecture

The 33→41 column contract is enforced by `data_quality_platform/contracts.py`:

- `SOURCE_COLUMNS` — exactly 33 columns in fixed order.
- `FLAG_COLUMNS` — exactly 8 flag columns.
- `OUTPUT_COLUMNS = SOURCE_COLUMNS + FLAG_COLUMNS` — exactly 41 columns.
- `EXPECTED_COLUMN_COUNT = 33`, `EXPECTED_FLAG_COUNT = 8`, `TOTAL_OUTPUT_COLUMNS = 41`.

The validation engine is `data_quality_platform/validation/engine.py` (`ValidationEngine.validate()`). The CLI entry point is `runner/cli.py` (`cmd_validate`). The production invocation is wrapped by the hardened execution pipeline in `data_quality_platform/hardening/pipeline.py`, which wires the A–H hardening layers around the engine subprocess.

### Additive A–H operational-hardening envelope

| Layer | Module | Role |
|-------|--------|------|
| **A** — Input Contract | `data_quality_platform/hardening/input_contract.py` | SHA-256 pin, UTF-8 decode, NUL-byte scan, header equality, column-count enforcement |
| **B** — Authorization Gate | `data_quality_platform/hardening/authorization.py` | `hmac.compare_digest` on 6 scope fields (input SHA, schema fingerprint, V1 ruleset SHA, etc.) |
| **C** — Idempotency Ledger | `data_quality_platform/hardening/idempotency.py` | PARTIAL / COMMITTED / DUPLICATE_BLOCKED state machine; resume is refused (see Layer E) |
| **D** — Atomic Output Commit | `data_quality_platform/hardening/atomic_commit.py` + `engine.py` GAP-02 | Temp file + `fsync` + `os.replace` (atomic publish); GAP-01 path-collision guard rejects identical input/output paths |
| **E** — Checkpoint / Safe-Resume Contract | `data_quality_platform/hardening/checkpoint_contract.py` | **CONTRACT ONLY — NOT IMPLEMENTED BY DESIGN.** Resume is refused; a fresh full re-run is the safe equivalent (the engine is deterministic and dual-run byte-identical). |
| **F** — Schema Evolution Guard | `data_quality_platform/hardening/schema_guard.py` | Blocks unrecognized schema changes |
| **G** — Reference-Data Versioning | `data_quality_platform/hardening/reference_data.py` | Reference datasets are versioned and hash-pinned |
| **H** — Resource Guard | `data_quality_platform/hardening/resource_guard.py` | Pre-execution and post-execution resource/contract guards |

### End-to-end data flow

```
Input CSV (33 columns)
    ↓  Layer A — Input Contract
    ↓  Layer F — Schema Evolution Guard
    ↓  Layer G — Reference-Data Versioning
    ↓  Layer B — Authorization Gate
    ↓  Layer C — Idempotency Ledger (PARTIAL)
    ↓  Layer H — Pre-Execution Resource Guard
Engine subprocess (runner/cli.py validate → streaming → 8 rules → 41-col output)
    ↓  Layer H — Post-Execution Resource Guard
    ↓  Layer D — Atomic Output Commit (temp + fsync + os.replace)
    ↓  Layer C — Ledger Finalization (COMMITTED)
Evidence (manifest, lineage, audit, monitoring, alerts, evidence_root)
    ↓  Release gate (24 fail-closed gates)
Final verdict
```

---

## 7. Reproducibility and Determinism

**Determinism was demonstrated by byte-identical independent runs and supported by the deterministic execution design.** This is a scope-bounded empirical demonstration on the documented 3.3M synthetic dataset, not a claim of universal determinism across every possible environment.

The determinism mechanism (from `FINAL_RESULTS.json` → `reproducibility.determinism_mechanism`):

- `csv.DictReader` is streaming and preserves input row order.
- `uuid4` is used **only** for the temporary file name (not in output content).
- No `random` module is imported in `data_quality_platform/validation/` or `data_quality_platform/rules/`.
- Evidence JSON is written with `json.dumps(sort_keys=True)` for byte-stable serialization.

| Property | Value |
|----------|-------|
| Byte-identical output (Run 1 SHA == Run 2 SHA) | **YES** |
| Input immutability (input SHA identical pre/post) | **YES** |
| Run 1 output SHA-256 | `469c55907a3757d81f53af32bfa0afa37868456e909db6d08d012c10ebd908de` |
| Run 2 output SHA-256 | `469c55907a3757d81f53af32bfa0afa37868456e909db6d08d012c10ebd908de` |
| Average wall time | `119.27` seconds for 3.3M rows (~27,669 rows/sec) |

### Reproduction recipe

```bash
# From the repository root, against Build HEAD 95abd86:
python3 -m runner.cli validate \
    --input  data/generated/3m3/input_3m3_seed_20260929.csv \
    --output data/generated/3m3/output_3m3_seed_20260929.csv \
    --seed   20260929

# Re-run; the output SHA-256 must be identical.
sha256sum data/generated/3m3/output_3m3_seed_20260929.csv
# Expected: 469c55907a3757d81f53af32bfa0afa37868456e909db6d08d012c10ebd908de
```

The input file is treated as read-only; the engine aborts if the input SHA changes during a run (input immutability guard).

---

## 8. Release Gate

The release gate is implemented by `scripts/release_gate.py`. The authoritative gate result is `evidence/release_gate/final_release_gate.json`, recorded against Build HEAD `95abd86`.

| Property | Value |
|----------|-------|
| Gate version | `4.0.0` |
| Total gates | `24` |
| Gates passed | `24` |
| Gates failed | `0` |
| Exit code | `0` |
| Overall verdict | `PASS` |
| HEAD recorded by gate | `95abd860354d4239fecb01d722355a8a1d4a25cc` |

### Per-gate result (24/24 PASS)

| # | Gate | Result | Detail |
|---|------|--------|--------|
| 1 | `repository_integrity` | PASS | HEAD `95abd86`, clean outside `evidence/` |
| 2 | `commit_signature` | PASS | Commit signature verified |
| 3 | `baseline_signature` | PASS | Baseline signature verified |
| 4 | `unit_tests` | PASS | 605 passed / 0 skipped / 0 failed |
| 5 | `integration_tests` | PASS | 24 passed / 0 skipped / 0 failed |
| 6 | `contract_tests` | PASS | 22 passed / 0 skipped / 0 failed |
| 7 | `golden_tests` | PASS | 117 passed / 7 skipped / 0 failed |
| 8 | `property_tests` | PASS | 9 passed / 0 skipped / 0 failed |
| 9 | `differential_validation` | PASS | 10 consistency tests green |
| 10 | `mutation_testing` | PASS | 17/17 mutants killed, score 1.0 |
| 11 | `replay` | PASS | 2 runs byte-identical; nondeterministic registry rejected |
| 12 | `evidence_validation` | PASS | 3M two-run evidence validated; tamper-evident roots verified |
| 13 | `provenance_validation` | PASS | Decision provenance chain resolves |
| 14 | `reference_validation` | PASS | All production references VERIFIED |
| 15 | `safety_checks` | PASS | Fail-closed gates green; SP1 inactive; no ClickHouse client import |
| 16 | `pii_evidence_scan` | PASS | 0 prohibited in evidence tree |
| 17 | `performance_regression` | PASS | 1K/10K/100K/1M vs baseline: clean |
| 18 | `production_source_integrity` | PASS | Frozen sources byte-identical; 0 unauthorized delta |
| 19 | `assurance_tests` | PASS | 489 passed / 0 skipped / 0 failed / 5 deselected (B-8 bootstrap-circularity exclusions) |
| 20 | `machine_path_firewall` | PASS | 0 violations |
| 21 | `negative_release_gate` | PASS | 14/14 controlled failures rejected |
| 22 | `claim_provenance` | PASS | **29/30 claims verified, 1 honestly NOT_VERIFIED** |
| 23 | `consistency_matrix` | PASS | All chain edges verified, CONSISTENT |
| 24 | `absolute_path_release_gate` | PASS | 0 violations |

### Claim provenance — important honesty note

Gate 22 (`claim_provenance`) recorded **29/30 claims verified, 1 honestly NOT_VERIFIED**. This is the authoritative release-gate result. The single `NOT_VERIFIED` claim is preserved as honest provenance — the gate does not retroactively rewrite `NOT_VERIFIED` claims as `VERIFIED`. Do not report this as 30/30.

---

## 9. Security and Assurance Scope

| Property | Status (scope-bounded) |
|----------|------------------------|
| Security findings | **0 confirmed exploitable findings within the documented forensic audit scope** |
| Fail-open paths | **None found within the documented forensic audit scope** |
| Mutation testing | 17/17 mutants killed, score 1.0 |
| Negative battery | 14/14 controlled failures rejected |
| PII evidence scan | 0 prohibited in evidence tree |
| Customer data processed | **No** — synthetic only |

### Runtime safety model (LIM-011)

Runtime safety (0 sockets, 0 `exec`, in-repo writes only) is measured via **CPython audit hooks** inside the production CLI subprocess. This is **cooperative observation, not a kernel-level sandbox**. A cooperative model is sufficient for evidence collection and fail-closed behavior, but it is not an OS-level isolation boundary.

### Filesystem metadata limitation (LIM-017)

Filesystem metadata mutations such as `os.chmod` and `os.utime` are **not captured** by the runtime safety audit hook. The defined 18-operation mutation matrix focuses on content/boundary mutations (`open-write`, `remove`, `rmdir`, `truncate`, `mkdir`, `rename`, `link`, `symlink`, `shutil.copyfile`/`copymode`/`copystat`/`move`/`rmtree`). `os.chmod`/`os.utime` are metadata-only mutations (permissions/timestamps, not content). **Production validation code does not call `chmod`/`utime`**. This is documented as an explicit limitation under the cooperative security model (LIM-011), not as a vulnerability.

### Filesystem output hardening (GAP-01 / GAP-02)

- **GAP-01** — Input/output path-collision guard (`data_quality_platform/validation/engine.py`): if `Path(csv_path).resolve() == Path(output_path).resolve()`, the engine raises `ValueError` rather than overwriting the input.
- **GAP-02** — Atomic output publication: the output is first written to a temp file, then `fsync`'d, then atomically published via `os.replace`. A crash during writing leaves the previous output (if any) intact.

### Security language policy

This document uses **bounded language**. The phrases "0 confirmed exploitable findings" and "0 confirmed engine defects" are scope-bounded to the documented forensic audit and validation scopes respectively. They are **not** claims of "zero security risk", "fully secure", "bug-free", "guaranteed secure", or "universally production-ready".

---

## 10. Airflow Status

| Property | Value |
|----------|-------|
| DAG file | `airflow/dags/dq_validation_dag.py` |
| Tasks | 6 (`preflight`, `schema`, `rule`, `validation`, `monitoring`, `evidence`) — all `PythonOperator` |
| DAG structurally importable | YES — covered by structural tests `test_dag_importable`, `test_dag_has_tasks` |
| Airflow scheduler/worker deployed | **NO** |
| Airflow runtime validated | **NO** |

**Status: STRUCTURALLY IMPLEMENTED — NOT DEPLOYED — NOT RUNTIME-VALIDATED.**

The DAG exists as a structural artifact and is importable, but no Airflow scheduler or worker is installed or run in this environment. The DAG must not be presented as production-Airflow-validated.

---

## 11. ClickHouse Status

| Property | Value |
|----------|-------|
| SQL schema files | `sql/001_create_source.sql`, `sql/002_create_flag_preview.sql`, `sql/003_create_reference_tables.sql`, `sql/004_create_audit_table.sql`, `sql/005_create_lineage_table.sql` |
| Docker Compose service | `docker-compose.yml` (service declared) |
| Production ClickHouse client | **Intentionally absent** (verified by gate 15 safety_checks; boundary enforced) |
| Runtime connection validated | **NO** |

**Status: SCHEMAS + CONFIG IMPLEMENTED — RUNTIME NOT VALIDATED — CLIENT INTENTIONALLY NOT IN PRODUCTION CODE.**

SQL schemas and Docker Compose configuration are implemented as structural artifacts. No live ClickHouse server is connected or executed. The absence of a production ClickHouse client is a deliberate boundary, not an oversight.

---

## 12. Known Limitations

The following limitations are documented in `evidence/release/limitation_registry.json` and `FINAL_RESULTS.json` (→ `limitations`). None are blocking for the documented validation verdict; all are explicitly disclosed.

| ID | Title | Status | Description |
|----|-------|--------|-------------|
| `LIM-001` | O(N) memory profile | OPEN / VERIFIED_LOCALLY | Engine materializes the full dataset in memory. Peak RSS ~2365.7 MB at 3.2M rows. Memory scales linearly with row count. A bounded-memory design exists in `docs/future/bounded_memory_execution.md` as a future design only — **intentionally not implemented** because business-equivalence is unproven. |
| `LIM-002` | ClickHouse runtime not executed | OPEN / NOT_EXECUTED | Import-verified only; no ClickHouse server is connected or executed. Client code contains no live connection path. |
| `LIM-003` | Airflow runtime not executed | OPEN / NOT_EXECUTED | DAG is statically validated only; scheduler/executor runtime is not installed or run. |
| `LIM-004` | Authoritative DL fixture unavailable | OPEN / NOT_VERIFIED | The authoritative DL001–DL015 geography acceptance table was not supplied by the repo owner; 7 golden tests are skipped with that explicit reason. Skipped tests are never converted to PASS. |
| `LIM-005` | SP1 validation-only | OPEN / VERIFIED_LOCALLY | The SP1 successor geography layer is implemented for validation only; it is NOT registered in the production rule registry and NOT activated. |
| `LIM-006` | E1 not implemented / not authorized | OPEN / NOT_AUTHORIZED | Zero E1 identifiers exist in application code (tripwire-enforced boundary test). |
| `LIM-011` | Runtime safety is cooperative instrumentation | OPEN / VERIFIED_LOCALLY | Runtime safety is CPython audit hooks inside the production CLI subprocess — cooperative observation, **not a kernel sandbox**. |
| `LIM-017` | Filesystem metadata mutations not captured | OPEN / VERIFIED_LOCALLY | `os.chmod`/`os.utime` are not captured by the audit hook. Production validation code does not call `chmod`/`utime`. Documented as a limitation, not a vulnerability. |
| `CUR-001` | Customer data not processed | NOT_PROVEN | Customer data has not been processed. |
| `CUR-002` | Airflow runtime not validated | NOT_PROVEN | Airflow runtime has not been validated in a deployed Airflow environment. |
| `CUR-003` | ClickHouse runtime not validated | NOT_PROVEN | ClickHouse runtime connection has not been validated. |
| `CUR-004` | Unicode beyond ASCII synthetic not covered | NOT_TESTED | Unicode beyond the tested ASCII synthetic dataset was not covered by the 3.3M test. |
| `CUR-005` | Near-duplicate detection not part of validation | NOT_TESTED | Near-duplicate detection was not part of this controlled validation. |
| `CUR-006` | Peak memory/CPU not measured | ENVIRONMENT_LIMITED | Peak memory and CPU were not measured in this run. |
| `CUR-007` | Historical fixed-point verification env-limited | ENVIRONMENT_LIMITED | Historical 2026-09-18 fixed-point verification remains environment-limited (required ZIP unavailable). |

### Geography non-assessable — important semantic note

The 5,562 non-assessable geography cases in the 3.3M run are **NOT clean**. They are **NOT ASSESSABLE / NOT EVALUATED**. A record with an invalid US state cannot be evaluated for `geography_mismatch_candidate` because that rule is conditional on `zip_state_assessable = 1`. Reporting non-assessable records as clean would be a misrepresentation of the rule semantics.

---

## 13. Historical Release — 2026-09-19

The 2026-09-19 release is preserved as **historical provenance**. It is not the current 3.3M validation. Do not present the historical release as the current release.

| Property | Value |
|----------|-------|
| Historical release identity | `DQAEIP-FINAL-HARDENED-RELEASE-2026-09-19` |
| Release kind | `OPERATIONAL_HARDENING_ADDITIVE` |
| Historical release date | 2026-09-19 |
| Historical build commit | `3c7e0852cfdabf114ca28d16319040f0819bae65` (`3c7e085`) |
| Historical certified rows | `3,200,000` |
| Historical seed | `20260918` |
| Historical input SHA-256 | `59624a53c72f908f1dde673ceecf59e0662ae721bbf8f9af7e165acba5318d153` |
| Historical output SHA-256 | `b72adc235160a86e0b99a08f988dd0bb5f2cff82bbe5b5d28ea07c5a5719329a` |
| H-4 ANCESTOR (historical) | `3c7e0852` is a verified ancestor of the current HEAD |

The 3.3M validation (Build HEAD `95abd86`) is a **separate, later** validation state, not a re-statement of the 2026-09-19 release. The historical release evidence at `evidence/FINAL_HARDENED_RELEASE_2026-09-19/release_identity/RELEASE_IDENTITY.json` is preserved as immutable provenance and was not modified by the 3.3M validation.

---

## 14. Repository Contents

```
DQAEIP-FINAL-HARDENED/
├── README.md                                  # Existing repo-facing README (V1 wording)
├── FINAL_RESULTS.json                         # Authoritative 3.3M validation result
├── DELIVERY_MANIFEST.json                     # Delivery manifest
├── RELEASE_NOTES.md                           # Release notes
├── final_result.json                          # Historical 2026-09-19 release evidence (NOT modified)
├── release_manifest.json                      # Release manifest
├── pyproject.toml                             # Python project metadata
├── docker-compose.yml                         # Docker Compose (ClickHouse service declared)
├── .env.example                               # Environment variable template
├── .gitignore
├── runner/                                    # CLI entry point (cmd_validate)
├── data_quality_platform/
│   ├── contracts.py                           # 33→41 column contract
│   ├── rules/v1_rules.py                      # 8 frozen V1 rules (hash-pinned)
│   ├── validation/engine.py                   # ValidationEngine + GAP-01/GAP-02
│   ├── hardening/                             # A–H hardening envelope
│   ├── schema/, security/, lineage/, audit/, ...
├── scripts/release_gate.py                    # 24 fail-closed gates
├── evidence/
│   ├── release_gate/final_release_gate.json   # Gate result (authoritative)
│   ├── release/limitation_registry.json       # Limitation registry
│   ├── release/security_release_report.json   # Security release report
│   ├── release/claim_provenance.json          # Claim provenance (29/30 + 1 NOT_VERIFIED)
│   ├── bench_quick/, dqvp_performance/, mutation_testing/, q20_cli/, rebuild_verification/, hardening_baseline/, validation/
│   └── FINAL_HARDENED_RELEASE_2026-09-19/...  # Historical release evidence (immutable)
├── airflow/dags/dq_validation_dag.py          # Airflow DAG (structural only)
├── sql/                                       # ClickHouse SQL schemas (5 files)
├── tests/                                     # unit / integration / contract / golden / property / runtime / hardening
└── docs/
    ├── DQAEIP_ARCHITECTURE_GUIDE.md           # Architecture guide
    └── future/bounded_memory_execution.md     # Future design (not implemented)
```

---

## 15. Evidence Locations

| Artifact | Path |
|----------|------|
| 3.3M validation result | `FINAL_RESULTS.json` |
| Release gate result | `evidence/release_gate/final_release_gate.json` |
| Limitation registry | `evidence/release/limitation_registry.json` |
| Security release report | `evidence/release/security_release_report.json` |
| Claim provenance | `evidence/release/claim_provenance.json` |
| Release artifact manifest | `evidence/release/release_artifact_manifest.json` |
| Historical release identity (2026-09-19) | `evidence/FINAL_HARDENED_RELEASE_2026-09-19/release_identity/RELEASE_IDENTITY.json` |
| Historical release evidence (root) | `final_result.json` |
| Architecture guide | `docs/DQAEIP_ARCHITECTURE_GUIDE.md` |
| Bounded-memory future design | `docs/future/bounded_memory_execution.md` |

---

## 16. Reproduction

To reproduce the 3.3M validation against Build HEAD `95abd86`:

```bash
# 1. Confirm you are at Build HEAD (or that Build HEAD is an ancestor of current HEAD):
git rev-parse HEAD
git merge-base --is-ancestor 95abd860354d4239fecb01d722355a8a1d4a25cc HEAD
#   exit 0  → Build HEAD is an ancestor of current HEAD (H-4 verified)

# 2. Run the validation (input file at the documented path):
python3 -m runner.cli validate \
    --input  data/generated/3m3/input_3m3_seed_20260929.csv \
    --output data/generated/3m3/output_3m3_seed_20260929.csv \
    --seed   20260929

# 3. Re-run and confirm byte-identical output:
python3 -m runner.cli validate \
    --input  data/generated/3m3/input_3m3_seed_20260929.csv \
    --output data/generated/3m3/output_3m3_seed_20260929_run2.csv \
    --seed   20260929

# 4. Verify:
sha256sum data/generated/3m3/output_3m3_seed_20260929.csv
#   Expected: 469c55907a3757d81f53af32bfa0afa37868456e909db6d08d012c10ebd908de
sha256sum data/generated/3m3/output_3m3_seed_20260929_run2.csv
#   Expected: identical to Run 1

# 5. Re-run the release gate (optional, requires GNUPGHOME for GPG verification):
GNUPGHOME=<signing-home> python3 scripts/release_gate.py
#   Expected: 24/24 PASS, exit 0
```

The input SHA-256 must equal `37b74de296f66135cb3897b28a13d2faecb0f093ef3f29a124db7684674d7c7b` before and after the run (input immutability guard).

---

## 17. Release Identity

| Property | Value |
|----------|-------|
| Historical release identity | `DQAEIP-FINAL-HARDENED-RELEASE-2026-09-19` |
| Release kind | `OPERATIONAL_HARDENING_ADDITIVE` |
| 3.3M validation | **Not a new release identity.** It is the validation/repository state produced against Build HEAD `95abd86`, documented at commit `f594e10`, with architecture provenance finalized at commit `2a8c146`, using the frozen 2026-09-19 release identity with post-release hardening commits. |
| Software / rule-engine version | Unchanged. The V1 rule set is hash-pinned (`daef1ded…`). No new software version or new rule-engine version is introduced by this documentation. |

---

## 18. Company Delivery Interpretation

This README V2 is a **company-facing documentation artifact**. It is **not** a new software release, not a new rule-engine version, and not a new validation result. It is a clean rewrite of the company-facing README from the actual repository state and the authoritative evidence already present in the repository.

### What this README is

- A precise, bounded, evidence-anchored description of DQAEIP as it exists in the repository at the current HEAD.
- A re-statement of the 3.3M synthetic validation result produced against Build HEAD `95abd86`.
- A disclosure of the documented limitations (LIM-001, LIM-002, LIM-003, LIM-004, LIM-005, LIM-006, LIM-011, LIM-017; CUR-001 through CUR-007).

### What this README is not

- A new software release. The V1 rule set is unchanged.
- A new validation result. The 3.3M validation was performed against Build HEAD `95abd86` and is preserved as historical provenance.
- A claim of "fully secure", "zero security risk", "bug-free", "guaranteed secure", or "universally production-ready". All security and defect statements are scope-bounded to the documented forensic audit and validation scopes.
- A claim of Airflow runtime validation. Airflow is structurally implemented, not deployed, not runtime-validated.
- A claim of ClickHouse runtime validation. ClickHouse schemas and configuration are implemented; runtime is not validated; the production client is intentionally absent.
- A claim that customer (production) data has been processed. All validations used synthetic data.

### Provenance to the company

The 3.3M validation documentation was produced during an earlier repository state and was not pushed to GitHub at the time of validation. The Build HEAD (`95abd86`), the initial documentation commit (`f594e10`), the architecture-provenance commit (`2a8c146`), and the current repository HEAD (`190a956`) form a verified H-4 ANCESTOR chain. Current Git divergence from `origin/main` must be determined from the repository's actual Git state at the time of inspection, not from any hard-coded count in this document.

---

*End of README V2 — Company-Facing Documentation.*
