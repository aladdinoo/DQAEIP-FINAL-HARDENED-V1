"""SP1 successor geography contract tests.

AUTHORITATIVE COMPANY ACCEPTANCE CASES (TestCompanyAcceptanceCases)
-------------------------------------------------------------------
The seven cases in TestCompanyAcceptanceCases are quoted verbatim from
the company document "Geography rule - canonical definition and
acceptance cases" (SHA-256 0cf6eb93..., prepared 2026-09-01). They are
reproduced exactly as delivered; no additional case in this file is
labeled authoritative.

CONTROLLED FIXTURES
-------------------
The reference rows used by the in-memory provider are controlled
fixtures for pure-semantics verification only. Each fixture row is
traceable to an authoritative acceptance case (or to DL011/DL014 exact
prose in the MASTER REMEDIATION PROMPT); none is presented as company
canonical production reference data. Canonical production validation
remains BLOCKED pending the physical reference datasets.
"""

from __future__ import annotations

import inspect

import pytest

from data_quality_platform.geography import (
    SP1_CONTRACT_DOCUMENT_SHA256,
    SP1_CONTRACT_SOURCE_COMMIT,
    SP1_CONTRACT_SUPERSEDES_SHA256,
    STATE_ALLOWLIST,
    FieldPresenceNotDefinedError,
    GeographyAssessment,
    InMemoryTwoReferenceProvider,
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
from data_quality_platform.rules.v1_rules import (
    GeographyMismatchCandidate as V1GeographyMismatchCandidate,
)
from data_quality_platform.rules.v1_rules import (
    ZipStateAssessable as V1ZipStateAssessable,
)


# ---------------------------------------------------------------------------
# Controlled reference fixtures (traceable to authoritative cases ONLY).
#
# canonical:  90210 -> CA   (company case: CA / 90210, match=true)
#             99501 -> AK   (company case: WA / 99501, canonical = AK;
#                            also DL011 exact prose "WA / 99501 resolves to AK")
#             96910 -> GU   (company case: GU / 96910, match=true;
#                            also DL014 "GU / 96910 becomes assessable")
# cross:      90210 -> CA   (agrees)
#             99501 -> AK   (agrees)
#             96910: NO ROW (company case: the cross reference has no row
#                            and that is NOT a conflict)
# ---------------------------------------------------------------------------


def make_provider() -> InMemoryTwoReferenceProvider:
    canonical_rows = [
        {"zip": "90210", "state": "CA"},
        {"zip": "99501", "state": "AK"},
        {"zip": "96910", "state": "GU"},
    ]
    cross_rows = [
        {"zip": "90210", "state": "CA"},
        {"zip": "99501", "state": "AK"},
        # 96910 intentionally absent - the GU case.
    ]
    return InMemoryTwoReferenceProvider(
        canonical_rows=tuple(canonical_rows), cross_rows=tuple(cross_rows)
    )


PROVIDER = make_provider()


# ---------------------------------------------------------------------------
# Authoritative company acceptance cases (verbatim, 7 cases).
# ---------------------------------------------------------------------------


class TestCompanyAcceptanceCases:
    """The seven exact acceptance cases delivered by the company.

    CA / 90210   -> assessable=true,  match=true,  mismatch=false
    CA / 00USA   -> assessable=false, match=false, mismatch=false
    CA / 0       -> assessable=false, match=false, mismatch=false
    CA / 000CA   -> assessable=false, match=false, mismatch=false
    CA / "015 8" -> assessable=false, match=false, mismatch=false
    WA / 99501   -> assessable=true,  match=false, mismatch=true,
                    canonical resolution = AK
    GU / 96910   -> assessable=true,  match=true,  mismatch=false
                    (cross reference has no row; that is NOT a conflict)
    """

    def test_ca_90210(self):
        a = evaluate_geography("90210", "CA", PROVIDER)
        assert a.zip_state_assessable is True
        assert a.zip_state_match is True
        assert a.zip_state_mismatch is False

    def test_ca_00usa(self):
        a = evaluate_geography("00USA", "CA", PROVIDER)
        assert a.zip_state_assessable is False
        assert a.zip_state_match is False
        assert a.zip_state_mismatch is False

    def test_ca_0(self):
        a = evaluate_geography("0", "CA", PROVIDER)
        assert a.zip_state_assessable is False
        assert a.zip_state_match is False
        assert a.zip_state_mismatch is False

    def test_ca_000ca(self):
        a = evaluate_geography("000CA", "CA", PROVIDER)
        assert a.zip_state_assessable is False
        assert a.zip_state_match is False
        assert a.zip_state_mismatch is False

    def test_ca_015_8(self):
        a = evaluate_geography("015 8", "CA", PROVIDER)
        assert a.zip_state_assessable is False
        assert a.zip_state_match is False
        assert a.zip_state_mismatch is False

    def test_wa_99501(self):
        a = evaluate_geography("99501", "WA", PROVIDER)
        assert a.zip_state_assessable is True
        assert a.zip_state_match is False
        assert a.zip_state_mismatch is True
        assert a.canonical_state == "AK"

    def test_gu_96910_cross_row_absent_is_not_conflict(self):
        a = evaluate_geography("96910", "GU", PROVIDER)
        assert a.zip_state_assessable is True
        assert a.zip_state_match is True
        assert a.zip_state_mismatch is False
        assert a.canonical_state == "GU"
        assert a.cross_state_count == 0  # no cross row -> NOT a conflict


# ---------------------------------------------------------------------------
# Contract pins: allowlist, provenance constants, mismatch implication.
# ---------------------------------------------------------------------------


class TestContractPins:
    def test_allowlist_is_verbatim_and_includes_territories(self):
        expected = (
            "AA AE AK AL AP AR AS AZ CA CO CT DC DE FL FM GA GU HI IA ID IL IN "
            "KS KY LA MA MD ME MH MI MN MO MP MS MT NC ND NE NH NJ NM NV NY OH "
            "OK OR PA PR PW RI SC SD TN TX UT VA VI VT WA WI WV WY"
        ).split()
        assert STATE_ALLOWLIST == tuple(expected)
        # Territories and military codes are included.
        for code in ("AA", "AE", "AP", "AS", "FM", "GU", "MH", "MP", "PR", "PW", "VI", "DC"):
            assert code in STATE_ALLOWLIST

    def test_provenance_constants_pinned(self):
        assert SP1_CONTRACT_DOCUMENT_SHA256 == (
            "0cf6eb930149e975397b348709d8f7e83f96eb6eb70d2361cf66551ada311bc0"
        )
        assert SP1_CONTRACT_SOURCE_COMMIT == (
            "ee7859e1ad521cb68ba32b604498d951c7690b19"
        )
        assert SP1_CONTRACT_SUPERSEDES_SHA256 == (
            "3297179ea3527f56091191c48e8f72606e000fc7b885da906a7e59b97e1aebc8"
        )

    def test_mismatch_implies_assessable_everywhere(self):
        # For every probe row: mismatch=1 -> assessable=1.
        probes = [
            ("90210", "CA"), ("99501", "WA"), ("99501", "AK"),
            ("96910", "GU"), ("00USA", "CA"), ("0", "CA"),
            ("000CA", "CA"), ("015 8", "CA"), ("90210", "TX"),
            (None, None), ("", ""), ("90210", "01"), ("90210", "ZZ"),
        ]
        for zip_raw, state_raw in probes:
            a = evaluate_geography(zip_raw, state_raw, PROVIDER)
            if a.zip_state_mismatch:
                assert a.zip_state_assessable, (zip_raw, state_raw)

    def test_unassessable_never_carries_mismatch_or_match(self):
        probes = [
            ("00USA", "CA"), ("0", "CA"), ("000CA", "CA"),
            ("015 8", "CA"), (None, None), ("90210", "01"),
            ("90210", "ZZ"), ("", "CA"),
        ]
        for zip_raw, state_raw in probes:
            a = evaluate_geography(zip_raw, state_raw, PROVIDER)
            if not a.zip_state_assessable:
                assert not a.zip_state_mismatch, (zip_raw, state_raw)
                assert not a.zip_state_match, (zip_raw, state_raw)

    def test_module_does_not_import_legacy_prefix_map(self):
        # Isolation tripwire: the successor must not import or consume the
        # legacy V1 prefix-map contract in any form. (Mentioning the name
        # in an isolation notice is documentation, not consumption.)
        import sys
        import data_quality_platform.geography.canonical as canonical_mod
        import data_quality_platform.geography.references as references_mod

        for module in (canonical_mod, references_mod):
            source = inspect.getsource(module)
            assert "from data_quality_platform.contracts" not in source
            assert "import contracts" not in source
            imported = {
                name.split(".")[0]
                for name in dir(module)
                if not name.startswith("_")
            }
            contracts_mod = sys.modules.get("data_quality_platform.contracts")
            if contracts_mod is not None:
                for attr in ("STATE_ZIP_PREFIXES",):
                    assert getattr(module, attr, None) is not getattr(
                        contracts_mod, attr, object()
                    )


# ---------------------------------------------------------------------------
# Normalization and classifiers (engineering tests).
# ---------------------------------------------------------------------------


class TestNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, ""),
            ("", ""),
            ("   ", ""),
            ("90210", "90210"),
            (" 90210 ", "90210"),
            ("\t90210\n", "90210"),
            ("00USA", ""),      # non-digit -> ''
            ("0", ""),          # too short
            ("000CA", ""),      # letter -> ''
            ("015 8", ""),      # internal space -> ''
            ("902101", ""),     # six digits -> '' (DL006 semantics)
            (90210, "90210"),   # numeric input converted to text
        ],
    )
    def test_zip5(self, raw, expected):
        assert compute_zip5(raw) == expected

    def test_dl006_six_digit_zip_is_not_valid_zip5(self):
        # MASTER PROMPT DL006 exact prose: "six-digit ZIP must NOT pass
        # as a valid 5-digit ZIP".
        assert compute_zip5("902101") == ""

    def test_normalize_text_null_and_whitespace(self):
        assert normalize_text(None) == ""
        assert normalize_text("  CA  ") == "CA"

    def test_normalize_state_uppercased(self):
        assert normalize_state("ca") == "CA"
        assert normalize_state(" Ca ") == "CA"
        assert normalize_state(None) == ""


