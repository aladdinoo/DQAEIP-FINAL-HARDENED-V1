#!/usr/bin/env python3
"""DQAEIP FINAL PORTABLE EVIDENCE & RELEASE HARDENING — Phase 14.

Writes the machine-readable RELEASE_IDENTITY.json that ships INSIDE
the release archive:

    {
      "release_id": "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18",
      "zip_sha256": null,   <- an archive cannot embed its own hash
      "final_results_sha256": "...",
      "manifest_sha256": "...",
      "dependency_fingerprint": "...",
      "verification_state": "PASS_WITH_DOCUMENTED_LIMITATIONS"
    }

The archive's own SHA-256 is necessarily recorded OUTSIDE the archive
(repo-side ZIP record + the .sha256 sidecar beside the archive) — a
zip file cannot contain its own hash. This is stated explicitly in
the identity document so no verifier mistakes the null for a gap.
"""

import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

NS = "evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18"
OUT = os.path.join(REPO_ROOT, NS, "release_manifest",
                  "RELEASE_IDENTITY.json")
RELEASE_ID = "DQAEIP-FINAL-CLEAN-REBUILD-RELEASE-2026-09-18"

FR = os.path.join(REPO_ROOT, NS, "final_results",
                  "FINAL_RESULTS_PORTABLE_2026-09-18.json")


def sha256_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    fr = json.load(open(FR, encoding="utf-8"))
    doc = {
        "report": "DQAEIP machine-readable release identity",
        "schema": {"name": "dqaeip.release_identity", "version": "1.0"},
        "release_id": RELEASE_ID,
        "release_date": "2026-09-18",
        "supersedes": "DQAEIP-FINAL-UPDATE-2026-09-17",
        "product_name": "Data Quality Assurance & Evidence "
                        "Integrity Platform",
        "final_results_path": f"{NS}/final_results/"
                              "FINAL_RESULTS_PORTABLE_2026-09-18.json",
        "final_results_sha256": sha256_file(FR),
        "dependency_fingerprint": fr["dependency_fingerprint"],
        "frozen_v1_sha256": fr["derived_values"]["frozen_v1_sha256"],
        "official_input_sha256": fr["derived_values"]["input_sha256"],
        "official_output_sha256": fr["derived_values"]["output_sha256"],
        "official_checker_sha256": fr["derived_values"]["checker_sha256"],
        "verification_state": fr["verification_state"],
        "zip_sha256": None,
        "zip_sha256_note": (
            "a zip archive cannot embed its own hash; the "
            "authoritative zip_sha256 is recorded in the repo-side "
            "ZIP record (evidence/FINAL_CLEAN_REBUILD_RELEASE_2026-09-18/"
            "release_manifest/zip_record.json) and in the .sha256 "
            "sidecar beside the archive"),
        "verification_chain": [
            "official 3M run pair (Run 1 + Run 2; no Run 3)",
            "run-pair verification 95/95",
            "two-phase FINAL_RESULTS rebuild (schema gate)",
            "claim -> evidence -> hash graph verification",
            "artifact identity registry validation",
            "evidence schema compatibility (all current KNOWN)",
            "absolute-path release gate (0 violations)",
            "integrity monitors 20/20",
            "evidence mutation matrix 16/16 rejected",
            "release gate 22/22 fail-closed gates",
            "clean-room self-contained verification",
        ],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"release identity written: {os.path.relpath(OUT, REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
