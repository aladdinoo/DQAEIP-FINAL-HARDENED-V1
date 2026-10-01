"""SP1 successor geography contract - canonical pure semantics.

AUTHORITY
---------
Contract source: company-delivered document

    "Geography rule - canonical definition and acceptance cases"
    prepared 2026-09-01, measurements 2026-08-31
    document SHA-256: 0cf6eb930149e975397b348709d8f7e83f96eb6eb70d2361cf66551ada311bc0
    source commit:    ee7859e1ad521cb68ba32b604498d951c7690b19

The document was supplied through the authoritative company instruction
channel. It was NOT accessible as a physical file in the coding
environment, therefore its SHA-256 above is the company-provided value
and could not be re-computed locally. See
docs/GEOGRAPHY_RULE_SP1_CONTRACT.md for the full provenance record.

ISOLATION NOTICE
----------------
This module implements the SP1 SUCCESSOR contract as a pure, injectable-
reference implementation. It does NOT alter, replace, or re-register the
V1 rules (ZipStateAssessable / GeographyMismatchCandidate backed by
STATE_ZIP_PREFIXES in data_quality_platform.contracts), which remain the
only geography rules registered in the production RuleRegistry.

Activation of the successor semantics in production selection is
DEFERRED until the physical canonical reference datasets (canonical
reference + cross reference derived from tips_data.tblZipStCtyIB) are
available with provenance. Until then:

    - the pure semantics below are verified with controlled fixtures,
    - no canonical production validation is claimed,
    - no production behavior changes.

CORE PRINCIPLE
--------------
    UNASSESSABLE != MISMATCH

A mismatch row is assessable by definition (mismatch implies assessable).
An unassessable row whose requested geography field is present is
ELIGIBLE under SP1 - it is not treated as a mismatch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

# ---------------------------------------------------------------------------
# Contract provenance constants (pinned for auditability).
# ---------------------------------------------------------------------------

SP1_CONTRACT_DOCUMENT_TITLE = (
    "Geography rule - canonical definition and acceptance cases"
)
SP1_CONTRACT_PREPARED = "2026-09-01"
SP1_CONTRACT_MEASUREMENTS = "2026-08-31"
SP1_CONTRACT_DOCUMENT_SHA256 = (
    "0cf6eb930149e975397b348709d8f7e83f96eb6eb70d2361cf66551ada311bc0"
)
SP1_CONTRACT_SOURCE_COMMIT = (
    "ee7859e1ad521cb68ba32b604498d951c7690b19"
)
# Document hashes recorded in the company provenance block:
SP1_CONTRACT_V3_SHA256 = (
    "8ae3256b362d218849a688cc8f0a76d86c4ffb886607f69848030c2e6ba1fe74"
)
SP1_CONTRACT_DECISION_RECORD_V2_SHA256 = (
    "4dd8914f4d5ed7ab47f5245fd762d9e06983e43aba0858d1e38b3c1cf21fac4c"
)
SP1_CONTRACT_PINNED_TEMPLATE_SHA256 = (
    "47b3361b22ee9882c17e70886c3d5e3c493107881ed9f86345b96c5aa1cd521a"
)
# Superseded prepared version (never present in this repository):
SP1_CONTRACT_SUPERSEDES_SHA256 = (
    "3297179ea3527f56091191c48e8f72606e000fc7b885da906a7e59b97e1aebc8"
)

# ---------------------------------------------------------------------------
# Provenance additions recorded from the 2026-09-10 successor-contract
# instruction delivery (GEOGRAPHY SUCCESSOR CONTRACT INTEGRATION master
# prompt, section 13 "GULNARA PROVENANCE"). These are PROVENANCE METADATA
# ONLY - they are not execution evidence and must never be merged with
# Evidence Manifest v1. The manual delivery manifest identifier refers to
# the business-rule delivery channel, NOT to a repository evidence
# manifest.
# ---------------------------------------------------------------------------

# geography_rule_summary.md SHA-256 (company-provided value; the physical
# file is not present in this repository and the hash could not be
# re-computed locally):
SP1_GEOGRAPHY_RULE_SUMMARY_SHA256 = (
    "410bbf294e20692db616962884523bd3ef67d13c3bef0771ac9b92d4c2b0b708"
)
# Manual delivery manifest identifier (provenance only, NOT execution
# evidence and NOT Evidence Manifest v1):
SP1_MANUAL_DELIVERY_MANIFEST = "manual_delivery_v1"
# Recipient receipt of the manual delivery: not verified.
SP1_RECIPIENT_RECEIPT = "NOT VERIFIED"

# ---------------------------------------------------------------------------
# Authoritative state allowlist (verbatim from the company contract;
# territories and military codes are included).
# ---------------------------------------------------------------------------

STATE_ALLOWLIST: Tuple[str, ...] = (
    "AA", "AE", "AK", "AL", "AP", "AR", "AS", "AZ",
    "CA", "CO", "CT", "DC", "DE",
    "FL", "FM", "GA", "GU",
    "HI", "IA", "ID", "IL", "IN",
    "KS", "KY", "LA",
    "MA", "MD", "ME", "MH", "MI", "MN", "MO", "MP", "MS", "MT",
    "NC", "ND", "NE", "NH", "NJ", "NM", "NV", "NY",
    "OH", "OK", "OR",
    "PA", "PR", "PW",
    "RI",
    "SC", "SD",
    "TN", "TX",
    "UT",
    "VA", "VI", "VT",
    "WA", "WI", "WV", "WY",
)

_STATE_ALLOWLIST_SET = frozenset(STATE_ALLOWLIST)

# ---------------------------------------------------------------------------
# Normalization (contract: convert to text, trim surrounding whitespace,
# null -> empty string, state upper-cased before comparison).
# ---------------------------------------------------------------------------

_ZIP5_RE = re.compile(r"^[0-9]{5}$")
_TWO_LETTER_RE = re.compile(r"^[A-Za-z]{2}$")
_DIGITS_ONLY_RE = re.compile(r"^[0-9]+$")


def normalize_text(value: Any) -> str:
    """Contract normalization: null -> '', str(), surrounding whitespace trimmed."""
    if value is None:
        return ""
    return str(value).strip()


def normalize_state(value: Any) -> str:
    """Contract normalization for state: text, trimmed, upper-cased."""
    return normalize_text(value).upper()


def compute_zip5(value: Any) -> str:
    """zip5 = trimmed zip matching ^[0-9]{5}$, otherwise ''."""
    text = normalize_text(value)
    if _ZIP5_RE.match(text):
        return text
    return ""


# ---------------------------------------------------------------------------
# State value classifiers (all operate on the normalized state value).
# ---------------------------------------------------------------------------

def is_blank_state(state_code: str) -> bool:
    """blank_state = state = '' (after normalization)."""
    return state_code == ""


def is_invalid_state_format(state_text: str, state_code: str) -> bool:
    """invalid_state_format =
        state != '' AND not ^[A-Za-z]{2}$ AND not all digits."""
    if state_code == "":
        return False
    if _TWO_LETTER_RE.match(state_text):
        return False
    if _DIGITS_ONLY_RE.match(state_text):
        return False
    return True


def is_numeric_state_review(state_code: str) -> bool:
    """numeric_state_review = state != '' AND all digits."""
    if state_code == "":
        return False
    return bool(_DIGITS_ONLY_RE.match(state_code))


def is_unknown_state_code(state_code: str) -> bool:
    """unknown_state_code = two-letter state AND not in allowlist."""
    if not _TWO_LETTER_RE.match(state_code):
        return False
    return state_code not in _STATE_ALLOWLIST_SET


# ---------------------------------------------------------------------------
# Reference resolution (two-reference model).
#
# The provider supplies, for a given zip5, the distinct normalized states
# found in the canonical reference and in the cross reference. See
# references.py for the provider interface and the controlled-fixture
# implementation. No physical canonical production dataset is bundled.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReferenceResolution:
    """Outcome of the two-reference resolution for one zip5.

    reference_resolved =
        zip5 != ''
        AND canonical_state_count = 1
        AND cross_state_count <= 1
        AND (cross_state_count = 0 OR canonical_state = cross_state)
    """

    zip5: str
    canonical_state_count: int
    cross_state_count: int
    canonical_state: Optional[str]
    cross_state: Optional[str]
    reference_resolved: bool


def resolve_reference(zip5: str, provider: Any) -> ReferenceResolution:
    """Apply the contract's two-reference resolution to one zip5."""
    if zip5 == "":
        return ReferenceResolution(
            zip5="",
            canonical_state_count=0,
            cross_state_count=0,
            canonical_state=None,
            cross_state=None,
            reference_resolved=False,
        )
    canonical_states = tuple(provider.canonical_states(zip5))
    cross_states = tuple(provider.cross_states(zip5))
    canonical_count = len(canonical_states)
    cross_count = len(cross_states)
    canonical_state: Optional[str] = (
        canonical_states[0] if canonical_count == 1 else None
    )
    cross_state: Optional[str] = cross_states[0] if cross_count == 1 else None
    resolved = (
        canonical_count == 1
        and cross_count <= 1
        and (cross_count == 0 or canonical_state == cross_state)
    )
    return ReferenceResolution(
        zip5=zip5,
        canonical_state_count=canonical_count,
        cross_state_count=cross_count,
        canonical_state=canonical_state,
        cross_state=cross_state,
        reference_resolved=resolved,
    )


