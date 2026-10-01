# Geography Rule — SP1 Successor Contract (Canonical Definition and Acceptance Cases)

**Artifact class:** NEW project documentation artifact (dated current-version record)
**Created:** 2026-09-05 (delivery revision 2)
**Supersedes:** none (this file does not edit or replace any historical document; the prior
design study `docs/CANONICAL_GEOGRAPHY_DESIGN.md` remains byte-identical and is hereby
recorded as a draft-stage predecessor)

---

## 1. Provenance and authority

| Field | Value |
|---|---|
| Authoritative document title | Geography rule — canonical definition and acceptance cases |
| Prepared | 2026-09-01 |
| Measurements | 2026-08-31 |
| Document SHA-256 (company-provided) | `0cf6eb930149e975397b348709d8f7e83f96eb6eb70d2361cf66551ada311bc0` |
| Source commit | `ee7859e1ad521cb68ba32b604498d951c7690b19` |
| contract_v3 SHA-256 | `8ae3256b362d218849a688cc8f0a76d86c4ffb886607f69848030c2e6ba1fe74` |
| decision_record_v2 SHA-256 | `4dd8914f4d5ed7ab47f5245fd762d9e06983e43aba0858d1e38b3c1cf21fac4c` |
| pinned_template SHA-256 | `47b3361b22ee9882c17e70886c3d5e3c493107881ed9f86345b96c5aa1cd521a` |
| Superseded prepared version | `3297179ea3527f56091191c48e8f72606e000fc7b885da906a7e59b97e1aebc8` |
| Superseded document in this repository? | No — the superseded hash appears nowhere in the repository history; it was never committed |

**Accessibility record (verbatim):** Company artifact was supplied externally (via the
authoritative company instruction channel) but is not accessible as a file in the current
coding environment. The SHA-256 values above are the company-provided provenance values
and could **not** be independently re-computed locally. Per instruction, the supplied
historical document itself has not been edited (it is not present in the environment to
edit); this artifact transcribes the contract content **as delivered**, preserving the
original provenance and SHA, and is the implementation-authoritative record for SP1.

The delivered contract supersedes the older prepared version listed above and is treated
as the authoritative SP1 successor geography definition. Where the MASTER REMEDIATION
PROMPT (`ccf9c3905b1cd1e77dec29442ab9c6cb4f0dd9e6057ec0e670caca39402f987c`, two
byte-identical copies in `upload/`) and the delivered document differ — notably the state
allowlist (MASTER PROMPT §9 omits `DE`, `IL`, `WY`; the delivered allowlist includes them)
— the delivered document governs.

---

## 2. SP1 successor selection semantics (verbatim contract)

The current SP1 selection policy is:

```
exclude when:
    geography_mismatch_candidate = 1
    OR
    NOT field_present(requested geography field)
```

This replaces the old rule:

```
exclude when:
    zip_state_assessable = 0
    OR
    geography_mismatch_candidate = 1
```

The new principle is:

    UNASSESSABLE != MISMATCH

Required semantics:

```
mismatch = 1
    -> excluded

assessable + matching geography
    -> eligible

unassessable + requested geography field present
    -> eligible

requested geography field absent
    -> excluded
```

The mismatch exclusion applies to every targeted geography field supported by the rule.
The old V1 eligibility rule (`eligible = assessable AND NOT mismatch`) is a DIFFERENT
contract and must not be restored.

---

## 3. Canonical geography definitions (verbatim contract)

```
zip_state_assessable =
    reference_resolved
    AND NOT blank_state
    AND NOT invalid_state_format
    AND NOT numeric_state_review
    AND NOT unknown_state_code

zip5 =
    if trimmed zip matches ^[0-9]{5}$:
        zip5
    else:
        ''

reference_resolved =
    zip5 != ''
    AND canonical_state_count = 1
    AND cross_state_count <= 1
    AND (
        cross_state_count = 0
        OR canonical_state = cross_state
    )

blank_state =
    state = ''

invalid_state_format =
    state != ''
    AND not ^[A-Za-z]{2}$
    AND not all digits

numeric_state_review =
    state != ''
    AND all digits

unknown_state_code =
    two-letter state
    AND not in allowlist
```

All values:

- are converted to text
- surrounding whitespace is trimmed
- null is treated as empty string
- state is upper-cased before comparison

Canonical mismatch:

```
zip_state_mismatch =
    same assessable conjunction
    AND state_code != canonical_state
```

