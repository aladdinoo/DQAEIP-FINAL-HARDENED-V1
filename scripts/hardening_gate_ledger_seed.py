#!/usr/bin/env python3
"""One-time seed of the gate-round ledger with the prior session's
rounds 1-2 (reconstructed summary for round 1 — its full content was
superseded and not preserved; round 2 is ledgered in full by
hardening_gate_round_ledger.py --purge)."""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER = REPO_ROOT / "evidence" / "FINAL_HARDENED_RELEASE_2026-09-19" / \
    "release_gate" / "gate_rounds.json"

ledger = {
    "schema": "dqaeip.hardening.gate.rounds/1.0",
    "release": "DQAEIP-FINAL-HARDENED-RELEASE-2026-09-19",
    "rounds": [
        {
            "round": 1,
            "source": "prior session (2026-09-19 morning) first release-"
                      "gate run of the hardened release",
            "preservation": ("RECONSTRUCTED SUMMARY: full content was "
                             "superseded by the round-2 re-run and not "
                             "preserved; failure set reconstructed from "
                             "the session record"),
            "generated_utc": None,
            "overall_verdict": "FAIL",
            "failing_gates_reconstructed": [
                {"gate": "repository_integrity",
                 "cause": "uncommitted hardening delta (pre-commit "
                          "state, expected until the release commit)"},
                {"gate": "consistency_matrix",
                 "cause": "contradiction check flagged README "
                          "scalability_overclaim false positives "
                          "(out-of-scope list mention of 100M/800M)"},
                {"gate": "claim_provenance",
                 "cause": "test-suite claim mismatch after the "
                          "limitation-registry duplication regressed "
                          "the suite"},
                {"gate": "evidence_validation",
                 "cause": "regression engine evidence roots missing "
                          "(fixed by scripts/hardening_fixed_point_"
                          "fixer.py step 1)"},
            ],
        },
    ],
}

LEDGER.parent.mkdir(parents=True, exist_ok=True)
LEDGER.write_text(json.dumps(ledger, indent=1) + "\n", encoding="utf-8")
print(f"ledger seeded with round 1 ({len(ledger['rounds'])} rounds)")
sys.exit(0)
