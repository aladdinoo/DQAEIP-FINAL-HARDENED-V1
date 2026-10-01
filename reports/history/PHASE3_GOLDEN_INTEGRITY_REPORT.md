# PHASE 3 — GOLDEN DATA INTEGRITY REMEDIATION REPORT

Repo: data-quality-platformV2 @ 4065714 (HEAD unchanged — no commits made)
Scope: forensic audit + minimal repair of golden fixtures, integrity test suite, oracle-gap remediation.
Safety: zero ClickHouse operations, E1 not executed, no production writes, historical evidence byte-identical to HEAD.

---

## 1. ORIGINAL FIXTURE HASHES (pre-remediation, preserved in immutable snapshot)

| Fixture | SHA-256 | Bytes |
|---|---|---|
| tests/golden/golden_cases.csv | `7af809acb1f75d59008eee2e7ef29ea3f5ba0aa27f2c55d15107e2a95ce79215` | 15164 |
| tests/golden/expected_results.csv | `13d05ebf26a20504472f4ced5a2c970354c3abe76b0de3b954b7b9bf965a0e4a` | 1377 |
| tests/golden/geography_edge_cases.csv | `c5084feb4d8f2cee6dbe4bab67fc3f8fb15f39d2098f7ab8c6a5a5c9d6b8406f` | 1458 |

Immutable snapshot (originals + per-row field counts + manifest): `/home/z/my-project/scratch/phase3/immutable_snapshot/` (outside tracked evidence; snapshot write is guarded — never overwritten once created).

## 2. FINAL FIXTURE HASHES (post-remediation)

| Fixture | SHA-256 | Status |
|---|---|---|
| tests/golden/golden_cases.csv | `9ff2364f6b283ad26612677af99a39905ef9587654f1cef03206db994b2bc23e` | REPAIRED (6 lines changed) |
| tests/golden/expected_results.csv | `fd2d9783718c7bd60ee89615309a3f5708c8e3fa0401c8fdbdcc4ed9db3a63b2` | REPAIRED (1 row changed) |
| tests/golden/geography_edge_cases.csv | `c5084feb4d8f2cee6dbe4bab67fc3f8fb15f39d2098f7ab8c6a5a5c9d6b8406f` | UNCHANGED |
| tests/golden/test_golden_cases.py | `3f155b8bc4a5ff4099ead2cf16a4661486519c3c25810d6cf2b43f7e408a68b7` | UNCHANGED |

## 3. EVERY MALFORMED ROW (with exact corruption operations, LCS-proven)

| Row | Line | Fields | Corruption (raw → intended) |
|---|---|---|---|
| GC022 "Blank email and blank names" | 23 | **46** (header 43) | Empty `last_name` field OMITTED + 4 spurious empty fields inserted (difflib minimal script: 1 insert, 4 deletes). Everything from `last_name` shifted left: state←"85001", zip←"web.net". The intended 8-value inline vector (0,0,0,1,0,0,1,0) was visible verbatim in the raw overflow tail. |
| GC050 "Valid all fields populated" | 51 | **45** (header 43) | 2 spurious fields ("51","52") inserted between `interest_ids` and `DNC`. State/zip intact; norms + inline expected columns shifted right by 2 ("user","73344" landed in expected_first/last_name columns; overflow [1,0]). |

All other 48 rows: 43 fields exactly. expected_results.csv: 50/50 rows well-formed (9 fields). geography_edge_cases.csv: 20/20 rows well-formed (10 fields).

## 4. EVERY EXPECTED-VALUE DISCREPANCY (15 found inline-vs-file, pre-repair)

GC011×1, GC022×5, GC030×1, GC032×1, GC037×2, GC041×1, GC050×4 (full list in `scratch/phase3/forensic_snapshot.json`). Post-repair a 16th contradiction became VISIBLE: GC050 `geography_mismatch` inline=0 vs file=1 had been MASKED by the field shift (DictReader read the shifted "1" into the inline slot).

## 5. CLASSIFICATION OF EACH DISCREPANCY (per the 6 allowed classes)

| Class | Cells | Disposition |
|---|---|---|
| 1. fixture corruption (shift artifacts) | GC022 first/last/name/email_blank/zip_state inline (5); GC050 first/last/proposed/zip_state inline (4) | Resolved by structural repair of the two rows |
| 2. expected-result corruption | GC022 file `last_name_cleaning=1`, `zip_state_assessable=0` — PROVEN codified from the corrupted shifted row (impl-on-corrupted reproduced the file row 8/8; see Step-2 proof) | File row repaired to independently derived values `0,0,0,1,0,0,1,0` |
| 3. test interpretation bug | DictReader silent restval/restkey tolerance (the mechanism that let corrupted rows pass); positional `cases[i]` access without order pin | Fixed by integrity tests (strict loader + order pin); test_golden_cases.py itself unchanged |
| 4. implementation bug | none found in V1 rules (file+impl agree on all 50×8 cells post-repair) | — |
| 5. contract ambiguity | GC011, GC037, GC050 `geography_mismatch`: inline=0 (real-world Austin TX 733xx intent) vs file=1 & impl=1 (legacy 2-digit prefix map assigns 73→OK) | **Carried conflict — STOP per Step 10**, resolution = canonical geography (Phase 6); pinned as `CARRIED_GEOGRAPHY_CONFLICTS` tripwire |
| 6. unresolved | none beyond the 3 carried cells | — |

