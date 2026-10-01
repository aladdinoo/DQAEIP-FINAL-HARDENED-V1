#!/usr/bin/env python3
"""Build the permanent golden regression corpus (DQAVP Section 12).

Every confirmed defect / boundary / ambiguity becomes:
    minimal reproducible case -> expected decision -> regression corpus
    entry -> permanent evidence.

Corpus policy:
- Expected values are computed by EXECUTING the frozen production rules
  (the corpus pins CURRENT V1 behavior as the compatibility baseline).
- Every case is cross-checked against the independent oracle; any
  disagreement aborts the build (fail closed) — the corpus may never
  encode an engine/oracle split.
- Known ambiguities (real-world vs frozen V1 semantics) are marked
  ``review_required`` with an explanation — never silently decided.

Output: tests/golden/regression_corpus.json
"""

import csv
import importlib.util
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_quality_platform.contracts import FLAG_COLUMNS
from data_quality_platform.rules.registry import RuleRegistry

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORACLE_PATH = os.path.join(REPO_ROOT, "scripts", "final_3m_validation.py")
OUT_PATH = os.path.join(REPO_ROOT, "tests", "golden",
                        "regression_corpus.json")

# Curated minimal cases. `input` holds partial row fields; missing fields
# default to "". Each case documents its area and origin.
CASES = [
    # ---- email area ---------------------------------------------------
    ("RC-E01", "email", "blank email flags email_blank only",
     {"email_address": ""}, False),
    ("RC-E02", "email", "whitespace-only email flags email_blank (strip semantics)",
     {"email_address": "   "}, False),
    ("RC-E03", "email", "null-like missing email field",
     {"email_address": None}, False),
    ("RC-E04", "email", "valid simple email",
     {"email_address": "user@example.com"}, False),
    ("RC-E05", "email", "padded valid email is stripped before matching",
     {"email_address": "  user@example.com  "}, False),
    ("RC-E06", "email", "no-at-sign invalid syntax",
     {"email_address": "not-an-email"}, False),
    ("RC-E07", "email", "double @ invalid",
     {"email_address": "user@@double.com"}, False),
    ("RC-E08", "email", "single-char TLD invalid under V1 regex",
     {"email_address": "user@x.c"}, False),
    ("RC-E09", "email", "multi-label TLD valid",
     {"email_address": "user@mail.example.co.uk"}, False),
    ("RC-E10", "email", "plus-tag valid",
     {"email_address": "u.ser+tag@sub.example.io"}, False),
    ("RC-E11", "email", "consecutive dots ACCEPTED by V1 regex (known gap)",
     {"email_address": "bad..dots@example.com"}, False),
    ("RC-E12", "email", "unicode local part rejected by V1 regex",
     {"email_address": "Ü@example.com"}, False),
    ("RC-E13", "email", "hyphen domain valid",
     {"email_address": "user@my-site.org"}, False),
    # ---- first/last name area -----------------------------------------
    ("RC-N01", "name", "suspicious substring 'test' in first name",
     {"first_name": "Test"}, False),
    ("RC-N02", "name", "suspicious substring embedded in last name",
     {"last_name": "McTesty"}, False),
    ("RC-N03", "name", "digit in first name flags non-alpha",
     {"first_name": "John2"}, False),
    ("RC-N04", "name", "punctuation in last name flags non-alpha",
     {"last_name": "O!Brien"}, False),
    ("RC-N05", "name", "hyphen allowed (no flag)",
     {"first_name": "Anne-Marie"}, False),
    ("RC-N06", "name", "apostrophe allowed (no flag)",
     {"first_name": "O'Brien"}, False),
    ("RC-N07", "name", "repeated single character flags",
     {"first_name": "aaaa"}, False),
    ("RC-N08", "name", "repeated char with apostrophe flags",
     {"first_name": "zz'z"}, False),
    ("RC-N09", "name", "unicode alpha NOT flagged (str.isalpha true)",
     {"first_name": "José"}, False),
    ("RC-N10", "name", "padded suspicious name still flagged (strip)",
     {"first_name": "  Test  "}, False),
    ("RC-N11", "name", "blank first name: no name flags",
     {"first_name": "", "last_name": "Smith"}, False),
    # ---- full-name combination area -------------------------------------
    ("RC-F01", "name", "first equals last (case-insensitive) flags",
     {"first_name": "Chris", "last_name": "chris"}, False),
    ("RC-F02", "name", "both single char flags",
     {"first_name": "A", "last_name": "B"}, False),
    ("RC-F03", "name", "one single char + one long: no flag",
     {"first_name": "A", "last_name": "Johnson"}, False),
    ("RC-F04", "name", "both blank: no flag",
     {"first_name": "", "last_name": ""}, False),
    ("RC-F05", "name", "equal names with different case+padding",
     {"first_name": " Lee ", "last_name": "lee"}, False),
    # ---- zip/state assessability area ------------------------------------
    ("RC-Z01", "geography", "assessable NY/10001 no mismatch",
     {"zip": "10001", "state": "NY"}, False),
    ("RC-Z02", "geography", "mismatch NY/90210",
     {"zip": "90210", "state": "NY"}, False),
    ("RC-Z03", "geography", "blank zip: not assessable",
     {"zip": "", "state": "NY"}, False),
    ("RC-Z04", "geography", "blank state: not assessable",
     {"zip": "10001", "state": ""}, False),
    ("RC-Z05", "geography", "whitespace zip: not assessable (strip)",
     {"zip": "   ", "state": "NY"}, False),
    ("RC-Z06", "geography", "lowercase state normalized to upper",
     {"zip": "10001", "state": "ny"}, False),
    ("RC-Z07", "geography", "padded state normalized",
     {"zip": "10001", "state": " NY "}, False),
    ("RC-Z08", "geography", "unknown state ZZ: not assessable",
     {"zip": "12345", "state": "ZZ"}, False),
    ("RC-Z09", "geography", "territory PR: not in map, not assessable",
     {"zip": "00901", "state": "PR"}, False),
    ("RC-Z10", "geography", "six-digit zip with in-map state still assessable; "
     "prefix mismatch", {"zip": "123456", "state": "NY"}, False),
    ("RC-Z11", "geography", "alpha zip with in-map state still assessable; "
     "prefix mismatch", {"zip": "12A45", "state": "NY"}, False),
    ("RC-Z12", "geography", "shared-prefix control: UT/84501 is NO mismatch "
     "(845 spans UT/OK; documented DL013 control)",
     {"zip": "84501", "state": "UT"}, False),
    # ---- REVIEW_REQUIRED: real-world vs frozen V1 -------------------------
    ("RC-R01", "geography", "REVIEW: ZIP 73301 is Austin TX in real USPS "
     "geography, but frozen V1 map assigns prefix 73 to OK only -> V1 flags "
     "mismatch. Same class as golden cases 11/37/50.",
     {"zip": "73301", "state": "TX"}, True),
    ("RC-R02", "geography", "REVIEW: lowercase state that WOULD mismatch "
     "under uppercase normalization (tx/10001) — pins the normalization "
     "dependency explicitly.",
     {"zip": "10001", "state": "tx"}, True),
]


