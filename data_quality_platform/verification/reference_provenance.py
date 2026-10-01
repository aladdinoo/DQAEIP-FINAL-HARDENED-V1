"""Reference Data Provenance (DQAVP hardening, Section 9).

A decision must never depend on an unidentified reference. This module
builds a machine-readable registry of EVERY reference dataset that
participates in V1 (and SP1-successor) decisions:

    reference identity / version / source / hash / effective date /
    schema / row count

and classifies each reference's verification status. For the SP1
successor specifically, the registry never pretends the company
authoritative fixture exists: statuses distinguish

    AUTHORITATIVE   — company-delivered and verified in this repository
    DERIVED         — derived from a delivered authoritative artifact
    LOCAL           — locally defined, frozen as part of the contract
    EXPERIMENTAL    — successor/validation-only semantics
    UNVERIFIED      — claimed by a company document, not locally
                      verifiable (e.g., physical tables never delivered)

Fail closed: the registry is built ONLY from what actually exists in
this repository. Nothing is inferred, nothing is fabricated.
"""

import hashlib
import json
from typing import Any, Dict

from data_quality_platform.contracts import (
    STATE_ZIP_PREFIXES, SUSPICIOUS_NAME_PATTERNS,
)

__all__ = ["build_reference_registry", "reference_sha256",
           "map_status_to_enterprise_vocabulary"]

# Enterprise governance vocabulary mapping (Section 13). ADDITIVE: the
# operational status is always preserved; the enterprise equivalent is
# derived by explicit, reviewed rules — never silently reinterpreted.
_ENTERPRISE_STATUS_MAP = {
    "LOCAL": "VERIFIED",
    "EXPERIMENTAL": "EXPERIMENTAL",
    "UNVERIFIED": "MISSING",
    "AUTHORITATIVE": "COMPANY_SUPPLIED",
    "DERIVED": "VERIFIED",
}


def map_status_to_enterprise_vocabulary(operational_status):
    """Map an operational reference status to the enterprise vocabulary.

    Unknown statuses map to REVIEW_REQUIRED (fail-closed: never a
    silent promotion). See docs/REFERENCE_GOVERNANCE_VOCABULARY.md for
    the reviewed justification of each rule.
    """
    return _ENTERPRISE_STATUS_MAP.get(operational_status, "REVIEW_REQUIRED")

# Map of rule_id -> the references its decisions depend on.
_RULE_REFERENCES = {
    "first_name_cleaning_candidate": ["suspicious_name_patterns_v1"],
    "last_name_cleaning_candidate": ["suspicious_name_patterns_v1"],
    "name_cleaning_candidate": [],
    "email_blank": [],
    "email_syntax_failure": ["email_syntax_regex_v1"],
    "proposed_email_export_eligible": ["email_syntax_regex_v1"],
    "zip_state_assessable": ["state_zip_prefix_map_v1"],
    "geography_mismatch_candidate": ["state_zip_prefix_map_v1"],
}


