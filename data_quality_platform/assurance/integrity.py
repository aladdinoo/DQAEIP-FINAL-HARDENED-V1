"""DQAEIP FINAL UPDATE 2026-09-17 — integrity monitoring core.

Implements task-book sections 11-19 for continuous integrity monitoring,
drift detection, evidence freshness, and change-ledger recording. All
functions are pure with respect to (repo_root, snapshot) and perform no
writes except the explicitly requested change-ledger append.

Fail-closed semantics (NEVER violated):
    - a missing or unreadable baseline snapshot is NOT_VERIFIED (never PASS)
    - a malformed baseline snapshot is FAIL (tamper suspicion)
    - a critical protected artifact change (Frozen V1 / official 3M
      evidence / checker chain) is FAIL and is never downgraded
    - a missing dependency is NOT_VERIFIED; a moved dependency is STALE

Status ordering (worst wins, FAIL never downgraded):
    FAIL > NOT_VERIFIED > INVALID > STALE > WARNING > PASS
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

STATUS_ORDER = [
    "PASS", "WARNING", "STALE", "INVALID", "NOT_VERIFIED", "FAIL",
]
CRITICAL_STATUSES = {"FAIL", "NOT_VERIFIED"}

UPDATE_ID = "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18"

# current release evidence namespace (monitors read the CURRENT
# release artifacts; historical namespaces stay on disk, superseded)
RELEASE_NS = "evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18"

FROZEN_V1_SOURCE = "data_quality_platform/rules/v1_rules.py"
FROZEN_V1_EXPECTED_SHA256 = (
    "daef1ded54c7d3c79898a1ba253be2acd5b6120e18b16b09009fdd7be9fc2276")
OFFICIAL_EVIDENCE_DIR = "evidence/validation/2026-09-19/fresh_3m2"
OFFICIAL_CHECKER = "scripts/final_3m_validation.py"
OFFICIAL_VERIFIER = "scripts/verify_run_pair.py"
OFFICIAL_INPUT_SHA256 = (
    "59624a53c72f908f1dde673ceecf59e0662ae721bb8f9af7e165acba5318d153")
OFFICIAL_OUTPUT_SHA256 = (
    "b72adc235160a86e0b99a08f988dd0bb5f2cff82bbe5b5d28ea07c5a5719329a")

RUN3_PATTERN = re.compile(r"run[_\-]?3(?![0-9])", re.IGNORECASE)


class IntegritySnapshotError(Exception):
    """Raised when the baseline snapshot is missing or malformed."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status  # NOT_VERIFIED (missing/unreadable) or FAIL


def worst_status(statuses: Iterable[str]) -> str:
    """Return the worst status present (FAIL is never downgraded)."""
    present = [s for s in statuses if s in STATUS_ORDER]
    if not present:
        return "NOT_VERIFIED"
    return max(present, key=lambda s: STATUS_ORDER.index(s))


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def directory_fingerprint(path: str) -> Optional[str]:
    """Deterministic fingerprint over a directory tree: sorted
    (relative path, sha256) pairs for every file (pyc/cache excluded).
    Returns None when the directory does not exist."""
    if not os.path.isdir(path):
        return None
    h = hashlib.sha256()
    entries = []
    for root, dirs, files in os.walk(path):
        dirs[:] = sorted(d for d in dirs
                         if d not in ("__pycache__", ".pytest_cache"))
        for fn in sorted(files):
            if fn.endswith((".pyc", ".pyo")):
                continue
            abs_p = os.path.join(root, fn)
            entries.append((os.path.relpath(
                abs_p, path).replace(os.sep, "/"), sha256_file(abs_p)))
    for rel, sha in sorted(entries):
        h.update(rel.encode("utf-8") + b"\x00" + sha.encode("utf-8"))
    return h.hexdigest()


def dependency_fingerprint(dependencies: List[Dict[str, str]]) -> str:
    """Deterministic fingerprint over stable dependency identities only.

    Timestamps, durations and machine-local paths never participate
    (task-book section 11). Input: list of {"path","sha256"} dicts.
    """
    pairs = sorted((d["path"], d["sha256"]) for d in dependencies)
    h = hashlib.sha256()
    for path, sha in pairs:
        h.update(path.encode("utf-8") + b"\x00" + sha.encode("utf-8"))
    return h.hexdigest()


# ---------------------------------------------------------------------
# Baseline snapshot (task-book section 15)
# ---------------------------------------------------------------------

def build_snapshot_protected_hashes(repo_root: str) -> Dict[str, str]:
    """Hash every file under the authoritative inventory paths."""
    protected_dirs = [
        "data_quality_platform/rules",
        OFFICIAL_EVIDENCE_DIR,
    ]
    protected_files = [
        FROZEN_V1_SOURCE,
        OFFICIAL_CHECKER,
        OFFICIAL_VERIFIER,
        "data_quality_platform/contracts.py",
        "data_quality_platform/validation/engine.py",
        "data_quality_platform/generation/synthetic.py",
    ]
    hashes: Dict[str, str] = {}
    for rel in protected_files:
        abs_p = os.path.join(repo_root, rel)
        if os.path.isfile(abs_p):
            hashes[rel] = sha256_file(abs_p)
    for d in protected_dirs:
        base = os.path.join(repo_root, d)
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for fn in sorted(files):
                if fn.endswith(".pyc"):
                    continue
                abs_p = os.path.join(root, fn)
                rel = os.path.relpath(abs_p, repo_root).replace(os.sep, "/")
                hashes[rel] = sha256_file(abs_p)
    return hashes


def load_snapshot(path: str) -> Dict[str, Any]:
    """Load the baseline snapshot fail-closed."""
    if not os.path.isfile(path):
        raise IntegritySnapshotError(
            "NOT_VERIFIED",
            f"baseline snapshot missing: {path} — integrity state cannot "
            f"be established; NEVER defaults to PASS")
    try:
        with open(path, encoding="utf-8") as f:
            snap = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegritySnapshotError(
            "FAIL", f"baseline snapshot unreadable/corrupt: {exc}") from exc
    required = ("snapshot_version", "update_id",
                "protected_artifact_hashes")
    for key in required:
        if key not in snap:
            raise IntegritySnapshotError(
                "FAIL",
                f"baseline snapshot malformed: missing '{key}'")
    return snap


# ---------------------------------------------------------------------
# Monitor results
# ---------------------------------------------------------------------

@dataclass
class MonitorResult:
    monitor: str
    status: str
    findings: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "monitor": self.monitor,
            "status": self.status,
            "findings": self.findings,
            "details": self.details,
        }


