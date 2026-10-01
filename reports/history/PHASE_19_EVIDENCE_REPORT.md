# PHASE 19 — CANONICAL GEOGRAPHY CONTRACT RECONCILIATION — EVIDENCE REPORT

**Phase type:** READ-ONLY / DOCUMENTATION-FIRST / NO BEHAVIORAL IMPLEMENTATION
**Report date:** 2026-09-07
**Repository:** `/home/z/my-project/data-quality-platformV2`

---

## 1. Scope

Reconcile the newly issued canonical Geography rule contract ("Geography rule — canonical definition and acceptance cases", supplied through the authoritative company instruction channel in the Phase 19 brief) against the current repository implementation and documentation. The phase covered: contract extraction, implementation location, a 21-element semantic reconciliation matrix, SP1 verification against the contract, two-reference semantics verification, the 62-code allowlist comparison, the seven acceptance cases, the SP1 policy supersession, V1 preservation, authorization boundaries, documentation-only remediation, test safety, and git integrity. No production behavior was implemented or modified; SP1 was not activated; E1 was not executed; no ClickHouse mutation occurred; nothing was committed or pushed.

## 2. Baseline commit

| Item | Value | Verified |
|---|---|---|
| HEAD | `a5ec759f069c2c8aeea72b147437f1b8b22756d9` | `git rev-parse HEAD` — matches expected reviewed HEAD |
| Parent | `2a8b7e12914d64ec3fc151d8b97710697c06e22e` | verified |
| origin/main | `4065714c3c810c503020d60a8f726a485a5e09ac` | 6 local commits ahead, unpushed |
| Pre-existing working-tree state | README.md content rebuild (+1139/−544, Task 17 legacy) + untracked `FINAL_IMPROVEMENT_REPORT.md` (509 lines) + 201 files mode-only drift (100644→100755, environment chmod artifact) | `git diff --numstat` filtered: README.md is the ONLY content-changed tracked file before this phase's documentation edit |

Frozen evidence integrity: golden fixture SHA-256s re-computed this phase — `tests/golden/expected_results.csv` = `fd2d9783…`, `golden_cases.csv` = `9ff2364f…`, `geography_edge_cases.csv` = `c5084feb…` — identical to the PHASE 18 frozen records; zero fixture drift. No STOP condition triggered.

## 3. Contract version/date (extraction record)

The authoritative contract was extracted from the Phase 19 brief and cross-checked against the repository's pinned provenance:

| Contract element (brief item) | Extracted value | Repository pin |
|---|---|---|
| A. SP1 policy | exclude when geography_mismatch_candidate = 1 OR NOT field_present(requested geography field) | `canonical.py:407-413` (SP1Decision docstring), `sp1_eligibility` 434–460; `docs/GEOGRAPHY_RULE_SP1_CONTRACT.md` §2 verbatim |
| B. Assessability | reference_resolved AND NOT blank_state AND NOT invalid_state_format AND NOT numeric_state_review AND NOT unknown_state_code | `canonical.py:301-307` |
| C. ZIP normalization | zip5 = trimmed zip if ^[0-9]{5}$ else '' | `compute_zip5`, `canonical.py:127-132`, `_ZIP5_RE` line 110 |
| D. Reference resolution | reference_resolved = zip5 != '' AND canonical_state_count = 1 AND cross_state_count <= 1 AND (cross_state_count = 0 OR canonical_state = cross_state) | `resolve_reference`, `canonical.py:198-229`; `ReferenceResolution` docstring 183–187 |
| E. State conditions | blank_state / invalid_state_format / numeric_state_review / unknown_state_code | `canonical.py:139-167` |
| F. Two-reference requirement | canonical reference + independent cross reference, five-digit-ZIP + two-letter-state filtering, grouped by ZIP | `references.py:62-131` |
| G. 62-code allowlist | 62 codes incl. territories/military | `STATE_ALLOWLIST`, `canonical.py:85-101` |
| H. field_present | zip/state/city/address defined; per-field evaluation | `canonical.py:357-396` |
| I. county/country | NOT DEFINED by this rule set | `FieldPresenceNotDefinedError`, `canonical.py:340-347, 389-396` |
| J. Acceptance cases | the seven cases (CA/90210 … GU/96910) | `tests/unit/test_sp1_geography_contract.py:97-154` |
| K. Mismatch assessability | mismatch predicate contains the assessability conjunction | `canonical.py:309-314`: `mismatch = assessable AND state_code != canonical_state` |

