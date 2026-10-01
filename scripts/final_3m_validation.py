#!/usr/bin/env python3
"""FINAL 3M VALIDATION — independent validation harness, FAIL-CLOSED edition.

Purpose
-------
Execute a REAL, fresh 3,000,000-row validation of the frozen V1 pipeline and
independently verify the results with a from-scratch oracle.

Independence statement
----------------------
- This script has ZERO imports from data_quality_platform / runner.
- The production path is exercised ONLY as a subprocess of the canonical CLI
  (``runner.cli validate ...``), executed as ``__main__`` inside the audit-hook
  runtime-safety wrapper ``scripts/final_3m_runtime_safety_wrapper.py``
  (identical entrypoint and argv to ``python -m runner.cli validate ...``).
- The ORACLE below re-implements all 8 V1 predicates from the documented frozen
  contract with an independently written code path. It does NOT call any
  production rule function. The STATE_ZIP_PREFIXES table is transcribed as a
  frozen data constant of the contract (a pytest regression test cross-checks
  the transcription against data_quality_platform.contracts).
- Semantics notes for the oracle:
  * names: suspicious-substring (case-insensitive), non-alpha (Unicode-aware
    ``str.isalpha`` + hyphen + apostrophe allowed — same predicate family as the
    frozen engine), repeated-single-char after removing hyphen/apostrophe.
  * email: blank after strip -> email_blank=1; non-blank and not matching the
    documented pattern -> email_syntax_failure=1; non-blank and matching ->
    proposed_email_export_eligible=1. The oracle uses ``re.fullmatch`` on the
    stripped value; the engine uses ``re.match`` with a trailing ``$`` on the
    stripped value — for newline-free CSV values these are equivalent (any
    string distinguishing them must contain a trailing newline AFTER stripping,
    which is impossible since ``str.strip`` removes trailing whitespace).
  * geography: V1 frozen PREFIX-MAP semantics (NOT the SP1 canonical-reference
    semantics). States outside the 51-state prefix map (e.g. GU, PR, AA) are
    NOT assessable; a well-formed-or-not ZIP with an in-map state is scored
    purely by prefix membership.

FAIL-CLOSED FINAL VERDICT (Dave review requirements)
----------------------------------------------------
The final PASS verdict is computed by ONE authoritative gate
(``evaluate_final_verdict``) that requires ALL of:

    FINAL_PASS =
        exactly_two_complete_runs
        AND run1_complete AND run2_complete
        AND run1_all_required_checks_pass AND run2_all_required_checks_pass
        AND deterministic_outputs_verified
        AND all_staged_results_successful
        AND safety_verified
        AND sp1_expected_names_verified
        AND sp1_expected_hashes_verified
        AND evidence_consistent

- BOTH runs must participate in EVERY final check: a passing Run 1 never
  hides a failing Run 2 (no results[0]/runs[0]/first_run/pass1-only logic
  anywhere in the verdict path).
- SAVED staged results are authoritative (Dave C): a saved FAIL / missing /
  malformed / stale stage result propagates to a final FAIL regardless of
  process exit codes, exception handling, or shell success.
- Safety is RUNTIME MEASURED per run via the audit-hook wrapper (Dave D):
  PASS only if both runs' measurements are clean; a missing/incomplete
  measurement is NOT_MEASURED and can NEVER satisfy a final PASS.
- SP1/V1 verification (Dave E) compares the run's engine-manifest rule NAMES
  and implementation HASHES against the pinned frozen baseline
  (evidence/final_execution/rule_matrix.json, recorded 2026-09-07, plus
  secondary full-hash pins from the preserved 2026-09-09 3M execution
  manifests). Expected values are NEVER generated from the actual run
  values. If the pinned baseline cannot be established, PASS is refused —
  values are never invented.
- Comparison counts (Dave F) explicitly report Run 1, Run 2, and the
  combined total (each run = rows x 8 flag rules; combined = run_1 + run_2).
- Determinism (Dave J) requires BOTH runs' input and output SHA-256 equality
  AND an actually-performed byte-identical file comparison at finalize
  (filecmp shallow=False). The existence of two runs alone proves nothing.
- FINAL_RESULTS.json carries full provenance (script path, exact script
  SHA-256, exact git commit, generation timestamp, per-run input/output
  hashes) and stale-evidence protection: every stage result must carry the
  same script SHA-256 and git commit as the checker computing the verdict.

Determinism
-----------
- One ``random.Random(seed)`` instance drives the whole dataset, consumed
  strictly in row order -> byte-identical dataset for the same (seed, rows).
- The engine is deterministic for identical input -> byte-identical output.
- The script runs the full pipeline TWICE and proves byte-identity; a final
  PASS is impossible with fewer than two complete successful runs.

Safety
------
- No ClickHouse, no network, no production data, no credentials, no
  out-of-repository mutations — RUNTIME VERIFIED per run through the
  audit-hook wrapper (see that script's docstring for the honest scope of
  the measurement; it is an observation layer, not a kernel sandbox).
- Peak memory measured via resource.getrusage (SELF + CHILDREN).
- Progress logged every 250,000 rows.

Usage
-----
    python scripts/final_3m_validation.py --rows 3000000 --seed 20260910 --passes 2

Staged mode (constrained shells; final PASS still requires BOTH passes):

    python scripts/final_3m_validation.py --phase generate --pass-no 1 ...
    python scripts/final_3m_validation.py --phase validate --pass-no 1 ...
    python scripts/final_3m_validation.py --phase verify   --pass-no 1 ...
    (same three phases with --pass-no 2)
    python scripts/final_3m_validation.py --phase finalize
"""

import argparse
import csv
import filecmp
import hashlib
import json
import os
import random
import re
import resource
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Checker provenance / pinned-baseline constants ──
CHECKER_VERSION = "2.0.0 (fail-closed final-verdict hardening, Dave review)"

WRAPPER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "final_3m_runtime_safety_wrapper.py")

# Pinned frozen EXPECTED V1 rule names + implementation-hash heads — the
# canonical per-rule hash record, recorded 2026-09-07 (pre-existing evidence,
# independent of every run checked by this script). Expected values are
# NEVER derived from the actual values of the run being checked.
PINNED_RULE_MATRIX_REL = "evidence/final_execution/rule_matrix.json"

# Secondary pinned full-hash sources — the preserved historical 3M execution
# engine manifests (2026-09-09). Cross-checked when present; a conflict with
# the primary pin is a FAIL (cannot authoritatively establish expected).
PINNED_SECONDARY_RELS = (
    "evidence/final_5m_execution/11_largest_safe_execution_3m/run1/manifest.json",
    "evidence/final_5m_execution/11_largest_safe_execution_3m/run2/manifest.json",
)

REQUIRED_RUN_CHECK_KEYS = (
    "schema_status", "row_count_status", "column_count_status",
    "column_order_status", "row_identity_status", "row_ordering_status",
    "source_values_preserved_status", "output_shape_status",
    "flag_domain_status",
)

COMPARISON_COUNT_DEFINITION = (
    "independent-oracle flag comparisons: per run = rows x 8 flag rules "
    "(each engine output flag value compared against the independently "
    "computed oracle expectation); combined_total = run_1 + run_2")

# ── Frozen contract constants (transcribed; NOT imported from the platform) ──
SOURCE_COLUMNS = [
    "id", "email_address", "first_name", "last_name", "address",
    "city", "county_name", "state", "zip", "website_source",
    "phone_number", "gender", "dob", "registration_date", "valid",
    "extra", "email_id", "ethnicity", "ownrent", "domain",
    "main_interest", "sub_interest", "latitude", "longitude", "uploaded",
    "country", "websource_id", "interest_ids", "DNC", "source",
    "first_name_norm", "last_name_norm", "zip_norm",
]

FLAG_COLUMNS = [
    "first_name_cleaning_candidate",
    "last_name_cleaning_candidate",
    "name_cleaning_candidate",
    "email_blank",
    "email_syntax_failure",
    "proposed_email_export_eligible",
    "zip_state_assessable",
    "geography_mismatch_candidate",
]

# 51-state ZIP prefix map (frozen V1 data contract, transcribed independently)
ORACLE_PREFIXES = {
    "AL": ("35", "36"), "AK": ("99",), "AZ": ("85", "86"),
    "AR": ("71", "72"), "CA": ("90", "91", "92", "93", "94", "95", "96"),
    "CO": ("80", "81"), "CT": ("06",), "DE": ("19",),
    "DC": ("20", "20"), "FL": ("32", "33", "34"), "GA": ("30", "31"),
    "HI": ("96", "97"), "ID": ("83", "84"), "IL": ("60", "61", "62"),
    "IN": ("46", "47"), "IA": ("50", "51", "52"), "KS": ("66", "67"),
    "KY": ("40", "41", "42"), "LA": ("70", "71"), "ME": ("03", "04"),
    "MD": ("21", "22"), "MA": ("01", "02"), "MI": ("48", "49"),
    "MN": ("55", "56"), "MS": ("38", "39"), "MO": ("63", "64", "65"),
    "MT": ("59",), "NE": ("68", "69"), "NV": ("88", "89"),
    "NH": ("03",), "NJ": ("07", "08"), "NM": ("87", "88"),
    "NY": ("10", "11", "12", "13", "14"), "NC": ("27", "28"),
    "ND": ("58",), "OH": ("43", "44", "45"), "OK": ("73", "74"),
    "OR": ("97",), "PA": ("15", "16", "17", "18", "19"),
    "RI": ("02", "03"), "SC": ("29",), "SD": ("57",),
    "TN": ("37", "38"), "TX": ("75", "76", "77", "78", "79"),
    "UT": ("84",), "VT": ("05",), "VA": ("22", "23", "24"),
    "WA": ("98", "99"), "WV": ("24", "25", "26"),
    "WI": ("53", "54"), "WY": ("82", "83"),
}

SUSPICIOUS = (
    "test", "fake", "dummy", "xxx", "zzz", "aaa", "bbb",
    "admin", "null", "none", "na", "n/a", "unknown",
    "example", "sample", "asdf", "qwerty", "abc", "xyz",
)

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def transcription_self_check():
    """Structural sanity of the transcribed tables (no production imports)."""
    assert len(SOURCE_COLUMNS) == 33, "SOURCE_COLUMNS must be 33"
    assert len(set(SOURCE_COLUMNS)) == 33, "SOURCE_COLUMNS must be unique"
    assert len(FLAG_COLUMNS) == 8, "FLAG_COLUMNS must be 8"
    assert len(ORACLE_PREFIXES) == 51, "ORACLE_PREFIXES must have 51 states"
    for st, prefs in ORACLE_PREFIXES.items():
        assert len(st) == 2 and st.isupper() and st.isalpha(), st
        for p in prefs:
            assert len(p) == 2 and p.isdigit(), (st, p)
    assert len(SUSPICIOUS) == 19  # 19 frozen patterns in the contract


# ════════════════════════════════════════════════════════════════════
# INDEPENDENT ORACLE — the 8 frozen V1 predicates, re-implemented here
# ════════════════════════════════════════════════════════════════════

def _blank(text):
    return text is None or str(text).strip() == ""


def _oracle_name_flag(name):
    """first_name/last_name cleaning candidate predicate."""
    s = str(name or "").strip()
    if s == "":
        return 0
    low = s.lower()
    for pattern in SUSPICIOUS:
        if pattern in low:
            return 1
    for ch in s:
        if not (ch.isalpha() or ch == "-" or ch == "'"):
            return 1
    collapsed = low.replace("-", "").replace("'", "")
    if len(s) > 1 and collapsed != "" and len(set(collapsed)) == 1:
        return 1
    return 0


def _oracle_full_name_flag(first, last):
    f = str(first or "").strip()
    l = str(last or "").strip()
    if f == "" and l == "":
        return 0
    if f != "" and l != "":
        if f.lower() == l.lower():
            return 1
        if len(f) <= 1 and len(l) <= 1:
            return 1
    return 0


def _oracle_email_flags(raw_email):
    """Returns (blank, syntax_failure, export_eligible) for one raw value."""
    e = str(raw_email if raw_email is not None else "").strip()
    if e == "":
        return 1, 0, 0
    ok = EMAIL_RE.fullmatch(e) is not None
    return 0, (0 if ok else 1), (1 if ok else 0)


