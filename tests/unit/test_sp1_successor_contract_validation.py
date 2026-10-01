"""SP1 successor contract - 2026-09-10 integration validation tests.

SCOPE
-----
New test evidence added by the 2026-09-10 "GEOGRAPHY SUCCESSOR CONTRACT
INTEGRATION" task. This file ADDS coverage; it does not modify or weaken any
pre-existing test. The single canonical implementation of the successor
contract remains ``data_quality_platform.geography`` (no business logic is
duplicated here - every test consumes that one implementation).

Coverage map (master prompt section 9, letters A-H):
    A. ZIP presence        -> TestZipPresenceMatrix
    B. State presence      -> TestStatePresenceMatrix
    C. City presence       -> TestCityAddressPresenceMatrix
    D. Address presence    -> TestCityAddressPresenceMatrix
    E. Reference behavior  -> TestReferenceBehaviorMatrix
    F. Mismatch behavior   -> TestMismatchBehaviorMatrix
    G. Field-specific SP1  -> TestSP1FieldSpecificSelection
    H. Out-of-scope        -> TestOutOfScopeFields

Additional 2026-09-10 evidence:
    - Provenance additions (section 13) -> TestProvenanceAdditions20260918
    - SP1 status boundary (section 12)  -> TestSP1StatusBoundary
    - E1 non-implementation (section 15) -> TestE1Boundary

CONTROLLED FIXTURES: the in-memory provider rows below are traceable to the
authoritative company acceptance cases (90210->CA, 99501->AK, 96910->GU) and
to the DL013 control prose ("84501 resolves to Utah", master prompt section
10). They are validation fixtures only - NOT company canonical production
reference data, and no canonical production validation is claimed.
"""

from __future__ import annotations

import json
import os

import pytest

from data_quality_platform.geography import (
    SP1_CONTRACT_DECISION_RECORD_V2_SHA256,
    SP1_CONTRACT_PINNED_TEMPLATE_SHA256,
    SP1_CONTRACT_SOURCE_COMMIT,
    SP1_CONTRACT_V3_SHA256,
    SP1_GEOGRAPHY_RULE_SUMMARY_SHA256,
    SP1_MANUAL_DELIVERY_MANIFEST,
    SP1_RECIPIENT_RECEIPT,
    STATE_ALLOWLIST,
    FieldPresenceNotDefinedError,
    InMemoryTwoReferenceProvider,
    evaluate_geography,
    field_present,
    sp1_eligibility,
)

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def make_provider() -> InMemoryTwoReferenceProvider:
    """Controlled fixture provider (acceptance cases + DL013 control prose).

    canonical:  90210 -> CA   (acceptance case 1)
                99501 -> AK   (acceptance case 6 / DL011)
                96910 -> GU   (acceptance case 7 / DL014)
                84501 -> UT   (DL013 control case: "84501 resolves to Utah")
    cross:      90210 -> CA   (agrees)
                99501 -> AK   (agrees)
                84501 -> UT   (agrees)
                96910: NO ROW (case 7: absent cross row is not a conflict)
    """
    return InMemoryTwoReferenceProvider(
        canonical_rows=(
            {"zip": "90210", "state": "CA"},
            {"zip": "99501", "state": "AK"},
            {"zip": "96910", "state": "GU"},
            {"zip": "84501", "state": "UT"},
        ),
        cross_rows=(
            {"zip": "90210", "state": "CA"},
            {"zip": "99501", "state": "AK"},
            {"zip": "84501", "state": "UT"},
        ),
    )


PROVIDER = make_provider()


# ---------------------------------------------------------------------------
# A. ZIP presence
# ---------------------------------------------------------------------------


