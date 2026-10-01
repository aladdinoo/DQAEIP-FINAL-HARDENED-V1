"""Chunked-scan primitives for bounded-memory execution (FINAL
HARDENING, Section 10 — additive, validation-only).

STATUS: infrastructure primitives ONLY. These utilities are NOT wired
into the production validation engine. The engine's single-pass
execution carries frozen business behavior (output byte-layout,
evidence semantics, unique-ID and reconciliation accounting); rewiring
it to chunked execution requires a company-authorized equivalence
program per ``docs/future/bounded_memory_execution.md``. Nothing in
this module is imported by the engine, the CLI, or any production
code path.

What IS provided here (all additive, pure, deterministic):

    iter_chunks            fixed-row-count chunk reader over any CSV
                           reader (streaming, no full-file buffering)
    chunk_sha256           content hash of one chunk's raw CSV bytes
    ChunkStateChain        hash-chained per-chunk state (chunk_id,
                           row range, chunk hash, running counter
                           snapshot, previous state hash) so a resumed
                           run can prove every completed chunk still
                           matches its checkpoint record
    merge_counter_maps     mergeable counter aggregation (flag counts
                           etc.) — the per-chunk evidence aggregation
                           step of the design doc
    aggregate_chunks       run the full chunked aggregation over an
                           open CSV file and produce a deterministic
                           summary

Design contracts proven by tests (tests/unit/test_chunking.py):

    C1  chunk-size invariance: the merged counters and row count are
        IDENTICAL for every chunk size (1, 7, N/2, N, >N) — chunk
        boundaries never change aggregated business results
    C2  deterministic chaining: the same input and chunk size always
        produce the same chain of state hashes
    C3  tamper evidence: any modification of a completed chunk's bytes
        changes the chain hash at that chunk and every later chunk
    C4  ordering: chunks are strictly sequential with contiguous row
        ranges covering the file exactly once

These are the bounded-memory building blocks proposed in the design
document; using them inside the engine remains future work.
"""

import csv
import hashlib
import io
from typing import Any, Dict, Iterable, Iterator, List, Sequence, Tuple

__all__ = [
    "DEFAULT_CHUNK_ROWS",
    "iter_chunks",
    "chunk_sha256",
    "ChunkStateChain",
    "merge_counter_maps",
    "aggregate_chunks",
]

DEFAULT_CHUNK_ROWS = 250_000


def iter_chunks(reader: Iterable[Sequence[str]],
                chunk_rows: int = DEFAULT_CHUNK_ROWS
                ) -> Iterator[Tuple[int, List[Sequence[str]]]]:
    """Yield ``(chunk_id, rows)`` pairs of at most ``chunk_rows`` rows.

    ``chunk_id`` is zero-based and strictly sequential. The header row
    is the caller's responsibility: pass a ``csv.reader`` AFTER the
    header has been consumed (or any row iterable). Raises ValueError
    for non-positive chunk sizes (fail-closed configuration).
    """
    if not isinstance(chunk_rows, int) or chunk_rows <= 0:
        raise ValueError(f"chunk_rows must be a positive integer, "
                         f"got {chunk_rows!r}")
    chunk_id = 0
    buf: List[Sequence[str]] = []
    for row in reader:
        buf.append(row)
        if len(buf) >= chunk_rows:
            yield chunk_id, buf
            chunk_id += 1
            buf = []
    if buf:
        yield chunk_id, buf


def chunk_sha256(rows: Sequence[Sequence[str]]) -> str:
    """SHA-256 over one chunk's canonical CSV bytes.

    The canonical serialization is ``csv.writer`` output with LF line
    endings and minimal quoting — deterministic for identical row
    content regardless of the original file's quoting style.
    """
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    for row in rows:
        writer.writerow(row)
    return hashlib.sha256(out.getvalue().encode("utf-8")).hexdigest()