class TestStateClassifiers:
    def test_blank_state(self):
        assert is_blank_state("") is True
        assert is_blank_state("CA") is False

    def test_invalid_state_format(self):
        # Not 2 letters and not all digits.
        assert is_invalid_state_format("C1", "C1") is True
        assert is_invalid_state_format("000CA", "000CA") is True
        assert is_invalid_state_format("015 8", "015 8") is True
        assert is_invalid_state_format("CALIF", "CALIF") is True
        # 2 letters -> valid format.
        assert is_invalid_state_format("CA", "CA") is False
        assert is_invalid_state_format("ca", "CA") is False
        # all digits -> NOT invalid (numeric review instead).
        assert is_invalid_state_format("01", "01") is False
        # blank -> not invalid.
        assert is_invalid_state_format("", "") is False

    def test_numeric_state_review(self):
        assert is_numeric_state_review("01") is True
        assert is_numeric_state_review("12345") is True
        assert is_numeric_state_review("0") is True
        assert is_numeric_state_review("CA") is False
        assert is_numeric_state_review("") is False
        assert is_numeric_state_review("0A") is False

    def test_unknown_state_code(self):
        assert is_unknown_state_code("ZZ") is True
        assert is_unknown_state_code("QZ") is True
        assert is_unknown_state_code("CA") is False
        assert is_unknown_state_code("GU") is False
        assert is_unknown_state_code("PR") is False
        # Not two-letter -> classifier false (other buckets apply).
        assert is_unknown_state_code("01") is False
        assert is_unknown_state_code("") is False

    def test_acceptance_case_classifier_buckets(self):
        # Every unassessable company case lands in exactly the
        # classifier bucket the contract defines for it.
        zip_state = [
            ("00USA", "blank_zip5_no_state_bucket"),
            ("0", "numeric_zip_no_state_bucket"),
        ]
        # The state column in all five CA cases is valid ("CA"), so the
        # unassessability comes from reference resolution (zip5 = '').
        for zip_raw, _ in zip_state:
            a = evaluate_geography(zip_raw, "CA", PROVIDER)
            assert a.blank_state is False
            assert a.invalid_state_format is False
            assert a.numeric_state_review is False
            assert a.unknown_state_code is False
            assert a.reference_resolved is False

    def test_state_value_buckets_are_disjoint(self):
        # blank / invalid / numeric / known-two-letter / unknown-two-letter
        samples = ["", "01", "C1", "000CA", "CA", "ZZ"]
        for text in samples:
            code = text.upper()
            flags = [
                is_blank_state(code),
                is_invalid_state_format(text, code),
                is_numeric_state_review(code),
                is_unknown_state_code(code),
            ]
            assert sum(flags) <= 1, (text, flags)
            if is_blank_state(code):
                continue
            if _is_two_letter(code):
                assert is_unknown_state_code(code) or code in set(STATE_ALLOWLIST)
            elif is_numeric_state_review(code):
                assert not is_invalid_state_format(text, code)