def _oracle_geography_flags(raw_zip, raw_state):
    """Returns (assessable, mismatch) under frozen V1 prefix-map semantics."""
    z = str(raw_zip or "").strip()
    s = str(raw_state or "").strip()
    if z == "" or s == "":
        return 0, 0
    su = s.upper()
    if su not in ORACLE_PREFIXES:
        return 0, 0
    for prefix in ORACLE_PREFIXES[su]:
        if z.startswith(prefix):
            return 1, 0
    return 1, 1


def oracle_flags(row):
    """Compute all 8 V1 flags for one row dict. Independent code path."""
    blank, syntax_fail, eligible = _oracle_email_flags(row.get("email_address"))
    assessable, mismatch = _oracle_geography_flags(row.get("zip"), row.get("state"))
    return {
        "first_name_cleaning_candidate": _oracle_name_flag(row.get("first_name")),
        "last_name_cleaning_candidate": _oracle_name_flag(row.get("last_name")),
        "name_cleaning_candidate": _oracle_full_name_flag(
            row.get("first_name"), row.get("last_name")),
        "email_blank": blank,
        "email_syntax_failure": syntax_fail,
        "proposed_email_export_eligible": eligible,
        "zip_state_assessable": assessable,
        "geography_mismatch_candidate": mismatch,
    }


# ════════════════════════════════════════════════════════════════════
# DETERMINISTIC 3M DATASET GENERATOR (independent of platform generator)
# ════════════════════════════════════════════════════════════════════

FIRST_NORMAL = ["James", "Mary", "Robert", "Patricia", "Michael", "Linda",
                "David", "Sarah", "Daniel", "Laura", "Kevin", "Emily",
                "Brian", "Anna", "Jason", "Olivia", "Eric", "Sophia",
                "Mark", "Grace", "Paul", "Chloe", "Andrew", "Hannah"]
LAST_NORMAL = ["Smith", "Johnson", "Brown", "Garcia", "Miller", "Wilson",
               "Anderson", "Taylor", "Thomas", "Moore", "Jackson", "Martin",
               "Lee", "Clark", "Lewis", "Walker", "Hall", "Young", "King",
               "Wright", "Scott", "Green", "Baker", "Adams"]
SUSPICIOUS_NAMES = ["Test", "Fakeuser", "Dummy", "Xyz", "Sample", "Asdf",
                    "Qwerty", "Unknown", "Null", "Abcuser"]
REPEATED_NAMES = ["aaaa", "bbbb", "zzzz", "xx", "qqqq"]
UNICODE_NAMES = ["José", "Zoë", "André", "François", "Müller", "Sjöberg"]
HYPHEN_APOS_NAMES = ["Anne-Marie", "O'Brien", "D'Angelo", "Jean-Pierre", "Mary-Jane"]
MALFORMED_ZIPS = ["0", "00USA", "000CA", "015 8", "123456", "12A45", ""]
UNKNOWN_STATES = ["ZZ", "XX", "GU", "PR", "VI"]
CITIES = ["Springfield", "Riverside", "Franklin", "Greenville", "Bristol",
          "Clinton", "Fairview", "Salem", "Madison", "Georgetown", "Arlington"]
COUNTIES = ["Washington", "Jefferson", "Lincoln", "Jackson", "Franklin",
            "Montgomery", "Marion", "Monroe", "Adams", "Clay"]
STREETS = ["Main St", "Oak Ave", "Maple Dr", "Cedar Ln", "Pine Rd",
           "Elm Blvd", "Sunset Ave", "River Rd", "Hill St", "Lake Dr"]
DOMAINS = ["example.com", "testmail.org", "webmail.net", "company.io", "inbox.co"]
INVALID_EMAILS = ["not-an-email", "no-at-sign.com", "user@@double.com",
                  "user@nodot", "a@b", "user name@x.com", "..@..", "@missinglocal"]
WEBSOURCES = ["organic", "partner", "affiliate", "paid-search", "social"]
ETHNICITIES = ["W", "B", "A", "H", "O", "U"]
INTERESTS = ["sports", "finance", "travel", "tech", "home", "auto", "health"]
SUBINTERESTS = ["news", "deals", "reviews", "guides", "tips", "trends"]
SOURCES = ["vendor_a", "vendor_b", "partner_c", "internal"]
ALL_PREFIXES = sorted({p for prefs in ORACLE_PREFIXES.values() for p in prefs})


def _five_digit(rng):
    return f"{rng.randrange(10000, 100000)}"


def _matching_zip(rng, state):
    prefix = rng.choice(ORACLE_PREFIXES[state])
    return prefix + f"{rng.randrange(100, 1000)}"


def _mismatching_zip(rng, state):
    """A 5-digit ZIP guaranteed NOT to start with any prefix of `state`."""
    own = set(ORACLE_PREFIXES[state])
    while True:
        prefix = rng.choice(ALL_PREFIXES)
        if prefix not in own:
            return prefix + f"{rng.randrange(100, 1000)}"


def _random_row(rng, i):
    # email distribution: 78% valid / 8% blank / 7% invalid / 5% padded / 2% NULL-string
    r = rng.random()
    if r < 0.78:
        email = f"user{i}@{rng.choice(DOMAINS)}"
    elif r < 0.86:
        email = ""
    elif r < 0.93:
        email = rng.choice(INVALID_EMAILS)
    elif r < 0.98:
        email = f"  user{i}@{rng.choice(DOMAINS)}  "
    else:
        email = "NULL"
    # names
    r = rng.random()
    if r < 0.82:
        first = rng.choice(FIRST_NORMAL)
    elif r < 0.87:
        first = rng.choice(SUSPICIOUS_NAMES)
    elif r < 0.91:
        first = rng.choice(REPEATED_NAMES)
    elif r < 0.94:
        first = rng.choice(UNICODE_NAMES)
    elif r < 0.97:
        first = rng.choice(HYPHEN_APOS_NAMES)
    else:
        first = rng.choice(["", "J", "A", "x", " "])
    r = rng.random()
    if r < 0.84:
        last = rng.choice(LAST_NORMAL)
    elif r < 0.88:
        last = rng.choice(SUSPICIOUS_NAMES)
    elif r < 0.92:
        last = rng.choice(REPEATED_NAMES)
    elif r < 0.95:
        last = rng.choice(UNICODE_NAMES)
    elif r < 0.97:
        last = rng.choice(HYPHEN_APOS_NAMES)
    else:
        last = rng.choice(["", "K", "Z", "q", " "])
    # geography
    r = rng.random()
    if r < 0.90:
        state = rng.choice(sorted(ORACLE_PREFIXES))
    elif r < 0.93:
        state = rng.choice(sorted(ORACLE_PREFIXES)).lower()
    elif r < 0.96:
        state = rng.choice(UNKNOWN_STATES)
    elif r < 0.98:
        state = ""
    else:
        state = f"{rng.randrange(10, 100)}"
    if state.upper() in ORACLE_PREFIXES and state != "":
        r = rng.random()
        if r < 0.85:
            zip_val = _matching_zip(rng, state.upper())
        elif r < 0.95:
            zip_val = _mismatching_zip(rng, state.upper())
        else:
            zip_val = rng.choice(MALFORMED_ZIPS)
    else:
        r = rng.random()
        if r < 0.70:
            zip_val = _five_digit(rng)
        elif r < 0.90:
            zip_val = rng.choice(MALFORMED_ZIPS)
        else:
            zip_val = ""
    city = "" if rng.random() < 0.05 else rng.choice(CITIES)
    county = "" if rng.random() < 0.10 else rng.choice(COUNTIES)
    address = "" if rng.random() < 0.05 else f"{rng.randrange(1, 9999)} {rng.choice(STREETS)}"
    return {
        "id": str(i),
        "email_address": email,
        "first_name": first,
        "last_name": last,
        "address": address,
        "city": city,
        "county_name": county,
        "state": state,
        "zip": zip_val,
        "website_source": rng.choice(WEBSOURCES),
        "phone_number": f"555-{rng.randrange(100, 1000):03d}-{rng.randrange(1000, 10000):04d}",
        "gender": rng.choice(["M", "F"]),
        "dob": f"19{rng.randrange(40, 100):02d}-{rng.randrange(1, 13):02d}-{rng.randrange(1, 29):02d}",
        "registration_date": f"2025-{rng.randrange(1, 13):02d}-{rng.randrange(1, 29):02d}",
        "valid": str(rng.randrange(0, 2)),
        "extra": "",
        "email_id": f"eid{i}",
        "ethnicity": rng.choice(ETHNICITIES),
        "ownrent": rng.choice(["R", "O"]),
        "domain": rng.choice(DOMAINS),
        "main_interest": rng.choice(INTERESTS),
        "sub_interest": rng.choice(SUBINTERESTS),
        "latitude": f"{rng.uniform(24.0, 50.0):.6f}",
        "longitude": f"{rng.uniform(-125.0, -66.0):.6f}",
        "uploaded": f"2026-0{rng.randrange(1, 9)}-{rng.randrange(10, 29):02d}",
        "country": "US" if rng.random() < 0.95 else "",
        "websource_id": str(rng.randrange(1, 5000)),
        "interest_ids": f"{rng.randrange(1, 50)},{rng.randrange(1, 50)}",
        "DNC": str(rng.randrange(0, 2)),
        "source": rng.choice(SOURCES),
        "first_name_norm": first.lower(),
        "last_name_norm": last.lower(),
        "zip_norm": zip_val,
    }


def _edge_rows():
    """Hand-crafted edge rows embedded at the head of the dataset (deterministic).
    These exercise V1 semantics on the exact geography/name/email boundaries,
    including the well-known WA/99501 and GU/96910 pairs (under V1 prefix-map
    semantics: WA+99501 -> assessable=1/mismatch=0; GU+96910 -> 0/0)."""
    rows = []

    def add(email, first, last, state, zip_val, city="Springfield",
            county="Franklin", address="123 Main St"):
        rows.append({
            "id": "0", "email_address": email, "first_name": first,
            "last_name": last, "address": address, "city": city,
            "county_name": county, "state": state, "zip": zip_val,
            "website_source": "organic", "phone_number": "555-010-0100",
            "gender": "M", "dob": "1980-01-01", "registration_date": "2025-01-01",
            "valid": "1", "extra": "", "email_id": "eid0", "ethnicity": "U",
            "ownrent": "O", "domain": "example.com", "main_interest": "tech",
            "sub_interest": "news", "latitude": "35.000000",
            "longitude": "-90.000000", "uploaded": "2026-01-01", "country": "US",
            "websource_id": "1", "interest_ids": "1,2", "DNC": "0",
            "source": "vendor_a", "first_name_norm": first.lower(),
            "last_name_norm": last.lower(), "zip_norm": zip_val,
        })

    # geography acceptance-style pairs + boundaries (V1 prefix-map semantics)
    add("user1@example.com", "James", "Smith", "CA", "90210")
    add("user2@example.com", "James", "Smith", "CA", "00USA")
    add("user3@example.com", "James", "Smith", "CA", "0")
    add("user4@example.com", "James", "Smith", "CA", "000CA")
    add("user5@example.com", "James", "Smith", "CA", "015 8")
    add("user6@example.com", "James", "Smith", "WA", "99501")
    add("user7@example.com", "James", "Smith", "GU", "96910")
    add("user8@example.com", "James", "Smith", "ca", "90210")       # lowercase state
    add("user9@example.com", "James", "Smith", "NY", "10001")
    add("user10@example.com", "James", "Smith", "NY", "99999")      # mismatching
    add("user11@example.com", "James", "Smith", "", "90210")        # blank state
    add("user12@example.com", "James", "Smith", "CA", "")           # blank zip
    add("user13@example.com", "James", "Smith", "12", "90210")      # numeric state
    add("user14@example.com", "James", "Smith", "XX", "12345")      # unknown state
    add("user15@example.com", "James", "Smith", "AK", "99501")      # AK prefix 99
    add("user16@example.com", "James", "Smith", "MA", "01234")
    add("user17@example.com", "James", "Smith", "WA", "98101")
    # name edges
    add("user20@example.com", "José", "García", "CA", "90210")      # unicode alpha OK
    add("user21@example.com", "O'Brien", "Smith", "CA", "90210")
    add("user22@example.com", "Anne-Marie", "Dupont", "CA", "90210")
    add("user23@example.com", "aaaa", "Smith", "CA", "90210")       # repeated
    add("user24@example.com", "Test", "User", "CA", "90210")        # suspicious
    add("user25@example.com", "", "Smith", "CA", "90210")           # blank first
    add("user26@example.com", "J", "K", "CA", "90210")              # single chars
    add("user27@example.com", "Same", "Same", "CA", "90210")        # first==last
    add("user28@example.com", "Smith", "smith", "CA", "90210")      # case-insensitive equal
    add("user29@example.com", "John Doe42", "Smith", "CA", "90210")  # non-alpha
    # email edges
    add("", "James", "Smith", "CA", "90210")                        # blank email
    add("   ", "James", "Smith", "CA", "90210")                     # whitespace email
    add("  user30@example.com  ", "James", "Smith", "CA", "90210")  # padded valid
    add("not-an-email", "James", "Smith", "CA", "90210")            # invalid
    add("user@nodot", "James", "Smith", "CA", "90210")              # invalid
    add("NULL", "James", "Smith", "CA", "90210")                    # null-string
    # blank city / blank address
    add("user31@example.com", "James", "Smith", "CA", "90210", city="", address="")
    add("user32@example.com", "James", "Smith", "CA", "90210", county="", address="")
    return rows


