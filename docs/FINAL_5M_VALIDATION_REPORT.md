# DATA QUALITY — FINAL 5M VALIDATION & ALIGNMENT REPORT

## 1. Document Control

| Field | Value |
|---|---|
| Report date | 2026-09-09 |
| Repository | `/home/z/my-project/Data-Quality-V1-Final-Company-Integrated` (product: **Data Quality Validation Platform**, V1 frozen engine) |
| Commit at baseline | `0282e67bf1212b188915973b9449e09bcd22a11b` (branch `main`) |
| Environment | Linux container · 2 vCPU · 4,041 MB total RAM (no swap) · Python 3.12.14 |
| Dataset | `data/generated/final_5m/consumer_5m_seed_20260909.csv` — exactly 5,000,000 rows × 33 columns |
| Seed | **20260909** (new single seed lineage for this task; distinct from the historical 1K CLI seed 20260821 and from every earlier seed) |
| Report status | FINAL — rebuilt from evidence artifacts generated in this pass; not derived from any previous report |

## 2. Executive Decision

**PASS WITH DOCUMENTED LIMITATIONS.**
The 5,000,000-row dataset was created, forensically verified, and used for a
real 5M pipeline attempt; the attempt was killed by the kernel OOM killer at
98.9% completion (environment RAM limit, fully evidenced). The complete
dual-run protocol — execution, independent verification, second run,
byte-for-byte comparison — was then executed at **3,000,000 rows**, the
largest scale satisfying the pre-registered memory-safety rule, and passed
every check with **0 mismatches across 48,000,000 independent flag
comparisons**. The frozen V1 platform itself is verified at that scale; the
5M ceiling is an environment limitation of this 4 GB container, not a
platform defect, and is reported as such — never hidden.

## 3. Scope

**Evaluated in this pass (executed):**
- New deterministic 5M dataset generation + independent dataset forensics.
- One real 5M pipeline execution attempt through the canonical CLI.
- Complete dual-run protocol at 3M (Run 1, independent verifier, Run 2,
  byte comparison), plus a 1K/10K/100K/1M performance ladder and the repo's
  tracemalloc benchmark for metric continuity.
- Full test suite (331 collected) with skip attribution.
- SP1 activation-boundary proof (six properties), V1 geography aggregation,
  reporting-consistency audit, evidence manifest, final archive + unpack
  verification.

**Not evaluated / out of scope (explicit statuses):**
- 5M Run 2 — NOT EXECUTED (deterministic OOM failure mode; documented).
- ClickHouse runtime — NOT RUNTIME VERIFIED (0 connections; DDL templates only).
- Airflow runtime — NOT RUNTIME VERIFIED (static DAG = 6 tasks verified).
- E1 — NOT IMPLEMENTED / NOT AUTHORIZED.
- DL001–DL015 canonical geography — COMPANY-GATED (external fixtures).
- Company 721,141,364 / 590,011,545 population scale — COMPANY-SUPPLIED,
  arithmetic-only, NOT locally reproduced.

## 4. 5M Validation Results

**Dataset (complete and verified):**
- Rows: **5,000,000** · Columns: 33 (exact contract order) · IDs 1..5,000,000
  strictly sequential, no duplicates, no missing (independent streaming check).
- Size: 1,351,673,659 bytes · SHA-256
  `44e41bb8cfe1c0d2fbafbff5e91bb40b100f8331ef26f946532b84c57409fb9d`.
- Generation: canonical CLI, 123.904 s, child peak RSS 22.57 MB
  (`ru_maxrss` method) — streaming, as designed.

**Run 1 (5M attempt):** command = canonical `python -m runner.cli validate …`;
185.307 s; **terminated by SIGKILL (exit -9)** at row 4,943,922 / 5,000,000
(98.9%); kernel record captured live: `Out of memory: Killed process 3565
(python) total-vm:3678772kB, anon-rss:3592016kB`. The pre-registered linear
memory model (715.63 MB per 1M rows, from measured 1M/2M anchors) projected
3,593.9 MB against 3,576 MB available — the kill matches the projection
within 0.1%. Status: **FAILED — ENVIRONMENT OOM** (honest record in
`evidence/final_5m_execution/03_run1/`).

**Run 2 (5M):** NOT EXECUTED — the failure mode is deterministic (same frozen
engine, same input, same RAM); a second doomed attempt would add no
information (`05_run2/5M_RUN2_NOT_EXECUTED.md`).

**Largest completed execution — 3M dual-run protocol:**

