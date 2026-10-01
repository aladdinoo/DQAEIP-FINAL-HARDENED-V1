CREATE TABLE IF NOT EXISTS state_zip_reference (
    state String,
    zip_prefix String,
    PRIMARY KEY state
) ENGINE = ReplacingMergeTree()
ORDER BY (state, zip_prefix);

CREATE TABLE IF NOT EXISTS quality_rules (
    rule_id String,
    rule_version String,
    rule_hash String,
    sql_template String,
    description String,
    created_at DateTime DEFAULT now(),
    PRIMARY KEY rule_id
) ENGINE = ReplacingMergeTree()
ORDER BY rule_id;