def generate_dataset(path, rows, seed, progress_every=250_000):
    """Deterministic dataset: one RNG consumed strictly in row order."""
    rng = random.Random(seed)
    edges = _edge_rows()
    t0 = time.perf_counter()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    written = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SOURCE_COLUMNS)
        writer.writeheader()
        for i in range(1, rows + 1):
            if i <= len(edges):
                row = dict(edges[i - 1])
                row["id"] = str(i)
            else:
                row = _random_row(rng, i)
            writer.writerow(row)
            written += 1
            if written % progress_every == 0:
                log(f"  generate: {written:,}/{rows:,} rows "
                    f"({time.perf_counter() - t0:.1f}s)")
    return time.perf_counter() - t0


# ════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ════════════════════════════════════════════════════════════════════

def log(msg):
    print(msg, flush=True)


def sha256_file(path, chunk=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def peak_rss_mb():
    """Peak RSS in MB: max of this process and its children (Linux ru_maxrss is KiB)."""
    self_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    child_kb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    return max(self_kb, child_kb) / 1024.0


def git_commit_id():
    """Current HEAD commit id (read-only local git query; None if unavailable)."""
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                              capture_output=True, text=True, timeout=30)
        commit = proc.stdout.strip()
        if proc.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", commit):
            return commit
    except Exception:
        pass
    return None


def script_identity():
    """Path + SHA-256 of THIS script file, as actually executing.

    Also pins the runtime-safety wrapper (WRAPPER_PATH) so that any
    tampering with the wrapper's source bytes (e.g. disabling the audit
    hook) is detectable by downstream gates. Without this, an attacker
    modifying only the wrapper would evade script_sha256 verification
    (B-9 fix)."""
    ident = {
        "script_path": os.path.abspath(__file__),
        "script_sha256": sha256_file(__file__),
    }
    try:
        ident["wrapper_path"] = os.path.abspath(WRAPPER_PATH)
        ident["wrapper_sha256"] = sha256_file(WRAPPER_PATH)
    except OSError:
        # If the wrapper is unreadable, record None — downstream gates
        # treat None as a fail-closed signal (stale-evidence check).
        ident["wrapper_path"] = os.path.abspath(WRAPPER_PATH) \
            if os.path.exists(WRAPPER_PATH) else None
        ident["wrapper_sha256"] = None
    return ident


def _dig(data, *keys):
    """Safe nested dict getter: None if any level is missing/not a dict."""
    node = data
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def run_cli_validate(csv_path, out_path, run_id, evidence_dir, events_path):
    """Run the PRODUCTION validation path as a subprocess of the canonical CLI,
    executed inside the audit-hook runtime-safety wrapper.

    The wrapper runs ``runner.cli`` as ``__main__`` via runpy with argv
    identical to ``python -m runner.cli validate ...`` — the same canonical
    entrypoint — while recording socket / process-exec / filesystem-mutation
    audit events to ``events_path`` (the runtime safety measurement; see the
    wrapper docstring for its honest scope)."""
    cmd = [
        sys.executable, WRAPPER_PATH,
        "--events-out", events_path, "--max-events", "50000", "--",
        "validate", "--csv", csv_path, "--output", out_path,
        "--run-id", run_id, "--evidence-dir", evidence_dir,
    ]
    canonical_cmd = [
        sys.executable, "-m", "runner.cli", "validate",
        "--csv", csv_path, "--output", out_path,
        "--run-id", run_id, "--evidence-dir", evidence_dir,
    ]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    duration = time.perf_counter() - t0
    return {
        "command": " ".join(cmd),
        "canonical_command": " ".join(canonical_cmd),
        "wrapper_script": os.path.relpath(WRAPPER_PATH, REPO_ROOT),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "duration_seconds": round(duration, 3),
    }


# ════════════════════════════════════════════════════════════════════
# VERIFICATION + INDEPENDENT ORACLE PASS
# ════════════════════════════════════════════════════════════════════

def verify_and_oracle(in_path, out_path, expected_rows, progress_every=250_000):
    """Stream input+output in lockstep. Checks the 16 required dimensions that
    apply to the per-pass verification (schema, counts, order, identity,
    ordering, immutability of values, output shape, all 8 flags, oracle)."""
    result = {
        "schema_status": "FAIL",
        "row_count_status": "FAIL",
        "column_count_status": "FAIL",
        "column_order_status": "FAIL",
        "row_identity_status": "FAIL",
        "row_ordering_status": "FAIL",
        "source_values_preserved_status": "FAIL",
        "output_shape_status": "FAIL",
        "flag_domain_status": "FAIL",
        "oracle_comparisons": 0,
        "oracle_mismatches": 0,
        "mismatches_by_rule": {c: 0 for c in FLAG_COLUMNS},
        "first_mismatches": [],
        "flag_totals": {c: 0 for c in FLAG_COLUMNS},
        "input_rows": 0,
        "output_rows": 0,
    }

    with open(in_path, "r", newline="", encoding="utf-8") as fin, \
         open(out_path, "r", newline="", encoding="utf-8") as fout:
        reader_in = csv.DictReader(fin)
        reader_out = csv.DictReader(fout)
        header_in = list(reader_in.fieldnames or [])
        header_out = list(reader_out.fieldnames or [])

        # 1. schema + 3/4. column count + order
        result["schema_status"] = "PASS" if header_in == SOURCE_COLUMNS else "FAIL"
        result["column_count_status"] = (
            "PASS" if len(header_in) == 33 and len(header_out) == 41 else "FAIL")
        result["column_order_status"] = (
            "PASS" if header_out == SOURCE_COLUMNS + FLAG_COLUMNS else "FAIL")

        rows_seen = 0
        identity_ok = True
        ordering_ok = True
        preserved_ok = True
        flag_domain_ok = True
        identity_first_bad = None
        ordering_first_bad = None
        preserved_first_bad = None
        t0 = time.perf_counter()

        for pos, (src, dst) in enumerate(zip(reader_in, reader_out), start=1):
            rows_seen += 1
            # 5. row identity: id equals its 1-based position in both files
            if src.get("id") != str(pos) or dst.get("id") != str(pos):
                identity_ok = False
                if identity_first_bad is None:
                    identity_first_bad = (pos, src.get("id"), dst.get("id"))
            # 6. row ordering + 7. source values preserved: all 33 source
            #    columns byte-equal between input row and output row at pos
            for col in SOURCE_COLUMNS:
                if src.get(col) != dst.get(col):
                    ordering_ok = False
                    preserved_ok = False
                    if ordering_first_bad is None:
                        ordering_first_bad = (pos, col, repr(src.get(col)), repr(dst.get(col)))
            # 8/9. output shape: flags in {0,1}
            for col in FLAG_COLUMNS:
                v = dst.get(col)
                if v not in ("0", "1"):
                    flag_domain_ok = False
                if v == "1":
                    result["flag_totals"][col] += 1
            # 10. independent oracle
            expected = oracle_flags(src)
            for col in FLAG_COLUMNS:
                result["oracle_comparisons"] += 1
                actual = dst.get(col)
                if str(expected[col]) != actual:
                    result["oracle_mismatches"] += 1
                    result["mismatches_by_rule"][col] += 1
                    if len(result["first_mismatches"]) < 5:
                        result["first_mismatches"].append({
                            "row": pos, "rule": col,
                            "input": {k: src.get(k) for k in
                                      ("id", "email_address", "first_name",
                                       "last_name", "state", "zip")},
                            "oracle": str(expected[col]), "engine": actual,
                        })
            if rows_seen % progress_every == 0:
                log(f"  verify+oracle: {rows_seen:,} rows "
                    f"({time.perf_counter() - t0:.1f}s, mismatches so far: "
                    f"{result['oracle_mismatches']})")

        result["input_rows"] = rows_seen
        # drain both readers to prove equal counts
        extra_in = sum(1 for _ in reader_in)
        extra_out = sum(1 for _ in reader_out)
        result["output_rows"] = rows_seen + extra_out
        result["extra_input_rows_after_lockstep"] = extra_in
        result["extra_output_rows_after_lockstep"] = extra_out

    result["row_count_status"] = (
        "PASS" if (result["input_rows"] == expected_rows
                   and result["output_rows"] == expected_rows
                   and extra_in == 0 and extra_out == 0) else "FAIL")
    result["row_identity_status"] = "PASS" if identity_ok else "FAIL"
    if identity_first_bad:
        result["row_identity_first_anomaly"] = identity_first_bad
    result["row_ordering_status"] = "PASS" if ordering_ok else "FAIL"
    result["source_values_preserved_status"] = "PASS" if preserved_ok else "FAIL"
    if ordering_first_bad:
        result["first_source_column_difference"] = ordering_first_bad
    result["output_shape_status"] = "PASS" if (
        flag_domain_ok and result["column_count_status"] == "PASS"
        and result["column_order_status"] == "PASS") else "FAIL"
    result["flag_domain_status"] = "PASS" if flag_domain_ok else "FAIL"
    result["verify_duration_seconds"] = round(time.perf_counter() - t0, 3)
    return result


# ════════════════════════════════════════════════════════════════════
# PINNED FROZEN SP1/V1 RULE BASELINE + RUNTIME SAFETY CLASSIFICATION
# ════════════════════════════════════════════════════════════════════

def load_pinned_rule_baseline(repo_root=REPO_ROOT):
    """Load the pinned frozen EXPECTED V1 rule names and implementation
    hash heads from the canonical pre-existing rule matrix (2026-09-07),
    plus the secondary full-hash pins from the preserved historical 3M
    execution manifests (2026-09-09).

    Expected values are read ONLY from these pinned, pre-existing evidence
    files; they are NEVER derived from the actual values of the run being
    checked. Returns None if the authoritative pinned baseline is missing
    or malformed — the caller must then refuse final PASS (expected values
    are never invented). A present-but-conflicting secondary source is
    recorded as a conflict (also refuses PASS)."""
    matrix_path = os.path.join(repo_root, PINNED_RULE_MATRIX_REL)
    if not os.path.exists(matrix_path):
        return None
    try:
        with open(matrix_path, "r", encoding="utf-8") as f:
            matrix = json.load(f)
        rules = matrix["rules"]
        assert isinstance(rules, list) and len(rules) == 8
        names, heads = [], {}
        for entry in rules:
            rid = entry["rule_id"]
            head = entry["implementation_hash_head"]
            assert re.fullmatch(r"[0-9a-f]{16}", head), rid
            assert re.fullmatch(r"[A-Za-z0-9_.]+", rid), rid
            names.append(rid)
            heads[rid] = head
        assert len(set(names)) == 8
    except Exception:
        return None
    secondary, conflicts = [], 0
    for rel in PINNED_SECONDARY_RELS:
        path = os.path.join(repo_root, rel)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            hashes = manifest["rule_hashes"]
            assert isinstance(hashes, dict) and len(hashes) == 8
            assert sorted(hashes.keys()) == sorted(names)
            assert all(re.fullmatch(r"[0-9a-f]{64}", v)
                       for v in hashes.values())
            assert all(hashes[k].startswith(heads[k]) for k in heads)
            secondary.append({"source": rel, "rule_hashes": dict(hashes)})
        except Exception:
            conflicts += 1
    return {
        "primary_source": PINNED_RULE_MATRIX_REL,
        "primary_generated_at_utc": matrix.get("generated_at_utc"),
        "expected_rule_names": sorted(names),
        "expected_hash_heads": heads,
        "secondary_sources": list(PINNED_SECONDARY_RELS),
        "secondary_full_hashes": secondary,
        "secondary_sources_present": len(secondary),
        "secondary_conflict": conflicts > 0,
    }