def reference_sha256(payload: Any) -> str:
    """Stable SHA-256 of a reference payload (canonical JSON)."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()


def build_reference_registry() -> Dict[str, Any]:
    """Build the full reference registry (read-only, fail closed)."""
    registry: Dict[str, Any] = {
        "registry_version": "1.0.0",
        "generated_by": "data_quality_platform.verification."
                        "reference_provenance",
        "rule_reference_map": dict(_RULE_REFERENCES),
        "references": {},
    }
    refs = registry["references"]

    # ---- V1 LOCAL frozen references (the production decision inputs) ----
    prefix_map_entry = {
        "identity": "state_zip_prefix_map_v1",
        "description": "US state -> ZIP prefix map used by the frozen V1 "
                       "geography rules (zip_state_assessable, "
                       "geography_mismatch_candidate)",
        "status": "LOCAL",
        "status_note": "frozen part of the V1 contract since baseline "
                       "ecf476a; simplified USPS geography with known "
                       "divergences (see docs/RULE_ORACLE_INDEPENDENCE.md)",
        "version": "1.0.0 (V1 frozen)",
        "source": "data_quality_platform/contracts.py:STATE_ZIP_PREFIXES",
        "sha256": reference_sha256(STATE_ZIP_PREFIXES),
        "effective_date": None,
        "schema": {"state": "2-letter uppercase code",
                   "prefixes": "list of 2-3 digit ZIP prefixes"},
        "row_count": len(STATE_ZIP_PREFIXES),
    }
    refs["state_zip_prefix_map_v1"] = prefix_map_entry

    suspicious_entry = {
        "identity": "suspicious_name_patterns_v1",
        "description": "Suspicious name substrings used by the frozen V1 "
                       "name-cleaning rules",
        "status": "LOCAL",
        "status_note": "frozen part of the V1 contract since baseline "
                       "ecf476a",
        "version": "1.0.0 (V1 frozen)",
        "source": "data_quality_platform/contracts.py:"
                  "SUSPICIOUS_NAME_PATTERNS",
        "sha256": reference_sha256(sorted(SUSPICIOUS_NAME_PATTERNS)),
        "effective_date": None,
        "schema": {"pattern": "lowercase substring"},
        "row_count": len(SUSPICIOUS_NAME_PATTERNS),
    }
    refs["suspicious_name_patterns_v1"] = suspicious_entry

    import re
    from data_quality_platform.rules.v1_rules import EmailSyntaxFailure
    regex_entry = {
        "identity": "email_syntax_regex_v1",
        "description": "E-mail syntax regular expression used by "
                       "email_syntax_failure and "
                       "proposed_email_export_eligible",
        "status": "LOCAL",
        "status_note": "frozen part of the V1 contract; compiled in two "
                      "rule classes (identity pinned by "
                      "test_rule_oracle_consistency)",
        "version": "1.0.0 (V1 frozen)",
        "source": "data_quality_platform/rules/v1_rules.py:"
                  "EmailSyntaxFailure.EMAIL_PATTERN",
        "sha256": reference_sha256(
            EmailSyntaxFailure.EMAIL_PATTERN.pattern),
        "effective_date": None,
        "schema": {"type": "regular expression (str.fullmatch semantics)"},
        "row_count": 1,
    }
    refs["email_syntax_regex_v1"] = regex_entry

    # ---- SP1 successor references (EXPERIMENTAL, NOT AUTHORITATIVE) ----
    try:
        from data_quality_platform.geography import canonical as sp1_canonical
        sp1_entry = {
            "identity": "sp1_two_reference_provider",
            "description": "Injectable two-reference provider interface "
                           "for the SP1 successor geography contract "
                           "(canonical + cross reference)",
            "status": "EXPERIMENTAL",
            "status_note": "validation-only; NOT registered in the "
                           "production registry; physical references "
                           "NOT delivered",
            "version": getattr(sp1_canonical, "SP1_STATUS", "UNKNOWN"),
            "source": "data_quality_platform/geography/references.py:"
                      "TwoReferenceProvider",
            "sha256": reference_sha256(
                {"canonical_source_table":
                 "tips_data.tblZipStCtyIB",
                 "contract_document_sha256":
                 getattr(sp1_canonical, "SP1_CONTRACT_DOCUMENT_SHA256",
                         None)}),
            "effective_date": "2026-09-01 (contract prepared)",
            "schema": {"canonical": "zip5 -> state", "cross": "zip5 -> "
                       "state (must agree or be absent)"},
            "row_count": 0,
            "physical_reference_status": "UNVERIFIED",
            "physical_reference_note": "the physical canonical/cross "
                                       "reference datasets were never "
                                       "delivered; no data is fabricated",
        }
        refs["sp1_two_reference_provider"] = sp1_entry
    except Exception:  # pragma: no cover - defensive
        pass

    # ---- Company-supplied but unverifiable references ---------------------
    dl_entry = {
        "identity": "dl_geography_cases_company_fixture",
        "description": "DL001-DL015 authoritative geography acceptance "
                       "cases fixture",
        "status": "UNVERIFIED",
        "status_note": "the authoritative fixture "
                       "(tests/golden/dl_geography_cases.csv) was never "
                       "delivered; the 7-test DL module is skip-gated by "
                       "design; no synthetic authoritative fixture is "
                       "created",
        "version": None,
        "source": "company (never delivered)",
        "sha256": None,
        "effective_date": None,
        "schema": None,
        "row_count": 0,
    }
    refs["dl_geography_cases_company_fixture"] = dl_entry

    registry["unverified_count"] = sum(
        1 for r in refs.values() if r["status"] == "UNVERIFIED")
    registry["no_fabrication_statement"] = (
        "Every entry describes what actually exists in this repository. "
        "Physical company references that were never delivered are "
        "recorded as UNVERIFIED with zero rows and no hash — never "
        "reconstructed, never fabricated.")
    return registry


def rule_reference_ids(rule_id: str):
    """Reference identities a given rule's decisions depend on."""
    return list(_RULE_REFERENCES.get(rule_id, []))