Contract provenance pins in code: title/prepared 2026-09-01/measurements 2026-08-31 and company-provided SHA-256 `0cf6eb93…ada311bc0` at `canonical.py:54-64` — identical to the brief's document identification. The physical document was never present in the environment; its SHA-256 could not be re-computed locally (recorded honestly at `canonical.py:12-16` and contract doc §1).

## 4. Semantic reconciliation matrix

Legend: Match / Partial / Mismatch / Missing. "Impl. authorized?" = whether production implementation of that element is authorized (APPROVED SEMANTICS != IMPLEMENTATION AUTHORIZATION).

| # | Contract element | Current repository behavior | Status | Evidence | Impl. authorized? | Required future action |
|---|---|---|---|---|---|---|
| 1 | 62-code allowlist | `STATE_ALLOWLIST` = 62 codes, sorted, duplicate-free, 11 territory/military + DC | **Match** | probe §2 output; `test_allowlist_is_verbatim_and_includes_territories` | Semantics approved; production use NOT authorized | None semantic; activate only under production authorization |
| 2 | ZIP ^[0-9]{5}$ validation | `compute_zip5` strict regex, else '' | **Match** | `canonical.py:110,127-132`; `TestNormalization.test_zip5` | No (SP1 not active) | None |
| 3 | State normalization (upper-case) | `normalize_state` = text → trim → upper | **Match** | `canonical.py:122-124`; `test_normalize_state_uppercased` | No | None |
| 4 | null → empty string | `normalize_text(None) == ''` | **Match** | `canonical.py:115-119`; `test_normalize_text_null_and_whitespace` | No | None |
| 5 | Trimming | `str(value).strip()` in `normalize_text` | **Match** | same | No | None |
| 6 | Uppercase state comparison | `state_code = state_text.upper()` before all comparisons | **Match** | `canonical.py:290-291` | No | None |
| 7 | Canonical reference resolution | exact contract formula in `resolve_reference` | **Match** | `canonical.py:198-229` | No | Requires physical canonical dataset + authorization |
| 8 | Cross-reference conflict handling | cross ≠ canonical or cross_count ≥ 2 → unresolved → not assessable; cross_count = 0 → NOT a conflict (GU case) | **Match** | `canonical.py:217-221`; `test_reference_conflict_is_not_assessable`, `test_cross_row_absent_resolves_gu_case` | No | None |
| 9 | zip_state_assessable | exact five-clause conjunction | **Match** | `canonical.py:301-307` | No | None |
| 10 | geography_mismatch_candidate (canonical mismatch) | `mismatch = assessable AND state_code != canonical_state` (mismatch ⇒ assessable; 13-probe sweep: 0 violations) | **Match** (naming note below) | `canonical.py:309-314`; `test_mismatch_implies_assessable_everywhere` | No | None |
| 11 | field_present(zip) = zip5 != '' | exact | **Match** | `canonical.py:374-375`; `test_zip_presence_uses_zip5` | No | None |
| 12 | field_present(state) = NOT blank AND NOT invalid AND NOT numeric AND NOT unknown | exact | **Match** | `canonical.py:376-384`; `test_state_presence_uses_classifiers_only` | No | None |
| 13 | field_present(city) = NOT blank_city | `normalize_text(city) != ''` | **Match** | `canonical.py:385-386`; `test_city_and_address_use_blankness_only` | No | None |
| 14 | field_present(address) = NOT blank_address | `normalize_text(address) != ''` | **Match** | `canonical.py:387-388` | No | None |
| 15 | county/country undefined | refused with `FieldPresenceNotDefinedError`; no invented predicates (unknown fields also refused) | **Match** (NOT DEFINED honored) | `canonical.py:340-396`; `test_county_and_country_are_not_defined`, `test_unknown_field_refused` | No | Contract extension needed before any predicate may exist |
| 16 | SP1 selection policy (NEW: exclude mismatch=1 OR NOT field_present) | implemented in `sp1_eligibility`; old policy (assessable=0 OR mismatch=1) superseded, reproduced only as divergence evidence | **Match** | `canonical.py:434-460`; `TestSP1Eligibility`, `TestOldVsSuccessorDivergence` | NOT AUTHORIZED (activation) | Explicit registry swap + activation after authorization |
| 17 | Acceptance cases (7) | 7/7 via tests and independent probe | **Match** | §9 below | No | None |
| 18 | SP1 registration | not registered (`create_default()` = exactly 8 V1 rules; AST scan of engine/registry/base/CLI/DAG clean) | **Match** (boundary respected) | §5, probe §7 | REGISTRATION NOT AUTHORIZED | Future: explicit, non-silent registration under authorization |
| 19 | SP1 activation | not active; isolated behind injectable provider; tripwire test | **Match** (boundary respected) | README §23; `test_module_does_not_import_legacy_prefix_map` | ACTIVATION NOT AUTHORIZED | Future: activation preconditions (contract doc §8) |
| 20 | V1 default behavior | V1 prefix-map rules registered, default, unchanged; fixtures byte-identical to HEAD | **Match** (intentionally unchanged) | §10 below | V1 change NOT AUTHORIZED | None |
| 21 | Two-reference model | interface + filtering + grouping + conflict rule | **Match** | `references.py:62-131` | No | Physical datasets required |

