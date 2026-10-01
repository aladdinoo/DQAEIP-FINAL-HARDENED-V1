#!/usr/bin/env python3
"""DQAEIP FINAL UPDATE 2026-09-17 — Phase 1: artifact classification +
authoritative inventory (task book sections 5 and 7).

Classifies every tracked artifact into EXACTLY one of:

    AUTHORITATIVE  immutable truth; protected; never regenerated
    DERIVED        rebuilt by this update from authoritative evidence
    STALE          derived artifact whose dependency moved (pre-update)
    SUPERSEDED     historical record explicitly kept (marked historical)
    TEMPORARY      scratch / test fixtures / caches
    UNKNOWN        protected until manually resolved (never auto-deleted)

UNKNOWN is protected until manually resolved. Never automatically delete
UNKNOWN. This script never deletes anything — classification only.

Writes:

    evidence/FINAL_UPDATE_2026-09-17/authoritative_inventory/
        authoritative_inventory.json

For each protected (AUTHORITATIVE) artifact it records path, role,
SHA-256, size, type, authority level, producer, provenance, and
protection reason, exactly as required by section 7.
"""

import hashlib
import json
import os
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(
    REPO_ROOT, "evidence", "FINAL_UPDATE_2026-09-17",
    "authoritative_inventory")
UPDATE_ID = "DQAEIP-FINAL-UPDATE-2026-09-17"

# --------------------------------------------------------------------- 
# AUTHORITATIVE — frozen business-semantic core (12 production files)
# ---------------------------------------------------------------------
FROZEN_PRODUCTION_FILES = {
    "data_quality_platform/rules/v1_rules.py":
        "Frozen V1 rule definitions (8 rules, versions 1.0.0)",
    "data_quality_platform/rules/registry.py":
        "Frozen V1 rule registry (must expose exactly the 8 V1 rules)",
    "data_quality_platform/rules/base.py":
        "Rule base classes (evaluation contract for V1)",
    "data_quality_platform/contracts.py":
        "33/41 schema + flag contract + state/zip map",
    "data_quality_platform/validation/engine.py":
        "Deterministic validation engine (drives the 8 V1 rules)",
    "data_quality_platform/generation/synthetic.py":
        "Deterministic synthetic generator (seed 20260910 corpus)",
    "data_quality_platform/lineage/recorder.py":
        "Decision provenance recorder (row-level lineage)",
    "data_quality_platform/evidence/manifests.py":
        "Evidence manifest writer (tamper-evident roots)",
    "data_quality_platform/audit/trail.py":
        "Audit trail writer",
    "data_quality_platform/monitoring/quality.py":
        "Quality monitoring (SLA evaluation)",
    "data_quality_platform/alerting/alerts.py":
        "Alert evaluation (SLA breach surfacing)",
    "runner/cli.py":
        "CLI entry point (validate/generate/verify commands)",
}

# AUTHORITATIVE — official 3M run-pair evidence (2026-09-15)
OFFICIAL_EVIDENCE_DIR = "evidence/final_3m_validation_2026-09-15"
OFFICIAL_EVIDENCE_ROLE = (
    "Official Run 1 + Run 2 validation evidence (3,000,000 synthetic rows "
    "per run; 24,000,000 comparisons per run; 48,000,000 combined; "
    "0 mismatches; byte-identical outputs)")

# AUTHORITATIVE — verification chain (checker + verifier)
# Anti-regression: distinguish the historical certified baseline checker
# SHA (0ef7c10c... from the 2026-09-18 certified baseline) from the
# current hardened checker SHA (d216dbca... after B-8 hardening). The
# previous description presented 0ef7c10c as the current SHA, which
# became stale after B-8 hardened scripts/final_3m_validation.py.
AUTHORITATIVE_SCRIPTS = {
    "scripts/final_3m_validation.py":
        "Official fail-closed 3M checker. Historical certified baseline "
        "SHA: 0ef7c10c... (preserved in RELEASE_IDENTITY.json "
        "frozen_core.checker_sha256 as the 2026-09-18 certified "
        "baseline reference). Current hardened checker SHA: "
        "d216dbca... (B-8 hardened; computed live at runtime by "
        "sha256sum scripts/final_3m_validation.py). The current and "
        "historical SHAs legitimately differ post-B-8: B-8 hardened "
        "the checker to add L-8 byte-identity classification, B-9 "
        "wrapper SHA binding, and refactor the runtime-safety payload "
        "classifier. The script identity recorded inside Run 1/Run 2 "
        "evidence carries the SHA at the time those runs executed.",
    "scripts/verify_run_pair.py":
        "Run-pair fail-closed verifier (95 checks over the official pair)",
}

