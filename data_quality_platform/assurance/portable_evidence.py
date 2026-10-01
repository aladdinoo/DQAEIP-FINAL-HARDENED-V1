"""Portable Evidence Path Standard (DQAEIP FINAL PORTABLE EVIDENCE &
RELEASE HARDENING, task section 3 — Phase 2).

THE single centralized path-normalization utility for the whole
platform. No other module may implement its own path rewriting.

Canonical internal representation: repo-relative POSIX paths.

    BAD:  /home/z/my-project/dqvp-work/repo/scripts/final_3m_validation.py
    GOOD: scripts/final_3m_validation.py

Logical artifact identity (used ONLY where an explicit logical URI is
useful — e.g. the artifact identity registry, Phase 4):

    repo://scripts/final_3m_validation.py

Normalization rules (task-book section 3, enforced here):

    1. Portable evidence MUST NOT depend on the author's machine.
    2. Repository-local paths MUST be relative.
    3. Logical artifact identity MAY use repo://.
    4. Every important artifact retains SHA-256 identity (the source
       artifact is never modified by normalization; derived copies
       record the source SHA-256).
    5. Historical evidence remains historically accurate (originals
       are preserved byte-exact; normalization only ever produces
       clearly-marked DERIVED representations).
    6. Never converted (fail-safe defaults of this module):
         - external HTTPS/HTTP URLs
         - hashes (hex strings)
         - email addresses
         - Windows-path EXAMPLES in documentation
         - legitimate non-repository machine paths, UNLESS the field
           is explicitly classified as a filesystem artifact path AND
           an explicit placeholder mapping is supplied (used only for
           clearly-marked derived representations of historical
           runtime-safety records).

This module never writes files. Pure functions only.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "REPO_URI_SCHEME",
    "to_posix",
    "to_repo_uri",
    "from_repo_uri",
    "repo_relative",
    "is_repository_path",
    "contains_repository_path",
    "normalize_string",
    "normalize_document",
    "MACHINE_PATH_DETECTORS",
    "contains_machine_local_path",
]

REPO_URI_SCHEME = "repo://"

# Detectors used to decide whether a string is machine-local AT ALL.
# Shared by this module and by the release gate (tools/absolute_path_
# release_gate.py re-uses these patterns; they are defined once here).
MACHINE_PATH_DETECTORS = [
    ("posix_home", re.compile(r"(?<![A-Za-z0-9])/home/[A-Za-z0-9_.-]+")),
    ("macos_users", re.compile(r"(?<![A-Za-z0-9])/Users/[A-Za-z0-9_.-]+")),
    ("root_home", re.compile(r"(?<![A-Za-z0-9])/root(?![A-Za-z0-9])")),
    ("mounted_volume", re.compile(r"(?<![A-Za-z0-9])/mnt/[A-Za-z0-9_.-]+")),
    ("machine_tmp", re.compile(r"(?<![A-Za-z0-9])/tmp/")),
    ("system_var", re.compile(
        r"(?<![A-Za-z0-9])/var/(?:lib|log|tmp|spool)/")),
    ("service_tree", re.compile(r"(?<![A-Za-z0-9])/srv/")),
    # drive letter at a token boundary — the lookbehind prevents URL
    # schemes (https://, file://) from matching
    ("windows_drive", re.compile(
        r"(?<![A-Za-z0-9])[A-Za-z]:[/\\][A-Za-z0-9_.\\\\/ -]*")),
    ("unc_share", re.compile(
        r"\\\\[A-Za-z0-9_.$-]+\\[A-Za-z0-9_.$-]+")),
    ("file_uri", re.compile(r"file://[A-Za-z0-9_.:/\\-]+")),
    ("tilde_user", re.compile(r"(?<![A-Za-z0-9_.-])~/")),
    ("tilde_named_user",
     re.compile(r"(?<![A-Za-z0-9_.-])~[A-Za-z][A-Za-z0-9_-]*/")),
]


def to_posix(path: str) -> str:
    """Convert any path to POSIX separators (never changes meaning)."""
    return path.replace("\\", "/")


def to_repo_uri(relative: str) -> str:
    """Logical artifact identity for a repo-relative path."""
    rel = to_posix(relative).lstrip("./")
    return REPO_URI_SCHEME + rel


def from_repo_uri(uri: str) -> Optional[str]:
    """Parse a repo:// URI back to a repo-relative path."""
    if not isinstance(uri, str) or not uri.startswith(REPO_URI_SCHEME):
        return None
    return uri[len(REPO_URI_SCHEME):]


