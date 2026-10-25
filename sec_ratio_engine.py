import os
import json
import hashlib
import duckdb
import requests
from datetime import datetime, timezone

DB_FILE = "data/sec_ratios.db"
HISTORY_DIR = "data/history"
EXPORT_DIR = "public"
API_DIR = os.path.join(EXPORT_DIR, "v1")

# High-capitalization targets frequently ingested by financial & quantitative agents
TARGET_COMPANIES = {
    "AAPL": {"cik": "0000320193", "name": "Apple Inc."},
    "MSFT": {"cik": "0000789019", "name": "Microsoft Corp"},
    "NVDA": {"cik": "0001045810", "name": "NVIDIA Corp"},
    "GOOGL": {"cik": "0001652044", "name": "Alphabet Inc."},
    "AMZN": {"cik": "0001018724", "name": "Amazon.com Inc."}
}

# SEC EDGAR requires a specific User-Agent format: SampleName AdminContact@<domain>.com
SEC_HEADERS = {
    "User-Agent": "AutonomousAgentResearchBot research@agentmesh.internal",
    "Accept-Encoding": "gzip, deflate"
}

def compute_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()

def get_latest_fact_val(us_gaap: dict, concept_tags: list) -> tuple[float, int, str]:
    """Finds the most recent 10-K or 10-Q filing value across alternative US-GAAP concept tags."""
    for tag in concept_tags:
        if tag not in us_gaap:
            continue
        units = us_gaap[tag].get("units", {})
        usd_units = units.get("USD", [])
        if not usd_units:
            continue

        # Filter strictly for 10-K annual or 10-Q quarterly reports
        valid_filings = [
            f for f in usd_units 
            if f.get("form") in ["10-K", "10-Q"] and "val" in f and "fy" in f
        ]
        if valid_filings:
            valid_filings.sort(key=lambda x: (x.get("fy", 0), x.get("fp", ""), x.get("filed", "")), reverse=True)
            latest = valid_filings[0]
            return float(latest["val"]), int(latest["fy"]), str(latest["form"])
            
    return 0.0, 0, ""

def fetch_and_calculate_ratios(ticker: str, cik: str, name: str) -> dict:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik.zfill(10)}.json"
    try:
        resp = requests.get(url, headers=SEC_HEADERS, timeout=20)
        if resp.status_code != 200:
            return {}
        facts = resp.json()
    except Exception as e:
        print(f"Failed to fetch {ticker}: {e}")
        return {}

    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    if not us_gaap:
        return {}

    # Extract foundational balance sheet and income statement items
    revenue, fy_rev, form = get_latest_fact_val(us_gaap, [
        "RevenueFromContractWithCustomerExcludingAssessedTax", 
        "Revenues", 
        "SalesRevenueNet"
    ])
    cost_of_rev, _, _ = get_latest_fact_val(us_gaap, [
        "CostOfGoodsAndServicesSold", 
        "CostOfRevenue"
    ])
    op_income, _, _ = get_latest_fact_val(us_gaap, [
        "OperatingIncomeLoss"
    ])
    net_income, fy_ni, _ = get_latest_fact_val(us_gaap, [
        "NetIncomeLoss"
    ])
    assets_curr, _, _ = get_latest_fact_val(us_gaap, [
        "AssetsCurrent"
    ])
    liab_curr, _, _ = get_latest_fact_val(us_gaap, [
        "LiabilitiesCurrent"
    ])
    total_liab, _, _ = get_latest_fact_val(us_gaap, [
        "Liabilities"
    ])
    equity, _, _ = get_latest_fact_val(us_gaap, [
        "StockholdersEquity", 
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
    ])

    # Deterministic calculations
    gross_margin = round((revenue - cost_of_rev) / revenue, 4) if revenue > 0 and cost_of_rev > 0 else 0.0
    operating_margin = round(op_income / revenue, 4) if revenue > 0 else 0.0
    net_margin = round(net_income / revenue, 4) if revenue > 0 else 0.0
    current_ratio = round(assets_curr / liab_curr, 4) if liab_curr > 0 else 0.0
    debt_to_equity = round(total_liab / equity, 4) if equity > 0 else 0.0

    raw_metrics = {
        "revenue_usd": revenue,
        "cost_of_revenue_usd": cost_of_rev,
        "operating_income_usd": op_income,
        "net_income_usd": net_income,
        "current_assets_usd": assets_curr,
        "current_liabilities_usd": liab_curr,
        "total_liabilities_usd": total_liab,
        "stockholders_equity_usd": equity
    }

    fiscal_year = max(fy_rev, fy_ni)

    canonical_state = {
        "ticker": ticker,
        "fiscal_year": fiscal_year,
        "form": form,
        "gross_margin": gross_margin,
        "operating_margin": operating_margin,
        "net_margin": net_margin,
        "current_ratio": current_ratio,
        "debt_to_equity": debt_to_equity
    }

    return {
        "ticker": ticker,
        "cik": cik,
        "company_name": name,
        "fiscal_year": fiscal_year,
        "form": form,
        "gross_margin": gross_margin,
        "operating_margin": operating_margin,
        "net_margin": net_margin,
        "current_ratio": current_ratio,
        "debt_to_equity": debt_to_equity,
        "raw_metrics": raw_metrics,
        "content_hash": compute_hash(canonical_state)
    }

