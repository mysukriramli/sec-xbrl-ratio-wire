CREATE SEQUENCE IF NOT EXISTS seq_commit_id START 1;

CREATE TABLE IF NOT EXISTS financial_ratios (
    ticker VARCHAR PRIMARY KEY,
    cik VARCHAR,
    company_name VARCHAR,
    fiscal_year INTEGER,
    form VARCHAR,
    gross_margin DOUBLE,
    operating_margin DOUBLE,
    net_margin DOUBLE,
    current_ratio DOUBLE,
    debt_to_equity DOUBLE,
    raw_metrics_json VARCHAR,
    content_hash VARCHAR,
    last_updated_utc VARCHAR
);

CREATE TABLE IF NOT EXISTS ledger (
    commit_id BIGINT PRIMARY KEY,
    timestamp_utc VARCHAR,
    operation VARCHAR,
    ticker VARCHAR,
    fiscal_year INTEGER,
    net_margin DOUBLE,
    detail VARCHAR
);