Important: **a mismatch row is assessable by definition** (mismatch implies assessable).

Allowlist (62 codes — 50 states + DC; military AA/AE/AP; territories AS/GU/MP/PR/VI;
freely-associated states FM/MH/PW; territories are included):

```
AA AE AK AL AP AR AS AZ CA CO CT DC DE FL FM GA GU HI IA ID IL IN KS KY LA MA MD ME MH
MI MN MO MP MS MT NC ND NE NH NJ NM NV NY OH OK OR PA PR PW RI SC SD TN TX UT VA VI VT
WA WI WV WY
```

---

## 4. Two-reference model (verbatim contract)

The contract explicitly defines TWO references.

Each reference:

- is filtered to a five-digit ZIP
- is filtered to a two-letter state
- is grouped by ZIP

Canonical reference: resolves the canonical state.
Cross reference: must agree with the canonical state, or have no row.

If a ZIP resolves to different states between the references: **conflict → not assessable**.
A missing cross-reference row is **not** a conflict (the GU / 96910 case).

DO NOT replace this two-reference model with the legacy prefix map. DO NOT create fake
reference data.

---

## 5. field_present (verbatim contract)

```
field_present(zip)     = zip5 != ''

field_present(state)   = NOT blank_state
                         AND NOT invalid_state_format
                         AND NOT numeric_state_review
                         AND NOT unknown_state_code

field_present(city)    = NOT blank_city

field_present(address) = NOT blank_address

field_present(county)  = NOT DEFINED

field_present(country) = NOT DEFINED
```

County/country presence logic must NOT be invented. City/address use blankness only.
Evaluation is PER FIELD, not per row: a row with a valid state and a malformed ZIP is
present for state-targeted selection and not present for ZIP-targeted selection.

---

## 6. Authoritative acceptance cases (delivered by the company)

| # | Consumer state / ZIP | assessable | match | mismatch | canonical resolution | Note |
|---|---|---|---|---|---|---|
| 1 | CA / 90210 | true | true | false | CA | baseline match |
| 2 | CA / 00USA | false | false | false | — | malformed ZIP → unassessable, NOT a mismatch |
| 3 | CA / 0 | false | false | false | — | unassessable |
| 4 | CA / 000CA | false | false | false | — | unassessable |
| 5 | CA / "015 8" | false | false | false | — | unassessable |
| 6 | WA / 99501 | true | false | **true** | **AK** | mismatch row; assessable by definition |
| 7 | GU / 96910 | true | true | false | GU | **cross reference has no row — that is NOT a conflict** |

These seven cases are the only cases labeled authoritative by the delivered document. No
additional case has been invented and labeled authoritative; all other test rows in
`tests/unit/test_sp1_geography_contract.py` are explicitly marked engineering cases.

---

## 7. Old (V1) vs successor — explicit divergence record

| Consumer row | V1 assessable | V1 mismatch | Old SP1 decision | Successor decision | Divergence driver |
|---|---|---|---|---|---|
| CA / 90210 | 1 (90 ∈ CA prefixes) | 0 | eligible | eligible | none |
| CA / 00USA | 1 (V1 does not validate ZIP format) | **1** (no CA bucket starts 00) | **excluded (mismatch)** | **eligible** (unassessable, state present) | UNASSESSABLE ≠ MISMATCH; V1 prefix-probe vs canonical resolution |
| GU / 96910 | **0** (GU absent from prefix map) | 0 | **excluded (unassessable)** | **eligible** (assessable + match via canonical) | canonical reference replaces prefix map |
| WA / 99501 | 1 (99 bucketed under WA) | 0 | **eligible** | **excluded** (canonical resolution = AK → mismatch) | prefix map wrong vs canonical reference |
| CA / 0, CA / 000CA, CA / "015 8" | 1 each (V1 does not validate ZIP format) | 1 each | excluded (mismatch) | unassessable (not mismatch); eligible when state targeted | ZIP5 normalization + per-field presence |

The legacy implementation (`ZipStateAssessable`, `GeographyMismatchCandidate`,
`STATE_ZIP_PREFIXES` in `data_quality_platform/contracts.py` + `rules/v1_rules.py`) is
**isolated, not canonical**: it remains registered in the production `RuleRegistry`
unchanged, and the successor module contains an automated tripwire
(`test_module_does_not_import_legacy_prefix_map`) proving the successor never imports the
legacy map.

---

## 8. Implementation and isolation map

