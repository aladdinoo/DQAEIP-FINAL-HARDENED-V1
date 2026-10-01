"""DQAEIP evidence quarantine — explicit classification of evidence
trust status (assurance layer only; never alters business rules).

Every evidence artifact fed into a release decision must pass through
this classifier. The taxonomy is closed:

    VERIFIED     — on disk, parseable, hash matches the expected hash
    TRUSTED      — VERIFIED and inside the pinned trusted set (the
                   official 3M evidence roots and their direct
                   references)
    STALE        — well-formed but records an identity (checker /
                   rule-set / gate count) older than the current
                   authoritative one
    FOREIGN      — present in the evidence tree but absent from the
                   expected inventory (unexpected evidence)
    TAMPERED     — on disk but hash does NOT match the expected hash
    QUARANTINED  — present but malformed (unparseable / wrong shape)
    NOT_VERIFIED — absent, or no expected hash exists to verify against

Fail-closed rule (absolute): an artifact classified STALE, FOREIGN,
TAMPERED, or QUARANTINED can NEVER raise a release verdict. A verdict
computed over a screened set that contains any such class is capped at
its minimum — the screening report records this explicitly.
"""

import hashlib
import json
import os

TRUSTED_CLASSES = ("VERIFIED", "TRUSTED")
REJECTED_CLASSES = ("STALE", "FOREIGN", "TAMPERED", "QUARANTINED")

# The pinned trusted set: official two-run 3M evidence and its direct
# references. Anything here is TRUSTED only while its hash matches the
# recorded official value.
DEFAULT_TRUSTED_SET = [
    "evidence/validation/2026-09-19/fresh_3m2/FINAL_RESULTS.json",
    "evidence/validation/2026-09-19/fresh_3m2/pass1_engine/manifest.json",
    "evidence/validation/2026-09-19/fresh_3m2/pass1_engine/evidence_root.json",
    "evidence/validation/2026-09-19/fresh_3m2/pass2_engine/manifest.json",
    "evidence/validation/2026-09-19/fresh_3m2/pass2_engine/evidence_root.json",
]


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class EvidenceQuarantine:
    """Classifier over an expected-evidence inventory.

    ``expected`` maps repository-relative paths to the SHA-256 the
    artifact must have to count as VERIFIED. Paths may map to ``None``
    (present-but-unanchored: existence check only, classified
    NOT_VERIFIED rather than VERIFIED — an unanchored artifact can
    never verify a release claim).
    """

    def __init__(self, expected, trusted_set=None,
                 current_identities=None):
        self.expected = dict(expected or {})
        self.trusted_set = set(trusted_set or DEFAULT_TRUSTED_SET)
        # current_identities: {"checker_sha256":..., "rule_set_sha256":...,
        # "gate_count":...} used for STALE detection.
        self.current = current_identities or {}

    def classify(self, repo_root, rel_path):
        """Classify one evidence artifact. Returns a classification
        record; never raises on bad input (fail-closed, not crashy)."""
        rec = {
            "path": rel_path,
            "classification": "NOT_VERIFIED",
            "reason": None,
        }
        abs_p = os.path.join(repo_root, rel_path)
        if rel_path not in self.expected:
            rec["classification"] = "FOREIGN"
            rec["reason"] = ("not in the expected evidence inventory "
                             "(unexpected artifact)")
            return rec
        if not os.path.isfile(abs_p):
            rec["reason"] = "expected artifact is missing"
            return rec

        expected_sha = self.expected[rel_path]
        if expected_sha is None:
            rec["reason"] = ("no expected hash pinned; existence alone "
                             "cannot verify")
            return rec

        actual_sha = _sha256_file(abs_p)
        rec["actual_sha256"] = actual_sha
        rec["expected_sha256"] = expected_sha
        if actual_sha != expected_sha:
            rec["classification"] = "TAMPERED"
            rec["reason"] = ("hash differs from the pinned expected hash")
            return rec

        # Hash-anchored and matching: parse-check JSON evidence.
        if rel_path.endswith(".json"):
            try:
                with open(abs_p, encoding="utf-8") as f:
                    doc = json.load(f)
                if not isinstance(doc, dict):
                    raise ValueError("top-level JSON object required")
            except (OSError, ValueError) as exc:
                rec["classification"] = "QUARANTINED"
                rec["reason"] = f"malformed evidence: {exc}"
                return rec
            # STALE detection: recorded identities older than current.
            stale_refs = self._stale_references(rel_path, doc)
            if stale_refs:
                rec["classification"] = "STALE"
                rec["reason"] = ("records superseded identities: "
                                 + "; ".join(stale_refs))
                return rec

        rec["classification"] = (
            "TRUSTED" if rel_path in self.trusted_set else "VERIFIED")
        rec["reason"] = (
            "hash matches pinned expected value"
            + ("; inside the pinned trusted set" if rel_path in
               self.trusted_set else ""))
        return rec

    def _stale_references(self, rel_path, doc):
        """Detect evidence that pins an older checker / gate identity
        than the current authoritative one. Only fields the record
        actually carries are compared (absence is not staleness)."""
        stale = []
        cur_checker = self.current.get("checker_sha256")
        rec_checker = None
        for holder in (doc, doc.get("provenance") if isinstance(
                doc.get("provenance"), dict) else {}):
            for key in ("checker_script_sha256", "checker_sha256",
                        "script_sha256"):
                v = holder.get(key)
                if isinstance(v, str):
                    rec_checker = v
                    break
            if rec_checker:
                break
        if cur_checker and isinstance(rec_checker, str) \
                and rec_checker != cur_checker:
            stale.append("checker_sha256_differs_from_current")
        cur_gate = self.current.get("gate_count")
        if cur_gate and isinstance(doc.get("gate_count"), int) \
                and doc["gate_count"] != cur_gate:
            stale.append("gate_count_differs_from_current")
        return stale

    def screen(self, repo_root, paths=None):
        """Classify an evidence set and produce a fail-closed screening
        report. ``verdict`` can never be PASS when any rejected class
        is present; when nothing is rejected it reports CLEAN (it
        does NOT by itself assert PASS — that requires the release
        gate)."""
        paths = paths if paths is not None else sorted(self.expected)
        results = [self.classify(repo_root, p) for p in paths]
        counts = {}
        for r in results:
            counts[r["classification"]] = counts.get(
                r["classification"], 0) + 1
        rejected = [r for r in results
                    if r["classification"] in REJECTED_CLASSES]
        report = {
            "screened": len(results),
            "classification_counts": counts,
            "rejected": [{
                "path": r["path"],
                "classification": r["classification"],
                "reason": r["reason"],
            } for r in rejected],
            "rejected_count": len(rejected),
            "verdict": "EVIDENCE_REJECTED" if rejected else "CLEAN",
            "fail_closed_rule": (
                "any STALE / FOREIGN / TAMPERED / QUARANTINED artifact "
                "makes the screening verdict EVIDENCE_REJECTED; untrusted "
                "evidence can never raise a release verdict"),
            "results": results,
        }
        return report
