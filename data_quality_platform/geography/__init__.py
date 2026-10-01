"""SP1 successor geography package (pure, isolated implementation).

STATUS: IMPLEMENTED (pure semantics) - production activation DEFERRED.

    SP1 COMPANY CONTRACT STATUS ......... VERIFIED (delivered document;
                                          see docs/GEOGRAPHY_RULE_SP1_CONTRACT.md)
    IMPLEMENTATION READINESS ............ pure/local implementation complete,
                                          verified with controlled fixtures
    CANONICAL PRODUCTION VALIDATION .... BLOCKED (physical reference datasets
                                          unavailable; provenance gate open)
    REGISTRY IMPACT ..................... none - V1 rules remain the only
                                          registered geography rules

This package implements the successor contract from the company document
"Geography rule - canonical definition and acceptance cases"
(SHA-256 0cf6eb93..., prepared 2026-09-01) behind an injectable
two-reference provider interface, without modifying the V1 prefix-map
rules (ZipStateAssessable / GeographyMismatchCandidate / STATE_ZIP_PREFIXES)
or any production selection behavior.

Core principle: UNASSESSABLE != MISMATCH.
"""

from data_quality_platform.geography.canonical import (
    GEOGRAPHY_FIELDS_WITH_PRESENCE_CONTRACT,
    SP1_CONTRACT_DECISION_RECORD_V2_SHA256,
    SP1_CONTRACT_DOCUMENT_SHA256,
    SP1_CONTRACT_DOCUMENT_TITLE,
    SP1_CONTRACT_MEASUREMENTS,
    SP1_CONTRACT_PINNED_TEMPLATE_SHA256,
    SP1_CONTRACT_PREPARED,
    SP1_CONTRACT_SOURCE_COMMIT,
    SP1_CONTRACT_SUPERSEDES_SHA256,
    SP1_CONTRACT_V3_SHA256,
    SP1_GEOGRAPHY_RULE_SUMMARY_SHA256,
    SP1_MANUAL_DELIVERY_MANIFEST,
    SP1_RECIPIENT_RECEIPT,
    STATE_ALLOWLIST,
    FieldPresenceNotDefinedError,
    GeographyAssessment,
    ReferenceResolution,
    SP1Decision,
    compute_zip5,
    evaluate_geography,
    field_present,
    is_blank_state,
    is_invalid_state_format,
    is_numeric_state_review,
    is_unknown_state_code,
    normalize_state,
    normalize_text,
    resolve_reference,
    sp1_eligibility,
)
from data_quality_platform.geography.references import (
    CANONICAL_SOURCE_TABLE,
    InMemoryTwoReferenceProvider,
    ReferenceUnavailableError,
    TwoReferenceProvider,
)

__all__ = [
    "GEOGRAPHY_FIELDS_WITH_PRESENCE_CONTRACT",
    "SP1_CONTRACT_DECISION_RECORD_V2_SHA256",
    "SP1_CONTRACT_DOCUMENT_SHA256",
    "SP1_CONTRACT_DOCUMENT_TITLE",
    "SP1_CONTRACT_MEASUREMENTS",
    "SP1_CONTRACT_PINNED_TEMPLATE_SHA256",
    "SP1_CONTRACT_PREPARED",
    "SP1_CONTRACT_SOURCE_COMMIT",
    "SP1_CONTRACT_SUPERSEDES_SHA256",
    "SP1_CONTRACT_V3_SHA256",
    "SP1_GEOGRAPHY_RULE_SUMMARY_SHA256",
    "SP1_MANUAL_DELIVERY_MANIFEST",
    "SP1_RECIPIENT_RECEIPT",
    "STATE_ALLOWLIST",
    "CANONICAL_SOURCE_TABLE",
    "FieldPresenceNotDefinedError",
    "GeographyAssessment",
    "InMemoryTwoReferenceProvider",
    "ReferenceResolution",
    "ReferenceUnavailableError",
    "SP1Decision",
    "TwoReferenceProvider",
    "compute_zip5",
    "evaluate_geography",
    "field_present",
    "is_blank_state",
    "is_invalid_state_format",
    "is_numeric_state_review",
    "is_unknown_state_code",
    "normalize_state",
    "normalize_text",
    "resolve_reference",
    "sp1_eligibility",
]