# ---------------------------------------------------------------------------
# Geography assessment (canonical chain:
# Canonical Geography -> zip_state_assessable -> zip_state_mismatch).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GeographyAssessment:
    """Full per-row geography assessment under the SP1 successor contract.

    Booleans are True/False; ``canonical_state``/``cross_state`` are None
    when not uniquely resolved. ``zip_state_mismatch`` implies
    ``zip_state_assessable`` (a mismatch row is assessable by definition).
    """

    zip_raw: str
    state_raw: str
    zip5: str
    state_code: str
    blank_state: bool
    invalid_state_format: bool
    numeric_state_review: bool
    unknown_state_code: bool
    canonical_state_count: int
    cross_state_count: int
    canonical_state: Optional[str]
    cross_state: Optional[str]
    reference_resolved: bool
    zip_state_assessable: bool
    zip_state_match: bool
    zip_state_mismatch: bool

    def to_dict(self) -> Mapping[str, Any]:
        """Fixed-key deterministic dict (audit-friendly, no floats/clock)."""
        return {
            "zip_raw": self.zip_raw,
            "state_raw": self.state_raw,
            "zip5": self.zip5,
            "state_code": self.state_code,
            "blank_state": self.blank_state,
            "invalid_state_format": self.invalid_state_format,
            "numeric_state_review": self.numeric_state_review,
            "unknown_state_code": self.unknown_state_code,
            "canonical_state_count": self.canonical_state_count,
            "cross_state_count": self.cross_state_count,
            "canonical_state": self.canonical_state,
            "cross_state": self.cross_state,
            "reference_resolved": self.reference_resolved,
            "zip_state_assessable": self.zip_state_assessable,
            "zip_state_match": self.zip_state_match,
            "zip_state_mismatch": self.zip_state_mismatch,
        }


