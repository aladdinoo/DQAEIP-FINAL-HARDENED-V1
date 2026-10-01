"""Artifact Identity Contract (DQAEIP FINAL PORTABLE EVIDENCE &
RELEASE HARDENING, task section 5 — Phase 4).

A small, stable identity model for every important artifact:

    {
      "logical_path": "repo://scripts/final_3m_validation.py",
      "relative_path": "scripts/final_3m_validation.py",
      "sha256": "<64 hex>",
      "artifact_class": "AUTHORITATIVE",
      "schema_version": "1.0"
    }

The contract distinguishes:

    logical identity   repo:// URI (stable across machines and layouts)
    physical path      repository-relative POSIX path
    cryptographic id   SHA-256 of the exact bytes
    artifact class      AUTHORITATIVE | DERIVED | SUPERSEDED | UNKNOWN
                       | TEMPORARY
    provenance          producer + role + source registry entry

Fail-closed rules (never violated):

    - a relative_path that is not a clean repo-relative POSIX path
      (absolute, machine-local, or traversing) is INVALID;
    - an artifact_class outside the closed five-class vocabulary is
      INVALID;
    - an UNKNOWN artifact is never silently forced into another class
      — reclassification requires an explicit resolution record;
    - a recorded sha256 that does not match the live artifact is
      STALE (the identity is broken, never "close enough");
    - registry fingerprints are deterministic and timestamp-free.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from typing import Any, Dict, List, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

ARTIFACT_CLASSES = (
    "AUTHORITATIVE",
    "DERIVED",
    "SUPERSEDED",
    "UNKNOWN",
    "TEMPORARY",
)

SCHEMA_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")

__all__ = [
    "ARTIFACT_CLASSES",
    "make_identity",
    "validate_identity",
    "sha256_of",
    "registry_fingerprint",
    "resolve_logical_path",
]


def sha256_of(path: str) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def resolve_logical_path(logical_path: str) -> Optional[str]:
    """repo:// URI -> repository-relative path."""
    if not isinstance(logical_path, str) or not logical_path.startswith(
            "repo://"):
        return None
    rel = logical_path[len("repo://"):]
    return rel or None


def _is_clean_relative(rel: str) -> bool:
    if not rel or rel.startswith("/") or rel.startswith("\\"):
        return False
    if re.match(r"^[A-Za-z]:", rel):
        return False
    parts = rel.split("/")
    for p in parts:
        if p in ("", ".", ".."):
            return False
    return True


def make_identity(relative_path: str,
                  artifact_class: str,
                  schema_version: str = "1.0",
                  repo_root: Optional[str] = None,
                  provenance: Optional[Dict[str, Any]] = None
                  ) -> Dict[str, Any]:
    """Build one identity record (validates inputs; raises ValueError
    on contract violations — callers report, never guess)."""
    if artifact_class not in ARTIFACT_CLASSES:
        raise ValueError(
            f"unknown artifact class {artifact_class!r}; valid: "
            f"{list(ARTIFACT_CLASSES)}")
    rel = relative_path.replace("\\", "/")
    if not _is_clean_relative(rel):
        raise ValueError(
            f"identity path must be a clean repo-relative POSIX path, "
            f"got {relative_path!r}")
    if not SCHEMA_VERSION_PATTERN.match(schema_version or ""):
        raise ValueError(f"schema_version must be N.M, got "
                         f"{schema_version!r}")
    root = repo_root or _REPO_ROOT
    sha = sha256_of(os.path.join(root, rel))
    if sha is None:
        raise ValueError(f"artifact not found: {rel}")
    record = {
        "logical_path": f"repo://{rel}",
        "relative_path": rel,
        "sha256": sha,
        "artifact_class": artifact_class,
        "schema_version": schema_version,
    }
    if provenance:
        record["provenance"] = provenance
    return record


def validate_identity(record: Dict[str, Any],
                      repo_root: Optional[str] = None
                      ) -> List[str]:
    """Fail-closed validation of one identity record; returns problems
    (empty list = valid)."""
    problems: List[str] = []
    if not isinstance(record, dict):
        return ["identity record is not an object"]
    logical = record.get("logical_path")
    rel = record.get("relative_path")
    if not isinstance(logical, str) or not logical.startswith("repo://"):
        problems.append("logical_path must be a repo:// URI")
    else:
        parsed = resolve_logical_path(logical)
        if parsed != rel:
            problems.append(
                f"logical_path {logical!r} does not resolve to "
                f"relative_path {rel!r}")
    if not isinstance(rel, str) or not _is_clean_relative(rel):
        problems.append(f"relative_path is not repo-relative POSIX: "
                        f"{rel!r}")
    sha = record.get("sha256")
    if not isinstance(sha, str) or not _HEX64.match(sha):
        problems.append("sha256 must be 64 lowercase hex characters")
    cls = record.get("artifact_class")
    if cls not in ARTIFACT_CLASSES:
        problems.append(f"artifact_class {cls!r} outside closed "
                       f"vocabulary {list(ARTIFACT_CLASSES)}")
    sv = record.get("schema_version")
    if not isinstance(sv, str) or not SCHEMA_VERSION_PATTERN.match(sv):
        problems.append(f"schema_version must be N.M, got {sv!r}")
    # live hash check (only when the artifact is expected on disk)
    if isinstance(rel, str) and _is_clean_relative(rel):
        root = repo_root or _REPO_ROOT
        live = sha256_of(os.path.join(root, rel))
        if live is None:
            problems.append(f"artifact missing on disk: {rel}")
        elif isinstance(sha, str) and _HEX64.match(sha) and live != sha:
            problems.append(f"STALE identity: recorded {sha[:12]}… but "
                            f"live artifact hashes to {live[:12]}…")
    return problems


def registry_fingerprint(records: List[Dict[str, Any]]) -> str:
    """Deterministic, timestamp-free fingerprint over the registry:
    SHA-256 over canonical (logical_path, sha256, artifact_class)
    triples."""
    triples = sorted(
        (r["logical_path"], r["sha256"], r["artifact_class"])
        for r in records)
    h = hashlib.sha256()
    for logical, sha, cls in triples:
        h.update(logical.encode("utf-8") + b"\x00")
        h.update(sha.encode("utf-8") + b"\x00")
        h.update(cls.encode("utf-8") + b"\x00")
    return h.hexdigest()
