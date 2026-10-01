"""Rule Impact Analysis (DQAVP hardening, Section 7).

A controlled differential-analysis capability that answers:

    "What will change if this rule changes?"

For a CURRENT rule (or whole registry) versus a PROPOSED rule (or
registry), both are executed over the SAME dataset and the decision
diff is computed:

- rows evaluated
- unchanged decisions
- changed decisions
- old flag count / new flag count
- additions (0 -> 1) and removals (1 -> 0)
- changed rows (bounded sample with row numbers and old/new decisions)
- per-rule breakdown when a whole registry is compared

Safety contract:
- READ-ONLY with respect to the dataset (source preservation).
- Proposals are NEVER activated: this module registers nothing, mutates
  nothing, and its results carry an explicit ``proposal_activated:
  false`` marker. Activation of any proposed rule remains a separate,
  explicit, governed decision outside this module.
- Fail closed: unknown rule ids, non-callable proposals, or unreadable
  datasets raise rather than returning a partial comparison.
"""

import csv
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from data_quality_platform.contracts import SOURCE_COLUMNS

__all__ = ["RuleImpactAnalyzer", "ImpactDiff", "load_rows_csv"]


def load_rows_csv(csv_path: str, limit: Optional[int] = None) -> List[dict]:
    """Load data rows from a CSV (fail closed on missing file/header)."""
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {csv_path}")
        rows = []
        for i, row in enumerate(reader, start=2):
            if limit is not None and len(rows) >= limit:
                break
            rows.append(row)
        if not rows:
            raise ValueError(f"CSV has no data rows: {csv_path}")
        return rows


@dataclass
class ImpactDiff:
    """Decision diff between a current and a proposed rule on one dataset."""

    rule_id: str
    rows_evaluated: int
    unchanged_decisions: int
    changed_decisions: int
    old_flag_count: int
    new_flag_count: int
    additions: int  # 0 -> 1
    removals: int   # 1 -> 0
    changed_row_sample: List[Dict[str, Any]] = field(default_factory=list)
    proposal_activated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rows_evaluated": self.rows_evaluated,
            "unchanged_decisions": self.unchanged_decisions,
            "changed_decisions": self.changed_decisions,
            "old_flag_count": self.old_flag_count,
            "new_flag_count": self.new_flag_count,
            "additions": self.additions,
            "removals": self.removals,
            "changed_row_sample": self.changed_row_sample,
            "proposal_activated": self.proposal_activated,
        }


class RuleImpactAnalyzer:
    """Differential analysis between current and proposed rule decisions."""

    def __init__(self, registry, rows: Iterable[dict]):
        """Args:
            registry: the CURRENT production RuleRegistry.
            rows: dataset rows (list of dicts) to evaluate both sides on.
        """
        self.registry = registry
        self.rows = list(rows)

    def compare_rule(
        self,
        rule_id: str,
        proposed_execute: Callable[[dict], int],
        *,
        sample_size: int = 25,
        identity_fields: tuple = ("id", "zip", "state"),
    ) -> ImpactDiff:
        """Compare the current production rule ``rule_id`` against a
        proposed ``execute(row) -> 0|1`` callable on the SAME dataset.

        Fail closed on unknown rule id or non-callable proposal.
        """
        if rule_id not in self.registry._rules:
            raise KeyError(f"unknown rule_id: {rule_id!r}")
        if not callable(proposed_execute):
            raise TypeError("proposed_execute must be callable(row)->int")
        current = self.registry.get(rule_id)
        old_count = new_count = unchanged = changed = additions = removals = 0
        changed_sample: List[Dict[str, Any]] = []
        for row_num, row in enumerate(self.rows, start=2):
            old = current.execute(row)
            try:
                new = proposed_execute(row)
            except Exception as exc:
                raise RuntimeError(
                    f"proposed rule raised on row {row_num}: {exc}") from exc
            if new not in (0, 1):
                raise ValueError(
                    f"proposed rule returned non-binary flag {new!r} "
                    f"on row {row_num}")
            old_count += old
            new_count += new
            if old == new:
                unchanged += 1
            else:
                changed += 1
                additions += 1 if new == 1 else 0
                removals += 1 if new == 0 else 0
                if len(changed_sample) < sample_size:
                    changed_sample.append({
                        "row_number": row_num,
                        "identity": {f: row.get(f, "") for f in
                                     identity_fields if f in row},
                        "old_decision": old,
                        "new_decision": new,
                    })
        return ImpactDiff(
            rule_id=rule_id,
            rows_evaluated=len(self.rows),
            unchanged_decisions=unchanged,
            changed_decisions=changed,
            old_flag_count=old_count,
            new_flag_count=new_count,
            additions=additions,
            removals=removals,
            changed_row_sample=changed_sample,
            proposal_activated=False,
        )

    def compare_registry(
        self,
        proposed_registry,
        *,
        rule_ids: Optional[List[str]] = None,
    ) -> Dict[str, ImpactDiff]:
        """Compare every (or selected) rule between the current registry
        and a whole proposed registry (e.g., a future rule pack)."""
        ids = rule_ids or [r.rule_id for r in self.registry.get_all_rules()]
        diffs = {}
        for rid in ids:
            if rid not in self.registry._rules:
                raise KeyError(f"unknown current rule_id: {rid!r}")
            proposed_rule = getattr(proposed_registry, "get",
                                    lambda _rid: None)(rid)
            if proposed_rule is None:
                raise KeyError(f"proposed registry lacks rule_id: {rid!r}")
            diffs[rid] = self.compare_rule(
                rid, lambda row, _r=proposed_rule: _r.execute(row))
        return diffs
