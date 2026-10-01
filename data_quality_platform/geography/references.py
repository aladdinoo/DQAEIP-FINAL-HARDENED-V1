"""Two-reference provider interface for the SP1 successor geography contract.

CONTRACT (company document "Geography rule - canonical definition and
acceptance cases", SHA-256 0cf6eb93..., prepared 2026-09-01):

    The contract explicitly defines TWO references.

    Each reference:
    - is filtered to a five-digit ZIP
    - is filtered to a two-letter state
    - is grouped by ZIP

    Canonical reference:  resolves the canonical state.
    Cross reference:      must agree with the canonical state or have no row.

    If a ZIP resolves to different states between the references:
        conflict -> not assessable.

PROVENANCE STATUS
-----------------
The PHYSICAL reference datasets (canonical reference and cross reference
derived from tips_data.tblZipStCtyIB) are NOT available in this
environment: no reachable authorized ClickHouse endpoint, no
company-committed snapshot, no approved extract. Per the no-fabrication
rule, no canonical reference data is reconstructed, bundled, or claimed
here.

What IS provided:

    - TwoReferenceProvider: the injectable provider interface a future
      authorized production source must implement.
    - InMemoryTwoReferenceProvider: a CONTROLLED-FIXTURE provider for
      pure-semantics tests and design work ONLY. Its contents in tests
      are traceable to authoritative company acceptance cases; it is
      NOT a canonical production source and MUST NOT be used to claim
      canonical production validation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Tuple

from data_quality_platform.geography.canonical import (
    compute_zip5,
    normalize_state,
)

_ZIP5_RE = re.compile(r"^[0-9]{5}$")
_TWO_LETTER_RE = re.compile(r"^[A-Za-z]{2}$")

CANONICAL_SOURCE_TABLE = "tips_data.tblZipStCtyIB"


class ReferenceUnavailableError(RuntimeError):
    """Raised when an authorized physical canonical reference is required
    but not available. This error must never be swallowed into a
    fallback that fabricates reference data."""


class TwoReferenceProvider:
    """Injectable provider interface (contract: two-reference model).

    Implementations return the DISTINCT normalized (upper-cased,
    two-letter) states recorded for one zip5 in each reference. A
    production implementation must be backed by an authorized canonical
    source with documented provenance (source table, extraction date,
    row counts, SHA-256) - never by prefix maps, fixtures, or memory.
    """

    def canonical_states(self, zip5: str) -> Tuple[str, ...]:
        raise NotImplementedError

    def cross_states(self, zip5: str) -> Tuple[str, ...]:
        raise NotImplementedError


def _filter_reference_rows(
    rows: Iterable[Mapping[str, Any]],
) -> Dict[str, Tuple[str, ...]]:
    """Filter reference rows per the contract and group by ZIP.

    Filtering: keep rows whose ZIP (trimmed) matches ^[0-9]{5}$ and
    whose state (trimmed, upper-cased) matches ^[A-Za-z]{2}$.
    Grouping: zip5 -> ordered distinct states.
    """
    grouped: Dict[str, list] = {}
    for row in rows:
        zip5 = compute_zip5(row.get("zip"))
        if not _ZIP5_RE.match(zip5):
            continue
        state = normalize_state(row.get("state"))
        if not _TWO_LETTER_RE.match(state):
            continue
        bucket = grouped.setdefault(zip5, [])
        if state not in bucket:
            bucket.append(state)
    return {zip5: tuple(states) for zip5, states in grouped.items()}


@dataclass(frozen=True)
class InMemoryTwoReferenceProvider(TwoReferenceProvider):
    """CONTROLLED-FIXTURE two-reference provider.

    Accepted inputs are raw reference-like row mappings (``zip`` and
    ``state`` keys); the contract's filtering (five-digit ZIP, two-letter
    state) is applied internally so tests exercise the documented filter
    semantics rather than pre-digested lookups.

    SCOPE GUARD: instances of this class are controlled fixtures for
    pure-semantics verification. They are not derived from, and must
    never be presented as, the company's canonical production reference.
    """

    canonical_rows: Tuple[Mapping[str, Any], ...]
    cross_rows: Tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "_canonical_index", _filter_reference_rows(self.canonical_rows)
        )
        object.__setattr__(
            self, "_cross_index", _filter_reference_rows(self.cross_rows)
        )

    def canonical_states(self, zip5: str) -> Tuple[str, ...]:
        return self._canonical_index.get(zip5, ())

    def cross_states(self, zip5: str) -> Tuple[str, ...]:
        return self._cross_index.get(zip5, ())
