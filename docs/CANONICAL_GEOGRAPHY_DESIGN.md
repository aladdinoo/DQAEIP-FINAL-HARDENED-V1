# Canonical Geography — Implementation Design & Test Plan

Status: **DESIGN ONLY — NO IMPLEMENTATION AUTHORIZED**
Scope: geography rules only (`zip_state_assessable`, `geography_mismatch_candidate`)
Repo: `data-quality-platformV2` @ `4065714` ("Initial commit: Data Quality Platform V2")

**Hard guardrails honored in this analysis**

- No ClickHouse access. No `INSERT` / `UPDATE` / `ALTER UPDATE` / `DELETE` / `TRUNCATE` against any environment.
- Experiment **E1** not executed. Proposal **SP1** not implemented. Name rules **R1–R3** not modified.
- No production data mutation of any kind. All work below is read-only inspection, an
  independent reproduction script, and one new (skip-gated) test file.

---

## 1. Current implementation inspection (what produces the two flags)

| Concern | Exact location | Behavior |
|---|---|---|
| `zip_state_assessable` | `data_quality_platform/rules/v1_rules.py` → `class ZipStateAssessable.execute` (lines 244–270, logic at 255–260) | `1` iff `str(row["zip"]).strip()` non-empty **and** `str(row["state"]).strip().upper()` is a key of `STATE_ZIP_PREFIXES`. **No ZIP format validation of any kind.** |
| `geography_mismatch_candidate` | same file → `class GeographyMismatchCandidate.execute` (lines 273–307, logic at 284–296) | `0` if either field empty or state unknown; else `1` iff **no** prefix listed for the state satisfies `zip_val.startswith(prefix)`. |
| Prefix data | `data_quality_platform/contracts.py` → `STATE_ZIP_PREFIXES` (lines 47–67) | 51 entries (50 states + DC), **2-digit** prefix lists. No territories, no military codes. |
| SQL templates | `ZipStateAssessable.execute_sql_template` (contains unresolved `{states}`), `GeographyMismatchCandidate.execute_sql_template` (contains unresolved `{zip_state_conditions}`) | Templates are **never rendered** anywhere: `RuleRegistry.get_sql_templates()` (registry.py:146–151) only collects them for hashing/evidence (engine.py:273, cli.py:239). No SQL path computes these flags today. |

Observed implementation quirks (documented, **not** fixed):

1. **No ZIP format gate.** `"90001-1234"`, `"9001"`, `"ABCDE"` are all "assessable" when the state is known.
2. **`str(None)` quirk.** `row.get("zip", "")` returning `None` (dict API, not CSV path) yields the string `"None"`, which is truthy → `zip_state_assessable=1` and, for any known state, `geography_mismatch_candidate=1`. The CSV pipeline never hits this; the Python API can.
3. **Territories/military absent** from the reference → `GU/AS/PR/VI/MP/AA/AE/AP` rows are never assessable, never mismatches (silent blind spot).
4. **2-digit prefix map cannot be made deterministic** — 13 prefixes are claimed by more than one state (measured, §3.3), so `startswith` matching accepts cross-state ZIPs (false negatives) and excludes real in-state ZIPs (false positives, e.g. Austin TX `733xx`).
5. `STATE_ZIP_PREFIXES["DC"] == ["20", "20"]` — duplicate entry (harmless, but symptomatic of hand-maintained data).

---

## 2. Independent reproduction (item 3) — method and result

Tool: `/home/z/my-project/scripts/repro_prefix_map.py` (read-only, outside the repo).