**Naming observation (not a defect):** the canonical mismatch predicate is named `zip_state_mismatch` in `GeographyAssessment` while the contract's selection language calls it `geography_mismatch_candidate`; `sp1_eligibility` maps it to the exclusion reason string `"geography_mismatch_candidate=1"` (`canonical.py:446-452`). Separately, the V1 registry retains a *different* predicate with the same rule id (`GeographyMismatchCandidate`, prefix-map based, production-registered). The two contexts are isolated; semantics match the contract exactly. No escalation required.

## 5. SP1 comparison (where semantics live, who imports whom)

1. **V1 geography semantics:** `data_quality_platform/rules/v1_rules.py` — `ZipStateAssessable.execute` (v1_rules.py:254–260: non-empty zip + non-empty state + state in `STATE_ZIP_PREFIXES` → 1) and `GeographyMismatchCandidate.execute` (v1_rules.py:284–296: prefix probe). Knowledge base: `STATE_ZIP_PREFIXES` (`contracts.py:47-67`, 51 entries, DC `["20","20"]` duplicate, 13 cross-state ambiguous prefixes, 8 territory/military codes absent).
2. **SP1 semantics:** `data_quality_platform/geography/canonical.py` (pure) + `data_quality_platform/geography/references.py` (provider interface + controlled-fixture provider).
3. **Does V1 import/call SP1?** No. Grep + AST sweep: the only importers of `data_quality_platform.geography` are the package itself and `tests/unit/test_sp1_geography_contract.py`. AST scan of `engine.py`, `registry.py`, `base.py`, `runner/cli.py`, `airflow/dags/dq_validation_dag.py`: **CLEAN** (no `geography.canonical`, `sp1_eligibility`, `evaluate_geography`, `field_present`, `TwoReferenceProvider`).
4. **Registered?** No — `RuleRegistry.create_default()` (`registry.py:39-54`) instantiates exactly 8 V1 rules; probe confirmed ids and count = 8, zero sp1/canonical ids.
5. **Active?** No. 6. **Default?** No — V1 remains the default path. 7. **Production execution path invoking SP1?** None exists.

## 6. field_present comparison (brief §4)

| Field | Contract | Implementation (`canonical.py`) | Probe result | Test coverage | Discrepancy |
|---|---|---|---|---|---|
| zip | zip5 != '' | `compute_zip5(row.get("zip")) != ""` | valid-state+malformed-zip row → False; `90210`/`" 90210 "` → True | `test_zip_presence_uses_zip5` | **None** |
| state | NOT blank AND NOT invalid_format AND NOT numeric AND NOT unknown | negated 4-classifier conjunction | True for valid state on same malformed-zip row | `test_state_presence_uses_classifiers_only` | **None** |
| city | NOT blank_city | `normalize_text(city) != ''` | True (non-blank) | `test_city_and_address_use_blankness_only` | **None** |
| address | NOT blank_address | `normalize_text(address) != ''` | True (non-blank) | same | **None** |
| county / country | NOT DEFINED | raises `FieldPresenceNotDefinedError` (also for unknown fields) | refused ×3 (county, country, region) | `test_county_and_country_are_not_defined`, `test_unknown_field_refused` | **None** — no predicates invented |

