# PHASE 1 — Q21 CONTRACT ADJUDICATION

Status: ADJUDICATION COMPLETE — NO CODE CHANGED — STOPPING FOR REVIEW
Repo: data-quality-platformV2 @ 4065714c3c810c503020d60a8f726a485a5e09ac (single commit; tracked diff empty at end of Phase 1)

---

## 1. EXACT ORIGINAL Q21 REQUIREMENT (RECOVERED, VERBATIM)

Six sources exist; all carry identical requirement wording:

| # | Source | Location | Content |
|---|--------|----------|---------|
| S1 | `evidence/final_verification/VERIFICATION_MATRIX.json` | lines 203–211 | requirement: "V1 scope assessment" · expected: "All Q1-Q20 verified" · actual: "See individual Q results" · status: PASS · evidence: "evidence/final_verification/FINAL_VERIFICATION.json" · source: "" · test: "" |
| S2 | `evidence/final_verification/FINAL_VERIFICATION.json` | `q1_q22_results[20]` | identical fields to S1 |
| S3 | `FINAL_VERIFICATION_REPORT.md` | line 306 | Q21 row: PASS; evidence = FINAL_VERIFICATION.json; source "--"; test "--" |
| S4 | `README.md` | line 304 (+307, +309) | same Q21 row; same document states "Result: 20 PASS, 2 PARTIAL, 0 FAIL." and "Q18 is PARTIAL because production IAM (OAuth2/SAML/LDAP) is not implemented." |
| S5 | `scripts/run_final_verification.py` | lines 990–992 | generator: `add_q("Q21", "V1 scope assessment", "All Q1-Q20 verified", "See individual Q results", "PASS", evidence=..., source="", test="")` — hardcoded literal |
| S6 | `runner/cli.py` | lines 452–456 | live harness: `def q21(): return "PASS", "V1 scope verified - see individual Q results"` — hardcoded literal, zero aggregation |