Additional stale-annotation sub-class (file+impl agree, inline stale — repaired inline): GC030 first_clean 0→1 ('Nancy' contains pattern "na"), GC032 last_clean 0→1 ('Hernandez' ⊃ "na"), GC037 first_clean 0→1 ('Donald' ⊃ "na"), GC041 name_clean 1→0 ('test'≠'fake'). Observation recorded: the contract's `"na"` substring pattern matches inside legitimate names (Nancy/Hernandez/Donald) — potential false-positive class, noted for FALSE_POSITIVE_REVIEW follow-up, NOT changed (implementation changes are out of Phase 3 scope).

## 6. EXACT FILES CHANGED

- `tests/golden/golden_cases.csv` — 6 lines (GC022, GC050 structural; GC030/GC032/GC037/GC041 inline cells)
- `tests/golden/expected_results.csv` — 1 row (GC022)
- `tests/golden/test_golden_fixture_integrity.py` — NEW integrity test suite (15 tests)
- (Phase 2 files unchanged in this phase: runner/cli.py, data_quality_platform/verification/*, tests/unit/test_q21_scope_aggregation.py)

## 7. BEFORE/AFTER ROW-LEVEL CHANGES (complete)

```
GC022 BEFORE (46 fields): GC022,Blank email and blank names,22,,,456 Elm St,Phoenix,Maricopa County,AZ,85001,web.net,,F,2000-02-29,2024-10-01,0,,email_22,,,,web.net,,,,32.7157,-112.0740,2024-10-01,US,22,22,0,web,,,,,85001,0,0,0,1,0,0,1,0
GC022 AFTER  (43 fields): GC022,Blank email and blank names,22,,,,456 Elm St,Phoenix,Maricopa County,AZ,85001,web.net,,F,2000-02-29,2024-10-01,0,,email_22,,,web.net,,,32.7157,-112.0740,2024-10-01,US,22,22,0,web,,,85001,0,0,0,1,0,0,1,0
  (empty last_name restored at position 6; 4 spurious empties removed; email='' first='' last='' state='AZ' zip='85001')

GC050 BEFORE (45 fields): ...,US,50,50,51,52,0,web,complete,user,73344,0,0,0,0,0,1,1,0
GC050 AFTER  (43 fields): ...,US,50,50,0,web,complete,user,73344,0,0,0,0,0,1,1,0
  (spurious "51","52" removed; DNC=0, source=web, norms=complete/user/73344)

GC030 inline: expected_first_name_cleaning_candidate 0→1 (rule contract: 'Nancy' ⊃ "na")
GC032 inline: expected_last_name_cleaning_candidate  0→1 (rule contract: 'Hernandez' ⊃ "na")
GC037 inline: expected_first_name_cleaning_candidate 0→1 (rule contract: 'Donald' ⊃ "na")
GC041 inline: expected_name_cleaning_candidate       1→0 (rule contract: first≠last, not both single-char)

expected_results.csv GC022 row:
  BEFORE: GC022,0,1,0,1,0,0,0,0   (codified corrupted row: last_name='456 Elm St'→1, state='85001'→assessable=0)
  AFTER : GC022,0,0,0,1,0,0,1,0   (rule contract on intended row: blank names→0/0/0, blank email→1, AZ∈map+85001⊃'85'→assessable=1, mismatch=0)
```

## 8. TESTS ADDED — tests/golden/test_golden_fixture_integrity.py (15 tests)

1. exactly 50 cases · 2. header contract (43 columns, data columns == SOURCE_COLUMNS) · 3. every row 43 fields · 4. strict DictReader load (no restval-None / restkey-overflow — the exact historical failure mode) · 5. case IDs unique · 6. case IDs canonical GC001–GC050 sequence (pins positional access) · 7. expected IDs match golden IDs both directions · 8. exactly one expected result per case · 9. expected values conform to the rule contract via the REAL registry (with pinned carried-conflict tripwire) · 10. inline annotations consistent except the 3 pinned carried cells · 11. loader-target pin (golden tests read golden_cases.csv + expected_results.csv) · 12. positional-access alignment (each spot-checked position maps to the intended case and passes) · 13. strict-loader rejects a deliberately malformed GC022 probe (proves detection power) · 14. deterministic rerun identical · 15. geography_edge_cases: structure + first-ever automated execution (20/20 conform to implementation).

## 9. FOCUSED TEST RESULTS

- tests/golden/ (golden cases + integrity + DL skip-gates): **25 passed, 7 skipped, 0 failed**
- Geography-focused (unit rules + golden + integrity): **79 passed, 0 failed**

## 10. FULL PYTEST RESULT

**228 passed, 9 skipped, 0 failed, 0 errors** (Phase 2 baseline 213+9sk; +15 integrity tests; the 9 skips are the pre-existing skip-gated DL/runtime tests, none newly skipped; no assertion weakened).

## 11. FRESH Q1–Q22 VERIFICATION (scratch evidence dir)

`python -m runner.cli verify --evidence-dir <scratch>` → **20 PASS, 2 PARTIAL, 0 FAIL** — Q18 = PARTIAL (production IAM, unchanged), Q21 = PARTIAL (computed aggregation, unchanged policy).

## 12. Q14 STATUS AFTER REMEDIATION

**PASS — now substantively proven, not merely counted.** Q14's harness check still reads "50 golden cases", but the integrity suite now proves: exactly 50 well-formed 43-field rows, unique canonical IDs, 1:1 expected mapping, every expected value conforming to the live rule contract, strict-parse cleanliness, and deterministic evaluation. The historical caveat ("50 rows includes 2 structurally misaligned rows") is CLOSED.

## 13. DO GOLDEN TESTS GENUINELY EXERCISE golden_cases.csv?

**YES** — `test_all_50_cases_all_rules` executes the real registry on every golden row and compares against expected_results.csv (true oracle chain: input → rule execution → expected → assertion). The audit DID find and close three oracle weaknesses: (a) DictReader silently tolerated malformed rows and the corrupted rows' shifted views were codified into the expected file (the suite stayed green through corruption — proven by impl-on-corrupted == file 8/8 for both rows); (b) positional indexing was unpinned (now pinned); (c) the inline expected_* columns were dead, contradictory annotations (now consistent except the 3 pinned carries). The tests do NOT depend on a duplicated rule implementation — they consume `RuleRegistry.create_default()`.

## 14. IS geography_edge_cases.csv ACTUALLY TESTED?

**Historically NO** — zero pytest consumers; only presence-checks (runner/cli.py Q22, scripts/run_final_verification.py). **Now YES** — two integrity tests validate its structure and execute all 20 rows against the geography rules (20/20 conform). It does not overlap by case ID with golden_cases (GEO001–020 vs GC001–050); value-level overlaps exist (e.g., AZ/85001 in both) but no duplicated expected-value conflicts. Semantics are current, not stale. Not deleted, not merged.

## 15. HISTORICAL EVIDENCE INTEGRITY RESULT

All 6 checked artifacts byte-identical to HEAD (SHA-256 vs `git cat-file`): verification_report.json/.md (restored after the known cli.py:121–126 regeneration side effect), final_verification/manifest.json, benchmarks/benchmark.json, VERIFICATION_MATRIX.json, FINAL_VERIFICATION.json. The pre-remediation fixture state is preserved in the immutable snapshot + git HEAD.

## 16. CLICKHOUSE SAFETY PROOF

`curl localhost:8123/ping` → exit 7 (no server reachable — unchanged environment state). Zero ClickHouse statements in any Phase 3 change. No production/reference data touched (git diff shows only the two fixture files + test file + prior-phase files).

## 17. E1 SAFETY PROOF

E1 was not executed. No extraction/pipeline script was run against any data source in Phase 3; only pytest, the verify CLI, and read-only Python analyses.

## 18. REMAINING BLOCKERS / AMBIGUITIES

1. **3 carried geography conflicts** (GC011/GC037/GC050 `geography_mismatch`, inline=0 vs file=1/impl=1): require canonical geography semantics + reference provenance (Phase 6; the cross-reference provenance chain remains BLOCKED from the earlier task). Pinned by test tripwire `CARRIED_GEOGRAPHY_CONFLICTS` so they cannot drift silently.
2. **"na" substring aggressiveness** ('Nancy'/'Hernandez'/'Donald' flagged as suspicious names): documented observation; any change is an implementation-contract decision outside Phase 3 authorization.
3. golden_cases.csv has no trailing newline (pre-existing cosmetic property, deliberately preserved).

## 19. IS PHASE 4 SAFE TO BEGIN?

**YES.** Golden fixtures are internally coherent, structurally valid, and correctly interpreted; the remediation evidence path (Phase 4) can proceed without touching historical artifacts. Phase 4 must continue to leave the stale committed manifest rule-hashes as-is (disclosed conflict #3 from the audit) and build the new evidence generation path alongside.

---
Integrity recomputation (independent of pytest): ALL CHECKS PASS (`scripts/phase3_step8_6_recompute.py`).