Per-field semantics (contract example: valid state + malformed ZIP → state-present / zip-absent) verified live in probe §3 and `test_per_field_example_from_contract`. **No code alteration was needed; no discrepancy exists.**

## 7. Two-reference comparison (brief §5)

| Contract requirement | Implementation | Evidence |
|---|---|---|
| Canonical reference resolves canonical state | `TwoReferenceProvider.canonical_states(zip5)` | `references.py:72-73` |
| Independent cross reference | `cross_states(zip5)` — separate index | `references.py:75-76, 119-125` |
| Five-digit ZIP filtering | rows kept only if trimmed zip matches `^[0-9]{5}$` | `references.py:79-99` (`_filter_reference_rows`); `test_reference_rows_filtered_to_zip5_and_two_letter_state` |
| Two-letter state filtering | rows kept only if upper-cased state matches `^[A-Za-z]{2}$` | same |
| Grouping by ZIP | `zip5 → ordered distinct states` buckets | `references.py:88-99` |
| canonical_state_count = 1 | `canonical_count == 1` else unresolved | `canonical.py:217-221`; `test_canonical_ambiguity_is_not_resolved` |
| cross_state_count <= 1 | `cross_count <= 1` clause | `canonical.py:219`; `test_cross_ambiguity_is_not_resolved` |
| cross_state_count = 0 OR canonical_state = cross_state | exact disjunction; GU/96910 (no cross row) resolves | `canonical.py:220`; `test_cross_row_absent_resolves_gu_case` |
| Conflict → not assessable | unresolved reference fails the assessability conjunction; conflict is never a mismatch | `test_reference_conflict_is_not_assessable` (also asserts SP1-eligible when state present — UNASSESSABLE ≠ MISMATCH) |

**The repository implementation does not differ from the contract; nothing needed replacing.** Physical datasets remain absent by design (`ReferenceUnavailableError`; no fabrication), so canonical *production* validation remains BLOCKED (contract doc §8).

## 8. 62-code comparison (brief §6)

| Check | Result |
|---|---|
| Exact count | **62** |
| Missing codes vs authoritative 62 | **none** |
| Extra codes | **none** |
| Duplicates | **none** |
| Ordering | strictly alphabetical; **order-identical** to the authoritative list (`repo == authoritative_62 → True`) |
| Territories/military represented | **yes — 11/11**: AA, AE, AP, AS, FM, GU, MH, MP, PR, PW, VI (+ DC) |
| Composition | 50 states + DC + military (AA/AE/AP) + territories (AS/GU/MP/PR/VI) + freely-associated (FM/MH/PW) = 62 |

⚠ **Precision note on the brief's §6 enumeration:** the code list as typed in the Phase 19 brief contains **61** codes — `TX` is absent from the brief's inline list (rows end "…TN **UT**…"). The repository's list is 62 codes *including* TX, which matches the authoritative contract text pinned in `test_allowlist_is_verbatim_and_includes_territories` (test file lines 164–169) and `docs/GEOGRAPHY_RULE_SP1_CONTRACT.md` §3. Classified: **transcription omission in the task text, not a repository defect**; the repository value (62 incl. TX) is treated as authoritative and was NOT "corrected" downward.

Ordering/duplicate classification per the brief: the repo list has neither; a hypothetical ordering difference would not have been a semantic defect (set semantics) — recorded for completeness.

## 9. Acceptance-case results (brief §7)

Read-only verification performed two independent ways — (a) the existing test suite, (b) a direct probe against `evaluate_geography` using the same controlled fixtures (canonical: 90210→CA, 99501→AK, 96910→GU; cross: 90210→CA, 99501→AK; 96910 cross row intentionally absent) — with **zero code changes**:

| Case | assessable | match | mismatch | Expected | Result |
|---|---|---|---|---|---|
| CA / 90210 | true | true | false | true/true/false | **PASS** |
| CA / 00USA | false | false | false | false/false/false | **PASS** |
| CA / 0 | false | false | false | false/false/false | **PASS** |
| CA / 000CA | false | false | false | false/false/false | **PASS** |
| CA / "015 8" | false | false | false | false/false/false | **PASS** |
| WA / 99501 | true | false | true (canonical = AK) | true/false/true, AK | **PASS** |
| GU / 96910 | true | true | false (cross_count = 0, not a conflict) | true/true/false | **PASS** |

**7/7 PASS** in both the suite (`TestCompanyAcceptanceCases`, 7 tests) and the independent probe. Supporting invariants: mismatch ⇒ assessable (13-probe sweep, 0 violations); unassessable ⇒ never mismatch/match (8-probe sweep); assessment dict deterministic and frozen. Existing infrastructure executed the cases without modification — **no limitation to document, no behavioral change made**.

## 10. V1 preservation check (brief §9)

- V1 still uses its existing/default semantics: `ZipStateAssessable` / `GeographyMismatchCandidate` registered via `create_default()`; live probes confirmed legacy behavior (WA/99501 → assessable=1, mismatch=0; GU/96910 → assessable=0; CA/00USA → assessable=1, mismatch=1).
- `STATE_ZIP_PREFIXES` unchanged: content diff vs HEAD shows `contracts.py` byte-identical (mode-only drift).
- V1 not silently switched to canonical reference resolution: AST/registry proof in §5.
- Existing V1 acceptance expectations not rewritten: golden fixtures byte-identical to frozen PHASE 18 hashes (`fd2d9783`/`9ff2364f`/`c5084feb`); `tests/golden/test_golden_cases.py` + integrity tests **25 passed**; V1 rules group **54 passed**.
- No V1 production behavior changes occurred: the only content changes this phase are the pre-existing README rebuild and the engine.py docstring correction (§12.4) — zero executable-behavior lines touched (full suite byte-for-byte result identical before/after).

## 11. Authorization status (brief §10)

| Item | Status |
|---|---|
| Canonical Geography contract | **DEFINED** |
| SP1 semantics | **DEFINED** (implemented as pure semantics; production semantics not switched) |
| field_present | **DEFINED** |
| SP1 implementation (production wiring) | **NOT AUTHORIZED** |
| SP1 activation | **NOT AUTHORIZED** |
| SP1 default registration | **NOT AUTHORIZED** |
| V1 semantic change | **NOT AUTHORIZED** |
| E1 | **APPROVED RULE ONLY / NOT AUTHORIZED TO EXECUTE** (no execution path exists) |
| ClickHouse mutation | **NOT AUTHORIZED / MUST NOT OCCUR** (none occurred) |
| Production pilot | **NOT AUTHORIZED / MUST NOT OCCUR** (none occurred) |

## 12. Test results (brief §12)

1. Full suite: `python -m pytest -q` → **327 collected / 318 passed / 9 skipped / 0 failed / 0 errors** — exactly the expected baseline. Skips: 7 × DL001–DL015 (authoritative table absent, company-gated), 1 × Docker/ClickHouse unavailable, 1 × Airflow not installed.
2. Focused: SP1 contract tests **63/63 passed**; golden (V1 geography expectations + integrity) **25 passed**; V1 rules **54 passed**; DL module **7 skipped** (unchanged gate).
3. Classification (recorded, consistent with PHASE 17/18 derivation): 216 V1/shared + 63 SP1 + 27 R3 + 21 Q21 = 327.
4. Post-documentation-edit re-run: **318 passed / 9 skipped / 0 failed** — identical; the docstring correction caused zero behavioral impact.
5. No test was altered, weakened, or added to manufacture a pass. No contract/implementation/test gap was auto-fixed.

## 13. Differences requiring future authorized implementation