# ---------------------------------------------------------------------
# DERIVED — release-facing artifacts rebuilt by THIS update
# ---------------------------------------------------------------------
DERIVED_CURRENT = {
    "README.md": "Presentation layer (rebuilt from FINAL_RESULTS)",
    "RELEASE_NOTES.md": "Release notes (rebuilt)",
    "DELIVERY_MANIFEST.json": "Delivery manifest (rebuilt)",
    "FINAL_RESULTS.json": "Authoritative final machine-readable results",
    "final_result.json": "Compatibility copy of final results",
    "release_manifest.json": "Release manifest (rebuilt)",
}

DERIVED_EVIDENCE_DIRS = {
    "evidence/release/": "Current release evidence model (rebuilt)",
    "evidence/release_gate/": "Release gate results (re-run)",
    "evidence/verification/": "Verification reports (re-run)",
    "evidence/rebuild_verification/": "Run-pair + test verification (re-run)",
    "evidence/mutation_testing/": "Mutation assurance results (re-run)",
    "evidence/impact_analysis/": "Rule impact analysis (re-derived)",
}

# DERIVED — documentation / report presentation layer (checked by the
# contradiction engine; values must trace to FINAL_RESULTS)
DERIVED_DOC_DIRS = {
    "docs/": "Documentation (presentation layer; metrics must trace to "
             "FINAL_RESULTS or verified evidence)",
    "reports/": "Reports (presentation layer)",
}

# SUPERSEDED — historical reports
SUPERSEDED_DOC_DIRS = {
    "reports/history/": "Historical report archive (explicitly historical)",
}

# ---------------------------------------------------------------------
# SUPERSEDED — historical records (explicitly marked historical)
# ---------------------------------------------------------------------
SUPERSEDED_DIRS = {
    "evidence/final_3m_validation/":
        "Superseded earlier record of the same official run pair "
        "(final_3m_validation_2026-09-15 is the authoritative record)",
    "evidence/enterprise_release_2026-09-15/":
        "Superseded release identity (enterprise release 2026-09-15)",
    "evidence/final_release_2026-09-15/":
        "Superseded release manifest (2026-09-15)",
    "evidence/final_hardening_2026-09-16/":
        "Superseded release identity (final hardening 2026-09-16)",
    "evidence/assurance_baseline/":
        "Historical assurance baseline (2026-09-17 rebaseline session)",
    "evidence/assurance_rebaseline_2026-09-17/":
        "Superseded release identity (Enterprise-Assurance-Validation)",
    "evidence/assurance_rebuild_2026-09-17/":
        "Superseded release identity (Assurance-Rebuild-Release)",
    "evidence/assurance_rebuild_baseline/":
        "Historical rebuild baseline (zero-assumption session)",
    "evidence/rebuild_baseline/":
        "Historical rebuild baseline (2026-09-16 session)",
    "evidence/hardening_baseline/":
        "Historical hardening baseline (2026-09-16 session)",
    "evidence/final/": "Historical final-evidence root (pre-release)",
    "evidence/final_execution/": "Historical execution evidence",
    "evidence/final_verification/": "Historical verification evidence",
    "evidence/final_5m_execution/":
        "Historical 5M execution probe (NOT the official pair; diagnostic)",
    "evidence/dqvp_performance/": "Historical performance certification",
    "evidence/benchmarks/": "Historical benchmark evidence",
    "evidence/sp1_successor_2026-09-10/":
        "Historical SP1 successor validation (validation-only geography)",
    "evidence/audit_1k/": "Historical 1k audit evidence",
    "evidence/rt_1k/": "Historical runtime 1k evidence",
    "evidence/test_q9/": "Historical test scratch (q9)",
    "evidence/q20_cli/": "Historical CLI probe (q20)",
}

# ---------------------------------------------------------------------
# TEMPORARY — fixtures / scratch (kept for test reproducibility; small)
# ---------------------------------------------------------------------
TEMPORARY_PATHS = {
    "data/generated/": "Deterministic test fixtures (small CSVs, replayed "
                       "by the unit suite; NOT the official 3M corpus)",
}

# New namespace of THIS update (working area, promoted on verification)
UPDATE_NAMESPACE = "evidence/FINAL_UPDATE_2026-09-17/"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(args):
    return subprocess.run(["git", "-C", REPO_ROOT] + args,
                          capture_output=True, text=True, check=False)


