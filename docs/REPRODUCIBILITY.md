# REPRODUCIBILITY — TERMINAL GUIDE (FINAL 5M VALIDATION)
All commands below are the ACTUAL commands executed in this pass (2026-09-09),
in order. Every command's full captured output lives in the cited evidence
file. Working directory: the repository root.

## 0. Environment probe

COMMAND
    python --version && python -m pytest --version && free -m && df -h .
PURPOSE
    Pin the toolchain and resource envelope before any execution.
EXPECTED RESULT
    Python 3.12.x, pytest 9.x, ~4 GB RAM (no swap), >3 GB free disk.
ACTUAL RESULT
    Python 3.12.14; pytest as captured; MemTotal 4041 MB / Swap 0;
    9.9 GB disk. Evidence: `evidence/final_5m_execution/00_baseline/environment.txt`,
    `00_baseline/git_state.txt`.

## 1. Dataset generation (5,000,000 rows — authoritative dataset)

COMMAND
    python -m runner.cli generate --rows 5000000 --seed 20260909 \
        --output data/generated/final_5m/consumer_5m_seed_20260909.csv
PURPOSE
    Produce the authoritative exactly-5,000,000-row synthetic dataset with the
    new recorded seed via the canonical CLI (frozen generator).
EXPECTED RESULT
    stdout `Generated 5000000 rows -> …`, exit 0; streaming generator keeps
    RSS < ~50 MB; file ≈ 1.35 GB.
ACTUAL RESULT
    `Generated 5000000 rows -> data/generated/final_5m/consumer_5m_seed_20260909.csv`,
    exit 0, 123.904 s, child peak RSS 22.57 MB.
    Evidence: `02_dataset/dataset_generation_terminal.txt`.

## 2. Dataset forensic verification (independent)

COMMAND
    python scripts/five_m/verify_dataset_5m.py \
        data/generated/final_5m/consumer_5m_seed_20260909.csv \
        evidence/final_5m_execution/02_dataset/dataset_generation_result.json
PURPOSE
    Independently verify (no production imports): header == 33 contract
    columns in order; exactly 5,000,000 rows; IDs 1..5,000,000 strict
    (proves no duplicates / none missing); CSV structural integrity;
    SHA-256 + size.
EXPECTED RESULT
    `ALL_CHECKS_PASS: true`, sha256 44e41bb8cfe1c0d2fbafbff5e91bb40b100f8331ef26f946532b84c57409fb9d.
ACTUAL RESULT
    ALL_CHECKS_PASS true; 1,351,673,659 bytes; 16.9 s.
    Evidence: `02_dataset/dataset_integrity.txt`, `dataset_generation_result.json`,
    `dataset_sha256.txt`, `consumer_5m_metadata.json`.

## 3. 5M pipeline execution attempt (real CLI — honest failure)

COMMAND
    python -m runner.cli validate \
        --csv data/generated/final_5m/consumer_5m_seed_20260909.csv \
        --output data/generated/final_5m/consumer_5m_seed_20260909_out_run1.csv \
        --run-id run_5m_r1 \
        --evidence-dir evidence/final_5m_execution/03_run1/pipeline_evidence
PURPOSE
    Execute the real production validation path on the 5M dataset.
EXPECTED RESULT
    Either success (3,000,000-class memory envelope permitting) or an honest
    failure record; the pre-registered linear memory model projected
    ~3,594 MB peak vs ~3,576 MB available — an OOM kill was the known risk.
ACTUAL RESULT
    FAILED — kernel OOM killer (SIGKILL, exit -9) at 185.307 s, row
    4,943,922/5,000,000 (98.9%); dmesg captured live:
    `Out of memory: Killed process 3565 (python) total-vm:3678772kB, anon-rss:3592016kB`.
    Evidence: `03_run1/terminal_output.txt`, `03_run1/oom_kernel_log.txt`,
    `03_run1/EXECUTION_BLOCKED_SUMMARY.md`, `03_run1/{runtime,memory,hashes}.txt`.
    On a machine with ≥ ~4.6 GB free RAM this command is expected to complete
    (no code change needed).

## 4. 3M dataset (largest safe scale — same seed lineage)

COMMAND
    python -m runner.cli generate --rows 3000000 --seed 20260909 \
        --output data/generated/final_3m/consumer_3m_seed_20260909.csv
