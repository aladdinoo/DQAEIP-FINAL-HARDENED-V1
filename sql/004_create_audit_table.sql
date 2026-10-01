CREATE TABLE IF NOT EXISTS audit_log (
    event_id UUID DEFAULT generateUUIDv4(),
    event_type String,
    run_id String,
    timestamp DateTime DEFAULT now(),
    details String DEFAULT '',
    user_id String DEFAULT ''
) ENGINE = MergeTree()
ORDER BY (run_id, timestamp);
