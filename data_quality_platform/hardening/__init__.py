"""Operational security hardening package for the DQAEIP frozen V1 core.

Scope (2026-09-19 hardened release)
-----------------------------------
This package adds EIGHT operational security layers as additive wrappers
around the certified DQAEIP core. It NEVER modifies:

* ``data_quality_platform/rules/v1_rules.py`` (Frozen V1, SHA-256
  daef1ded54c7d3c79898a1ba253be2acd5b6120e18b16b09009fdd7be9fc2276)
* the certified 2026-09-18 baseline evidence tree
* the frozen validation harness ``scripts/final_3m_validation.py``

Layers
------
A. Input Contract Firewall      -> :mod:`data_quality_platform.hardening.input_contract`
B. Execution Authorization Gate -> :mod:`data_quality_platform.hardening.authorization`
C. Idempotency Protection       -> :mod:`data_quality_platform.hardening.idempotency`
D. Atomic Output Commit         -> :mod:`data_quality_platform.hardening.atomic_commit`
E. Checkpoint/Resume Contract   -> :mod:`data_quality_platform.hardening.checkpoint_contract`
F. Schema Evolution Guard       -> :mod:`data_quality_platform.hardening.schema_guard`
G. Reference-Data Versioning    -> :mod:`data_quality_platform.hardening.reference_data`
H. Resource/Execution Guard     -> :mod:`data_quality_platform.hardening.resource_guard`

Orchestration: :mod:`data_quality_platform.hardening.pipeline`.

Fail-closed contract
--------------------
Every layer returns a structured verdict object. Any exception, missing
artifact, or failed check produces a REJECT/FAIL verdict with explicit
reasons; no layer ever converts an error into a PASS. Verdict objects are
plain JSON-serializable data so they can be embedded in execution
manifests as machine-readable evidence.
"""

HARDENING_PACKAGE = "data_quality_platform.hardening"
HARDENING_RELEASE_ID = "DQAEIP-FINAL-HARDENED-RELEASE-2026-09-19"
HARDENING_LAYER_VERSION = "1.0.0"

# Layer registry: id -> (name, module). Kept declarative so the pipeline,
# evidence builders, and tests can enumerate layers without imports that
# would create cycles.
LAYERS = (
    ("A", "input_contract", "Input Contract Firewall"),
    ("B", "authorization", "Execution Authorization Gate"),
    ("C", "idempotency", "Idempotency / Duplicate-Run Protection"),
    ("D", "atomic_commit", "Atomic Output Commit"),
    ("E", "checkpoint_contract", "Checkpoint / Safe-Resume Contract"),
    ("F", "schema_guard", "Schema Evolution Guard"),
    ("G", "reference_data", "Reference-Data Versioning"),
    ("H", "resource_guard", "Resource / Execution Guard"),
)

FROZEN_V1_SHA256 = (
    "daef1ded54c7d3c79898a1ba253be2acd5b6120e18b16b09009fdd7be9fc2276"
)

__all__ = [
    "HARDENING_PACKAGE", "HARDENING_RELEASE_ID", "HARDENING_LAYER_VERSION",
    "LAYERS", "FROZEN_V1_SHA256",
]
