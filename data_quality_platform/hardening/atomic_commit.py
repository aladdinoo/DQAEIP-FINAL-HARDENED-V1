"""Layer D — Atomic Output Commit.

Directory-level atomic commit protocol:

1. Outputs are produced into a staging directory whose name embeds the
   execution identity and carries a ``PARTIAL_MANIFEST.json`` marker
   (partial artifacts are thereby always distinguishable from committed
   artifacts).
2. Every staged member is verified by the caller-supplied verify hook
   (independent verification — the hook is expected to be independent of
   the producing code path).
3. Every staged member is hashed (SHA-256).
4. The staging directory is atomically renamed onto the final directory
   (single ``os.replace``/``os.rename`` on the same filesystem — the
   directory entry either moves completely or not at all).
5. A ``COMMITTED_MANIFEST.json`` with member hashes is written INSIDE the
   committed directory, and the manifest itself is hashed into the
   caller's execution manifest.

Failure at ANY phase leaves the final directory untouched; a crashed or
interrupted run can only ever leave staging directories behind, never a
half-committed final directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Callable, List, Optional

LAYER_ID = "D"
LAYER_NAME = "Atomic Output Commit"
LAYER_VERSION = "1.0.0"

VERDICT_COMMITTED = "ATOMIC_COMMIT_COMPLETE"
VERDICT_FAILED = "ATOMIC_COMMIT_FAILED"

PARTIAL_MANIFEST = "PARTIAL_MANIFEST.json"
COMMITTED_MANIFEST = "COMMITTED_MANIFEST.json"

_READ_CHUNK = 1 << 20


@dataclass
class AtomicCommitResult:
    layer_id: str = LAYER_ID
    layer_name: str = LAYER_NAME
    layer_version: str = LAYER_VERSION
    verdict: str = VERDICT_FAILED
    reasons: list = field(default_factory=list)
    details: dict = field(default_factory=dict)

    @property
    def committed(self) -> bool:
        return self.verdict == VERDICT_COMMITTED

    def as_dict(self) -> dict:
        return {
            "layer_id": self.layer_id,
            "layer_name": self.layer_name,
            "layer_version": self.layer_version,
            "verdict": self.verdict,
            "reasons": list(self.reasons),
            "details": dict(self.details),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_READ_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def staging_directory(base_dir: str, identity_sha: str) -> str:
    """Deterministic staging directory path for an execution identity."""
    return os.path.join(base_dir, f"staging-{identity_sha}.partial")


def write_partial_manifest(staging_dir: str, identity_sha: str,
                           planned_members: List[str]) -> None:
    """Stamp the staging directory as PARTIAL before execution."""
    os.makedirs(staging_dir, exist_ok=True)
    payload = {
        "schema": "dqaeip.atomic.partial/1.0",
        "identity_sha256": identity_sha,
        "planned_members": list(planned_members),
        "note": "partial (uncommitted) staging directory; not a release "
                "artifact; safe to delete wholesale",
    }
    path = os.path.join(staging_dir, PARTIAL_MANIFEST)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)


def discard_staging(staging_dir: str) -> None:
    """Remove a staging directory wholesale (only ever staging paths)."""
    if os.path.basename(staging_dir).startswith("staging-") \
            and staging_dir.endswith(".partial"):
        shutil.rmtree(staging_dir, ignore_errors=True)


def commit_directory_atomically(
    staging_dir: str,
    final_dir: str,
    verify_hook: Optional[Callable[[str], bool]] = None,
) -> AtomicCommitResult:
    """Verify + hash + atomically rename staging_dir onto final_dir.

    Parameters
    ----------
    staging_dir:
        The partial staging directory holding the produced outputs.
    final_dir:
        The final destination directory. Must not be an ancestor of the
        staging directory (guard against destructive renames).
    verify_hook:
        Optional independent verifier invoked with each staged member
        path; any ``False``/exception aborts the commit.
    """
    result = AtomicCommitResult()
    add = result.reasons.append
    result.details["staging_dir"] = staging_dir
    result.details["final_dir"] = final_dir

    try:
        if not os.path.isdir(staging_dir):
            add(f"staging directory missing: {staging_dir}")
            return result
        if os.path.commonpath(
                [os.path.abspath(final_dir),
                 os.path.abspath(staging_dir)]) \
                == os.path.abspath(final_dir) \
                and os.path.abspath(final_dir) != os.path.abspath(
                    staging_dir):
            add("final_dir would contain the staging directory "
                "(destructive layout refused)")
            return result
        members = sorted(
            name for name in os.listdir(staging_dir)
            if name not in (PARTIAL_MANIFEST, COMMITTED_MANIFEST)
        )
        if not members:
            add("staging directory contains no output members")
            return result
        for name in members:
            member_path = os.path.join(staging_dir, name)
            if not os.path.isfile(member_path):
                add(f"staged member is not a regular file: {name} "
                    "(directories and symlinks are not committable "
                    "members)")
                return result

        # ── phase 1: independent verification ──────────────────────────
        if verify_hook is not None:
            verification_failures = []
            for name in members:
                path = os.path.join(staging_dir, name)
                try:
                    ok = bool(verify_hook(path))
                except Exception as exc:  # fail-closed
                    ok = False
                    verification_failures.append(
                        f"{name}: verifier exception {exc!r}")
                if not ok and not verification_failures:
                    # record first plain failure without exception text
                    verification_failures = [
                        f"{name}: independent verification rejected "
                        "the artifact"]
            if verification_failures:
                add("; ".join(verification_failures))
                return result
        result.details["verified_members"] = len(members)

        # ── phase 2: member hashing ───────────────────────────────────
        member_hashes = {}
        for name in members:
            member_hashes[name] = sha256_file(
                os.path.join(staging_dir, name))
        result.details["member_count"] = len(member_hashes)

        # ── phase 3: prepare commit manifest (staged, then moved) ──────
        manifest_payload = {
            "schema": "dqaeip.atomic.committed/1.0",
            "members": {k: v for k, v in sorted(member_hashes.items())},
        }
        manifest_tmp = os.path.join(staging_dir,
                                    COMMITTED_MANIFEST + ".tmp")
        with open(manifest_tmp, "w", encoding="utf-8") as f:
            json.dump(manifest_payload, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())

        # drop the PARTIAL marker (the commit manifest replaces it)
        partial_path = os.path.join(staging_dir, PARTIAL_MANIFEST)
        if os.path.exists(partial_path):
            os.remove(partial_path)
        os.replace(manifest_tmp,
                   os.path.join(staging_dir, COMMITTED_MANIFEST))

        # ── phase 4: atomic directory rename ──────────────────────────
        final_parent = os.path.dirname(
            os.path.abspath(final_dir))
        os.makedirs(final_parent, exist_ok=True)
        if os.path.exists(final_dir):
            add(f"final directory already exists: {final_dir} "
                "(refusing to overwrite a previous committed output)")
            return result
        os.rename(staging_dir, final_dir)

        result.details["committed_manifest_sha256"] = sha256_file(
            os.path.join(final_dir, COMMITTED_MANIFEST))
        result.details["member_hashes"] = member_hashes
        result.verdict = VERDICT_COMMITTED
        return result
    except Exception as exc:  # fail-closed on anything unexpected
        add(f"atomic commit failed: {exc!r}")
        result.verdict = VERDICT_FAILED
        return result


def is_committed_directory(directory: str) -> bool:
    """Distinguish committed directories from partial staging dirs."""
    if not os.path.isdir(directory):
        return False
    has_committed = os.path.isfile(
        os.path.join(directory, COMMITTED_MANIFEST))
    has_partial = os.path.isfile(os.path.join(directory, PARTIAL_MANIFEST))
    return has_committed and not has_partial


def verify_committed_directory(directory: str) -> bool:
    """Re-verify every member hash recorded in the commit manifest."""
    try:
        with open(os.path.join(directory, COMMITTED_MANIFEST),
                  "r", encoding="utf-8") as f:
            manifest = json.load(f)
        members = manifest["members"]
        for name, expected in members.items():
            if sha256_file(os.path.join(directory, name)) != expected:
                return False
        return True
    except Exception:
        return False
