#!/usr/bin/env python3
"""DQAEIP FINAL UPDATE 2026-09-17 — evidence freshness evaluation (§12).

Reads the dependency graph and assigns every derived artifact:

    CURRENT       all dependencies unchanged since generation
    STALE         a dependency hash moved
    NOT_VERIFIED  a dependency (or the artifact itself) is missing
    INVALID       the artifact's own hash changed since generation

Never silently refreshes stale evidence: STALE findings are recorded
and must be resolved by an explicit re-derivation through the two-phase
rebuild (staging -> verify -> promote).
"""

import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from data_quality_platform.assurance.integrity import (  # noqa: E402
    UPDATE_ID, evaluate_freshness, sha256_file)

GRAPH_PATH = os.path.join(
    REPO_ROOT, "evidence", "FINAL_CLEAN_REBUILD_RELEASE_2026-09-18",
    "dependency_graph", "dependency_graph.json")
OUT_PATH = os.path.join(
    REPO_ROOT, "evidence", "FINAL_CLEAN_REBUILD_RELEASE_2026-09-18",
    "freshness", "freshness_report.json")


def main():
    if not os.path.isfile(GRAPH_PATH):
        print("FATAL: dependency graph missing — freshness cannot be "
              "established (NOT_VERIFIED, never PASS)")
        return 3
    graph = json.load(open(GRAPH_PATH, encoding="utf-8"))

    artifacts = {}
    findings = []
    for node in graph.get("nodes", []):
        artifact = node["artifact"]
        deps = node.get("dependencies", [])
        # physical artifacts only (path-like nodes with dependencies)
        if not deps:
            continue
        result = evaluate_freshness(artifact, deps, REPO_ROOT)
        abs_artifact = os.path.join(REPO_ROOT, artifact)
        recorded_self = None
        if os.path.isfile(abs_artifact):
            recorded_self = sha256_file(abs_artifact)
        artifacts[artifact] = {
            "state": result["state"],
            "reasons": result["reasons"],
            "authority_level": node.get("authority_level"),
            "dependency_count": len(deps),
            "self_sha256": recorded_self,
        }
        if result["state"] != "CURRENT":
            findings.extend(result["reasons"])

    states = [v["state"] for v in artifacts.values()]
    overall = ("NOT_VERIFIED" if "NOT_VERIFIED" in states else
               "INVALID" if "INVALID" in states else
               "STALE" if "STALE" in states else "CURRENT")

    doc = {
        "report": "DQAEIP FINAL UPDATE evidence freshness report",
        "update_id": UPDATE_ID,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "graph_fingerprint": graph.get("graph_fingerprint"),
        "artifact_count": len(artifacts),
        "states": {s: states.count(s) for s in
                   ("CURRENT", "STALE", "NOT_VERIFIED", "INVALID")},
        "overall_state": overall,
        "policy": ("stale evidence is never silently refreshed; STALE "
                   "must be resolved by an explicit two-phase "
                   "re-derivation"),
        "findings": findings,
        "artifacts": artifacts,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"FRESHNESS: {overall}")
    for state, count in doc["states"].items():
        if count:
            print(f"  {state}: {count}")
    for f_ in findings[:10]:
        print(f"  - {f_}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
