CREATE TABLE IF NOT EXISTS lineage_record (
    run_id String,
    source String,
    database String,
    table_name String,
    rule_id String,
    rule_version String,
    row_count UInt64,
    schema_hash String,
    ddl_hash String,
    sql_hash String,
    output_identity String,
    recorded_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (run_id, recorded_at);

CREATE TABLE IF NOT EXISTS row_lineage (
    run_id String,
    row_number UInt64,
    rule_id String,
    rule_version String,
    flag_value UInt8,
    row_hash String,
    recorded_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (run_id, rule_id, row_number);