PURPOSE
    Produce the flagship dual-run dataset at the largest scale satisfying the
    pre-registered safety rule (projected peak RSS 2,162 MB ≤ 70% of RAM).
EXPECTED RESULT
    `Generated 3000000 rows -> …`, exit 0.
ACTUAL RESULT
    exit 0, 74.559 s, peak RSS 22.33 MB.
    Evidence: `11_largest_safe_execution_3m/dataset_generation_terminal.txt`,
    `dataset_verification.json` (ALL_CHECKS_PASS, sha256 9be5438e…),
    `dataset_prefix_property.txt` (byte-prefix of the 5M dataset — determinism proof).

## 5. Flagship Run 1 (3M)

COMMAND
    python -m runner.cli validate \
        --csv data/generated/final_3m/consumer_3m_seed_20260909.csv \
        --output data/generated/final_3m/consumer_3m_seed_20260909_out_run1.csv \
        --run-id run_3m_r1 \
        --evidence-dir evidence/final_5m_execution/11_largest_safe_execution_3m/run1
PURPOSE
    First full pipeline execution of the flagship protocol.
EXPECTED RESULT
    `Validation PASSED: 3000000 rows in, 3000000 rows out`, exit 0,
    8 flag-count lines, peak RSS ≈ 2.1–2.2 GB.
ACTUAL RESULT
    Exactly that: exit 0, 138.472 s, peak RSS 2,192.27 MB,
    flag-event sum 6,767,852, reconciliation passed.
    Evidence: `11_…/run1/terminal_output.txt`, `result.json`, `runtime.txt`,
    `memory.txt`, `hashes.txt`, `manifest.json`, `lineage.json`.

## 6. Independent verification (Run 1 — no production imports)

COMMAND
    python scripts/five_m/independent_verifier.py \
        data/generated/final_3m/consumer_3m_seed_20260909.csv \
        data/generated/final_3m/consumer_3m_seed_20260909_out_run1.csv \
        /tmp/pipeline_counts_r1.json \
        evidence/final_5m_execution/04_independent_verification/verification_result_run1.json \
        evidence/final_5m_execution/11_largest_safe_execution_3m/run1/lineage.json
PURPOSE
    Recompute every flag value with independently implemented predicates and
    reconcile against the pipeline's counts (24,000,000 comparisons).
EXPECTED RESULT
    `ALL_CHECKS_PASS: true`, mismatches 0, all 8 deltas 0.
ACTUAL RESULT
    ALL_CHECKS_PASS true — 24,000,000 comparisons, 0 mismatches, deltas 0,
    lineage cross-check 6,767,852 == flag-event sum.
    Evidence: `04_independent_verification/verifier_run1_terminal.txt`,
    `verification_result_run1.json`, `independent_verifier.py`, `command.txt`.

## 7. Flagship Run 2 (3M — same frozen input, no regeneration)

COMMAND
    python -m runner.cli validate \
        --csv data/generated/final_3m/consumer_3m_seed_20260909.csv \
        --output data/generated/final_3m/consumer_3m_seed_20260909_out_run2.csv \
        --run-id run_3m_r2 \
        --evidence-dir evidence/final_5m_execution/11_largest_safe_execution_3m/run2
PURPOSE
    Second deterministic execution for the byte-comparison proof.
EXPECTED RESULT
    Identical behavior to Run 1; exit 0.
ACTUAL RESULT
    exit 0, 140.466 s, peak RSS 2,195.82 MB, identical flag counts.
    Evidence: `11_…/run2/` (same file set as Run 1).

## 8. Independent verification (Run 2)

COMMAND
    python scripts/five_m/independent_verifier.py \
        data/generated/final_3m/consumer_3m_seed_20260909.csv \
        data/generated/final_3m/consumer_3m_seed_20260909_out_run2.csv \
        /tmp/pipeline_counts_r1.json \
        evidence/final_5m_execution/04_independent_verification/verification_result_run2.json \
        evidence/final_5m_execution/11_largest_safe_execution_3m/run2/lineage.json
EXPECTED RESULT / ACTUAL RESULT
    ALL_CHECKS_PASS true — 24,000,000 comparisons, 0 mismatches.
    Evidence: `04_independent_verification/verifier_run2_terminal.txt`.

## 9. Byte comparison (determinism proof)