class TestZipPresenceMatrix:
    """field_present(zip) across the required ZIP-presence matrix."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("90210", True),       # valid 5-digit ZIP
            ("00USA", False),      # malformed ZIP
            ("", False),           # empty ZIP
            (None, False),         # NULL ZIP
            (" 90210 ", True),     # whitespace around valid ZIP
            ("\t90210\n", True),   # tab/newline whitespace
            ("902101", False),     # six-digit ZIP
            ("ABCDE", False),      # alphabetic ZIP
            ("000CA", False),      # alphanumeric malformed ZIP
            ("015 8", False),      # internal space
        ],
    )
    def test_zip_presence(self, raw, expected):
        assert field_present("zip", {"zip": raw}) is expected

    def test_zip_presence_is_zip5_not_blankness(self):
        # A non-blank but malformed ZIP is NOT present: presence requires
        # the zip5 predicate, not mere non-emptiness.
        assert field_present("zip", {"zip": "00USA"}) is False


# ---------------------------------------------------------------------------
# B. State presence
# ---------------------------------------------------------------------------


class TestStatePresenceMatrix:
    """field_present(state) across the required state-presence matrix."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("CA", True),          # valid state
            ("ca", True),          # lowercase state (upper-cased)
            ("  CA  ", True),      # surrounding whitespace
            ("\ttx\n", True),      # whitespace + lowercase
            ("63", False),         # numeric state
            ("60", False),         # numeric state
            ("C1", False),         # malformed state
            ("000CA", False),      # malformed state
            ("ZZ", False),         # unknown two-letter code
            ("ON", False),         # non-US two-letter code
            (None, False),         # NULL
            ("", False),           # blank
            ("   ", False),        # whitespace-only
        ],
    )
    def test_state_presence(self, raw, expected):
        assert field_present("state", {"state": raw}) is expected

    def test_state_presence_equals_valid_state_predicate(self):
        # field_present(state) == the assessability state-classifier
        # conjunction (blank/invalid/numeric/unknown all excluded).
        for raw in ("CA", "ca", " CA ", "63", "C1", "ZZ", "", None):
            row = {"zip": "90210", "state": raw}
            a = evaluate_geography(row["zip"], row["state"], PROVIDER)
            classifier_valid = not (
                a.blank_state
                or a.invalid_state_format
                or a.numeric_state_review
                or a.unknown_state_code
            )
            assert field_present("state", row) is classifier_valid, raw


# ---------------------------------------------------------------------------
# C + D. City / address presence
# ---------------------------------------------------------------------------


class TestCityAddressPresenceMatrix:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Beverly Hills", True),   # normal city
            ("   ", False),            # whitespace-only city
            ("", False),               # empty city
            (None, False),             # NULL city
            ("  Austin  ", True),      # surrounding whitespace
        ],
    )
    def test_city_presence(self, raw, expected):
        assert field_present("city", {"city": raw}) is expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("1 Main St", True),       # normal address
            ("   ", False),            # whitespace-only address
            ("", False),               # empty address
            (None, False),             # NULL address
            ("  1 Main St  ", True),   # surrounding whitespace
        ],
    )
    def test_address_presence(self, raw, expected):
        assert field_present("address", {"address": raw}) is expected


# ---------------------------------------------------------------------------
# E. Reference behavior
# ---------------------------------------------------------------------------


class TestReferenceBehaviorMatrix:
    def test_canonical_exactly_one_state_resolves(self):
        a = evaluate_geography("90210", "CA", PROVIDER)
        assert a.canonical_state_count == 1
        assert a.reference_resolved is True

    def test_canonical_multiple_states_not_resolved(self):
        provider = InMemoryTwoReferenceProvider(
            canonical_rows=(
                {"zip": "10001", "state": "NY"},
                {"zip": "10001", "state": "NJ"},
            ),
            cross_rows=(),
        )
        a = evaluate_geography("10001", "NY", provider)
        assert a.canonical_state_count == 2
        assert a.reference_resolved is False
        assert a.zip_state_assessable is False

    def test_cross_absent_resolves(self):
        a = evaluate_geography("96910", "GU", PROVIDER)
        assert a.cross_state_count == 0
        assert a.reference_resolved is True

    def test_cross_agrees_resolves(self):
        a = evaluate_geography("90210", "CA", PROVIDER)
        assert a.cross_state == "CA"
        assert a.reference_resolved is True

    def test_cross_conflicts_not_resolved_and_not_assessable(self):
        provider = InMemoryTwoReferenceProvider(
            canonical_rows=({"zip": "90210", "state": "CA"},),
            cross_rows=({"zip": "90210", "state": "TX"},),
        )
        a = evaluate_geography("90210", "CA", provider)
        assert a.reference_resolved is False
        assert a.zip_state_assessable is False
        assert a.zip_state_mismatch is False  # conflict != mismatch

    def test_unresolved_zip_not_resolved(self):
        # ZIP not present in the reference at all -> unresolved.
        a = evaluate_geography("99999", "CA", PROVIDER)
        assert a.canonical_state_count == 0
        assert a.reference_resolved is False
        assert a.zip_state_assessable is False

    def test_dl013_control_case_resolves_to_utah(self):
        # DL013 (UT / 84501) is a CONTROL CASE: 84501 resolves to UT and
        # a shared ZIP prefix must NOT be classified as erroneous.
        a = evaluate_geography("84501", "UT", PROVIDER)
        assert a.zip_state_assessable is True
        assert a.zip_state_match is True
        assert a.zip_state_mismatch is False
        assert a.canonical_state == "UT"


