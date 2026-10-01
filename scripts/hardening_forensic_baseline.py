#!/usr/bin/env python3
"""PHASE 0 — FORENSIC BASELINE AUDIT for the 2026-09-19 hardening release.

READ-ONLY. Establishes the exact current state of the repository and the
certified 2026-09-18 baseline BEFORE any hardening change is made, and
writes an immutable machine-readable baseline record to

    evidence/forensic_baseline/2026-09-19/baseline_record.json

The record pins (with SHA-256 where applicable):
- outer workspace git state and inner DQAEIP repo git state
- the certified 2026-09-18 release ZIP (hash, size, member count) checked
  against its sidecar
- the certified fresh_3m2 dual-run validation facts (rows, runs, oracle
  comparisons, mismatches, input/output SHA-256, verdict)
- Frozen V1 identity (source file SHA-256, 8 rule names, registry hash)
- the current README.md / FINAL_RESULTS.json / release_manifest.json
- the evidence namespace inventory
- test suite, release gate, mutation and negative-gate counts as recorded
  in the current evidence tree

Fail-closed: a missing expected baseline artifact is recorded as MISSING
with ok=false; the audit never invents values.
"""

import hashlib
import json
import os
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO_ROOT, "evidence", "forensic_baseline", "2026-09-19")
OUT_PATH = os.path.join(OUT_DIR, "baseline_record.json")

# ── Certified 2026-09-18 baseline expectations (declared constants; the
#    audit VERIFIES the tree against them rather than trusting them) ──
BASELINE_RELEASE_ID = "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18"
BASELINE_ZIP = os.path.join(
    os.path.dirname(REPO_ROOT), "..", "download",
    "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18.zip")
BASELINE_ZIP_SIDECAR = BASELINE_ZIP + ".sha256"
FROZEN_V1_REL = "data_quality_platform/rules/v1_rules.py"
FROZEN_V1_EXPECTED_SHA = (
    "daef1ded54c7d3c79898a1ba253be2acd5b6120e18b16b09009fdd7be9fc2276")
FRESH_3M2_REL = "evidence/validation/2026-09-18/fresh_3m2/harness"
EXPECTED_RULES = [
    "first_name_cleaning_candidate", "last_name_cleaning_candidate",
    "name_cleaning_candidate", "email_blank", "email_syntax_failure",
    "proposed_email_export_eligible", "zip_state_assessable",
    "geography_mismatch_candidate",
]


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(chunk), b""):
            h.update(c)
    return h.hexdigest()


def git(repo, args):
    return subprocess.run(["git", "-C", repo] + args,
                          capture_output=True, text=True, check=False)


def git_state(repo):
    head = git(repo, ["rev-parse", "HEAD"]).stdout.strip()
    branch = git(repo, ["branch", "--show-current"]).stdout.strip()
    tree = git(repo, ["rev-parse", "HEAD^{tree}"]).stdout.strip()
    status = git(repo, ["status", "--porcelain"]).stdout
    lines = [l for l in status.splitlines() if l.strip()]
    modified = [l[3:] for l in lines if l[:2] in (" M", "M ")]
    untracked = [l[3:] for l in lines if l[:2] == "??"]
    staged = [l[3:] for l in lines if l[:2] not in (" M", "??", "  ")]
    log5 = [l for l in git(repo, ["log", "--oneline", "-5"]).stdout.splitlines()]
    return {
        "repo": repo,
        "head": head or None,
        "branch": branch or None,
        "tree_hash": tree or None,
        "modified_count": len(modified),
        "untracked_count": len(untracked),
        "staged_count": len(staged),
        "status_porcelain_sha256": hashlib.sha256(
            status.encode("utf-8")).hexdigest() if status else None,
        "last_5_commits": log5,
    }


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), True
    except Exception as exc:
        return {"_error": f"{type(exc).__name__}: {exc}"}, False


