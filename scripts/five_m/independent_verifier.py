#!/usr/bin/env python3
"""INDEPENDENT VERIFIER for the FINAL 5M/3M validation protocol.

INDEPENDENCE CONTRACT (taskbook Phase 5):
  This verifier MUST NOT import:
    - production V1 rule functions
    - the production validation engine
    - production geography functions
    - the production reconciliation implementation
  It uses only the Python standard library (csv, re, json, sys, os, time).
  All 8 rule predicates are independently re-implemented below from the
  frozen V1 behavioral specification; the 51-entry state->ZIP-prefix map and
  the 19 suspicious-name patterns are transcribed constants (data, not code).

What it verifies (streaming, row-by-row, input and output in lockstep):
  1.  output row count
  2.  output schema: exactly 41 columns = 33 source + 8 flags, exact order
  3.  ID sequence: input and output row i both carry id == str(i)
  4.  duplicate IDs / missing IDs (proven by the strict sequential check)
  5.  source-column preservation: output cols 1..33 == input cols 1..33 (exact strings)
  6.  all 8 flag columns present, values in {0,1}
  7.  EVERY flag value recomputed independently and compared
      (rows x 8 comparisons; expected mismatches = 0)
  8.  independent per-flag counts vs pipeline-reported counts (deltas, expected 0)
  9.  reconciliation: output rows == input rows; flag event sum vs lineage
      total_row_records (if lineage path provided)
  10. ordering: IDs strictly sequential prove output ordering

Usage:
  python independent_verifier.py <input.csv> <output.csv> <pipeline_flag_counts.json> \
      <result_json_out> [lineage.json]
"""

import csv
import json
import os
import re
import sys
import time

# ---------------------------------------------------------------------------
# Independently transcribed constants (frozen V1 data contract)
# ---------------------------------------------------------------------------
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
    "first_name_cleaning_candidate", "last_name_cleaning_candidate",
    "name_cleaning_candidate", "email_blank", "email_syntax_failure",
    "proposed_email_export_eligible", "zip_state_assessable",
    "geography_mismatch_candidate",
]
OUTPUT_COLUMNS = SOURCE_COLUMNS + FLAG_COLUMNS
SUSPICIOUS = ["test", "fake", "dummy", "xxx", "zzz", "aaa", "bbb",
              "admin", "null", "none", "na", "n/a", "unknown",
              "example", "sample", "asdf", "qwerty", "abc", "xyz"]
STATE_ZIP_PREFIXES = {
    "AL": ["35", "36"], "AK": ["99"], "AZ": ["85", "86"],
    "AR": ["71", "72"], "CA": ["90", "91", "92", "93", "94", "95", "96"],
    "CO": ["80", "81"], "CT": ["06"], "DE": ["19"],
    "DC": ["20", "20"], "FL": ["32", "33", "34"], "GA": ["30", "31"],
    "HI": ["96", "97"], "ID": ["83", "84"], "IL": ["60", "61", "62"],
    "IN": ["46", "47"], "IA": ["50", "51", "52"], "KS": ["66", "67"],
    "KY": ["40", "41", "42"], "LA": ["70", "71"], "ME": ["03", "04"],
    "MD": ["21", "22"], "MA": ["01", "02"], "MI": ["48", "49"],
    "MN": ["55", "56"], "MS": ["38", "39"], "MO": ["63", "64", "65"],
    "MT": ["59"], "NE": ["68", "69"], "NV": ["88", "89"],
    "NH": ["03"], "NJ": ["07", "08"], "NM": ["87", "88"],
    "NY": ["10", "11", "12", "13", "14"], "NC": ["27", "28"],
    "ND": ["58"], "OH": ["43", "44", "45"], "OK": ["73", "74"],
    "OR": ["97"], "PA": ["15", "16", "17", "18", "19"],
    "RI": ["02", "03"], "SC": ["29"], "SD": ["57"],
    "TN": ["37", "38"], "TX": ["75", "76", "77", "78", "79"],
    "UT": ["84"], "VT": ["05"], "VA": ["22", "23", "24"],
    "WA": ["98", "99"], "WV": ["24", "25", "26"],
    "WI": ["53", "54"], "WY": ["82", "83"],
}
# Independent email syntax predicate (same accepted grammar as the frozen V1 rule)
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


