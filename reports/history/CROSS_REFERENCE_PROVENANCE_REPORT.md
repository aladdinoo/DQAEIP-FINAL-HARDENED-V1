# CROSS-REFERENCE SNAPSHOT PROVENANCE — PHASE 0 REPORT & FINAL CLASSIFICATION

- Task: Establish a reproducible, deterministic, READ-ONLY provenance chain from
  `tips_data.tblZipStCtyIB` to a pinned repository snapshot
  `data/cross_reference_snapshot.csv`.
- Repository: `github.com/aladdinoo/data-quality-platformV2`
- HEAD inspected: `4065714c3c810c503020d60a8f726a485a5e09ac` (single commit, single branch `main`)
- Remote check: `git fetch origin` + `git ls-remote` → upstream HEAD is identical; no other branches, no stashes.
- Date: 2026-09-05

---

## PART 1 — PHASE 0 INSPECTION REPORT (A–J)

### A. Current snapshot format

**DOES NOT EXIST.** There is no `data/` directory anywhere in the repository.
`data/cross_reference_snapshot.csv` is absent at HEAD `4065714` and absent from
every branch, stash, and the upstream remote. A filesystem-wide search of the
workspace found zero files matching `*cross_reference*` or `*canonical_zip*`.

The only matches for the strings `cross_reference` / `canonical_zip` in the
entire workspace are artifacts of the previous audit session (untracked):
`docs/CANONICAL_GEOGRAPHY_DESIGN.md`, `tests/golden/test_dl_canonical_geography.py`,
and the external harness `scripts/repro_prefix_map.py`.

### B. Current snapshot size

N/A — file does not exist.

### C. Is it currently test-only?

N/A — neither the file nor any documentation of it as a "TEST FIXTURE" exists
in the tracked tree.

### D. Every code path that consumes it

**NONE.** Grep over the full tracked tree for
`cross_reference_snapshot|cross-reference snapshot|CrossReferenceSnapshot`
returns **zero** hits. No Python module, test, SQL file, config, or doc
references such a snapshot. The only geography reference actually consumed by
code is the hard-coded in-memory dict:

- `data_quality_platform/contracts.py:47–67` — `STATE_ZIP_PREFIXES`
  (51 entries, 2-digit prefixes, consumed by
  `ZipStateAssessable.execute` at `v1_rules.py:255–260` and
  `GeographyMismatchCandidate.execute` at `v1_rules.py:284–296`).

A second, *designed but never populated and never read* reference exists only
as DDL: `sql/003_create_reference_tables.sql:1–6` creates ClickHouse table
`state_zip_reference(state, zip_prefix)`. No code path reads it.

### E. Current canonical reference provenance pattern

**No file-based canonical reference or provenance pattern exists.** There is no
`data/canonical_zip_reference.csv`, no `evidence/rebuild/` directory, and no
loader for any reference CSV. Existing provenance conventions that DO exist:

- `data_quality_platform/evidence/manifests.py` — `compute_file_sha256()`
  (hash-after-close), `fsync_path()`, `ManifestWriter.write_success_manifest()`
  producing `manifest.json` with `file_hashes` and a `manifest_hash` computed
  over the written manifest file; `write_failure_manifest()` for failures.
- Command-output evidence convention: `evidence/final_verification/commands/*.txt`
  (e.g., `pytest_output.txt`, `runtime_tests_output.txt`).
- Config gates in `PlatformConfig` (`config/settings.py`): `generate_manifests`,
  `compute_sha256`, `fsync_evidence` — all default true.

### F. Current evidence/manifest pattern

As above: JSON manifests under `evidence/<run>/manifest.json` with per-file
SHA-256 and a manifest self-hash (hash of the file as written, stored in the
returned dict, not recursively inside the file — no recursive self-hash
problem). `.gitignore` ignores `data/generated/*.csv` but nothing that would
hide `data/cross_reference_snapshot.csv` — the file genuinely does not exist
rather than being ignored.

### G. Existing ClickHouse connection mechanism

Repository conventions:

