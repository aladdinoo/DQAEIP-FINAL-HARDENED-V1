# False-Positive Review Framework

## Overview

This document describes the methodology for analyzing and reducing false positives in the Data Quality Platform's rule system.

## Per-Rule False-Positive Analysis

### first_name_cleaning_candidate

**Triggers:** Names matching suspicious patterns (test, fake, xxx, admin, etc.), non-alpha characters, repeated characters.

**Potential False Positives:**
- Legitimate names that happen to match patterns (e.g., "Admin" as a surname)
- Names with diacritical marks or hyphens from non-English origins
- Short names that happen to be all the same character (unlikely but possible)

**Mitigation:**
- Maintain an allowlist of known legitimate names
- Add locale-aware name validation
- Use a name database (e.g., census data) for validation

### last_name_cleaning_candidate

Same considerations as first_name_cleaning_candidate.

### name_cleaning_candidate

**Triggers:** first_name == last_name, or both are single characters.

**Potential False Positives:**
- Cultural naming conventions where first and last names can be the same
- Mononymous individuals (single name)

**Mitigation:**
- Add a minimum name length check before flagging same-name
- Allow mononymous records to be excluded via configuration

### email_blank

**Triggers:** Empty or whitespace-only email.

**False Positive Rate:** Effectively zero - blank is blank.

### email_syntax_failure

**Triggers:** Email does not match `^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$`

**Potential False Positives:**
- Emails with comments or unusual but valid characters
- Internationalized domain names (IDN)
- Emails with + addressing (subaddressing) - these ARE supported

**Mitigation:**
- Consider RFC 5322 full compliance for critical use cases
- Add an "accepted domains" allowlist

### proposed_email_export_eligible

**Triggers:** Non-blank, syntactically valid email.

**False Positive Rate:** Effectively zero - this is a positive flag.

### zip_state_assessable

**Triggers:** Both ZIP and state are present and state is in our reference.

**False Positive Rate:** Zero - this is an informational flag.

### geography_mismatch_candidate

**Triggers:** ZIP prefix does not match any known prefix for the state.

**Potential False Positives:**
- ZIP prefix overlaps between nearby states
- Users with PO boxes in different states
- Recently assigned ZIP codes
- Military addresses (APO/FPO)

**Mitigation:**
- Expand STATE_ZIP_PREFIXES with more precise 3-digit prefixes
- Add APO/FPO handling
- Allow configurable tolerance

## Review Workflow

1. Run validation on production sample
2. Export flagged rows to review file
3. For each rule, manually classify flags as:
   - TP (True Positive) - genuine quality issue
   - FP (False Positive) - valid data incorrectly flagged
   - Unknown - requires business judgment
4. Calculate precision = TP / (TP + FP) per rule
5. Rules with precision > 99% can be considered for auto-cleaning
6. Rules with precision < 95% should be refined

## Tracking

| Rule | Total Flags | TP | FP | Precision | Action |
|------|------------|----|----|-----------|--------|
| | | | | | |

Fill this table after each production run to track improvement over time.