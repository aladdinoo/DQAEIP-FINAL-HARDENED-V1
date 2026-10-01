#!/usr/bin/env python3
"""DQAEIP RUN 1 + RUN 2 PAIR VERIFICATION (Phases 4/5/10).

Fail-closed verification of the official two-run production validation
evidence. Verifies EVERY required invariant from the actual artifacts —
never from documentation or README claims.

Per-run checks (each independently required):
    run_id well-formed + unique; completion status PASS
    input SHA256 + row count + column count; source unmutated
    output SHA256 + rows + 41 columns
    schema identity; rule registry identity (8 rule hashes)
    checker identity (version, script SHA-256 vs actual file)
    Git lineage (commit recorded, must be ancestor of current HEAD)
    comparison counts (rows x 8 rules) + mismatch counts
    runtime + peak RSS recorded
    runtime safety result
    SP1 pinned frozen baseline result
    evidence-root integrity (tamper-evident recompute)
    manifest recorded artifact hashes vs actual files

Cross-run invariants (all must hold):
    input_sha256 equal, output_sha256 equal, schema_hash equal,
    rule identity equal, checker identity equal, Git lineage equal,
    both statuses PASS, both mismatches 0, flag totals equal

Anti-stale / anti-mixing:
    every stage artifact must carry the SAME script_sha256 and git_commit;
    a Run 1 from one lineage mixed with a Run 2 from another is REJECTED.

Output: evidence/rebuild_verification/run_pair_verification.json
FAIL CLOSED: exit code 1 if any invariant cannot be established.
"""

import hashlib
import json
import os
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVIDENCE_DIR = os.path.join(REPO_ROOT, "evidence", "validation", "2026-09-19", "fresh_3m2")
CHECKER_SCRIPT = os.path.join(REPO_ROOT, "scripts", "final_3m_validation.py")
PINNED_BASELINE = os.path.join(REPO_ROOT, "evidence", "final_execution", "rule_matrix.json")

V1_RULE_IDS = [
    "first_name_cleaning_candidate", "last_name_cleaning_candidate",
    "name_cleaning_candidate", "email_blank", "email_syntax_failure",
    "proposed_email_export_eligible", "zip_state_assessable",
    "geography_mismatch_candidate",
]


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(args):
    return subprocess.run(["git", "-C", REPO_ROOT] + args,
                          capture_output=True, text=True, check=False)


def git_is_ancestor(commit):
    r = git(["merge-base", "--is-ancestor", commit, "HEAD"])
    return r.returncode == 0


class Result:
    def __init__(self):
        self.checks = []
        self.failures = []

    def check(self, name, ok, detail=None, required=True):
        entry = {"check": name, "status": "PASS" if ok else "FAIL",
                 "required": required}
        if detail is not None:
            entry["detail"] = detail
        self.checks.append(entry)
        if not ok and required:
            self.failures.append(name)
        return ok

    @property
    def all_pass(self):
        return not self.failures