- `docker-compose.yml` — ClickHouse 24.3, ports 8123/9000, DB `data_quality`,
  user `default`, empty password, init from `./sql` (creates `source`,
  `flag_preview`, `state_zip_reference`, `quality_rules`, audit, lineage).
- `data_quality_platform/config/settings.py:40–45` — `clickhouse_host=localhost`,
  `port=8123`, `user=default`, `password=""`, `database=data_quality`;
  env overrides `DQ_CLICKHOUSE_HOST/PORT/USER/PASSWORD` (lines 64–74).
- `data_quality_platform/storage/__init__.py` — "V1 uses file-based storage;
  ClickHouse integration is designed but runtime-verified only with Docker."
- `tests/runtime/test_runtime.py:103–127` — runtime ClickHouse test pings
  `http://localhost:8123/ping` and **skips** when unavailable; executes the
  `sql/*.sql` files over the HTTP interface.

**In this execution environment: NO ClickHouse connection exists.**

- `curl http://localhost:8123/ping` → connection refused (exit 7); nothing
  listening on 8123/9000.
- `docker` binary not installed → the compose stack cannot even be started.
- No `clickhouse-client` binary; no Python ClickHouse driver installed.
- No `DQ_CLICKHOUSE_*` environment variables set; `/home/z/my-project/.env`
  contains only `DATABASE_URL=file:/home/z/my-project/db/custom.db` (SQLite).
- The database `tips_data` is referenced **nowhere** in the repository; the
  table name `tblZipStCtyIB` returns **zero** grep hits across the tracked tree.

### H. Exact files that would need to change (if the source were verifiable)

All NEW files; **zero existing files require modification**:

1. `scripts/extract_cross_reference_snapshot.py` — offline, fail-closed,
   read-only extraction tool (proposed spec in Part 2).
2. `data/cross_reference_snapshot.csv` — the pinned snapshot produced by the
   tool (there is currently no schema contract to violate; proposed `zip,state`).
3. `evidence/rebuild/CROSS_REFERENCE_PROVENANCE.md` — provenance report.
4. `evidence/rebuild/commands/cross_reference_extraction.txt` — exact executed
   SQL + command + output evidence (follows `evidence/final_verification/commands/` convention).
5. `evidence/rebuild/manifest.json` — SHA-256 evidence following
   `ManifestWriter` conventions (per-file hashes; no recursive self-hash).
6. Optional: unit tests for the tool's pure-Python normalization/validation
   logic (no ClickHouse required) + a skip-gated integration test mirroring
   `test_runtime.py:103` (skips without a live server).

### I. Exact files that should NOT change

- `data_quality_platform/contracts.py` — semantics untouched; no hard-coded
  acceptance ZIPs (42223, 45275, 99501, 96501, 96910, 96799).
- `data_quality_platform/rules/v1_rules.py`, `rules/registry.py`, `rules/base.py`
- Everything E1 / SP1 / R1 / R2 / R3 related — none of it is touched by this task.
- `sql/*.sql`, `docker-compose.yml` — no ClickHouse schema changes.
- All existing `evidence/**` artifacts.
- `tests/golden/*` fixtures — note: `99501` appears in
  `tests/golden/geography_edge_cases.csv` (GEO011, AK); `42223`, `45275`,
  `96501`, `96910`, `96799` appear nowhere in the tracked tree.

### J. Current git status

```
On branch main  (HEAD 4065714, up to date with origin/main after fresh fetch)
Untracked files (pre-existing from previous session, untouched):
    docs/CANONICAL_GEOGRAPHY_DESIGN.md
    tests/golden/test_dl_canonical_geography.py
No modified tracked files.
```

---

## PART 2 — PROPOSED (NOT EXECUTED) EXTRACTION ARCHITECTURE & EXACT QUERIES

Presented per the task's final safety statement so that execution can proceed
immediately once a live, authorized ClickHouse with `tips_data.tblZipStCtyIB`
is reachable. **None of these queries were executed** — no server exists here.

### Proposed architecture — OPTION B (normalization inside the SELECT)