def main():
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    record = {
        "report": "DQAEIP forensic baseline audit (Phase 0, read-only)",
        "audit_utc": started,
        "audit_mode": "READ_ONLY",
        "release_context": {
            "baseline_certified_release": BASELINE_RELEASE_ID,
            "baseline_release_date": "2026-09-18",
            "new_hardened_release_planned":
                "DQAEIP-FINAL-HARDENED-RELEASE-2026-09-19",
            "policy": ("baseline preserved byte-for-byte; new release adds "
                       "additive hardening only; Frozen V1 immutable"),
        },
        "git": {
            "dqaeip_repo": git_state(REPO_ROOT),
            "outer_workspace": git_state(
                os.path.dirname(os.path.dirname(REPO_ROOT))),
        },
    }

    # ── Certified release ZIP + sidecar ─────────────────────────────
    zip_abs = os.path.normpath(BASELINE_ZIP)
    zip_info = {"path": zip_abs, "exists": os.path.exists(zip_abs)}
    if os.path.exists(zip_abs):
        zip_info["sha256"] = sha256_file(zip_abs)
        zip_info["size_bytes"] = os.path.getsize(zip_abs)
        import zipfile
        with zipfile.ZipFile(zip_abs) as zf:
            zip_info["member_count"] = len(zf.namelist())
    sidecar_abs = os.path.normpath(BASELINE_ZIP_SIDECAR)
    zip_info["sidecar_exists"] = os.path.exists(sidecar_abs)
    sidecar_ok = False
    if os.path.exists(sidecar_abs):
        with open(sidecar_abs, "r", encoding="utf-8") as f:
            sidecar_text = f.read().strip()
        expected_hash = sidecar_text.split()[0] if sidecar_text else ""
        sidecar_ok = (expected_hash == zip_info.get("sha256"))
        zip_info["sidecar_expected_sha256"] = expected_hash
        zip_info["sidecar_matches_actual"] = sidecar_ok
    record["certified_release_zip"] = zip_info

    # ── fresh_3m2 certified validation facts ────────────────────────
    fr_path = os.path.join(REPO_ROOT, FRESH_3M2_REL, "FINAL_RESULTS.json")
    fr, fr_ok = load_json(fr_path)
    runs = fr.get("runs", {}) if fr_ok else {}
    p1 = runs.get("run_1", {})
    p2 = runs.get("run_2", {})
    record["certified_validation"] = {
        "source": FRESH_3M2_REL + "/FINAL_RESULTS.json",
        "readable": fr_ok,
        "final_status": fr.get("final_status") if fr_ok else None,
        "rows": fr.get("rows") if fr_ok else None,
        "runs": fr.get("runs_run_count", len(runs)) if fr_ok else None,
        "input_sha256": fr.get("input_sha256") if fr_ok else None,
        "output_sha256": fr.get("output_sha256") if fr_ok else None,
        "run_1": {
            "status": p1.get("status"),
            "oracle_comparisons": (
                p1.get("oracle", {}).get("comparisons")),
            "oracle_mismatches": (
                p1.get("oracle", {}).get("mismatches")),
        },
        "run_2": {
            "status": p2.get("status"),
            "oracle_comparisons": (
                p2.get("oracle", {}).get("comparisons")),
            "oracle_mismatches": (
                p2.get("oracle", {}).get("mismatches")),
        },
        "expected_input_sha256": (
            "59624a53c72f908f1dde673ceecf59e0662ae721bb8f9af7e165acba5318d153"),
        "expected_output_sha256": (
            "b72adc235160a86e0b99a08f988dd0bb5f2cff82bbe5b5d28ea07c5a5719329a"),
    }
    cv = record["certified_validation"]
    cv["input_sha256_matches_declared"] = (
        cv.get("input_sha256") == cv["expected_input_sha256"])
    cv["output_sha256_matches_declared"] = (
        cv.get("output_sha256") == cv["expected_output_sha256"])
    cv["combined_comparisons"] = (
        (cv["run_1"].get("oracle_comparisons") or 0)
        + (cv["run_2"].get("oracle_comparisons") or 0)) if fr_ok else None

    # ── Frozen V1 ───────────────────────────────────────────────────
    v1_path = os.path.join(REPO_ROOT, FROZEN_V1_REL)
    v1 = {"source": FROZEN_V1_REL, "exists": os.path.exists(v1_path)}
    if os.path.exists(v1_path):
        v1["sha256"] = sha256_file(v1_path)
        v1["size_bytes"] = os.path.getsize(v1_path)
        v1["matches_expected_sha256"] = (
            v1["sha256"] == FROZEN_V1_EXPECTED_SHA)
    record["frozen_v1"] = v1

    # pinned rule matrix (per-rule implementation hashes)
    rm_path = os.path.join(REPO_ROOT, "evidence/final_execution/rule_matrix.json")
    rm, rm_ok = load_json(rm_path)
    matrix_rules = {}
    if rm_ok:
        for r in rm.get("rules", []):
            matrix_rules[r.get("rule_id")] = {
                "implementation_hash_head": r.get("implementation_hash_head"),
                "rule_version": r.get("rule_version"),
            }
    record["pinned_rule_matrix"] = {
        "source": "evidence/final_execution/rule_matrix.json",
        "readable": rm_ok,
        "rule_count": len(matrix_rules),
        "rule_names_match_frozen_eight": (
            sorted(matrix_rules.keys()) == sorted(EXPECTED_RULES)),
        "frozen_v1_source_sha256_in_matrix": rm.get("frozen_v1_source_sha256"),
        "rules": matrix_rules,
    }

    # ── current release documents ───────────────────────────────────
    docs = {}
    for name in ("README.md", "FINAL_RESULTS.json", "release_manifest.json",
                 "RELEASE_NOTES.md"):
        p = os.path.join(REPO_ROOT, name)
        entry = {"path": name, "exists": os.path.exists(p)}
        if os.path.exists(p):
            entry["sha256"] = sha256_file(p)
            entry["size_bytes"] = os.path.getsize(p)
            if name.endswith(".json"):
                d, ok = load_json(p)
                entry["readable"] = ok
                if ok:
                    if name == "FINAL_RESULTS.json":
                        entry["release_name"] = d.get("release_identity", {}).get(
                            "release_name")
                        entry["final_status"] = d.get("final_release_status")
                    if name == "release_manifest.json":
                        entry["release_name"] = d.get("release_name")
        docs[name] = entry
    record["current_release_documents"] = docs

    # ── evidence namespace inventory ────────────────────────────────
    ev_root = os.path.join(REPO_ROOT, "evidence")
    namespaces = {}
    if os.path.isdir(ev_root):
        for name in sorted(os.listdir(ev_root)):
            p = os.path.join(ev_root, name)
            if os.path.isdir(p):
                file_count = sum(
                    len(files) for _, _, files in os.walk(p))
                namespaces[name] = {"file_count": file_count}
    record["evidence_namespaces"] = namespaces

    # ── counts from current evidence ────────────────────────────────
    ts, ts_ok = load_json(os.path.join(
        REPO_ROOT, "evidence/rebuild_verification/test_summary.json"))
    record["test_summary"] = {
        "source": "evidence/rebuild_verification/test_summary.json",
        "readable": ts_ok,
        "collected": ts.get("collected"), "passed": ts.get("passed"),
        "skipped": ts.get("skipped"), "failed": ts.get("failed"),
        "all_green": ts.get("all_green"),
    }
    gate, gate_ok = load_json(os.path.join(
        REPO_ROOT, "evidence/release_gate/final_release_gate.json"))
    record["release_gate"] = {
        "source": "evidence/release_gate/final_release_gate.json",
        "readable": gate_ok,
        "gate_count": len(gate.get("gates", [])) if gate_ok else None,
        "overall_verdict": gate.get("overall_verdict") if gate_ok else None,
    }
    bmut, bmut_ok = load_json(os.path.join(
        REPO_ROOT, "evidence/mutation_testing/mutation_results.json"))
    record["business_mutation"] = {
        "source": "evidence/mutation_testing/mutation_results.json",
        "readable": bmut_ok,
        "mutants_total": bmut.get("mutants_total") if bmut_ok else None,
        "detected": bmut.get("detected") if bmut_ok else None,
        "mutation_score": bmut.get("mutation_score") if bmut_ok else None,
    }
    amut, amut_ok = load_json(os.path.join(
        REPO_ROOT, "evidence/release/assurance_mutation.json"))
    neg = amut.get("scenarios_total") if amut_ok else None
    record["assurance_mutation"] = {
        "source": "evidence/release/assurance_mutation.json",
        "readable": amut_ok,
        "scenarios_total": neg,
        "all_rejected": amut.get("all_rejected") if amut_ok else None,
    }

    # ── historical reference census (context, explicitly historical) ─
    ref18 = ref15 = 0
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        parts = os.path.relpath(dirpath, REPO_ROOT).split(os.sep)
        if parts and parts[0] in (".git", ".venv", ".pytest_cache",
                                  "__pycache__", "data"):
            dirnames[:] = []
            continue
        for fn in filenames:
            if fn.endswith((".py", ".json", ".md", ".txt", ".yaml", ".yml",
                            ".csv")):
                fp = os.path.join(dirpath, fn)
                try:
                    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                    ref18 += text.count("2026-09-18")
                    ref15 += text.count("2026-09-15")
                except OSError:
                    pass
    record["historical_reference_census"] = {
        "note": ("counts include legitimate historical labels; the new "
                 "release must label any retained 2026-09-18 references as "
                 "BASELINE_CERTIFIED (historical) and never as current"),
        "files_with_2026_09_18_occurrences": ref18,
        "files_with_2026_09_15_occurrences": ref15,
    }

    # ── verdict of the audit itself ─────────────────────────────────
    checks = {
        "baseline_zip_sidecar_verified": sidecar_ok,
        "frozen_v1_sha_matches": v1.get("matches_expected_sha256") is True,
        "certified_input_sha_matches": cv["input_sha256_matches_declared"],
        "certified_output_sha_matches": cv["output_sha256_matches_declared"],
        "rule_names_match_frozen_eight": (
            record["pinned_rule_matrix"]["rule_names_match_frozen_eight"]),
    }
    record["audit_checks"] = checks
    record["audit_verdict"] = (
        "BASELINE_ESTABLISHED" if all(checks.values())
        else "BASELINE_DISCREPANCY")

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, sort_keys=False)
    print(f"baseline record written: {os.path.relpath(OUT_PATH, REPO_ROOT)}")
    print(f"audit verdict: {record['audit_verdict']}")
    for k, v in checks.items():
        print(f"  {'OK ' if v else 'BAD'} {k}")
    return 0 if record["audit_verdict"] == "BASELINE_ESTABLISHED" else 1


if __name__ == "__main__":
    sys.exit(main())
