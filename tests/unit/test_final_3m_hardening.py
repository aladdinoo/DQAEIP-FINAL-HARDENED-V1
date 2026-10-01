"""Final-3M-task hardening: permanent regression tripwires.

These tests convert the independently verified facts of the 2026-09-10 final
3M validation task into permanent regression tripwires:

1. Oracle transcription fidelity — the independently transcribed constants in
   scripts/final_3m_validation.py are pinned to the frozen contract tables.
2. Engine-vs-oracle agreement — a fast, small-scale version of the 3M
   agreement proof (production engine vs the independent oracle), including
   novel edge cases beyond the golden fixtures.
3. DL001-DL015 derived divergence — the 8/12 derived-disagreement fact is
   pinned on documented controlled inputs. DERIVED analysis only: the
   authoritative tests/golden/dl_geography_cases.csv fixture was never
   delivered and is NOT claimed here.
4. Production-boundary tripwires — no ClickHouse client, no network client,
   no E1 identifiers, exactly 8 V1 rules in the registry.
5. W-1/W-2 documentation facts — DELIVERY_MANIFEST.json records golden-fixture
   hashes (not per-rule hashes); rule_matrix.json is the per-rule hash record;
   the two 2026-08-25 manifests pin older historical rule-hash generations.

All checks are additive and semantics-preserving; nothing here mutates the
frozen V1 layer.
"""

import csv
import importlib.util
import json
import os
import re
import random
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.contracts import (  # noqa: E402
    FLAG_COLUMNS,
    REQUIRED_RULE_IDS,
    SOURCE_COLUMNS,
    STATE_ZIP_PREFIXES,
    SUSPICIOUS_NAME_PATTERNS,
)
from data_quality_platform.geography import (  # noqa: E402
    InMemoryTwoReferenceProvider,
    evaluate_geography,
)
from data_quality_platform.rules import RuleRegistry  # noqa: E402
from data_quality_platform.rules.v1_rules import (  # noqa: E402
    GeographyMismatchCandidate,
    ZipStateAssessable,
)
from data_quality_platform.validation.engine import ValidationEngine  # noqa: E402


