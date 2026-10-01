"""Layer C — Idempotency / Duplicate-Run Protection.

Deterministic execution identity + an append-only execution ledger.

Behavior
--------
* The execution identity is the authorization scope identity (Layer B)
  — fully deterministic given the same inputs, software, and config.
* ``check_execution`` consults the ledger BEFORE execution:
  - identity never seen before -> ``NEW_EXECUTION`` (proceed)
  - identity already COMMITTED and every recorded output still hashes to
    its committed value -> ``IDEMPOTENT_COMPLETE`` (duplicate safely
    identified; re-execution not required and not performed)
  - identity already COMMITTED but outputs missing/tampered ->
    ``DUPLICATE_BLOCKED`` (fail-closed; requires operator intervention)
  - identity present as PARTIAL (interrupted) -> ``DUPLICATE_BLOCKED``
    (never resume a partial run — see Layer E contract)
* Different identities are distinct ledger entries and are never
  compared, merged, or conflated.

Ledger discipline
-----------------
The ledger is a JSON file with one entry per execution identity. Writes
are atomic (temp file + os.replace). A malformed, unreadable, or
hand-tampered ledger fails closed: every verdict becomes
``LEDGER_UNUSABLE_BLOCKED`` rather than silently allowing execution.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

LAYER_ID = "C"
LAYER_NAME = "Idempotency / Duplicate-Run Protection"
LAYER_VERSION = "1.0.0"

VERDICT_NEW = "NEW_EXECUTION"
VERDICT_IDEMPOTENT = "IDEMPOTENT_COMPLETE"
VERDICT_DUPLICATE_BLOCKED = "DUPLICATE_BLOCKED"
VERDICT_LEDGER_UNUSABLE = "LEDGER_UNUSABLE_BLOCKED"

_READ_CHUNK = 1 << 20

STATE_PARTIAL = "PARTIAL"
STATE_COMMITTED = "COMMITTED"


@dataclass
class IdempotencyResult:
    layer_id: str = LAYER_ID
    layer_name: str = LAYER_NAME
    layer_version: str = LAYER_VERSION
    verdict: str = VERDICT_LEDGER_UNUSABLE
    reasons: list = field(default_factory=list)
    details: dict = field(default_factory=dict)

    @property
    def proceed(self) -> bool:
        return self.verdict in (VERDICT_NEW,)

    @property
    def already_complete(self) -> bool:
        return self.verdict == VERDICT_IDEMPOTENT

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


class ExecutionLedger:
    """Append-only execution ledger keyed by execution identity."""

    def __init__(self, ledger_path: str):
        self.path = ledger_path

    # ── internal load/save ─────────────────────────────────────────────
    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {"schema": "dqaeip.execution.ledger/1.0",
                    "entries": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise LedgerUnusableError(f"ledger unreadable: {exc!r}") from exc
        if not isinstance(payload, dict) \
                or payload.get("schema") != "dqaeip.execution.ledger/1.0" \
                or not isinstance(payload.get("entries"), dict):
            raise LedgerUnusableError(
                "ledger malformed (schema or entries invalid)")
        return payload

    def _save(self, payload: dict) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        tmp = self.path + ".tmp-write"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    # ── public API ─────────────────────────────────────────────────────
    def check_execution(self, identity_sha: str,
                        output_paths: List[str]) -> IdempotencyResult:
        """Decide whether an execution with this identity may start."""
        result = IdempotencyResult()
        add = result.reasons.append
        result.details["identity_sha256"] = identity_sha
        try:
            payload = self._load()
        except LedgerUnusableError as exc:
            add(str(exc))
            result.verdict = VERDICT_LEDGER_UNUSABLE
            return result

        entry = payload["entries"].get(identity_sha)
        if entry is None:
            result.verdict = VERDICT_NEW
            return result

        state = entry.get("state")
        result.details["ledger_state"] = state
        if state == STATE_PARTIAL:
            add("a PARTIAL (interrupted) execution exists for this "
                "identity; resume is refused by contract (Layer E); "
                "operator must clear partial artifacts before a fresh run")
            result.verdict = VERDICT_DUPLICATE_BLOCKED
            return result
        if state != STATE_COMMITTED:
            add(f"ledger entry has unknown state {state!r}")
            result.verdict = VERDICT_LEDGER_UNUSABLE
            return result

        recorded = entry.get("outputs", {})
        if sorted(recorded) != sorted(list(output_paths)):
            add("recorded committed outputs do not match the requested "
                "output set for this identity")
            result.verdict = VERDICT_DUPLICATE_BLOCKED
            return result

        mismatched = []
        for path in output_paths:
            expected = recorded[path]
            try:
                actual = sha256_file(path)
            except OSError:
                mismatched.append(f"{path}: missing/unreadable")
                continue
            if actual.lower() != expected.lower():
                mismatched.append(f"{path}: hash drift")
        if mismatched:
            add("committed outputs no longer match their recorded "
                "hashes: " + "; ".join(mismatched))
            result.verdict = VERDICT_DUPLICATE_BLOCKED
            return result

        result.details["committed_outputs_verified"] = len(output_paths)
        result.verdict = VERDICT_IDEMPOTENT
        return result

    def register_partial(self, identity_sha: str) -> IdempotencyResult:
        """Record (or keep) a PARTIAL entry before execution starts."""
        return self._upsert(identity_sha, STATE_PARTIAL, {})

    def register_committed(self, identity_sha: str,
                           output_paths: List[str]) -> IdempotencyResult:
        """Record the COMMITTED entry with output hashes, atomically."""
        outputs: Dict[str, str] = {}
        for path in output_paths:
            outputs[path] = sha256_file(path)
        return self._upsert(identity_sha, STATE_COMMITTED, outputs)

    def clear_partial(self, identity_sha: str) -> IdempotencyResult:
        """Remove a PARTIAL entry after a cleanly-reported failure.

        Only PARTIAL entries are removable; a COMMITTED entry is
        immutable history. Used by the pipeline when an execution failed
        but the failure was REPORTED cleanly (engine exit non-zero,
        guard trip) — the next fresh run then proceeds as NEW_EXECUTION.
        A hard crash (pipeline itself killed) leaves the PARTIAL entry
        in place, and the next run stays blocked until an operator
        intervenes.
        """
        result = IdempotencyResult()
        add = result.reasons.append
        result.details["identity_sha256"] = identity_sha
        try:
            payload = self._load()
        except LedgerUnusableError as exc:
            add(str(exc))
            result.verdict = VERDICT_LEDGER_UNUSABLE
            return result
        entry = payload["entries"].get(identity_sha)
        if entry is None:
            result.verdict = VERDICT_NEW
            result.details["note"] = "no entry existed"
            return result
        if entry.get("state") != STATE_PARTIAL:
            add("refusing to clear a non-PARTIAL (committed) entry")
            result.verdict = VERDICT_DUPLICATE_BLOCKED
            return result
        del payload["entries"][identity_sha]
        try:
            self._save(payload)
        except OSError as exc:
            add(f"ledger write failed: {exc!r}")
            result.verdict = VERDICT_LEDGER_UNUSABLE
            return result
        result.verdict = VERDICT_NEW
        result.details["cleared"] = True
        return result

    def _upsert(self, identity_sha: str, state: str,
                outputs: Dict[str, str]) -> IdempotencyResult:
        result = IdempotencyResult()
        add = result.reasons.append
        result.details["identity_sha256"] = identity_sha
        result.details["new_state"] = state
        try:
            payload = self._load()
        except LedgerUnusableError as exc:
            add(str(exc))
            result.verdict = VERDICT_LEDGER_UNUSABLE
            return result
        entry = payload["entries"].get(identity_sha)
        if entry is not None and entry.get("state") == STATE_COMMITTED \
                and state == STATE_PARTIAL:
            add("refusing to downgrade a COMMITTED entry to PARTIAL")
            result.verdict = VERDICT_DUPLICATE_BLOCKED
            return result
        payload["entries"][identity_sha] = {
            "state": state,
            "outputs": outputs,
            "transitions": _append_transition(entry, state),
        }
        try:
            self._save(payload)
        except OSError as exc:
            add(f"ledger write failed: {exc!r}")
            result.verdict = VERDICT_LEDGER_UNUSABLE
            return result
        result.verdict = VERDICT_IDEMPOTENT if state == STATE_COMMITTED \
            else VERDICT_NEW
        if state == STATE_PARTIAL:
            result.details["note"] = (
                "partial marker recorded; execution may proceed")
        return result


def _append_transition(entry: Optional[dict], new_state: str) -> list:
    transitions: list = []
    if entry is not None and isinstance(entry.get("transitions"), list):
        transitions = list(entry["transitions"])
    transitions.append(new_state)
    return transitions


class LedgerUnusableError(Exception):
    """Raised internally; converted to fail-closed verdicts."""
