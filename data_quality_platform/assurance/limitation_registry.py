"""Structured Limitation Registry (DQAEIP rebuild Phase 18).

Each limitation has: stable ID, status, description, evidence
reference, verification state, affected scope, and whether it blocks
release. Limitations are NOT hidden and NOT converted into failures
unless the stated release policy requires blocking.

The registry DATA lives in ``evidence/release/limitation_registry.json``
(curated, tracked, validated here); this module provides the schema,
loader and validators. Keeping the data out of production Python
sources also preserves the production-code boundary tripwires.

Registry policy:
- The stated release policy is PASS_WITH_DOCUMENTED_LIMITATIONS when
  all required verifications pass and documented, non-blocking
  limitations remain.
- A limitation can only be marked resolved by evidence recorded in
  the registry itself (never by editing prose elsewhere).
"""

import json
import os

__all__ = [
    "REGISTRY_PATH",
    "REQUIRED_FIELDS",
    "ALLOWED_VERIFICATION_STATES",
    "load_registry",
    "validate_registry",
    "registry_summary",
    "get_limitation",
]

# Repository-relative canonical location of the registry data.
REGISTRY_PATH = os.path.join("evidence", "release",
                             "limitation_registry.json")

REQUIRED_FIELDS = ("id", "title", "status", "description",
                   "evidence_reference", "verification_state",
                   "affected_scope", "blocks_release")

ALLOWED_VERIFICATION_STATES = (
    "VERIFIED_LOCALLY", "COMPANY_SUPPLIED", "HISTORICAL",
    "NOT_EXECUTED", "NOT_AUTHORIZED", "REVIEW_REQUIRED", "NOT_VERIFIED",
)

_ID_PREFIX = "LIM-"


def load_registry(repo_root):
    """Load the registry data; returns (entries, problems).

    Fail closed: unreadable/malformed JSON yields problems and an
    empty entry list.
    """
    path = os.path.join(repo_root, REGISTRY_PATH)
    if not os.path.isfile(path):
        return [], [f"registry file missing: {REGISTRY_PATH}"]
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except Exception as exc:
        return [], [f"registry JSON unreadable: {type(exc).__name__}"]
    entries = doc.get("limitations") if isinstance(doc, dict) else None
    if not isinstance(entries, list) or not entries:
        return [], ["registry contains no limitations list"]
    return entries, []


def validate_registry(entries=None, repo_root="."):
    """Validate registry structure; returns problem list (empty=ok)."""
    if entries is None:
        entries, load_problems = load_registry(repo_root)
        if load_problems:
            return load_problems
    problems = []
    ids = set()
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            problems.append(f"limitation[{i}] is not an object")
            continue
        for field in REQUIRED_FIELDS:
            if field not in e:
                problems.append(f"limitation[{i}] missing field "
                                f"{field!r}")
        lid = e.get("id")
        if not isinstance(lid, str) or not lid.startswith(_ID_PREFIX):
            problems.append(f"limitation[{i}] id {lid!r} must use the "
                            f"stable '{_ID_PREFIX}NNN' form")
        elif lid in ids:
            problems.append(f"duplicate limitation id {lid!r}")
        ids.add(lid)
        state = e.get("verification_state")
        if state not in ALLOWED_VERIFICATION_STATES:
            problems.append(
                f"limitation {lid!r} unknown verification_state "
                f"{state!r} (closed vocabulary, fail closed)")
        if not isinstance(e.get("blocks_release"), bool):
            problems.append(f"limitation {lid!r} blocks_release must "
                            f"be boolean")
    return problems


def get_limitation(repo_root, lid):
    entries, _ = load_registry(repo_root)
    for e in entries:
        if e.get("id") == lid:
            return e
    return None


def registry_summary(repo_root="."):
    entries, problems = load_registry(repo_root)
    if problems:
        return {"total": 0, "open": 0, "blocking": 0,
                "by_verification_state": {}, "problems": problems}
    return {
        "total": len(entries),
        "open": sum(1 for e in entries if e.get("status") == "OPEN"),
        "blocking": sum(1 for e in entries if e.get("blocks_release")),
        "by_verification_state": {
            state: sum(1 for e in entries
                       if e.get("verification_state") == state)
            for state in sorted({e.get("verification_state")
                                 for e in entries})
        },
    }
