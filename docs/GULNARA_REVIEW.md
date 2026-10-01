# Gulnara Review Guide

This document outlines actionable contribution areas for Gulnara to review, improve, and extend the Data Quality Platform.

## 1. Geography Edge Cases

### Current State
The geography mismatch detection uses a static `STATE_ZIP_PREFIXES` mapping based on the first 2-3 digits of ZIP codes.

### Known Limitations
- Some ZIP prefixes overlap between states (e.g., 06 is shared by CT and other New England states)
- ZIP+4 is not used for more precise matching
- Puerto Rico and territories are not covered
- PO Box ZIP codes may not match the state of the mailing address

### Review Tasks
1. Verify `tests/golden/geography_edge_cases.csv` - 20 geography-specific edge cases
2. Add additional edge cases for overlapping ZIP prefixes
3. Review whether 3-digit prefix matching would reduce false positives
4. Consider adding ZIP code validation (checksum digit)

## 2. False-Positive Analysis

### How to Analyze
Run the validation on a real dataset and examine the `evidence/<run_id>/monitoring.json` for flag counts. Compare flagged rows against business knowledge.

### Common False Positive Sources
- **Name cleaning candidates**: Legitimate names from non-English origins may be flagged
- **ZIP/state mismatch**: Users may have billing address (different state) vs mailing address
- **Email syntax**: Some valid international email formats may not pass the regex

### Review Tasks
1. Cross-reference `geography_mismatch_candidate` flags with known valid addresses
2. Review `name_cleaning_candidate` flags against a name diversity database
3. Document accepted false-positive rates per rule

## 3. Review-Only vs Automatic Cleaning

### Current Design
The platform is **detection-only** in V1. The `CleaningGate` requires explicit authorization.

### Decision Framework
| Scenario | Recommended Mode | Rationale |
|----------|-----------------|----------|
| First run on new dataset | Review-only | Establish baseline false-positive rate |
| Known good rules (>99% precision) | Automatic | High confidence rules can auto-clean |
| PII-related flags | Review-only | Risk of data loss |
| Geography rules | Review-only | Business knowledge needed |

### Review Tasks
1. Set `auto_clean: false` in configuration for initial runs
2. Establish a review dashboard for flagged rows
3. Define approval workflows for automatic cleaning

## 4. Airflow Validation

### DAG Structure
The DAG at `airflow/dags/dq_validation_dag.py` has 6 tasks:
1. preflight - validates rules and schema
2. schema_validation - validates source CSV
3. rule_validation - validates rule registry
4. quality_validation - runs full pipeline
5. monitoring - evaluates SLA
6. evidence_finalization - verifies evidence completeness

### Review Tasks
1. Configure the DAG with actual dataset paths
2. Set up alerting (email/Slack) for SLA breaches
3. Add dataset-specific configuration
4. Schedule the DAG for recurring execution

## Files for Review
- `tests/golden/geography_edge_cases.csv` - 20 geography test cases
- `tests/golden/golden_cases.csv` - 50 comprehensive golden test cases
- `configs/quality.yaml` - SLA threshold configuration
- `sql/` - ClickHouse table definitions