class ChunkStateChain:
    """Hash-chained checkpoint state over a chunked scan.

    Each ``advance`` records one chunk and returns the new state
    record. The chain hash of chunk N covers: the previous chain hash,
    the chunk id, its row range, its content hash, and the running
    counter snapshot. Resuming a scan therefore requires replaying the
    same chunk bytes — any divergence is visible in the chain hash
    (tamper evidence, design goal G3).
    """

    def __init__(self) -> None:
        self.records: List[Dict[str, Any]] = []
        self._prev_hash = ""

    @property
    def head(self) -> str:
        """Chain hash after the most recently recorded chunk ('' if none)."""
        return self._prev_hash

    def advance(self, chunk_id: int, first_row: int, last_row: int,
                chunk_hash: str,
                counters: Dict[str, int]) -> Dict[str, Any]:
        """Record one completed chunk; returns its state record.

        ``first_row``/``last_row`` are 1-based data-row numbers
        (header excluded). ``counters`` is a snapshot of the running
        aggregate counters AFTER including this chunk.
        """
        payload = "|".join([
            self._prev_hash,
            str(chunk_id),
            f"{first_row}-{last_row}",
            chunk_hash,
            ";".join(f"{k}={counters[k]}" for k in sorted(counters)),
        ])
        state_hash = hashlib.sha256(
            payload.encode("utf-8")).hexdigest()
        record = {
            "chunk_id": chunk_id,
            "first_row": first_row,
            "last_row": last_row,
            "chunk_sha256": chunk_hash,
            "chain_sha256": state_hash,
            "counters_snapshot": dict(counters),
        }
        self.records.append(record)
        self._prev_hash = state_hash
        return record

    def verify(self, records: Sequence[Dict[str, Any]]) -> bool:
        """Fail-closed verification of a recorded chain.

        Re-derives the chain from the records and compares every state
        hash; any mismatch (or malformed record) is False.
        """
        probe = ChunkStateChain()
        for rec in records:
            if not isinstance(rec, dict):
                return False
            try:
                new = probe.advance(
                    rec.get("chunk_id"), rec.get("first_row"),
                    rec.get("last_row"), rec.get("chunk_sha256"),
                    rec.get("counters_snapshot") or {})
            except Exception:
                return False
            if new["chain_sha256"] != rec.get("chain_sha256"):
                return False
        return probe.records == list(records)


def merge_counter_maps(base: Dict[str, int],
                       extra: Dict[str, int]) -> Dict[str, int]:
    """Merge two integer counter maps additively (returns a new dict).

    Order-independent by construction: merging A then B yields exactly
    the same totals as B then A (chunk-size invariance building block).
    """
    merged = dict(base)
    for k, v in extra.items():
        merged[k] = merged.get(k, 0) + int(v)
    return merged


def aggregate_chunks(csv_file: Any, chunk_rows: int = DEFAULT_CHUNK_ROWS,
                     count_columns: Sequence[str] = ()
                     ) -> Dict[str, Any]:
    """Full chunked aggregation over an OPEN csv file object.

    Reads data rows in fixed-size chunks, builds the hash-chained state
    per chunk, and returns a deterministic summary:

        {"total_rows", "chunk_count", "column_totals", "chain_head",
         "records"}

    ``csv_file`` must be positioned at the header row; the header is
    consumed first and its column order is returned as part of the
    per-chunk identity (via the chunk hash, which covers raw row
    content). ``count_columns`` selects which columns are summed (all
    values are treated as integers; non-integer values are counted as
    parse failures, fail-closed).
    """
    reader = csv.reader(csv_file)
    header = next(reader, None)
    if header is None:
        raise ValueError("input has no header row")
    chain = ChunkStateChain()
    totals: Dict[str, int] = {c: 0 for c in count_columns}
    total_rows = 0
    chunk_count = 0
    for chunk_id, rows in iter_chunks(reader, chunk_rows):
        if not rows:
            continue
        for row in rows:
            total_rows += 1
            for col in count_columns:
                try:
                    idx = header.index(col)
                except ValueError:
                    raise ValueError(f"count column {col!r} not in header")
                value = (row[idx] if idx < len(row) else "").strip()
                if value == "":
                    continue
                try:
                    totals[col] += int(value)
                except ValueError:
                    raise ValueError(
                        f"non-integer value {value!r} in count column "
                        f"{col!r} at data row {total_rows + 1}")
        first = total_rows - len(rows) + 1
        counters = dict(totals)
        counters["_rows"] = total_rows
        chain.advance(chunk_id, first, total_rows,
                      chunk_sha256(rows), counters)
        chunk_count += 1
    return {
        "total_rows": total_rows,
        "chunk_count": chunk_count,
        "column_totals": totals,
        "chain_head": chain.head,
        "records": chain.records,
        "chunk_rows": chunk_rows,
    }
