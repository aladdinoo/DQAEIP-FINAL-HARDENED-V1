#!/usr/bin/env python3
"""Fixed-point verification for DQAEIP-FINAL-HARDENED-RELEASE-2026-09-19.

One run = deterministic rebuild of the complete derived layer from the
SAME authoritative inputs, then verification that the release documents
BYTE-CONVERGE (stabilized writes: identical bytes when the freshly
derived payload differs only in generated_utc) and that every checker
re-verifies green.

Authoritative inputs (never re-derived here):
  * the canonical test summary (fresh execution, captured before)
  * the 2026-09-19 fresh_3m2 regression evidence (frozen runs)
  * the live release-gate artifact (PASS 22/22 round)
  * the frozen rule sources / checker / baseline registry

Derived layer rebuilt deterministically on every run:
  evidence namespace -> README -> FINAL_RESULTS -> RELEASE_NOTES ->
  release_manifest -> release model artifacts -> observability ->
  consistency matrix -> README consistency -> contradiction check

Recorded per run: SHA-256 of every stabilized release document BEFORE
and AFTER the rebuild, byte-convergence verdict, checker verdicts,
suite identity source values. Two runs (Run #1, Run #2) must produce
identical records on all deterministic fields — a false fixed point
(excluding changed artifacts from verification) is impossible because
every release document is hashed and compared.

Usage: python scripts/hardening_fixed_point_verify.py <run_number>
Writes: evidence/FINAL_HARDENED_RELEASE_2026-09-19/fixed_point/
        run_<N>.json
Exit 0 only when the fixed point holds and every check passes.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NS = REPO_ROOT / "evidence" / "FINAL_HARDENED_RELEASE_2026-09-19"
FP_DIR = NS / "fixed_point"

# Anti-regression: import canonical GATE_COUNT from release_gate.py
# so this verifier never hardcodes a stale gate count. The previous
# hardcoded "22" became stale after B-8 introduced 24 gates.
try:
    import importlib.util
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    _spec = importlib.util.spec_from_file_location(
        "release_gate",
        str(REPO_ROOT / "scripts" / "release_gate.py"))
    _rg_mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_rg_mod)
    _GATE_COUNT_CANON = _rg_mod.GATE_COUNT
except Exception as _exc:
    raise SystemExit(
        f"FAIL-CLOSED: cannot import GATE_COUNT from scripts/release_gate.py: "
        f"{_exc}; ensure release_gate.py is present and syntactically "
        f"valid before running fixed-point verification")

# The stabilized release-document set (byte-convergence targets).
STABILIZED_DOCS = [
    "README.md",
    "FINAL_RESULTS.json",
    "final_result.json",
    "RELEASE_NOTES.md",
    "release_manifest.json",
    "evidence/release/release_evidence_model.json",
    "evidence/release/reproducibility_manifest.json",
    "evidence/release/golden_release_snapshot.json",
    "evidence/release/claim_provenance.json",
]

REBUILD_SEQUENCE = [
    ("evidence namespace", ["python3", "scripts/hardening_evidence_builder.py"]),
    ("README", ["python3", "scripts/hardening_readme_builder.py"]),
    ("FINAL_RESULTS", ["python3", "scripts/hardening_final_results_builder.py"]),
    ("RELEASE_NOTES", ["python3", "scripts/hardening_release_notes_builder.py"]),
    ("release_manifest", ["python3", "scripts/hardening_release_manifest_builder.py"]),
    ("release model artifacts", ["python3", "scripts/hardening_release_model_builder.py"]),
    ("observability", ["python3", "scripts/build_observability_status.py"]),
    ("consistency matrix", ["python3", "scripts/consistency_matrix.py"]),
    ("README consistency", ["python3", "scripts/readme_consistency_check.py"]),
    ("contradiction check", ["python3", "scripts/contradiction_checker.py"]),
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def doc_hashes() -> dict:
    out = {}
    for rel in STABILIZED_DOCS:
        p = REPO_ROOT / rel
        out[rel] = sha256_file(p) if p.is_file() else None
    return out


def run(cmd) -> tuple:
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True,
                          text=True, timeout=600)
    return proc.returncode, proc.stdout, proc.stderr


def checker_battery() -> dict:
    """Re-verify every release checker LIVE (fail-closed)."""
    results = {}
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

    # 1. contradiction checker verdict
    from data_quality_platform.assurance import contradiction_checker
    con = contradiction_checker.run_contradiction_check(str(REPO_ROOT))
    results["contradiction_check"] = {
        "verdict": con.get("verdict"),
        "pass": con.get("verdict") == "CONSISTENT",
    }

    # 2. consistency matrix verdict
    matrix = json.loads((REPO_ROOT / "evidence" / "release" /
                         "consistency_matrix.json").read_text())
    results["consistency_matrix"] = {
        "verdict": matrix.get("verdict"),
        "pass": matrix.get("verdict") == "CONSISTENT",
    }

    # 3. README consistency (§10 checker)
    import readme_consistency_check as rcc
    rcc_result = rcc.run_check(str(REPO_ROOT))
    results["readme_consistency"] = {
        "verdict": rcc_result.get("verdict"),
        "pass": rcc_result.get("verdict") == "CONSISTENT",
    }

    # 4. FINAL_RESULTS claims live re-derivation
    from data_quality_platform.assurance import claims as claims_mod
    fr = json.loads((REPO_ROOT / "FINAL_RESULTS.json").read_text())
    rep = claims_mod.verify_claims(fr.get("claims", []), str(REPO_ROOT))
    results["claims_rederivation"] = {
        "claims_total": rep.get("claims_total"),
        "recheck_passed": rep.get("recheck_passed"),
        "pass": rep.get("recheck_passed") is True,
    }

    # 5. release document schemas
    from data_quality_platform.assurance import release_schema
    problems = []
    for rel, kind in (("FINAL_RESULTS.json", "final_results"),
                      ("final_result.json", "final_results"),
                      ("release_manifest.json", "release_manifest"),
                      ("evidence/release/reproducibility_manifest.json",
                       "reproducibility_manifest")):
        p, _ = release_schema.validate_document(str(REPO_ROOT / rel), kind)
        problems += [(rel, x) for x in p]
    results["release_schemas"] = {
        "problems": problems,
        "pass": not problems,
    }

    # 6. observability terminal statuses (live evidence match)
    obs = json.loads((REPO_ROOT / "evidence" / "release" /
                      "observability_status.json").read_text())
    dims = obs.get("status_dimensions", {})
    results["observability"] = {
        "EVIDENCE_INTEGRITY_STATUS": dims.get("EVIDENCE_INTEGRITY_STATUS",
                                              {}).get("status"),
        "RELEASE_VERDICT": dims.get("RELEASE_VERDICT", {}).get("status"),
        "VALIDATION_STATUS": dims.get("VALIDATION_STATUS", {}).get("status"),
        "pass": (dims.get("EVIDENCE_INTEGRITY_STATUS", {}).get("status")
                 == "PASS"
                 and dims.get("RELEASE_VERDICT", {}).get("status")
                 == "PASS_WITH_DOCUMENTED_LIMITATIONS"
                 and dims.get("VALIDATION_STATUS", {}).get("status")
                 == "PASS"),
    }

    # 7. live gate state (input, not rebuilt)
    gate = json.loads((REPO_ROOT / "evidence" / "release_gate" /
                       "final_release_gate.json").read_text())
    results["live_gate"] = {
        "overall_verdict": gate.get("overall_verdict"),
        "gate_count": gate.get("gate_count"),
        "gate_counts": gate.get("gate_counts"),
        "pass": (gate.get("overall_verdict") == "PASS"
                 and gate.get("gate_counts", {}).get("pass")
                 == gate.get("gate_count") == _GATE_COUNT_CANON),
    }

    # 8. canonical test summary agreement (input identity)
    ts = json.loads((REPO_ROOT / "evidence" / "rebuild_verification" /
                     "test_summary.json").read_text())
    fr_ti = fr.get("test_identity", {})
    ns_suite = json.loads((NS / "test_suite" / "test_suite_results.json")
                          .read_text()).get("stats", {})
    agree = all(fr_ti.get(k) == ts.get(k) == ns_suite.get(k)
                for k in ("collected", "passed", "skipped", "failed",
                          "errors"))
    results["test_identity_agreement"] = {
        "canonical": {k: ts.get(k) for k in ("collected", "passed",
                                             "skipped", "failed",
                                             "errors")},
        "final_results": {k: fr_ti.get(k) for k in
                          ("collected", "passed", "skipped", "failed",
                           "errors")},
        "namespace": ns_suite,
        "pass": agree and ts.get("all_green") is True,
    }
    return results


def main() -> int:
    run_no = sys.argv[1] if len(sys.argv) > 1 else "1"
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    before = doc_hashes()

    # deterministic rebuild of the complete derived layer
    rebuild_steps = []
    for name, cmd in REBUILD_SEQUENCE:
        rc, out, err = run(cmd)
        rebuild_steps.append({"step": name, "exit_code": rc})
        if rc != 0:
            print(f"FAIL-CLOSED: rebuild step {name!r} exited {rc}:\n"
                  f"{out[-800:]}\n{err[-800:]}")
            return 1

    after = doc_hashes()
    converged = {rel: before[rel] == after[rel] and after[rel] is not None
                 for rel in STABILIZED_DOCS}
    byte_convergence = all(converged.values())

    checks = checker_battery()
    all_checks_pass = all(v.get("pass") for v in checks.values())

    record = {
        "schema": "dqaeip.hardening.fixed_point.run/1.0",
        "run": run_no,
        "generated_utc": started,
        "authoritative_inputs": {
            "canonical_test_summary": "evidence/rebuild_verification/"
                                      "test_summary.json",
            "regression_evidence": "evidence/validation/2026-09-19/"
                                   "fresh_3m2/",
            "live_gate_artifact": "evidence/release_gate/"
                                  "final_release_gate.json",
        },
        "rebuild_sequence": rebuild_steps,
        "document_hashes_before": before,
        "document_hashes_after": after,
        "byte_convergence": converged,
        "byte_convergence_verdict": (
            "CONVERGED" if byte_convergence else "DIVERGED"),
        "checker_battery": checks,
        "fixed_point_holds": byte_convergence and all_checks_pass,
    }
    FP_DIR.mkdir(parents=True, exist_ok=True)
    out_path = FP_DIR / f"run_{run_no}.json"
    out_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")

    print(f"fixed-point Run #{run_no}: "
          f"byte-convergence={record['byte_convergence_verdict']} "
          f"({'/'.join(rel for rel, ok in converged.items() if not ok) or 'all 9 documents byte-identical'})"
          f"; checks "
          f"{'ALL PASS' if all_checks_pass else 'FAILED: ' + ', '.join(k for k, v in checks.items() if not v.get('pass'))}")
    print(f"record: {out_path.relative_to(REPO_ROOT)}")
    return 0 if record["fixed_point_holds"] else 1


if __name__ == "__main__":
    sys.exit(main())