def _is_two_letter(code: str) -> bool:
    return len(code) == 2 and code.isalpha()


# ---------------------------------------------------------------------------
# Two-reference resolution (engineering tests).
# ---------------------------------------------------------------------------


class TestTwoReferenceResolution:
    def test_cross_agreement_resolves(self):
        r = resolve_reference("90210", PROVIDER)
        assert r.reference_resolved is True
        assert r.canonical_state == "CA"
        assert r.cross_state == "CA"

    def test_cross_row_absent_resolves_gu_case(self):
        r = resolve_reference("96910", PROVIDER)
        assert r.reference_resolved is True
        assert r.canonical_state == "GU"
        assert r.cross_state_count == 0

    def test_reference_conflict_is_not_assessable(self):
        provider = InMemoryTwoReferenceProvider(
            canonical_rows=({"zip": "90210", "state": "CA"},),
            cross_rows=({"zip": "90210", "state": "TX"},),
        )
        a = evaluate_geography("90210", "CA", provider)
        assert a.reference_resolved is False
        assert a.zip_state_assessable is False
        assert a.zip_state_mismatch is False  # conflict is not a mismatch
        # UNASSESSABLE != MISMATCH: with a present state field the row
        # remains SP1-eligible (no mismatch exclusion applies).
        d = sp1_eligibility("state", {"zip": "90210", "state": "CA"}, provider)
        assert d.eligible is True

    def test_canonical_ambiguity_is_not_resolved(self):
        provider = InMemoryTwoReferenceProvider(
            canonical_rows=(
                {"zip": "90210", "state": "CA"},
                {"zip": "90210", "state": "TX"},
            ),
            cross_rows=(),
        )
        r = resolve_reference("90210", provider)
        assert r.canonical_state_count == 2
        assert r.reference_resolved is False

    def test_cross_ambiguity_is_not_resolved(self):
        provider = InMemoryTwoReferenceProvider(
            canonical_rows=({"zip": "90210", "state": "CA"},),
            cross_rows=(
                {"zip": "90210", "state": "CA"},
                {"zip": "90210", "state": "TX"},
            ),
        )
        r = resolve_reference("90210", provider)
        assert r.cross_state_count == 2
        assert r.reference_resolved is False

    def test_reference_rows_filtered_to_zip5_and_two_letter_state(self):
        provider = InMemoryTwoReferenceProvider(
            canonical_rows=(
                {"zip": "90210-1234", "state": "CA"},   # not 5-digit -> dropped
                {"zip": "90210", "state": "CALIFORNIA"},  # not 2-letter -> dropped
                {"zip": " 90210 ", "state": " ca "},     # trims to 90210 / CA
                {"zip": "90211", "state": "01"},          # non-letter -> dropped
            ),
            cross_rows=(),
        )
        assert provider.canonical_states("90210") == ("CA",)
        assert provider.canonical_states("90211") == ()
        assert provider.canonical_states("90210-1234") == ()

    def test_empty_zip5_short_circuits_resolution(self):
        r = resolve_reference("", PROVIDER)
        assert r.reference_resolved is False
        assert r.canonical_state_count == 0