def build_static_api(conn):
    os.makedirs(API_DIR, exist_ok=True)
    now_iso = datetime.now(timezone.utc).isoformat()

    cur = conn.execute("SELECT ticker, cik, company_name, fiscal_year, form, gross_margin, operating_margin, net_margin, current_ratio, debt_to_equity, raw_metrics_json, last_updated_utc FROM financial_ratios ORDER BY ticker ASC")
    rows = cur.fetchall()

    catalog = []
    lines = [
        "# SEC-XBRL Deterministic Ratio Wire",
        f"> Last Sync: {now_iso} UTC",
        "> Source: SEC EDGAR XBRL Company Facts (100% Deterministic Python Math)",
        "",
        "## Summary Performance Ratios"
    ]

    for row in rows:
        ticker, cik, name, fy, form, gm, om, nm, cr, de, raw_json, updated = row
        catalog.append({
            "ticker": ticker,
            "cik": cik,
            "company_name": name,
            "fiscal_year": fy,
            "form": form,
            "gross_margin": gm,
            "operating_margin": om,
            "net_margin": nm,
            "current_ratio": cr,
            "debt_to_equity": de,
            "raw_fundamentals": json.loads(raw_json),
            "updated_utc": updated
        })

        lines.append(
            f"- **{ticker}** ({name} - FY{fy} {form}): "
            f"Net Margin: {nm:.2%} | Op Margin: {om:.2%} | Current Ratio: {cr:.2f} | D/E: {de:.2f}"
        )

    with open(os.path.join(API_DIR, "ratios.json"), "w", encoding="utf-8") as f:
        json.dump({"metadata": {"updated_at": now_iso, "count": len(catalog)}, "companies": catalog}, f, indent=2)

    with open(os.path.join(EXPORT_DIR, "llms.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    html = f"""<!DOCTYPE html><html><head><title>SEC-XBRL Ratio Wire</title></head>
    <body style='font-family:system-ui,sans-serif;max-width:850px;margin:2rem auto;line-height:1.6;padding:0 1rem;'>
    <h1>📊 SEC-XBRL Deterministic Ratio Wire</h1>
    <p>Pre-computed corporate balance sheet and margin ratios directly from raw SEC EDGAR XBRL data.</p>
    <h3>Machine Feeds</h3>
    <ul>
      <li><a href='v1/ratios.json'>/v1/ratios.json</a> (Pre-computed Metrics JSON)</li>
      <li><a href='llms.txt'>llms.txt</a> (Token-Efficient Agent Digest)</li>
      <li><a href='ratios.parquet'>ratios.parquet</a> (Columnar Parquet Snapshot)</li>
    </ul>
    <h3>Latest Ratios</h3>
    <table border="1" cellpadding="6" style="border-collapse:collapse;width:100%;text-align:left;">
      <tr><th>Ticker</th><th>Company</th><th>Filing</th><th>Net Margin</th><th>Current Ratio</th><th>D/E</th></tr>
      {"".join([f"<tr><td><strong>{c['ticker']}</strong></td><td>{c['company_name']}</td><td>FY{c['fiscal_year']} {c['form']}</td><td>{c['net_margin']:.2%}</td><td>{c['current_ratio']:.2f}</td><td>{c['debt_to_equity']:.2f}</td></tr>" for c in catalog])}
    </table>
    </body></html>"""
    with open(os.path.join(EXPORT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

def run():
    os.makedirs("data", exist_ok=True)
    os.makedirs(HISTORY_DIR, exist_ok=True)
    os.makedirs(EXPORT_DIR, exist_ok=True)

    conn = duckdb.connect(DB_FILE)
    with open("schema.sql", "r", encoding="utf-8") as f:
        conn.execute(f.read())

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    date_str = now.strftime("%Y-%m-%d")
    year_str = now.strftime("%Y")
    month_str = now.strftime("%m")

    month_dir = os.path.join(HISTORY_DIR, year_str, month_str)
    os.makedirs(month_dir, exist_ok=True)
    daily_history_file = os.path.join(month_dir, f"{date_str}.jsonl")

    conn.execute("BEGIN TRANSACTION")

    for ticker, info in TARGET_COMPANIES.items():
        data = fetch_and_calculate_ratios(ticker, info["cik"], info["name"])
        if not data:
            continue

        raw_json = json.dumps(data["raw_metrics"]).replace("'", "''")
        hash_val = data["content_hash"]

        existing = conn.execute(f"SELECT content_hash FROM financial_ratios WHERE ticker = '{ticker}'").fetchone()

        if not existing:
            conn.execute(f"""
                INSERT INTO financial_ratios (
                    ticker, cik, company_name, fiscal_year, form, gross_margin,
                    operating_margin, net_margin, current_ratio, debt_to_equity,
                    raw_metrics_json, content_hash, last_updated_utc
                ) VALUES (
                    '{ticker}', '{data['cik']}', '{data['company_name']}', {data['fiscal_year']}, '{data['form']}',
                    {data['gross_margin']}, {data['operating_margin']}, {data['net_margin']}, {data['current_ratio']},
                    {data['debt_to_equity']}, '{raw_json}', '{hash_val}', '{now_iso}'
                )
            """)

            commit_id = conn.execute("SELECT nextval('seq_commit_id')").fetchone()[0]
            conn.execute(f"""
                INSERT INTO ledger (commit_id, timestamp_utc, operation, ticker, fiscal_year, net_margin, detail)
                VALUES ({commit_id}, '{now_iso}', 'INIT_RATIO', '{ticker}', {data['fiscal_year']}, {data['net_margin']}, 'Initial XBRL ratios compiled')
            """)

            ledger_entry = {
                "commit_id": commit_id,
                "timestamp_utc": now_iso,
                "operation": "INIT_RATIO",
                "ticker": ticker,
                "fiscal_year": data["fiscal_year"],
                "form": data["form"],
                "net_margin": data["net_margin"],
                "content_hash": hash_val
            }
            with open(daily_history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(ledger_entry) + "\n")

        elif existing[0] != hash_val:
            conn.execute(f"""
                UPDATE financial_ratios SET
                    fiscal_year = {data['fiscal_year']},
                    form = '{data['form']}',
                    gross_margin = {data['gross_margin']},
                    operating_margin = {data['operating_margin']},
                    net_margin = {data['net_margin']},
                    current_ratio = {data['current_ratio']},
                    debt_to_equity = {data['debt_to_equity']},
                    raw_metrics_json = '{raw_json}',
                    content_hash = '{hash_val}',
                    last_updated_utc = '{now_iso}'
                WHERE ticker = '{ticker}'
            """)

            commit_id = conn.execute("SELECT nextval('seq_commit_id')").fetchone()[0]
            conn.execute(f"""
                INSERT INTO ledger (commit_id, timestamp_utc, operation, ticker, fiscal_year, net_margin, detail)
                VALUES ({commit_id}, '{now_iso}', 'RATIO_DRIFT', '{ticker}', {data['fiscal_year']}, {data['net_margin']}, 'New filing processed')
            """)

            ledger_entry = {
                "commit_id": commit_id,
                "timestamp_utc": now_iso,
                "operation": "RATIO_DRIFT",
                "ticker": ticker,
                "fiscal_year": data["fiscal_year"],
                "form": data["form"],
                "net_margin": data["net_margin"],
                "content_hash": hash_val
            }
            with open(daily_history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(ledger_entry) + "\n")

    conn.execute("COMMIT")

    conn.execute(f"COPY (SELECT ticker, cik, company_name, fiscal_year, form, gross_margin, operating_margin, net_margin, current_ratio, debt_to_equity, content_hash, last_updated_utc FROM financial_ratios) TO '{EXPORT_DIR}/ratios.parquet' (FORMAT PARQUET)")
    build_static_api(conn)
    conn.close()

if __name__ == "__main__":
    run()
