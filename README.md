# 📊 SEC-XBRL Ratio Wire

An autonomous, zero-maintenance financial data infrastructure running entirely on GitHub Actions. It extracts raw corporate XBRL facts from SEC EDGAR, deterministically calculates foundational margin, leverage, and liquidity ratios, and publishes zero-token-sink feeds for AI agents.

## Token Reduction Metrics
- **Average Token Savings**: ~98%
- **Mathematical Accuracy**: 100% deterministic arithmetic via Python (zero model hallucinations on margin or ratio division).

## Machine Feeds
- [`v1/ratios.json`](public/v1/ratios.json) (Pre-computed ratios)
- [`llms.txt`](public/llms.txt) (Token-efficient LLM digest)
- `ratios.parquet` (Columnar database snapshot)

## Architecture
- **Source**: SEC EDGAR XBRL Company Facts API
- **Engine**: Python Quantitative Engine + DuckDB
- **Ledger**: Append-only Git-committed JSONL in `/data/history`
- **Delivery**: GitHub Pages (Fastly CDN)