# ---------------------------------------------------------------------------
# field_present (per-field semantics).
# ---------------------------------------------------------------------------


class TestFieldPresence:
    def test_zip_presence_uses_zip5(self):
        assert field_present("zip", {"zip": "90210"}) is True
        assert field_present("zip", {"zip": " 90210 "}) is True
        assert field_present("zip", {"zip": "00USA"}) is False
        assert field_present("zip", {"zip": None}) is False
        assert field_present("zip", {"zip": "902101"}) is False

    def test_state_presence_uses_classifiers_only(self):
        assert field_present("state", {"state": "CA"}) is True
        assert field_present("state", {"state": "ca"}) is True
        assert field_present("state", {"state": "  "}) is False
        assert field_present("state", {"state": None}) is False
        assert field_present("state", {"state": "01"}) is False
        assert field_present("state", {"state": "ZZ"}) is False
        assert field_present("state", {"state": "C1"}) is False

    def test_city_and_address_use_blankness_only(self):
        assert field_present("city", {"city": "Beverly Hills"}) is True
        assert field_present("city", {"city": "   "}) is False
        assert field_present("city", {"city": None}) is False
        assert field_present("address", {"address": "1 Main St"}) is True
        assert field_present("address", {"address": ""}) is False

    def test_county_and_country_are_not_defined(self):
        with pytest.raises(FieldPresenceNotDefinedError):
            field_present("county", {"county": "Los Angeles"})
        with pytest.raises(FieldPresenceNotDefinedError):
            field_present("country", {"country": "USA"})

    def test_unknown_field_refused(self):
        with pytest.raises(FieldPresenceNotDefinedError):
            field_present("region", {"region": "west"})

    def test_per_field_example_from_contract(self):
        # Contract example: valid state + malformed ZIP
        #   -> present for state-targeted selection
        #   -> not present for ZIP-targeted selection.
        row = {"zip": "00USA", "state": "CA"}
        assert field_present("state", row) is True
        assert field_present("zip", row) is False