def main():
    spec = importlib.util.spec_from_file_location("f3m_corpus",
                                                  ORACLE_PATH)
    f3m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(f3m)

    registry = RuleRegistry.create_default()
    corpus = []
    disagreements = []
    for case_id, area, origin, partial, review in CASES:
        row = {c: "" for c in f3m.SOURCE_COLUMNS}
        row.update({k: ("" if v is None else v)
                    for k, v in partial.items()})
        row.setdefault("id", case_id)
        expected = {}
        for rule in registry.get_all_rules():
            expected[rule.rule_id] = rule.execute(row)
        oracle = f3m.oracle_flags(row)
        for flag in FLAG_COLUMNS:
            if oracle[flag] != expected[flag]:
                disagreements.append((case_id, flag, expected[flag],
                                      oracle[flag]))
        corpus.append({
            "case_id": case_id,
            "area": area,
            "origin": origin,
            "review_required": review,
            "input": {k: v for k, v in partial.items()},
            "expected": expected,
        })

    if disagreements:
        print("FATAL: engine/oracle disagreement — corpus build aborted:")
        for d in disagreements:
            print("  ", d)
        return 1

    doc = {
        "corpus_version": "1.0.0",
        "generated_utc": __import__("time").strftime(
            "%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
        "policy": (
            "Expected values are the CURRENT frozen V1 behavior, "
            "computed by executing the production rules and cross-checked "
            "against the independent oracle (build aborts on any "
            "disagreement). review_required cases pin V1 behavior that is "
            "known to diverge from real-world/company expectations; the "
            "ambiguity is documented, never silently decided."),
        "case_count": len(corpus),
        "review_required_count": sum(c["review_required"]
                                     for c in corpus),
        "areas": sorted({c["area"] for c in corpus}),
        "cases": corpus,
    }
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    print(f"corpus written: {OUT_PATH}")
    print(f"cases: {len(corpus)} "
          f"(review_required: {doc['review_required_count']})")
    print(f"areas: {doc['areas']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