| | Run 1 (`run_3m_r1`) | Run 2 (`run_3m_r2`) |
|---|---|---|
| Input rows | 3,000,000 | 3,000,000 |
| Output rows | 3,000,000 | 3,000,000 |
| Duration | 138.472 s | 140.466 s |
| Exit code | 0 ("Validation PASSED") | 0 ("Validation PASSED") |
| peak RSS (ru_maxrss) | 2,192.27 MB | 2,195.82 MB |
| Output SHA-256 | `22110e49d0276eeed1153fe16ddf00a2a87c49a379ece7363a84cfdca2cb1ef9` | identical |

**Deterministic comparison:** `cmp` exit 0 — the two outputs are
**byte-identical** (identical SHA-256, identical byte length, identical flag
counts, identical ordering, both reconciliation PASSED). Evidence:
`11_largest_safe_execution_3m/byte_comparison/comparison.txt`.

## 5. Independent Verification

Verifier: `04_independent_verification/independent_verifier.py` — stdlib only,
**zero production imports** (grep-verified), all 8 predicates independently
re-implemented from the frozen V1 specification; 51-entry prefix map and
suspicious-name patterns transcribed as data constants.

Checks performed on BOTH run outputs (streaming, row-by-row):

| Check | Run 1 | Run 2 |
|---|---|---|
| Rows checked | 3,000,000 | 3,000,000 |
| Flag comparisons (rows × 8) | **24,000,000** | **24,000,000** |
| Flag value mismatches | **0** | **0** |
| Flag domain errors (non-0/1) | 0 | 0 |
| IDs strictly sequential/complete | yes | yes |
| Source-column preservation (33 cols, exact strings) | 0 errors | 0 errors |
| Extra/missing output rows | 0 | 0 |
| Reconciliation deltas (8 flags) | **all 0** | **all 0** |
| Lineage cross-check (flag-event sum) | 6,767,852 == `total_row_records` | 6,767,852 == `total_row_records` |
| Overall | **ALL_CHECKS_PASS** | **ALL_CHECKS_PASS** |

Total across both runs: **48,000,000 comparisons, 0 mismatches.**

Per-flag reconciliation (pipeline count == independent count, delta 0):
first_name_cleaning_candidate 317,185 · last_name_cleaning_candidate 210,603 ·
name_cleaning_candidate 91,020 · email_blank 240,000 ·
email_syntax_failure 210,000 · proposed_email_export_eligible 2,550,000 ·
zip_state_assessable 3,000,000 · geography_mismatch_candidate 149,044.
Flag-event sum: 6,767,852 — exactly equal to the pipeline lineage
`total_row_records` (a cross-system consistency check the pipeline itself
does not perform).

## 6. Test Suite

Command: `python -m pytest -q -rs` (captured 2026-09-09,
`12_test_suite/pytest_full_rs.txt`):

| Collected | Passed | Skipped | Failed | Errors | Duration |
|---|---|---|---|---|---|
| 331 | 322 | 9 | 0 | 0 | 4.63 s |

Every skip attributed (captured in the same file):
- 7 × `tests/golden/test_dl_canonical_geography.py` — DL001–DL015
  COMPANY-GATED: authoritative acceptance table is external company evidence,
  never reconstructed locally.
- 1 × ClickHouse runtime — Docker/ClickHouse unavailable.
- 1 × Airflow runtime — Airflow not installed; DAG statically verified only.

Golden fixture hashes unchanged (frozen V1 semantics intact):
`9ff2364f` (golden_cases.csv) · `fd2d9783` (expected_results.csv) ·
`c5084feb` (geography_edge_cases.csv).

## 7. Requirement Alignment

Central mapping — see `docs/EVIDENCE_COVERAGE.md` (23 requirements ×
implementation/test/independent-verification/runtime/evidence/claim-strength/
status, one row each).

## 8. V1 Geography

Frozen V1 prefix-map semantics only (full report:
`evidence/final_5m_execution/07_geography/GEOGRAPHY_V1_RESULTS.md`):

- `zip_state_assessable` = 3,000,000 / 3,000,000 — **"100% assessable under
  the frozen V1 prefix-map predicate"** (this is the only "100%" claim; V1
  does not perform strict ZIP5 canonical validation, so "100% valid ZIPs" is
  never stated).
- `geography_mismatch_candidate` = **149,044** (4.9681%) — reported strictly
  as **"V1 prefix-map geography mismatch candidates"**, never as canonical
  USPS errors or confirmed geographic errors.
- Frozen limitations verified present and disclosed: 13 ambiguous prefixes,
  DC duplicate `"20","20"` map entry, 11 authoritative territory/military
  codes absent from the frozen V1 map (8 territory codes + 3 military/APO/FPO
  codes; none of the 11 occurs in the generated dataset, which emits
  50 states + DC), None-string quirk, documentation-only exclusion policy,
  known Austin false-positive golden cases.