1. `STATE_ZIP_PREFIXES` extracted from `contracts.py` **via AST literal evaluation** — no import, no code execution of repo modules for the data.
2. Both rules' semantics restated as fresh independent functions (`current_zip_state_assessable`, `current_geography_mismatch`), transcribed from the source lines above.
3. Equivalence proof: 25-probe sweep (valid, empty, unknown-state, malformed, territory, military, `None`-zip cases) — independent restatement vs. the repo's real `RuleRegistry.execute_all`: **0 mismatches**.
4. Fixture fidelity check (harness only — these fixtures are *not* DL evidence):
   - `GEO001–GEO020` (geography_edge_cases.csv): 20/20 reproduced.
   - GC geography columns vs `expected_results.csv`: 50/50 reproduced.
   - **Fixture-internal contradictions found** (well-aligned rows): `GC011` (TX/73301) and `GC037` (TX/73302) carry inline `expected_geography_mismatch_candidate=0` in `golden_cases.csv` while `expected_results.csv` asserts `1` (which matches current FP behavior). `73301`/`73344` are real Austin, TX ZIPs → the current prefix map produces **false positives** here, and the two fixture files disagree about it.
   - `GC022` and `GC050` are **structurally misaligned rows** (field count ≠ 42-column header). Their inline annotations are unreliable; recorded as fixture-quality defects, out of scope, not silently fixed.

### 2.1 Legacy map diagnostics (measured)

- Territory/military codes absent: `AA, AE, AP, AS, GU, MP, PR, VI` (all 8).
- Duplicate entries: `DC: ["20","20"]`.
- 2-digit prefixes claimed by >1 state (determinism impossible at this granularity):
  `02 (MA,RI) · 03 (ME,NH,RI) · 19 (DE,PA) · 22 (MD,VA) · 24 (VA,WV) · 38 (MS,TN) · 71 (AR,LA) · 83 (ID,WY) · 84 (ID,UT) · 88 (NM,NV) · 96 (CA,HI) · 97 (HI,OR) · 99 (AK,WA)`
- Consequence classes: over-claims create **false negatives** (e.g. `HI` claims `97` → an HI row with an OR ZIP `97xxx` passes); under-claims create **false positives** (TX lacks `733xx` → Austin rows flagged); absent codes create an **assessment blind spot** (all territories).

---

## 3. Canonical geography contract (successor semantics)

Normative, from the acceptance brief — preserved verbatim as invariants:

- **C1** `zip` must match `^[0-9]{5}$` (leading zeros valid; ZIP+4, short/long, alphanumeric → not assessable).
- **C2** the reference must resolve the ZIP **deterministically** (exactly one geography per resolvable ZIP).
- **C3** the cross-reference must **agree or have no entry** (the state→prefix view is derived from the ZIP→state reference; never independently hand-edited).
- **C4** territories are valid geographies — per clarification: **all inhabited territories (PR, VI, GU, AS, MP) plus military AA, AE, AP** (50 states + DC + 8 = **59 codes**).
- **C5** `mismatch = assessable AND row_state != canonical_resolved_state(zip)`.
- **C6** **DL013 remains a non-defect control case** (`canonical_geography_mismatch_candidate = 0`).

Derived flag definitions (the only definitions consistent with C1–C5):

```text
zip_format_valid(zip) := zip matches ^[0-9]{5}$
state_valid(state)    := upper(strip(state)) ∈ CANONICAL_GEOGRAPHY_CODES     # 59 codes, C4
resolution(zip)       := resolve_zip(zip) ∈ CANONICAL_GEOGRAPHY_CODES ∪ {UNRESOLVED}   # C2

zip_state_assessable         := zip_format_valid AND state_valid AND (resolution ≠ UNRESOLVED)
geography_mismatch_candidate := assessable AND (resolution ≠ row_state)              # C5
```

Rationale for requiring resolution inside `assessable` (rejected alternative:
`assessable = format ∧ state_valid`): with an unresolved ZIP, "row state ≠ canonical
resolved state" is undefined; treating unresolved as mismatch would manufacture false
positives for genuinely unassigned 5-digit ranges. C3's "no entry → no claim" is
honored by `assessable=0, mismatch=0` with `resolution_status = UNRESOLVED` carried
as diagnostic metadata (never as a data mutation).

---

## 4. Proposed implementation design (canonical geography only)