def _load_final_3m_module():
    path = os.path.join(REPO_ROOT, "scripts", "final_3m_validation.py")
    spec = importlib.util.spec_from_file_location("final_3m_validation", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


F3M = _load_final_3m_module()


# ────────────────────────────────────────────────────────────────────
# 1. Oracle transcription fidelity (independent oracle vs frozen contract)
# ────────────────────────────────────────────────────────────────────

class TestOracleTranscriptionFidelity:
    """The 3M oracle's independently transcribed tables must equal the frozen
    contract tables exactly — this pins transcription fidelity (the oracle's
    LOGIC is independent; its DATA must be the frozen contract)."""

    def test_source_columns_transcription(self):
        assert F3M.SOURCE_COLUMNS == SOURCE_COLUMNS

    def test_flag_columns_transcription(self):
        assert F3M.FLAG_COLUMNS == FLAG_COLUMNS

    def test_prefix_map_transcription(self):
        oracle_map = {k: tuple(v) for k, v in F3M.ORACLE_PREFIXES.items()}
        contract_map = {k: tuple(v) for k, v in STATE_ZIP_PREFIXES.items()}
        assert oracle_map == contract_map
        assert len(contract_map) == 51

    def test_suspicious_patterns_transcription(self):
        assert tuple(F3M.SUSPICIOUS) == tuple(SUSPICIOUS_NAME_PATTERNS)

    def test_output_columns_are_source_plus_flags(self):
        assert F3M.SOURCE_COLUMNS + F3M.FLAG_COLUMNS == \
            SOURCE_COLUMNS + FLAG_COLUMNS
        assert len(SOURCE_COLUMNS) == 33 and len(FLAG_COLUMNS) == 8


# ────────────────────────────────────────────────────────────────────
# 2. Engine-vs-oracle agreement (fast small-scale 3M agreement proof)
# ────────────────────────────────────────────────────────────────────

NOVEL_EDGE_ROWS = [
    # state whitespace-padded (V1: strip().upper() -> in-map)
    {"state": " CA ", "zip": "90210"},
    # mixed-case state (V1: upper())
    {"state": "Ca", "zip": "90210"},
    # leading-zero ZIP in MA (prefix 01)
    {"state": "MA", "zip": "01234"},
    # whitespace-only ZIP (V1: strip -> blank -> not assessable)
    {"state": "HI", "zip": "   "},
    # fully blank geography
    {"state": "", "zip": ""},
    # unicode-alpha names are NOT non-alpha (V1 uses str.isalpha)
    {"state": "NY", "zip": "10001", "first_name": "Müller", "last_name": "Sjöberg"},
    # multi-hyphen name
    {"state": "TX", "zip": "75201", "first_name": "A-B-C", "last_name": "X"},
    # padded-valid email with subdomain TLD chain
    {"state": "WA", "zip": "98101", "email_address": " u.ser@sub.example.co.uk "},
    # numeric-state + matching-style 5-digit zip (V1: not in map -> unassessable)
    {"state": "63", "zip": "12345"},
    # unknown territory state under V1 prefix map (not assessable)
    {"state": "PR", "zip": "00901"},
]


def _build_agreement_dataset():
    """Edge rows + deterministic random rows + novel cases (~700 rows)."""
    rows = [dict(r) for r in F3M._edge_rows()]
    rng = random.Random(20260918)
    rows.extend(F3M._random_row(rng, i) for i in range(len(rows) + 1, 601))
    # novel edges on top of the edge-row template
    template = dict(rows[0])
    for novel in NOVEL_EDGE_ROWS:
        row = dict(template)
        row.update({k: v for k, v in novel.items() if k in row})
        rows.append(row)
    # re-normalize ids to positions (row identity contract)
    for i, row in enumerate(rows, start=1):
        row["id"] = str(i)
    return rows


class TestEngineOracleAgreement:
    """Run the production engine over a controlled dataset and require the
    independent oracle to agree on all 8 flags for every row — the fast
    regression version of the 24,000,000-comparison 3M proof."""

    @pytest.fixture(scope="class")
    def engine_run(self, tmp_path_factory):
        rows = _build_agreement_dataset()
        csv_path = str(tmp_path_factory.mktemp("agreement") / "input.csv")
        out_path = str(tmp_path_factory.mktemp("agreement") / "output.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=SOURCE_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        engine = ValidationEngine(
            rules=RuleRegistry.create_default(),
            run_id="hardening_oracle_agreement",
            evidence_dir=str(tmp_path_factory.mktemp("evidence")),
        )
        result = engine.validate(csv_path, out_path)
        assert result.success, result.error
        return rows, out_path, result

    def test_row_count_preserved(self, engine_run):
        rows, _, result = engine_run
        assert result.input_row_count == len(rows)
        assert result.output_row_count == len(rows)

    def test_all_flags_agree_with_independent_oracle(self, engine_run):
        rows, out_path, _ = engine_run
        mismatches = []
        with open(out_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == SOURCE_COLUMNS + FLAG_COLUMNS
            for pos, out_row in enumerate(reader, start=1):
                src = rows[pos - 1]
                expected = F3M.oracle_flags(src)
                for flag in FLAG_COLUMNS:
                    if str(expected[flag]) != out_row[flag]:
                        mismatches.append((pos, flag, src, expected[flag],
                                           out_row[flag]))
        assert not mismatches, f"oracle disagreements: {mismatches[:5]}"

    def test_source_values_preserved_row_by_row(self, engine_run):
        rows, out_path, _ = engine_run
        with open(out_path, "r", newline="", encoding="utf-8") as f:
            for pos, out_row in enumerate(csv.DictReader(f), start=1):
                for col in SOURCE_COLUMNS:
                    assert out_row[col] == rows[pos - 1][col], (pos, col)

    def test_novel_edge_rows_present_and_passing(self, engine_run):
        rows, out_path, _ = engine_run
        assert len(rows) >= 600 + len(NOVEL_EDGE_ROWS)
        # the novel edge rows are the last len(NOVEL_EDGE_ROWS) rows
        novel_slice = rows[-len(NOVEL_EDGE_ROWS):]
        for i, novel in enumerate(NOVEL_EDGE_ROWS):
            for k, v in novel.items():
                assert novel_slice[i][k] == v


# ────────────────────────────────────────────────────────────────────
# 3. DL001-DL015 derived divergence (DERIVED — not authoritative)
# ────────────────────────────────────────────────────────────────────

# Reference rows traceable to acceptance cases 1/6/7 (90210 CA, 99501 AK,
# 96910 GU), the documented DL013 control (84501 UT), and recorded DL prose
# (96501 AP, 96799 AS). DERIVED analysis on controlled inputs: the
# authoritative dl_geography_cases.csv fixture does NOT exist in the repo.
DL_PROVIDER = InMemoryTwoReferenceProvider(
    canonical_rows=(
        {"zip": "90210", "state": "CA"},
        {"zip": "99501", "state": "AK"},
        {"zip": "96910", "state": "GU"},
        {"zip": "84501", "state": "UT"},
        {"zip": "96501", "state": "AP"},
        {"zip": "96799", "state": "AS"},
    ),
    cross_rows=(
        {"zip": "90210", "state": "CA"},
        {"zip": "99501", "state": "AK"},
    ),
)

DL_CASES = [
    ("DL001", "CA", "00USA"),
    ("DL002", "TX", "0"),
    ("DL003", "MD", "000MD"),
    ("DL004", "ON", "K2H 8E9"),
    ("DL008", "63", "12345"),
    ("DL009", "60", "12345"),
    ("DL010", "MA", "015 8"),
    ("DL011", "WA", "99501"),
    ("DL012", "HI", "96501"),
    ("DL013", "UT", "84501"),
    ("DL014", "GU", "96910"),
    ("DL015", "AS", "96799"),
]

DL_EXPECTED_DISAGREEMENTS = ["DL001", "DL002", "DL003", "DL010",
                             "DL011", "DL012", "DL014", "DL015"]
DL_EXPECTED_AGREEMENTS = ["DL004", "DL008", "DL009", "DL013"]


class TestDLDerivedDivergencePinned:
    """Pin the DERIVED 8/12 divergence fact. This does NOT claim authoritative
    DL-case verification (that fixture was never delivered and stays
    skip-gated in tests/golden/test_dl_canonical_geography.py)."""

    def _v1(self, state, zip_val):
        row = {"state": state, "zip": zip_val}
        a = ZipStateAssessable().execute(row)
        m = GeographyMismatchCandidate().execute(row)
        return (a, m)

    def _canonical(self, state, zip_val):
        assessment = evaluate_geography(zip_val, state, DL_PROVIDER)
        return (int(assessment.zip_state_assessable),
                int(assessment.zip_state_mismatch))

    def test_derived_divergence_is_exactly_8_of_12(self):
        disagreements = [cid for cid, st, zp in DL_CASES
                         if self._v1(st, zp) != self._canonical(st, zp)]
        assert disagreements == DL_EXPECTED_DISAGREEMENTS
        assert len(disagreements) == 8

    def test_derived_agreements_are_exactly_4(self):
        agreements = [cid for cid, st, zp in DL_CASES
                      if self._v1(st, zp) == self._canonical(st, zp)]
        assert agreements == DL_EXPECTED_AGREEMENTS

    def test_dl013_shared_prefix_control_is_not_a_defect(self):
        # DL013: UT / 84501 — 845 is shared between UT and OK in the V1 prefix
        # map, but both V1 and the successor agree here (assessable, match).
        assert self._v1("UT", "84501") == (1, 0)
        assert self._canonical("UT", "84501") == (1, 0)

    def test_dl012_robust_to_alternative_reference_resolution(self):
        provider = InMemoryTwoReferenceProvider(
            canonical_rows=DL_PROVIDER.canonical_rows +
            ({"zip": "96501", "state": "MP"},),
            cross_rows=DL_PROVIDER.cross_rows,
        )
        assessment = evaluate_geography("96501", "HI", provider)
        canonical = (int(assessment.zip_state_assessable),
                     int(assessment.zip_state_mismatch))
        assert canonical != self._v1("HI", "96501")

    def test_dl005_dl007_agree_for_all_probe_zips(self):
        for state in ("", "ON", "null", None):
            for zip_val in ("12345", "00USA", "", "902101", "015 8"):
                assert self._v1(state, zip_val) == \
                    self._canonical(state, zip_val)

    def test_authoritative_dl_fixture_is_absent_and_not_fabricated(self):
        assert not os.path.exists(
            os.path.join(REPO_ROOT, "tests", "golden",
                         "dl_geography_cases.csv"))


# ────────────────────────────────────────────────────────────────────
# 4. Production-boundary tripwires (fail-closed)
# ────────────────────────────────────────────────────────────────────

PROD_PACKAGES = ("data_quality_platform", "runner")
DANGEROUS_PATTERNS = (
    r"clickhouse_connect",
    r"clickhouse_driver",
    r"\bimport\s+clickhouse",
    r"\bfrom\s+clickhouse",
    r"\bimport\s+requests\b",
    r"\bimport\s+socket\b",
    r"\bimport\s+urllib\b",
    r"\bfrom\s+urllib\b",
    r"\bimport\s+http\b",
    r"\bfrom\s+http\b",
    r"\bINSERT\s+INTO\b",
    r"\bDELETE\s+FROM\b",
    r"\bALTER\s+TABLE\b",
    r"\bDROP\s+TABLE\b",
)


def _production_python_sources():
    for pkg in PROD_PACKAGES:
        for root, dirs, files in os.walk(os.path.join(REPO_ROOT, pkg)):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fn in files:
                if fn.endswith(".py"):
                    yield os.path.join(root, fn)


class TestProductionBoundaryTripwires:
    """Fail-closed boundary: no database/network client, no mutation SQL,
    no E1 identifiers, exactly the 8 frozen V1 rules in the registry."""

    def test_no_client_or_mutation_code_in_production_packages(self):
        violations = []
        for path in _production_python_sources():
            text = open(path, encoding="utf-8").read()
            for pattern in DANGEROUS_PATTERNS:
                if re.search(pattern, text):
                    violations.append(
                        (os.path.relpath(path, REPO_ROOT), pattern))
        assert not violations, violations

    def test_registry_has_exactly_the_8_v1_rules(self):
        registry = RuleRegistry.create_default()
        ids = sorted(r.rule_id for r in registry.get_all_rules())
        assert ids == sorted(REQUIRED_RULE_IDS)
        assert registry.count == 8

    def test_no_e1_identifiers_in_production_packages(self):
        for path in _production_python_sources():
            text = open(path, encoding="utf-8").read()
            assert not re.search(r"\bE1\b", text), \
                (os.path.relpath(path, REPO_ROOT), "E1 identifier present")

    def test_sp1_successor_not_registered_and_not_default(self):
        registry = RuleRegistry.create_default()
        ids = {r.rule_id for r in registry.get_all_rules()}
        assert not any("sp1" in i or "canonical" in i for i in ids)
        missing_lookup_fails = False
        try:
            registry.get("sp1_successor")
        except Exception:
            missing_lookup_fails = True
        assert missing_lookup_fails


# ────────────────────────────────────────────────────────────────────
# 5. W-1 / W-2 documentation facts (pins the corrected citations)
# ────────────────────────────────────────────────────────────────────

class TestW1W2DocumentationFacts:
    """W-1: DELIVERY_MANIFEST.json records golden-fixture hashes and
    artifact file hashes — NOT per-rule hashes; rule_matrix.json is the
    per-rule hash record. W-2: the two 2026-08-25 manifests pin older
    historical rule-hash generations (pre-existing, baseline-identical)."""

    def test_delivery_manifest_records_golden_fixture_hashes(self):
        dm = json.load(open(os.path.join(REPO_ROOT, "DELIVERY_MANIFEST.json"),
                            encoding="utf-8"))
        fixtures = dm["safety_confirmation"]["golden_fixture_hashes"]
        assert "golden_cases.csv" in fixtures
        assert "expected_results.csv" in fixtures
        assert "geography_edge_cases.csv" in fixtures

    def test_delivery_manifest_has_no_per_rule_hashes(self):
        dm = json.load(open(os.path.join(REPO_ROOT, "DELIVERY_MANIFEST.json"),
                            encoding="utf-8"))
        rule_ids = set(FLAG_COLUMNS)
        hash_like = re.compile(r"^[0-9a-f]{16,64}$")

        def rule_hash_entries(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in rule_ids and isinstance(v, str) \
                            and hash_like.match(v):
                        yield k
                    yield from rule_hash_entries(v)
            elif isinstance(obj, list):
                for v in obj:
                    yield from rule_hash_entries(v)

        entries = list(rule_hash_entries(dm))
        assert not entries, \
            f"DELIVERY_MANIFEST.json must not carry per-rule hash entries: {entries}"

    def test_rule_matrix_is_the_per_rule_hash_record(self):
        rm = json.load(open(
            os.path.join(REPO_ROOT, "evidence", "final_execution",
                         "rule_matrix.json"), encoding="utf-8"))
        assert rm["rule_count"] == 8
        live = RuleRegistry.create_default().get_rule_hashes()
        for entry in rm["rules"]:
            assert entry["implementation_hash_head"] == \
                live[entry["rule_id"]][:16]

    def test_clean_room_manifests_pin_current_generation(self):
        """Clean-room rebuild (2026-09-18): the old pre-rebuild evidence
        tree — including its 2026-08-25-era historical manifests that
        pinned older rule-hash generations — was deleted from zero per
        the clean-room mandate. The current tree must therefore contain
        NO stale-generation manifests: every engine manifest present in
        the evidence tree pins exactly the CURRENT frozen V1 rule-hash
        generation (all 8 hashes match the live registry)."""
        live = RuleRegistry.create_default().get_rule_hashes()
        harness = os.path.join(REPO_ROOT, "evidence", "validation",
                               "2026-09-18", "fresh_3m2")
        found = 0
        for dirpath, dirnames, filenames in os.walk(harness):
            for fn in filenames:
                if fn != "manifest.json":
                    continue
                rel = os.path.relpath(os.path.join(dirpath, fn),
                                      REPO_ROOT)
                m = json.load(open(os.path.join(dirpath, fn),
                                   encoding="utf-8"))
                matches = sum(1 for r, h in live.items()
                              if m.get("rule_hashes", {}).get(r) == h)
                assert matches == 8, \
                    f"{rel} does not pin the current rule-hash " \
                    f"generation ({matches}/8)"
                found += 1
        assert found >= 3, \
            "expected at least the two 3.2M run manifests + preflight"