def sp1_frozen_verification(engine_evidence_dir, pinned):
    """Verify ONE run's engine manifest against the pinned frozen baseline.

    Dave requirement E — checks BOTH:
      - expected rule NAMES: the manifest's rule set must equal the pinned 8
        V1 rule names exactly (so no SP1 successor rule was registered or
        executed — SP1 isolation by name-set equality);
      - expected rule HASHES: every manifest implementation hash must match
        the pinned hash head (primary pin) AND, when secondary full-hash pins
        are available, the full 64-char pinned hash.

    Expected values come ONLY from `pinned` (pre-existing evidence files
    recorded BEFORE the runs checked here); they are never generated from
    the actual run values (no self-validation)."""
    result = {
        "status": "FAIL",
        "expected_names_verified": False,
        "expected_hashes_verified": False,
        "secondary_full_hash_match": None,
        "pinned_source": None,
        "manifest_rule_names": None,
        "mismatched_rules": {},
        "reason": "",
    }
    manifest_path = os.path.join(engine_evidence_dir, "manifest.json")
    if pinned is None:
        result["reason"] = (
            "pinned frozen baseline unavailable "
            f"({PINNED_RULE_MATRIX_REL}) — refusing to verify against invented "
            "expected values")
        return result
    result["pinned_source"] = pinned["primary_source"]
    if not os.path.exists(manifest_path):
        result["reason"] = f"engine manifest not present: {manifest_path}"
        return result
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        rule_hashes = manifest["rule_hashes"]
        assert isinstance(rule_hashes, dict)
    except Exception as exc:
        result["reason"] = f"engine manifest unreadable: {exc}"
        return result
    actual_names = sorted(rule_hashes.keys())
    expected_names = list(pinned["expected_rule_names"])
    result["manifest_rule_names"] = actual_names
    result["manifest_rule_hashes"] = dict(rule_hashes)
    if actual_names != expected_names:
        result["reason"] = ("rule name set mismatch: expected (pinned) "
                            f"{expected_names}, manifest has {actual_names}")
        return result
    result["expected_names_verified"] = True
    heads = pinned["expected_hash_heads"]
    for rid, head in heads.items():
        actual_hash = rule_hashes.get(rid, "")
        if not str(actual_hash).startswith(head):
            result["mismatched_rules"][rid] = {
                "expected_head": head, "actual": actual_hash}
    if result["mismatched_rules"]:
        result["reason"] = ("rule implementation hash mismatch vs pinned "
                            f"baseline: {sorted(result['mismatched_rules'])}")
        return result
    result["expected_hashes_verified"] = True
    if pinned.get("secondary_full_hashes"):
        for sec in pinned["secondary_full_hashes"]:
            for rid, full in sec["rule_hashes"].items():
                if rule_hashes.get(rid) != full:
                    result["secondary_full_hash_match"] = False
                    result["mismatched_rules"][rid] = {
                        "secondary_source": sec["source"],
                        "expected_full": full,
                        "actual": rule_hashes.get(rid, "")}
                    result["reason"] = ("rule hash mismatch vs secondary "
                                        f"full-hash pin {sec['source']}")
                    return result
        result["secondary_full_hash_match"] = True
    result["status"] = "PASS"
    result["reason"] = ("manifest rule names and implementation hashes match "
                        "the pinned frozen baseline (exactly the 8 frozen V1 "
                        "rules executed; SP1 successor layer absent)")
    return result


_RUNTIME_SAFETY_MEASUREMENT_NOTE = (
    "CPython audit-hook runtime instrumentation of the production CLI "
    "subprocess (scripts/final_3m_runtime_safety_wrapper.py); cooperative "
    "observation, not a kernel sandbox")


def _runtime_safety_result(status, reason, **extra):
    """Build a runtime-safety result dict with the canonical measurement
    note. Shared by both the path-based and bytes-based classifiers so
    the measurement note is always identical."""
    base = {"status": status, "reason": reason,
            "measurement": _RUNTIME_SAFETY_MEASUREMENT_NOTE}
    base.update(extra)
    return base


def _classify_runtime_safety_payload(payload, repo_root=REPO_ROOT):
    """Classify ONE run's RUNTIME safety from an ALREADY-PARSED event
    payload (a dict). Called by:
      - ``classify_runtime_safety_from_bytes`` (the L-8 fix's
        byte-sequence-based classifier, used by both producer and
        consumer so that hashing and classification operate on the
        EXACT same bytes — closing the L-8 TOCTOU window and the L-8
        saved-status bypass).
      - ``classify_runtime_safety`` (the legacy path-based API kept
        for backward-compatible callers; reads the file then delegates
        here).

    Dave requirement D — statuses:
      PASS         -> complete (non-truncated) record with ZERO socket
                      events, ZERO process-exec events, and every recorded
                      filesystem mutation inside repo_root.
      FAIL         -> runtime evidence of network activity, process
                      spawning, or an out-of-repository mutation.
      NOT_MEASURED -> events file missing / unreadable / truncated: the
                      measurement was not (completely) performed and must
                      NEVER satisfy a final PASS."""
    if not isinstance(payload, dict):
        return _runtime_safety_result(
            "NOT_MEASURED",
            "runtime safety event payload is not a JSON object")
    if payload.get("truncated"):
        return _runtime_safety_result(
            "NOT_MEASURED",
            "runtime safety event record truncated (hit "
            f"max-events cap {payload.get('max_events')}) — "
            "incomplete measurement")
    events = payload.get("events")
    if not isinstance(events, list):
        return _runtime_safety_result(
            "NOT_MEASURED",
            "runtime safety event payload missing 'events' list")

    network = [e for e in events
               if str(e.get("event", "")).startswith("socket.")]
    exec_events = [e for e in events if str(e.get("event", "")) in (
        "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn",
        "os.spawn", "os.fork")]
    ctypes_events = [e for e in events
                     if str(e.get("event", "")).startswith("ctypes.")]

    write_mask = (os.O_WRONLY | os.O_RDWR | os.O_CREAT
                  | os.O_TRUNC | os.O_APPEND)

    def _resolve(p, follow_symlinks=True):
        """Resolve a path for boundary checking.

        When follow_symlinks=True (default): uses os.path.realpath()
        which follows ALL symlinks (parent + final component). This
        is correct for operations that ACCESS existing paths (open,
        mkdir, rename src/dst, remove, etc.) — we want the physical
        path after resolving all symlinks.

        When follow_symlinks=False: uses os.path.normpath(abspath())
        which normalizes but does NOT follow symlinks. This is correct
        for os.symlink's linkpath (path2) — the symlink is being
        CREATED, not followed. Using realpath on a just-created
        symlink would follow it back to the target, misclassifying
        an outside linkpath as inside.
        """
        if not isinstance(p, str) or p == "":
            return None
        if not os.path.isabs(p):
            p = os.path.join(repo_root, p)
        if follow_symlinks:
            return os.path.realpath(p)
        else:
            return os.path.normpath(os.path.abspath(p))

    # Resolve repo_root once with realpath so that the boundary
    # comparison is consistent: both the event path and the repo root
    # must be symlink-resolved for the startswith() check to be
    # meaningful.
    _resolved_repo_root = os.path.realpath(repo_root)

    def _in_repo(p, follow_symlinks=True):
        r = _resolve(p, follow_symlinks=follow_symlinks)
        return r is not None and (r == _resolved_repo_root
                                  or r.startswith(_resolved_repo_root + os.sep))

    mutations, out_of_repo = [], []
    for e in events:
        name = str(e.get("event", ""))
        if name == "open":
            flags = e.get("flags")
            mode = str(e.get("mode", ""))
            is_write = ((isinstance(flags, int) and (flags & write_mask))
                        or any(c in mode for c in "wax+"))
            if is_write:
                mutations.append({"event": "open(write)",
                                  "path": e.get("path")})
                if not _in_repo(e.get("path")):
                    out_of_repo.append(e)
        elif name in ("os.remove", "os.rmdir", "os.truncate", "os.mkdir",
                      "shutil.rmtree"):
            mutations.append({"event": name, "path": e.get("path")})
            if not _in_repo(e.get("path")):
                out_of_repo.append(e)
        elif name in ("os.rename", "os.link", "os.symlink",
                      "shutil.copyfile", "shutil.copymode",
                      "shutil.copystat", "shutil.move"):
            # NOTE: CPython 3.12 does NOT emit separate "os.replace",
            # "shutil.copy", or "shutil.copy2" audit events.
            # os.replace → "os.rename"; shutil.copy → "shutil.copyfile"
            # + "shutil.copymode"; shutil.copy2 → "shutil.copyfile"
            # + "shutil.copystat". This list matches the CANONICAL
            # event names that CPython actually emits.
            mutations.append({"event": name, "path": e.get("path"),
                              "target": e.get("path2")})
            # For os.symlink, path2 is the LINKPATH (where the symlink
            # is created). Using realpath on it would follow the
            # just-created symlink back to the target — misclassifying
            # an outside linkpath as inside. So for os.symlink, check
            # path2 with follow_symlinks=False.
            if name == "os.symlink":
                if (not _in_repo(e.get("path"))
                        or not _in_repo(e.get("path2"),
                                        follow_symlinks=False)):
                    out_of_repo.append(e)
            else:
                if not _in_repo(e.get("path")) or not _in_repo(e.get("path2")):
                    out_of_repo.append(e)

    common = {
        "network_event_count": len(network),
        "exec_event_count": len(exec_events),
        "ctypes_event_count": len(ctypes_events),
        "mutation_count": len(mutations),
        "out_of_repo_mutation_count": len(out_of_repo),
        "event_count": payload.get("event_count", len(events)),
        "engine_exit_code": payload.get("exit_code"),
        "sample_mutations": mutations[:25],
    }
    if network:
        return _runtime_safety_result(
            "FAIL", "network activity observed at runtime "
            f"({len(network)} socket events; first: "
            f"{network[0]})", network_events=network[:20], **common)
    if exec_events:
        return _runtime_safety_result(
            "FAIL", "process execution observed at runtime "
            f"({len(exec_events)} exec events; first: "
            f"{exec_events[0]})", exec_events=exec_events[:20], **common)
    if ctypes_events:
        # Native-code loading (ctypes.dlopen, ctypes.CDLL, etc.) is a
        # security-relevant runtime behavior — fail-closed. The wrapper's
        # own docstring advertises ctypes.* as a captured event; the
        # classifier must enforce it, not merely count it.
        return _runtime_safety_result(
            "FAIL", "native library loading observed at runtime "
            f"({len(ctypes_events)} ctypes events; first: "
            f"{ctypes_events[0]})", ctypes_events=ctypes_events[:20],
            **common)
    if out_of_repo:
        return _runtime_safety_result(
            "FAIL", "out-of-repository mutation observed at "
            f"runtime ({len(out_of_repo)} events; first: "
            f"{out_of_repo[0]})",
            out_of_repo_mutations=out_of_repo[:20], **common)
    return _runtime_safety_result(
        "PASS",
        "runtime-verified: 0 socket events, 0 process-exec "
        f"events, {len(mutations)} filesystem mutations all "
        "within the repository root", **common)


def classify_runtime_safety_from_bytes(events_raw, repo_root=REPO_ROOT):
    """Classify ONE run's RUNTIME safety from IN-MEMORY event bytes.

    L-8 fix: this is the authoritative byte-sequence classifier. The
    producer (phase_validate) and the consumer (_per_run_checks) both
    route through this function so that:

      - the SHA-256 stored as ``events_file_sha256`` is computed from
        the EXACT byte sequence that gets parsed and classified
        (closing the producer-side TOCTOU window between classify
        and hash); and

      - the consumer re-derives the runtime-safety status from the
        bytes it independently read from disk, rather than trusting
        the saved ``runtime_safety.status`` field in the run-result
        JSON (closing the L-8 saved-status bypass).

    Args:
      events_raw: the raw bytes of the events JSON file (must be a
        bytes object, not a str).
      repo_root: the repository root used to resolve relative paths
        in the events file.

    Returns:
      A runtime-safety result dict with at least ``status`` and
      ``reason``; ``status`` is one of PASS / FAIL / NOT_MEASURED.
    """
    if not isinstance(events_raw, (bytes, bytearray)):
        return _runtime_safety_result(
            "NOT_MEASURED",
            "runtime safety event bytes not a bytes/bytearray "
            f"(got {type(events_raw).__name__})")
    if len(events_raw) == 0:
        return _runtime_safety_result(
            "NOT_MEASURED",
            "runtime safety event record is empty (0 bytes)")
    try:
        payload = json.loads(events_raw.decode("utf-8"))
    except Exception as exc:
        return _runtime_safety_result(
            "NOT_MEASURED",
            f"runtime safety event record unreadable: {exc}")
    return _classify_runtime_safety_payload(payload, repo_root=repo_root)