def evaluate_geography(
    zip_raw: Any, state_raw: Any, provider: Any
) -> GeographyAssessment:
    """Evaluate one row's geography under the canonical SP1 contract."""
    zip_text = normalize_text(zip_raw)
    state_text = normalize_text(state_raw)
    state_code = state_text.upper()
    zip5 = compute_zip5(zip_text)

    blank = is_blank_state(state_code)
    invalid = is_invalid_state_format(state_text, state_code)
    numeric = is_numeric_state_review(state_code)
    unknown = is_unknown_state_code(state_code)

    resolution = resolve_reference(zip5, provider)

    assessable = (
        resolution.reference_resolved
        and not blank
        and not invalid
        and not numeric
        and not unknown
    )

    # zip_state_mismatch = same assessable conjunction
    #                      AND state_code != canonical_state.
    # A mismatch row is assessable by definition; when unassessable,
    # both match and mismatch are False (UNASSESSABLE != MISMATCH).
    mismatch = bool(assessable and state_code != resolution.canonical_state)
    match = bool(assessable and state_code == resolution.canonical_state)

    return GeographyAssessment(
        zip_raw=zip_text,
        state_raw=state_text,
        zip5=zip5,
        state_code=state_code,
        blank_state=blank,
        invalid_state_format=invalid,
        numeric_state_review=numeric,
        unknown_state_code=unknown,
        canonical_state_count=resolution.canonical_state_count,
        cross_state_count=resolution.cross_state_count,
        canonical_state=resolution.canonical_state,
        cross_state=resolution.cross_state,
        reference_resolved=resolution.reference_resolved,
        zip_state_assessable=assessable,
        zip_state_match=match,
        zip_state_mismatch=mismatch,
    )


