"""DQAEIP assurance layer (rebuild Phase 6-18).

An ADDITIVE, fail-closed assurance package on top of the existing
platform. It contains NO business logic and NEVER modifies production
rule decisions. Components:

    path_firewall       machine-local path detection for release artifacts
    truth_model         two-level FACT/INTERPRETATION status vocabulary
    release_schema      release-facing document schema validation
    stale_evidence      anti-stale / anti-mixing evidence rejection
    claims              claim-to-evidence provenance with verification
    release_chain       verifiable SOURCE->...->DOCUMENTATION chain
    limitation_registry structured limitation registry
    golden_snapshot     PII-free release fingerprint

Compatibility: the Python package name ``data_quality_platform`` is
retained unchanged (DQAEIP compatibility policy).
"""