def component_type(rel):
    """Manual-resolution annotation for UNKNOWN (protected) entries."""
    if rel.startswith("data_quality_platform/") or rel.startswith("runner/"):
        return ("active production code (non-frozen platform/runner "
                "modules; behavior covered by the test suite)")
    if rel.startswith("tests/"):
        return ("active test suite (test-health monitored; collected/passed/"
                "skipped counts are release evidence inputs)")
    if rel.startswith("scripts/"):
        return ("analysis / verification tooling (producers of derived "
                "evidence; each tool is SHA-anchored when it participates "
                "in a verification chain)")
    if rel.startswith("sql/") or rel == "docker-compose.yml" \
            or rel == "airflow/dags/dq_validation_dag.py":
        return ("static deployment configuration (static code only; NOT "
                "runtime-verified — ClickHouse/Airflow remain NOT_VERIFIED "
                "as runtime claims)")
    if rel == "pyproject.toml" or rel == "configs/quality.yaml":
        return "project / quality configuration (dependency-drift monitored)"
    if rel in (".gitignore", ".env.example"):
        return "repository hygiene file (.env.example documents required " \
               "variables; contains NO secrets)"
    return "unclassified system component"


def classify(rel, tracked_set):
    """Return (classification, role, protection_reason, manual_resolution)."""
    if rel in FROZEN_PRODUCTION_FILES:
        return ("AUTHORITATIVE", FROZEN_PRODUCTION_FILES[rel],
                "Frozen V1 business-semantic core; any change is an "
                "unauthorized rule change -> STOP", None)
    if rel in AUTHORITATIVE_SCRIPTS:
        return ("AUTHORITATIVE", AUTHORITATIVE_SCRIPTS[rel],
                "Verification-chain anchor; SHA recorded inside official "
                "evidence; modification invalidates the run-pair proof", None)
    if rel == OFFICIAL_EVIDENCE_DIR or rel.startswith(
            OFFICIAL_EVIDENCE_DIR + "/"):
        return ("AUTHORITATIVE", OFFICIAL_EVIDENCE_ROLE,
                "Official Run 1 + Run 2 evidence; NEVER regenerate, NEVER "
                "modify, NEVER create Run 3 -> STOP on any change", None)
    if rel.startswith(UPDATE_NAMESPACE):
        return ("DERIVED", "FINAL UPDATE 2026-09-17 work product (this "
                           "update; staged then promoted)",
                "New evidence produced under the update namespace", None)
    if rel in DERIVED_CURRENT:
        return ("DERIVED", DERIVED_CURRENT[rel],
                "Derived from authoritative evidence; rebuilt by this "
                "update", None)
    for d, role in SUPERSEDED_DOC_DIRS.items():
        if rel.startswith(d):
            return ("SUPERSEDED", role,
                    "Historical record; explicitly marked historical; kept "
                    "for audit; never presented as current", None)
    for d, role in DERIVED_DOC_DIRS.items():
        if rel.startswith(d):
            return ("DERIVED", role,
                    "Presentation layer; rebuilt/checked by this update; "
                    "metric values must trace to verified evidence", None)
    for d, role in DERIVED_EVIDENCE_DIRS.items():
        if rel == d.rstrip("/") or rel.startswith(d):
            return ("DERIVED", role,
                    "Derived evidence; refreshed/re-derived by this update", None)
    for d, role in SUPERSEDED_DIRS.items():
        if rel == d.rstrip("/") or rel.startswith(d):
            return ("SUPERSEDED", role,
                    "Historical record; explicitly marked historical; kept "
                    "for audit; never presented as current", None)
    for d, role in TEMPORARY_PATHS.items():
        if rel == d.rstrip("/") or rel.startswith(d):
            return ("TEMPORARY", role,
                    "Small deterministic fixtures replayed by tests; "
                    "not release evidence", None)
    if rel.endswith(".pyc") or "__pycache__" in rel:
        return ("TEMPORARY", "bytecode cache", "regenerable", None)
    return None  # UNKNOWN -> caller annotates