- Observed mismatch count (149,044) is 956 below the generator's nominal 5%
  injection (150,000) — a direct consequence of V1's ambiguous-prefix match
  semantics; labeled as observed + arithmetically inferred, not per-row proven.

## 9. SP1

Isolated successor semantics; activation boundary verified by machine check
(`08_activation_boundary/SP1_NEGATIVE_ACTIVATION_PROOF.md`):
**REGISTERED = NO · ACTIVE = NO · DEFAULT = NO · AUTHORIZED = NO ·
PRODUCTION CALL SITES = 0 · PHYSICAL REFERENCE BOUND = NO.**
Runtime corroboration: both 3M success manifests carry exactly the 8 V1 rule
hashes; the independent V1-only recomputation matched all 48,000,000 flag
values. SP1 contract semantics remain tested (63/63) — reported as tested
semantics, never as physical canonical validation.

## 10. External / Company-Gated Dependencies

| Item | Status |
|---|---|
| DL001–DL015 | COMPANY-GATED — authoritative company fixtures/reference data unavailable (7 skip-gated tests; fixtures never fabricated) |
| ClickHouse | NOT RUNTIME EXECUTED — 0 connections, 0 mutation SQL; DDL templates only |
| Authoritative reference data | NOT AVAILABLE locally — company-supplied hashes verified by citation only |
| Airflow | STATICALLY VERIFIED (DAG = 6 tasks); runtime NOT EXECUTED |
| E1 | NOT IMPLEMENTED / NOT EXECUTED / NOT AUTHORIZED |
| 721,141,364 / 590,011,545 population figures | COMPANY-SUPPLIED / HISTORICAL / ARITHMETIC-ONLY / NOT LOCALLY REPRODUCED |

## 11. Security & Safety Boundaries

- No unauthorized mutation: `git diff` content sweep = 0 production code
  paths changed in this task (docs/evidence/scripts/.gitignore only).
- Frozen V1 semantics untouched: golden hashes identical; 322/322 executable
  tests pass unchanged.
- SP1 not activated (six negative properties, machine-verified).
- E1 not executed. ClickHouse never contacted (0 connections / 0 mutations —
  grep-swept again this pass: 0 hits).
- No fabricated evidence: every terminal output, hash, and timing in this
  pass is a captured artifact; the 5M failure is recorded verbatim, not
  normalized away.
- Security probe: 0 secret-like hits, 0 mutation-SQL hits
  (`12_test_suite/consolidation_probe.txt`).

## 12. Provenance & Reproducibility

- Single source of truth: `evidence/final_5m_execution/FINAL_RESULTS.json`
  (every number in this report traces to it or to a cited artifact).
- Exact commands + captured outputs: `03_run1/`, `05_run2/`,
  `11_largest_safe_execution_3m/{run1,run2}/` (command.txt +
  terminal_output.txt + runtime.txt + memory.txt + hashes.txt each),
  `02_dataset/dataset_generation_terminal.txt`,
  `06_performance/bench_*_terminal.txt`.
- Terminal reproduction procedure: `docs/REPRODUCIBILITY.md`.
- Dataset determinism: same-seed regeneration reproduces the input byte-for-byte;
  additionally the 3M dataset is the exact byte-prefix of the 5M dataset
  (same seed lineage; SHA-256 equality of `head -c 809834462` — free
  cross-scale determinism proof, `11_…/dataset_prefix_property.txt`).
- Memory measurement methods are labeled on every figure
  (`ru_maxrss`/VmHWM process peak vs tracemalloc object peak).

## 13. Evidence Coverage Matrix

See `docs/EVIDENCE_COVERAGE.md` — 23 requirement rows with claim-strength
classes A–F; every major project requirement appears exactly once.

## 14. Final Audit Decision Matrix

See `docs/FINAL_AUDIT_DECISION_MATRIX.md` — 22 areas with the mandatory
status vocabulary; final decision **PASS WITH DOCUMENTED LIMITATIONS**.

## 15. Limitations

1. **5M end-to-end execution failed on environment RAM** (kernel OOM kill at
   98.9% completion; 3,592,016 KiB anon-rss vs ~3,576 MB available; no swap;
   non-root). 5M is therefore the verified *dataset* scale, not the verified
   *execution* scale.
2. Engine total in-process memory is implementation-level **O(N)**
   (id_set + per-flag lineage records) — documented in the engine docstring,
   measured at ~713–732 KB per 1K rows (RSS basis). Single-box execution
   beyond ~3M rows requires memory headroom or a streaming-lineage variant
   (out of scope: frozen V1).