### 4.1 Reference data model (one source of truth)

A single ordered, **pairwise-disjoint** (per different geography code) range table:

```python
# data_quality_platform/rules/geography_canonical.py  (NEW MODULE — designed, not implemented)
CANONICAL_ZIP_RANGES = [
    # (zip_start, zip_end, geography_code)   # 5-digit inclusive bounds
    ("00501", "00599", "NY"),   # Holtsville NY (IRS) — 005xx is NY, not PR
    ("00600", "00799", "PR"),
    ("00800", "00899", "VI"),
    ("00900", "00999", "PR"),
    ("01000", "02799", "MA"),
    ("02800", "02999", "RI"),
    ("03000", "03899", "NH"),
    ("03900", "04999", "ME"),
    ("05000", "05999", "VT"),
    ("06000", "06999", "CT"),
    ("07000", "08999", "NJ"),
    ("09000", "09899", "AE"),   # military
    ("10000", "14999", "NY"),
    ("15000", "19699", "PA"),
    ("19700", "19999", "DE"),
    ("20000", "20599", "DC"),
    ("20600", "21999", "MD"),
    ("22000", "24699", "VA"),
    ("24700", "26899", "WV"),
    ("27000", "28999", "NC"),
    ("29000", "29999", "SC"),
    ("30000", "31999", "GA"),
    ("32000", "33499", "FL"),
    ("33600", "33999", "FL"),
    ("34000", "34099", "AA"),   # military — carve-out inside 34x
    ("34100", "34299", "FL"),
    ("34400", "34499", "FL"),
    ("34600", "34799", "FL"),
    ("34900", "34999", "FL"),
    ("35000", "36999", "AL"),
    ("37000", "38599", "TN"),
    ("38600", "39799", "MS"),
    ("40000", "42799", "KY"),
    ("43000", "45999", "OH"),
    ("46000", "47999", "IN"),
    ("48000", "49999", "MI"),
    ("50000", "52899", "IA"),
    ("53000", "54999", "WI"),
    ("55000", "56799", "MN"),
    ("57000", "57799", "SD"),
    ("58000", "58899", "ND"),
    ("59000", "59999", "MT"),
    ("60000", "62999", "IL"),
    ("63000", "65899", "MO"),
    ("66000", "67999", "KS"),
    ("68000", "69399", "NE"),
    ("70000", "71499", "LA"),
    ("71600", "72999", "AR"),
    ("73000", "73199", "OK"),
    ("73300", "73399", "TX"),   # Austin unique ZIPs 73301/73344 — fixes GC011/GC037/GC050 FPs
    ("73400", "74999", "OK"),
    ("75000", "79999", "TX"),
    ("80000", "81699", "CO"),
    ("82000", "83199", "WY"),
    ("83200", "83899", "ID"),
    ("84000", "84799", "UT"),
    ("85000", "86599", "AZ"),
    ("87000", "88499", "NM"),
    ("88900", "89899", "NV"),
    ("90000", "96199", "CA"),
    ("96200", "96699", "AP"),   # military
    ("96700", "96798", "HI"),   # 96799 carved out for AS below
    ("96799", "96799", "AS"),
    ("96800", "96899", "HI"),
    ("96910", "96932", "GU"),
    ("96950", "96952", "MP"),
    ("97000", "97999", "OR"),
    ("98000", "99499", "WA"),
    ("99500", "99999", "AK"),
]

CANONICAL_GEOGRAPHY_CODES = frozenset(
    {c for _, _, c in CANONICAL_ZIP_RANGES}          # 59 codes by construction
)
CANONICAL_ZIP_PATTERN = re.compile(r"^[0-9]{5}$")
```

**DRAFT-UNVERIFIED marking (mandatory before merge):** the range bounds above are a
draft reconstruction from standard USPS 3-digit assignments and must be verified
against the USPS City State File / ZIP code product before implementation lands.
The *structure*, *algorithm*, and *invariants* below are the contract; the *data* is
gated behind a verification step and a disjointness test. Verification never touches
production data (file-based check only).

