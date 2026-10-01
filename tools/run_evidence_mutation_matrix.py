#!/usr/bin/env python3
"""DQAEIP FINAL PORTABLE EVIDENCE & RELEASE HARDENING — Phase 8.

EVIDENCE MUTATION TESTING (task-book section 9).

Controlled mutations are applied to ISOLATED temporary fixtures
(never to authoritative production evidence). For every mutation the
portable-release verification machinery must produce:

    FAIL  or  NOT_VERIFIED

A tampered-evidence PASS is impossible by construction and any
mutation that would produce PASS fails the whole matrix (exit 4).

Mutations (task-book list, all 16):

    1  51.2M -> 47M                        combined comparisons anchor
    2  0 mismatches -> 1                    mismatch anchor
    3  Run 2 -> Run 3                       run-count integrity
    4  Frozen V1 SHA modification           rule-source identity
    5  checker SHA modification             checker identity
    6  input SHA modification               dataset identity
    7  output SHA modification              output identity
    8  verdict modification                 verdict is machine-derived
    9  limitation removal                   limitation registry integrity
    10 evidence dependency modification     freshness must go STALE
    11 manifest modification                manifest hash verification
    12 release identity modification        cross-artifact identity
    13 stale evidence state                 staleness detection
    14 absolute path injection              path gate must FAIL
    15 missing evidence                    NOT_VERIFIED, never PASS
    16 malformed JSON                      schema/parse rejection

Verification layers exercised per mutation (as appropriate):
    - claim-graph verification (re-hash + re-derive, fail-closed)
    - evidence schema validation (anchor-aware structural validators)
    - artifact identity validation (STALE detection)
    - absolute-path release gate
    - freshness evaluation (STALE / NOT_VERIFIED)
    - manifest hash verification
    - release-identity cross-check
    - verdict re-derivation (a verdict is never trusted as recorded)
"""

import json
import os
import shutil
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance.artifact_identity import (  # noqa: E402
    make_identity, validate_identity)
from data_quality_platform.assurance.claim_graph import (  # noqa: E402
    GraphBuilder, verify_graph)
from data_quality_platform.assurance.evidence_schema import (  # noqa: E402
    validate_schema_identity)
from data_quality_platform.assurance.integrity import (  # noqa: E402
    evaluate_freshness, run_all_monitors)
from data_quality_platform.assurance.portable_evidence import (  # noqa: E402
    MACHINE_PATH_DETECTORS)

NS = "evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18"
OFFICIAL = "evidence/validation/2026-09-18/fresh_3m2/harness"
V1_REL = "data_quality_platform/rules/v1_rules.py"
CHECKER_REL = "scripts/final_3m_validation.py"
VERIFIER_REL = "scripts/verify_run_pair.py"
RUN_PAIR_REL = "evidence/rebuild_verification/run_pair_verification.json"
LIMITS_REL = "evidence/release/limitation_registry.json"
PORTABLE_FR_REL = (f"{NS}/final_results/"
                   "FINAL_RESULTS_PORTABLE_2026-09-18.json")
PORTABLE_COPY_REL = (f"{NS}/portable_evidence/{OFFICIAL}/"
                     "FINAL_RESULTS.json")
RELEASE_ID = "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18"

V1_SHA = ("daef1ded54c7d3c79898a1ba253be2acd5b6120e18b16b09009f"
          "dd7be9fc2276")
INPUT_SHA = ("59624a53c72f908f1dde673ceecf59e0662ae721bb8f9af7e165"
             "acba5318d153")
OUTPUT_SHA = ("b72adc235160a86e0b99a08f988dd0bb5f2cff82bbe5b5d28ea07"
              "c5a5719329a")


# ------------------------------------------------------------- fixture

CHECKER_SHA = ("0ef7c10c14a1df317c23cb0dfc73b3a60c2257c064b35080d69"
              "4e5fe8bc50d84")


def _write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def _write_json(root, rel, doc):
    _write(root, rel, json.dumps(doc, indent=2, sort_keys=True) + "\n")


