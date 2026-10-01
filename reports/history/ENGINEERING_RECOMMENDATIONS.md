# ENGINEERING RECOMMENDATIONS — Data Quality Platform V2

**Post-audit deliverable. NON-BINDING. These recommendations are NOT company requirements and must not be treated as such.**
**No recommendation has been implemented. The repository was intentionally left untouched by this phase.**

| Field | Value |
|---|---|
| Repository | `data-quality-platformV2` (branch `main`) |
| HEAD at issuance | `bc81ee019f24bbb3f37356b9e930e9be08dfe660` — working tree clean; no code, doc, or history changes made by this recommendations phase; the reviewed ZIP `data-quality-platformV2-reviewed-bc81ee019f24bbb3f37356b9e930e9be08dfe660.zip` (SHA-256 `1a82c2177258e4cbbb8833644c9760ae41d1699728d1b6abaf0e3110892ffb7b`) and `DELIVERY_MANIFEST.json` remain valid |
| Audit basis | Full forensic re-review at this HEAD, freshly re-verified: pytest **291 passed / 9 skipped / 0 failed** (300 collected; skips = 7× DL table absent, 1× Docker/ClickHouse unavailable, 1× Airflow not installed); SP1 independent oracle **ALL CHECKS PASSED** (7/7 acceptance cases, golden hashes 3/3, Q21 recompute PARTIAL==PARTIAL); prefix-map repro 25 probes / 0 mismatches; CLI verify **20 PASS / 2 PARTIAL / 0 FAIL**; security scan: no secrets, PII synthetic-by-design; tracked-file drift after all runs: **0** |
| ClickHouse mutations | **0** (no client exists in application code; this session performed no ClickHouse operation beyond the test suite's skip-gated health probe, which found the endpoint refused) |
| SP1 / E1 state | SP1: contract VERIFIED, pure implementation complete, **NOT activated**. E1: does not exist as code, **NOT executed, NOT authorized** |
| Semantic authority | The 2026-09-01 company document *"Geography rule — canonical definition and acceptance cases"* (SHA-256 `0cf6eb93…`, pinned in `data_quality_platform/geography/canonical.py`) remains the sole semantic authority for SP1. Nothing below modifies, reinterprets, or extends company-defined semantics. |
| Classification key | **1 = COMPANY REQUIREMENT** (depends on a company decision/input; must not be implemented unilaterally) · **2 = ENGINEERING IMPROVEMENT** (engineering correctness/robustness; no company-defined semantics touched) · **3 = OPTIONAL / NICE-TO-HAVE** (hygiene, docs, tooling) |

---

## R1 — Canonical snapshot provider for SP1 (`SnapshotTwoReferenceProvider`)

- **Classification:** 2 — ENGINEERING IMPROVEMENT
- **Current repository state:** `geography/references.py` defines the injectable `TwoReferenceProvider` interface (L62–76), `ReferenceUnavailableError` (L56), and `CANONICAL_SOURCE_TABLE = "tips_data.tblZipStCtyIB"` (L53). The ONLY implementation is `InMemoryTwoReferenceProvider` (L102–131), a scope-guarded controlled-fixture provider. No loader for any physical source exists. README §8 records the agreed unblock path: authorized read-only access OR company-supplied hash-identified snapshots at `data/canonical_zip_reference.csv` / `data/cross_reference_snapshot.csv`.
- **Problem/risk addressed:** SP1 can never progress beyond pure-semantics verification; absence of a sanctioned loading path invites someone eventually improvising a non-provenance source (the exact failure mode the no-fabrication rule forbids).
- **Proposed solution:** add a `SnapshotTwoReferenceProvider` that loads the two company-supplied CSV snapshots, verifies their SHA-256 against hashes pinned in config, applies the contract filter internally, and raises `ReferenceUnavailableError` on missing file / hash mismatch (fail-closed). Separately (later, only with credentials), a read-only ClickHouse-backed provider implementing the same interface. No registry change, no activation.
- **Changes business/rule semantics:** NO — resolution logic is already fixed by the company contract; this only supplies data.
- **Requires company approval:** the loader code NO; the DATA itself YES (snapshots must be company-supplied with provenance).
- **Affects SP1:** YES — it is the enabler for eventual activation; does not activate anything by itself.
- **Affects E1:** NO.
- **Affects ClickHouse:** future provider would be SELECT-only against the designated table; no writes; nothing executed until credentials exist.
- **Implementation risk:** LOW — additive module + fail-closed tests verifiable without live ClickHouse.
- **Priority:** HIGH
- **Exact files/symbols:** `data_quality_platform/geography/references.py` (new class); `configs/quality.yaml` (new `canonical_snapshot:` keys); NEW `tests/unit/test_snapshot_provider.py`; `docs/CANONICAL_GEOGRAPHY_DESIGN.md`; README §8.
- **Safe before production authorization:** YES — implementation and hash-failure/presence tests run today; live-source verification deferred until authorized access exists.

## R2 — Explicit, default-off SP1 activation gate (config-driven geography rule mode)

- **Classification:** 2 — ENGINEERING IMPROVEMENT
- **Current repository state:** `rules/registry.py::create_default()` (L38–54) hardcodes the eight V1 rules; `runner/cli.py::cmd_validate` (L40–50) and the Airflow DAG (`quality_validation`, L51–66) both call it directly. There is no configuration surface for rule selection at all, and no gate that would prevent an accidental or undocumented successor swap.
- **Problem/risk addressed:** the highest-risk moment in this platform's future is the V1→canonical swap. With no explicit mode switch, activation could happen via an unreviewed code edit rather than a visible, auditable configuration change.
- **Proposed solution:** add a registry factory parameter (e.g., `geography_rule_mode: v1 | sp1_canonical`, default `v1`) carried in `PlatformConfig`; `sp1_canonical` refuses to construct unless the R1 provider verifies its snapshots (fail-closed). Default behavior remains byte-identical to today. Flipping the switch to `sp1_canonical` in any production context requires company approval; the mechanism itself is neutral.
- **Changes business/rule semantics:** NO while default `v1` (provably identical output); YES only at the moment the company authorizes the flip.
- **Requires company approval:** mechanism NO; flipping the switch YES.
- **Affects SP1:** YES — this is the activation mechanism.
- **Affects E1:** NO.
- **Affects ClickHouse:** NO directly (provider data path per R1).
- **Implementation risk:** MEDIUM — touches the registry creation path used everywhere; the legacy-isolation tripwire tests (63-test SP1 suite, golden GC011/GC037) must keep passing unchanged.
- **Priority:** HIGH
- **Exact files/symbols:** `data_quality_platform/rules/registry.py` (`create_default`, new `create(mode=…)`); `data_quality_platform/config/settings.py` (new field); `configs/quality.yaml`; `runner/cli.py::cmd_validate`; `airflow/dags/dq_validation_dag.py::quality_validation`; tripwires in `tests/golden/test_golden_cases.py`, `tests/unit/test_sp1_geography_contract.py`.
- **Safe before production authorization:** YES — default-off, behavior-identical; tripwire tests prove no drift.

## R3 — Fix decorative configuration loading (`PlatformConfig.from_yaml` silently drops ALL YAML values)

- **Classification:** 2 — ENGINEERING IMPROVEMENT
- **Current repository state:** EMPIRICALLY PROVEN DEFECT (probe executed during this review; probe script persisted at `scripts/verify_config_drop.py` outside the repo). `config/settings.py::from_yaml` (L56–89) looks YAML keys `completeness`, `validity`, … up against dataclass fields named `completeness_threshold`, … — no key matches, so every threshold is dropped; the nested sections `evidence:`, `security:`, `monitoring:`, `clickhouse:` are never flattened either. A probe YAML with `completeness: 0.11`, `generate_manifests: false`, `pii_masking_enabled: false`, `monitoring_enabled: false`, `clickhouse.host: 10.9.9.9` loaded to a config identical to defaults (all values silently discarded). Additionally, `PlatformConfig` is never instantiated outside an import-only contract test (`tests/contract/test_imports.py` L66–67): `cmd_validate` and the DAG never pass `config_thresholds`, so `QualityMonitor` (monitoring/quality.py L26–36) always uses hardcoded defaults — which today happen to equal the YAML values, masking the defect.
- **Problem/risk addressed:** the config file promises enforcement it does not deliver; any future YAML edit is silently ignored; auditors reading `configs/quality.yaml` would wrongly conclude thresholds are configurable.
- **Proposed solution:** correct the key mapping (`quality_thresholds.*` → `*_threshold` fields), flatten and apply the nested sections, instantiate `PlatformConfig` in `cmd_validate` and the DAG and wire thresholds into `ValidationEngine`/`QualityMonitor`; add unit tests asserting that a YAML override actually changes the computed SLA outcome (and that today's file yields values identical to current defaults — net-zero behavior change).
- **Changes business/rule semantics:** NO — monitoring/evidence plumbing only; no rule, flag, or geography semantics touched. Runtime behavior becomes "as documented" once live.
- **Requires company approval:** NO (values in the file are repo-defined and unchanged).
- **Affects SP1:** NO. **Affects E1:** NO. **Affects ClickHouse:** NO (config fields stay env-indirected, read-only; no client is added).
- **Implementation risk:** MEDIUM — makes config live; net-zero today because defaults == YAML values; must be test-proven.
- **Priority:** HIGH
- **Exact files/symbols:** `data_quality_platform/config/settings.py::from_yaml` (L83–89 mapping + section flattening); `runner/cli.py::cmd_validate`; `airflow/dags/dq_validation_dag.py::quality_validation`; NEW `tests/unit/test_config_wiring.py`; `data_quality_platform/monitoring/quality.py::QualityMonitor` (unchanged, consumes wired thresholds).
- **Safe before production authorization:** YES.

## R4 — Supply the authoritative DL001–DL015 acceptance table

- **Classification:** 1 — COMPANY REQUIREMENT
- **Current repository state:** `tests/golden/dl_geography_cases.csv` is ABSENT. `tests/golden/test_dl_canonical_geography.py` skip-gates 7 tests on it (L62–66: *"external evidence to be supplied verbatim by the repo owner; it is never reconstructed from existing fixtures"*). FINAL_REMEDIATION_REPORT §8/§9: only 5/15 partial prose descriptions were accessible; reconstruction is forbidden. The module expects 15 cases, required columns `case_id, state, zip, canonical_zip_state_assessable, canonical_geography_mismatch_candidate`, the canonical invariant (mismatch ⇒ assessable), DL013 as non-defect control, and exactly 8 current-vs-canonical disagreements (L49).
- **Problem/risk addressed:** geography acceptance cannot complete; SP1/DL status stays PARTIALLY AVAILABLE / NOT FULLY VERIFIED.
- **Proposed solution:** company supplies the 15-row table verbatim, with provenance. The test module already supports `DL_CASES_PATH` override; nothing else is needed to run Group A/C.
- **Changes business/rule semantics:** the TABLE IS company-defined semantics; engineering side changes nothing.
- **Requires company approval:** YES — it is a company action.
- **Affects SP1:** YES — completes its acceptance evidence. **Affects E1:** NO. **Affects ClickHouse:** NO.
- **Implementation risk:** n/a (company input).
- **Priority:** HIGH
- **Exact files/symbols:** `tests/golden/dl_geography_cases.csv` (NEW, company-supplied only); consumer: `tests/golden/test_dl_canonical_geography.py`.
- **Safe before production authorization:** n/a — it is a prerequisite input, not an implementation.

## R5 — Authorize canonical reference data (read-only ClickHouse access or company snapshot)

- **Classification:** 1 — COMPANY REQUIREMENT
- **Current repository state:** `tips_data.tblZipStCtyIB` unreachable (no driver, no credentials, no Docker; endpoint refused). `sql/003_create_reference_tables.sql` defines only prefix-shaped `state_zip_reference` and `quality_rules` — neither two-reference canonical tables nor the source table exist in repo SQL. No snapshot exists anywhere; fabrication forbidden and not done. README §8 records the two sanctioned unblock options.
- **Problem/risk addressed:** SP1 activation and full DL verification are both blocked on physical reference data.
- **Proposed solution:** company either grants authorized read-only access to the designated source table, or supplies the two hash-identified snapshot CSVs (consumed by R1's provider).
- **Changes business/rule semantics:** NO — data provisioning; semantics already fixed by the contract.
- **Requires company approval:** YES — entirely a company decision/action.
- **Affects SP1:** YES (enabler). **Affects E1:** NO. **Affects ClickHouse:** read-only SELECT at most; zero writes; nothing happens until the company acts.
- **Implementation risk:** n/a.
- **Priority:** HIGH
- **Exact files/symbols:** `data/canonical_zip_reference.csv`, `data/cross_reference_snapshot.csv` (company-supplied, gitignored paths per `.gitignore` `data/generated/*.csv` pattern needs a new explicit entry) or credentials via existing env vars `DQ_CLICKHOUSE_*` (`config/settings.py` L64–74).
- **Safe before production authorization:** n/a.

## R6 — Company decision on V1 geography known defects (fix V1 vs successor-only remediation)

- **Classification:** 1 — COMPANY REQUIREMENT
- **Current repository state:** V1 `STATE_ZIP_PREFIXES` (`contracts.py` L47–67, 51 entries incl. DC duplicated `["20","20"]` L51) has documented, pinned, UNFIXED-by-design weaknesses (FINAL_REMEDIATION_REPORT §6.4; README §7): territory/military codes absent from V1 (11 codes in the SP1 62-code allowlist are not in V1: 8 territory codes AS FM GU MH MP PR PW VI + 3 military AA AE AP); 13 ambiguous 2-digit prefixes (02 03 19 22 24 38 71 83 84 88 96 97 99); real-Austin false positives pinned by golden tripwires GC011 TX/73301, GC037 TX/73302. V1 semantics are company-defined production behavior; the defects are documented rather than silently altered.
- **Problem/risk addressed:** known systematic geography errors remain in production-flag output until the canonical successor is authorized; the company must decide whether V1 receives any interim correction or whether remediation is successor-only.
- **Proposed solution:** company decision. Option A: successor-only (current design; no V1 change). Option B: company-issued corrected V1 semantics implemented as a versioned rule change. No unilateral engineering action.
- **Changes business/rule semantics:** only if Option B is chosen — which is precisely why it needs company approval.
- **Requires company approval:** YES.
- **Affects SP1:** YES (defines the interim relationship between V1 and SP1). **Affects E1:** NO. **Affects ClickHouse:** Option A no; Option B no (prefix map is in code).
- **Implementation risk:** n/a for the decision; Option B would be a versioned semantic change requiring the full golden/evidence treatment.
- **Priority:** HIGH
- **Exact files/symbols (read-only until decided):** `data_quality_platform/contracts.py::STATE_ZIP_PREFIXES`; `data_quality_platform/rules/v1_rules.py::ZipStateAssessable / GeographyMismatchCandidate`; documentation `docs/FALSE_POSITIVE_REVIEW.md`, `docs/GULNARA_REVIEW.md`.
- **Safe before production authorization:** no change is to be made; nothing to implement unilaterally.

## R7 — Design-note the DL Group B implementation bridge (API gap: `rules.geography_canonical` vs `geography/canonical.py`)

- **Classification:** 2 — ENGINEERING IMPROVEMENT
- **Current repository state:** `tests/golden/test_dl_canonical_geography.py` Group B (L143–168) `importorskip("data_quality_platform.rules.geography_canonical")` and calls `geo.evaluate_geography(row={"state": …, "zip": …})` — a row-dict API returning flag-keyed results. The SP1 pure module exposes `evaluate_geography(zip_raw, state_raw, provider)` returning a `GeographyAssessment` dataclass (`geography/canonical.py` L285–333). These are DIFFERENT modules and APIs, deliberately so: the DL gate anticipates a future registered-style canonical module.
- **Problem/risk addressed:** when the DL table (R4) and authorization both arrive, an implementer could conflate the two APIs or improvise an adapter with semantic drift at the most dangerous moment of the project.
- **Proposed solution:** documentation only (now): a section in `docs/CANONICAL_GEOGRAPHY_DESIGN.md` mapping the SP1 module to the future `rules/geography_canonical.py` row-API adapter, including provider injection per R1 and the invariant that the adapter must be a thin, provenance-preserving delegate — no new semantics.
- **Changes business/rule semantics:** NO (design note; the actual bridge is gated on company authorization).
- **Requires company approval:** the note NO; the eventual canonical swap YES.
- **Affects SP1:** YES (its future production integration path). **Affects E1:** NO. **Affects ClickHouse:** indirectly via R1 only.
- **Implementation risk:** LOW.
- **Priority:** MEDIUM
- **Exact files/symbols:** `docs/CANONICAL_GEOGRAPHY_DESIGN.md` (new section); future `data_quality_platform/rules/geography_canonical.py`; `tests/golden/test_dl_canonical_geography.py` L146–153 (import target — test semantics untouched).
- **Safe before production authorization:** YES.

## R8 — Airflow DAG `monitoring` task fails open on SLA breach / missing evidence

- **Classification:** 2 — ENGINEERING IMPROVEMENT
- **Current repository state:** `airflow/dags/dq_validation_dag.py::monitoring` (L69–79) prints SLA status and — if `monitoring.json` is missing — returns `{"sla_passed": False, "error": …}` WITHOUT raising; the task and therefore the DAG complete green. `evidence_finalization` (L82–92) raises only when the manifest file is absent, not when the manifest is of failure type. DAG uses the V1 registry (L18/43/56) and `schedule=None` (L109). Airflow is not installed here; the suite marks the DAG `DESIGNED_BUT_NOT_RUNTIME_VERIFIED` (runtime test skip, `tests/runtime/test_runtime.py` L156).
- **Problem/risk addressed:** an SLA breach or an evidence gap would surface nowhere in orchestration — silent green in the layer whose job is to surface it.
- **Proposed solution:** `monitoring()` raises (or marks the task failed via Airflow semantics) when `sla_passed` is false or the file is missing; `evidence_finalization` additionally rejects failure-type manifests. Keep it config-consistent with `alert_on_sla_breach` settings once R3 makes config live.
- **Changes business/rule semantics:** NO — orchestration/monitoring only; no rule or flag semantics.
- **Requires company approval:** NO.
- **Affects SP1:** NO. **Affects E1:** NO. **Affects ClickHouse:** NO.
- **Implementation risk:** LOW–MEDIUM — cannot be runtime-verified in this environment (Airflow absent); import-level tests only.
- **Priority:** MEDIUM
- **Exact files/symbols:** `airflow/dags/dq_validation_dag.py::monitoring / evidence_finalization`; import-gated assertions in `tests/runtime/test_runtime.py`.
- **Safe before production authorization:** YES.

## R9 — CI pipeline: pytest + evidence-drift check + security scan on every push

- **Classification:** 2 — ENGINEERING IMPROVEMENT
- **Current repository state:** NO CI configuration exists (no `.github/` directory; verified). `pyproject.toml` defines pytest markers (`clickhouse`, `runtime`, …) but no workflow consumes them. All verification is manual (this audit's scripts live outside the repo).
- **Problem/risk addressed:** regressions or evidence side effects can land unnoticed between manual audits; the Rev-3 harness-side-effect class of defect is only caught when someone re-runs the full battery by hand.
- **Proposed solution:** a minimal GitHub Actions workflow: `pip install -e ".[dev]"`, `pytest -rs -q`, then `git status --porcelain` MUST be empty (drift gate), then the repo's security-scan pattern. No secrets, no ClickHouse service, no Docker.
- **Changes business/rule semantics:** NO. **Requires company approval:** NO (repo-infra only; pushing to GitHub is a separate, currently unauthorized action).
- **Affects SP1:** NO. **Affects E1:** NO. **Affects ClickHouse:** NO (explicitly no service).
- **Implementation risk:** LOW.
- **Priority:** MEDIUM
- **Exact files/symbols:** NEW `.github/workflows/ci.yml`; README §18 (reproduction commands) note.
- **Safe before production authorization:** YES.

## R10 — Define the production IAM target state (Q18 remains PARTIAL)

- **Classification:** 1 — COMPANY REQUIREMENT
- **Current repository state:** CLI verify Q18 = PARTIAL, evidence string verbatim: *"RBAC and masking verified; production IAM not implemented"* (`runner/cli.py` L394–409). In-repo: `PIIMasker` + in-memory `RBACManager` (`security/auth.py`, `security/pii_masking.py`); no external identity provider, no production authn.
- **Problem/risk addressed:** before any production deployment someone must decide what "production IAM" means here (IdP integration? service accounts? token scopes?).
- **Proposed solution:** company defines the target state and requirements; engineering follows with a versioned, tested implementation.
- **Changes business/rule semantics:** NO (security infrastructure). **Requires company approval:** YES (defines it).
- **Affects SP1:** NO. **Affects E1:** NO. **Affects ClickHouse:** potentially (credential model for future read-only access should be defined together).
- **Implementation risk:** deferred until specified.
- **Priority:** MEDIUM
- **Exact files/symbols:** `data_quality_platform/security/auth.py::RBACManager / AuthContext / Permission`; `SECURITY.md`; CLI verify Q18.
- **Safe before production authorization:** n/a — company action first.

## R11 — Operator guard for `verify` into the tracked historical evidence directory

- **Classification:** 2 — ENGINEERING IMPROVEMENT
- **Current repository state:** `runner/cli.py::cmd_verify` (L115) defaults `--evidence-dir` to `evidence/verification/` — a TRACKED directory containing historical evidence (`verification_report.{json,md}`, SHAs recorded since Rev-1). The Rev-3 fix deliberately preserved this production default and isolated only the test harness. Any operator running `python -m runner.cli verify` without `--evidence-dir` overwrites tracked historical evidence (by design of the original CLI contract).
- **Problem/risk addressed:** accidental historical-evidence overwrite during demos or company-review walkthroughs; git protects recoverability but the event itself is undesirable and confusing in audit trails.
- **Proposed solution:** warning-only (no behavior change): if the resolved evidence dir contains tracked historical report paths, print a prominent notice recommending an explicit `--evidence-dir`, plus (optionally) a `--force` flag. Do NOT change the default; do NOT make the command interactive.
- **Changes business/rule semantics:** NO — CLI ergonomics; default behavior unchanged.
- **Requires company approval:** changing the DEFAULT would need approval; the warning does not.
- **Affects SP1:** NO. **Affects E1:** NO. **Affects ClickHouse:** NO.
- **Implementation risk:** LOW.
- **Priority:** MEDIUM
- **Exact files/symbols:** `runner/cli.py::cmd_verify` (L112–142); new test in `tests/runtime/` or `tests/integration/` asserting default path unchanged + notice printed.
- **Safe before production authorization:** YES.

## R12 — Deterministic default run IDs (clock-free identifiers)

- **Classification:** 3 — OPTIONAL / NICE-TO-HAVE
- **Current repository state:** `runner/cli.py::cmd_validate` L42 and `ValidationEngine.validate` L97 fall back to `run_{int(time.time())}`; CLI verify stamps `datetime.now(timezone.utc)` into reports. Rules themselves are clock-free (contract tripwires prove it), but run identifiers are not reproducible.
- **Problem/risk addressed:** identical inputs produce different run IDs; weaker evidence cross-referencing; deterministic reproduction requires remembering `--run-id`.
- **Proposed solution:** derive the default run ID from input content hash + schema hash (e.g., `run_<16hex>`), or require explicit `--run-id` in production profiles; document either way.
- **Changes business/rule semantics:** NO. **Requires company approval:** NO. **Affects SP1:** NO. **Affects E1:** NO. **Affects ClickHouse:** NO.
- **Implementation risk:** LOW (evidence manifests embed run_id — consumers must be checked).
- **Priority:** LOW
- **Exact files/symbols:** `runner/cli.py::cmd_validate`; `data_quality_platform/validation/engine.py::ValidationEngine.validate`; tests asserting determinism of run_id.
- **Safe before production authorization:** YES.

## R13 — Add `.env.example` documenting the supported environment variables

- **Classification:** 3 — OPTIONAL / NICE-TO-HAVE
- **Current repository state:** `.gitignore` explicitly allows `!.env.example`, but no `.env.example` exists (security scan: no .env-style files). The supported vars are only discoverable by reading `config/settings.py` L64–74 (`DQ_CLICKHOUSE_HOST/PORT/USER/PASSWORD`, `DQ_SLACK_WEBHOOK_URL`, `DQ_SMTP_*`).
- **Problem/risk addressed:** operators may guess variable names; a placeholder file prevents both guessing and accidental real-secret commits.
- **Proposed solution:** add `.env.example` with empty/placeholder values and comments; no real values ever.
- **Changes business/rule semantics:** NO. **Requires company approval:** NO. **Affects SP1/E1/ClickHouse:** NO (no credentials included).
- **Implementation risk:** LOW. **Priority:** LOW
- **Exact files/symbols:** NEW `.env.example`; README §15 cross-reference.
- **Safe before production authorization:** YES.

## R14 — Document the expected SLA-breach alert on synthetic fixtures

- **Classification:** 3 — OPTIONAL / NICE-TO-HAVE
- **Current repository state:** CLI verify on synthetic data emits `[ALERT WARNING] sla_breach: SLA breach for email_quality: score=0.85, threshold=0.95` (reproduced during this review). The synthetic generator deliberately includes malformed emails (documented as synthetic-by-design in the security scan). The alert is the monitoring system working correctly on intentionally defective fixtures — but nothing in the repo explains that to a first-time reader.
- **Problem/risk addressed:** the warning can be misread as a platform defect during company review.
- **Proposed solution:** one paragraph in README §13/§17: expected, by-design, fixture-induced; real-data SLA behavior unchanged.
- **Changes business/rule semantics:** NO. **Requires company approval:** NO. **Affects SP1/E1/ClickHouse:** NO.
- **Implementation risk:** LOW. **Priority:** LOW
- **Exact files/symbols:** `README.md` (§13 Tests and/or §17 Limitations).
- **Safe before production authorization:** YES.

---

## A. MUST FIX BEFORE COMPANY REVIEW

1. **Documentation precision: "8 territory/military state codes absent" (FINAL_REMEDIATION_REPORT §6.4, README §7, docs/DATA_FLOW_MAP.md).** Verified actual delta between the V1 51-entry map and the SP1 62-code allowlist is **11 codes**: 8 territory/commonwealth (AS FM GU MH MP PR PW VI) **plus** 3 military (AA AE AP). The count "8" is correct for territories only; the wording conflates the two groups. One-line precision edit per file (documentation only — NOT applied now per the no-modification instruction; on approval this is a 3-line doc change + report revision note).
   Nothing else blocks company review: the repository at `bc81ee0` is fully described by the rebuilt README, all statuses are evidence-backed, and the full verification battery is green.

## B. SHOULD FIX BEFORE PRODUCTION

Engineering (implementable now, safely, before authorization — none change company semantics):
- **R3** config wiring fix (defect empirically proven) — HIGH
- **R2** default-off SP1 activation gate — HIGH
- **R1** snapshot provider (code + fail-closed tests; live data pending R5) — HIGH
- **R7** DL Group B bridge design note — MEDIUM
- **R11** operator guard for verify-into-tracked-evidence — MEDIUM
- **R8** DAG monitoring fails-open fix — MEDIUM

Company-gated prerequisites (cannot be engineered around):
- **R5** authorize canonical reference data (read-only access or hash-identified snapshots) — HIGH
- **R4** supply the authoritative DL001–DL015 table — HIGH
- **R6** decide V1-defect strategy (successor-only vs company-issued V1 correction) — HIGH
- **R10** define production IAM target state — MEDIUM

## C. OPTIONAL ENGINEERING IMPROVEMENTS

- **R9** CI pipeline (pytest + drift gate + security scan) — MEDIUM
- **R12** deterministic default run IDs — LOW
- **R13** `.env.example` — LOW
- **R14** synthetic-fixture SLA-breach note in README — LOW

## D. DO NOT CHANGE — ALREADY COMPLIANT

- **V1 production registry and semantics.** The eight v1.0.0 rules — including `ZipStateAssessable` (presence-only: non-empty zip + state in map, NO ZIP-format check) and `GeographyMismatchCandidate` (prefix `startswith`) — are company-defined production behavior. Any "improvement" here is a semantic change requiring company approval. Do not touch.
- **SP1 module purity and isolation.** `geography/canonical.py` + `geography/references.py`: pure, deterministic, no ClickHouse I/O, no clock, no legacy imports (tripwired), contract provenance pinned, deliberately unregistered. Compliant with the 2026-09-01 contract; do not alter its semantics.
- **Q21 fail-closed scope aggregation.** No hard-coded PASS (verified: no `return "PASS"` literal; consumes `aggregate_scope(results)`); PARTIAL verdict with `UNIFORM_PASS_REQUIRED` is the designed honest outcome. Do not change.
- **E1 non-implementation.** E1 exists as documentation only (9 files, all documentation/status references incl. a test-module scope guard; zero code paths). NOT EXECUTED / NOT AUTHORIZED is the compliant state. Its documented 10-point safety precondition list must be preserved for any future authorized run. Do not "pre-implement" it.
- **PS1 non-existence.** Zero literal `PS1`/`ps1`/`*.ps1` occurrences; only the README transposition note. Nothing to fix; do not invent a PS1 component.
- **Historical evidence immutability.** `evidence/verification/`, `evidence/final_verification/`, `evidence/final/` byte-identical after the entire battery (tracked-drift check = 0); the Rev-3 harness fix removed the last rewriter at source. Do not redirect, rewrite, or "refresh" any of it.
- **No ClickHouse client in application code; SQL is schema-only; docker-compose is local-only.** Zero mutations across the whole engagement. Do not add a client outside the R1-provider path.
- **DL skip-gating design.** Skipping on absent authoritative evidence (never reconstructing fixtures) is the correct fail-closed behavior. Do not loosen.
- **Golden fixture integrity + synthetic PII policy.** Golden hashes verified 3/3 by the independent oracle; PII in evidence is synthetic-by-design with recorded exclusions. Already compliant.

---

### Verification appendix — commands and results at HEAD `bc81ee0` (this review, fresh runs)

| Check | Result |
|---|---|
| `python -m pytest -rs -q` | 291 passed / 9 skipped / 0 failed (300 collected); skips: 7× DL table absent · 1× Docker/ClickHouse unavailable · 1× Airflow not installed |
| `scripts/sp1_independent_oracle.py` (repo-external) | ALL CHECKS PASSED — 7/7 acceptance cases oracle==impl==expected; golden hashes 3/3; Q21 recompute PARTIAL==PARTIAL |
| `scripts/verify_q21_recompute.py` | ALL CHECKS PASSED — no `return "PASS"` literal; consumes `aggregate_scope` |
| `scripts/repro_prefix_map.py` | AST-extracted 51 state entries; 25 probes, 0 mismatches; DL comparison standing by |
| `python -m runner.cli verify --evidence-dir <scratch>` | 20 PASS / 2 PARTIAL / 0 FAIL (Q18, Q21 PARTIAL by design) |
| `scripts/final_security_scan.py` | No secrets detected; PII synthetic-by-design; no .env-style files |
| Post-run `git status --porcelain` | 0 entries — historical evidence byte-preserved |
| Config-drop probe (`scripts/verify_config_drop.py`, repo-external) | ALL YAML values silently dropped — defect confirmed |
| ClickHouse mutations during this review | **0** |