### 4.2 Functions (new module `geography_canonical.py`)

```python
def normalize_state(state) -> str            # str().strip().upper(); None → ""
def zip_format_valid(zip_raw) -> bool        # C1 gate
def resolve_zip(zip_raw) -> tuple[ResolutionStatus, str | None]
    # ResolutionStatus ∈ {RESOLVED, FORMAT_INVALID, UNRESOLVED}
    # C2: binary search over the sorted, disjoint CANONICAL_ZIP_RANGES;
    # exactly one range may contain a resolvable ZIP (invariant-tested).
def evaluate_geography(row) -> dict
    # {"zip_state_assessable": 0|1,
    #  "geography_mismatch_candidate": 0|1,
    #  "resolved_state": <code>|None,          # diagnostic only
    #  "resolution_status": "RESOLVED"|"FORMAT_INVALID"|"UNRESOLVED"}
def validate_reference_consistency() -> list[str]
    # C3: derives the inverse (state → prefix ranges) and asserts it agrees
    # with CANONICAL_ZIP_RANGES ("agree or have no entry"); returns [] when clean.
```

Rule classes (only if/when the registry swap is authorized):

```python
class ZipStateAssessableCanonical(Rule):        # rule_version "2.0.0"
    execute(row) -> evaluate_geography(row)["zip_state_assessable"]
class GeographyMismatchCandidateCanonical(Rule) # rule_version "2.0.0"
    execute(row) -> evaluate_geography(row)["geography_mismatch_candidate"]
```

Both provide rendered SQL templates (parameterized against the reference table in
§4.4) — no unresolved placeholders like the v1 templates.

### 4.3 Registry swap policy — explicit, never silent

`RuleRegistry.create_default()` is **not** modified in this step. When implementation
is authorized, the swap lands as a separately reviewable change:

```python
@classmethod
def create_default(cls, use_canonical_geography: bool = False) -> "RuleRegistry":
    ...  # default False → byte-identical behavior until explicitly enabled
```

`STATE_ZIP_PREFIXES` in `contracts.py` is retained verbatim (deprecated in a doc
comment in the same authorized PR — not before). v1 rule classes stay in the tree.

### 4.4 SQL reference table (DDL only — never executed)

New file `sql/006_create_canonical_geography_reference.sql` (designed, not applied):

```sql
CREATE TABLE IF NOT EXISTS canonical_zip_range (
    zip_start  UInt32,          -- inclusive 5-digit lower bound
    zip_end    UInt32,          -- inclusive 5-digit upper bound
    geo_code   FixedString(2),
    range_kind Enum8('state' = 1, 'territory' = 2, 'military' = 3)
) ENGINE = ReplacingMergeTree()
ORDER BY (zip_start, zip_end);

-- Deterministic resolution view (C2): a ZIP joins at most one row because the
-- range table is pairwise-disjoint per geo_code; guarded by the validation job
-- below (read-only SELECT validation, run only with explicit authorization).
```

No `INSERT` of reference rows is proposed for production: loading is a separate,
explicitly authorized change (a `SELECT`-only verification query accompanies it).

---

## 5. Exact files/functions/tests that would change (item 9)