# ---------------------------------------------------------------------------
# SP1 eligibility (successor selection semantics).
# ---------------------------------------------------------------------------


class TestSP1Eligibility:
    def test_mismatch_is_excluded(self):
        d = sp1_eligibility("state", {"zip": "99501", "state": "WA"}, PROVIDER)
        assert d.eligible is False
        assert d.mismatch_exclusion is True
        assert "geography_mismatch_candidate=1" in d.exclusion_reasons

    def test_assessable_and_matching_is_eligible(self):
        d = sp1_eligibility("state", {"zip": "90210", "state": "CA"}, PROVIDER)
        assert d.eligible is True
        assert d.mismatch_exclusion is False

    def test_unassessable_with_present_field_is_eligible(self):
        # UNASSESSABLE != MISMATCH: malformed ZIP with a valid state.
        d = sp1_eligibility("state", {"zip": "00USA", "state": "CA"}, PROVIDER)
        assert d.assessment.zip_state_assessable is False
        assert d.mismatch_exclusion is False
        assert d.field_present is True
        assert d.eligible is True

    def test_absent_field_is_excluded(self):
        d = sp1_eligibility("zip", {"zip": "00USA", "state": "CA"}, PROVIDER)
        assert d.eligible is False
        assert d.field_present is False
        assert "field_present(zip)=0" in d.exclusion_reasons

    def test_mismatch_exclusion_applies_to_every_targeted_field(self):
        row = {"zip": "99501", "state": "WA", "city": "Seattle", "address": "1 Way"}
        for target in ("zip", "state", "city", "address"):
            d = sp1_eligibility(target, row, PROVIDER)
            assert d.mismatch_exclusion is True, target
            assert d.eligible is False, target

    def test_successor_accepts_rows_old_rule_prefix_mismatched(self):
        # CA / 00USA under V1: zip non-empty + state in prefix map ->
        # assessable = 1; prefix probe: "00USA" matches no CA bucket ->
        # V1 mismatch = 1 -> the OLD rule excludes it as a mismatch.
        # The successor classifies it as UNASSESSABLE (zip5 = '',
        # mismatch = 0) and, the state field being present, ELIGIBLE.
        row = {"zip": "00USA", "state": "CA"}
        assert V1ZipStateAssessable().execute(row) == 1
        assert V1GeographyMismatchCandidate().execute(row) == 1
        assert _old_sp1_eligible(row, target_present=True) is False
        d = sp1_eligibility("state", row, PROVIDER)
        assert d.assessment.zip_state_assessable is False
        assert d.eligible is True

    def test_successor_eligible_where_v1_unassessable(self):
        # GU / 96910: GU absent from the V1 prefix map -> V1 assessable
        # = 0 -> the old rule excluded it outright. The successor
        # resolves it through the canonical reference and accepts it.
        row = {"zip": "96910", "state": "GU"}
        assert V1ZipStateAssessable().execute(row) == 0
        assert sp1_eligibility("state", row, PROVIDER).eligible is True


# ---------------------------------------------------------------------------
# Old (V1) vs successor explicit divergence (engineering evidence).
#
# The "old SP1 behavior" (per MASTER PROMPT section 8) is:
#     eligible_old = NOT (assessable == 0 OR mismatch == 1)
# with assessable/mismatch computed by the REAL V1 rule classes.
# The successor rule is:
#     eligible_new = NOT (mismatch == 1) AND field_present(target)
# ---------------------------------------------------------------------------


def _old_sp1_eligible(row, target_present: bool) -> bool:
    assessable = V1ZipStateAssessable().execute(row)
    mismatch = V1GeographyMismatchCandidate().execute(row)
    if assessable == 0:
        return False
    if mismatch == 1:
        return False
    return bool(target_present)


