#!/usr/bin/env python3
"""PHASE 3 — INDEPENDENT dataset forensic verification (5M).

Independently implemented: does NOT import data_quality_platform or runner.
The 33-column schema is hardcoded below (transcribed from the delivered
contract for cross-checking), predicates are self-contained, parsing is
streaming csv module only.

Checks:
  1. header == expected 33 columns in exact order
  2. exactly 5,000,000 data rows
  3. every row parses with exactly 33 fields (CSV structural integrity)
  4. IDs exactly 1..5,000,000 in order, no duplicates, no missing
  5. SHA-256 + byte size of the dataset
Outputs machine-readable JSON to stdout (also written to a file by caller).
"""

import csv
import hashlib
import json
import os
import sys
import time

EXPECTED_COLUMNS = [
    "id", "email_address", "first_name", "last_name", "address",
    "city", "county_name", "state", "zip", "website_source",
    "phone_number", "gender", "dob", "registration_date", "valid",
    "extra", "email_id", "ethnicity", "ownrent", "domain",
    "main_interest", "sub_interest", "latitude", "longitude", "uploaded",
    "country", "websource_id", "interest_ids", "DNC", "source",
    "first_name_norm", "last_name_norm", "zip_norm",
]
EXPECTED_ROWS_DEFAULT = 5_000_000


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    csv_path = sys.argv[1]
    out_json = sys.argv[2]
    expected_rows = int(sys.argv[3]) if len(sys.argv) > 3 else EXPECTED_ROWS_DEFAULT
    t0 = time.time()
    result = {
        "check": "dataset_forensic_verification",
        "dataset_path": csv_path,
        "expected_rows": expected_rows,
        "expected_columns": EXPECTED_COLUMNS,
        "independent_implementation": True,
        "production_imports": False,
    }

    # structural + id verification in ONE streaming pass
    row_count = 0
    ids_ok = True
    structure_errors = []
    first_bad_row = None
    id_errors = []
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        result["header"] = header
        result["header_ok"] = (header == EXPECTED_COLUMNS)
        if header != EXPECTED_COLUMNS:
            result["header_diff"] = {
                "missing": [c for c in EXPECTED_COLUMNS if c not in header],
                "extra": [c for c in header if c not in EXPECTED_COLUMNS],
                "order_matches": header == EXPECTED_COLUMNS,
            }
        expected_id = 1
        for fields in reader:
            row_count += 1
            if len(fields) != 33:
                structure_errors.append({"row": row_count, "fields": len(fields)})
                if len(structure_errors) <= 3:
                    continue
                break
            rid = fields[0]
            if rid != str(expected_id):
                if ids_ok:
                    first_bad_row = {"row": row_count, "got": rid, "expected": str(expected_id)}
                ids_ok = False
                if len(id_errors) < 10:
                    id_errors.append(first_bad_row)
                if row_count < expected_id or not rid.isdigit() or int(rid) != expected_id:
                    # keep scanning to count rows; do not attempt recovery of order
                    pass
            expected_id += 1
            if row_count % 1_000_000 == 0:
                print(f"  scanned {row_count} rows...", flush=True)

    result["row_count"] = row_count
    result["row_count_ok"] = (row_count == expected_rows)
    result["csv_structure_errors"] = structure_errors[:10]
    result["csv_structure_ok"] = (len(structure_errors) == 0)
    result["id_sequence_check"] = {
        "ids_sequential_1_to_N": ids_ok and row_count == expected_rows and expected_id - 1 == expected_rows,
        "first_anomaly": first_bad_row,
        "note": "streamed strict check: each row's id field must equal its 1-based position; "
                "a strict in-order pass with count==5,000,000 and zero anomalies proves "
                "IDs 1..5,000,000 with no duplicates and no missing values",
    }
    result["ids_ok"] = bool(ids_ok and row_count == expected_rows
                            and expected_id - 1 == expected_rows and first_bad_row is None)

    size = os.path.getsize(csv_path)
    result["file_size_bytes"] = size
    result["file_size_mb"] = round(size / 1024 / 1024, 2)
    t1 = time.time()
    digest = sha256_of(csv_path)
    result["sha256"] = digest
    result["sha256_duration_s"] = round(time.time() - t1, 3)
    result["verification_duration_s"] = round(time.time() - t0, 2)
    result["ALL_CHECKS_PASS"] = bool(
        result["header_ok"] and result["row_count_ok"] and result["csv_structure_ok"]
        and result["ids_ok"]
    )

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("expected_columns", "header")}, indent=2))
    return 0 if result["ALL_CHECKS_PASS"] else 1


if __name__ == "__main__":
    sys.exit(main())