def _abs_root(repo_root: str) -> str:
    return os.path.abspath(repo_root).rstrip("/") + "/"


def repo_relative(value: str, repo_root: str) -> Optional[str]:
    """Repo-relative POSIX form of a machine-local path, or None when
    the value does not point inside the repository."""
    if not isinstance(value, str) or not value:
        return None
    root = _abs_root(repo_root)
    v = to_posix(value)
    if v.startswith(root):
        rest = v[len(root):]
        return rest if rest else "."
    # tilde-style repo references are not resolvable portably
    return None


def is_repository_path(value: str, repo_root: str) -> bool:
    return repo_relative(value, repo_root) is not None


def contains_repository_path(value: str, repo_root: str) -> bool:
    """True when the string EMBEDS a repository-local machine path
    anywhere inside it (e.g. a full command line)."""
    if not isinstance(value, str):
        return False
    return _abs_root(repo_root) in to_posix(value)


def contains_machine_local_path(value: str) -> Optional[str]:
    """Return the detector id when the string contains any
    machine-local path pattern; None otherwise."""
    if not isinstance(value, str):
        return None
    for detector_id, pattern in MACHINE_PATH_DETECTORS:
        if pattern.search(value):
            return detector_id
    return None


def normalize_string(value: str, repo_root: str,
                     placeholder_map: Optional[Dict[str, str]] = None
                     ) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Normalize ONE string.

    Transformation (deterministic, order-fixed):

      1. every placeholder_map key (longest first) is replaced by its
         documented placeholder token — used ONLY for clearly-marked
         derived representations of non-repository environment paths
         (e.g. the historical interpreter home);
      2. every embedded repository-root prefix is rewritten to the
         repo-relative form.

    Returns ``(new_value, change_record)`` where ``change_record`` is
    None when the string was already portable. The change record
    intentionally does NOT embed the original machine-local value —
    originals live in the preserved source artifact, recoverable via
    its SHA-256; derived copies stay free of machine paths.
    """
    if not isinstance(value, str):
        return value, None
    new = value
    changes = []
    for source, token in sorted((placeholder_map or {}).items(),
                                key=lambda kv: -len(kv[0])):
        if source and source in new:
            new = new.replace(source, token)
            changes.append({"type": "environment_placeholder",
                            "token": token})
    root = _abs_root(repo_root)
    npos = to_posix(new)
    if root in npos:
        new = npos.replace(root, "")
        changes.append({"type": "repo_relative"})
    if new == value:
        return value, None
    return new, {"changes": changes}


def normalize_document(doc: Any, repo_root: str,
                        placeholder_map: Optional[Dict[str, str]] = None
                        ) -> Tuple[Any, List[Dict[str, Any]]]:
    """Recursively normalize every string of a parsed JSON document.

    Only strings that actually contain machine-local repository paths
    (or an explicit placeholder-mapped environment prefix) are
    rewritten. Hashes, URLs, emails, documentation examples and other
    strings are structurally incapable of triggering a rewrite: the
    rewrite only fires on an exact repository-root prefix or an exact
    placeholder-map key, never on a pattern heuristic.

    Returns ``(new_doc, changes)``; each change records the JSON path
    of the rewritten string (values are NOT recorded — see
    normalize_string).
    """
    changes: List[Dict[str, Any]] = []

    def walk(obj, path):
        if isinstance(obj, dict):
            return {k: walk(v, f"{path}.{k}" if path else str(k))
                    for k, v in obj.items()}
        if isinstance(obj, list):
            return [walk(v, f"{path}[{i}]") for i, v in enumerate(obj)]
        if isinstance(obj, str):
            new, change = normalize_string(obj, repo_root,
                                           placeholder_map)
            if change is not None:
                changes.append({"json_path": path, **change})
            return new
        return obj

    new_doc = walk(doc, "$")
    return new_doc, changes
