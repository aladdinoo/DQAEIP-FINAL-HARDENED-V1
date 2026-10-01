#!/usr/bin/env python3
"""Rule Impact Analysis runner (DQAVP hardening, Section 7).

Executes controlled CURRENT-vs-PROPOSED rule comparisons on a real
dataset and records the decision diff as evidence. PROPOSED RULES ARE
NEVER ACTIVATED: this script registers nothing and changes no
production behavior; it only measures what WOULD change.

Built-in proposal scenarios (illustrative, clearly labeled):
  email_stricter           — reject emails containing consecutive dots
                             (e.g., "a@b..co") that the current regex
                             accepts
  geography_case_sensitive — treat state comparison as case-sensitive
                             (a defective proposal: proves the analyzer
                             detects real decision changes)
  email_blank_no_strip     — count whitespace-only emails as non-blank

Usage:
  python scripts/rule_impact_analysis.py --csv tests/golden/golden_cases.csv
  python scripts/rule_impact_analysis.py --csv <dataset.csv> \
      --out evidence/impact_analysis/impact_results.json
"""

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_quality_platform.rules.registry import RuleRegistry
from data_quality_platform.validation.impact_analysis import (
    RuleImpactAnalyzer, load_rows_csv,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _prop_email_stricter(row):
    email = str(row.get("email_address", "")).strip()
    if not email:
        return 0
    ok = re.fullmatch(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
                      email) is not None
    has_double_dot = ".." in email
    return 0 if (ok and not has_double_dot) else 1


def _prop_geography_case_sensitive(row):
    zip_val = str(row.get("zip", "")).strip()
    state = str(row.get("state", "")).strip()
    if not zip_val or not state:
        return 0
    from data_quality_platform.contracts import STATE_ZIP_PREFIXES
    if state not in STATE_ZIP_PREFIXES:  # case-sensitive (defect proposal)
        return 0
    for prefix in STATE_ZIP_PREFIXES[state]:
        if zip_val.startswith(prefix):
            return 0
    return 1


def _prop_email_blank_no_strip(row):
    email = row.get("email_address")
    if email is None or str(email) == "":
        return 1
    return 0


SCENARIOS = {
    "email_stricter": ("email_syntax_failure",
                       "stricter email syntax: consecutive dots rejected",
                       _prop_email_stricter),
    "geography_case_sensitive": (
        "geography_mismatch_candidate",
        "defective proposal: case-sensitive state comparison",
        _prop_geography_case_sensitive),
    "email_blank_no_strip": (
        "email_blank",
        "defective proposal: whitespace-only emails not blank",
        _prop_email_blank_no_strip),
}


def build_demo_battery(out_path):
    """Build a demonstration dataset for the impact analyzer: the 3M
    checker's edge rows plus explicit rows that discriminate the built-in
    proposal scenarios. This is a DEMONSTRATION dataset (clearly labeled),
    not a validation oracle."""
    import csv
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "f3m_impact", os.path.join(REPO_ROOT, "scripts",
                                   "final_3m_validation.py"))
    f3m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(f3m)
    rows = [dict(r) for r in f3m._edge_rows()]
    base = dict(rows[0])
    demo_rows = [
        # lowercase state whose uppercase form would MISMATCH under V1
        {"state": "tx", "zip": "10001"},
        # lowercase state that MATCHES under V1 uppercase normalization
        {"state": "ca", "zip": "90210"},
        # consecutive-dot email (accepted by current regex)
        {"email_address": "bad..dots@example.com"},
        # whitespace-only email (blank under V1 strip semantics)
        {"email_address": "   "},
    ]
    for extra in demo_rows:
        row = dict(base)
        row.update({k: v for k, v in extra.items() if k in row})
        rows.append(row)
    for i, row in enumerate(rows, start=1):
        row["id"] = str(i)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return out_path, len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=None,
                    help="dataset to analyze (current vs proposed); "
                         "omit with --demo to use the demonstration battery")
    ap.add_argument("--demo", action="store_true",
                    help="build and analyze the demonstration battery "
                         "(3M checker edge rows + discriminating rows)")
    ap.add_argument("--scenario", default="all",
                    choices=["all"] + sorted(SCENARIOS))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.demo:
        demo_path = os.path.join(REPO_ROOT, "evidence", "impact_analysis",
                                 "demo_battery.csv")
        os.makedirs(os.path.dirname(demo_path), exist_ok=True)
        _, n = build_demo_battery(demo_path)
        print(f"demo battery: {n} rows -> {demo_path}")
        csv_path = demo_path
    elif args.csv:
        csv_path = args.csv
    else:
        ap.error("provide --csv or --demo")
        return 2

    rows = load_rows_csv(csv_path)
    registry = RuleRegistry.create_default()
    analyzer = RuleImpactAnalyzer(registry, rows)
    names = sorted(SCENARIOS) if args.scenario == "all" else [args.scenario]

    report = {
        "tool": "scripts/rule_impact_analysis.py",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dataset": os.path.relpath(csv_path, REPO_ROOT)
        if csv_path.startswith(REPO_ROOT) else csv_path,
        "dataset_is_demonstration_battery": bool(args.demo),
        "dataset_rows": len(rows),
        "proposal_activated": False,
        "scenarios": {},
    }
    for name in names:
        rule_id, desc, prop = SCENARIOS[name]
        diff = analyzer.compare_rule(rule_id, prop)
        report["scenarios"][name] = {
            "rule_id": rule_id,
            "proposal_description": desc,
            **diff.to_dict(),
        }
        d = report["scenarios"][name]
        print(f"[{name}] {rule_id}: rows={d['rows_evaluated']} "
              f"changed={d['changed_decisions']} "
              f"(+{d['additions']}/-{d['removals']}) "
              f"old={d['old_flag_count']} new={d['new_flag_count']}")

    out = args.out or os.path.join(REPO_ROOT, "evidence", "impact_analysis",
                                   "impact_results.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"evidence written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
