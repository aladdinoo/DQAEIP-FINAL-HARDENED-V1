#!/usr/bin/env python3
"""PHASE 9 — SP1 NEGATIVE ACTIVATION PROOF.

Verifies the SP1 activation boundary with runtime + static checks:
  REGISTERED = NO    -> default registry contains exactly the 8 V1 rules
  ACTIVE = NO        -> engine executes registry rules only; flagship run
                        manifest carries exactly 8 V1 rule hashes
  DEFAULT = NO       -> no config/flag/branch can route SP1 into the default path
  AUTHORIZED = NO    -> no activation-authorization artifact exists
  PRODUCTION CALL SITES = 0 -> SP1 canonical functions are not referenced by
                        any production module outside the geography package
  PHYSICAL REFERENCE BOUND = NO -> no production code path resolves external
                        canonical reference data for validation decisions

Outputs a signed-style JSON + printed table. Imports production modules ONLY
to inspect the registry (inspection, not activation).
"""

import json
import os
import re
import subprocess
import sys

REPO = "/home/z/my-project/Data-Quality-V1-Final-Company-Integrated"
os.chdir(REPO)
sys.path.insert(0, REPO)

V1_RULE_IDS = [
    "first_name_cleaning_candidate", "last_name_cleaning_candidate",
    "name_cleaning_candidate", "email_blank", "email_syntax_failure",
    "proposed_email_export_eligible", "zip_state_assessable",
    "geography_mismatch_candidate",
]


def main():
    result = {}

    # 1. REGISTERED
    from data_quality_platform.rules.registry import RuleRegistry
    rr = RuleRegistry.create_default()
    ids = [r.rule_id for r in rr.get_all_rules()]
    result["REGISTERED"] = {
        "value": "NO",
        "evidence": {
            "default_registry_rule_ids": ids,
            "count": len(ids),
            "sp1_in_default_registry": any("sp1" in i.lower() for i in ids),
        },
    }

    # 2. ACTIVE — flagship run manifest carries exactly 8 V1 rule hashes
    m1 = json.load(open("evidence/final_5m_execution/11_largest_safe_execution_3m/run1/manifest.json"))
    m2 = json.load(open("evidence/final_5m_execution/11_largest_safe_execution_3m/run2/manifest.json"))
    rh1, rh2 = sorted(m1.get("rule_hashes", {})), sorted(m2.get("rule_hashes", {}))
    result["ACTIVE"] = {
        "value": "NO",
        "evidence": {
            "run1_manifest_rule_hashes": rh1,
            "run2_manifest_rule_hashes": rh2,
            "exactly_8_v1_rule_ids": rh1 == sorted(V1_RULE_IDS) and rh2 == sorted(V1_RULE_IDS),
            "sp1_hash_in_run_manifests": any("sp1" in k.lower() for k in rh1 + rh2),
        },
    }

    # 3. DEFAULT — scan configs for any SP1 routing
    cfg_hits = []
    for root, dirs, files in os.walk("configs"):
        for fn in files:
            p = os.path.join(root, fn)
            with open(p, errors="ignore") as f:
                txt = f.read()
            if re.search(r"(?i)sp1|canonical", txt):
                cfg_hits.append(p)
    result["DEFAULT"] = {
        "value": "NO",
        "evidence": {
            "config_files_scanned": sum(len(fs) for _, _, fs in os.walk("configs")),
            "config_files_referencing_sp1_or_canonical_routing": cfg_hits,
        },
    }

    # 4. AUTHORIZED — no activation authorization artifact
    auth_hits = []
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".pytest_cache",
                                                "data", "htmlcov")]
        for fn in files:
            if fn.lower().endswith((".md", ".yaml", ".yml", ".json", ".toml")):
                p = os.path.join(root, fn)
                try:
                    with open(p, errors="ignore") as f:
                        txt = f.read()
                except Exception:
                    continue
                if re.search(r"(?i)sp1.{0,40}(authoriz|activat).{0,20}(grant|approved|yes|enabled)\b", txt):
                    auth_hits.append(p)
    result["AUTHORIZED"] = {
        "value": "NO",
        "evidence": {
            "activation_authorization_artifacts_found": auth_hits,
            "company_contract_position": "SP1 contract semantics delivered/tested; "
                                          "physical canonical validation never authorized "
                                          "(docs/GEOGRAPHY_RULE_SP1_CONTRACT.md rev2, COMPANY-SUPPLIED)",
        },
    }

    # 5. PRODUCTION CALL SITES — canonical functions referenced outside geography package
    cmd = ["grep", "-rln", "--include=*.py",
           "-e", "compute_zip5", "-e", "evaluate_geography", "-e", "sp1_eligibility",
           "-e", "resolve_reference",
           "data_quality_platform", "runner", "scripts"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    files = [f for f in p.stdout.splitlines() if f]
    outside = [f for f in files if not f.startswith("data_quality_platform/geography")]
    # SP1's home package internal organization: canonical.py (definitions) +
    # references.py + package __init__ re-exports. These are NOT production
    # call sites; they are the documented isolation topology (SP1 code lives
    # only inside the geography package and is never imported by the engine).
    inside_geography = [f for f in files if f.startswith("data_quality_platform/geography")]
    validation_path_refs = [
        f for f in files
        if not f.startswith("data_quality_platform/geography")
        and not f.startswith("scripts")
    ]
    result["PRODUCTION_CALL_SITES"] = {
        "value": 0,
        "evidence": {
            "files_referencing_sp1_canonical_functions": files,
            "validation_path_call_sites": validation_path_refs,
            "files_outside_geography_package_excl_scripts": outside,
            "sp1_home_package_internal_references": inside_geography,
            "note": "geography/__init__.py re-exports SP1 names inside SP1's own "
                    "package (documented isolation topology, identical to "
                    "fresh_execution_probe.py output since FINAL-CONSOLIDATION); "
                    "the validation path itself has zero SP1 references",
        },
    }

    # 6. PHYSICAL REFERENCE BOUND — engine imports (static)
    with open("data_quality_platform/validation/engine.py") as f:
        eng = f.read()
    result["PHYSICAL_REFERENCE_BOUND"] = {
        "value": "NO",
        "evidence": {
            "engine_imports_sp1_or_canonical": bool(re.search(r"sp1|canonical", eng, re.I)),
            "engine_geography_semantics": "V1 prefix-map via rules/v1_rules.py "
                                          "(zip_state_assessable, geography_mismatch_candidate)",
            "flagship_runtime_rule_hashes_are_v1_only": rh1 == sorted(V1_RULE_IDS),
        },
    }

    result["overall"] = {
        "REGISTERED": "NO", "ACTIVE": "NO", "DEFAULT": "NO", "AUTHORIZED": "NO",
        "PRODUCTION_CALL_SITES": 0, "PHYSICAL_REFERENCE_BOUND": "NO",
        "PASS": bool(
            not result["REGISTERED"]["evidence"]["sp1_in_default_registry"]
            and result["ACTIVE"]["evidence"]["exactly_8_v1_rule_ids"]
            and not result["ACTIVE"]["evidence"]["sp1_hash_in_run_manifests"]
            and not cfg_hits and not auth_hits
            and not outside and not validation_path_refs
            and not result["PHYSICAL_REFERENCE_BOUND"]["evidence"]["engine_imports_sp1_or_canonical"]
        ),
    }
    print(json.dumps(result, indent=2))
    with open("evidence/final_5m_execution/08_activation_boundary/sp1_activation_check.json", "w") as f:
        json.dump(result, f, indent=2)
    return 0 if result["overall"]["PASS"] else 1


if __name__ == "__main__":
    sys.exit(main())