3. Canonical geography validation remains COMPANY-GATED (DL001–DL015 external;
   SP1 implemented but not authorized/activated).
4. ClickHouse/Airflow runtimes NOT EXECUTED here (environment).
5. Company 721M-scale figures are arithmetic-only here.
6. The 5M "mismatch-rate vs injected-rate" delta explanation (§8) is an
   observed + inferred account, not per-row intent proof (generator intent is
   not recorded in outputs).

## 16. Open Actions

1. To execute 5M+ end-to-end: provide an environment with ≥ ~4.6 GB free RAM
   (or enable swap / grant root for swapfile), then re-run the recorded
   commands from `docs/REPRODUCIBILITY.md` — no code change required.
2. Supply the authoritative DL001–DL015 acceptance table (company input) to
   un-gate 7 tests.
3. Company decision (pre-existing, F-07): whether the "R3 = R1 OR R2"
   contract text should be amended to match the implemented independent
   predicate (live counterexamples exist; behavior intentionally frozen).
4. Optional: streaming-lineage engine variant (design exists in
   ENGINEERING_RECOMMENDATIONS) to make O(1)-ish memory possible — requires
   explicit authorization since it touches frozen code paths.

## 17. Evidence Index

| Artifact | Path (relative to repo root) |
|---|---|
| Baseline forensics + feasibility probes | `evidence/final_5m_execution/00_baseline/` |
| Reporting forensic audit | `evidence/final_5m_execution/01_reporting_audit/REPORTING_FORENSIC_AUDIT.md` |
| 5M dataset evidence | `evidence/final_5m_execution/02_dataset/` |
| 5M Run 1 failure evidence (incl. dmesg) | `evidence/final_5m_execution/03_run1/` |
| 5M Run 2 not-executed decision | `evidence/final_5m_execution/05_run2/5M_RUN2_NOT_EXECUTED.md` |
| Independent verifier + results | `evidence/final_5m_execution/04_independent_verification/` |
| 3M flagship dual-run protocol | `evidence/final_5m_execution/11_largest_safe_execution_3m/` |
| Performance ladder + report | `evidence/final_5m_execution/06_performance/` |
| Geography V1 report + per-state data | `evidence/final_5m_execution/07_geography/` |
| SP1 activation boundary | `evidence/final_5m_execution/08_activation_boundary/` |
| Test suite captures | `evidence/final_5m_execution/12_test_suite/` |
| Consistency audit | `evidence/final_5m_execution/09_consistency/DOCUMENT_CONSISTENCY_REPORT.md` |
| Final terminal summary | `evidence/final_5m_execution/10_final_summary/FINAL_TERMINAL_SUMMARY.txt` |
| Single source of truth | `evidence/final_5m_execution/FINAL_RESULTS.json` |
| Evidence manifest | `evidence/final_5m_execution/MANIFEST.json` |
| Coverage + decision matrices | `docs/EVIDENCE_COVERAGE.md`, `docs/FINAL_AUDIT_DECISION_MATRIX.md` |
| Reproduction guide | `docs/REPRODUCIBILITY.md` |
| Final archive (current package, 2026-09-09 documentation consolidation) | `download/Data-Quality-Validation-Platform-5M-Revalidated-2026-09-09-v2.zip` (SHA-256 in `download/…-v2.zip.sha256` and `evidence/final_5m_execution/13_archive/archive_v2_sha256.txt`) |
| Prior package (task-time, preserved unmodified) | `download/Data-Quality-Validation-Platform-5M-Revalidated-2026-09-09.zip` (SHA-256 `51fdf65d…` in `13_archive/archive_sha256.txt`) |

## 18. Final Verdict

**PASS WITH DOCUMENTED LIMITATIONS** — the evidence supports exactly this
verdict and no stronger one:

- PASS: dataset forensics (5M + 3M), dual-run determinism (byte-identical),
  independent verification (48,000,000 comparisons / 0 mismatches),
  reconciliation (all deltas 0), test suite (322/9/0/0, all skips attributed),
  SP1 isolation, V1 geography semantics (frozen, qualified), consistency,
  manifest, archive.
- DOCUMENTED LIMITATIONS: 5M execution BLOCKED by environment memory with
  complete forensic evidence; company-gated canonical geography; ClickHouse /
  Airflow runtimes not executed; 721M figures company-supplied arithmetic
  only; O(N) engine memory disclosed with measurements.
- The verdict would upgrade to a full PASS only when a memory-capable
  environment re-runs the recorded 5M commands successfully (Open Action 1);
  it would be FAIL if any executed check had mismatched — none did.
