#!/usr/bin/env python3
"""DQAEIP ZERO-ASSUMPTION REBUILD — Phase 4E rule impact graph.

Builds a machine-readable, per-rule impact graph for the Frozen V1
rule set, mapping each rule to:

    implementation    (canonical source class + rule hash + version)
    schema deps       (input columns the predicate actually reads)
    tests             (test modules referencing the rule id)
    golden cases      (golden fixtures referencing the rule id)
    oracle            (reference-oracle wiring for the rule)
    evidence          (official 3M flag counts + mismatch records)
    release claims    (claim-provenance claims anchored to the rule
                       source / registry)

This is METADATA ONLY — it never alters rule behavior. If a rule
changes, this graph identifies the evidence that must be regenerated
("affected evidence"), which is exactly what a reviewer needs.

Derivation is static analysis of actual files:
    - schema deps come from parsing the predicate source in
      v1_rules.py (row.get / row[...] accesses) — the actual code,
      not documentation;
    - test references come from scanning the test tree for the rule
      id;
    - evidence references come from the official 3M manifests;
    - claim references come from claim_provenance.json.

Output: evidence/release/rule_impact_graph.json
"""

import hashlib
import json
import os
import re
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PATH = os.path.join(
    REPO_ROOT, "evidence", "release", "rule_impact_graph.json")

V1_SOURCE = "data_quality_platform/rules/v1_rules.py"
RUN_MANIFESTS = [
    "evidence/validation/2026-09-18/fresh_3m2/harness/pass1_engine/manifest.json",
    "evidence/validation/2026-09-18/fresh_3m2/harness/pass2_engine/manifest.json",
]
FINAL_3M = ("evidence/validation/2026-09-18/fresh_3m2/harness/"
            "FINAL_RESULTS.json")
CLAIMS = "evidence/release/claim_provenance.json"

REQUIRED_V1_RULE_IDS = [
    "first_name_cleaning_candidate",
    "last_name_cleaning_candidate",
    "name_cleaning_candidate",
    "email_blank",
    "email_syntax_failure",
    "proposed_email_export_eligible",
    "zip_state_assessable",
    "geography_mismatch_candidate",
]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(rel):
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def parse_rule_classes(source_text):
    """Split v1_rules.py source into {class_name: class_body} blocks
    plus each class's registered rule id."""
    blocks = {}
    current = None
    for line in source_text.splitlines():
        m = re.match(r"^class\s+(\w+)", line)
        if m:
            current = m.group(1)
            blocks[current] = [line]
        elif current is not None:
            blocks[current].append(line)
    return blocks


def class_rule_id(body_lines):
    """Rule id from a class body — the id is the returned string of
    the rule_id property, which may sit on the line after the
    property declaration."""
    for i, ln in enumerate(body_lines):
        if "def rule_id" in ln:
            window = " ".join(body_lines[i:i + 3])
            m = re.search(r'return\s+"([a-z0-9_]+)"', window)
            if m:
                return m.group(1)
    return None


def schema_deps(body_lines):
    """Input columns read by the predicate (from actual code)."""
    deps = set()
    for ln in body_lines:
        for m in re.finditer(r'row\.get\(\s*"([^"]+)"', ln):
            deps.add(m.group(1))
        for m in re.finditer(r'row\[\s*"([^"]+)"\s*\]', ln):
            deps.add(m.group(1))
    return sorted(deps)


def scan_test_references(rule_id):
    """Test modules that reference the rule id (or its SQL name)."""
    refs = []
    tests_root = os.path.join(REPO_ROOT, "tests")
    for dirpath, _dirnames, filenames in os.walk(tests_root):
        for fn in sorted(filenames):
            if not (fn.startswith("test_") and fn.endswith(".py")):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn),
                                  REPO_ROOT).replace(os.sep, "/")
            try:
                with open(os.path.join(dirpath, fn), encoding="utf-8") as f:
                    text = f.read()
            except OSError:
                continue
            if rule_id in text:
                refs.append(rel)
    return refs