| Component | Path | Status |
|---|---|---|
| Pure canonical semantics (zip5, classifiers, assessable, mismatch, field_present, SP1 eligibility) | `data_quality_platform/geography/canonical.py` | IMPLEMENTED (pure) |
| Two-reference provider interface + controlled-fixture provider | `data_quality_platform/geography/references.py` | IMPLEMENTED (interface + test fixture provider) |
| Contract tests incl. the 7 authoritative acceptance cases | `tests/unit/test_sp1_geography_contract.py` | 63 tests, all passing |
| Production registry | `data_quality_platform/rules/registry.py` | UNCHANGED — V1 rules only |
| Production selection behavior | validation engine / flags pipeline | UNCHANGED |

**SP1 dual-track status:**

- COMPANY CONTRACT STATUS: **VERIFIED** (delivered document; provenance above).
- IMPLEMENTATION READINESS: **pure/local implementation complete, verified with
  controlled fixtures** — sanctioned by the delivery instruction §6 ("implement the
  contract behind an injectable/reference-provider interface where safe, and test the
  pure semantics with controlled fixtures").
- CANONICAL PRODUCTION VALIDATION: **BLOCKED** — the physical reference datasets
  (canonical reference + cross reference derived from `tips_data.tblZipStCtyIB`) are not
  accessible: no reachable authorized ClickHouse endpoint (GET /ping refused throughout),
  no company-committed snapshot (`data/` directory does not exist at HEAD), no approved
  extract. No canonical production validation is claimed.

**Production activation preconditions (all required, none satisfied yet):**

1. Authorized access to `tips_data.tblZipStCtyIB` (or a company-approved snapshot) with
   documented provenance: source identity, extraction query, extraction date, row counts,
   SHA-256.
2. Both physical references delivered/derived per the two-reference model.
3. Explicit company authorization to change production selection behavior.
4. Registry swap executed explicitly (never silently), with the V1→successor divergence
   report regenerated against production data.

Until then the successor remains behind the injectable provider interface
(`TwoReferenceProvider`); `ReferenceUnavailableError` marks the missing physical source,
and no code path fabricates reference data.

---

## 9. DL001–DL015 status

- The previously available company material (MASTER REMEDIATION PROMPT §10) contained
  only a **partial** DL001–DL015 table: all 15 IDs listed, exact prose for **five** cases
  only — DL006 ("six-digit ZIP must NOT pass as a valid 5-digit ZIP"), DL011 ("WA / 99501
  resolves to AK according to canonical reference"), DL012 ("HI / 96501 resolves to AP
  according to canonical reference"), DL014 ("GU / 96910 becomes assessable through
  canonical reference"), DL015 ("AS / 96799 becomes assessable through canonical
  reference").
- The delivered geography document provides seven acceptance cases (§6 above) whose
  semantics are consistent with DL011/DL014, but the document does not present a complete
  DL001–DL015 table, and supersession of the old DL table **cannot be proven from the
  delivered provenance** (no DL-scope hash or text was delivered).
- Consequence (recorded, not worked around):
  **DL001–DL015 = PARTIALLY AVAILABLE / NOT FULLY VERIFIED.**
- All known authoritative cases are preserved; the skip-gated DL test suite
  (`tests/golden/test_dl_canonical_geography.py`, 7 tests) remains byte-identical and
  skip-gated pending the authoritative table. No skip-gate was removed to force a green
  summary; no missing case was fabricated.
- Pure-semantics coverage that DOES exist for the known DL prose: DL006
  (`test_dl006_six_digit_zip_is_not_valid_zip5`), DL011/DL014 semantics via acceptance
  cases 6 and 7. DL012/DL015 (HI/96501→AP, AS/96799) have no fixture rows because the
  canonical resolution values AP/96799 would require reference rows not traceable to any
  delivered acceptance case — fabricating them is forbidden.

---

## 10. Verification summary (this delivery revision)

- 63/63 tests in `tests/unit/test_sp1_geography_contract.py` pass, including the seven
  authoritative acceptance cases, the mismatch-implies-assessable invariant (13-probe
  sweep), the unassessable-never-mismatch invariant (8-probe sweep), the GU
  no-cross-row case, two-reference conflict/ambiguity handling, per-field presence, the
  NOT DEFINED county/country refusals, the old-vs-successor divergence matrix, and
  module-isolation/determinism tripwires.
- Full-suite and CLI verification results are recorded in `FINAL_TEST_REPORT.md` and
  `evidence/final/PROOF_MATRIX.md` (P-31 … P-36).