Wording provenance: the phrase "All Q1-Q20 verified" enters history in the single Initial commit `4065714` (`git log --all -S` confirms no earlier artifact). Exhaustive repo sweep finds exactly three occurrences of the phrase (S1, S2, S5) plus the two rendered tables (S3, S4). No document in `docs/` (including `GULNARA_REVIEW.md`, `FALSE_POSITIVE_REVIEW.md`) mentions Q21 or defines the word "verified". The forensic audit deliverable (`Q1_Q22_ACCEPTANCE_AUDIT.md`, Q21 section + conflict #2) preserves the wording verbatim and requested exactly this owner decision.

Both historical Q21 = PASS records (S5, S6) are hardcoded literals — no mechanism ever computed them.

## 2. INTERPRETATION ADJUDICATION — A vs B

- **Interpretation A:** "All Q1-Q20 verified" = all Q1–Q20 must be **PASS**.
- **Interpretation B:** "All Q1-Q20 verified" = all Q1–Q20 must be **assessed with evidence-backed statuses**.

### Evidence favoring B (historical record)
1. The historical artifacts co-record, in the same generation run: Q18 = PARTIAL, Q19 = PARTIAL, **and** Q21 = PASS (S1 = S2 = S3 = S4). README (S4) presents "Result: 20 PASS, 2 PARTIAL, 0 FAIL." as the accepted outcome while showing Q21 = PASS in the same table. Under A, the historical record would contain a self-contradiction baked in at generation time.
2. The expected field's companion `actual` = "See individual Q results" — a coverage pointer, not a uniformity claim.
3. The requirement title is "V1 scope **assessment**" — assessment/coverage semantics.

### Why this does NOT make B authoritative
Every historical Q21 = PASS traces to a hardcoded literal (S5, S6), never to a mechanism. The co-existence of Q21 = PASS with two PARTIALs may therefore be precisely the defect under remediation rather than an owner's semantic ruling. The historical Q21 "evidence" pointer is FINAL_VERIFICATION.json — the artifact asserting the PASS itself (circular). No document or git history defines "verified".

### Why A is not adoptable by default either
No source states A. Adopting A would be an assumption — expressly forbidden by Phase 1 instruction 3.

### Adjudication
**Owner/business evidence is INSUFFICIENT to resolve A vs B.** Per Phase 1 instruction 5, the remediation implements a verification mechanism that reports the actual aggregate state **without changing the requirement**, never manufactures PASS, and keeps the unresolved semantics isolated behind one documented policy constant.

## 3. AUTHORITATIVE INTERPRETATION FOR IMPLEMENTATION (fail-safe, decision-neutral)

Not a resolution of A vs B — a reporting contract that is honest under **both** readings while the decision is open. Two mechanically checkable dimensions over the actual Q1–Q20 results:

- **D1 COVERAGE** (necessary for A and B): every Q1..Q20 executed exactly once, status ∈ {PASS, PARTIAL, FAIL, BLOCKED, NOT AUTHORIZED}, non-empty evidence.
- **D2 UNIFORMITY** (A's reading): all 20 statuses = PASS.

Deterministic status mapping:

| Condition | Verdict |
|-----------|---------|
| Any structural defect (missing ID / duplicate ID / unexpected ID in scope / invalid status / malformed result / empty evidence) | **FAIL** (fail closed — the assessment itself is broken) |
| D1 ok **and** D2 (all 20 PASS) | **PASS** — valid under both A and B |
| D1 ok, D2 fails (e.g., live state: 19 PASS + Q18 PARTIAL) | **PARTIAL** with full per-status composition disclosed — **never PASS** |

This directly implements the Phase 1 closing rule: *"If Q18 remains PARTIAL under the authoritative requirement, Q21 must NOT falsely report PASS merely because all questions were run."* Under the live repository state (Q18 = PARTIAL, Q1–Q20 = 19 PASS + 1 PARTIAL), the mechanism reports **PARTIAL**, not PASS.

**Policy isolation:** if the owner later rules B, the covered-but-not-uniform mapping flips PARTIAL → PASS by changing ONE named policy constant; requirement wording and mechanism unchanged. If the owner rules A, the mapping stands.

**Secondary policy point (surfaced, default chosen):** when a constituent is FAIL/BLOCKED/NOT AUTHORIZED (not merely PARTIAL), the default mapping still yields aggregate PARTIAL with the composition fully disclosed (counts make the constituent FAIL visible). Stricter alternative — any constituent FAIL/BLOCKED/NOT AUTHORIZED propagates aggregate FAIL — is documented as owner-overridable. Default avoids double-counting one constituent failure as two, since Q21's own requirement is scope assessment.

## 4. PROPOSED Q21 AGGREGATION LOGIC (to be implemented in Phase 2)

Pure, deterministic, no I/O, no clock. New module `data_quality_platform/verification/scope_aggregator.py` (final placement confirmed at implementation):

```
aggregate_scope(results: Sequence[Mapping]) -> ScopeAggregate
  expected_ids   = Q1..Q20 (fixed)
  ALLOWED        = {PASS, PARTIAL, FAIL, BLOCKED, NOT AUTHORIZED}
  defects        = missing ids | duplicate ids | unexpected ids in scope
                 | non-Mapping entries | missing required keys
                 | status not in ALLOWED | evidence empty/whitespace/non-string
  counts         = per-status tally over found results
  output (fixed key order, JSON-serializable, no timestamps/floats):
    scope, total_expected, total_found, missing[], duplicates[], unexpected[],
    invalid_status[], missing_evidence[], malformed[], counts{...},
    all_pass, coverage_ok, verdict, verdict_basis
```

`runner/cli.py::q21()` rewiring: feed the in-process results accumulated by `check()` (at q21 execution time this is exactly Q1–Q20, appended sequentially — the aggregator still fail-closes on any structural anomaly); return `(aggregate.verdict, deterministic evidence string)` where the evidence string carries counts, non-passing IDs, and defects.

Guarantees mapped to the Phase 2 spec: consumes actual Q1–Q20 results · verifies every required question executed · verifies allowed statuses · verifies evidence presence · distinguishes all five statuses · fails closed on missing results · never infers PASS from absence of errors · deterministic output · dedicated tests.

## 5. TESTS THAT WILL PROVE IT (Phase 2)

New dedicated file `tests/unit/test_q21_scope_aggregation.py`:

| # | Scenario | Expected verdict |
|---|----------|------------------|
| T1 | all Q1–Q20 PASS | PASS (all_pass, coverage_ok) |
| T2 | one PARTIAL (Q18 = PARTIAL, 19 PASS — the live case) | PARTIAL, explicitly not PASS |
| T3 | one FAIL constituent | PARTIAL + counts.FAIL = 1 (default mapping; stricter propagation documented as owner-overridable) |
| T4 | one missing result (Q9 absent) | FAIL (fail closed) |
| T5 | invalid status ("PASSED") | FAIL |
| T6 | malformed result (non-mapping / missing `question`) | FAIL |
| T7 | evidence missing (empty/whitespace) | FAIL |
| T8 | determinism: same input → byte-identical output across calls | identical |
| T9 | wiring/regression: run the verify path (same pattern as existing integration tests), recompute `aggregate_scope` over the report's Q1–Q20 results, assert equality with the recorded Q21 status — detects any future reversion to a hardcoded assertion (with Q18 = PARTIAL live, a hardcoded PASS fails this test) | agreement |
| T10 | scope hygiene: Q21/Q22 IDs injected into the Q1–Q20 window | FAIL (unexpected IDs) |

No Q18 modification in any test; no assertion weakened to obtain PASS.

## 6. IS AN OWNER DECISION STILL REQUIRED? — YES

**Decision D-OWNER-Q21 (single, narrow):** semantics of "verified" in Q21's expected field.
- **Option A** (all Q1–Q20 must be PASS): mapping stands as proposed; with Q18 = PARTIAL, Q21 reports PARTIAL until production IAM is actually implemented (Phase 10 keeps Q18 PARTIAL — no greenwashing).
- **Option B** (all Q1–Q20 assessed with evidence-backed statuses): one policy constant flips covered-but-not-uniform to PASS; Q21 would then report PASS today (coverage_ok; 19 PASS + 1 PARTIAL), with the composition still disclosed.

Until adjudicated, the fail-safe mapping (Section 3) is active: no PASS is manufactured under either reading. Phases 2–14 can proceed without waiting — the mechanism is decision-neutral; only the final status-mapping constant depends on the owner's answer. The secondary FAIL-propagation policy point can be bundled into the same decision.

## 7. PHASE 1 CONDUCT — NOTHING CHANGED

- Zero production file modifications in Phase 1. This report is documentation only.
- Working-tree hygiene: `evidence/verification/verification_report.{json,md}` had been regenerated with a new timestamp (12:54 UTC) by the prior session's full-suite run — the known `runner/cli.py:121–126` pytest side effect. Diff verified timestamp-only, restored to HEAD bytes via `git checkout --`. Final tracked diff: **empty**. Untracked: only the two known prior-session artifacts (`docs/CANONICAL_GEOGRAPHY_DESIGN.md`, `tests/golden/test_dl_canonical_geography.py`), untouched.
- Live Q1–Q20 composition (from the committed harness output): Q1–Q17 PASS, Q18 PARTIAL, Q19 PASS, Q20 PASS → 19 PASS + 1 PARTIAL; Q21 currently self-asserts PASS (S6) — the defect Phase 2 removes.

**STOPPING FOR REVIEW BEFORE ANY CODE CHANGE.**