Single deterministic, fully recorded SELECT; the Python tool then re-validates
every returned row against the same contract (defense in depth) and writes the
CSV. No `any()`, `first()`, `last()`, no aggregation that can collapse
conflicting states, `GROUP BY` guarantees distinctness, `ORDER BY` guarantees
determinism.

### Exact proposed metadata/read queries (Phase 1, SELECT/DESCRIBE/SHOW only)

```
Q1  SHOW DATABASES
Q2  SHOW TABLES FROM tips_data
Q3  DESCRIBE TABLE tips_data.tblZipStCtyIB
Q4  SHOW CREATE TABLE tips_data.tblZipStCtyIB

Q5  SELECT count() FROM tips_data.tblZipStCtyIB

Q6  SELECT count() FROM tips_data.tblZipStCtyIB
    WHERE trimBoth(zip) MATCHES '^[0-9]{5}$'

Q7  SELECT count() FROM tips_data.tblZipStCtyIB
    WHERE upper(trimBoth(St)) MATCHES '^[A-Z]{2}$'

Q8  SELECT count() FROM tips_data.tblZipStCtyIB
    WHERE (trimBoth(zip) MATCHES '^[0-9]{5}$')
      AND (upper(trimBoth(St)) MATCHES '^[A-Z]{2}$')

Q9  SELECT count() FROM (
      SELECT trimBoth(zip) AS zip_key, upper(trimBoth(St)) AS state_key
      FROM tips_data.tblZipStCtyIB
      WHERE (trimBoth(zip) MATCHES '^[0-9]{5}$')
        AND (upper(trimBoth(St)) MATCHES '^[A-Z]{2}$')
      GROUP BY zip_key, state_key )

Q10 SELECT uniqExact(zip_key) FROM (
      SELECT trimBoth(zip) AS zip_key, upper(trimBoth(St)) AS state_key
      FROM tips_data.tblZipStCtyIB
      WHERE (trimBoth(zip) MATCHES '^[0-9]{5}$')
        AND (upper(trimBoth(St)) MATCHES '^[A-Z]{2}$')
      GROUP BY zip_key, state_key )

Q11 SELECT count() FROM (
      SELECT zip_key, uniqExact(state_key) AS n_states
      FROM tips_data.tblZipStCtyIB
      WHERE (trimBoth(zip) MATCHES '^[0-9]{5}$')
        AND (upper(trimBoth(St)) MATCHES '^[A-Z]{2}$')
      GROUP BY zip_key )
    WHERE n_states > 1

Q12 SELECT zip_key, groupArray(state_key) AS states
    FROM tips_data.tblZipStCtyIB
    WHERE (trimBoth(zip) MATCHES '^[0-9]{5}$')
      AND (upper(trimBoth(St)) MATCHES '^[A-Z]{2}$')
    GROUP BY zip_key
    HAVING uniqExact(state_key) > 1
    ORDER BY zip_key ASC
```

Notes on contract equivalence: the task defines
`state_key = upper(trimBoth(St))` valid against `^[A-Za-z]{2}$`; after
`upper()`, the equivalent gate is `^[A-Z]{2}$` (documented equivalence, same
semantics). Q12 exists purely as *evidence* of preserved conflicts — its
output never feeds selection logic.

### Exact proposed extraction SELECT (the one whose text is pinned in evidence)

```
SELECT trimBoth(zip) AS zip_key, upper(trimBoth(St)) AS state_key
FROM tips_data.tblZipStCtyIB
WHERE (trimBoth(zip) MATCHES '^[0-9]{5}$')
  AND (upper(trimBoth(St)) MATCHES '^[A-Z]{2}$')
GROUP BY zip_key, state_key
ORDER BY zip_key ASC, state_key ASC
FORMAT CSV
```

Python-side post-conditions enforced fail-closed by the proposed tool:
regex re-validation of every row (`^[0-9]{5}$` / `^[A-Z]{2}$`), duplicate
(zip,state) detection, strict `(zip_key, state_key)` ascending order
verification, header `zip,state`, LF newlines, no metadata rows inside the
CSV (provenance lives in evidence files), byte-exact SHA-256 computed after
close and independently recomputed.