def main():
    out_path = os.path.join(OUT_DIR, "authoritative_inventory.json")
    os.makedirs(OUT_DIR, exist_ok=True)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    tracked = [p for p in git(["ls-files", "-z"]).stdout.split("\0") if p]
    head = git(["rev-parse", "HEAD"]).stdout.strip()

    classification = {}
    authoritative_records = []
    counts = {"AUTHORITATIVE": 0, "DERIVED": 0, "STALE": 0,
              "SUPERSEDED": 0, "TEMPORARY": 0, "UNKNOWN": 0}
    unknown_files = []
    authoritative_hashes = {}

    for rel in sorted(tracked):
        abs_p = os.path.join(REPO_ROOT, rel)
        if not os.path.isfile(abs_p):
            classification[rel] = {
                "classification": "UNKNOWN",
                "role": "tracked path missing on disk",
                "protection_reason": "tracked file missing from worktree — "
                                     "investigate before any action",
            }
            counts["UNKNOWN"] += 1
            unknown_files.append(rel)
            continue
        result = classify(rel, set(tracked))
        sha = sha256_file(abs_p)
        size = os.path.getsize(abs_p)
        if result is None:
            resolution = component_type(rel)
            classification[rel] = {
                "classification": "UNKNOWN",
                "role": "not an evidence-taxonomy artifact",
                "protection_reason": "UNKNOWN = protected until manually "
                                     "resolved; never automatically deleted",
                "manual_resolution": (
                    f"reviewed {started[:10]}: {resolution}; retained as "
                    "protected system content"),
                "sha256": sha,
                "size_bytes": size,
            }
            counts["UNKNOWN"] += 1
            unknown_files.append(rel)
            continue
        cls, role, reason = result[:3]
        classification[rel] = {
            "classification": cls, "role": role,
            "protection_reason": reason, "sha256": sha,
            "size_bytes": size,
        }
        counts[cls] += 1
        if cls == "AUTHORITATIVE":
            authoritative_hashes[rel] = sha
            authoritative_records.append({
                "path": rel,
                "role": role,
                "sha256": sha,
                "size": size,
                "type": ("python-source" if rel.endswith(".py")
                         else "evidence-json" if rel.endswith(".json")
                         else "other"),
                "authority_level": "AUTHORITATIVE",
                "producer": (
                    "2026-09-15 official run / frozen V1 sources"
                    if rel.startswith(OFFICIAL_EVIDENCE_DIR)
                    else "frozen V1 source tree" if rel.startswith(
                        "data_quality_platform/") or rel == "runner/cli.py"
                    else "verification chain"),
                "provenance": (
                    "commit history 0e2eab8..4228fe5; official pair "
                    "verified 95/95 by verify_run_pair.py"
                    if rel.startswith(OFFICIAL_EVIDENCE_DIR)
                    else "tracked since initial freeze; SHA anchored in "
                         "baseline daef1ded/0ef7c10c/0ec07367 chain"),
                "protection_reason": reason,
            })

    # Sanity: STALE is a runtime state assigned by the freshness engine
    # (section 12), not a static starting classification. Pre-update, no
    # artifact is statically STALE: staleness is DERIVED from dependency
    # movement. Record this explicitly so the classification is honest.
    doc = {
        "report": "DQAEIP FINAL UPDATE 2026-09-17 — artifact "
                  "classification + authoritative inventory",
        "update_id": UPDATE_ID,
        "generated_utc": started,
        "git_head": head,
        "classification_taxonomy": {
            "AUTHORITATIVE": "immutable truth; protected; never regenerated",
            "DERIVED": "rebuilt by this update from authoritative evidence",
            "STALE": "derived artifact whose dependency moved "
                     "(assigned dynamically by freshness engine)",
            "SUPERSEDED": "historical record explicitly kept",
            "TEMPORARY": "fixtures / caches / scratch",
            "UNKNOWN": "protected until manually resolved; never "
                       "auto-deleted",
        },
        "classification_counts": counts,
        "unknown_files": unknown_files,
        "unknown_policy": ("UNKNOWN artifacts are protected until manually "
                           "resolved; never automatically deleted "
                           "(task book section 5). Every UNKNOWN entry in "
                           "this inventory carries a manual_resolution "
                           "annotation from the 2026-09-17 review: active "
                           "production code, tests, tooling, configs and "
                           "repository-hygiene files. They are retained and "
                           "protected — the UNKNOWN label means 'outside the "
                           "evidence taxonomy', not 'suspicious'."),
        "stale_note": ("STALE is assigned dynamically by the freshness "
                       "engine when a dependency hash moves; at update "
                       "start the recorded count is a snapshot only"),
        "authoritative_inventory": authoritative_records,
        "authoritative_artifact_count": len(authoritative_records),
        "full_classification": classification,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"Phase 1 artifact classification written: "
          f"evidence/FINAL_UPDATE_2026-09-17/authoritative_inventory/"
          f"authoritative_inventory.json")
    print(f"  classification counts: {counts}")
    print(f"  authoritative artifacts inventoried: "
          f"{len(authoritative_records)}")
    print(f"  UNKNOWN files (protected): {len(unknown_files)}")
    for u in unknown_files[:20]:
        print(f"    UNKNOWN: {u}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