| # | Path | Change | When |
|---|---|---|---|
| 1 | `data_quality_platform/rules/geography_canonical.py` | **NEW** — `CANONICAL_ZIP_RANGES`, `CANONICAL_GEOGRAPHY_CODES`, `CANONICAL_ZIP_PATTERN`, `normalize_state`, `zip_format_valid`, `resolve_zip`, `evaluate_geography`, `validate_reference_consistency`, `ZipStateAssessableCanonical`, `GeographyMismatchCandidateCanonical` | At implementation authorization |
| 2 | `tests/golden/dl_geography_cases.csv` | **NEW** — the authoritative DL001–DL015 table, supplied verbatim by the repo owner | As soon as the owner pastes it |
| 3 | `tests/golden/test_dl_canonical_geography.py` | **NEW — ALREADY ADDED** (skip-gated; 7 tests) | Done in this analysis |
| 4 | `tests/golden/test_geography_canonical_unit.py` | **NEW (planned)** — disjointness invariant, determinism, C1 format gate, C4 territory validity, C5 invariant, C6 DL013 guard, reference-consistency | With implementation |
| 5 | `sql/006_create_canonical_geography_reference.sql` | **NEW** — DDL only, never executed by this analysis | File at implementation time; execution only with explicit authorization |
| 6 | `data_quality_platform/rules/registry.py` → `create_default` | Explicit `use_canonical_geography: bool = False` parameter | Separate authorized PR |
| 7 | `data_quality_platform/contracts.py` → `STATE_ZIP_PREFIXES` | Deprecation comment only (data untouched) | Same authorized PR |

**Explicitly untouched:** `v1_rules.py` (all 8 classes incl. R1–R3 name rules and
v1 geography classes), `SP1`, experiment `E1`, `sql/003_create_reference_tables.sql`,
all ClickHouse objects/data, `test_golden_cases.py` and existing fixtures.

---

## 6. DL001–DL015 comparison — BLOCKED PENDING AUTHORITATIVE TABLE (items 4–5)

The brief designates DL001–DL015 as **authoritative external acceptance evidence**
and forbids reconstruction from any fixture. The table is not present in the repo,
so items 4–5 (per-case comparison; the exact 8 disagreements) are **not fabricated
here**. Everything is armed so the comparison completes the moment the table lands:

- Harness: `python scripts/repro_prefix_map.py --dl <csv> [--dl-out <json>]` → prints
  and writes the exact disagreement list (case, state, zip, current vs canonical,
  disagreed fields).
- Tests: `tests/golden/test_dl_canonical_geography.py` — Group A structural checks,
  Group C divergence evidence with the acceptance-brief tripwire
  (`EXPECTED_DISAGREEMENT_COUNT = 8`: if the authoritative table yields ≠ 8, the test
  fails loudly and forces reconciliation between table and brief before any design
  decision is taken).
- Expected disagreement shape (from §3 semantics; to be confirmed by the table):
  malformed-ZIP rows (C1 vs no-format-check), territory/military rows (C4 vs absent
  codes), cross-state over-claim rows (13 ambiguous prefixes), and TX `733xx`
  false positives. The canonical expectation for DL013 is fixed by C6: mismatch = 0.
- **Open confirmation:** the clarification answer set DL013 = "plain valid row," but
  the instruction "DL013 MUST be exactly: …" arrived truncated. The pasted table is
  authoritative and will settle DL013's exact fields; until then no DL row values
  are assumed anywhere.

## 7. Test plan (item 10) and acceptance procedure

1. Owner pastes `dl_geography_cases.csv` (verbatim) → placed at
   `tests/golden/dl_geography_cases.csv` (or `DL_CASES_PATH` override).
2. `pytest tests/golden/test_dl_canonical_geography.py -v`
   - Group A (5 tests) must pass immediately — validates the table itself
     (15 cases, DL001–DL015, boolean canonical flags, C5 invariant, C6 DL013 guard).
   - Group C (1 test) executes the **current** v1 prefix map against the table and
     asserts exactly 8 current-vs-canonical disagreements — this *is* item 5 made
     executable, with per-case detail emitted to `DL_DIVERGENCE_OUT` when set.
   - Group B (1 test) stays skipped until the canonical module is merged, then
     asserts all 15 canonical expectations (item 10's acceptance assertion).
3. `pytest tests/golden tests/unit/test_rules.py` — baseline remains green
   (verified this session: 64 passed with the new file added).
4. Only after (1)–(3) reconcile: implementation PR per §4–§5, turning Group B green.
5. E1, SP1, R1–R3, ClickHouse: remain out of scope throughout.
