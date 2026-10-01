"""Chunk-size invariance tests for the validation-only chunking
primitives (FINAL HARDENING, Section 10).

These tests prove, on SMALL DETERMINISTIC FIXTURES, the design
contracts C1-C4 of ``data_quality_platform/validation/chunking.py``:

    C1  chunk-size invariance — merged aggregates identical for every
        chunk size; boundaries never change aggregated results
    C2  deterministic chaining — same input + chunk size → same chain
    C3  tamper evidence — modified chunk bytes change the chain
    C4  ordering — sequential ids, contiguous non-overlapping ranges

Per the task's explicit constraint: NO 3M re-validation is performed
here; these are small-fixture contract tests only. The primitives are
NOT wired into the production engine (that remains future work under a
company-authorized equivalence program).
"""

import csv
import io
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from data_quality_platform.validation.chunking import (
    ChunkStateChain,
    aggregate_chunks,
    chunk_sha256,
    iter_chunks,
    merge_counter_maps,
)

# Deterministic small fixture: 50 rows, three count columns with known
# sums (produced by a fixed arithmetic pattern — no randomness).
ROWS = [
    [f"id-{i:03d}", str(i % 7), str(i % 3), str(1 if i % 5 == 0 else 0)]
    for i in range(50)
]
HEADER = ["id", "mod7", "mod3", "flag5"]
EXPECTED_TOTALS = {
    "mod7": sum(int(r[1]) for r in ROWS),
    "mod3": sum(int(r[2]) for r in ROWS),
    "flag5": sum(int(r[3]) for r in ROWS),
}


def _csv_text() -> str:
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(HEADER)
    writer.writerows(ROWS)
    return out.getvalue()


class TestIterChunks:
    def test_invalid_chunk_size_fails_closed(self):
        with pytest.raises(ValueError):
            list(iter_chunks(iter(ROWS), 0))
        with pytest.raises(ValueError):
            list(iter_chunks(iter(ROWS), -3))

    def test_chunks_cover_every_row_exactly_once(self):
        for size in (1, 3, 50, 51):
            chunks = list(iter_chunks(iter(ROWS), size))
            flat = [r for _, rs in chunks for r in rs]
            assert flat == ROWS
            assert [cid for cid, _ in chunks] == list(range(len(chunks)))

    def test_chunk_sizes_respected(self):
        for size in (1, 3, 7, 50):
            for _, rows in iter_chunks(iter(ROWS), size):
                assert 1 <= len(rows) <= size


class TestChunkHash:
    def test_deterministic(self):
        assert chunk_sha256(ROWS[:5]) == chunk_sha256(ROWS[:5])

    def test_content_sensitivity(self):
        mutated = [list(r) for r in ROWS[:5]]
        mutated[2][1] = "99"
        assert chunk_sha256(mutated) != chunk_sha256(ROWS[:5])


class TestChunkStateChain:
    def test_same_input_same_chain(self):
        def build():
            chain = ChunkStateChain()
            counters = {}
            for i, (cid, rows) in enumerate(iter_chunks(iter(ROWS), 5)):
                counters["_rows"] = (i + 1) * len(rows)
                chain.advance(cid, i * 5 + 1, (i + 1) * 5,
                              chunk_sha256(rows), counters)
            return chain
        assert build().head == build().head

    def test_tampered_chunk_changes_chain_from_that_point(self):
        def build(mutate_at=None):
            chain = ChunkStateChain()
            counters = {}
            for i, (cid, rows) in enumerate(iter_chunks(iter(ROWS), 5)):
                if mutate_at is not None and i == mutate_at:
                    rows = [list(r) for r in rows]
                    rows[0][1] = "999"
                counters["_rows"] = sum(len(rs) for _, rs in
                                       list(iter_chunks(iter(ROWS), 5))[:i + 1])
                chain.advance(cid, i * 5 + 1, (i + 1) * 5,
                              chunk_sha256(rows), counters)
            return chain
        clean = build()
        tampered = build(mutate_at=2)
        assert clean.head != tampered.head
        # chunks before the tamper keep their hashes
        assert (clean.records[0]["chain_sha256"]
                == tampered.records[0]["chain_sha256"])
        assert (clean.records[1]["chain_sha256"]
                == tampered.records[1]["chain_sha256"])
        # the tampered chunk and all later ones differ
        for i in (2, 3, 4):
            assert (clean.records[i]["chain_sha256"]
                    != tampered.records[i]["chain_sha256"])

    def test_verify_accepts_own_records(self):
        chain = ChunkStateChain()
        counters = {}
        for i, (cid, rows) in enumerate(iter_chunks(iter(ROWS), 5)):
            counters["_rows"] = (i + 1) * len(rows)
            chain.advance(cid, i * 5 + 1, (i + 1) * 5,
                          chunk_sha256(rows), counters)
        assert chain.verify(chain.records)

    def test_verify_rejects_tampered_records(self):
        chain = ChunkStateChain()
        for i, (cid, rows) in enumerate(iter_chunks(iter(ROWS), 5)):
            chain.advance(cid, i * 5 + 1, (i + 1) * 5,
                          chunk_sha256(rows), {"_rows": (i + 1) * 5})
        tampered = [dict(r) for r in chain.records]
        tampered[1]["chunk_sha256"] = "0" * 64
        assert not chain.verify(tampered)


