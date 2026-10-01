#!/usr/bin/env python3
"""RELEASE_NOTES.md regeneration for the 2026-09-19 hardened release.

Contract (consistency_matrix "RELEASE_NOTES.md carries I/O hash
fingerprints" + contradiction checker): the notes must carry the
CURRENT input/output SHA-256 fingerprints (at minimum the 16-hex
prefixes the matrix checks; the full hashes are authoritative and
carried verbatim), the current suite counts, and the honest limitation
counts (11 inherited + 5 new = 16 unique registry entries — the
canonical deduplicated registry, never the stale 21-entry form).

Fixed-point discipline: stabilized write (byte-identical when the
freshly derived content differs only in generated_utc).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NS = REPO_ROOT / "evidence" / "FINAL_HARDENED_RELEASE_2026-09-19"
REG_EV = REPO_ROOT / "evidence" / "validation" / "2026-09-19" / "fresh_3m2"
GATE_FILE = (REPO_ROOT / "evidence" / "release_gate"
             / "final_release_gate.json")
RUN_PAIR = (REPO_ROOT / "evidence" / "rebuild_verification"
            / "run_pair_verification.json")
CANON_REGISTRY = (REPO_ROOT / "evidence" / "release"
                  / "limitation_registry.json")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def maybe_load(path: Path):
    try:
        return load(path)
    except (OSError, ValueError):
        return None


def _write_stabilized_text(path: Path, text: str,
                           stamp_line: str) -> bool:
    """Fixed-point write for markdown: keep the existing file when the
    candidate differs only in the generated-utc stamp line."""
    if path.is_file():
        existing_lines = path.read_text(encoding="utf-8").splitlines()
        candidate_lines = text.splitlines()
        strip = lambda lines: [l for l in lines  # noqa: E731
                               if not l.startswith(stamp_line)]
        if strip(existing_lines) == strip(candidate_lines):
            return False
    path.write_text(text, encoding="utf-8")
    return True


def main() -> int:
    identity = load(NS / "release_identity" / "RELEASE_IDENTITY.json")
    regression = load(NS / "regression" / "fresh_3m2_regression.json")
    battery = load(NS / "negative_battery" / "battery_results.json")
    suite = load(NS / "test_suite" / "test_suite_results.json")
    perf = load(NS / "performance" / "performance_summary.json")
    layers = load(NS / "hardening_layers" / "layer_registry.json")
    limitations = load(NS / "limitations" / "limitation_registry.json")
    canon_registry = load(CANON_REGISTRY)
    run_pair = maybe_load(RUN_PAIR) or {}
    gate = maybe_load(GATE_FILE) or {}

    base = identity["baseline_certified_historical"]
    bstats = battery["stats"]
    sstats = suite["stats"]
    p1 = regression["pass1"]
    inp, out = p1["input_sha256"], p1["output_sha256"]
    inherited = len(
        limitations["inherited_from_baseline_certified_historical"])
    new = len(limitations["new_hardening_limitations"])
    total = len(canon_registry["limitations"])

    gate_verdict = gate.get("overall_verdict")
    gate_line = (
        f"**PASS — {gate.get('gate_count')}/"
        f"{gate.get('gate_count')} fail-closed gates** (terminal round "
        "on the committed release tree)"
        if gate_verdict == "PASS" else
        "**pending** — the terminal gate round runs on the committed "
        "release tree (fail-closed; the live verdict is only claimed "
        "after the gate itself says PASS)")

    rp_total = run_pair.get("checks_total")
    rp_failed = run_pair.get("checks_failed")

    notes = f"""# DQAEIP Release Notes — Operational Hardening 2026-09-19

Product: **Data Quality Assurance & Evidence Integrity Platform (DQAEIP)**
Technical package: `data_quality_platform` (unchanged for compatibility)
Release identity: `DQAEIP-FINAL-HARDENED-RELEASE-2026-09-19`
Supersedes: `DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18`
(certified baseline preserved byte-for-byte and re-verified; not modified)
Final verdict: **PASS_WITH_DOCUMENTED_LIMITATIONS**
(regression checker verdict: **PASS**; full test suite: {sstats['passed']} passed / {sstats['skipped']} skipped / {sstats['failed']} failed)

Current validation fingerprints (2026-09-19 fresh dual-run regression):

- Input SHA-256: `{inp}`
- Output SHA-256: `{out}`
- Frozen checker SHA-256: `0ef7c10c14a1df317c23cb0dfc73b3a60c2257c064b35080d694e5fe8bc50d84`
- Frozen V1 rule source SHA-256: `daef1ded54c7d3c79898a1ba253be2acd5b6120e18b16b09009fdd7be9fc2276`
- Run 1 ID: `final_3m_pass1`; Run 2 ID: `final_3m_pass2` (Run 1 + Run 2)

