"""Anti-Stale Evidence Rejection (DQAEIP rebuild Phase 10).

Rejects evidence when ANY binding identity differs from the run-set
expectation, and prevents accidental mixing of runs from different
release lineages (Run 1 from release A with Run 2 from release B).

Binding identities (per run record):
    git_commit, checker (script) sha256, schema hash, input sha256,
    output sha256, rule hash set, run id

Reject when:
- Git lineage differs across runs
- rule hash set differs across runs or from the pinned V1 set
- checker hash differs across runs or from the actual checker file
- schema/input/output hashes differ across runs
- run identity duplicates (same run_id twice) or missing
- required companion artifacts are missing (manifest, evidence root,
  per-run result)

Every rejection carries an explicit reason. Fail closed: missing
evidence is a rejection, never a pass.
"""

import hashlib
import os

__all__ = [
    "REQUIRED_RUN_KEYS",
    "BINDING_KEYS",
    "check_run_record",
    "check_no_mixing",
    "check_companion_artifacts",
    "evaluate_run_set",
]

REQUIRED_RUN_KEYS = (
    "run_id", "status", "git_commit", "checker_sha256",
    "schema_hash", "input_sha256", "output_sha256", "rule_hashes",
    "oracle_mismatches",
)

BINDING_KEYS = (
    "git_commit", "checker_sha256", "schema_hash", "input_sha256",
    "output_sha256", "rule_hashes",
)


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_run_record(run, index):
    """Structural check of one run record; returns problem list."""
    problems = []
    label = f"run[{index}]"
    if not isinstance(run, dict):
        return [f"{label}: not an object"]
    for key in REQUIRED_RUN_KEYS:
        if key not in run:
            problems.append(f"{label}: missing required key '{key}'")
    if run.get("status") != "PASS":
        problems.append(f"{label}: status {run.get('status')!r} is not PASS")
    if isinstance(run.get("oracle_mismatches"), int) \
            and run["oracle_mismatches"] != 0:
        problems.append(f"{label}: oracle mismatches != 0")
    rh = run.get("rule_hashes")
    if not isinstance(rh, dict) or not rh:
        problems.append(f"{label}: rule_hashes missing/empty")
    return problems


def check_no_mixing(runs):
    """Cross-run binding-identity equality; returns problem list.

    A single differing binding key means the runs come from different
    executions/lineages and MUST NOT be combined into one release.
    """
    problems = []
    if not isinstance(runs, list) or len(runs) < 2:
        return ["mixing check requires >= 2 run records"]
    for key in BINDING_KEYS:
        values = []
        for i, run in enumerate(runs):
            v = run.get(key) if isinstance(run, dict) else None
            values.append((i, v))
        distinct = {repr(v) for _, v in values}
        if len(distinct) != 1:
            problems.append(
                f"MIXED-LINEAGE: binding '{key}' differs across runs: "
                + "; ".join(f"run[{i}]={str(v)[:24]}..." for i, v in values))
    # duplicate run_id (same execution recorded twice) is also mixing
    ids = [r.get("run_id") for r in runs if isinstance(r, dict)]
    if len(set(map(str, ids))) != len(ids):
        problems.append(f"MIXED-LINEAGE: duplicate run_id values: {ids}")
    return problems


def check_companion_artifacts(repo_root, run_companions):
    """Check required companion artifacts exist; returns problem list.

    run_companions: list of dicts {"run_id": str, "required": [relpaths]}
    """
    problems = []
    for entry in run_companions:
        rid = entry.get("run_id", "<unknown>")
        for rel in entry.get("required", []):
            if not os.path.isfile(os.path.join(repo_root, rel)):
                problems.append(f"{rid}: missing companion artifact "
                                f"{rel!r}")
    return problems


def evaluate_run_set(runs, repo_root=None, expected_checker_sha=None,
                     pinned_rule_hashes=None, run_companions=None):
    """Full anti-stale evaluation of a run set.

    Returns a report dict with verdict PASS only when every check is
    clean. ``expected_checker_sha`` optionally binds the checker
    identity to the ACTUAL checker file; ``pinned_rule_hashes``
    optionally binds the rule set to the frozen V1 registry.
    """
    problems = []
    for i, run in enumerate(runs or []):
        problems.extend(check_run_record(run, i))
    if not runs:
        problems.append("no run records supplied")
    else:
        problems.extend(check_no_mixing(runs))

    if expected_checker_sha:
        for i, run in enumerate(runs):
            if run.get("checker_sha256") != expected_checker_sha:
                problems.append(
                    f"STALE CHECKER: run[{i}].checker_sha256 does not "
                    f"match the actual checker file")
    if pinned_rule_hashes:
        for i, run in enumerate(runs):
            if run.get("rule_hashes") != pinned_rule_hashes:
                problems.append(
                    f"STALE RULES: run[{i}].rule_hashes differ from the "
                    f"pinned V1 registry")
    if run_companions:
        problems.extend(check_companion_artifacts(repo_root or ".",
                                                  run_companions))
    return {
        "checks": [
            "per-run structural integrity",
            "cross-run binding identity (anti-mixing)",
            "checker identity binding",
            "pinned rule identity binding",
            "companion artifact presence",
        ],
        "problems": problems,
        "verdict": "PASS" if not problems else "REJECT",
        "verdict_note": (
            "REJECT means stale or mixed-lineage evidence; such evidence "
            "must never contribute to a PASS release verdict"
        ),
    }