### Credentials policy

`DQ_CLICKHOUSE_HOST/PORT/USER/PASSWORD` env vars only (existing
`PlatformConfig` mechanism); never stored in source. The tool hard-codes only
the source identifier `tips_data.tblZipStCtyIB` and column names `zip`, `St`,
executes SELECT-only statements, and refuses to run any statement class other
than SELECT/SHOW/DESCRIBE/EXISTS.

---

## PART 3 — PHASE 16 FINAL REPORT

### A. FILES CHANGED

**None.** No file in the repository was created, modified, or deleted by this
task. Working tree is byte-identical to the state found at Phase 0 start
(two pre-existing untracked artifacts from the prior session remain, untouched).

Rationale: implementation never started, per the task's own instruction —
Phase 0 revealed that the provenance chain cannot be demonstrated, and the
task forbids working around blockers or fabricating provenance.

### B. FILES NOT CHANGED — explicit confirmation

- ClickHouse server(s): **no connection was ever established; nothing touched.**
- Production tables / production data: **untouched.**
- E1: **not executed, not modified.**
- SP1: **not modified.**
- R1 / R2 / R3: **not modified.**
- Unrelated production logic (`contracts.py`, `v1_rules.py`, registry, engine,
  runner, evidence, security modules): **untouched.**

### C. CLICKHOUSE OPERATIONS

**ZERO ClickHouse operations were executed** — no query, no metadata call,
not even the ping succeeded (connection refused; no server, no client, no
credentials, no docker). The complete list of ClickHouse-related actions
performed in the host environment:

| Action | Type | Result |
|---|---|---|
| `curl http://localhost:8123/ping` | TCP reachability probe (not SQL) | Connection refused (exit 7) |
| `docker ps` | host command | `docker: command not found` |
| `env` grep / `.env` read | credential discovery | No ClickHouse credentials exist |

**READ-ONLY ONLY: confirmed trivially — zero operations.** Every query that
*would* have been executed is recorded verbatim in Part 2, none of which is a
write statement.

### D. SOURCE PROVENANCE

- database: `tips_data` — **existence NOT verifiable from this environment**
  (no server reachable; name appears nowhere in the repository).
- table: `tblZipStCtyIB` — **existence NOT verifiable**; zero references in
  the tracked tree (code, SQL DDL, docs, tests, evidence).
- columns: `zip`, `St` — **unverifiable** for the same reason.
- source verification: **FAILED — link 1 of the provenance chain cannot be
  demonstrated.** No claim is made about the table's existence, schema, or
  contents.

### E. EXTRACTION CONTRACT

Fully specified (Part 2) but **not executed**:

- normalization: `zip_key = trimBoth(zip)`; `state_key = upper(trimBoth(St))`
- filtering: `zip_key MATCHES '^[0-9]{5}$' AND state_key MATCHES '^[A-Z]{2}$'`
- distinct behavior: `GROUP BY zip_key, state_key` — ALL distinct pairs
  preserved; e.g. `12345→{CA,CA,NV}` yields rows `12345,CA` **and** `12345,NV`
- conflict preservation: pair-based output is inherently multi-state-capable;
  no `any()`/`first()`/`last()`; conflicts additionally evidenced via Q12
- ordering: `ORDER BY zip_key ASC, state_key ASC`, verified byte-level after write

### F. COUNTS

Not obtainable — every count requires the live source (Phase 1 items 6–12).
Recorded as **UNKNOWN**, not zero, not invented: raw rows, valid normalized
rows, distinct ZIP/state pairs, unique ZIPs, multi-state ZIPs.

### G. SNAPSHOT

- path: `data/cross_reference_snapshot.csv` — **does not exist; not created**
  (creating it from anything other than a verified live extraction would be
  fabrication, which the task forbids).
- row count / byte size / SHA-256: N/A.
- ordering / duplicate verification: N/A — no artifact to verify.

### H. PROVENANCE EVIDENCE

