"""
update_fundamentals.py
Fetches the last 8 quarterly income statements for every ticker in
stocks.json / watchlist.json (via yfinance) and writes fundamentals.json.
The dashboard's Earnings page computes growth, margins and red flags from it.

Values are stored in ₹ crore. Tickers that fail on a run keep their
previous data, so one flaky night doesn't wipe the file.
"""

import json
import math
import time
from datetime import datetime, timezone, timedelta

import yfinance as yf

ROWS = {
    # field: candidate row names in yfinance, first match wins
    "rev":      ["Total Revenue", "Operating Revenue"],
    "ebitda":   ["EBITDA", "Normalized EBITDA"],
    "pbt":      ["Pretax Income"],
    "tax":      ["Tax Provision"],
    "pat":      ["Net Income Common Stockholders", "Net Income",
                 "Net Income From Continuing Operation Net Minority Interest"],
    "unusual":  ["Total Unusual Items", "Total Unusual Items Excluding Goodwill"],
    "other_inc": ["Other Income Expense", "Other Non Operating Income Expenses"],
    "eps":      ["Diluted EPS", "Basic EPS"],
}
CRORE = 1e7


def load_tickers():
    tickers = set()
    for fname in ("stocks.json", "watchlist.json"):
        try:
            with open(fname) as f:
                for s in json.load(f):
                    if s.get("ticker"):
                        tickers.add(s["ticker"].strip().upper())
        except FileNotFoundError:
            pass
    return sorted(tickers)


def num(v, scale=CRORE):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(v):
        return None
    return round(v / scale, 2)


def fetch_one(ticker):
    df = yf.Ticker(ticker + ".NS").quarterly_income_stmt
    if df is None or df.empty:
        raise ValueError("no quarterly data")
    quarters = []
    for col in sorted(df.columns)[-8:]:
        q = {"q": col.strftime("%Y-%m-%d")}
        for field, names in ROWS.items():
            q[field] = None
            for n in names:
                if n in df.index:
                    val = num(df.at[n, col], 1 if field == "eps" else CRORE)
                    if val is not None:
                        q[field] = val
                        break
        if q["rev"] is not None or q["pat"] is not None:
            quarters.append(q)
    if not quarters:
        raise ValueError("empty rows")
    return quarters


def main():
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)
    tickers = load_tickers()
    print(f"Fundamentals update — {now:%d %b %Y %H:%M IST} — {len(tickers)} tickers")

    try:
        with open("fundamentals.json") as f:
            old = json.load(f).get("data", {})
    except (FileNotFoundError, json.JSONDecodeError):
        old = {}

    data, failed = {}, []
    for i, t in enumerate(tickers, 1):
        for attempt in (1, 2):
            try:
                data[t] = fetch_one(t)
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    failed.append(t)
                    if t in old:
                        data[t] = old[t]  # keep last good data
                    print(f"  ✗ {t}: {e}")
                else:
                    time.sleep(3)
        time.sleep(0.7)
        if i % 25 == 0:
            print(f"  … {i}/{len(tickers)}")

    fresh = len(tickers) - len(failed)
    if tickers and fresh < len(tickers) * 0.4:
        raise SystemExit(f"Aborting: only {fresh}/{len(tickers)} fetched — likely rate-limited by Yahoo")

    out = {
        "updated_at": now.isoformat(),
        "updated_at_readable": now.strftime("%d %b %Y %H:%M IST"),
        "units": "INR crore (eps in INR)",
        "data": data,
        "failed": failed,
    }
    with open("fundamentals.json", "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"✓ fundamentals.json — {fresh} fresh, {len(failed)} failed")
    if failed:
        print("  Failed:", ", ".join(failed))


if __name__ == "__main__":
    main()