def _scan_protected(repo_root: str, snapshot: Dict[str, Any]
                    ) -> Tuple[Dict[str, str], Dict[str, str],
                               List[str], List[str]]:
    """Walk protected paths; return (current hashes, modes, deleted, new).

    current hashes: path -> sha256 for existing protected artifacts
    modes: path -> octal mode for existing protected artifacts
    deleted: protected paths missing on disk
    new: files present in protected dirs that the snapshot does not know
    """
    protected = dict(snapshot.get("protected_artifact_hashes", {}))
    protected_dirs = list(snapshot.get("protected_directories", []))
    current: Dict[str, str] = {}
    modes: Dict[str, str] = {}
    deleted: List[str] = []
    new: List[str] = []

    for rel in sorted(protected):
        abs_p = os.path.join(repo_root, rel)
        if os.path.isfile(abs_p):
            current[rel] = sha256_file(abs_p)
            modes[rel] = oct(os.stat(abs_p).st_mode & 0o777)
        else:
            deleted.append(rel)

    for d in protected_dirs:
        base = os.path.join(repo_root, d)
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for fn in sorted(files):
                if fn.endswith(".pyc"):
                    continue
                rel = os.path.relpath(
                    os.path.join(root, fn), repo_root).replace(os.sep, "/")
                if rel not in protected:
                    new.append(rel)
    return current, modes, deleted, new


# ---------------------------------------------------------------------
# Monitors A-T (task-book section 13)
# ---------------------------------------------------------------------

def _changed(current: Dict[str, str],
             snapshot_hashes: Dict[str, str]) -> List[str]:
    return sorted(
        rel for rel, sha in snapshot_hashes.items()
        if rel in current and current[rel] != sha)


def monitor_A_content_changes(current: Dict[str, str],
                              snapshot: Dict[str, Any]) -> MonitorResult:
    """A. content changes on protected artifacts."""
    snap_hashes = snapshot.get("protected_artifact_hashes", {})
    changed = _changed(current, snap_hashes)
    critical = [r for r in changed if _is_critical_artifact(r)]
    status = "FAIL" if changed else "PASS"
    if critical:
        status = "FAIL"
    elif changed and not critical:
        status = "FAIL"  # all protected artifacts are authoritative
    return MonitorResult(
        "A_content_changes", status,
        [f"protected artifact content changed: {r}" for r in changed],
        {"changed": changed, "critical": critical})


def _is_critical_artifact(rel: str) -> bool:
    return (rel == FROZEN_V1_SOURCE
            or rel.startswith(OFFICIAL_EVIDENCE_DIR + "/")
            or rel in (OFFICIAL_CHECKER, OFFICIAL_VERIFIER))


def monitor_B_deletion(deleted: List[str]) -> MonitorResult:
    """B. deletion of protected artifacts."""
    critical = [r for r in deleted if _is_critical_artifact(r)]
    status = "FAIL" if deleted else "PASS"
    return MonitorResult(
        "B_deletion", status,
        [f"protected artifact deleted: {r}" for r in deleted],
        {"deleted": deleted, "critical": critical})


def monitor_C_unexpected_creation(new: List[str],
                                  snapshot: Dict[str, Any]) -> MonitorResult:
    """C. unexpected creation inside protected directories."""
    official_new = [r for r in new
                    if r.startswith(OFFICIAL_EVIDENCE_DIR + "/")]
    status = "FAIL" if official_new else ("WARNING" if new else "PASS")
    return MonitorResult(
        "C_unexpected_creation", status,
        [f"unexpected file in protected dir: {r}" for r in new],
        {"new": new,
         "official_evidence_dir_new": official_new,
         "note": ("new files inside the official 3M evidence directory "
                  "are FAIL (possible Run 3 / injection); new files "
                  "elsewhere are WARNING pending review")})


def monitor_D_rename(deleted: List[str], new: List[str],
                     current: Dict[str, str]) -> MonitorResult:
    """D. rename (protected path gone, same bytes present elsewhere)."""
    renames = []
    for gone in deleted:
        # look for an unknown new file with the same content hash is not
        # possible without hashing new files; approximate by name match
        base = os.path.basename(gone)
        for candidate in new:
            if os.path.basename(candidate) == base:
                renames.append({"from": gone, "to": candidate})
    status = "FAIL" if renames else ("FAIL" if deleted else "PASS")
    return MonitorResult(
        "D_rename", status,
        [f"protected artifact renamed: {r['from']} -> {r['to']}"
         for r in renames],
        {"renames": renames})


def monitor_E_sha_changes(current: Dict[str, str],
                          snapshot: Dict[str, Any]) -> MonitorResult:
    """E. SHA-256 changes (per-artifact detail view of A)."""
    snap_hashes = snapshot.get("protected_artifact_hashes", {})
    changed = _changed(current, snap_hashes)
    return MonitorResult(
        "E_sha_changes", "FAIL" if changed else "PASS",
        [f"sha256 changed: {r}" for r in changed],
        {"changed": {r: {
            "expected": snap_hashes[r],
            "actual": current.get(r)} for r in changed}})


def monitor_F_permission_changes(
        current: Dict[str, str], modes: Dict[str, str],
        snapshot: Dict[str, Any]) -> MonitorResult:
    """F. permission changes (executable bit only; group-write storage
    noise is recorded but not a failure)."""
    snap_modes = snapshot.get("protected_artifact_modes", {})
    changed = []
    for rel, mode in modes.items():
        expected = snap_modes.get(rel)
        if expected is None:
            continue
        exec_expected = expected.endswith(("5", "7"))
        exec_actual = mode.endswith(("5", "7"))
        if exec_expected != exec_actual:
            changed.append({"artifact": rel, "expected": expected,
                            "actual": mode, "kind": "exec-bit"})
    return MonitorResult(
        "F_permission_changes", "FAIL" if changed else "PASS",
        [f"permission change: {c['artifact']} "
         f"{c['expected']} -> {c['actual']}" for c in changed],
        {"changes": changed,
         "note": ("only the executable bit is monitored; group-write "
                  "storage-layer noise is recorded, not failed")})


