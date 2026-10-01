#!/usr/bin/env python3
"""Gate-round ledger for DQAEIP-FINAL-HARDENED-RELEASE-2026-09-19.

Honest fixed-point discipline for release-gate rounds (single-commit
release): every release-gate round is ledgered in the release namespace
before its evidence file is replaced by the next round. FAIL rounds are
preserved IN FULL (embedded) so the convergence story is auditable;
PASS rounds are ledgered as summaries (their evidence file persists on
disk and is committed).

Why the ledger lives OUTSIDE the contradiction checker's scan set
(evidence/FINAL_HARDENED_RELEASE_2026-09-19/ is not in the checker's
MD_DOCS/JSON_DOCS/JSON_DOC_GLOBS scope): an embedded FAIL round quotes
the very overclaim strings that were flagged ("100M" match samples).
A ledger that re-triggered the checker would make gate convergence
impossible (self-reference fixed point). The checker's own
SELF_OUTPUT exclusion exists for exactly the same reason.

Modes:
  --purge    ledger the CURRENT evidence/release_gate/
             final_release_gate.json (if present), then DELETE it so
             the next gate round starts without self-referential
             contradiction samples embedded in a stale round file.
  --summary  ledger the current round as a summary only (PASS rounds;
             the on-disk file stays and is committed).

Fail-closed: unreadable/corrupt gate file aborts with exit 1.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE_FILE = REPO_ROOT / "evidence" / "release_gate" / \
    "final_release_gate.json"
LEDGER = REPO_ROOT / "evidence" / "FINAL_HARDENED_RELEASE_2026-09-19" / \
    "release_gate" / "gate_rounds.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_gate() -> dict:
    try:
        return json.loads(GATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"FAIL-CLOSED: cannot read gate file: {exc}")


def next_round(ledger: dict) -> int:
    if not ledger.get("rounds"):
        return 1
    return max(r["round"] for r in ledger["rounds"]) + 1


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--purge"
    if mode not in ("--purge", "--summary"):
        raise SystemExit(f"unknown mode {mode!r}")

    ledger = {"schema": "dqaeip.hardening.gate.rounds/1.0",
              "release": "DQAEIP-FINAL-HARDENED-RELEASE-2026-09-19"}
    if LEDGER.is_file():
        try:
            ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SystemExit(f"FAIL-CLOSED: corrupt ledger: {exc}")

    if not GATE_FILE.is_file():
        print("no live gate file; nothing to ledger")
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(json.dumps(ledger, indent=1) + "\n",
                          encoding="utf-8")
        return 0

    gate = load_gate()
    verdict = gate.get("overall_verdict")
    failing = [{"gate": g["gate"], "status": g["status"],
                "evidence": g.get("evidence")}
               for g in gate.get("gates", []) if g.get("status") != "PASS"]
    statuses = {g["gate"]: g.get("status") for g in gate.get("gates", [])}

    entry = {
        "round": next_round(ledger),
        "ledgered_utc_source": "evidence/release_gate/"
                               "final_release_gate.json",
        "source_sha256": sha256_file(GATE_FILE),
        "generated_utc": gate.get("generated_utc"),
        "overall_verdict": verdict,
        "gate_count": len(statuses),
        "gate_statuses": statuses,
        "failing_gates": failing,
    }

    if verdict == "PASS" and mode == "--summary":
        entry["preservation"] = ("PASS round: summary only; the round's "
                                 "evidence file persists on disk and is "
                                 "committed with the release")
        keep_file = True
    else:
        entry["preservation"] = ("FAIL round: full content embedded "
                                 "here (the working-tree file is "
                                 "superseded by the next round; the "
                                 "single-commit release has no "
                                 "intermediate git history to "
                                 "preserve it in)")
        entry["full_content"] = gate
        keep_file = False

    ledger.setdefault("rounds", []).append(entry)
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(ledger, indent=1) + "\n",
                      encoding="utf-8")
    print(f"round {entry['round']} ledgered "
          f"(verdict={verdict}, failing={len(failing)})")

    if not keep_file:
        GATE_FILE.unlink()
        print("stale gate file purged (next round starts clean)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