# ---------------------------------------------------------------------------
# F. Mismatch behavior
# ---------------------------------------------------------------------------


class TestMismatchBehaviorMatrix:
    PROBES = [
        ("90210", "CA"), ("99501", "WA"), ("99501", "AK"), ("96910", "GU"),
        ("84501", "UT"), ("84501", "NV"), ("00USA", "CA"), ("0", "CA"),
        ("000CA", "CA"), ("015 8", "CA"), ("90210", "TX"), ("99999", "CA"),
        (None, None), ("", ""), ("90210", "01"), ("90210", "ZZ"),
        ("", "CA"), ("90210", ""), ("96910", "WA"), ("84501", "WA"),
    ]

    def test_mismatch_only_when_assessable(self):
        for zip_raw, state_raw in self.PROBES:
            a = evaluate_geography(zip_raw, state_raw, PROVIDER)
            if a.zip_state_mismatch:
                assert a.zip_state_assessable, (zip_raw, state_raw)

    def test_unassessable_rows_never_become_mismatch(self):
        for zip_raw, state_raw in self.PROBES:
            a = evaluate_geography(zip_raw, state_raw, PROVIDER)
            if not a.zip_state_assessable:
                assert a.zip_state_mismatch is False, (zip_raw, state_raw)
                assert a.zip_state_match is False, (zip_raw, state_raw)

    def test_assessable_rows_are_match_or_mismatch_exclusively(self):
        for zip_raw, state_raw in self.PROBES:
            a = evaluate_geography(zip_raw, state_raw, PROVIDER)
            if a.zip_state_assessable:
                assert (a.zip_state_match + a.zip_state_mismatch) == 1, (
                    zip_raw, state_raw
                )


# ---------------------------------------------------------------------------
# G. Field-specific SP1 behavior
# ---------------------------------------------------------------------------


class TestSP1FieldSpecificSelection:
    def test_valid_state_with_malformed_zip(self):
        row = {"zip": "00USA", "state": "CA", "city": "Los Angeles",
               "address": "1 Main St"}
        d_state = sp1_eligibility("state", row, PROVIDER)
        d_zip = sp1_eligibility("zip", row, PROVIDER)
        assert d_state.eligible is True   # state present, no mismatch
        assert d_zip.eligible is False    # ZIP not present

    def test_valid_zip_with_blank_state(self):
        row = {"zip": "90210", "state": "", "city": "Beverly Hills",
               "address": "1 Main St"}
        d_state = sp1_eligibility("state", row, PROVIDER)
        d_zip = sp1_eligibility("zip", row, PROVIDER)
        # State-targeted: field absent -> excluded.
        assert d_state.eligible is False
        assert d_state.field_present is False
        # ZIP-targeted: ZIP present, row unassessable (blank state) so no
        # mismatch exclusion is possible -> eligible.
        assert d_zip.eligible is True
        assert d_zip.field_present is True
        assert d_zip.mismatch_exclusion is False

    def test_valid_city_with_no_zip(self):
        row = {"zip": None, "state": "CA", "city": "Sacramento",
               "address": "1 Capitol Ave"}
        d_city = sp1_eligibility("city", row, PROVIDER)
        d_zip = sp1_eligibility("zip", row, PROVIDER)
        assert d_city.eligible is True    # city present, unassessable != mismatch
        assert d_zip.eligible is False    # no ZIP

    def test_valid_address_with_no_zip(self):
        row = {"zip": "", "state": "CA", "city": "Sacramento",
               "address": "1 Capitol Ave"}
        d_address = sp1_eligibility("address", row, PROVIDER)
        d_zip = sp1_eligibility("zip", row, PROVIDER)
        assert d_address.eligible is True
        assert d_zip.eligible is False

    def test_each_requested_field_evaluated_independently(self):
        # One row, four different per-field outcomes (the master prompt
        # example: presence is PER FIELD, never once per row).
        row = {"zip": "00USA", "state": "CA", "city": "   ",
               "address": "1 Main St"}
        outcomes = {
            target: sp1_eligibility(target, row, PROVIDER).eligible
            for target in ("zip", "state", "city", "address")
        }
        assert outcomes == {"zip": False, "state": True,
                            "city": False, "address": True}

    def test_mismatch_exclusion_applies_to_all_fields_when_mismatch(self):
        row = {"zip": "99501", "state": "WA", "city": "Seattle",
               "address": "1 Way"}
        for target in ("zip", "state", "city", "address"):
            d = sp1_eligibility(target, row, PROVIDER)
            assert d.mismatch_exclusion is True, target
            assert d.eligible is False, target

    def test_no_row_wide_geography_shortcut(self):
        # A row with an absent field must be excluded for THAT field even
        # when another geography field is present and the row is otherwise
        # assessable-and-matching.
        row = {"zip": "90210", "state": "CA", "city": "", "address": None}
        assert sp1_eligibility("zip", row, PROVIDER).eligible is True
        assert sp1_eligibility("state", row, PROVIDER).eligible is True
        assert sp1_eligibility("city", row, PROVIDER).eligible is False
        assert sp1_eligibility("address", row, PROVIDER).eligible is False