def monitor_G_dependency_changes(
        repo_root: str, snapshot: Dict[str, Any]) -> MonitorResult:
    """G. dependency-graph fingerprint changes."""
    expected_fp = snapshot.get("expected_dependency_graph_fingerprint")
    if not expected_fp:
        return MonitorResult(
            "G_dependency_changes", "NOT_VERIFIED",
            ["dependency graph fingerprint not present in snapshot"],
            {})
    path = os.path.join(repo_root, RELEASE_NS,
                        "dependency_graph", "dependency_graph.json")
    if not os.path.isfile(path):
        return MonitorResult(
            "G_dependency_changes", "NOT_VERIFIED",
            ["dependency graph artifact missing"], {})
    try:
        graph = json.load(open(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return MonitorResult(
            "G_dependency_changes", "FAIL",
            [f"dependency graph unreadable: {exc}"], {})
    actual_fp = graph.get("graph_fingerprint")
    if actual_fp != expected_fp:
        return MonitorResult(
            "G_dependency_changes", "FAIL",
            ["dependency graph fingerprint changed"],
            {"expected": expected_fp, "actual": actual_fp})
    return MonitorResult("G_dependency_changes", "PASS", [], {})


def monitor_H_stale_evidence(repo_root: str) -> MonitorResult:
    """H. stale evidence (freshness engine results)."""
    path = os.path.join(repo_root, RELEASE_NS,
                        "freshness", "freshness_report.json")
    if not os.path.isfile(path):
        return MonitorResult(
            "H_stale_evidence", "NOT_VERIFIED",
            ["freshness report missing"], {})
    try:
        report = json.load(open(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return MonitorResult(
            "H_stale_evidence", "FAIL",
            [f"freshness report unreadable: {exc}"], {})
    artifacts = report.get("artifacts", {})
    stale = [a for a, v in artifacts.items()
             if isinstance(v, dict) and v.get("state") == "STALE"]
    not_verified = [a for a, v in artifacts.items()
                    if isinstance(v, dict)
                    and v.get("state") == "NOT_VERIFIED"]
    invalid = [a for a, v in artifacts.items()
               if isinstance(v, dict) and v.get("state") == "INVALID"]
    status = ("FAIL" if invalid else
              "STALE" if stale else
              "NOT_VERIFIED" if not_verified else "PASS")
    return MonitorResult(
        "H_stale_evidence", status,
        [f"stale evidence: {a}" for a in stale]
        + [f"not-verified evidence: {a}" for a in not_verified]
        + [f"invalid evidence: {a}" for a in invalid],
        {"stale": stale, "not_verified": not_verified,
         "invalid": invalid})


def monitor_I_manifest_changes(repo_root: str,
                               snapshot: Dict[str, Any]) -> MonitorResult:
    """I. release-manifest changes."""
    return _sha_vs_snapshot(
        repo_root, snapshot, "I_manifest_changes",
        "release_manifest_path", "release_manifest_sha256")


def monitor_J_provenance_changes(repo_root: str,
                                snapshot: Dict[str, Any]) -> MonitorResult:
    """J. provenance (claims) changes."""
    return _sha_vs_snapshot(
        repo_root, snapshot, "J_provenance_changes",
        "provenance_path", "provenance_sha256")


def _sha_vs_snapshot(repo_root, snapshot, monitor, path_key, sha_key):
    rel = snapshot.get(path_key)
    expected = snapshot.get(sha_key)
    if not rel or not expected:
        return MonitorResult(monitor, "NOT_VERIFIED",
                             [f"{path_key} not pinned in snapshot"], {})
    abs_p = os.path.join(repo_root, rel)
    if not os.path.isfile(abs_p):
        return MonitorResult(
            monitor, "FAIL", [f"{rel} missing"], {})
    actual = sha256_file(abs_p)
    if actual != expected:
        return MonitorResult(
            monitor, "FAIL", [f"{rel} changed"],
            {"expected": expected, "actual": actual})
    return MonitorResult(monitor, "PASS", [], {"artifact": rel})


def monitor_K_release_identity(repo_root: str,
                               snapshot: Dict[str, Any]) -> MonitorResult:
    """K. release identity changes."""
    expected = snapshot.get("expected_release_identity", {})
    fr_path = snapshot.get(
        "final_results_path",
        f"{RELEASE_NS}/final_results/"
        "FINAL_RESULTS_PORTABLE_2026-09-18.json")
    abs_p = os.path.join(repo_root, fr_path)
    if not os.path.isfile(abs_p):
        return MonitorResult(
            "K_release_identity", "NOT_VERIFIED",
            ["FINAL_RESULTS missing; release identity unverifiable"], {})
    try:
        fr = json.load(open(abs_p, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return MonitorResult(
            "K_release_identity", "FAIL",
            ["FINAL_RESULTS unreadable; release identity unverifiable"], {})
    actual = (fr.get("release_identity") or {}).get("release_id")
    want = expected.get("release_id")
    if want and actual != want:
        return MonitorResult(
            "K_release_identity", "FAIL",
            ["release identity changed"],
            {"expected": want, "actual": actual})
    return MonitorResult("K_release_identity", "PASS", [],
                          {"release_id": actual})


def monitor_L_final_results(repo_root: str,
                            snapshot: Dict[str, Any]) -> MonitorResult:
    """L. FINAL_RESULTS changes."""
    return _sha_vs_snapshot(
        repo_root, snapshot, "L_final_results",
        "final_results_path", "final_results_sha256")


def monitor_M_readme_metrics(repo_root: str,
                            snapshot: Dict[str, Any]) -> MonitorResult:
    """M. README metric changes (hash + consistency verdict)."""
    res = _sha_vs_snapshot(
        repo_root, snapshot, "M_readme_metrics",
        "readme_path", "readme_sha256")
    if res.status != "PASS":
        return res
    consistency = snapshot.get("readme_consistency_path")
    if consistency:
        abs_c = os.path.join(repo_root, consistency)
        if not os.path.isfile(abs_c):
            res.status = "NOT_VERIFIED"
            res.findings.append("README consistency report missing")
        else:
            try:
                verdict = json.load(open(abs_c, encoding="utf-8"))
                if verdict.get("verdict") not in (None, "CONSISTENT"):
                    res.status = "FAIL"
                    res.findings.append(
                        "README consistency verdict: "
                        f"{verdict.get('verdict')}")
            except (OSError, json.JSONDecodeError):
                res.status = "FAIL"
                res.findings.append("README consistency report unreadable")
    return res


def monitor_N_frozen_v1(current: Dict[str, str],
                        snapshot: Dict[str, Any]) -> MonitorResult:
    """N. Frozen V1 changes (critical anchor; snapshot pin first,
    immutable module anchor as fallback — both pin the same value in
    production)."""
    expected = (snapshot.get("expected_evidence_identity", {}).get(
        "frozen_v1_sha256") or FROZEN_V1_EXPECTED_SHA256)
    actual = current.get(FROZEN_V1_SOURCE)
    if actual is None:
        return MonitorResult(
            "N_frozen_v1", "FAIL",
            [f"{FROZEN_V1_SOURCE} missing"], {})
    if actual != expected:
        return MonitorResult(
            "N_frozen_v1", "FAIL",
            ["Frozen V1 source hash differs from the immutable anchor"],
            {"expected": expected, "actual": actual})
    return MonitorResult("N_frozen_v1", "PASS", [],
                         {"sha256": actual})


def monitor_O_official_3m(current: Dict[str, str],
                          snapshot: Dict[str, Any]) -> MonitorResult:
    """O. official 3M evidence changes (critical anchor)."""
    snap_hashes = snapshot.get("protected_artifact_hashes", {})
    official = {r: s for r, s in snap_hashes.items()
                if r.startswith(OFFICIAL_EVIDENCE_DIR + "/")}
    missing = [r for r in official if r not in current]
    changed = [r for r, s in official.items()
               if r in current and current[r] != s]
    findings = [f"official evidence missing: {r}" for r in missing]
    findings += [f"official evidence changed: {r}" for r in changed]
    return MonitorResult(
        "O_official_3m_evidence", "FAIL" if (missing or changed) else "PASS",
        findings, {"missing": missing, "changed": changed})


def monitor_P_checker(current: Dict[str, str],
                      snapshot: Dict[str, Any]) -> MonitorResult:
    """P. checker changes (critical anchor)."""
    snap_hashes = snapshot.get("protected_artifact_hashes", {})
    problems = []
    for rel in (OFFICIAL_CHECKER, OFFICIAL_VERIFIER):
        expected = snap_hashes.get(rel)
        actual = current.get(rel)
        if expected is None or actual is None:
            problems.append(f"{rel}: not pinned/present")
        elif expected != actual:
            problems.append(f"{rel}: checker chain hash changed")
    return MonitorResult(
        "P_checker", "FAIL" if problems else "PASS", problems, {})


def monitor_Q_run3(repo_root: str) -> MonitorResult:
    """Q. Run 3 appearance (forbidden third run)."""
    findings = []
    evidence_base = os.path.join(repo_root, "evidence")
    for root, dirs, files in os.walk(evidence_base):
        dirs[:] = [d for d in dirs if d not in ("__pycache__",)]
        for name in dirs + files:
            if RUN3_PATTERN.search(name):
                rel = os.path.relpath(os.path.join(root, name),
                                      repo_root).replace(os.sep, "/")
                # historical/superseded records may mention run 3 only in
                # prose; file/dir NAMES matching run3 are suspicious
                findings.append(rel)
    if findings:
        return MonitorResult(
            "Q_run3_appearance", "FAIL",
            [f"possible Run 3 artifact: {f}" for f in findings],
            {"matches": findings})
    return MonitorResult("Q_run3_appearance", "PASS", [], {})


def monitor_R_duplicate_identity(repo_root: str) -> MonitorResult:
    """R. duplicate artifact identity (logical role, not identical
    bytes; two legitimate files MAY share bytes)."""
    path = os.path.join(repo_root, RELEASE_NS,
                        "release_manifest", "release_manifest.json")
    if not os.path.isfile(path):
        return MonitorResult(
            "R_duplicate_identity", "NOT_VERIFIED",
            ["release manifest missing; duplicate check not possible"],
            {})
    try:
        manifest = json.load(open(path, encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return MonitorResult(
            "R_duplicate_identity", "FAIL",
            [f"release manifest unreadable: {exc}"], {})
    if not isinstance(manifest, dict):
        return MonitorResult(
            "R_duplicate_identity", "FAIL",
            ["release manifest is not a JSON object"], {})
    entries = manifest.get("files") or manifest.get("artifacts") or []
    by_identity: Dict[str, List[str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ident = (entry.get("artifact_identity") or entry.get("role")
                 or entry.get("path"))
        if ident:
            by_identity.setdefault(str(ident), []).append(
                entry.get("path", "?"))
    dupes = {k: v for k, v in by_identity.items() if len(v) > 1}
    return MonitorResult(
        "R_duplicate_identity", "FAIL" if dupes else "PASS",
        [f"duplicate artifact identity '{k}': {v}"
         for k, v in dupes.items()],
        {"duplicates": dupes,
         "note": ("identity = logical role/path, never raw bytes; "
                  "legitimate byte-identical files are not rejected")})


def monitor_S_unauthorized_artifacts(repo_root: str) -> MonitorResult:
    """S. unauthorized artifacts (untracked files inside protected
    namespaces; tracked status judged via the classification policy)."""
    findings = []
    for d in (OFFICIAL_EVIDENCE_DIR, "data_quality_platform/rules"):
        base = os.path.join(repo_root, d)
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for fn in files:
                rel = os.path.relpath(os.path.join(root, fn),
                                      repo_root).replace(os.sep, "/")
                if fn.endswith((".pyc", ".jsonl")):
                    findings.append(f"{rel}: forbidden extension in "
                                    f"protected dir")
    if findings:
        return MonitorResult(
            "S_unauthorized_artifacts", "FAIL", findings,
            {"artifacts": findings})
    return MonitorResult("S_unauthorized_artifacts", "PASS", [], {})


def monitor_T_malformed_manifests(repo_root: str) -> MonitorResult:
    """T. malformed manifests (key release-facing JSON must parse and
    carry required identity fields)."""
    candidates = [
        ("FINAL_RESULTS.json", ("final_release_status", "runs")),
        ("release_manifest.json", ()),
        (f"{RELEASE_NS}/release_manifest/"
         "release_manifest.json", ()),
        (f"{RELEASE_NS}/release_manifest/"
         "release_lock.json", ("release_id",)),
        ("evidence/release/release_evidence_model.json", ()),
    ]
    findings = []
    for rel, required_keys in candidates:
        abs_p = os.path.join(repo_root, rel)
        if not os.path.isfile(abs_p):
            continue  # absence is other monitors' concern
        try:
            doc = json.load(open(abs_p, encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(f"{rel}: malformed JSON ({exc})")
            continue
        if not isinstance(doc, dict):
            findings.append(f"{rel}: manifest is not a JSON object")
            continue
        for key in required_keys:
            if key not in doc:
                findings.append(f"{rel}: missing required field '{key}'")
    return MonitorResult(
        "T_malformed_manifests", "FAIL" if findings else "PASS",
        findings, {"checked": [c[0] for c in candidates]})


ALL_MONITORS = [
    "A_content_changes", "B_deletion", "C_unexpected_creation",
    "D_rename", "E_sha_changes", "F_permission_changes",
    "G_dependency_changes", "H_stale_evidence", "I_manifest_changes",
    "J_provenance_changes", "K_release_identity", "L_final_results",
    "M_readme_metrics", "N_frozen_v1", "O_official_3m_evidence",
    "P_checker", "Q_run3_appearance", "R_duplicate_identity",
    "S_unauthorized_artifacts", "T_malformed_manifests",
]


def run_all_monitors(repo_root: str,
                     snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Run monitors A-T; aggregate worst status; FAIL never downgraded."""
    current, modes, deleted, new = _scan_protected(repo_root, snapshot)
    results = [
        monitor_A_content_changes(current, snapshot),
        monitor_B_deletion(deleted),
        monitor_C_unexpected_creation(new, snapshot),
        monitor_D_rename(deleted, new, current),
        monitor_E_sha_changes(current, snapshot),
        monitor_F_permission_changes(current, modes, snapshot),
        monitor_G_dependency_changes(repo_root, snapshot),
        monitor_H_stale_evidence(repo_root),
        monitor_I_manifest_changes(repo_root, snapshot),
        monitor_J_provenance_changes(repo_root, snapshot),
        monitor_K_release_identity(repo_root, snapshot),
        monitor_L_final_results(repo_root, snapshot),
        monitor_M_readme_metrics(repo_root, snapshot),
        monitor_N_frozen_v1(current, snapshot),
        monitor_O_official_3m(current, snapshot),
        monitor_P_checker(current, snapshot),
        monitor_Q_run3(repo_root),
        monitor_R_duplicate_identity(repo_root),
        monitor_S_unauthorized_artifacts(repo_root),
        monitor_T_malformed_manifests(repo_root),
    ]
    overall = worst_status(r.status for r in results)
    return {
        "update_id": UPDATE_ID,
        "monitor_count": len(results),
        "monitors": {r.monitor: r.status for r in results},
        "results": [r.as_dict() for r in results],
        "overall_status": overall,
        "fail_closed_statement": (
            "FAIL is never downgraded; a missing snapshot is "
            "NOT_VERIFIED, never PASS"),
    }


# ---------------------------------------------------------------------
# Drift detection (task-book section 16)
# ---------------------------------------------------------------------

@dataclass
class DriftFinding:
    drift_type: str
    severity: str          # REVIEW | CRITICAL
    source: str
    expected: Any
    actual: Any
    affected_artifacts: List[str]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "drift_type": self.drift_type,
            "severity": self.severity,
            "source": self.source,
            "expected_value": self.expected,
            "actual_value": self.actual,
            "affected_artifacts": self.affected_artifacts,
        }


def detect_content_drift(repo_root: str, snapshot: Dict[str, Any]
                         ) -> List[DriftFinding]:
    current, _, deleted, _ = _scan_protected(repo_root, snapshot)
    snap_hashes = snapshot.get("protected_artifact_hashes", {})
    changed = _changed(current, snap_hashes)
    findings = []
    for rel in changed:
        findings.append(DriftFinding(
            "CONTENT_DRIFT", "CRITICAL", rel, snap_hashes[rel],
            current.get(rel),
            _dependents_of(rel, snapshot)))
    for rel in deleted:
        findings.append(DriftFinding(
            "CONTENT_DRIFT", "CRITICAL", rel, snap_hashes.get(rel),
            None, _dependents_of(rel, snapshot)))
    return findings


def _dependents_of(rel: str, snapshot: Dict[str, Any]) -> List[str]:
    graph = snapshot.get("dependency_dependents", {})
    return list(graph.get(rel, []))


def detect_rule_drift(repo_root: str) -> List[DriftFinding]:
    """RULE DRIFT: registry must expose exactly the 8 frozen V1 rules."""
    findings = []
    import sys
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    try:
        from data_quality_platform.rules.registry import RuleRegistry
        registry = RuleRegistry.create_default()
        ids = sorted(r.rule_id for r in registry.get_all_rules())
    except Exception as exc:  # noqa: BLE001 — any import failure is drift
        return [DriftFinding("RULE_DRIFT", "CRITICAL",
                             "data_quality_platform/rules/registry.py",
                             "importable registry", f"import failure: {exc}",
                             ["FINAL_RESULTS", "README"])]
    expected_ids = sorted([
        "first_name_cleaning_candidate",
        "last_name_cleaning_candidate",
        "name_cleaning_candidate",
        "email_blank",
        "email_syntax_failure",
        "proposed_email_export_eligible",
        "zip_state_assessable",
        "geography_mismatch_candidate",
    ])
    if ids != expected_ids:
        findings.append(DriftFinding(
            "RULE_DRIFT", "CRITICAL",
            "data_quality_platform/rules/registry.py", expected_ids, ids,
            ["FINAL_RESULTS", "README", "release_manifest"]))
    v1_path = os.path.join(repo_root, FROZEN_V1_SOURCE)
    if os.path.isfile(v1_path):
        actual_sha = sha256_file(v1_path)
        if actual_sha != FROZEN_V1_EXPECTED_SHA256:
            findings.append(DriftFinding(
                "RULE_DRIFT", "CRITICAL", FROZEN_V1_SOURCE,
                FROZEN_V1_EXPECTED_SHA256, actual_sha,
                ["FINAL_RESULTS", "README"]))
    return findings


def detect_schema_drift(repo_root: str) -> List[DriftFinding]:
    """SCHEMA DRIFT: 33 input columns / 8 flags / 41 output columns."""
    import sys
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    try:
        from data_quality_platform.contracts import (
            SOURCE_COLUMNS, FLAG_COLUMNS, TOTAL_OUTPUT_COLUMNS)
        actual = (len(SOURCE_COLUMNS), len(FLAG_COLUMNS),
                  TOTAL_OUTPUT_COLUMNS)
    except Exception as exc:  # noqa: BLE001
        return [DriftFinding(
            "SCHEMA_DRIFT", "CRITICAL", "data_quality_platform/contracts.py",
            "(33, 8, 41)", f"import failure: {exc}",
            ["FINAL_RESULTS", "README"])]
    expected = (33, 8, 41)
    if actual != expected:
        return [DriftFinding(
            "SCHEMA_DRIFT", "CRITICAL",
            "data_quality_platform/contracts.py", expected, actual,
            ["FINAL_RESULTS", "README", "release_manifest"])]
    return []


def detect_evidence_drift(repo_root: str, snapshot: Dict[str, Any]
                          ) -> List[DriftFinding]:
    """EVIDENCE DRIFT: official run-pair evidence changes."""
    current, _, deleted, _ = _scan_protected(repo_root, snapshot)
    snap_hashes = snapshot.get("protected_artifact_hashes", {})
    official = {r: s for r, s in snap_hashes.items()
                if r.startswith(OFFICIAL_EVIDENCE_DIR + "/")}
    findings = []
    for rel, expected_sha in official.items():
        if rel in deleted:
            findings.append(DriftFinding(
                "EVIDENCE_DRIFT", "CRITICAL", rel, expected_sha, None,
                _dependents_of(rel, snapshot)))
        elif current.get(rel) != expected_sha:
            findings.append(DriftFinding(
                "EVIDENCE_DRIFT", "CRITICAL", rel, expected_sha,
                current.get(rel), _dependents_of(rel, snapshot)))
    # recorded input/output anchors must still be present in the
    # official FINAL_RESULTS
    fr_path = os.path.join(repo_root, OFFICIAL_EVIDENCE_DIR,
                           "FINAL_RESULTS.json")
    if os.path.isfile(fr_path):
        try:
            fr = json.load(open(fr_path, encoding="utf-8"))
            if fr.get("input_sha256") != OFFICIAL_INPUT_SHA256:
                findings.append(DriftFinding(
                    "EVIDENCE_DRIFT", "CRITICAL",
                    OFFICIAL_EVIDENCE_DIR + "/FINAL_RESULTS.json",
                    OFFICIAL_INPUT_SHA256, fr.get("input_sha256"),
                    ["FINAL_RESULTS"]))
            if fr.get("output_sha256") != OFFICIAL_OUTPUT_SHA256:
                findings.append(DriftFinding(
                    "EVIDENCE_DRIFT", "CRITICAL",
                    OFFICIAL_EVIDENCE_DIR + "/FINAL_RESULTS.json",
                    OFFICIAL_OUTPUT_SHA256, fr.get("output_sha256"),
                    ["FINAL_RESULTS"]))
        except (OSError, json.JSONDecodeError):
            findings.append(DriftFinding(
                "EVIDENCE_DRIFT", "CRITICAL",
                OFFICIAL_EVIDENCE_DIR + "/FINAL_RESULTS.json",
                "parseable JSON", "unreadable", ["FINAL_RESULTS"]))
    return findings


def detect_provenance_drift(repo_root: str, snapshot: Dict[str, Any]
                            ) -> List[DriftFinding]:
    """PROVENANCE DRIFT: claims / dependency chain changed."""
    rel = snapshot.get("provenance_path")
    expected = snapshot.get("provenance_sha256")
    if not rel or not expected:
        return [DriftFinding(
            "PROVENANCE_DRIFT", "REVIEW", "snapshot",
            "provenance pinned", "not pinned", [])]
    abs_p = os.path.join(repo_root, rel)
    if not os.path.isfile(abs_p):
        return [DriftFinding(
            "PROVENANCE_DRIFT", "CRITICAL", rel, expected, "missing", [])]
    actual = sha256_file(abs_p)
    if actual != expected:
        return [DriftFinding(
            "PROVENANCE_DRIFT", "REVIEW", rel, expected, actual,
            ["README", "observability"])]
    return []


def detect_configuration_drift(repo_root: str, snapshot: Dict[str, Any]
                              ) -> List[DriftFinding]:
    """CONFIGURATION DRIFT: python version, pyproject, configs."""
    findings = []
    import platform
    expected_py = snapshot.get("configuration_baseline", {}).get(
        "python_version")
    actual_py = platform.python_version()
    if expected_py and actual_py != expected_py:
        findings.append(DriftFinding(
            "CONFIGURATION_DRIFT", "REVIEW", "python interpreter",
            expected_py, actual_py,
            ["all derived evidence (mark STALE if material)"]))
    for rel in ("pyproject.toml", "configs/quality.yaml"):
        abs_p = os.path.join(repo_root, rel)
        expected_sha = snapshot.get("configuration_baseline", {}).get(
            "config_hashes", {}).get(rel)
        if not os.path.isfile(abs_p) or not expected_sha:
            continue
        actual_sha = sha256_file(abs_p)
        if actual_sha != expected_sha:
            findings.append(DriftFinding(
                "CONFIGURATION_DRIFT", "REVIEW", rel, expected_sha,
                actual_sha, ["affected evidence marked STALE"]))
    return findings


def detect_dependency_drift(repo_root: str, snapshot: Dict[str, Any]
                            ) -> List[DriftFinding]:
    """DEPENDENCY DRIFT: installed packages vs declared requirements."""
    findings = []
    declared = snapshot.get("configuration_baseline", {}).get(
        "installed_packages", {})
    if not declared:
        return [DriftFinding(
            "DEPENDENCY_DRIFT", "REVIEW", "snapshot",
            "package baseline pinned", "not pinned", [])]
    import importlib.metadata as md
    actual = {}
    for dist in md.distributions():
        name = (dist.metadata.get("Name") or "").lower()
        if name:
            actual[name] = dist.version
    changed = sorted(
        n for n in declared
        if n in actual and actual[n] != declared[n])
    missing = sorted(n for n in declared if n not in actual)
    for n in changed:
        findings.append(DriftFinding(
            "DEPENDENCY_DRIFT", "REVIEW", f"package {n}", declared[n],
            actual[n], ["reproducibility (mark NOT_VERIFIED if material)"]))
    for n in missing:
        findings.append(DriftFinding(
            "DEPENDENCY_DRIFT", "REVIEW", f"package {n}", declared[n],
            "not installed", ["reproducibility"]))
    return findings


def detect_release_drift(repo_root: str, snapshot: Dict[str, Any]
                         ) -> List[DriftFinding]:
    """RELEASE DRIFT: release identity / manifest / lock changed."""
    findings = []
    expected_release = snapshot.get("expected_release_identity", {})
    lock_rel = snapshot.get("release_lock_path")
    if lock_rel:
        lock_abs = os.path.join(repo_root, lock_rel)
        expected_lock_sha = snapshot.get("release_lock_sha256")
        if os.path.isfile(lock_abs) and expected_lock_sha:
            actual = sha256_file(lock_abs)
            if actual != expected_lock_sha:
                findings.append(DriftFinding(
                    "RELEASE_DRIFT", "CRITICAL", lock_rel,
                    expected_lock_sha, actual,
                    ["release ZIP (INVALIDATED)"]))
                return findings
    fr_path = os.path.join(repo_root, snapshot.get(
        "final_results_path",
        f"{RELEASE_NS}/final_results/"
        "FINAL_RESULTS_PORTABLE_2026-09-18.json"))
    if os.path.isfile(fr_path):
        try:
            fr = json.load(open(fr_path, encoding="utf-8"))
            rid = (fr.get("release_identity") or {}).get("release_id")
            want = expected_release.get("release_id")
            if want and rid != want:
                findings.append(DriftFinding(
                    "RELEASE_DRIFT", "CRITICAL", "FINAL_RESULTS release_id",
                    want, rid, ["README", "release_manifest"]))
        except (OSError, json.JSONDecodeError):
            findings.append(DriftFinding(
                "RELEASE_DRIFT", "CRITICAL", "FINAL_RESULTS",
                "parseable", "unreadable", ["README"]))
    return findings


def detect_documentation_drift(repo_root: str) -> List[DriftFinding]:
    """DOCUMENTATION DRIFT: README metric claims vs FINAL_RESULTS."""
    findings = []
    readme = os.path.join(repo_root, "README.md")
    fr_path = os.path.join(repo_root, "FINAL_RESULTS.json")
    if not (os.path.isfile(readme) and os.path.isfile(fr_path)):
        return [DriftFinding(
            "DOCUMENTATION_DRIFT", "REVIEW", "README.md / FINAL_RESULTS.json",
            "both present", "one missing", ["README"])]
    text = open(readme, encoding="utf-8").read()
    forbidden_claims = [
        ("real rows", "3,200,000 real rows"),
        ("production ready", "production ready"),
        ("bounded memory", "bounded memory"),
    ]
    for marker, claim in forbidden_claims:
        if marker in text.lower():
            findings.append(DriftFinding(
                "DOCUMENTATION_DRIFT", "CRITICAL", "README.md",
                f"no unsupported claim '{claim}'",
                f"claim present: '{claim}'", ["README"]))
    return findings


def detect_test_baseline_drift(repo_root: str, snapshot: Dict[str, Any]
                               ) -> List[DriftFinding]:
    """TEST-BASELINE DRIFT: counts vs previous verified baseline."""
    baseline = snapshot.get("test_baseline", {})
    if not baseline:
        return [DriftFinding(
            "TEST_BASELINE_DRIFT", "REVIEW", "snapshot",
            "test baseline pinned", "not pinned", ["test health"])]
    summary_rel = snapshot.get("test_summary_path",
                              "evidence/rebuild_verification/"
                              "test_summary.json")
    abs_p = os.path.join(repo_root, summary_rel)
    if not os.path.isfile(abs_p):
        return [DriftFinding(
            "TEST_BASELINE_DRIFT", "REVIEW", summary_rel,
            "test summary present", "missing", ["test health"])]
    try:
        ts = json.load(open(abs_p, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [DriftFinding(
            "TEST_BASELINE_DRIFT", "CRITICAL", summary_rel,
            "parseable", "unreadable", ["test health"])]
    findings = []
    for key in ("collected", "passed"):
        want = baseline.get(key)
        got = ts.get(key)
        if isinstance(want, int) and isinstance(got, int) and got < want:
            findings.append(DriftFinding(
                "TEST_BASELINE_DRIFT", "CRITICAL", summary_rel,
                want, got,
                ["release gate (test counts must never silently drop)"]))
    return findings


ALL_DRIFTS = [
    ("CONTENT_DRIFT", detect_content_drift),
    ("RULE_DRIFT", detect_rule_drift),
    ("SCHEMA_DRIFT", detect_schema_drift),
    ("EVIDENCE_DRIFT", detect_evidence_drift),
    ("PROVENANCE_DRIFT", detect_provenance_drift),
    ("CONFIGURATION_DRIFT", detect_configuration_drift),
    ("DEPENDENCY_DRIFT", detect_dependency_drift),
    ("RELEASE_DRIFT", detect_release_drift),
    ("DOCUMENTATION_DRIFT", detect_documentation_drift),
    ("TEST_BASELINE_DRIFT", detect_test_baseline_drift),
]


def run_drift_detection(repo_root: str, snapshot: Dict[str, Any]
                        ) -> Dict[str, Any]:
    """Run all ten drift detectors; critical drift blocks release."""
    findings: List[DriftFinding] = []
    for name, fn in ALL_DRIFTS:
        try:
            if fn.__code__.co_argcount == 2:
                findings.extend(fn(repo_root, snapshot))
            else:
                findings.extend(fn(repo_root))
        except Exception as exc:  # noqa: BLE001 — detector failure is drift
            findings.append(DriftFinding(
                name, "CRITICAL", f"{fn.__name__}", "detector executes",
                f"detector failure: {exc}", []))
    critical = [f for f in findings if f.severity == "CRITICAL"]
    review = [f for f in findings if f.severity != "CRITICAL"]
    return {
        "update_id": UPDATE_ID,
        "drift_types_checked": [n for n, _ in ALL_DRIFTS],
        "finding_count": len(findings),
        "critical_count": len(critical),
        "review_count": len(review),
        "state": "CRITICAL" if critical else (
            "REVIEW" if review else "NONE"),
        "blocks_release": bool(critical),
        "findings": [f.as_dict() for f in findings],
    }


# ---------------------------------------------------------------------
# Freshness engine (task-book section 12)
# ---------------------------------------------------------------------

def evaluate_freshness(artifact: str, dependencies: List[Dict[str, str]],
                        repo_root: str,
                        recorded_self_sha: Optional[str] = None,
                        artifact_path: Optional[str] = None
                        ) -> Dict[str, Any]:
    """CURRENT / STALE / NOT_VERIFIED / INVALID for one derived artifact.

    - dependency hash changed  -> STALE
    - dependency missing       -> NOT_VERIFIED
    - artifact's own hash moved -> INVALID
    - otherwise                -> CURRENT
    """
    reasons = []
    state = "CURRENT"
    for dep in dependencies:
        dep_path = os.path.join(repo_root, dep["path"])
        if os.path.isdir(dep_path):
            actual = directory_fingerprint(dep_path)
            if actual is None:
                state = _worsen(state, "NOT_VERIFIED")
                reasons.append(f"dependency missing: {dep['path']}")
                continue
            if actual != dep.get("sha256"):
                state = _worsen(state, "STALE")
                reasons.append(f"dependency changed: {dep['path']}")
            continue
        if not os.path.isfile(dep_path):
            state = _worsen(state, "NOT_VERIFIED")
            reasons.append(f"dependency missing: {dep['path']}")
            continue
        actual = sha256_file(dep_path)
        if actual != dep.get("sha256"):
            state = _worsen(state, "STALE")
            reasons.append(f"dependency changed: {dep['path']}")
    if artifact_path and recorded_self_sha:
        abs_self = os.path.join(repo_root, artifact_path)
        if not os.path.isfile(abs_self):
            state = _worsen(state, "NOT_VERIFIED")
            reasons.append("artifact itself missing")
        elif sha256_file(abs_self) != recorded_self_sha:
            state = _worsen(state, "INVALID")
            reasons.append("artifact hash changed since generation")
    return {"state": state, "reasons": reasons}


def _worsen(current: str, candidate: str) -> str:
    return worst_status([current, candidate])


# ---------------------------------------------------------------------
# Change ledger (task-book section 14) — append-only within a run
# ---------------------------------------------------------------------

LEDGER_FIELDS = ("timestamp", "artifact", "old_sha256", "new_sha256",
                "change_type", "expected", "actor", "reason", "result",
                "affected_dependents")


def ledger_entry(artifact: str, old_sha: Optional[str],
                 new_sha: Optional[str], change_type: str,
                 expected: bool, reason: str, result: str,
                 affected_dependents: Optional[List[str]] = None,
                 actor: str = "unknown",
                 timestamp: Optional[str] = None) -> Dict[str, Any]:
    return {
        "timestamp": timestamp or _now_utc(),
        "artifact": artifact,
        "old_sha256": old_sha,
        "new_sha256": new_sha,
        "change_type": change_type,
        "expected": expected,
        "actor": actor,
        "reason": reason,
        "result": result,
        "affected_dependents": affected_dependents or [],
    }


def _now_utc() -> str:
    import datetime
    return datetime.datetime.now(
        datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_ledger(path: str, entries: List[Dict[str, Any]]) -> int:
    """Append entries as JSONL. The ledger is append-only within the
    current run: existing lines are never rewritten or removed."""
    written = 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, sort_keys=True) + "\n")
            written += 1
    return written


# ---------------------------------------------------------------------
# Anomaly detection (task-book section 27) — conservative
# ---------------------------------------------------------------------

def classify_anomaly(value: Any, expected: Any, tolerance: Any = None,
                     documented: bool = False) -> str:
    """NORMAL / REVIEW / CRITICAL without inventing failures.

    Thresholds are only applied when explicitly documented. No threshold
    -> any change is REVIEW (never CRITICAL, never silent).
    """
    if value == expected:
        return "NORMAL"
    if tolerance is None or not documented:
        return "REVIEW"
    try:
        if abs(float(value) - float(expected)) <= float(tolerance):
            return "NORMAL"
    except (TypeError, ValueError):
        return "REVIEW"
    return "REVIEW"


def detect_anomalies(current: Dict[str, Any],
                     baseline: Dict[str, Any]) -> Dict[str, Any]:
    """Conservative anomaly detection over derived metric counters."""
    anomalies = []
    for key, expected in sorted(baseline.items()):
        if not isinstance(expected, (int, float)):
            continue
        actual = current.get(key)
        if actual is None:
            anomalies.append({"metric": key, "expected": expected,
                              "actual": None,
                              "classification": "REVIEW",
                              "reason": "metric missing"})
            continue
        cls = classify_anomaly(actual, expected)
        if cls != "NORMAL":
            anomalies.append({
                "metric": key, "expected": expected, "actual": actual,
                "classification": cls,
                "reason": "value differs from verified baseline"})
    return {
        "policy": ("anomaly detection MUST NOT invent a failure; "
                   "thresholds only where explicitly documented"),
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
        "state": ("REVIEW" if anomalies else "NORMAL"),
    }


# ---------------------------------------------------------------------
# FINAL_RESULTS UPDATE schema gate (task-book section 9)
# ---------------------------------------------------------------------

FR_UPDATE_REQUIRED_FIELDS = {
    "report": str,
    "update_id": str,
    "generated_utc": str,
    "release_identity": dict,
    "git_identity": dict,
    "evidence_identity": dict,
    "rule_identity": dict,
    "schema_identity": dict,
    "runs": dict,
    "verification": dict,
    "test_identity": dict,
    "assurance": dict,
    "limitations": list,
    "verification_state": str,
    "derived_values": dict,
    "dependency_fingerprint": str,
}

# Fields whose VALUES are anchored to immutable expected constants.
FR_UPDATE_ENUMS = {
    "verification_state": [
        "PASS", "PASS_WITH_DOCUMENTED_LIMITATIONS",
        "NOT_VERIFIED", "FAIL"],
}

# comparisons_per_run is a scalar (identical across the two official
# runs; per-run detail lives in runs.<run_id>.comparisons)
FR_UPDATE_SCALARS = {"comparisons_per_run": 25600000}

# Unknown top-level keys are rejected (unknown critical fields).
FR_UPDATE_ALLOWED_FIELDS = set(FR_UPDATE_REQUIRED_FIELDS) | {
    "dependencies", "generation_mode",
}


def schema_gate_final_results_update(doc: Dict[str, Any]
                                      ) -> List[str]:
    """Strict fail-closed validation (task-book section 9).

    Rejects: missing fields, wrong types, unknown critical fields,
    invalid enums, incorrect rule count, incorrect schema count,
    incorrect run count, incorrect hashes, impossible combinations,
    PASS without evidence. Returns a list of problems (empty = PASS).
    """
    problems: List[str] = []

    # missing fields / wrong types
    for key, typ in FR_UPDATE_REQUIRED_FIELDS.items():
        if key not in doc:
            problems.append(f"missing required field '{key}'")
        elif not isinstance(doc[key], typ):
            problems.append(
                f"field '{key}' has type "
                f"{type(doc[key]).__name__}, expected {typ.__name__}")

    # unknown critical fields
    for key in doc:
        if key not in FR_UPDATE_ALLOWED_FIELDS:
            problems.append(f"unknown critical field '{key}'")

    # enums
    for key, allowed in FR_UPDATE_ENUMS.items():
        val = doc.get(key)
        if isinstance(val, str) and val not in allowed:
            problems.append(
                f"field '{key}' value '{val}' not in allowed enum")

    dv = doc.get("derived_values", {})
    if isinstance(dv, dict):
        # rule count
        if dv.get("rule_count") != 8:
            problems.append(f"rule_count must be 8, got "
                            f"{dv.get('rule_count')!r}")
        # schema counts
        if dv.get("input_column_count") != 33:
            problems.append(f"input_column_count must be 33, got "
                            f"{dv.get('input_column_count')!r}")
        if dv.get("output_column_count") != 41:
            problems.append(f"output_column_count must be 41, got "
                            f"{dv.get('output_column_count')!r}")
        # run counts
        if dv.get("run_count") != 2:
            problems.append(f"run_count must be 2, got "
                            f"{dv.get('run_count')!r}")
        if dv.get("rows_per_run") != 3200000:
            problems.append(f"rows_per_run must be 3200000, got "
                            f"{dv.get('rows_per_run')!r}")
        for key, expected_value in FR_UPDATE_SCALARS.items():
            if dv.get(key) != expected_value:
                problems.append(f"{key} must be {expected_value}, got "
                                f"{dv.get(key)!r}")
        if dv.get("combined_comparisons") != 51200000:
            problems.append(f"combined_comparisons must be 51200000, got "
                            f"{dv.get('combined_comparisons')!r}")
        if dv.get("combined_mismatches") != 0:
            problems.append(f"combined_mismatches must be 0, got "
                            f"{dv.get('combined_mismatches')!r}")

    # hashes (anchored)
    ev = doc.get("evidence_identity", {})
    if isinstance(ev, dict):
        if ev.get("official_input_sha256") != OFFICIAL_INPUT_SHA256:
            problems.append("official input SHA mismatch")
        if ev.get("official_output_sha256") != OFFICIAL_OUTPUT_SHA256:
            problems.append("official output SHA mismatch")
        if ev.get("frozen_v1_sha256") != FROZEN_V1_EXPECTED_SHA256:
            problems.append("frozen V1 SHA mismatch")
        for k in ("official_input_sha256", "official_output_sha256",
                  "frozen_v1_sha256", "checker_sha256"):
            v = ev.get(k)
            if not (isinstance(v, str)
                    and re.fullmatch(r"[0-9a-f]{64}", v or "")):
                problems.append(f"evidence_identity.{k} not a valid "
                                f"SHA-256")

    # impossible combinations: PASS without evidence
    if doc.get("verification_state") in ("PASS",
                                         "PASS_WITH_DOCUMENTED_LIMITATIONS"):
        verification = doc.get("verification", {})
        if not isinstance(verification, dict) or not verification.get(
                "run_pair_verdict") == "PASS":
            problems.append(
                "PASS state without run-pair verification evidence "
                "(PASS without evidence is forbidden)")
        if isinstance(verification, dict) and verification.get(
                "test_all_green") is not True:
            problems.append(
                "PASS state without green test suite evidence")
        limitations = doc.get("limitations")
        if not isinstance(limitations, list) or not limitations:
            problems.append(
                "PASS state must carry its documented limitations")

    return problems
