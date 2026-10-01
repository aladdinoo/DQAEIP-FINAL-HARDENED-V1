#!/usr/bin/env python3
"""PHASE 8 — Geography aggregation over the actual 3M run output.

One streaming pass over the run1 output CSV (independent parse — stdlib csv
only; it reads the FLAG values already produced and cross-checked by the
independent verifier). Produces per-state: rows, assessable count, mismatch
count, mismatch rate; plus total mismatch/assessable and the V1-known
limitation checks (DC duplicate prefix entry present in the map, ambiguous
prefixes count, missing territory/military codes count).
"""

import csv
import json
import sys
from collections import defaultdict

# Transcribed constants (same as verifier) for the limitation accounting
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
ALL_USPS_FIRST_DIGITS = {str(i) for i in range(10)}
covered_prefixes = {p for plist in STATE_ZIP_PREFIXES.values() for p in plist}
covered_first_digits = {p[0] for p in covered_prefixes}
missing_first_digits = sorted(ALL_USPS_FIRST_DIGITS - covered_first_digits)
# V1-documented absent codes (territories/military) — statically known set
ABSENT_CODES = ["AS", "GU", "MP", "PR", "VI", "AA", "AE", "AP"]
# ambiguous prefixes: a 2-digit prefix assigned to more than one state
from collections import Counter
owner = defaultdict(set)
for st, plist in STATE_ZIP_PREFIXES.items():
    for p in plist:
        owner[p].add(st)
ambiguous = sorted(p for p, sts in owner.items() if len(sts) > 1)

def main():
    out_csv = sys.argv[1]
    res_path = sys.argv[2]
    per_state = defaultdict(lambda: {"rows": 0, "assessable": 0, "mismatch": 0})
    total_rows = 0
    total_mismatch = 0
    total_assessable = 0
    with open(out_csv, "r", newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        header = next(r)
        idx_state = header.index("state")
        idx_assess = header.index("zip_state_assessable")
        idx_mismatch = header.index("geography_mismatch_candidate")
        for fields in r:
            total_rows += 1
            st = fields[idx_state]
            a = fields[idx_assess]
            m = fields[idx_mismatch]
            d = per_state[st]
            d["rows"] += 1
            if a == "1":
                d["assessable"] += 1
                total_assessable += 1
            if m == "1":
                d["mismatch"] += 1
                total_mismatch += 1
    states = []
    for st in sorted(per_state):
        d = per_state[st]
        states.append({
            "state": st,
            "rows": d["rows"],
            "assessable": d["assessable"],
            "mismatch_candidates": d["mismatch"],
            "mismatch_rate_pct": round(d["mismatch"] / d["rows"] * 100, 3) if d["rows"] else 0.0,
        })
    result = {
        "source_output_csv": out_csv,
        "total_rows": total_rows,
        "total_assessable": total_assessable,
        "total_mismatch_candidates": total_mismatch,
        "assessable_rate_pct": round(total_assessable / total_rows * 100, 4) if total_rows else 0,
        "mismatch_rate_pct": round(total_mismatch / total_rows * 100, 4) if total_rows else 0,
        "per_state": states,
        "v1_map_limitation_accounting": {
            "map_entries": len(STATE_ZIP_PREFIXES),
            "dc_duplicate_prefix_entry_present": STATE_ZIP_PREFIXES.get("DC") == ["20", "20"],
            "ambiguous_prefixes_prefix_to_multiple_states": ambiguous,
            "ambiguous_prefix_owners": {p: sorted(owner[p]) for p in ambiguous},
            "absent_codes_territories_military": ABSENT_CODES,
            "uncovered_first_digits_1x_7x": missing_first_digits,
        },
    }
    with open(res_path, "w") as f:
        json.dump(result, f, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != "per_state"}, indent=2))
    print(f"states covered: {len(states)}")
    worst = sorted(states, key=lambda s: -s["mismatch_candidates"])[:5]
    print("top-5 mismatch states:", json.dumps(worst))

if __name__ == "__main__":
    main()