# ---------------------------------------------------------------------------
# H. Out-of-scope fields
# ---------------------------------------------------------------------------


class TestOutOfScopeFields:
    def test_county_not_defined(self):
        with pytest.raises(FieldPresenceNotDefinedError):
            field_present("county", {"county": "Los Angeles"})

    def test_country_not_defined(self):
        with pytest.raises(FieldPresenceNotDefinedError):
            field_present("country", {"country": "USA"})

    def test_no_presence_functionality_created_for_out_of_scope(self):
        # The presence contract covers exactly zip/state/city/address.
        from data_quality_platform.geography import (
            GEOGRAPHY_FIELDS_WITH_PRESENCE_CONTRACT,
        )
        assert set(GEOGRAPHY_FIELDS_WITH_PRESENCE_CONTRACT) == {
            "zip", "state", "city", "address"
        }


# ---------------------------------------------------------------------------
# Provenance additions (master prompt section 13, 2026-09-10 delivery)
# ---------------------------------------------------------------------------


class TestProvenanceAdditions20260918:
    def test_contract_v3_hash_pinned(self):
        assert SP1_CONTRACT_V3_SHA256 == (
            "8ae3256b362d218849a688cc8f0a76d86c4ffb886607f69848030c2e6ba1fe74"
        )

    def test_decision_record_v2_hash_pinned(self):
        assert SP1_CONTRACT_DECISION_RECORD_V2_SHA256 == (
            "4dd8914f4d5ed7ab47f5245fd762d9e06983e43aba0858d1e38b3c1cf21fac4c"
        )

    def test_pinned_template_hash_pinned(self):
        assert SP1_CONTRACT_PINNED_TEMPLATE_SHA256 == (
            "47b3361b22ee9882c17e70886c3d5e3c493107881ed9f86345b96c5aa1cd521a"
        )

    def test_source_commit_pinned(self):
        assert SP1_CONTRACT_SOURCE_COMMIT == (
            "ee7859e1ad521cb68ba32b604498d951c7690b19"
        )

    def test_geography_rule_summary_hash_pinned(self):
        # Company-provided value; physical file not in this repository and
        # not locally re-computable (recorded as provenance metadata).
        assert SP1_GEOGRAPHY_RULE_SUMMARY_SHA256 == (
            "410bbf294e20692db616962884523bd3ef67d13c3bef0771ac9b92d4c2b0b708"
        )

    def test_manual_delivery_manifest_is_provenance_not_evidence(self):
        # manual_delivery_v1 is the manual business-rule delivery manifest
        # identifier - it is NOT Evidence Manifest v1 and must never be
        # merged with execution evidence.
        assert SP1_MANUAL_DELIVERY_MANIFEST == "manual_delivery_v1"
        evidence_manifest = os.path.join(
            PROJECT_ROOT, "evidence", "final_execution", "EVIDENCE_MANIFEST.json"
        )
        if os.path.exists(evidence_manifest):
            with open(evidence_manifest, encoding="utf-8") as fh:
                content = fh.read()
            assert "manual_delivery_v1" not in content, (
                "manual_delivery_v1 must not be merged into the execution "
                "evidence manifest"
            )

    def test_recipient_receipt_not_verified(self):
        assert SP1_RECIPIENT_RECEIPT == "NOT VERIFIED"

    def test_measurements_and_contract_dates_pinned(self):
        from data_quality_platform.geography import (
            SP1_CONTRACT_MEASUREMENTS,
            SP1_CONTRACT_PREPARED,
        )
        assert SP1_CONTRACT_MEASUREMENTS == "2026-08-31"
        assert SP1_CONTRACT_PREPARED == "2026-09-01"

    def test_allowlist_remains_62_codes(self):
        assert len(set(STATE_ALLOWLIST)) == 62
        # 50 states + DC + territories + military codes.
        for code in ("CA", "WY", "DE", "IL", "GU", "AS", "AA", "AE", "AP"):
            assert code in STATE_ALLOWLIST