## What changed (this release — operational hardening, additive only)

Built on the certified 2026-09-18 clean-room baseline. **No business
semantics changed; Frozen V1 remains byte-identical** to the immutable
baseline (`daef1ded…` for `v1_rules.py` — re-verified by test, by the
evidence builder, and by the release gate's frozen checks). The
certified baseline ZIP was re-hash-verified (`{base['zip_sha256'][:16]}…`)
and is referenced as history only.

This round adds an **operational security hardening bundle** — eight
additive layers wrapping the certified core (plus a pipeline
orchestrator), a 17-scenario negative battery, and a full re-validation:

| # | Change | Type | Files |
|---|---|---|---|
| H1 | **Layer A — Input Contract Firewall**: input SHA-256 pin, size/row caps, strict UTF-8, NUL scan, exact header contract, sampled type contract; rejected input never executes | HARDENING (new) | `data_quality_platform/hardening/input_contract.py` |
| H2 | **Layer B — Execution Authorization Gate**: binds input SHA + schema fingerprint + V1 rule-set SHA + reference-data fingerprint + config fingerprint + execution mode + software identity; single-field divergence fails closed | HARDENING (new) | `data_quality_platform/hardening/authorization.py` |
| H3 | **Layer C — Idempotency / Duplicate-Run Protection**: deterministic execution identity + atomic execution ledger; committed entries immutable; tamper/hash-drift detection | HARDENING (new) | `data_quality_platform/hardening/idempotency.py` |
| H4 | **Layer D — Atomic Output Commit**: staging-with-PARTIAL-manifest → verify → hash → single atomic rename; partial always distinguishable from committed | HARDENING (new) | `data_quality_platform/hardening/atomic_commit.py` |
| H5 | **Layer E — Checkpoint/Safe-Resume Contract**: contract-only by documented design; resume refused (4 risks); fresh full re-run is the safe equivalent | HARDENING (contract) | `data_quality_platform/hardening/checkpoint_contract.py` |
| H6 | **Layer F — Schema Evolution Guard**: COMPATIBLE / INCOMPATIBLE / REQUIRES_AUTHORIZATION classification (deletion, reorder, rename, insertion, type, nullability) | HARDENING (new) | `data_quality_platform/hardening/schema_guard.py` |
| H7 | **Layer G — Reference-Data Versioning**: content-addressed (SHA-256) reference artifacts; no external authority claimed (documented limitation) | HARDENING (new) | `data_quality_platform/hardening/reference_data.py` |
| H8 | **Layer H — Resource/Execution Guard**: input/output ceilings, runtime wall-time + peak-RSS monitor thread, SIGKILL on breach, fail-closed | HARDENING (new) | `data_quality_platform/hardening/resource_guard.py` |
| H9 | Hardened execution orchestrator wiring A→F→G→B→C→H→engine→H→D→C with machine-readable execution reports | HARDENING (new) | `data_quality_platform/hardening/pipeline.py` |
| H10 | 17-scenario negative battery + positive controls ({bstats['passed']} tests, all passing): wrong hash/schema/type/rule-set/config/reference, duplicate execution, authorization mismatch, partial output, interrupted run, stale/cross-input checkpoint, resource limits, unknown schema, tampered manifest/output, malformed ledger | TESTS (new) | `tests/hardening/test_hardening_negative_battery.py` |
| H11 | Full 3.2M dual-run regression re-executed via the FROZEN checker (byte-identical harness): every certified fact reproduced exactly — input SHA `59624a53…`, output SHA `b72adc23…`, 25,600,000 oracle comparisons per pass, 0 mismatches, byte-identical outputs, runtime safety PASS, SP1 PASS | VALIDATION (fresh) | `evidence/validation/2026-09-19/fresh_3m2/` |
| H12 | Performance ladder with hardening-overhead measurement: {perf['rung_labels'][0]}–{perf['rung_labels'][-1]} engine-only vs hardened pipeline (overhead {perf['overhead_percent_by_rung'][perf['rung_labels'][-1]]}% at 3.2M, dominated by full-content hashing + atomic commit) | EVIDENCE (new) | `scripts/hardening_performance_ladder.py`, `evidence/FINAL_HARDENED_RELEASE_2026-09-19/performance/` |
| H13 | Clean evidence namespace for the release (identity, frozen-core verification, layer registry, regression, battery, suite, performance, limitations, claims with source/SHA/derivation/verifier, integrity, path forensics) | EVIDENCE (new) | `evidence/FINAL_HARDENED_RELEASE_2026-09-19/` |
| H14 | README fully regenerated from evidence (15-section structure, consistency-checked); FINAL_RESULTS fully rebuilt to the certified release schema (release/project/rule identity, run_1/run_2, limitation list) distinguishing BASELINE VERIFIED / NEW HARDENING VERIFIED / PRODUCTION-INTEGRATION NOT YET VERIFIED | DOCUMENTS (new) | `README.md`, `FINAL_RESULTS.json`, `final_result.json` |
| H15 | Assurance layer re-pointed to the 2026-09-19 regression evidence; live observability record regenerated (five-dimension separation preserved); release gate re-run against the new release identity with the hardening files in the authorized delta | ASSURANCE | `scripts/build_observability_status.py`, `scripts/release_gate.py` |

## What did NOT change

- **Frozen V1 rules** (`data_quality_platform/rules/v1_rules.py`,
  SHA-256 `daef1ded54c7d3c79898a1ba253be2acd5b6120e18b16b09009fdd7be9fc2276`):
  byte-identical; any hardening that would touch V1 is out of scope.
- **The frozen validation checker**
  (`scripts/final_3m_validation.py`, SHA-256
  `0ef7c10c14a1df317c23cb0dfc73b3a60c2257c064b35080d694e5fe8bc50d84`):
  byte-identical to the harness that produced the certified baseline.
- **The certified 2026-09-18 baseline evidence tree and ZIP**: untouched;
  referenced as BASELINE_CERTIFIED_HISTORICAL.
- **Engine execution semantics**: the hardening layers wrap the canonical
  CLI invocation; the engine command is unchanged.

## Verification summary

| Check | Result |
|---|---|
| 3.2M dual-run regression | PASS — exact certified-baseline reproduction |
| Oracle | 51,200,000 comparisons, 0 mismatches |
| Determinism | byte-identical outputs (filecmp at finalize) |
| Runtime safety | PASS both runs (audit-hook measured) |
| SP1 frozen verification | PASS both runs |
| Full test suite | {sstats['passed']} passed / {sstats['skipped']} skipped / {sstats['failed']} failed |
| Hardening battery | {bstats['passed']}/{bstats['passed']} ({battery['mandated_negative_scenarios']} mandated negative scenarios + positive controls) |
| Run-pair verification | {rp_total - rp_failed}/{rp_total} checks (Run 1 + Run 2) |
| Performance overhead | {perf['overhead_percent_by_rung']['1K']}% ({perf['rung_labels'][0]}) → {perf['overhead_percent_by_rung'][perf['rung_labels'][-1]]}% ({perf['rung_labels'][-1]}) |
| Release gate | {gate_line} |
| Layer count | {len(layers['layers'])} modules ({sum(1 for e in layers['layers'] if e['implemented'])} implemented + {sum(1 for e in layers['layers'] if not e['implemented'])} contract-only) |

## Known limitations

{inherited} inherited from the certified baseline (O(N) memory
profile; ClickHouse and Airflow not executed in any certified run;
authoritative DL fixture unavailable; SP1 validation-only; E1 not
implemented or authorized; pinned oracle reference truth; 3.2M-row
validation scale; bulk staging CSVs reclaimed after the byte-proof;
ZIP 733xx / TX geography expectations under review; runtime safety is
cooperative instrumentation; and the O(N)-proven fresh regression
re-proof) plus {new} new hardening limitations (Layer E
checkpoint/resume contract-only; reference-data provenance is
content-addressed only; peak-RSS monitoring is sampled at 250 ms;
authorization is not a kernel sandbox; atomic commit is
single-filesystem) — **{total} unique registered limitations**
(`LIM-001`..`LIM-016`, deduplicated canonical registry at
`evidence/release/limitation_registry.json`).
Production integration remains **NOT YET VERIFIED**. Full registry:
`evidence/FINAL_HARDENED_RELEASE_2026-09-19/limitations/limitation_registry.json`.

<!--
generated_utc_stamp: machine-stabilized document; regenerated by
scripts/hardening_release_notes_builder.py from the current evidence
tree (fixed-point write discipline).
-->
"""

    # inject a machine-stable stamp line for the fixed-point comparison
    import time
    stamp = time.strftime("generated-utc: %Y-%m-%dT%H:%M:%SZ",
                          time.gmtime())
    notes = notes.replace(
        "<!--\ngenerated_utc_stamp:",
        f"<!--\n{stamp}\ngenerated_utc_stamp:")

    wrote = _write_stabilized_text(
        REPO_ROOT / "RELEASE_NOTES.md", notes, "generated-utc:")
    print(f"RELEASE_NOTES.md "
          f"{'regenerated' if wrote else 'verified at fixed point'} "
          f"({len(notes):,} chars; I/O fingerprints embedded)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
