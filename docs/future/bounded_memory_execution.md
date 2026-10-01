# Bounded-Memory Execution — Design Proposal (PARTIAL: primitives implemented, engine integration NOT implemented)

**Status**: DESIGN + VALIDATION-ONLY PRIMITIVES — engine integration remains future work
**Scope**: DQAVP enterprise hardening, Section 21; FINAL HARDENING Section 10
**Decision rule applied**: the existing execution architecture carries
business behavior (single-pass ordering, unique-ID checks, evidence
byte-layout, byte-identical output guarantee). Implementing
checkpoint/resume inside it **without a company-authorized equivalence
program** would risk business behavior, therefore it is NOT implemented
in this hardening release. This document is the safe proposal.

**What exists now (FINAL HARDENING, additive)**: the pure building
blocks proposed by this document are implemented and tested in
`data_quality_platform/validation/chunking.py` — the fixed-row-count
chunk reader (`iter_chunks`), the canonical chunk content hash
(`chunk_sha256`), the hash-chained checkpoint state
(`ChunkStateChain`, tamper-evident by construction), and the mergeable
counter aggregation (`merge_counter_maps` / `aggregate_chunks`).
Chunk-size invariance, chain determinism, tamper evidence, and ordering
are proven by contract tests in `tests/unit/test_chunking.py` on small
deterministic fixtures (per the task's explicit constraint, NO 3M
re-validation was run for this). These primitives are NOT wired into
the production engine, the CLI, or any production code path — the
engine's frozen single-pass execution is unchanged. Full
bounded-memory execution (streaming output assembly, resumable engine
runs, evidence adaptation) remains future work under the equivalence
program below.

## 1. Measured memory characteristics (facts, not assumptions)

Source: `evidence/dqvp_performance/performance_results.json` (1K → 1M
measured through the production CLI) and the 3M two-run validation
(peak RSS ≈ 2.2 GiB for 3,000,000 rows).

The current engine is **O(N) in-process memory in row count — it is
NOT O(1) and does not claim to be**. Three accumulation points exist
(`data_quality_platform/validation/engine.py`):

1. `id_set` — the set of seen row identifiers grows with N (duplicate
   detection across the whole file).
2. `LineageRecorder.row_records` — one `RowLineageRecord` per
   (row × rule) is accumulated in memory for the entire run
   (persistence is capped at 1000 records, but accumulation is not).
3. Output assembly / evidence counters and per-run state proportional
   to distinct values encountered.

A 5M-row execution previously exceeded the available memory on the
validation host at 98.9% completion (recorded in
`evidence/final_5m_execution/`); that limit is environmental, not a
code failure.

## 2. Design goals

- G1 Bounded peak memory: peak RSS must not grow linearly with N.
- G2 Byte-identical outputs: for identical input, chunked execution
  must produce the same output CSV bytes and the same evidence
  semantics as single-pass execution.
- G3 Fail-closed on incomplete state: a resumed run must prove that
  every completed chunk's chunk_hash still matches its checkpoint
  record, or refuse to continue.
- G4 No business-rule change: V1 rule evaluation per row is already
  row-local; chunking must not alter any decision or decision order.

## 3. Proposed architecture

### 3.1 Chunked input scan

- Read the CSV in fixed row-count chunks (configurable, e.g.
  `chunk_rows: 250_000`) using the existing streaming reader.
- Each chunk gets `chunk_id` (sequential), `chunk_row_range`,
  `chunk_input_sha256` (hash of the chunk's raw CSV bytes), and a
  `chunk_state_hash` covering: chunk_id, row range, input hash,
  running flag-count snapshot, and previous chunk's state hash
  (hash-chained).

### 3.2 Checkpoint / resume state

A checkpoint file per run:

```json
{
  "run_id": "...",
  "input_sha256": "<full-file hash>",
  "schema_sha256": "...",
  "rule_registry_hash": "...",
  "config_hash": "...",
  "completed_chunks": [
    {"chunk_id": 0, "rows": 250000, "chunk_input_sha256": "...",
     "chunk_state_hash": "...", "output_chunk_sha256": "..."}
  ],
  "resume_from": 2,
  "status": "INTERRUPTED|COMPLETE"
}
```

- `resume_from` = first incomplete chunk id.
- On resume: re-verify `input_sha256`, `schema_sha256`,
  `rule_registry_hash`, `config_hash`; re-hash every completed
  chunk's bytes in the partial output; any mismatch → hard failure
  (NON_DETERMINISM / EVIDENCE_ERROR class), never silent restart.

### 3.3 Bounded accumulation strategies

| Accumulator | Bounded replacement | Trade-off |
|---|---|---|
| `id_set` | external on-disk hash set (sorted spill + merge) or a disk-backed set keyed by identifier hash | exact duplicate detection preserved; slower (I/O-bound) |
| `row_records` lineage | ring buffer of the first K records + per-chunk lineage files capped identically to today's 1000-record policy; `total_row_records` maintained as a counter | persisted lineage semantics unchanged (first-N cap is the existing contract); per-chunk files replace the single in-memory accumulation |
| per-run counters | already O(1) or O(distinct-values); aggregate from chunk summaries at finalize | no change |

A Bloom filter for `id_set` is explicitly REJECTED for production use:
it trades exactness for memory, and duplicate detection is a
business-relevant verdict. A false-positive duplicate would silently
alter decisions — unacceptable under the frozen contract.

### 3.4 Evidence adaptation (additive)

- Per-chunk evidence manifests with the existing schema, plus a
  run-level aggregate manifest chaining chunk hashes.
- The tamper-evident evidence root covers the aggregate manifest and
  each chunk record, so removing/reordering chunks invalidates the
  root.
- Existing single-run evidence artifacts remain the canonical format;
  chunked mode adds, never replaces.

## 4. Equivalence program required before implementation

1. Chunked mode must reproduce byte-identical output CSVs at 1K/10K/
   100K/1M/3M scales vs single-pass mode (deterministic replay gate).
2. Flag counts, monitoring score, and audit event ORDER must match
   exactly (audit order is currently run-global).
3. Golden corpus and full regression suite green in both modes.
4. Failure injection: interrupted-at-chunk-k resume must equal an
   uninterrupted run for every tested k.
5. Company review sign-off on the evidence-format addition (per the
   frozen-evidence boundary).

## 5. Explicitly out of scope

- Any change to the V1 rule engine's row-local evaluation.
- Any change to the 33-column input contract or 41-column output
  contract.
- Parallel/multi-process execution (ordering risks).
- Approximate data structures that can alter verdicts.