# ---------------------------------------------------------------------------
# SP1 status boundary (master prompt section 12)
# ---------------------------------------------------------------------------


class TestSP1StatusBoundary:
    def test_sp1_not_registered_in_default_registry(self):
        from data_quality_platform.rules import RuleRegistry

        registry = RuleRegistry.create_default()
        rule_ids = sorted(
            rule.rule_id for rule in registry.get_all_rules()
        )
        assert rule_ids == [
            "email_blank",
            "email_syntax_failure",
            "first_name_cleaning_candidate",
            "geography_mismatch_candidate",
            "last_name_cleaning_candidate",
            "name_cleaning_candidate",
            "proposed_email_export_eligible",
            "zip_state_assessable",
        ]
        assert not any("sp1" in rid.lower() for rid in rule_ids)

    def test_no_sp1_routing_in_engine_or_settings(self):
        # Static boundary check: the production validation engine and the
        # settings module must not reference the successor package.
        for rel in (
            "data_quality_platform/validation/engine.py",
            "data_quality_platform/config/settings.py",
            "runner/cli.py",
        ):
            path = os.path.join(PROJECT_ROOT, rel)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            assert "geography.canonical" not in source, rel
            assert "sp1_eligibility" not in source, rel
            assert "TwoReferenceProvider" not in source, rel

    def test_sp1_decision_records_status_fields(self):
        d = sp1_eligibility("state", {"zip": "90210", "state": "CA"}, PROVIDER)
        payload = d.to_dict()
        assert set(payload) == {
            "requested_field", "field_present", "mismatch_exclusion",
            "eligible", "exclusion_reasons", "assessment",
        }
        assert json.dumps(payload, sort_keys=True)  # deterministic + serializable


# ---------------------------------------------------------------------------
# E1 boundary (master prompt section 15 - NOT implemented, NOT executed)
# ---------------------------------------------------------------------------


class TestE1Boundary:
    def test_no_e1_mutation_logic_in_successor_package(self):
        geography_dir = os.path.join(
            PROJECT_ROOT, "data_quality_platform", "geography"
        )
        for name in os.listdir(geography_dir):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(geography_dir, name), encoding="utf-8") as fh:
                source = fh.read()
            for banned in (
                "INSERT INTO",
                "ALTER TABLE",
                "UPDATE ",
                "DELETE FROM",
                "TRUNCATE",
                "latitude",
                "longitude",
            ):
                assert banned not in source, (name, banned)

    def test_no_e1_identifiers_in_production_packages(self):
        # E1 (latitude/longitude backfill) is not implemented anywhere in
        # the production packages.
        for package in ("data_quality_platform", "runner"):
            base = os.path.join(PROJECT_ROOT, package)
            for dirpath, _dirnames, filenames in os.walk(base):
                for name in filenames:
                    if not name.endswith(".py"):
                        continue
                    path = os.path.join(dirpath, name)
                    with open(path, encoding="utf-8") as fh:
                        source = fh.read()
                    for banned in ("e1_", "E1_", "experiment_e1", "E1Experiment"):
                        assert banned not in source, (path, banned)
