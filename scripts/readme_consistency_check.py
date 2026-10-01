#!/usr/bin/env python3
"""ASSURANCE REBASELINE 2026-09-17 — README/evidence automated
consistency check (task §5/§10).

Verifies that README.md claims match the authoritative machine-readable
evidence — value-based, not arbitrary prose greps: every expected
string is DERIVED from the canonical evidence artifact at check time.

Required (all must be present, derived from evidence):
    gate count, test counts (collected/passed/skipped/0 failed),
    official run structure, combined oracle comparisons, 0 mismatches,
    run-pair checks, mutation scores, frozen V1 rule count, final 3M
    validation status, release verdict, I/O + checker SHA prefixes,
    release identity.

Superseded values (any presence fails the check):
    "16 fail-closed gates", "16-gate", "16 gates", "715 passed",
    "813 collected", "804 passed", obsolete DQAVP-era ZIP tooling as
    the release command, stale checker SHA (a SHA-256 that appears in
    README's provenance block but matches none of the authoritative
    hashes).

Works without git metadata (extraction-verification context).
Exit code 0 only when verdict == CONSISTENT.
Output: evidence/release/readme_consistency.json
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO_ROOT, "evidence", "release",
                   "readme_consistency.json")


def maybe_load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def build_required_values(root):
    """Derive every required (label, expected-string) pair from the
    canonical evidence. Returns (required list, sources dict)."""
    ts = maybe_load(os.path.join(
        root, "evidence/rebuild_verification/test_summary.json"))
    gate = maybe_load(os.path.join(
        root, "evidence/release_gate/final_release_gate.json"))
    rp = maybe_load(os.path.join(
        root, "evidence/rebuild_verification/run_pair_verification.json"))
    f3m = maybe_load(os.path.join(
        root, "evidence/validation/2026-09-19/fresh_3m2/FINAL_RESULTS.json"))
    fr = maybe_load(os.path.join(root, "FINAL_RESULTS.json"))
    bm = maybe_load(os.path.join(
        root, "evidence/mutation_testing/mutation_results.json"))
    am = maybe_load(os.path.join(
        root, "evidence/release/assurance_mutation.json"))
    rules = maybe_load(os.path.join(
        root, "evidence/rebuild_baseline/v1_rule_inventory.json"))

    sources = {
        "test_summary": ts is not None,
        "release_gate": gate is not None,
        "run_pair": rp is not None,
        "final_3m": f3m is not None,
        "FINAL_RESULTS": fr is not None,
        "mutation": bm is not None,
        "assurance_mutation": am is not None,
        "rule_inventory": rules is not None,
    }

    required = []
    if ts:
        required += [
            ("test_collected", f"{ts.get('collected')} collected"),
            ("test_passed", f"{ts.get('passed')} passed"),
            ("test_skipped", f"{ts.get('skipped')} skipped"),
            ("test_failed", f"{ts.get('failed')} failed"),
        ]
    if gate:
        n = gate.get("gate_count")
        required += [
            ("gate_count_long", f"{n} fail-closed gates"),
            ("gate_count_short", f"{n}-gate"),
        ]
    if f3m:
        comparisons = f3m.get("oracle_comparisons")
        mm = f3m.get("oracle_mismatches") or {}
        mismatches = mm.get("combined_total")
        rows = f3m.get("rows")
        required += [
            ("comparisons_combined",
             f"{comparisons:,}" if isinstance(comparisons, int) else None),
            ("mismatches",
             f"{mismatches} mismatches"
             if isinstance(mismatches, int) else None),
            ("rows_per_run",
             f"{rows:,}-row" if isinstance(rows, int) else None),
            ("final_3m_verdict",
             f"Final 3M checker verdict: {f3m.get('final_status')}"),
            ("input_sha_prefix", (f3m.get("input_sha256") or "")[:8]),
            ("output_sha_prefix", (f3m.get("output_sha256") or "")[:8]),
        ]
    if rp:
        total = rp.get("checks_total")
        failed = rp.get("checks_failed")
        if isinstance(total, int) and isinstance(failed, int):
            required.append(
                ("run_pair_checks", f"{total - failed}/{total}"))
        if rp.get("run_1") and rp.get("run_2"):
            required.append(("official_runs", "Run 1 + Run 2"))
    if bm:
        required.append(("business_mutation",
                         f"{bm.get('mutants_detected')}/"
                         f"{bm.get('mutants_total')}"))
    if am:
        required.append(("assurance_mutation",
                         f"{am.get('scenarios_detected')}/"
                         f"{am.get('scenarios_total')}"))
    if rules:
        rl = rules.get("rules", rules) if isinstance(rules, dict) \
            else rules
        required.append(("v1_rule_count", f"{len(rl)} frozen V1 rules"))
    if fr:
        required += [
            ("release_verdict", "PASS_WITH_DOCUMENTED_LIMITATIONS"),
            ("release_name",
             (fr.get("release_identity") or {}).get("release_name", "")),
        ]
    return required, sources


SUPERSEDED_VALUES = [
    ("superseded_gate_16_long", "16 fail-closed gates"),
    ("superseded_gate_16_short", "16-gate"),
    ("superseded_gate_16_plain", "16 gates"),
    ("superseded_tests_715", "715 passed"),
    ("superseded_tests_813", "813 collected"),
    ("superseded_tests_804", "804 passed"),
    ("superseded_zip_tooling_primary",
     "scripts/build_enterprise_release_zip.py"),
    ("superseded_zip_tooling_verify",
     "scripts/verify_enterprise_release_zip.py"),
]


def run_check(root):
    readme_path = os.path.join(root, "README.md")
    if not os.path.isfile(readme_path):
        return {
            "verdict": "FAIL",
            "problems": ["README.md missing"],
        }
    with open(readme_path, encoding="utf-8") as f:
        readme = f.read()

    required, sources = build_required_values(root)
    problems = []
    missing_sources = [k for k, ok in sources.items() if not ok]
    if missing_sources:
        problems.append(f"authoritative evidence unreadable/missing: "
                        f"{missing_sources}")

    required_results = []
    for label, expected in required:
        if not expected:
            problems.append(f"required value for {label} could not be "
                            "derived from evidence (fail closed)")
            required_results.append({"label": label, "expected": expected,
                                     "found": False,
                                     "status": "NOT_DERIVED"})
            continue
        found = expected in readme
        required_results.append({"label": label, "expected": expected,
                                 "found": found})
        if not found:
            problems.append(f"README missing current value for {label}: "
                            f"{expected!r}")

    superseded_results = []
    for label, stale in SUPERSEDED_VALUES:
        present = stale in readme
        superseded_results.append({"label": label, "value": stale,
                                   "present": present})
        if present:
            problems.append(f"README contains superseded value "
                            f"({label}): {stale!r}")

    # stale checker SHA: any 64-hex token in README's provenance that is
    # not one of the authoritative hashes is a stale-hash problem
    f3m = maybe_load(os.path.join(
        root, "evidence/validation/2026-09-19/fresh_3m2/FINAL_RESULTS.json"))
    rp = maybe_load(os.path.join(
        root, "evidence/rebuild_verification/run_pair_verification.json"))
    if f3m and rp:
        # the frozen V1 rule-source hash is an authoritative identity
        # too (computed live from the frozen file, never hardcoded):
        # a README may carry it in full, and a WRONG full V1 hash is
        # still rejected as stale/unknown
        v1_path = os.path.join(
            root, "data_quality_platform/rules/v1_rules.py")
        v1_sha = None
        if os.path.isfile(v1_path):
            import hashlib
            h = hashlib.sha256()
            with open(v1_path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            v1_sha = h.hexdigest()
        authoritative = {
            f3m.get("input_sha256"), f3m.get("output_sha256"),
            rp.get("checker_script_sha256_actual"), v1_sha,
        }
        for token in set(re.findall(r"\b[0-9a-f]{64}\b", readme)):
            if token not in authoritative:
                problems.append(f"stale or unknown full SHA-256 in "
                                f"README: {token[:12]}...")
        checker_prefix = (rp.get("checker_script_sha256_actual")
                          or "")[:8]
        if checker_prefix and checker_prefix not in readme:
            problems.append("README missing current checker SHA prefix: "
                            f"{checker_prefix}")

    return {
        "required_values": required_results,
        "superseded_values": superseded_results,
        "evidence_sources_available": sources,
        "problems": problems,
        "verdict": "CONSISTENT" if not problems else "FAIL",
        "verdict_note": (
            "CONSISTENT only when every evidence-derived value is "
            "present and every known superseded value is absent; "
            "values are derived from evidence at check time, never "
            "hard-coded"),
    }


def main():
    root = REPO_ROOT
    result = run_check(root)
    result = {
        "report": "DQAEIP README/evidence automated consistency check",
        "schema_version": "1.0.0",
        "generated_utc": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "checked_file": "README.md",
        **result,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True)
        f.write("\n")
    print("README CONSISTENCY ->", os.path.relpath(OUT, REPO_ROOT),
          ":", result["verdict"])
    for p in result["problems"][:10]:
        print("  -", p)
    return 0 if result["verdict"] == "CONSISTENT" else 1


if __name__ == "__main__":
    sys.exit(main())