def scan_golden_references(rule_id):
    """Golden fixtures that reference the rule id."""
    refs = []
    golden_root = os.path.join(REPO_ROOT, "tests", "golden")
    for dirpath, _dirnames, filenames in os.walk(golden_root):
        for fn in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, fn),
                                  REPO_ROOT).replace(os.sep, "/")
            try:
                with open(os.path.join(dirpath, fn), encoding="utf-8",
                          errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            if rule_id in text:
                refs.append(rel)
    return refs


def main():
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    sys.path.insert(0, REPO_ROOT)
    from data_quality_platform.rules.registry import RuleRegistry
    registry = RuleRegistry.create_default()
    rules_by_id = {r.rule_id: r for r in registry.get_all_rules()}

    with open(os.path.join(REPO_ROOT, V1_SOURCE), encoding="utf-8") as f:
        v1_text = f.read()
    blocks = parse_rule_classes(v1_text)

    manifests = [load(rel) for rel in RUN_MANIFESTS]
    f3m = load(FINAL_3M)
    claims_doc = load(CLAIMS)
    claims = claims_doc.get("claims", [])

    # Oracle wiring: the independent oracle module used by the 3M
    # differential (all V1 rules; stated once at graph level).
    graph_rules = {}
    problems = []

    for class_name, body in blocks.items():
        rid = class_rule_id(body)
        if rid is None:
            continue
        rule = rules_by_id.get(rid)
        if rule is None:
            problems.append(f"class {class_name} registers unknown rule "
                            f"id {rid}")
            continue
        flag_counts = {}
        for i, m in enumerate(manifests, 1):
            flag_counts[f"run_{i}"] = m.get("flag_counts", {}).get(rid)
        mismatch_records = {}
        for i in (1, 2):
            run = f3m.get("runs", {}).get(f"run_{i}", {})
            mm = run.get("oracle", {}).get("mismatches_by_rule", {})
            mismatch_records[f"run_{i}"] = mm.get(rid)

        claim_refs = []
        for c in claims:
            src = c.get("source_artifact") or ""
            if "rules/v1_rules.py" in src or "v1_rule" in str(
                    c.get("derivation")) or "rules" in src:
                claim_refs.append(c.get("claim_id"))

        graph_rules[rid] = {
            "implementation": {
                "canonical_source": V1_SOURCE,
                "class_name": class_name,
                "rule_version": rule.rule_version,
                "rule_hash": rule.hash,
            },
            "schema_dependencies": schema_deps(body),
            "tests": scan_test_references(rid),
            "golden_cases": scan_golden_references(rid),
            "oracle": {
                "reference": "data_quality_platform/verification/"
                             "reference_provenance.py (independent oracle "
                             "path; 24,000,000 comparisons per official "
                             "run, per-rule mismatch records below)",
            },
            "evidence": {
                "official_3m_flag_counts": flag_counts,
                "official_3m_oracle_mismatches": mismatch_records,
                "run_manifests": RUN_MANIFESTS,
            },
            "release_claims": claim_refs,
            "affected_evidence_if_changed": [
                "evidence/validation/2026-09-18/fresh_3m2/harness/ "
                "(official evidence becomes INVALID — rules must not "
                "change; any change is an unauthorized rule change)",
                "evidence/rebuild_verification/run_pair_verification.json",
                "evidence/release/rule_impact_graph.json",
                "evidence/release/claim_provenance.json",
                "evidence/release/release_evidence_model.json",
                "evidence/release/consistency_matrix.json",
                "README.md (rule-derived sections)",
            ],
        }

    missing = [rid for rid in REQUIRED_V1_RULE_IDS if rid not in graph_rules]
    extra = [rid for rid in graph_rules if rid not in REQUIRED_V1_RULE_IDS]
    if missing:
        problems.append(f"rules missing from graph: {missing}")
    if extra:
        problems.append(f"unexpected rules in graph: {extra}")

    graph = {
        "report": "DQAEIP Frozen V1 rule impact graph (metadata only)",
        "generated_utc": started,
        "policy": (
            "assurance metadata only; rule behavior is never altered by "
            "this graph; if a rule changes, the affected_evidence lists "
            "identify what must be regenerated — V1 changes are "
            "unauthorized by definition"),
        "rule_set": {
            "canonical_source": V1_SOURCE,
            "canonical_source_sha256": sha256_file(
                os.path.join(REPO_ROOT, V1_SOURCE)),
            "rule_count": len(graph_rules),
            "registry_exactly_v1": (
                sorted(graph_rules) == sorted(REQUIRED_V1_RULE_IDS)),
        },
        "rules": graph_rules,
        "problems": problems,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"RULE IMPACT GRAPH written to evidence/release/rule_impact_graph.json")
    print(f"  rules: {len(graph_rules)} (exactly V1: "
          f"{graph['rule_set']['registry_exactly_v1']})")
    for rid in REQUIRED_V1_RULE_IDS:
        g = graph_rules[rid]
        print(f"  - {rid}: deps={g['schema_dependencies']} "
              f"tests={len(g['tests'])} golden={len(g['golden_cases'])}")
    if problems:
        print(f"  PROBLEMS: {problems}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