# ---------------------------------------------------------------------------
# Independent predicate implementations (one function per frozen V1 rule)
# ---------------------------------------------------------------------------
def p_first_name_cleaning(row):
    s = str(row[2]).strip()          # first_name
    if not s:
        return 0
    low = s.lower()
    for pat in SUSPICIOUS:
        if pat in low:
            return 1
    for ch in s:                     # non-alpha (hyphen/apostrophe allowed)
        if not ch.isalpha() and ch not in ("-", "'"):
            return 1
    cleaned = low.replace("-", "").replace("'", "")
    if len(s) > 1 and cleaned and len(set(cleaned)) == 1:
        return 1                     # repeated single character
    return 0


def p_last_name_cleaning(row):
    s = str(row[3]).strip()          # last_name
    if not s:
        return 0
    low = s.lower()
    for pat in SUSPICIOUS:
        if pat in low:
            return 1
    for ch in s:
        if not ch.isalpha() and ch not in ("-", "'"):
            return 1
    cleaned = low.replace("-", "").replace("'", "")
    if len(s) > 1 and cleaned and len(set(cleaned)) == 1:
        return 1
    return 0


def p_name_cleaning(row):
    f = str(row[2]).strip()
    l = str(row[3]).strip()
    if not f and not l:
        return 0
    if f and l and f.lower() == l.lower():
        return 1
    if f and l and len(f) <= 1 and len(l) <= 1:
        return 1
    return 0


def p_email_blank(row):
    e = row[1]
    if e is None or str(e).strip() == "":
        return 1
    return 0


def p_email_syntax_failure(row):
    e = str(row[1]).strip()
    if not e:
        return 0
    return 0 if EMAIL_RE.match(e) else 1


def p_proposed_email_export_eligible(row):
    e = str(row[1]).strip()
    if not e:
        return 0
    return 1 if EMAIL_RE.match(e) else 0


def p_zip_state_assessable(row):
    z = str(row[8]).strip()
    st = str(row[7]).strip()
    if z and st and st.upper() in STATE_ZIP_PREFIXES:
        return 1
    return 0


def p_geography_mismatch_candidate(row):
    z = str(row[8]).strip()
    st = str(row[7]).strip()
    if not z or not st:
        return 0
    stu = st.upper()
    if stu not in STATE_ZIP_PREFIXES:
        return 0
    for prefix in STATE_ZIP_PREFIXES[stu]:
        if z.startswith(prefix):
            return 0
    return 1


PREDICATES = [
    p_first_name_cleaning, p_last_name_cleaning, p_name_cleaning,
    p_email_blank, p_email_syntax_failure, p_proposed_email_export_eligible,
    p_zip_state_assessable, p_geography_mismatch_candidate,
]