# ---------------------------------------------------------------------------
# field_present (per-field evaluation; county/country are NOT DEFINED).
# ---------------------------------------------------------------------------

class FieldPresenceNotDefinedError(LookupError):
    """Raised for fields whose presence contract is NOT DEFINED.

    The company contract defines field_present for zip, state, city and
    address only. County and country are explicitly NOT DEFINED; this
    implementation refuses to invent presence logic for them.
    """


GEOGRAPHY_FIELDS_WITH_PRESENCE_CONTRACT: Tuple[str, ...] = (
    "zip",
    "state",
    "city",
    "address",
)


def field_present(field_name: str, row: Mapping[str, Any]) -> bool:
    """Per-field presence under the SP1 contract.

        field_present(zip)     = zip5 != ''
        field_present(state)   = NOT blank_state AND NOT invalid_state_format
                                 AND NOT numeric_state_review
                                 AND NOT unknown_state_code
        field_present(city)    = NOT blank_city
        field_present(address) = NOT blank_address
        field_present(county)  = NOT DEFINED   (refused - no invented logic)
        field_present(country) = NOT DEFINED   (refused - no invented logic)

    Evaluation is PER FIELD, not per row: a row with a valid state and a
    malformed ZIP is present for state-targeted selection and not present
    for ZIP-targeted selection.
    """
    name = str(field_name).strip().lower()
    if name == "zip":
        return compute_zip5(row.get("zip")) != ""
    if name == "state":
        state_text = normalize_text(row.get("state"))
        state_code = state_text.upper()
        return not (
            is_blank_state(state_code)
            or is_invalid_state_format(state_text, state_code)
            or is_numeric_state_review(state_code)
            or is_unknown_state_code(state_code)
        )
    if name == "city":
        return normalize_text(row.get("city")) != ""
    if name == "address":
        return normalize_text(row.get("address")) != ""
    if name in ("county", "country"):
        raise FieldPresenceNotDefinedError(
            "field_present(%s) is NOT DEFINED by the SP1 contract; "
            "no presence logic may be invented for it." % name
        )
    raise FieldPresenceNotDefinedError(
        "field_present(%s) has no contract definition." % field_name
    )


# ---------------------------------------------------------------------------
# SP1 eligibility (successor selection semantics).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SP1Decision:
    """Successor SP1 eligibility decision for one row.

    Exclusion policy (successor contract):

        exclude when geography_mismatch_candidate = 1
        OR NOT field_present(requested geography field)

    unlike the old rule, which also excluded rows for
    zip_state_assessable = 0 (UNASSESSABLE != MISMATCH).
    """

    requested_field: str
    field_present: bool
    mismatch_exclusion: bool
    eligible: bool
    exclusion_reasons: Tuple[str, ...]
    assessment: GeographyAssessment

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "requested_field": self.requested_field,
            "field_present": self.field_present,
            "mismatch_exclusion": self.mismatch_exclusion,
            "eligible": self.eligible,
            "exclusion_reasons": list(self.exclusion_reasons),
            "assessment": dict(self.assessment.to_dict()),
        }


def sp1_eligibility(
    requested_field: str,
    row: Mapping[str, Any],
    provider: Any,
) -> SP1Decision:
    """Successor SP1 selection decision for one row and one targeted field.

    The mismatch exclusion applies to EVERY targeted geography field
    supported by the rule; presence is evaluated per requested field.
    """
    assessment = evaluate_geography(row.get("zip"), row.get("state"), provider)
    present = field_present(requested_field, row)
    mismatch_exclusion = assessment.zip_state_mismatch
    reasons: Tuple[str, ...] = ()
    if mismatch_exclusion:
        reasons = reasons + ("geography_mismatch_candidate=1",)
    if not present:
        reasons = reasons + ("field_present(%s)=0" % requested_field,)
    eligible = not mismatch_exclusion and present
    return SP1Decision(
        requested_field=str(requested_field).strip().lower(),
        field_present=present,
        mismatch_exclusion=mismatch_exclusion,
        eligible=eligible,
        exclusion_reasons=reasons,
        assessment=assessment,
    )
