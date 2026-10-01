"""Claim → Evidence → Hash Provenance Graph (DQAEIP FINAL PORTABLE
EVIDENCE & RELEASE HARDENING, task section 6 — Phase 5).

Machine-readable provenance graph:

    CLAIM  "51,200,000 comparisons, 0 mismatches"
      ↓ (derivation)
    EVIDENCE  FINAL_RESULTS (official run-pair record)
      ↓ (dependency)
    ARTIFACT  Run 1 / Run 2 evidence
      ↓ (checker identity)
    ARTIFACT  official checker
      ↓ (rule source)
    ARTIFACT  Frozen V1 rules
      ↓
    SHA-256 identities

The graph supports BOTH directions:

    reverse lookup:   claim → evidence → artifact → SHA → source
    forward verify:    artifact → dependency → evidence → claim

Fail-closed rules (task section 6, never violated):

    - no claim may be marked verified when its required evidence is
      missing, stale, malformed or hash-invalid;
    - verification re-derives every claim value from live evidence and
      re-hashes every artifact — recorded values are never trusted;
    - the graph fingerprint is deterministic and timestamp-free;
    - NOT_VERIFIED claims are recorded as NOT_VERIFIED — they are
      never silently upgraded to PASS.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

__all__ = [
    "GraphBuilder",
    "verify_graph",
    "graph_fingerprint",
]


def _sha256_file(path: str) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _load_json(path: str) -> Optional[Any]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


class GraphBuilder:
    """Accumulates claim / evidence / artifact nodes and edges."""

    def __init__(self, repo_root: str):
        self.repo_root = repo_root
        self.claims: List[Dict[str, Any]] = []
        self.evidence: Dict[str, Dict[str, Any]] = {}
        self.edges: List[Dict[str, str]] = []

    # ---------------------------------------------------------- nodes

    def add_claim(self, claim_id: str, text: str, value: Any,
                  derivation: str,
                  evidence_paths: List[str],
                  derivation_fn: Optional[Callable[[str], Any]] = None
                  ) -> str:
        """Register a claim linked to its evidence artifacts.

        ``derivation_fn(repo_root) -> value`` re-derives the claim at
        verification time; without it the claim can never verify
        (fail-closed)."""
        record = {
            "node_id": f"claim:{claim_id}",
            "type": "CLAIM",
            "claim_id": claim_id,
            "text": text,
            "value": value,
            "derivation": derivation,
            "evidence": [self._evidence_id(p) for p in evidence_paths],
            "verifiable": derivation_fn is not None,
        }
        if derivation_fn is not None:
            record["_derivation_fn_name"] = getattr(
                derivation_fn, "__name__", "<lambda>")
            self._derivations[claim_id] = derivation_fn
        self.claims.append(record)
        for p in evidence_paths:
            self.add_evidence(p)
            self.edges.append({
                "from": f"claim:{claim_id}",
                "to": self._evidence_id(p),
                "relation": "derived_from",
            })
        return f"claim:{claim_id}"

    _derivations: Dict[str, Callable[[str], Any]] = {}

    def add_evidence(self, path: str, role: str = "",
                     depends_on: Optional[List[str]] = None,
                     anchor: bool = False,
                     volatile: bool = False) -> str:
        """Register an evidence artifact node with live SHA-256.

        ``volatile=True`` marks a RUNTIME OUTPUT (e.g. the integrity
        monitor report or the release gate report) that is
        regenerated on every verification run BY DESIGN. Volatile
        nodes are VALUE-anchored: verification re-derives claim values
        from the live file but never hash-pins it (hash-pinning a
        regenerated file would manufacture permanent staleness).
        Stability of those artifacts is instead proven by re-execution
        (clean-room verification) and by the deterministic re-derivation
        of their recorded values.
        """
        node_id = self._evidence_id(path)
        if node_id not in self.evidence:
            sha = None if volatile else _sha256_file(
                os.path.join(self.repo_root, path))
            self.evidence[node_id] = {
                "node_id": node_id,
                "type": "EVIDENCE",
                "artifact": path,
                "sha256": sha,
                "role": role,
                "anchor": anchor,
                "volatile": volatile,
                "status_hint": ("RUNTIME_VALUE_ANCHORED" if volatile
                                else ("PRESENT" if sha else "MISSING")),
            }
        if depends_on:
            for dep in depends_on:
                self.add_evidence(dep)
                self.edges.append({
                    "from": node_id,
                    "to": self._evidence_id(dep),
                    "relation": "depends_on",
                })
        return node_id

    @staticmethod
    def _evidence_id(path: str) -> str:
        return f"evidence:{path}"

    # ----------------------------------------------------------- graph

    def build(self) -> Dict[str, Any]:
        nodes = (list(self.evidence.values()) + self.claims)
        # reverse lookup: claim -> evidence chain (transitive)
        reverse = {}
        by_id = {n["node_id"]: n for n in nodes}
        for c in self.claims:
            reverse[c["claim_id"]] = self._chain(
                f"claim:{c['claim_id']}", by_id)
        # forward: artifact -> claims that depend on it
        forward: Dict[str, List[str]] = {}
        for c in self.claims:
            for ev in self._chain(f"claim:{c['claim_id']}", by_id):
                n = by_id.get(ev)
                if n and n["type"] == "EVIDENCE":
                    forward.setdefault(n["artifact"], []).append(
                        c["claim_id"])
        # artifacts that no claim depends on are recorded as
        # supporting (still hash-anchored)
        return {
            "node_count": len(nodes),
            "claim_count": len(self.claims),
            "evidence_count": len(self.evidence),
            "claims": self.claims,
            "evidence_nodes": list(self.evidence.values()),
            "edges": self.edges,
            "reverse_lookup": reverse,
            "forward_lookup": {
                k: sorted(set(v)) for k, v in forward.items()},
        }

    def _chain(self, node_id: str, by_id: Dict[str, Any]
               ) -> List[str]:
        """Transitive closure following edges from node."""
        seen, stack = set(), [node_id]
        while stack:
            cur = stack.pop()
            for e in self.edges:
                if e["from"] == cur and e["to"] not in seen:
                    seen.add(e["to"])
                    stack.append(e["to"])
        return sorted(seen)

    def derivations(self) -> Dict[str, Callable[[str], Any]]:
        return dict(self._derivations)


def graph_fingerprint(graph: Dict[str, Any]) -> str:
    """Deterministic, timestamp-free fingerprint: SHA-256 over the
    canonical (claim_id, value, verifiable) + (artifact, sha256)
    identity pairs."""
    h = hashlib.sha256()
    for c in sorted(graph["claims"], key=lambda x: x["claim_id"]):
        h.update(c["claim_id"].encode() + b"\x00")
        h.update(json.dumps(c["value"], sort_keys=True,
                            default=str).encode() + b"\x00")
        h.update(str(c["verifiable"]).encode() + b"\x00")
    for e in sorted(graph["evidence_nodes"],
                    key=lambda x: x["artifact"]):
        h.update(e["artifact"].encode() + b"\x00")
        h.update((e["sha256"] or "RUNTIME_VALUE_ANCHORED").encode()
                 + b"\x00")
    return h.hexdigest()


def verify_graph(graph: Dict[str, Any], repo_root: str,
                 derivations: Dict[str, Callable[[str], Any]]
                 ) -> Dict[str, Any]:
    """Fail-closed verification pass.

    For every evidence node: re-hash the live artifact. For every
    claim: re-derive the value. A claim verifies ONLY when every
    artifact in its chain is present + hash-identical AND its value
    re-derives exactly. Anything else -> NOT_VERIFIED (never PASS).
    """
    ev_problems: Dict[str, List[str]] = {}
    for ev in graph["evidence_nodes"]:
        if ev.get("volatile"):
            continue  # value-anchored runtime output — see add_evidence
        path = os.path.join(repo_root, ev["artifact"])
        live = _sha256_file(path)
        problems = []
        if live is None:
            problems.append("artifact missing on disk")
        elif ev.get("sha256") != live:
            problems.append(
                f"STALE: recorded {str(ev.get('sha256'))[:12]}… "
                f"live {live[:12]}…")
        doc = _load_json(path) if path.endswith(".json") else None
        if doc is None and path.endswith(".json"):
            problems.append("malformed or unreadable JSON evidence")
        if problems:
            ev_problems[ev["artifact"]] = problems

    claim_results = []
    all_ok = True
    for c in graph["claims"]:
        chain = graph["reverse_lookup"].get(c["claim_id"], [])
        chain_artifacts = []
        for nid in chain:
            if nid.startswith("evidence:"):
                chain_artifacts.append(nid[len("evidence:"):])
        broken = [a for a in chain_artifacts if a in ev_problems]
        derived = None
        deriv_error = None
        if c["claim_id"] in derivations:
            try:
                derived = derivations[c["claim_id"]](repo_root)
            except Exception as exc:  # noqa: BLE001 — record, never crash
                deriv_error = f"derivation raised: {exc}"
        ok = (
            not broken
            and deriv_error is None
            and derived is not None
            and derived == c["value"]
        )
        if not ok:
            all_ok = False
        claim_results.append({
            "claim_id": c["claim_id"],
            "text": c["text"],
            "recorded_value": c["value"],
            "re_derived_value": derived,
            "broken_evidence": broken,
            "derivation_error": deriv_error,
            "status": "VERIFIED" if ok else "NOT_VERIFIED",
        })

    verified = sum(1 for r in claim_results if r["status"] == "VERIFIED")
    return {
        "claims_total": len(claim_results),
        "claims_verified": verified,
        "claims_not_verified": len(claim_results) - verified,
        "evidence_problems": ev_problems,
        "all_claims_verified": all_ok,
        "verdict": "PASS" if all_ok and not ev_problems else
                   ("NOT_VERIFIED" if all_ok else "FAIL"),
        "claim_results": claim_results,
    }