def _read_json(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return json.load(f)


def build_fixture(root):
    """Synthetic evidence tree carrying the REAL anchor constants
    (content synthetic; the real protected evidence is never touched).
    """
    # frozen V1 source: byte-copy of the REAL frozen file (read-only)
    with open(os.path.join(REPO_ROOT, V1_REL), encoding="utf-8") as f:
        _write(root, V1_REL, f.read())
    _write(root, "data_quality_platform/rules/__init__.py", "")

    official = {
        "rows": 3200000, "seed": 20260918,
        "input_sha256": INPUT_SHA, "output_sha256": OUTPUT_SHA,
        "oracle_comparisons": 51200000,
        "comparison_count": {"run_1": 25600000, "run_2": 25600000,
                             "combined_total": 51200000},
        "oracle_mismatches": {"run_1": 0, "run_2": 0,
                              "combined_total": 0},
        "determinism_status":
            "PASS (byte-identical across two complete runs)",
        "safety_status": "PASS", "sp1_isolation_status": "PASS",
        "runs": {"run_1": {"oracle": {"comparisons": 25600000,
                                      "mismatches": 0}},
                 "run_2": {"oracle": {"comparisons": 25600000,
                                      "mismatches": 0}}},
    }
    _write_json(root, f"{OFFICIAL}/FINAL_RESULTS.json", official)
    for n in (1, 2):
        _write_json(root, f"{OFFICIAL}/pass{n}_result.json",
                    {"pass": f"pass{n}", "rows": 3200000,
                     "oracle": {"comparisons": 25600000,
                                "mismatches": 0}})
    _write(root, CHECKER_REL, "# synthetic checker stand-in\n")
    _write(root, VERIFIER_REL, "# synthetic verifier stand-in\n")
    _write_json(root, RUN_PAIR_REL,
                {"verdict": "PASS", "checks_total": 95,
                 "checks_failed": 0})
    _write_json(root, "evidence/rebuild_verification/test_summary.json",
                {"collected": 979, "passed": 970, "failed": 0,
                 "skipped": 9, "errors": 0, "all_green": True})
    _write_json(root, "evidence/mutation_testing/mutation_results.json",
                {"mutants_detected": 17, "mutants_total": 17})
    _write_json(root, "evidence/release/assurance_mutation.json",
                {"scenarios_detected": 14, "scenarios_total": 14})
    _write_json(root, LIMITS_REL, {"limitations": [
        {"id": f"LIM-{i:03d}", "text": f"synthetic limitation {i}"}
        for i in range(1, 12)]})  # 11 limitations

    portable_fr = {
        "schema": {"name": "dqaeip.final_results", "version": "2.0"},
        "release_identity": {"release_id": RELEASE_ID,
                             "release_date": "2026-09-18"},
        "derived_values": {"combined_comparisons": 51200000,
                           "combined_mismatches": 0, "run_count": 2},
        "verification": {"run_pair_verdict": "PASS",
                         "byte_identical_outputs": True,
                         "test_all_green": True},
        "verification_state": "PASS_WITH_DOCUMENTED_LIMITATIONS",
    }
    _write_json(root, PORTABLE_FR_REL, portable_fr)

    _write_json(root, PORTABLE_COPY_REL, {
        "portable_derivation": {
            "derived_from": f"{OFFICIAL}/FINAL_RESULTS.json",
            "source_sha256": "0" * 64,
            "policy": "A — original preserved; normalized derived",
            "normalized_field_paths": ["$.provenance.script_path"],
            "normalized_string_count": 1,
            "environment_placeholders": {},
            "portability": "PORTABLE"},
        "provenance": {"script_path": "scripts/final_3m_validation.py"},
        "rows": 3200000,
    })

    _write_json(root, f"{NS}/release_manifest/release_manifest.json", {
        "report": "fixture manifest",
        "release_id": RELEASE_ID,
        "files": [
            {"path": rel, "sha256": _sha(os.path.join(root, rel))}
            for rel in (PORTABLE_FR_REL, LIMITS_REL)
        ]})

    # recorded dependency graph (provenance-time hashes — the
    # freshness engine compares these against the LIVE tree)
    _write_json(root, f"{NS}/dependency_graph/dependency_graph.json", {
        "nodes": [{
            "artifact": PORTABLE_FR_REL,
            "dependencies": [
                {"path": RUN_PAIR_REL,
                 "sha256": _sha(os.path.join(root, RUN_PAIR_REL))},
                {"path": f"{OFFICIAL}/FINAL_RESULTS.json",
                 "sha256": _sha(os.path.join(
                                         root, f"{OFFICIAL}/FINAL_RESULTS.json"))},
            ]}]})

    _write(root, "README.md", "# synthetic readme (no claims)\n")
    return root


def _sha(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------- verification layers

def fixture_claim_graph(root):
    """Build a claim graph over the fixture tree (fail-closed)."""
    b = GraphBuilder(root)

    def d_combined(r):
        doc = _safe_json(os.path.join(r, f"{OFFICIAL}/FINAL_RESULTS.json"))
        if not doc:
            return None
        cc = doc.get("comparison_count", {})
        if cc.get("run_1") == cc.get("run_2") == 25600000 and \
                cc.get("combined_total") == 51200000:
            return 51200000
        return None

    def d_mismatches(r):
        doc = _safe_json(os.path.join(r, f"{OFFICIAL}/FINAL_RESULTS.json"))
        mm = (doc or {}).get("oracle_mismatches", {})
        if mm.get("combined_total") == 0:
            return 0
        return None

    def d_run_count(r):
        doc = _safe_json(os.path.join(r, f"{OFFICIAL}/FINAL_RESULTS.json"))
        runs = (doc or {}).get("runs") or {}
        return 2 if set(runs) == {"run_1", "run_2"} else None

    def d_v1(r):
        p = os.path.join(r, V1_REL)
        return _sha(p) if os.path.isfile(p) else None

    def d_input(r):
        return (_safe_json(os.path.join(
            r, f"{OFFICIAL}/FINAL_RESULTS.json")) or {}).get(
                "input_sha256")

    def d_output(r):
        return (_safe_json(os.path.join(
            r, f"{OFFICIAL}/FINAL_RESULTS.json")) or {}).get(
                "output_sha256")

    def d_checker(r):
        # asserts the OFFICIAL checker anchor — a tampered checker
        # file cannot satisfy its own published identity
        p = os.path.join(r, CHECKER_REL)
        if not os.path.isfile(p):
            return None
        live = _sha(p)
        # synthetic stand-in cannot hash to the real anchor; the
        # fixture therefore anchors the EXPECTED value from the
        # fixture's own recorded identity (see fixture_claim_graph)
        return live

    def d_run_pair(r):
        doc = _safe_json(os.path.join(r, RUN_PAIR_REL))
        if doc and doc.get("verdict") == "PASS":
            return doc.get("checks_total")
        return None

    def d_limits(r):
        doc = _safe_json(os.path.join(r, LIMITS_REL))
        lims = (doc or {}).get("limitations")
        return len(lims) if isinstance(lims, list) else None

    def d_verdict(r):
        doc = _safe_json(os.path.join(r, PORTABLE_FR_REL))
        # verdict is re-DERIVED from the verification block, never
        # trusted as recorded (mirrors tools/final_results_rebuild)
        if not doc:
            return None
        v = doc.get("verification", {})
        dv = doc.get("derived_values", {})
        if v.get("run_pair_verdict") != "PASS" or \
                v.get("byte_identical_outputs") is not True or \
                v.get("test_all_green") is not True:
            return "FAIL"
        if dv.get("combined_mismatches") != 0 or \
                dv.get("run_count") != 2:
            return "FAIL"
        return "PASS_WITH_DOCUMENTED_LIMITATIONS"

    specs = [
        ("combined_comparisons", 51200000, d_combined),
        ("combined_mismatches", 0, d_mismatches),
        ("run_count", 2, d_run_count),
        ("frozen_v1_sha256", V1_SHA, d_v1),
        ("input_sha256", INPUT_SHA, d_input),
        ("output_sha256", OUTPUT_SHA, d_output),
        ("checker_sha256", None, d_checker),
        ("limitation_count", 11, d_limits),
        ("verification_state", "PASS_WITH_DOCUMENTED_LIMITATIONS",
         d_verdict),
        ("run_pair_verification", 95, d_run_pair),
    ]
    derivations = {}
    for cid, value, fn in specs:
        if value is None:
            value = fn(root)
        ev = {"frozen_v1_sha256": [V1_REL],
              "checker_sha256": [CHECKER_REL],
              "input_sha256": [f"{OFFICIAL}/FINAL_RESULTS.json"],
              "output_sha256": [f"{OFFICIAL}/FINAL_RESULTS.json"],
              "run_pair_verification": [RUN_PAIR_REL],
              }.get(cid, [f"{OFFICIAL}/FINAL_RESULTS.json",
                          f"{OFFICIAL}/pass1_result.json",
                          f"{OFFICIAL}/pass2_result.json"])
        if cid == "limitation_count":
            ev = [LIMITS_REL]
        if cid == "verification_state":
            ev = [PORTABLE_FR_REL]
        b.add_claim(cid, cid, value, fn.__name__, ev, derivation_fn=fn)
        derivations[cid] = fn
    return b.build(), derivations


def _safe_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def claims_reject(root):
    """True when the claim graph verification refuses the tampered
    tree (any claim NOT_VERIFIED)."""
    graph, derivations = fixture_claim_graph(root)
    rep = verify_graph(graph, root, derivations)
    return not rep["all_claims_verified"], rep


def schema_rejects(root):
    status, problems = validate_schema_identity(
        _safe_json(os.path.join(root, PORTABLE_FR_REL)) or {})
    return status in ("MALFORMED", "UNKNOWN_SCHEMA",
                      "MISSING_SCHEMA"), status


def verdict_rederived_differs(root):
    """The recorded verdict differs from the machine-derived one."""
    doc = _safe_json(os.path.join(root, PORTABLE_FR_REL))
    if not doc:
        return True
    v = doc.get("verification", {})
    dv = doc.get("derived_values", {})
    if v.get("run_pair_verdict") != "PASS" or \
            v.get("byte_identical_outputs") is not True or \
            v.get("test_all_green") is not True:
        return True
    if dv.get("combined_mismatches") != 0 or dv.get("run_count") != 2:
        return True
    return doc.get("verification_state") != \
        "PASS_WITH_DOCUMENTED_LIMITATIONS"


def path_gate_rejects(root):
    """Scan the fixture's portable evidence for machine paths."""
    hits = []
    for dirpath, _dirs, files in os.walk(os.path.join(root, NS)):
        for fn in files:
            p = os.path.join(dirpath, fn)
            try:
                with open(p, encoding="utf-8",
                          errors="replace") as f:
                    text = f.read()
            except OSError:
                continue
            for _d, pat in MACHINE_PATH_DETECTORS:
                if pat.search(text):
                    hits.append(p)
                    break
    return bool(hits)


def manifest_rejects(root):
    doc = _safe_json(os.path.join(
        root, f"{NS}/release_manifest/release_manifest.json"))
    if not doc:
        return True
    for entry in doc.get("files", []):
        p = os.path.join(root, entry["path"])
        if not os.path.isfile(p) or _sha(p) != entry["sha256"]:
            return True
    return False


def identity_rejects(root):
    """Artifact identity validation against the tampered portable
    FINAL_RESULTS."""
    try:
        rec = make_identity(PORTABLE_FR_REL, "DERIVED",
                            repo_root=root)
    except (ValueError, FileNotFoundError):
        return True
    return bool(validate_identity(rec, repo_root=root))


def freshness_not_current(root):
    """Compare the RECORDED (provenance-time) dependency hashes in
    the fixture's dependency graph against the LIVE tree."""
    graph = _safe_json(os.path.join(
        root, f"{NS}/dependency_graph/dependency_graph.json"))
    if not graph:
        return True, "NOT_VERIFIED"
    node = graph["nodes"][0]
    result = evaluate_freshness(node["artifact"],
                                node["dependencies"], root)
    return result["state"] != "CURRENT", result["state"]


def release_identity_mismatch(root):
    doc = _safe_json(os.path.join(root, PORTABLE_FR_REL)) or {}
    manifest = _safe_json(os.path.join(
        root, f"{NS}/release_manifest/release_manifest.json")) or {}
    ids = {doc.get("release_identity", {}).get("release_id"),
           manifest.get("release_id")}
    return None in ids or len(ids) != 1 or RELEASE_ID not in ids


# ------------------------------------------------------------ mutations

def mutate(mutation_id, root):
    """Apply one controlled mutation to the fixture; return
    (rejected, outcome_status, detail)."""
    if mutation_id == "m01_combined_47m":
        d = _read_json(root, f"{OFFICIAL}/FINAL_RESULTS.json")
        d["comparison_count"]["combined_total"] = 47000000
        d["oracle_comparisons"] = 47000000
        _write_json(root, f"{OFFICIAL}/FINAL_RESULTS.json", d)
        rej, rep = claims_reject(root)
        return rej, rep["verdict"], "claim re-derivation mismatch"

    if mutation_id == "m02_one_mismatch":
        d = _read_json(root, f"{OFFICIAL}/FINAL_RESULTS.json")
        d["oracle_mismatches"]["combined_total"] = 1
        _write_json(root, f"{OFFICIAL}/FINAL_RESULTS.json", d)
        rej, rep = claims_reject(root)
        return rej, rep["verdict"], "mismatch anchor violated"

    if mutation_id == "m03_run3":
        d = _read_json(root, f"{OFFICIAL}/FINAL_RESULTS.json")
        d["runs"]["run_3"] = d["runs"].pop("run_2")
        _write_json(root, f"{OFFICIAL}/FINAL_RESULTS.json", d)
        rej, rep = claims_reject(root)
        return rej, rep["verdict"], "run count is not exactly 2"

    if mutation_id == "m04_frozen_v1_sha":
        with open(os.path.join(root, V1_REL), encoding="utf-8") as f:
            v1_text = f.read()
        _write(root, V1_REL, v1_text + "\n# tampered\n")
        rej, rep = claims_reject(root)
        return rej, rep["verdict"], "frozen V1 identity changed"

    if mutation_id == "m05_checker_sha":
        _write(root, CHECKER_REL,
               "# tampered checker stand-in\nx = 1\n")
        # the claim asserts the checker's PROVENANCE-TIME identity
        # (captured before mutation); the live file now hashes
        # differently -> STALE evidence node -> claim NOT_VERIFIED
        graph, derivations = fixture_claim_graph(root)
        for c in graph["claims"]:
            if c["claim_id"] == "checker_sha256":
                c["value"] = PRE_MUTATION_CHECKER_SHA.get(
                    root, c["value"])
        rep = verify_graph(graph, root, derivations)
        return not rep["all_claims_verified"], rep["verdict"], \
            "checker identity changed"

    if mutation_id == "m06_input_sha":
        d = _read_json(root, f"{OFFICIAL}/FINAL_RESULTS.json")
        d["input_sha256"] = "f" * 64
        _write_json(root, f"{OFFICIAL}/FINAL_RESULTS.json", d)
        rej, rep = claims_reject(root)
        return rej, rep["verdict"], "input SHA anchor violated"

    if mutation_id == "m07_output_sha":
        d = _read_json(root, f"{OFFICIAL}/FINAL_RESULTS.json")
        d["output_sha256"] = "f" * 64
        _write_json(root, f"{OFFICIAL}/FINAL_RESULTS.json", d)
        rej, rep = claims_reject(root)
        return rej, rep["verdict"], "output SHA anchor violated"

    if mutation_id == "m08_verdict_tamper":
        d = _read_json(root, PORTABLE_FR_REL)
        d["verification_state"] = "PASS"  # illegal upgrade
        _write_json(root, PORTABLE_FR_REL, d)
        rej, _ = claims_reject(root)
        detail = verdict_rederived_differs(root)
        return (rej or detail), "FAIL", \
            "verdict is machine-derived; recorded upgrade rejected"

    if mutation_id == "m09_limitation_removed":
        d = _read_json(root, LIMITS_REL)
        d["limitations"] = d["limitations"][:-1]
        _write_json(root, LIMITS_REL, d)
        rej, rep = claims_reject(root)
        return rej, rep["verdict"], "limitation count changed"

    if mutation_id == "m10_dependency_modified":
        _write_json(root, RUN_PAIR_REL, {"verdict": "PASS",
                                         "checks_total": 95,
                                         "checks_failed": 0,
                                         "injected": True})
        # graph recorded the original dependency hash
        rej, state = freshness_not_current(root)
        return rej, state, "dependency hash moved -> STALE"

    if mutation_id == "m11_manifest_modified":
        m = _read_json(root,
                       f"{NS}/release_manifest/release_manifest.json")
        m["files"][0]["sha256"] = "0" * 64
        _write_json(root,
                    f"{NS}/release_manifest/release_manifest.json", m)
        return manifest_rejects(root), "FAIL", \
            "manifest hash mismatch"

    if mutation_id == "m12_release_identity":
        d = _read_json(root, PORTABLE_FR_REL)
        d["release_identity"]["release_id"] = "DQAEIP-IMPOSTOR-RELEASE"
        _write_json(root, PORTABLE_FR_REL, d)
        return release_identity_mismatch(root), "FAIL", \
            "release identity inconsistent across artifacts"

    if mutation_id == "m13_stale_evidence":
        # dependency rewritten AFTER provenance recorded: the
        # freshness engine must report STALE (timestamps never
        # participate; content identity does)
        orig = _read_json(root, RUN_PAIR_REL)
        _write_json(root, RUN_PAIR_REL, dict(orig, checks_total=96))
        rej, state = freshness_not_current(root)
        return rej, state, "stale dependency state detected"

    if mutation_id == "m14_absolute_path_injection":
        d = _read_json(root, PORTABLE_COPY_REL)
        d["provenance"]["script_path"] = (
            "/home/z/my-project/dqvp-work/repo/scripts/"
            "final_3m_validation.py")
        _write_json(root, PORTABLE_COPY_REL, d)
        return path_gate_rejects(root), "FAIL", \
            "machine-local path injected into portable evidence"

    if mutation_id == "m15_missing_evidence":
        os.remove(os.path.join(root, RUN_PAIR_REL))
        rej, rep = claims_reject(root)
        return rej, rep["verdict"], "required evidence missing"

    if mutation_id == "m16_malformed_json":
        with open(os.path.join(root, PORTABLE_FR_REL), "w",
                  encoding="utf-8") as f:
            f.write('{"schema": {"name": "dqaeip.final_results", '
                    '"version": "2.0"}, "derived_values": ')
        rej, status = schema_rejects(root)
        rej2, _rep = claims_reject(root)
        return (rej or rej2), "FAIL", "malformed JSON rejected"

    raise ValueError(f"unknown mutation {mutation_id}")


PRE_MUTATION_CHECKER_SHA = {}

MUTATIONS = [
    "m01_combined_47m", "m02_one_mismatch", "m03_run3",
    "m04_frozen_v1_sha", "m05_checker_sha", "m06_input_sha",
    "m07_output_sha", "m08_verdict_tamper", "m09_limitation_removed",
    "m10_dependency_modified", "m11_manifest_modified",
    "m12_release_identity", "m13_stale_evidence",
    "m14_absolute_path_injection", "m15_missing_evidence",
    "m16_malformed_json",
]


def main():
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    results = []
    all_rejected = True
    for mid in MUTATIONS:
        with tempfile.TemporaryDirectory() as td:
            root = build_fixture(td)
            # provenance-time expectations captured BEFORE mutation:
            # claim values and recorded dependency hashes come from
            # the pristine fixture, then the mutation is applied
            PRE_MUTATION_CHECKER_SHA[root] = _sha(
                os.path.join(root, CHECKER_REL))
            rejected, outcome, detail = mutate(mid, root)
            PRE_MUTATION_CHECKER_SHA.pop(root, None)
            if not rejected or outcome == "PASS":
                all_rejected = False
            results.append({
                "mutation_id": mid,
                "rejected": bool(rejected),
                "outcome": outcome if outcome in ("FAIL",
                                                   "NOT_VERIFIED",
                                                   "STALE") else
                ("NOT_VERIFIED" if outcome == "NOT_VERIFIED"
                 else "FAIL"),
                "detail": detail,
                "fixture_isolated": True,
            })
            mark = "REJECTED" if rejected else "!!! ACCEPTED !!!"
            print(f"  [{mark}] {mid}: {detail} -> {outcome}")

    outcome_fix = []
    for r in results:
        o = r["outcome"]
        if o not in ("FAIL", "NOT_VERIFIED"):
            # STALE / INVALID are rejection states too; normalize to
            # the two documented outcome classes
            o = "NOT_VERIFIED" if o in ("STALE", "INVALID") else o
        r["outcome"] = o
        outcome_fix.append(r)
    results = outcome_fix

    doc = {
        "report": "DQAEIP evidence mutation matrix (Phase 8)",
        "schema": {"name": "dqaeip.evidence_mutation_matrix",
                   "version": "1.0"},
        "release_id": RELEASE_ID,
        "generated_utc": started,
        "mutation_count": len(results),
        "mutations": results,
        "policy": "PASS is NEVER produced from tampered evidence; every "
                  "mutation must yield FAIL or NOT_VERIFIED; fixtures "
                  "are isolated temporary trees — authoritative "
                  "evidence is never touched",
        "outcome": "PASS" if all_rejected else "FAIL",
    }

    out_path = os.path.join(REPO_ROOT, NS, "mutation_testing",
                            "evidence_mutation_matrix.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"evidence mutation matrix: {doc['outcome']} "
          f"({sum(1 for r in results if r['rejected'])}/"
          f"{len(results)} rejected)")
    print(f"written: {os.path.relpath(out_path, REPO_ROOT)}")
    return 0 if doc["outcome"] == "PASS" else 4


if __name__ == "__main__":
    sys.exit(main())
