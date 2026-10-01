#!/usr/bin/env python3
"""Write dataset metadata + sha files for the 5M dataset (Phase 2/3 closure),
and later a generic finalize for run artifacts. Subcommands:

  metadata   -> 02_dataset/consumer_5m_metadata.json + dataset_sha256.txt
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone

REPO = "/home/z/my-project/Data-Quality-V1-Final-Company-Integrated"
DS = os.path.join(REPO, "data", "generated", "final_5m", "consumer_5m_seed_20260909.csv")
D02 = os.path.join(REPO, "evidence", "final_5m_execution", "02_dataset")

SOURCE_COLUMNS = [
    "id", "email_address", "first_name", "last_name", "address",
    "city", "county_name", "state", "zip", "website_source",
    "phone_number", "gender", "dob", "registration_date", "valid",
    "extra", "email_id", "ethnicity", "ownrent", "domain",
    "main_interest", "sub_interest", "latitude", "longitude", "uploaded",
    "country", "websource_id", "interest_ids", "DNC", "source",
    "first_name_norm", "last_name_norm", "zip_norm",
]


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def metadata():
    gen_terminal = os.path.join(D02, "dataset_generation_terminal.txt")
    integ = os.path.join(D02, "dataset_generation_result.json")
    with open(integ) as f:
        integrity = json.load(f)

    meta = {
        "artifact": "consumer_5m_seed_20260909.csv",
        "role": "authoritative 5M validation dataset (FINAL 5M VALIDATION task)",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "generator_command": "python -m runner.cli generate --rows 5000000 --seed 20260909 "
                             "--output data/generated/final_5m/consumer_5m_seed_20260909.csv",
        "generator_entrypoint": "runner.cli cmd_generate (canonical CLI)",
        "seed": 20260909,
        "seed_note": "new seed for this task; distinct from the 1K CLI seed 20260821 and "
                     "from every historical seed; no reuse of any previous dataset",
        "rows": integrity["row_count"],
        "columns": len(SOURCE_COLUMNS),
        "schema": SOURCE_COLUMNS,
        "file_size_bytes": integrity["file_size_bytes"],
        "sha256": integrity["sha256"],
        "generation_duration_s": 123.904,
        "generation_child_peak_rss_mb": 22.57,
        "memory_measurement_method": "resource.getrusage(RUSAGE_CHILDREN).ru_maxrss (Linux KiB), "
                                     "VmHWM-equivalent process peak RSS",
        "generator_code_hashes": {
            "runner/cli.py": file_sha(os.path.join(REPO, "runner", "cli.py")),
            "data_quality_platform/generation/synthetic.py": file_sha(
                os.path.join(REPO, "data_quality_platform", "generation", "synthetic.py")),
            "data_quality_platform/contracts.py": file_sha(
                os.path.join(REPO, "data_quality_platform", "contracts.py")),
        },
        "input_path_relative": "data/generated/final_5m/consumer_5m_seed_20260909.csv",
        "integrity_checks": {
            "row_count_ok": integrity["row_count_ok"],
            "header_ok": integrity["header_ok"],
            "csv_structure_ok": integrity["csv_structure_ok"],
            "ids_ok": integrity["ids_ok"],
            "all_checks_pass": integrity["ALL_CHECKS_PASS"],
            "independent_verifier": "scripts/five_m/verify_dataset_5m.py "
                                    "(no production imports; streaming; see dataset_integrity.txt)",
        },
        "determinism_note": "generation is a deterministic function of (seed, rows) in the frozen "
                            "SyntheticDataGenerator; regenerate with the recorded command to "
                            "reproduce the identical SHA-256",
    }
    with open(os.path.join(D02, "consumer_5m_metadata.json"), "w") as f:
        json.dump(meta, f, indent=2)

    with open(os.path.join(D02, "dataset_sha256.txt"), "w") as f:
        f.write(f"{integrity['sha256']}  data/generated/final_5m/consumer_5m_seed_20260909.csv\n")
        f.write(f"size_bytes: {integrity['file_size_bytes']}\n")
        f.write("verified_by: independent streaming verifier (scripts/five_m/verify_dataset_5m.py)\n")
    print("metadata + sha256 files written")


if __name__ == "__main__":
    metadata()
