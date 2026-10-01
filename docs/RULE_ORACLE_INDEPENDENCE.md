# Rule / Oracle Independence Report

Status: VERIFIED LOCALLY (static analysis + consistency tests), 2026-09-15.
Scope: DQAVP hardening Section 5 — reduce silent semantic drift across the
multiple expressions of the frozen V1 rule semantics. No V1 behavior was
changed by this analysis; where drift was found it is documented, pinned
by regression tests, and classified — never silently redefined.

## 1. Canonical ownership map

| Semantics | Canonical source | Role | Duplicated expressions |
|---|---|---|---|
| 8 V1 rule predicates | `data_quality_platform/rules/v1_rules.py` | PRODUCTION (canonical) | Oracle re-implementation; SQL templates |
| Rule registration order / required set | `data_quality_platform/rules/registry.py` + `contracts.REQUIRED_RULE_IDS` | PRODUCTION (canonical) | Checker pinned-name gate |
| 33-column input contract | `data_quality_platform/contracts.SOURCE_COLUMNS` | PRODUCTION (canonical) | Oracle transcription; golden fixtures |
| ZIP/state prefix map (reference data) | `data_quality_platform/contracts.STATE_ZIP_PREFIXES` (51 states) | PRODUCTION (canonical reference) | `ORACLE_PREFIXES` transcription in `scripts/final_3m_validation.py`; `docs/CANONICAL_GEOGRAPHY_DESIGN.md` (SP1 successor, non-production) |
| Suspicious name patterns (reference data) | `data_quality_platform/contracts.SUSPICIOUS_NAME_PATTERNS` (19) | PRODUCTION (canonical reference) | `SUSPICIOUS` transcription in the oracle; SQL template literals |
| Email syntax regex | `EmailSyntaxFailure.EMAIL_PATTERN` in `v1_rules.py` | PRODUCTION (canonical) | Second compiled copy in `ProposedEmailExportEligible.EMAIL_PATTERN`; oracle `EMAIL_RE`; SQL template regex |
| Independent oracle (validation) | `scripts/final_3m_validation.py` `_oracle_*` functions | VALIDATION-ONLY (independent by construction: zero production imports) | — |
| Golden regression expectations | `tests/golden/golden_cases.csv` + `expected_results.csv` | REGRESSION (canonical expected-value record) | Per-case assertions in `test_golden_cases.py` |
| SP1 successor geography (future reference) | `data_quality_platform/geography/` (canonical.py + references.py) | EXPERIMENTAL, NOT REGISTERED, NOT AUTHORIZED | Company DL cases (fixture never delivered) |

## 2. Classification of duplicated semantics

1. **Intentional independence (keep):** the oracle in
   `scripts/final_3m_validation.py` re-implements all 8 predicates from the
   documented frozen contract with an independent code path. This is the
   point of the independent verification; it must NOT be replaced by calls
   to production code. Transcribed reference tables are pinned equal by
   `tests/unit/test_final_3m_hardening.py::TestOracleTranscriptionFidelity`
   and re-pinned by `tests/unit/test_rule_oracle_consistency.py`.
2. **Intra-production duplication (guarded, known):** the email regex is
   compiled twice (syntax-failure and export-eligibility rules). The two
   rules are logical complements on non-blank emails. Guarded by
   `test_email_regex_defined_identically_in_both_email_rules` and
   `test_email_rules_are_exact_complements_on_nonblank_emails`.
3. **Documentation duplication (inherent, low risk):** SQL templates and
   docs re-express rule logic in SQL / prose. SQL templates are static
   artifacts (never executed against any database in this repository);
   their embedded pattern lists are checked against the contract by
   `test_sql_templates_reference_the_same_suspicious_patterns`.
4. **Golden corpus divergence (REVIEW_REQUIRED, discovered 2026-09-15):**
   golden cases 11, 37, 50 (ZIP 73301 / 73302 / 73344, state TX) record
   `expected_geography_mismatch_candidate = 0` — the real-world USPS
   expectation (733xx = Austin TX). The frozen V1 prefix map assigns
   prefix 73 to OK only, so BOTH the production rule and the independent
   oracle compute 1. Engine and oracle agree; the golden expectation
   column is the outlier. Pinned by
   `test_golden_corpus_agrees_with_oracle` (exact allowlist — any new
   divergence fails the suite) and
   `test_engine_agrees_with_oracle_on_review_required_cases`.
   Classification: known V1 prefix-map limitation, same class as the
   documented DL001–DL015 derived divergences. NOT fixed silently.

## 3. Consistency checks created (Section 5-D)

- `tests/unit/test_rule_oracle_consistency.py` (10 tests):
  - production-internal duplication guards (email regex identity,
    complementarity property, reference import-only ownership via AST)
  - 5,000-row deterministic random battery: engine vs oracle, all 8 flags
  - golden corpus vs oracle triangulation with exact REVIEW_REQUIRED
    allowlist
  - reference-data structural sanity (51 states, 19 patterns)

## 4. Remaining semantic risks

- The prefix map is a simplification of USPS geography (73→OK-only is the
  newest pinned example; the DL001–DL015 analysis already documented 8 of
  12 derived divergences). Resolution requires the company-authoritative
  reference (never delivered) — until then V1 semantics stay frozen and
  the divergences stay documented.
- The SQL templates cannot be executed against ClickHouse from this
  repository (no client); their equivalence to Python predicates is
  documented intent, not an executed guarantee.
- The oracle's independence is code-path independence; its reference
  tables necessarily come from the same frozen contract (pinned equal by
  tests, so table drift is detectable, but table TRUTH is inherited).