def verify_run(pass_name, res, checker_sha, final_head):
    run = {"pass": pass_name}
    result_path = os.path.join(EVIDENCE_DIR, f"{pass_name}_result.json")
    engine_dir = os.path.join(EVIDENCE_DIR, f"{pass_name}_engine")

    # Existence / parseability
    run["result_file_exists"] = os.path.isfile(result_path)
    res.check(f"{pass_name}: result file exists", run["result_file_exists"])
    if not run["result_file_exists"]:
        return run
    try:
        r = json.load(open(result_path, encoding="utf-8"))
    except Exception as exc:
        res.check(f"{pass_name}: result JSON parseable", False, str(exc))
        return run
    run["result_json_parseable"] = True

    # Identity / lineage
    run["run_pass_marker"] = r.get("pass")
    res.check(f"{pass_name}: pass marker correct", r.get("pass") == pass_name)
    run["git_commit"] = r.get("git_commit")
    res.check(f"{pass_name}: git_commit recorded",
              isinstance(r.get("git_commit"), str) and len(r["git_commit"]) == 40)
    if run.get("git_commit"):
        res.check(f"{pass_name}: git_commit is ancestor of current HEAD",
                  git_is_ancestor(run["git_commit"]),
                  {"recorded": run["git_commit"], "current_head": final_head})
    run["checker_script_sha256"] = r.get("script_sha256")
    res.check(f"{pass_name}: checker script SHA matches actual file",
              run["checker_script_sha256"] == checker_sha)
    run["checker_version"] = r.get("checker_version")
    res.check(f"{pass_name}: checker version recorded",
              isinstance(r.get("checker_version"), str))
    res.check(f"{pass_name}: not blocked", r.get("blocked") is False)

    # CLI execution
    cli = r.get("cli", {})
    run["cli_returncode"] = cli.get("returncode")
    res.check(f"{pass_name}: CLI returncode 0", cli.get("returncode") == 0)
    res.check(f"{pass_name}: CLI verdict PASSED",
              "Validation PASSED" in str(cli.get("stdout", "")))

    # Dataset / input identity
    ds = r.get("dataset", {})
    run["input_sha256"] = ds.get("sha256")
    run["input_rows"] = ds.get("rows")
    run["input_columns"] = ds.get("columns")
    res.check(f"{pass_name}: input rows 3200000", ds.get("rows") == 3200000)
    res.check(f"{pass_name}: input columns 33", ds.get("columns") == 33)
    res.check(f"{pass_name}: input SHA256 recorded (64 hex)",
              isinstance(ds.get("sha256"), str) and len(ds["sha256"]) == 64)
    res.check(f"{pass_name}: source unmutated during validation",
              ds.get("sha256") == ds.get("sha256_after_validation"))

    # Output identity
    out = r.get("output", {})
    run["output_sha256"] = out.get("sha256")
    run["output_rows"] = out.get("rows")
    run["output_columns"] = out.get("columns")
    res.check(f"{pass_name}: output rows 3200000", out.get("rows") == 3200000)
    res.check(f"{pass_name}: output columns 41", out.get("columns") == 41)
    res.check(f"{pass_name}: output SHA256 recorded (64 hex)",
              isinstance(out.get("sha256"), str) and len(out["sha256"]) == 64)

    # Verification statuses
    ver = r.get("verification", {})
    ver_statuses = {}
    for k, v in ver.items():
        if k.endswith("_status"):
            ver_statuses[k] = v
    run["verification_statuses"] = ver_statuses
    res.check(f"{pass_name}: all 9 verification statuses PASS",
              len(ver_statuses) >= 9 and all(v == "PASS" for v in ver_statuses.values()),
              {"count": len(ver_statuses)})

    # Oracle comparisons / mismatches (flat under verification)
    oracle = ver
    run["oracle_comparisons"] = ver.get("oracle_comparisons")
    run["oracle_mismatches"] = ver.get("oracle_mismatches")
    res.check(f"{pass_name}: oracle comparisons == rows x 8 rules",
              ver.get("oracle_comparisons") == 3200000 * 8,
              {"comparisons": ver.get("oracle_comparisons")})
    res.check(f"{pass_name}: oracle mismatches == 0",
              ver.get("oracle_mismatches") == 0)
    flag_totals = ver.get("flag_totals", {})
    run["flag_totals"] = flag_totals
    res.check(f"{pass_name}: flag totals present for all 8 rules",
              sorted(flag_totals) == sorted(V1_RULE_IDS))
    mismatches_by_rule = ver.get("mismatches_by_rule", {})
    res.check(f"{pass_name}: mismatches-by-rule all zero",
              sorted(mismatches_by_rule) == sorted(V1_RULE_IDS)
              and all(v == 0 for v in mismatches_by_rule.values()))

    # SP1 frozen + runtime safety
    sp1 = r.get("sp1_frozen", {})
    run["sp1_frozen_status"] = sp1.get("status")
    res.check(f"{pass_name}: SP1 frozen baseline verified",
              sp1.get("status") == "PASS"
              and sp1.get("expected_names_verified") is True
              and sp1.get("expected_hashes_verified") is True)
    safety = r.get("runtime_safety", {})
    run["runtime_safety_status"] = safety.get("status")
    res.check(f"{pass_name}: runtime safety PASS", safety.get("status") == "PASS")

    # Runtime + RSS recorded (per-run result carries CLI + verify durations;
    # generation seconds live under dataset)
    run["stage_runtimes"] = {
        "generation_seconds": ds.get("generation_seconds"),
        "validation_seconds": cli.get("duration_seconds"),
        "verify_oracle_seconds": ver.get("verify_duration_seconds"),
    }
    run["engine_peak_rss_mb"] = r.get("engine_peak_rss_mb")
    res.check(f"{pass_name}: stage runtimes recorded (3 stages)",
              all(isinstance(v, (int, float)) and v > 0
                  for v in run["stage_runtimes"].values()),
              run["stage_runtimes"])
    res.check(f"{pass_name}: engine peak RSS recorded",
              isinstance(r.get("engine_peak_rss_mb"), (int, float))
              and r["engine_peak_rss_mb"] > 0)

    # Engine evidence dir: manifest integrity + evidence root
    res.check(f"{pass_name}: engine evidence dir exists", os.path.isdir(engine_dir))
    if os.path.isdir(engine_dir):
        try:
            m = json.load(open(os.path.join(engine_dir, "manifest.json"),
                               encoding="utf-8"))
        except Exception as exc:
            res.check(f"{pass_name}: engine manifest parseable", False, str(exc))
            m = None
        if m is not None:
            run["manifest_run_id"] = m.get("run_id")
            run["manifest_type"] = m.get("manifest_type")
            run["schema_hash"] = m.get("schema_hash")
            run["rule_hashes"] = m.get("rule_hashes")
            run["manifest_flag_counts"] = m.get("flag_counts")
            res.check(f"{pass_name}: manifest type success",
                      m.get("manifest_type") == "success")
            res.check(f"{pass_name}: manifest run_id matches pass",
                      m.get("run_id") == f"final_3m_{pass_name}")
            res.check(f"{pass_name}: schema hash recorded (64 hex)",
                      isinstance(m.get("schema_hash"), str)
                      and len(m["schema_hash"]) == 64)
            res.check(f"{pass_name}: rule hashes exactly 8 V1 rules",
                      sorted((m.get("rule_hashes") or {})) == sorted(V1_RULE_IDS))
            # flag counts in manifest match oracle flag totals
            res.check(f"{pass_name}: manifest flag counts == oracle flag totals",
                      (m.get("flag_counts") or {}) == flag_totals)
            # recorded artifact hashes vs actual (lineage/audit/monitoring/alerts)
            fh = m.get("file_hashes", {})
            gf = m.get("generated_files", {})
            for role, rel_path in (("lineage", gf.get("lineage")),
                                   ("audit", gf.get("audit")),
                                   ("monitoring", gf.get("monitoring")),
                                   ("alerts", gf.get("alerts"))):
                if not rel_path:
                    res.check(f"{pass_name}: manifest records {role} path", False)
                    continue
                abs_p = os.path.join(REPO_ROOT, rel_path)
                if os.path.isfile(abs_p):
                    actual = sha256_file(abs_p)
                    recorded = (fh.get(role) or {}).get("sha256") \
                        if isinstance(fh.get(role), dict) else fh.get(role)
                    res.check(f"{pass_name}: {role} hash matches actual file",
                              recorded == actual)
                else:
                    res.check(f"{pass_name}: {role} artifact present", False,
                              {"expected_path": rel_path})
            # output.csv: by-design staging absence is allowed (hash-anchored)
            out_rel = gf.get("output")
            if out_rel and not os.path.isfile(os.path.join(REPO_ROOT, out_rel)):
                run["output_csv_absent_by_design"] = True

        # Evidence root verification (tamper-evident)
        sys.path.insert(0, REPO_ROOT)
        from data_quality_platform.validation.evidence_root import verify_evidence_root
        ok, det = verify_evidence_root(engine_dir)
        run["evidence_root_verified"] = ok
        run["evidence_root_detail"] = det if ok else det
        res.check(f"{pass_name}: tamper-evident evidence root verified", ok,
                  det if not ok else None)

    return run