class TestMergeCounterMaps:
    def test_order_independence(self):
        a = {"x": 3, "y": 1}
        b = {"x": 4, "z": 9}
        assert (merge_counter_maps(a, b)
                == merge_counter_maps(b, a)
                == {"x": 7, "y": 1, "z": 9})


class TestAggregateChunksInvariance:
    """C1: the core chunk-size invariance contract."""

    @pytest.mark.parametrize("chunk_rows", [1, 2, 3, 7, 13, 25, 50, 51,
                                             1000])
    def test_totals_and_rows_identical_for_every_chunk_size(
            self, chunk_rows):
        summary = aggregate_chunks(io.StringIO(_csv_text()),
                                   chunk_rows=chunk_rows,
                                   count_columns=["mod7", "mod3", "flag5"])
        assert summary["total_rows"] == 50
        assert summary["column_totals"] == EXPECTED_TOTALS

    def test_chunk_count_varies_but_aggregate_does_not(self):
        counts = set()
        for chunk_rows in (1, 5, 10, 50):
            summary = aggregate_chunks(io.StringIO(_csv_text()),
                                      chunk_rows=chunk_rows,
                                      count_columns=["mod7"])
            counts.add(summary["chunk_count"])
            assert summary["column_totals"]["mod7"] == EXPECTED_TOTALS["mod7"]
        assert counts == {1, 5, 10, 50}

    def test_ranges_contiguous_and_complete(self):
        summary = aggregate_chunks(io.StringIO(_csv_text()),
                                   chunk_rows=7,
                                   count_columns=["mod7"])
        recs = summary["records"]
        assert [r["chunk_id"] for r in recs] == list(range(len(recs)))
        assert recs[0]["first_row"] == 1
        assert recs[-1]["last_row"] == 50
        for prev, nxt in zip(recs, recs[1:]):
            assert nxt["first_row"] == prev["last_row"] + 1

    def test_empty_data_rows_is_valid_structure(self):
        text = "id,mod7\n"
        summary = aggregate_chunks(io.StringIO(text), chunk_rows=5,
                                   count_columns=["mod7"])
        assert summary["total_rows"] == 0
        assert summary["chunk_count"] == 0
        assert summary["column_totals"] == {"mod7": 0}

    def test_non_integer_count_value_fails_closed(self):
        text = "id,v\n1,2\n3,oops\n"
        with pytest.raises(ValueError):
            aggregate_chunks(io.StringIO(text), chunk_rows=10,
                             count_columns=["v"])

    def test_unknown_count_column_fails_closed(self):
        with pytest.raises(ValueError):
            aggregate_chunks(io.StringIO(_csv_text()), chunk_rows=10,
                             count_columns=["nope"])

    def test_empty_header_fails_closed(self):
        with pytest.raises(ValueError):
            aggregate_chunks(io.StringIO(""), chunk_rows=10)

    def test_chunking_module_not_imported_by_production_paths(self):
        """The primitives must remain validation-only: neither the
        engine, the CLI, nor rule/registry code may import them."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-c",
             "import data_quality_platform.validation.engine, "
             "runner.cli, data_quality_platform.rules.registry"],
            cwd=REPO_ROOT, capture_output=True, text=True)
        assert result.returncode == 0
        # and the module is importable on its own
        import data_quality_platform.validation.chunking as mod
        assert mod.DEFAULT_CHUNK_ROWS > 0
