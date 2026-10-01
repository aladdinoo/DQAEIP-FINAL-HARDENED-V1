"""Layer E — Checkpoint / Safe-Resume Contract (CONTRACT ONLY).

DESIGN DECISION — NOT IMPLEMENTED BY CHOICE (fail-closed)
--------------------------------------------------------
Resume-from-checkpoint is deliberately NOT implemented in this release.
The mandate for the 2026-09-19 hardening release is explicit: if a resume
mechanism cannot be made provably safe, it must not ship. The specific
risks that make a checkpoint-resume unsafe for this pipeline are:

1. **Partial-write duplication**: a crash between an output row write and
   its checkpoint record allows re-emission of already-written rows on
   resume (double-counted rows) or omission of rows whose checkpoint was
   written ahead of the flush (lost rows).
2. **Oracle re-verification ambiguity**: the frozen validation oracle
   compares complete outputs; a resumed half-output has no independent
   way to prove it is exactly the prefix of a deterministic run without
   re-running the prefix anyway.
3. **Ledger-state conflation**: Layer C must never confuse
   PARTIAL/COMMITTED entries; introducing a third RESUMING state
   multiplies the state machine and the failure modes.
4. **Determinism makes resume unnecessary**: the engine is deterministic
   (certified dual-run byte-identical, 2026-09-18). A fresh full re-run
   reproduces the exact output; the only cost is time.

Therefore the SAFE behavior is: every interrupted execution is recorded
PARTIAL in the ledger (Layer C), resume requests are REFUSED, and the
operator re-runs from scratch. This layer defines the contract a future
checkpoint implementation would have to satisfy, and the refusal
function that enforces the decision.

Binding contract (what a future checkpoint would have to pin)
-------------------------------------------------------------
* execution identity SHA-256 (Layer B scope identity)
* input file SHA-256
* partial output SHA-256 (prefix hash at checkpoint time)
* row offset (0-based, rows already emitted)
* schema fingerprint, config fingerprint, software identity
* monotonic checkpoint sequence number
* HMAC-style binding preventing checkpoint transplantation across runs
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

LAYER_ID = "E"
LAYER_NAME = "Checkpoint / Safe-Resume Contract"
LAYER_VERSION = "1.0.0"

VERDICT_REFUSED = "RESUME_REFUSED_FRESH_RUN_REQUIRED"
IMPLEMENTED = False

REQUIRED_CHECKPOINT_BINDINGS = (
    "execution_identity_sha256",
    "input_sha256",
    "partial_output_sha256",
    "row_offset",
    "schema_fingerprint",
    "config_fingerprint",
    "software_identity",
    "checkpoint_sequence",
)

RESUME_RISK_REASONS = (
    "partial-write duplication: a crash between row emission and "
    "checkpoint record permits double-counted or lost rows on resume",
    "oracle re-verification ambiguity: a partial output cannot be "
    "proven to be the exact deterministic prefix without re-running "
    "the prefix",
    "ledger-state conflation: a RESUMING state would add failure modes "
    "to the Layer C PARTIAL/COMMITTED state machine",
    "determinism makes resume unnecessary: a fresh full re-run "
    "reproduces the byte-identical certified output",
)


@dataclass
class ResumeDecision:
    layer_id: str = LAYER_ID
    layer_name: str = LAYER_NAME
    layer_version: str = LAYER_VERSION
    verdict: str = VERDICT_REFUSED
    implemented: bool = IMPLEMENTED
    reasons: list = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "layer_id": self.layer_id,
            "layer_name": self.layer_name,
            "layer_version": self.layer_version,
            "verdict": self.verdict,
            "implemented": self.implemented,
            "reasons": list(self.reasons),
            "details": dict(self.details),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True)


def evaluate_resume_request(checkpoint: dict) -> ResumeDecision:
    """Refuse every resume request; demand a fresh full run.

    The checkpoint dict (if any) is only inspected to report which
    bindings a caller attempted to supply — inspection never grants
    authorization to resume.
    """
    decision = ResumeDecision()
    decision.reasons = list(RESUME_RISK_REASONS)
    decision.reasons.append(
        "contract decision: no checkpoint implementation is shipped in "
        "this release; the only safe path is a fresh full execution")
    if checkpoint:
        supplied = sorted(
            k for k in checkpoint if k in REQUIRED_CHECKPOINT_BINDINGS)
        decision.details["bindings_supplied_by_request"] = supplied
        missing = sorted(
            k for k in REQUIRED_CHECKPOINT_BINDINGS
            if k not in checkpoint)
        if missing:
            decision.details["bindings_missing_from_request"] = missing
    decision.details["required_future_bindings"] = list(
        REQUIRED_CHECKPOINT_BINDINGS)
    decision.details["operator_action"] = (
        "delete partial staging artifacts (Layer D staging directories "
        "marked .partial) and re-run the full execution from scratch")
    return decision


def checkpoint_contract_document() -> dict:
    """Machine-readable contract for a future (unshipped) design."""
    return {
        "layer_id": LAYER_ID,
        "layer_name": LAYER_NAME,
        "layer_version": LAYER_VERSION,
        "implemented": IMPLEMENTED,
        "decision": "CONTRACT_ONLY_NOT_IMPLEMENTED",
        "decision_basis": "resume cannot be made provably safe for a "
                          "deterministic pipeline; fresh re-run is the "
                          "safe equivalent",
        "required_bindings": list(REQUIRED_CHECKPOINT_BINDINGS),
        "resume_risk_reasons": list(RESUME_RISK_REASONS),
        "failure_mode_if_shipped_unsafe": [
            "double-counted rows", "lost rows",
            "prefix ambiguity under the frozen oracle",
            "ledger state conflation",
        ],
    }
