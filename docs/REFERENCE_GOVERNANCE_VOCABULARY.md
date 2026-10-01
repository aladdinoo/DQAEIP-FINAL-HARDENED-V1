# Reference Data Governance — Enterprise Status Vocabulary Mapping

**Module**: `data_quality_platform/verification/reference_provenance.py`
**Scope**: DQAVP enterprise hardening, Section 13 (Reference Data Governance)

## Purpose

The platform's reference registry uses the operational vocabulary
defined when the provenance layer was built (`LOCAL`, `EXPERIMENTAL`,
`UNVERIFIED`). Enterprise governance additionally requires the
standardized release vocabulary (`VERIFIED`, `COMPANY_SUPPLIED`,
`EXPERIMENTAL`, `MISSING`, `REVIEW_REQUIRED`, `APPROVED`). This
document is the explicit, reviewed mapping between the two
vocabularies. No reference status is silently reinterpreted: the
operational value is always preserved alongside its enterprise
equivalent.

## Mapping (implemented additively in `map_status_to_enterprise_vocabulary`)

| Operational status | Enterprise status | Justification |
|---|---|---|
| `LOCAL` | `VERIFIED` | Locally defined AND frozen as part of the V1 contract since the baseline commit; hash pinned in the hardening baseline, cross-checked by rule/oracle consistency tests, and byte-verified in mutation testing restore checks. Verification basis is local execution — NOT company delivery. |
| `EXPERIMENTAL` | `EXPERIMENTAL` | SP1 successor semantics: validation-only, not registered in the production registry, physical references not delivered. |
| `UNVERIFIED` | `MISSING` | Claimed by a company document but the physical artifact was never delivered to this repository (e.g. the DL001–DL015 authoritative geography fixture). Missing physical reference data → fail-closed: never fabricated, never reconstructed. |
| `AUTHORITATIVE` | `COMPANY_SUPPLIED` | Company-delivered and verified inside this repository (none exist for geography today; the only company-supplied artifacts are the frozen contract documents). |
| `DERIVED` | `VERIFIED` | Derived deterministically from a delivered authoritative artifact, with the derivation recorded. |
| anything else | `REVIEW_REQUIRED` | Unknown statuses are never silently promoted; they fail to review. |

## Production decision references (registry facts, 2026-09-15)

| reference_id | operational status | enterprise status | sha256 present | row count |
|---|---|---|---|---|
| `state_zip_prefix_map_v1` | LOCAL | VERIFIED | yes | 51 states + DC |
| `suspicious_name_patterns_v1` | LOCAL | VERIFIED | yes | 20 patterns |
| `email_syntax_regex_v1` | LOCAL | VERIFIED | yes | 1 |
| `sp1_two_reference_provider` | EXPERIMENTAL | EXPERIMENTAL | yes (contract id) | 0 (physical refs never delivered) |
| `dl_geography_cases_company_fixture` | UNVERIFIED | MISSING | none (no artifact) | 0 (never delivered) |

## Fail-closed rules

1. A V1 production decision must never depend on a reference whose
   status maps to `MISSING` or `REVIEW_REQUIRED`.
2. Missing reference data for an *optional* component (SP1, DL
   acceptance) blocks that component's activation — it never blocks
   V1 execution, because V1's references are all `LOCAL`/`VERIFIED`.
3. No synthetic or reconstructed reference may be created to upgrade
   a `MISSING` entry. The registry records absence as absence
   (zero rows, no hash) — `no_fabrication_statement`.