1. **Production selection wiring** — SP1 eligibility is implemented as pure semantics only; the production path (registry → engine → CLI/DAG) still executes V1 prefix-map rules. Future authorized change: explicit, non-silent registry swap + activation gate (recommendation R2), with the V1→successor divergence report regenerated against production data.
2. **Physical reference datasets** — canonical + cross reference derived from `tips_data.tblZipStCtyIB` are not present in the environment; controlled fixtures are test-only. Delivery with provenance (source identity, extraction query/date, row counts, SHA-256) is a precondition.
3. **DL001–DL015 authoritative table** — still absent; 7 tests remain skip-gated; classified PARTIALLY AVAILABLE / NOT FULLY VERIFIED / COMPANY DECISION REQUIRED. No case was fabricated.
4. **county/country presence** — undefined by the contract; requires a contract extension, not an implementation initiative.
5. **Residual documentation inaccuracy (reported, not corrected):** `scripts/benchmark.py` contains the runtime banner string "These benchmarks validate streaming O(1) memory behavior for file-based processing." — contradicted by `FINAL_SCALE_REPORT.md` (id_set O(N)). Left untouched because it is a runtime output string of an executable script, outside the documentation-only surface corrected this phase.

## 14–17. Explicit safety statements

14. **No production data changed.** All outputs of this phase were printed to stdout; the probe script lives outside the repository (`/home/z/my-project/scripts/phase19_probe.py`); no data file, fixture, or evidence artifact was written, and frozen evidence hashes are unchanged.
15. **No ClickHouse mutation occurred.** No ClickHouse connection was opened; no client exists in the codebase; no SQL statement was executed against any server.
16. **SP1 was not activated.** SP1 remains unregistered, inactive, non-default, and unreachable from the production execution path (AST-proven, tripwire-tested).
17. **E1 was not executed.** No execution path exists (doc-only status re-confirmed); nothing was run.

## 18. Final disposition

**RECONCILED WITH DOCUMENTED GAPS — IMPLEMENTATION BLOCKED BY AUTHORIZATION.**

Basis: the repository's SP1 successor implementation was built from the same authoritative document the Phase 19 brief designates as the canonical contract (identical title, prepared date 2026-09-01, measurements 2026-08-31, company-provided SHA-256 `0cf6eb93…`), so the semantic comparison yields **Match on all 21 matrix elements** — policy, assessability, ZIP normalization, reference resolution, field_present, allowlist, and all seven acceptance cases — with **zero discrepancies requiring code change**. The documented gaps are authorization-gated, not semantic: SP1 production wiring/activation/default registration remain NOT AUTHORIZED, the physical two-reference datasets and the DL001–DL015 table are absent (company-gated), county/country remain undefined by the contract, and V1 intentionally remains the unchanged default path. "Implemented" is therefore claimed only for the isolated pure-semantics layer (IMPLEMENTED/TESTED/VERIFIED/ISOLATED/PREPARED — never ACTIVE/DEFAULT/PRODUCTION-EXECUTED), and no "production-ready" claim is made.

Documentation-only remediations performed this phase (explicitly listed per §15):
1. `data_quality_platform/validation/engine.py` (docstring only, lines 55–61): removed the false "Memory is O(1) relative to row count" claim and replaced it with the accurate O(N) statement (id_set, row_lineage_buffer, lineage row_records; 1000-cap at persistence only) pointing to FINAL_SCALE_REPORT.md. Verified docstring-only via git diff; AST-valid; full suite identical before/after.
2. No other documentation correction was necessary: the SP1 policy supersession, new field_present definitions, county/country exclusion, 62-code allowlist, seven acceptance cases, and the separation of semantic approval from implementation authorization are already documented consistently in `docs/GEOGRAPHY_RULE_SP1_CONTRACT.md`, `README.md` §23/§26/§27, `docs/DATA_FLOW_MAP.md`, and the module headers.

Git safety (§15): `git status --short` = 201 mode-only files (pre-existing environment chmod artifact, reported not fixed) + ` M README.md` (pre-existing Task 17 rebuild) + ` M data_quality_platform/validation/engine.py` (docstring-only, this phase) + `?? FINAL_IMPROVEMENT_REPORT.md` (pre-existing). HEAD = `a5ec759f069c2c8aeea72b147437f1b8b22756d9` unchanged; origin/main = `4065714c…` unchanged; **nothing committed, nothing pushed**. No executable source behavior changed.

**PHASE 19 — RECONCILED WITH DOCUMENTED GAPS — IMPLEMENTATION BLOCKED BY AUTHORIZATION. STOP.**