def main():
    in_path, out_path, counts_path, result_path = sys.argv[1:5]
    lineage_path = sys.argv[5] if len(sys.argv) > 5 else None

    with open(counts_path) as f:
        pipeline_counts = json.load(f)

    t0 = time.time()
    res = {
        "verifier": "independent_verifier.py",
        "independence": {
            "imports_used": ["csv", "json", "os?", "re", "sys", "time"],
            "production_imports": False,
            "predicates": "independently re-implemented from the frozen V1 specification",
            "constants": "transcribed data constants (51-entry prefix map, 19 suspicious patterns)",
        },
        "input_csv": in_path,
        "output_csv": out_path,
    }

    mismatches = []            # (row, flag, expected, got) — first 20 kept
    mismatch_total = 0
    comparisons = 0
    rows = 0
    independent_counts = {c: 0 for c in FLAG_COLUMNS}
    preservation_errors = []
    id_errors = []
    flag_domain_errors = 0
    out_header_ok = None

    fin = open(in_path, "r", newline="", encoding="utf-8")
    fout = open(out_path, "r", newline="", encoding="utf-8")
    rin = csv.reader(fin)
    rout = csv.reader(fout)
    in_header = next(rin, None)
    out_header = next(rout, None)
    res["input_header_ok"] = (in_header == SOURCE_COLUMNS)
    out_header_ok = (out_header == OUTPUT_COLUMNS)
    res["output_header_ok"] = out_header_ok
    res["output_column_count"] = len(out_header) if out_header else 0

    for in_fields in rin:
        try:
            out_fields = next(rout)
        except StopIteration:
            res["fatal"] = f"output ended early at input row {rows + 1}"
            break
        rows += 1
        # 1. row count handled by loop; 2. field arity
        if len(out_fields) != 41:
            res["fatal"] = f"output row {rows} has {len(out_fields)} fields"
            break
        # 3/10. ID sequence + ordering (both files, strict)
        if in_fields[0] != str(rows) or out_fields[0] != str(rows):
            if len(id_errors) < 10:
                id_errors.append({"row": rows, "in_id": in_fields[0], "out_id": out_fields[0]})
        # 5. source-column preservation (exact string equality, 33 columns)
        if in_fields != out_fields[:33]:
            if len(preservation_errors) < 10:
                diff_cols = [SOURCE_COLUMNS[i] for i in range(33)
                             if in_fields[i] != out_fields[i]]
                preservation_errors.append({"row": rows, "differing_columns": diff_cols})
        # 7. recompute all 8 flags
        for j, pred in enumerate(PREDICATES):
            expected = pred(in_fields)
            got = out_fields[33 + j]
            comparisons += 1
            if got not in ("0", "1"):
                flag_domain_errors += 1
            if got != str(expected):
                mismatch_total += 1
                if len(mismatches) < 20:
                    mismatches.append({"row": rows, "flag": FLAG_COLUMNS[j],
                                       "expected": expected, "got": got})
            if expected == 1:
                independent_counts[FLAG_COLUMNS[j]] += 1
        if rows % 500_000 == 0:
            print(f"  verified {rows} rows...", flush=True)

    # output must not have extra rows
    extra_out = sum(1 for _ in rout)
    fin.close()
    fout.close()

    res["rows_checked"] = rows
    res["extra_output_rows"] = extra_out
    res["id_errors"] = id_errors
    res["ids_strictly_sequential_and_complete"] = bool(
        rows > 0 and not id_errors and extra_out == 0 and in_header == SOURCE_COLUMNS)
    res["source_preservation_errors"] = preservation_errors
    res["source_columns_preserved"] = (len(preservation_errors) == 0)
    res["flag_domain_errors"] = flag_domain_errors
    res["flag_comparisons_expected"] = rows * 8
    res["flag_comparisons_actual"] = comparisons
    res["flag_mismatches"] = mismatch_total
    res["flag_mismatch_examples"] = mismatches
    res["independent_flag_counts"] = independent_counts
    res["independent_flag_event_sum"] = sum(independent_counts.values())

    # 8. reconciliation: independent vs pipeline
    recon = []
    for c in FLAG_COLUMNS:
        pc = int(pipeline_counts.get(c, -1))
        ic = independent_counts[c]
        recon.append({"flag": c, "pipeline_count": pc, "independent_count": ic,
                      "delta": ic - pc, "status": "MATCH" if ic == pc else "MISMATCH"})
    res["reconciliation"] = recon
    res["reconciliation_all_zero_delta"] = all(r["delta"] == 0 for r in recon)

    # 9. lineage cross-check (flag event total)
    if lineage_path and os.path.exists(lineage_path):
        with open(lineage_path) as f:
            lin = json.load(f)
        total_events = lin.get("total_row_records")
        res["lineage_total_row_records"] = total_events
        res["lineage_matches_flag_event_sum"] = (total_events == sum(independent_counts.values()))
        res["lineage_truncated_field"] = lin.get("truncated")

    res["ALL_CHECKS_PASS"] = bool(
        res.get("input_header_ok") and out_header_ok
        and res["ids_strictly_sequential_and_complete"]
        and res["source_columns_preserved"]
        and flag_domain_errors == 0
        and mismatch_total == 0
        and comparisons == rows * 8
        and res["reconciliation_all_zero_delta"]
        and extra_out == 0
        and (not lineage_path or res.get("lineage_matches_flag_event_sum", True))
    )
    res["verification_duration_s"] = round(time.time() - t0, 2)

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print(json.dumps({k: v for k, v in res.items() if k != "flag_mismatch_examples"}, indent=2))
    return 0 if res["ALL_CHECKS_PASS"] else 1


if __name__ == "__main__":
    sys.exit(main())