def classify_runtime_safety(events_path, repo_root=REPO_ROOT):
    """Classify ONE run's RUNTIME safety from its audit-hook event record.

    Legacy path-based API. Reads the events file from disk and delegates
    to ``_classify_runtime_safety_payload``. New callers that need to
    share byte-identity between hashing and classification should use
    ``classify_runtime_safety_from_bytes`` instead.

    Dave requirement D — statuses:
      PASS         -> complete (non-truncated) record with ZERO socket
                      events, ZERO process-exec events, and every recorded
                      filesystem mutation inside repo_root.
      FAIL         -> runtime evidence of network activity, process
                      spawning, or an out-of-repository mutation.
      NOT_MEASURED -> events file missing / unreadable / truncated: the
                      measurement was not (completely) performed and must
                      NEVER satisfy a final PASS."""
    if not events_path or not os.path.exists(events_path):
        return _runtime_safety_result(
            "NOT_MEASURED",
            f"runtime safety event record not present: {events_path}")
    try:
        with open(events_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        return _runtime_safety_result(
            "NOT_MEASURED",
            f"runtime safety event record unreadable: {exc}")
    return _classify_runtime_safety_payload(payload, repo_root=repo_root)


# ════════════════════════════════════════════════════════════════════
# MAIN DRIVER
# ════════════════════════════════════════════════════════════════════

def phase_generate(args, pass_no):
    """PHASE: generate — build the deterministic dataset for one pass."""
    label = f"pass{pass_no}"
    in_path = os.path.join(args.data_dir, f"consumer_3m_seed_{args.seed}_{label}.csv")
    log(f"[{label}] GENERATE dataset ({args.rows:,} rows, seed {args.seed}) ...")
    gen_t = generate_dataset(in_path, args.rows, args.seed)
    in_hash = sha256_file(in_path)
    in_size = os.path.getsize(in_path)
    log(f"[{label}] dataset: {in_size:,} bytes, sha256={in_hash}, "
        f"generated in {gen_t:.1f}s")
    state = {
        "pass": label,
        "path": in_path, "rows": args.rows, "seed": args.seed,
        "columns": 33, "size_bytes": in_size, "sha256": in_hash,
        "generation_seconds": round(gen_t, 3),
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "script_sha256": script_identity()["script_sha256"],
        "wrapper_sha256": script_identity().get("wrapper_sha256"),
        "git_commit": git_commit_id(),
    }
    with open(os.path.join(args.evidence_dir, f"{label}_generate.json"), "w",
              encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    return state


def phase_validate(args, pass_no):
    """PHASE: validate — run the production CLI subprocess (inside the
    audit-hook runtime-safety wrapper) for one pass. Writes pass{N}_cli.json
    including the RUNTIME safety classification. Fail-closed: measurement
    problems are recorded and propagated, never silently treated as success."""
    label = f"pass{pass_no}"
    gen_path = os.path.join(args.evidence_dir, f"{label}_generate.json")
    with open(gen_path, "r", encoding="utf-8") as f:
        gen = json.load(f)
    in_path = gen["path"]
    out_path = os.path.join(
        args.data_dir, f"consumer_3m_seed_{args.seed}_{label}_out.csv")
    engine_ev = os.path.join(args.evidence_dir, f"{label}_engine")
    events_path = os.path.join(
        args.evidence_dir, f"{label}_runtime_safety_events.json")
    log(f"[{label}] VALIDATE via production CLI subprocess "
        f"(audit-hook runtime-safety wrapper) ...")
    cli = run_cli_validate(in_path, out_path, f"final_3m_{label}",
                           engine_ev, events_path)
    log(f"[{label}] CLI exit={cli['returncode']} in {cli['duration_seconds']}s")
    for line in cli["stdout"].splitlines():
        log(f"[{label}] CLI> {line}")
    if cli["stderr"].strip():
        for line in cli["stderr"].splitlines()[:20]:
            log(f"[{label}] CLI(err)> {line}")
    in_hash_post = sha256_file(in_path) if os.path.exists(in_path) else ""
    out_hash = (sha256_file(out_path)
                if cli["returncode"] == 0 and os.path.exists(out_path) else "")
    out_size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
    # L-8 producer fix: read the events file bytes ONCE and use those
    # exact bytes for BOTH the SHA-256 hash AND the classification.
    # This closes the producer-side TOCTOU window where the bytes
    # hashed could differ from the bytes classified if the events
    # file were modified between two separate open() calls.
    # The saved runtime_safety block now carries events_path,
    # events_file_sha256, and the derived status — all derived from
    # the same single byte read.
    if events_path and os.path.exists(events_path):
        with open(events_path, "rb") as f:
            events_raw = f.read()
        events_file_sha = hashlib.sha256(events_raw).hexdigest()
        runtime_safety = classify_runtime_safety_from_bytes(
            events_raw, repo_root=REPO_ROOT)
        runtime_safety["events_path"] = events_path
        runtime_safety["events_file_sha256"] = events_file_sha
    else:
        runtime_safety = classify_runtime_safety(events_path)
    log(f"[{label}] RUNTIME SAFETY: {runtime_safety['status']} — "
        f"{runtime_safety.get('reason')}")
    # Peak RSS of the engine = RUSAGE_CHILDREN high-water mark after the
    # subprocess completes (Linux ru_maxrss is KiB). This is the authoritative
    # whole-run memory figure, matching the method used by the prior 3M
    # execution evidence (evidence/final_5m_execution/11_.../run1/memory.txt).
    engine_peak_rss_mb = round(peak_rss_mb(), 2)
    log(f"[{label}] engine peak RSS (RUSAGE_CHILDREN, post-exit): "
        f"{engine_peak_rss_mb} MB")
    log(f"[{label}] output: {out_size:,} bytes, sha256={out_hash}")
    log(f"[{label}] source immutability: input hash before={gen['sha256'][:16]} "
        f"after={in_hash_post[:16]} -> "
        f"{'UNCHANGED' if gen['sha256'] == in_hash_post else 'CHANGED'}")
    state = {
        "pass": label,
        "cli": cli,
        "output_path": out_path, "output_size_bytes": out_size,
        "output_sha256": out_hash,
        "input_sha256_after_validation": in_hash_post,
        "engine_evidence_dir": engine_ev,
        "engine_peak_rss_mb": engine_peak_rss_mb,
        "runtime_safety": runtime_safety,
        "validated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "script_sha256": script_identity()["script_sha256"],
        "wrapper_sha256": script_identity().get("wrapper_sha256"),
        "git_commit": git_commit_id(),
    }
    with open(os.path.join(args.evidence_dir, f"{label}_cli.json"), "w",
              encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    # Stage exit code: non-zero if the saved CLI result failed OR the runtime
    # safety measurement is not a clean PASS. The SAVED state (above) is the
    # authority for the final gate — this exit code can only add signal.
    return 0 if (cli["returncode"] == 0
                 and runtime_safety["status"] == "PASS") else 1


def phase_verify(args, pass_no):
    """PHASE: verify — schema/identity/order/oracle verification for one pass
    + SP1 frozen verification + runtime safety propagation. Writes
    pass{N}_result.json. Returns 0 ONLY if every required check of THIS run
    passes; every failure is recorded in the SAVED result (Dave C: the final
    gate consumes the saved result, not process exit codes)."""
    label = f"pass{pass_no}"
    result_path = os.path.join(args.evidence_dir, f"{label}_result.json")
    pinned = load_pinned_rule_baseline()
    _ident = script_identity()
    pass_result = {
        "pass": label,
        "checker_version": CHECKER_VERSION,
        "script_sha256": _ident["script_sha256"],
        "wrapper_sha256": _ident.get("wrapper_sha256"),
        "git_commit": git_commit_id(),
    }
    exit_code = 1
    try:
        with open(os.path.join(args.evidence_dir, f"{label}_generate.json"),
                  "r", encoding="utf-8") as f:
            gen = json.load(f)
        with open(os.path.join(args.evidence_dir, f"{label}_cli.json"),
                  "r", encoding="utf-8") as f:
            cli_state = json.load(f)
        out_path = cli_state["output_path"]
        if not os.path.exists(out_path):
            raise RuntimeError(f"output file not present: {out_path}")
        if not cli_state.get("output_sha256"):
            raise RuntimeError("output SHA-256 missing (CLI failed or did "
                               "not produce output)")
        log(f"[{label}] VERIFY + INDEPENDENT ORACLE "
            f"(streaming {args.rows:,} rows) ...")
        verify = verify_and_oracle(gen["path"], out_path, args.rows)
        for key in REQUIRED_RUN_CHECK_KEYS:
            log(f"[{label}]   {key}: {verify[key]}")
        log(f"[{label}]   oracle comparisons={verify['oracle_comparisons']:,} "
            f"mismatches={verify['oracle_mismatches']}")
        if verify["oracle_mismatches"]:
            log(f"[{label}]   mismatches_by_rule={verify['mismatches_by_rule']}")
        sp1 = sp1_frozen_verification(cli_state["engine_evidence_dir"],
                                       pinned)
        log(f"[{label}] SP1 frozen verification (names+hashes vs pinned "
            f"baseline): {sp1['status']} — {sp1['reason']}")
        runtime_safety = cli_state.get("runtime_safety") or {
            "status": "NOT_MEASURED",
            "reason": "runtime safety result absent from validate stage state"}
        pass_result.update({
            "blocked": cli_state["cli"]["returncode"] != 0,
            "cli": cli_state["cli"],
            "dataset": {
                "path": gen["path"], "rows": gen["rows"], "seed": gen["seed"],
                "columns": 33, "size_bytes": gen["size_bytes"],
                "sha256": gen["sha256"],
                "sha256_after_validation":
                    cli_state["input_sha256_after_validation"],
                "generation_seconds": gen["generation_seconds"],
            },
            "output": {
                "path": cli_state["output_path"],
                "rows": verify["output_rows"], "columns": 41,
                "size_bytes": cli_state["output_size_bytes"],
                "sha256": cli_state["output_sha256"],
            },
            "verification": verify,
            "sp1_frozen": sp1,
            "runtime_safety": runtime_safety,
            "pinned_rule_baseline_source": (pinned or {}).get("primary_source"),
            "peak_rss_mb": round(peak_rss_mb(), 2),
            "engine_peak_rss_mb": cli_state.get("engine_peak_rss_mb"),
            "verified_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        expected_comparisons = args.rows * len(FLAG_COLUMNS)
        required_ok = (
            not pass_result["blocked"]
            and gen["rows"] == args.rows and gen["seed"] == args.seed
            and all(verify[key] == "PASS" for key in REQUIRED_RUN_CHECK_KEYS)
            and verify["oracle_mismatches"] == 0
            and verify["oracle_comparisons"] == expected_comparisons
            and sp1["status"] == "PASS"
            and runtime_safety["status"] == "PASS"
            and gen["sha256"] == cli_state.get("input_sha256_after_validation"))
        exit_code = 0 if required_ok else 1
        if exit_code != 0:
            log(f"[{label}] VERIFY stage result: FAIL — saved; the final "
                f"gate will propagate this saved result.")
    except Exception as exc:
        pass_result["blocked"] = True
        pass_result["verify_error"] = f"{type(exc).__name__}: {exc}"
        log(f"[{label}] VERIFY stage BLOCKED: {pass_result['verify_error']}")
        exit_code = 1
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(pass_result, f, indent=2)
    return exit_code


def run_pass(pass_no, args, t_total0):
    """Single-shot full pass (generate -> validate -> verify). Fail-closed:
    every stage's SAVED result is recorded and propagated to the final gate;
    failures never abort evidence collection."""
    label = f"pass{pass_no}"
    try:
        phase_generate(args, pass_no)
    except Exception as exc:
        log(f"[{label}] BLOCKED: generate failed: {type(exc).__name__}: {exc}")
        return
    rc_validate = 1
    try:
        rc_validate = phase_validate(args, pass_no)
    except Exception as exc:
        log(f"[{label}] BLOCKED: validate failed: {type(exc).__name__}: {exc}")
    try:
        rc_verify = phase_verify(args, pass_no)
    except Exception as exc:
        log(f"[{label}] BLOCKED: verify failed: {type(exc).__name__}: {exc}")
        rc_verify = 1
    log(f"[{label}] stage exit codes: validate={rc_validate} "
        f"verify={rc_verify} (saved stage results are the authority)")


def load_pass_result(path):
    """Load and structurally validate one pass result file. Fail-closed:
    a missing / unreadable / malformed / old-format result is marked
    run_status=FAIL with reasons and can never be interpreted as PASS
    (stale-evidence protection)."""
    problems = []
    if not os.path.exists(path):
        return {"run_present": False, "run_status": "FAIL",
                "run_problems": [f"result file not present: {path}"]}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        return {"run_present": True, "run_status": "FAIL",
                "run_problems": [f"result file unreadable/malformed: {exc}"]}
    if not isinstance(data, dict):
        return {"run_present": True, "run_status": "FAIL",
                "run_problems": ["result file is not a JSON object"]}
    required = ("pass", "blocked", "cli", "dataset", "output",
                "verification", "sp1_frozen", "runtime_safety",
                "script_sha256", "git_commit")
    missing = [k for k in required if k not in data]
    if missing:
        data["run_status"] = "FAIL"
        data["run_problems"] = [
            f"missing required key (stale or foreign format): {k}"
            for k in missing]
    else:
        data["run_status"] = "OK"
        data["run_problems"] = []
    data["run_present"] = True
    return data


def _per_run_checks(run, pinned, script_sha256, git_commit,
                    expected_rows, expected_seed, wrapper_sha256=None):
    """ALL required checks for ONE run, evaluated ONLY from its SAVED result
    (Dave B/C: BOTH runs are evaluated through this exact same function; no
    process exit codes, no re-execution, no silent defaults).

    ``wrapper_sha256`` is the hash of the runtime-safety wrapper as
    actually executing. If the saved evidence carries a wrapper_sha256
    field, a mismatch is a stale-evidence FAIL (B-9 fix). If the saved
    evidence does not carry the field (pre-fix evidence), the check is
    recorded as None (not verified, not failed) for backward compat."""
    checks = {}
    reasons = []
    if run.get("run_status") != "OK":
        checks["run_result_file_valid"] = False
        reasons.extend(run.get("run_problems")
                       or ["run result not loaded/valid"])
        return checks, reasons
    checks["run_result_file_valid"] = True
    checks["run_not_blocked"] = run.get("blocked") is False
    if not checks["run_not_blocked"]:
        reasons.append("run marked blocked (production CLI failed)")
    cli = run.get("cli") or {}
    checks["cli_returncode_zero"] = cli.get("returncode") == 0
    if not checks["cli_returncode_zero"]:
        reasons.append(f"saved staged CLI result failed "
                       f"(returncode {cli.get('returncode')!r})")
    verification = run.get("verification") or {}
    for key in REQUIRED_RUN_CHECK_KEYS:
        ok = verification.get(key) == "PASS"
        checks[f"verification.{key}"] = ok
        if not ok:
            reasons.append(f"saved staged verification status "
                           f"{key}={verification.get(key)!r}")
    comparisons = verification.get("oracle_comparisons")
    expected_comparisons = expected_rows * len(FLAG_COLUMNS)
    checks["oracle.comparisons_expected"] = (
        isinstance(comparisons, int) and comparisons == expected_comparisons)
    if not checks["oracle.comparisons_expected"]:
        reasons.append(f"oracle comparisons {comparisons!r} != rows x 8 "
                       f"= {expected_comparisons}")
    mismatches = verification.get("oracle_mismatches")
    checks["oracle.mismatches_zero"] = mismatches == 0
    if not checks["oracle.mismatches_zero"]:
        reasons.append(f"saved staged oracle result: {mismatches!r} mismatches")
    dataset = run.get("dataset") or {}
    checks["dataset.rows_seed_expected"] = (
        dataset.get("rows") == expected_rows
        and dataset.get("seed") == expected_seed)
    if not checks["dataset.rows_seed_expected"]:
        reasons.append(f"dataset rows/seed {dataset.get('rows')!r}/"
                       f"{dataset.get('seed')!r} != {expected_rows}/"
                       f"{expected_seed}")
    sha_before = dataset.get("sha256")
    sha_after = dataset.get("sha256_after_validation")
    checks["input_immutable_during_validation"] = (
        isinstance(sha_before, str) and len(sha_before) == 64
        and sha_before == sha_after)
    if not checks["input_immutable_during_validation"]:
        reasons.append("input SHA-256 missing or changed during validation")
    output = run.get("output") or {}
    out_sha = output.get("sha256") or ""
    out_size = output.get("size_bytes")
    checks["output.integrity"] = (
        re.fullmatch(r"[0-9a-f]{64}", out_sha) is not None
        and isinstance(out_size, int) and out_size > 0
        and output.get("rows") == expected_rows)
    if not checks["output.integrity"]:
        reasons.append("output hash/size/rows incomplete in saved result")
    sp1 = run.get("sp1_frozen") or {}
    checks["sp1.expected_names_verified"] = (
        sp1.get("expected_names_verified") is True)
    checks["sp1.expected_hashes_verified"] = (
        sp1.get("expected_hashes_verified") is True)
    if pinned is None:
        checks["sp1.pinned_baseline_available"] = False
        reasons.append("pinned frozen rule baseline unavailable — expected "
                       "names/hashes cannot be established (values are "
                       "never invented)")
    else:
        checks["sp1.pinned_baseline_available"] = True
        manifest_hashes = sp1.get("manifest_rule_hashes")
        names_ok = (isinstance(manifest_hashes, dict)
                    and sorted(manifest_hashes.keys())
                    == list(pinned["expected_rule_names"]))
        hashes_ok = names_ok and all(
            isinstance(manifest_hashes.get(rid), str)
            and manifest_hashes[rid].startswith(head)
            for rid, head in pinned["expected_hash_heads"].items())
        checks["sp1.saved_manifest_names_match_pinned"] = bool(names_ok)
        checks["sp1.saved_manifest_hashes_match_pinned"] = bool(hashes_ok)
        if not names_ok:
            reasons.append("saved manifest rule name set does not match the "
                           "pinned expected names")
        elif not hashes_ok:
            reasons.append("saved manifest rule hashes do not match the "
                           "pinned expected hash heads")
    safety = run.get("runtime_safety") or {}
    # L-8 fix: the consumer MUST NOT trust the saved
    # runtime_safety.status field. The saved status is data, not
    # authority — an attacker with write access to the saved run
    # result JSON could forge status="PASS" while the events file
    # contains FAIL-worthy behavior. The consumer independently
    # re-reads, re-hashes, and re-classifies the events file, and
    # requires the derived status to match the saved status AND be
    # "PASS". Any missing field, missing file, hash mismatch, parse
    # failure, or derived-status mismatch is a hard FAIL.
    saved_status = safety.get("status")
    saved_events_path = safety.get("events_path")
    saved_events_file_sha256 = safety.get("events_file_sha256")
    runtime_safety_ok = False
    runtime_safety_reason = ""
    if saved_status != "PASS":
        # The saved status itself is not PASS — fail immediately
        # (covers NOT_MEASURED, FAIL, None, and any other value).
        runtime_safety_reason = (
            f"saved runtime_safety.status is {saved_status!r} "
            "(not PASS)")
    elif not isinstance(saved_events_path, str) or not saved_events_path:
        runtime_safety_reason = (
            "events_path missing or not a string in saved "
            "runtime_safety — cannot re-verify (L-8: missing "
            "events_path fails closed)")
    elif not isinstance(saved_events_file_sha256, str) \
            or not re.fullmatch(r"[0-9a-f]{64}",
                                  saved_events_file_sha256):
        runtime_safety_reason = (
            "events_file_sha256 missing or not a valid SHA-256 hex "
            "in saved runtime_safety — cannot re-verify (L-8: "
            "missing events_file_sha256 fails closed; no "
            "backward-compat bypass)")
    elif not os.path.exists(saved_events_path):
        runtime_safety_reason = (
            f"events file not present at saved events_path "
            f"{saved_events_path} — cannot re-verify (L-8: "
            "event-file deletion fails closed)")
    else:
        try:
            with open(saved_events_path, "rb") as f:
                events_raw = f.read()
        except Exception as exc:
            runtime_safety_reason = (
                f"events file unreadable: {exc} — cannot re-verify "
                "(L-8: unreadable event file fails closed)")
        else:
            computed_hash = hashlib.sha256(events_raw).hexdigest()
            if computed_hash != saved_events_file_sha256:
                runtime_safety_reason = (
                    f"events file hash mismatch — saved "
                    f"{saved_events_file_sha256[:16]}.. != computed "
                    f"{computed_hash[:16]}.. (L-8: tampered event "
                    "content fails closed)")
            else:
                derived = classify_runtime_safety_from_bytes(
                    events_raw, repo_root=REPO_ROOT)
                derived_status = derived.get("status")
                if derived_status != saved_status:
                    runtime_safety_reason = (
                        f"saved runtime_safety.status {saved_status!r} "
                        f"!= independently derived status "
                        f"{derived_status!r} (L-8: forged saved "
                        "status fails closed)")
                elif derived_status != "PASS":
                    runtime_safety_reason = (
                        f"independently derived runtime safety status "
                        f"{derived_status!r}: "
                        f"{derived.get('reason', '')[:120]}")
                else:
                    runtime_safety_ok = True
    checks["runtime_safety.pass"] = runtime_safety_ok
    if not runtime_safety_ok:
        reasons.append(f"runtime safety L-8 verification failed: "
                       f"{runtime_safety_reason}")
    checks["provenance.script_sha256_matches"] = (
        run.get("script_sha256") == script_sha256)
    if not checks["provenance.script_sha256_matches"]:
        reasons.append("stale evidence: run result script SHA-256 does not "
                       "match the checker computing this verdict")
    # Wrapper SHA-256 stale-evidence check (B-9 fix): only enforced when
    # the saved evidence carries the field. Pre-fix evidence (without
    # wrapper_sha256) is accepted for backward compatibility — the
    # field is absent, not mismatched. New evidence written by the fixed
    # validator always includes wrapper_sha256; any future tampering of
    # the wrapper will be detected on the next validator run.
    saved_wrapper_sha = run.get("wrapper_sha256")
    if saved_wrapper_sha is not None:
        checks["provenance.wrapper_sha256_matches"] = (
            saved_wrapper_sha == wrapper_sha256)
        if not checks["provenance.wrapper_sha256_matches"]:
            reasons.append("stale evidence: run result wrapper SHA-256 "
                           "does not match the currently executing "
                           "wrapper (B-9: wrapper tampering detected)")
    else:
        # Pre-fix evidence: wrapper_sha256 absent. Not a mismatch (the
        # field was not written by old validators), but also not
        # verified — record as None so downstream consumers know.
        checks["provenance.wrapper_sha256_matches"] = None
    checks["provenance.git_commit_matches"] = (
        git_commit is not None and run.get("git_commit") == git_commit)
    if not checks["provenance.git_commit_matches"]:
        reasons.append("stale evidence: run result git commit does not "
                       "match current HEAD")
    return checks, reasons


def evaluate_final_verdict(p1, p2, pinned, script_sha256, git_commit,
                           byte_identical_output, expected_rows=3_000_000,
                           expected_seed=20260910, wrapper_sha256=None):
    """The single authoritative fail-closed FINAL verdict gate (Dave §3).

    PURE function: no I/O, no clock, no process exit codes. Inputs are the
    loaded (structurally validated) pass results p1/p2, the pinned frozen
    baseline, the identity of the checker script computing the verdict, and
    the byte-identical comparison result actually performed at finalize
    (True / False / None = not performed). No stage result, exit code, or
    single-run shortcut can bypass this gate; FAIL / missing / incomplete /
    NOT_MEASURED / inconsistent / stale are explicit failures — never silent
    successes."""
    gates = {}
    reasons = []
    checks_1, reasons_1 = _per_run_checks(
        p1, pinned, script_sha256, git_commit, expected_rows, expected_seed,
        wrapper_sha256=wrapper_sha256)
    if p2 is None:
        checks_2 = {"run_result_file_valid": False}
        reasons_2 = ["Run 2 result not present — final PASS requires TWO "
                     "complete successful runs"]
    else:
        checks_2, reasons_2 = _per_run_checks(
            p2, pinned, script_sha256, git_commit, expected_rows,
            expected_seed, wrapper_sha256=wrapper_sha256)

    run1_structural = (bool(p1) and p1.get("run_status") == "OK"
                       and p1.get("blocked") is False)
    run2_structural = (p2 is not None and p2.get("run_status") == "OK"
                       and p2.get("blocked") is False)
    gates["exactly_two_complete_runs"] = (
        p2 is not None and run1_structural and run2_structural)
    gates["run1_complete"] = run1_structural and all(checks_1.values())
    gates["run2_complete"] = run2_structural and all(checks_2.values())
    gates["run1_all_required_checks_pass"] = all(checks_1.values())
    gates["run2_all_required_checks_pass"] = all(checks_2.values())
    gates["all_staged_results_successful"] = (
        all(v for k, v in checks_1.items() if not k.startswith("provenance."))
        and all(v for k, v in checks_2.items()
                if not k.startswith("provenance.")))

    # ── Safety (Dave D): PASS only if runtime-verified on BOTH runs ──
    safety_1 = (p1 or {}).get("runtime_safety") or {}
    safety_2 = ((p2 or {}).get("runtime_safety") or {}) if p2 else {}
    s1, s2 = safety_1.get("status"), safety_2.get("status")
    if s1 == "PASS" and s2 == "PASS":
        safety_overall = "PASS"
    elif "FAIL" in (s1, s2):
        safety_overall = "FAIL"
    else:
        safety_overall = "NOT_MEASURED"
    gates["safety_verified"] = safety_overall == "PASS"
    if not gates["safety_verified"]:
        reasons.append(f"runtime safety overall status: {safety_overall} "
                       f"(run_1={s1!r}, run_2={s2!r}) — final PASS requires "
                       "a runtime-verified PASS on both runs")

    # ── SP1 expected names + hashes (Dave E), BOTH runs — each gate requires
    # BOTH the saved stage boolean AND the re-derived comparison of the
    # saved manifest values against the pinned baseline (tamper-evident).
    gates["sp1_expected_names_verified"] = (
        checks_1.get("sp1.expected_names_verified") is True
        and checks_2.get("sp1.expected_names_verified") is True
        and checks_1.get("sp1.saved_manifest_names_match_pinned") is True
        and checks_2.get("sp1.saved_manifest_names_match_pinned") is True)
    gates["sp1_expected_hashes_verified"] = (
        checks_1.get("sp1.expected_hashes_verified") is True
        and checks_2.get("sp1.expected_hashes_verified") is True
        and checks_1.get("sp1.saved_manifest_hashes_match_pinned") is True
        and checks_2.get("sp1.saved_manifest_hashes_match_pinned") is True)
    if not gates["sp1_expected_names_verified"]:
        reasons.append("SP1 expected rule names not verified for BOTH runs")
    if not gates["sp1_expected_hashes_verified"]:
        reasons.append("SP1 expected rule hashes not verified against the "
                       "pinned frozen baseline for BOTH runs")

    # ── Determinism (Dave §10): both runs' hashes + ACTUAL comparison ──
    det = {
        "run_1_input_sha256": _dig(p1, "dataset", "sha256"),
        "run_2_input_sha256": _dig(p2, "dataset", "sha256"),
        "run_1_output_sha256": _dig(p1, "output", "sha256"),
        "run_2_output_sha256": _dig(p2, "output", "sha256"),
        "byte_identical_output": byte_identical_output,
        "byte_comparison_performed": byte_identical_output is not None,
    }
    det["input_hash_equal"] = (
        det["run_1_input_sha256"] is not None
        and det["run_1_input_sha256"] == det["run_2_input_sha256"])
    det["output_hash_equal"] = (
        det["run_1_output_sha256"] is not None
        and det["run_1_output_sha256"] == det["run_2_output_sha256"])
    ft1 = _dig(p1, "verification", "flag_totals")
    ft2 = _dig(p2, "verification", "flag_totals")
    det["flag_totals_equal"] = isinstance(ft1, dict) and ft1 == ft2
    gates["deterministic_outputs_verified"] = (
        det["input_hash_equal"] and det["output_hash_equal"]
        and det["byte_identical_output"] is True
        and det["flag_totals_equal"])
    if not gates["deterministic_outputs_verified"]:
        reasons.append("determinism not fully verified: " + json.dumps(
            {k: det[k] for k in ("input_hash_equal", "output_hash_equal",
                                 "byte_identical_output",
                                 "byte_comparison_performed",
                                 "flag_totals_equal")}))

    # ── Comparison counts (Dave F) ──
    c1 = _dig(p1, "verification", "oracle_comparisons")
    c2 = _dig(p2, "verification", "oracle_comparisons")
    combined = (c1 + c2 if (isinstance(c1, int) and isinstance(c2, int))
                else None)
    expected_per_run = expected_rows * len(FLAG_COLUMNS)
    comparison_count = {
        "definition": COMPARISON_COUNT_DEFINITION,
        "run_1": c1,
        "run_2": c2,
        "combined_total": combined,
        "expected_per_run": expected_per_run,
        "run_1_matches_rows_times_rules": c1 == expected_per_run,
        "run_2_matches_rows_times_rules": c2 == expected_per_run,
        "combined_total_equals_run_1_plus_run_2": (
            combined is not None and combined == c1 + c2),
    }
    counts_math_ok = (
        comparison_count["combined_total_equals_run_1_plus_run_2"] is True
        and comparison_count["run_1_matches_rows_times_rules"] is True
        and comparison_count["run_2_matches_rows_times_rules"] is True)

    # ── Evidence consistency (Dave §11-12) ──
    rows_equal = (p2 is not None
                  and _dig(p1, "dataset", "rows")
                  == _dig(p2, "dataset", "rows") == expected_rows)
    seed_equal = (p2 is not None
                  and _dig(p1, "dataset", "seed")
                  == _dig(p2, "dataset", "seed") == expected_seed)
    gates["evidence_consistent"] = (
        checks_1.get("provenance.script_sha256_matches") is True
        and checks_2.get("provenance.script_sha256_matches") is True
        and checks_1.get("provenance.git_commit_matches") is True
        and checks_2.get("provenance.git_commit_matches") is True
        and rows_equal and seed_equal and counts_math_ok
        and pinned is not None
        and pinned.get("secondary_conflict") is not True)
    if not gates["evidence_consistent"]:
        reasons.append("evidence inconsistency: provenance/stale/rows/seed/"
                       "comparison-count math/pinned-baseline state")
    if pinned is None:
        reasons.append("pinned frozen baseline unavailable — refusing PASS "
                       "(expected values are never invented)")

    final_status = "PASS" if all(gates.values()) else "FAIL"
    return {
        "final_status": final_status,
        "gates": gates,
        "gate_failures": [k for k, v in gates.items() if not v],
        "reasons": reasons,
        "runs": {
            "run_1": {"complete": gates["run1_complete"],
                      "checks": checks_1, "failure_reasons": reasons_1},
            "run_2": {"complete": gates["run2_complete"],
                      "checks": checks_2, "failure_reasons": reasons_2},
        },
        "determinism": det,
        "comparison_count": comparison_count,
        "safety": {
            "overall_status": safety_overall,
            "run_1_status": s1,
            "run_2_status": s2,
            "measurement": ("CPython audit-hook runtime instrumentation of "
                            "each production CLI subprocess "
                            "(scripts/final_3m_runtime_safety_wrapper.py): "
                            "PASS requires 0 socket events, 0 process-exec "
                            "events, and 0 out-of-repository mutations per "
                            "run; cooperative observation, not a kernel "
                            "sandbox"),
        },
        "sp1": {
            "expected_names_verified": gates["sp1_expected_names_verified"],
            "expected_hashes_verified": gates["sp1_expected_hashes_verified"],
            "pinned_source": (pinned or {}).get("primary_source"),
            "pinned_generated_at_utc":
                (pinned or {}).get("primary_generated_at_utc"),
            "expected_rule_names": (pinned or {}).get("expected_rule_names"),
            "secondary_sources_present":
                (pinned or {}).get("secondary_sources_present"),
            "secondary_conflict": (pinned or {}).get("secondary_conflict"),
            "note": ("expected rule names and hashes come from the pinned "
                     "frozen baseline (pre-existing canonical evidence); "
                     "they are never generated from the actual run values"),
        },
    }


def _run_summary(run):
    """Compact per-run view for FINAL_RESULTS.json (full detail remains in
    the saved pass result files)."""
    if not run or not run.get("run_present", False):
        return {"status": "MISSING",
                "note": "result file not present — final PASS requires it"}
    cli = run.get("cli") or {}
    verification = run.get("verification") or {}
    sp1 = run.get("sp1_frozen") or {}
    safety = run.get("runtime_safety") or {}
    summary = {
        "status": ("PASS" if (run.get("run_status") == "OK"
                              and run.get("blocked") is False)
                   else "FAIL"),
        "pass": run.get("pass"),
        "blocked": run.get("blocked"),
        "cli": {
            "returncode": cli.get("returncode"),
            "duration_seconds": cli.get("duration_seconds"),
            "canonical_command": cli.get("canonical_command"),
            "verdict": ("Validation PASSED"
                        if (cli.get("returncode") == 0
                            and "Validation PASSED" in str(cli.get("stdout", "")))
                        else "FAILED"),
            "stdout": cli.get("stdout"),
        },
        "dataset": {k: (run.get("dataset") or {}).get(k) for k in (
            "path", "rows", "seed", "columns", "size_bytes", "sha256",
            "sha256_after_validation", "generation_seconds")},
        "output": {k: (run.get("output") or {}).get(k) for k in (
            "path", "rows", "columns", "size_bytes", "sha256")},
        "verification_statuses": {k: verification.get(k)
                                  for k in REQUIRED_RUN_CHECK_KEYS},
        "oracle": {
            "comparisons": verification.get("oracle_comparisons"),
            "mismatches": verification.get("oracle_mismatches"),
            "mismatches_by_rule": verification.get("mismatches_by_rule"),
            "first_mismatches": verification.get("first_mismatches"),
            "flag_totals": verification.get("flag_totals"),
        },
        "sp1_frozen": {
            "status": sp1.get("status"),
            "expected_names_verified": sp1.get("expected_names_verified"),
            "expected_hashes_verified": sp1.get("expected_hashes_verified"),
            "reason": sp1.get("reason"),
        },
        "runtime_safety": {
            "status": safety.get("status"),
            "reason": safety.get("reason"),
        },
        "stage_runtime_seconds": {
            "generation": _dig(run, "dataset", "generation_seconds"),
            "validation": cli.get("duration_seconds"),
            "verify_oracle": verification.get("verify_duration_seconds"),
        },
        "engine_peak_rss_mb": run.get("engine_peak_rss_mb"),
    }
    if run.get("verify_error"):
        summary["verify_error"] = run["verify_error"]
    return summary


def phase_finalize(args):
    """PHASE: finalize — the fail-closed final verdict gate + FINAL_RESULTS.json.

    Loads BOTH saved run results (fail-closed on missing/malformed), performs
    the ACTUAL byte-identical comparison over both runs' output files,
    evaluates the single authoritative gate, writes FINAL_RESULTS.json
    atomically with full provenance, and reclaims pass2 bulk CSVs only on a
    final PASS."""
    ident = script_identity()
    commit = git_commit_id()
    pinned = load_pinned_rule_baseline()
    p1 = load_pass_result(
        os.path.join(args.evidence_dir, "pass1_result.json"))
    p2 = load_pass_result(
        os.path.join(args.evidence_dir, "pass2_result.json"))
    p2 = p2 if p2.get("run_present") else None

    # ACTUAL byte-identical comparison at finalize (before any cleanup):
    byte_identical_output = None
    byte_compare_note = "byte comparison NOT performed (counts as FAIL)"
    out1 = _dig(p1, "output", "path")
    out2 = _dig(p2, "output", "path") if p2 else None
    if out1 and out2 and os.path.exists(out1) and os.path.exists(out2):
        byte_identical_output = filecmp.cmp(out1, out2, shallow=False)
        byte_compare_note = ("filecmp.cmp(shallow=False) executed at "
                             "finalize over both runs' output CSVs")
    elif out1 or out2:
        byte_compare_note = ("byte comparison NOT performed: one or both "
                             "output files not present (counts as FAIL)")
    log(f"DETERMINISM: byte_identical_output={byte_identical_output} "
        f"({byte_compare_note})")

    verdict = evaluate_final_verdict(
        p1, p2, pinned, ident["script_sha256"], commit,
        byte_identical_output,
        expected_rows=args.rows, expected_seed=args.seed,
        wrapper_sha256=ident.get("wrapper_sha256"))

    gates = verdict["gates"]
    final_status = verdict["final_status"]

    # Authoritative whole-run peak memory: engine child peak (validation
    # stage) across BOTH runs.
    harness_peak = max(_dig(p1, "peak_rss_mb") or 0,
                       _dig(p2, "peak_rss_mb") or 0)
    engine_peak = max(_dig(p1, "engine_peak_rss_mb") or 0,
                      _dig(p2, "engine_peak_rss_mb") or 0)
    peak_memory_mb = max(engine_peak, harness_peak)

    stage_runtimes = {}
    for label, run in (("pass1", p1), ("pass2", p2)):
        if run and run.get("run_present"):
            stage_runtimes[f"generation_{label}"] = _dig(
                run, "dataset", "generation_seconds")
            stage_runtimes[f"validation_{label}"] = _dig(
                run, "cli", "duration_seconds")
            stage_runtimes[f"verify_oracle_{label}"] = _dig(
                run, "verification", "verify_duration_seconds")
    total_runtime = sum(t for t in stage_runtimes.values()
                        if isinstance(t, (int, float)))

    def _both_statuses(keys):
        vals = [_dig(p1, "verification", k) for k in keys]
        if p2 is not None:
            vals += [_dig(p2, "verification", k) for k in keys]
        return "PASS" if all(v == "PASS" for v in vals) else "FAIL"

    mism_1 = _dig(p1, "verification", "oracle_mismatches")
    mism_2 = _dig(p2, "verification", "oracle_mismatches") if p2 else None
    combined_mism = (mism_1 + mism_2
                     if isinstance(mism_1, int) and isinstance(mism_2, int)
                     else None)

    final = {
        "report": "FINAL 3M VALIDATION RESULTS",
        "checker_version": CHECKER_VERSION,
        "verdict_model": (
            "single authoritative fail-closed gate (Dave review requirements "
            "A-F): no stage result, process exit code, or single-run "
            "shortcut can bypass it; BOTH runs must pass EVERY check"),
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "provenance": {
            "script_path": ident["script_path"],
            "script_sha256": ident["script_sha256"],
            "script_sha256_note": ("SHA-256 of the exact checker script file "
                                   "used to compute this verdict"),
            "git_commit": commit,
            "git_commit_note": ("exact git commit used to generate this "
                                "result"),
            "stale_evidence_protection": (
                "every saved stage result must carry the same script_sha256 "
                "and git_commit as the checker computing this verdict; any "
                "mismatch (stale/foreign evidence) fails the final gate"),
        },
        "rows": args.rows,
        "columns": 33,
        "output_columns": 41,
        "seed": args.seed,
        "input_sha256": _dig(p1, "dataset", "sha256"),
        "output_sha256": _dig(p1, "output", "sha256"),
        "input_size_bytes": _dig(p1, "dataset", "size_bytes"),
        "output_size_bytes": _dig(p1, "output", "size_bytes"),
        "runs": {"run_1": _run_summary(p1), "run_2": _run_summary(p2)},
        "runtime_seconds": round(total_runtime, 3),
        "runtime_note": ("sum of staged phase runtimes "
                         "(generation+validation+verify per pass)"),
        "stage_runtime_seconds": stage_runtimes,
        "peak_memory_mb": peak_memory_mb,
        "peak_memory_note": (
            "engine subprocess peak RSS via resource.getrusage"
            "(RUSAGE_CHILDREN) measured post-exit in the validate phase "
            "(authoritative); harness verify-process peak was "
            f"{harness_peak} MB"),
        "comparison_count": verdict["comparison_count"],
        "oracle_comparisons": verdict["comparison_count"]["combined_total"],
        "oracle_comparisons_note": (
            "combined_total = run_1 + run_2 (each run = rows x 8 flag "
            "rules); per-run values in comparison_count — this key is the "
            "COMBINED figure, never a single-run figure"),
        "oracle_mismatches": {
            "run_1": mism_1,
            "run_2": mism_2,
            "combined_total": combined_mism,
        },
        "mismatches_by_rule": _dig(p1, "verification", "mismatches_by_rule"),
        "mismatches_by_rule_note": (
            "run_1 detail (run_2 detail in runs.run_2.oracle); BOTH runs "
            "must be 0 mismatches for final PASS"),
        "first_mismatches": _dig(p1, "verification", "first_mismatches"),
        "flag_totals_output_csv": _dig(p1, "verification", "flag_totals"),
        "flag_totals_run_2_equal": verdict["determinism"]["flag_totals_equal"],
        "flag_totals_engine_cli": _dig(p1, "cli", "stdout"),
        "schema_status": _both_statuses(("schema_status",
                                         "column_count_status",
                                         "column_order_status")),
        "preservation_status": _both_statuses((
            "row_count_status", "row_identity_status", "row_ordering_status",
            "source_values_preserved_status", "output_shape_status",
            "flag_domain_status")),
        "determinism_status": (
            "PASS (byte-identical across two complete runs)"
            if gates["deterministic_outputs_verified"] else "FAIL"),
        "determinism_detail": dict(verdict["determinism"],
                                   byte_comparison_note=byte_compare_note),
        "safety": verdict["safety"],
        "safety_status": verdict["safety"]["overall_status"],
        "safety_status_note": (
            "PASS only when runtime-verified on BOTH runs via audit-hook "
            "instrumentation; NOT_MEASURED never satisfies final PASS"),
        "sp1": verdict["sp1"],
        "sp1_isolation_status": (
            "PASS" if (gates["sp1_expected_names_verified"]
                       and gates["sp1_expected_hashes_verified"]) else "FAIL"),
        "cli_verdict": {
            "run_1": _dig(p1, "cli", "returncode"),
            "run_2": _dig(p2, "cli", "returncode") if p2 else None,
        },
        "gates": gates,
        "gate_failures": verdict["gate_failures"],
        "failure_reasons": verdict["reasons"],
        "final_status": final_status,
        "environment": {
            "python": sys.version.split()[0],
            "os": sys.platform,
        },
        "pass2": ({
            "dataset_sha256": _dig(p2, "dataset", "sha256"),
            "output_sha256": _dig(p2, "output", "sha256"),
            "cli_returncode": _dig(p2, "cli", "returncode"),
            "oracle_mismatches": mism_2,
        } if p2 else None),
    }

    results_path = os.path.join(args.evidence_dir, "FINAL_RESULTS.json")
    tmp_path = results_path + ".tmp"

    def _write_results():
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(final, f, indent=2)
        os.replace(tmp_path, results_path)  # atomic evidence writing

    _write_results()
    log(f"FINAL_RESULTS.json written (atomic): {results_path}")

    # Reclaim pass2 bulk CSVs ONLY on a final PASS (determinism proven, all
    # hashes recorded). On FAIL the files are kept for debugging/forensics.
    if final_status == "PASS" and p2 is not None and not args.keep_pass2:
        removed = []
        for path in (_dig(p2, "dataset", "path"),
                     _dig(p2, "output", "path")):
            if path and os.path.exists(path):
                os.remove(path)
                removed.append(path)
        final["pass2_files_removed_after_byte_identical_proof"] = removed
        _write_results()
        log(f"pass2 bulk CSVs removed after byte-identity proof: {removed}")

    def _fmt(value):
        return f"{value:,}" if isinstance(value, int) else repr(value)

    log("=" * 72)
    log("FINAL 3M VALIDATION SUMMARY (fail-closed gate)")
    log(f"  final_status: {final_status}")
    if verdict["gate_failures"]:
        log(f"  FAILED GATES: {verdict['gate_failures']}")
    for reason in verdict["reasons"][:12]:
        log(f"  reason: {reason}")
    log(f"  rows: {final['rows']:,}  columns: 33 -> 41   "
        f"seed: {final['seed']}")
    log(f"  input_sha256:  {final['input_sha256']}")
    log(f"  output_sha256: {final['output_sha256']}")
    log(f"  runtime_seconds: {final['runtime_seconds']}  "
        f"peak_memory_mb: {final['peak_memory_mb']}")
    cc = final["comparison_count"]
    log(f"  comparison_count: run_1={_fmt(cc['run_1'])} "
        f"run_2={_fmt(cc['run_2'])} "
        f"combined_total={_fmt(cc['combined_total'])}")
    log(f"  oracle_mismatches: run_1={mism_1} run_2={mism_2} "
        f"combined={combined_mism}")
    log(f"  safety_status: {final['safety_status']}")
    log(f"  sp1_expected_names_verified: "
        f"{gates['sp1_expected_names_verified']}")
    log(f"  sp1_expected_hashes_verified: "
        f"{gates['sp1_expected_hashes_verified']}")
    log(f"  determinism_status: {final['determinism_status']}")
    log(f"  schema_status: {final['schema_status']}  "
        f"preservation_status: {final['preservation_status']}")
    log(f"  script_sha256: {ident['script_sha256']}")
    log(f"  git_commit: {commit}")
    log("=" * 72)
    return 0 if final_status == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description="Final 3M independent validation")
    parser.add_argument("--phase", default="all",
                        choices=["all", "generate", "validate", "verify", "finalize"],
                        help="Execution phase (staged mode for constrained shells); "
                             "'all' runs everything in one process")
    parser.add_argument("--pass-no", type=int, default=1, choices=[1, 2])
    parser.add_argument("--rows", type=int, default=3_000_000)
    parser.add_argument("--seed", type=int, default=20260910)
    parser.add_argument("--passes", type=int, default=2, choices=[1, 2],
                        help="passes executed by --phase all; the final "
                             "verdict REQUIRES two complete runs regardless")
    parser.add_argument("--data-dir", default=os.path.join(
        REPO_ROOT, "data", "generated", "final_3m"))
    parser.add_argument("--evidence-dir", default=os.path.join(
        REPO_ROOT, "evidence", "final_3m_validation"))
    parser.add_argument("--keep-pass2", action="store_true",
                        help="Keep pass2 CSVs after byte-identity is proven "
                             "(default: delete to reclaim disk, hashes retained)")
    args = parser.parse_args()
    transcription_self_check()
    os.makedirs(args.evidence_dir, exist_ok=True)
    t_total0 = time.perf_counter()

    log("=" * 72)
    log("FINAL 3M VALIDATION — independent harness (fail-closed edition)")
    log(f"checker_version: {CHECKER_VERSION}")
    log(f"phase={args.phase} rows={args.rows:,} seed={args.seed} "
        f"pass_no={args.pass_no} passes={args.passes}")
    log(f"script_sha256={script_identity()['script_sha256']}")
    log(f"git_commit={git_commit_id()}")
    log(f"started_utc={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")
    log("=" * 72)

    if args.phase == "generate":
        try:
            phase_generate(args, args.pass_no)
            return 0
        except Exception as exc:
            log(f"GENERATE FAILED: {type(exc).__name__}: {exc}")
            return 1
    if args.phase == "validate":
        try:
            return phase_validate(args, args.pass_no)
        except Exception as exc:
            log(f"VALIDATE FAILED: {type(exc).__name__}: {exc}")
            return 1
    if args.phase == "verify":
        return phase_verify(args, args.pass_no)
    if args.phase == "finalize":
        return phase_finalize(args)

    # --phase all: single-process full behavior. Fail-closed: every stage
    # failure is recorded in the saved stage results; the final verdict
    # ALWAYS comes from phase_finalize's authoritative gate.
    for pass_no in range(1, args.passes + 1):
        run_pass(pass_no, args, t_total0)
    return phase_finalize(args)


if __name__ == "__main__":
    sys.exit(main())