COMMAND
    cmp data/generated/final_3m/consumer_3m_seed_20260909_out_run1.csv \
        data/generated/final_3m/consumer_3m_seed_20260909_out_run2.csv
    sha256sum data/generated/final_3m/consumer_3m_seed_20260909_out_run*.csv
PURPOSE
    Prove the two executions produced byte-identical outputs.
EXPECTED RESULT
    cmp silent (exit 0); identical SHA-256 on both files.
ACTUAL RESULT
    cmp exit 0; both `22110e49d0276eeed1153fe16ddf00a2a87c49a379ece7363a84cfdca2cb1ef9`.
    Evidence: `11_…/byte_comparison/comparison.txt`.

## 10. Performance ladder (1K / 10K / 100K / 1M) + tracemalloc continuity

COMMAND
    python scripts/five_m/phase7_bench.py        # official CLI ladder + captures
    python scripts/benchmark.py                  # repo's tracemalloc benchmark (1K/10K/100K)
PURPOSE
    Measure duration / throughput / peak RSS with labeled methods; refresh the
    repo's object-level metric for continuity.
EXPECTED RESULT
    Throughput stabilizing ~21–22K rows/s at scale; RSS ~linear;
    tracemalloc 100K ≈ 68.65 MB (matches committed history).
ACTUAL RESULT
    5,343.8 → 22,365.8 rps (1K→100K), 21,778.5 rps @1M; peak RSS 22.43 → 735.71 MB;
    tracemalloc 100K = 68.65 MB (0.209/1.471/14.941 s).
    Evidence: `06_performance/bench_ladder.json`, `bench_*_terminal.txt`,
    `benchmark_tracemalloc_20260909.json`, `PERFORMANCE_REPORT.md`.

## 11. Test suite (fresh, with skip attribution)

COMMAND
    python -m pytest -q -rs
    python -m pytest --collect-only -q
PURPOSE
    Full suite health + every skip's written reason.
EXPECTED RESULT
    331 collected; 322 passed / 9 skipped / 0 failed / 0 errors.
ACTUAL RESULT
    331 collected; 322 passed / 9 skipped / 0 failed / 0 errors in 4.63 s;
    skips: 7 DL company-gated + 1 ClickHouse + 1 Airflow.
    Evidence: `12_test_suite/pytest_full_rs.txt`.

## 12. Boundary / consistency probes

COMMAND
    python scripts/fresh_execution_probe.py          # registry, isolation, security sweep
    python scripts/five_m/phase9_sp1.py              # SP1 six-property activation boundary
PURPOSE
    Machine-verify SP1 isolation and probe invariants.
EXPECTED RESULT
    registry = 8 V1 rules; SP1 not registered; 0 security/mutation hits;
    all six SP1 properties negative.
ACTUAL RESULT
    Exactly that (overall PASS). Evidence:
    `12_test_suite/consolidation_probe.txt`,
    `08_activation_boundary/sp1_activation_check.json`,
    `08_activation_boundary/SP1_NEGATIVE_ACTIVATION_PROOF.md`.

## 13. Archive verification (after packaging)

COMMAND
    sha256sum -c download/Data-Quality-Validation-Platform-5M-Revalidated-2026-09-09-v2.zip.sha256
    unzip -q <archive> -d /tmp/unpack_check && cd /tmp/unpack_check && python -m pytest -q
PURPOSE
    Prove the shipped archive matches its recorded hash and that a fresh
    unpack passes the suite.
EXPECTED RESULT
    Sidecar check: OK. Suite inside unpacked copy: 322 passed, 9 skipped,
    0 failed, 0 errors.
ACTUAL RESULT
    - v2 package (2026-09-09 documentation consolidation): sidecar OK;
      structural + documentation-currency unpack verification recorded in
      `13_archive/unpack_verification_v2.txt`. The test suite was deliberately
      NOT re-run during consolidation (outside the consolidation task's
      scope); its verified 2026-09-09 result stands
      (`12_test_suite/pytest_full_rs.txt`).
    - v1-named task-time package (preserved): full unpack including an
      in-copy suite re-run — 322 passed / 9 skipped — recorded in
      `13_archive/unpack_verification.txt`.
    - Manifest verification (regenerated during consolidation):
      `13_archive/manifest_verification_v2.txt`.
