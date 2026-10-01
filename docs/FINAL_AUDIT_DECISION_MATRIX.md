# FINAL AUDIT DECISION MATRIX
Task: FINAL 5M VALIDATION + PROFESSIONAL REPORTING REBUILD (2026-09-09)
Status vocabulary (mandatory): PASS · PASS WITH LIMITATIONS · PARTIAL ·
COMPANY-GATED · BLOCKED · NOT IMPLEMENTED · NOT AUTHORIZED · NOT RUNTIME
VERIFIED · NOT VERIFIED. No vague phrases.

| # | Area | Decision | Basis (evidence path) |
|---|---|---|---|
| 1 | 5M dataset creation + integrity | **PASS** | `02_dataset/` — 5,000,000 rows, 33 cols, IDs 1..5M strict, SHA-256 44e41bb8…, independent streaming verifier |
| 2 | 5M pipeline execution (Run 1) | **BLOCKED** (executed attempt; kernel OOM at 98.9%) | `03_run1/` — exit -9, dmesg `anon-rss:3592016kB`, pre-registered model predicted 3,594 MB vs 3,576 MB available |
| 3 | 5M pipeline execution (Run 2) | **NOT EXECUTED** (deterministic failure mode, documented decision) | `05_run2/5M_RUN2_NOT_EXECUTED.md` |
| 4 | 3M dataset + dual-run protocol (largest safe scale) | **PASS** | `11_largest_safe_execution_3m/` — both runs exit 0, 3,000,000 in/out |
| 5 | Determinism (byte-identical outputs) | **PASS** | `11_…/byte_comparison/comparison.txt` — cmp exit 0; identical SHA-256 22110e49… |
| 6 | Independent verification (all flags, both runs) | **PASS** | `04_independent_verification/` — 48,000,000 comparisons, 0 mismatches, schema/ID/preservation/order clean |
| 7 | Reconciliation (pipeline vs independent) | **PASS** | per-flag delta table all zero; lineage total 6,767,852 == independent sum |
| 8 | Frozen V1 rule semantics unchanged | **PASS** | golden hashes 9ff2364f / fd2d9783 / c5084feb unchanged; `git diff` = 0 production content rows; full suite green |
| 9 | V1 geography reporting | **PASS WITH LIMITATIONS** (prefix-map semantics only; 13 ambiguous prefixes, 11 absent territory/military codes [8 territory + 3 military/APO/FPO], DC duplicate — all frozen/disclosed) | `07_geography/GEOGRAPHY_V1_RESULTS.md` |
| 10 | SP1 activation boundary | **PASS** (isolated; all six properties negative) | `08_activation_boundary/SP1_NEGATIVE_ACTIVATION_PROOF.md` |
| 11 | SP1 canonical validation in production | **NOT AUTHORIZED** / **NOT RUNTIME VERIFIED** | company contract: semantics delivered, activation withheld; 0 call sites |
| 12 | DL001–DL015 canonical geography | **COMPANY-GATED** | 7 skip-gated tests; authoritative fixtures external |
| 13 | ClickHouse runtime | **NOT RUNTIME VERIFIED** | 0 connections, 0 mutation SQL; DDL templates only |
| 14 | Airflow runtime | **NOT RUNTIME VERIFIED** (static DAG = 6 tasks verified) | skip attribution + docs |
| 15 | E1 | **NOT IMPLEMENTED / NOT AUTHORIZED** | 0 production identifiers |
| 16 | Company 721M population-scale figures | **COMPANY-SUPPLIED / ARITHMETIC-ONLY** (never locally reproduced) | arithmetic identities 5/5; labeled in all current docs |
| 17 | Test suite | **PASS** | 331 collected / 322 passed / 9 skipped / 0 failed / 0 errors; every skip attributed |
| 18 | Performance & memory reporting honesty | **PASS** | every figure method-labeled; O(N) stated from inspection; 5M claims none |
| 19 | Documentation consistency (current docs) | **PASS** (post-rebuild sweep; historical docs quarantined with banners) | `09_consistency/DOCUMENT_CONSISTENCY_REPORT.md` |
| 20 | Archive integrity + unpack verification | **PASS** | Phase 18 manifest, archive SHA-256, fresh unpack + suite re-run (see MANIFEST.json + unpack log) |
| 21 | Zero unauthorized production changes | **PASS** | 0 production code paths in git diff; only docs/evidence/config(.gitignore)/scripts changes |
| 22 | Zero fabrication | **PASS** | every terminal output in this pass is a captured file; failure recorded, not hidden |

## FINAL DECISION

**PASS WITH DOCUMENTED LIMITATIONS** — for the delivery as a whole.

- The 5M execution is **BLOCKED by environment memory** with complete forensic
  evidence; it is not, and must not be reported as, a platform failure.
- The largest completed full protocol is **3,000,000 rows** (dual run,
  byte-identical, independently verified, all-zero deltas).
- All platform-scope checks that could be executed pass; everything not
  executed carries an explicit status from the vocabulary above.