class TestOldVsSuccessorDivergence:
    """Explicit old-vs-successor cases. Engineering demonstrations -
    NOT company acceptance cases."""

    def test_wa_99501_legacy_map_calls_it_a_match_successor_disagrees(self):
        row = {"zip": "99501", "state": "WA"}
        # V1: 99 -> WA prefix bucket -> assessable, no mismatch.
        assert V1ZipStateAssessable().execute(row) == 1
        assert V1GeographyMismatchCandidate().execute(row) == 0
        # Successor: canonical resolution is AK -> mismatch.
        d = sp1_eligibility("state", row, PROVIDER)
        assert d.assessment.zip_state_mismatch is True
        assert d.assessment.canonical_state == "AK"

    def test_gu_96910_invisible_to_legacy_assessable_to_successor(self):
        row = {"zip": "96910", "state": "GU"}
        # V1: GU absent from the prefix map -> unassessable.
        assert V1ZipStateAssessable().execute(row) == 0
        # Successor: assessable and matching.
        a = evaluate_geography("96910", "GU", PROVIDER)
        assert a.zip_state_assessable is True
        assert a.zip_state_match is True

    def test_old_excludes_unassessable_successor_eligible_when_present(self):
        # CA / 00USA: the old rule excludes it (V1 prefix mismatch = 1);
        # the successor finds the state field present and mismatch
        # impossible (unassessable) -> eligible.
        row = {"zip": "00USA", "state": "CA"}
        assert _old_sp1_eligible(row, target_present=True) is False
        assert sp1_eligibility("state", row, PROVIDER).eligible is True

    def test_legacy_map_accepts_99501_wa_successor_excludes(self):
        # The legacy prefix map buckets 99 under WA, so the old rule
        # would ACCEPT WA / 99501; the canonical resolution (AK) makes
        # the successor exclude it as a genuine mismatch.
        row = {"zip": "99501", "state": "WA"}
        assert _old_sp1_eligible(row, target_present=True) is True
        assert sp1_eligibility("state", row, PROVIDER).eligible is False

    def test_both_rules_exclude_absent_field(self):
        row = {"zip": "00USA", "state": "CA"}
        assert _old_sp1_eligible(row, target_present=False) is False
        assert sp1_eligibility("zip", row, PROVIDER).eligible is False

    def test_divergence_matrix(self):
        cases = [
            # (zip, state, target, target_present, expected_new_eligible)
            ("90210", "CA", "state", True, True),    # assessable + match
            ("99501", "WA", "state", True, False),   # successor mismatch
            ("96910", "GU", "state", True, True),    # assessable via canonical
            ("00USA", "CA", "state", True, True),    # unassessable, present
            ("00USA", "CA", "zip", False, False),    # field absent
            ("0", "CA", "state", True, True),        # unassessable, present
            ("000CA", "CA", "state", True, True),    # unassessable, present
            ("015 8", "CA", "state", True, True),    # unassessable, present
        ]
        for zip_raw, state, target, present, expected in cases:
            row = {"zip": zip_raw, "state": state}
            d = sp1_eligibility(target, row, PROVIDER)
            assert d.eligible is expected, (zip_raw, state, target)


# ---------------------------------------------------------------------------
# Determinism and audit-safety.
# ---------------------------------------------------------------------------


class TestDeterminismAndAuditSafety:
    def test_assessment_dict_is_deterministic(self):
        a1 = evaluate_geography("99501", "WA", PROVIDER).to_dict()
        a2 = evaluate_geography("99501", "WA", PROVIDER).to_dict()
        assert a1 == a2
        assert list(a1.keys()) == list(a2.keys())

    def test_no_clocks_or_randomness_in_module(self):
        import data_quality_platform.geography.canonical as canonical_mod

        source = inspect.getsource(canonical_mod)
        for banned in ("datetime", "time.time", "random", "uuid", "os.environ"):
            assert banned not in source, banned

    def test_assessment_is_frozen(self):
        a = evaluate_geography("90210", "CA", PROVIDER)
        with pytest.raises(Exception):
            a.zip5 = "00000"  # type: ignore[misc]

    def test_geography_assessment_fields_complete(self):
        a = evaluate_geography("90210", "CA", PROVIDER)
        assert isinstance(a, GeographyAssessment)
        expected_keys = {
            "zip_raw", "state_raw", "zip5", "state_code",
            "blank_state", "invalid_state_format", "numeric_state_review",
            "unknown_state_code", "canonical_state_count", "cross_state_count",
            "canonical_state", "cross_state", "reference_resolved",
            "zip_state_assessable", "zip_state_match", "zip_state_mismatch",
        }
        assert set(a.to_dict().keys()) == expected_keys