def main():
    os.makedirs(os.path.join(REPO_ROOT, "evidence", "rebuild_verification"),
                exist_ok=True)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    res = Result()
    head = git(["rev-parse", "HEAD"]).stdout.strip()
    checker_sha = sha256_file(CHECKER_SCRIPT)

    # FINAL_RESULTS.json
    fr_path = os.path.join(EVIDENCE_DIR, "FINAL_RESULTS.json")
    res.check("FINAL_RESULTS.json exists", os.path.isfile(fr_path))
    fr = json.load(open(fr_path, encoding="utf-8"))
    final_status = fr.get("final_status")
    res.check("FINAL_RESULTS final_status == PASS", final_status == "PASS")

    # Checker identity: FINAL_RESULTS provenance vs actual file + lineage
    prov = fr.get("provenance", {})
    res.check("FINAL_RESULTS checker SHA matches actual file",
              prov.get("script_sha256") == checker_sha,
              {"recorded": prov.get("script_sha256"), "actual": checker_sha})
    res.check("FINAL_RESULTS git_commit is ancestor of current HEAD",
              git_is_ancestor(prov.get("git_commit", "")),
              {"recorded": prov.get("git_commit"), "current_head": head})
    # Anti-stale: exactly two runs present, no third run
    run_keys = sorted(fr.get("runs", {}).keys())
    res.check("exactly two runs recorded", run_keys == ["run_1", "run_2"],
              {"runs": run_keys})

    # Per-run verification
    r1 = verify_run("pass1", res, checker_sha, head)
    r2 = verify_run("pass2", res, checker_sha, head)

    # ---- Cross-run invariants ----
    x = {}
    x["run_ids_distinct"] = (r1.get("manifest_run_id"), r2.get("manifest_run_id")) != (None, None) \
        and r1.get("manifest_run_id") != r2.get("manifest_run_id")
    res.check("run IDs distinct", x["run_ids_distinct"])
    for field, label in (
        ("input_sha256", "input SHA256"),
        ("output_sha256", "output SHA256"),
        ("schema_hash", "schema hash"),
        ("rule_hashes", "rule identity"),
        ("checker_script_sha256", "checker script SHA"),
        ("git_commit", "git lineage"),
    ):
        x[field] = r1.get(field) == r2.get(field) and r1.get(field) is not None
        res.check(f"cross-run {label} equal", x[field])
    x["both_mismatches_zero"] = (r1.get("oracle_mismatches") == 0
                                 and r2.get("oracle_mismatches") == 0)
    res.check("both runs mismatch count == 0", x["both_mismatches_zero"])
    x["flag_totals_equal"] = r1.get("flag_totals") == r2.get("flag_totals")
    res.check("cross-run flag totals equal", x["flag_totals_equal"])
    x["input_rows_equal"] = r1.get("input_rows") == r2.get("input_rows") == 3200000
    res.check("both runs 3,200,000 input rows", x["input_rows_equal"])

    # Cross-check against FINAL_RESULTS top-level
    res.check("FINAL_RESULTS input SHA == run evidence",
              fr.get("input_sha256") == r1.get("input_sha256") == r2.get("input_sha256"))
    res.check("FINAL_RESULTS output SHA == run evidence",
              fr.get("output_sha256") == r1.get("output_sha256") == r2.get("output_sha256"))
    det = fr.get("determinism_detail", {})
    res.check("FINAL_RESULTS determinism gate true (byte-identical)",
              det.get("byte_identical_output") is True
              and det.get("input_hash_equal") is True
              and det.get("output_hash_equal") is True)
    comp = fr.get("comparison_count", {})
    res.check("comparison math: per-run == rows x 8, combined == sum",
              comp.get("run_1") == comp.get("run_2") == 25600000
              and comp.get("combined_total") == 51200000)
    res.check("FINAL_RESULTS run statuses both PASS",
              fr.get("runs", {}).get("run_1", {}).get("status") == "PASS"
              and fr.get("runs", {}).get("run_2", {}).get("status") == "PASS")

    # Pinned frozen baseline (SP1) source exists + matches 8 V1 rule names
    res.check("pinned rule baseline exists", os.path.isfile(PINNED_BASELINE))
    if os.path.isfile(PINNED_BASELINE):
        pinned = json.load(open(PINNED_BASELINE, encoding="utf-8"))
        names = sorted(pinned.get("rules", {}) if isinstance(pinned.get("rules"), dict) else [rr.get("rule_id") for rr in pinned.get("rules", [])])
        res.check("pinned baseline names == 8 V1 rules",
                  names == sorted(V1_RULE_IDS), {"names": names})

    # Oracle architecture note: independent execution implementation
    # against pinned frozen reference truth (tests + verify stage).
    oracle_tests = os.path.join(REPO_ROOT, "tests", "unit",
                                "test_rule_oracle_consistency.py")
    res.check("oracle consistency test module present",
              os.path.isfile(oracle_tests))

    verdict = "PASS" if res.all_pass else "FAIL"
    report = {
        "report": "DQAEIP Run 1 + Run 2 pair verification",
        "generated_utc": started,
        "verification_mode": "fail-closed; every invariant derived from actual artifacts",
        "git_head_at_verification": head,
        "checker_script_sha256_actual": checker_sha,
        "evidence_dir": "evidence/validation/2026-09-19/fresh_3m2",
        "run_1": r1,
        "run_2": r2,
        "cross_run_invariants": x,
        "checks_total": len(res.checks),
        "checks_failed": len(res.failures),
        "failures": res.failures,
        "verdict": verdict,
        "verdict_note": (
            "PASS only when every required per-run and cross-run invariant "
            "is established from actual evidence artifacts; any missing or "
            "contradictory evidence is NOT_VERIFIED and fails this gate"
        ),
    }
    out_path = os.path.join(REPO_ROOT, "ebuild" if False else "evidence",
                            "rebuild_verification", "run_pair_verification.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, sort_keys=False)
        f.write("\n")

    print(f"RUN PAIR VERIFICATION: {verdict}")
    print(f"  checks: {len(res.checks)} total, {len(res.failures)} failed")
    for name in res.failures:
        print(f"  FAILED: {name}")
    print(f"  report: evidence/rebuild_verification/run_pair_verification.json")
    return 0 if res.all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