Evidence artifacts created by this task: **this report only**
(`CROSS_REFERENCE_PROVENANCE_REPORT.md`, stored outside the repository).
No `evidence/rebuild/*` files were created because no extraction occurred;
creating them would fabricate evidence. The exact formats they *will* follow
(`CROSS_REFERENCE_PROVENANCE.md` SOURCE/EXTRACTION/COUNTS/OUTPUT/EXECUTION/SAFETY
sections; `commands/cross_reference_extraction.txt`; `ManifestWriter`-style
`manifest.json` with per-file SHA-256) are specified in Part 1-H.

### I. TEST RESULTS

Full suite executed (baseline honesty check; no code was changed by this task):

```
collected: 201
passed:     192
failed:     0
skipped:      9
errors:       0
```

Command: `python -m pytest tests/ -q` → `192 passed, 9 skipped in 2.38s`.
Skips are pre-existing by design: 7 skip-gated DL acceptance tests from the
prior session, plus runtime ClickHouse/Airflow environment-gated tests.
No test was weakened, skipped-converted, or expected-value-edited.

### J. GIT STATUS

```
On branch main — HEAD 4065714c3c810c503020d60a8f726a485a5e09ac
Untracked (pre-existing, from previous audit session, untouched):
    docs/CANONICAL_GEOGRAPHY_DESIGN.md
    tests/golden/test_dl_canonical_geography.py
Modified tracked files: none.  Deletions: none.
```

`git diff` / `git diff --stat`: empty. Change set is exactly {} — consistent
with a read-only provenance-inspection outcome.

### K. FINAL CLASSIFICATION

**BLOCKED — CROSS REFERENCE SNAPSHOT PROVENANCE REQUIRED**

Specific missing provenance links (Phase 15 chain), each demonstrated, not
inferred:

1. **BLOCKED — LIVE SOURCE LINK.** `tips_data.tblZipStCtyIB` cannot be shown
   to exist: no ClickHouse server is reachable (localhost:8123 refused), no
   docker binary to start the compose stack, no client binary, no Python
   driver, no credentials in env/config/`.env`. The table name appears in
   zero repository artifacts.
2. **BLOCKED — PINNED SNAPSHOT LINK.** `data/cross_reference_snapshot.csv`
   (with its documented 9 records) does not exist at HEAD `4065714` — there
   is no `data/` directory and no branch/stash/remote contains one. The
   claimed test fixture cannot be preserved (Phase 6/12 have no object), and
   no code path consumes it (Phase 10's consumer question is currently moot).
3. **BLOCKED — PREMISE MISMATCH.** The task describes a "two-reference
   geography model" consuming `cross_reference_snapshot.csv` +
   `canonical_zip_reference.csv`. The actual repository's only geography
   references are (a) the hard-coded `STATE_ZIP_PREFIXES` dict
   (`contracts.py:47–67`) and (b) the designed-but-unpopulated,
   never-read ClickHouse table `state_zip_reference(state, zip_prefix)`
   (`sql/003:1–6`). No file-based reference loader exists.

Per the task's stop conditions #1/#4/#13/#14 and the Phase 15 rule
("If any link cannot be demonstrated: BLOCKED — do not claim PASS"), no
extraction, snapshot creation, evidence fabrication, or workaround was
performed.

### UNBLOCKING REQUIREMENTS (any one path)

1. Provide a reachable, authorized ClickHouse endpoint hosting
   `tips_data.tblZipStCtyIB` (e.g., set `DQ_CLICKHOUSE_HOST/PORT/USER/PASSWORD`
   or start the compose stack with the `tips_data` database and table actually
   present — noting the stock `sql/` init scripts create only `data_quality`
   objects and would NOT create `tips_data.tblZipStCtyIB`).
2. OR provide the current `data/cross_reference_snapshot.csv` (9 records) and
   `data/canonical_zip_reference.csv` in the repository (commit/push or paste),
   so Phase 6 fixture preservation and the premise can be reconciled.
3. OR confirm the authoritative source identity (stop condition #14) if
   `tips_data.tblZipStCtyIB` is not in fact the source.

Upon unblocking, the exact query set in Part 2 executes unchanged, and Phases
2–15 complete against real, recorded, reproducible evidence.
