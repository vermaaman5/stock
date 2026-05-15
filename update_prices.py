"""
update_prices.py
Fetches latest closing prices for all tickers via yfinance
and writes prices.json to the repo root.
Runs daily via GitHub Actions at 3:30 PM IST (market close).
"""

import json
import yfinance as yf
from datetime import datetime, timezone, timedelta

# ─────────────────────────────────────────────
# YOUR TICKERS — add/remove as needed
# Format: "NSE_TICKER" (yfinance needs .NS suffix for NSE)
# ─────────────────────────────────────────────
TICKERS = [
    "COALINDIA",
    "NTPC",
    "HDFCBANK",
    "KOTAKBANK",
    "KECINTER",       # KEC International
    "INFY",
    "RELIANCE",
    "LTIM",           # LTIMindtree
    "POWERGRID",
    # ── add more below ──
]

# ─────────────────────────────────────────────
# Fetch prices
# ─────────────────────────────────────────────
def fetch_prices(tickers):
    prices = {}
    failed = []

    for ticker in tickers:
        yf_symbol = ticker + ".NS"
        try:
            data = yf.Ticker(yf_symbol)
            info = data.fast_info
            price = round(info.last_price, 2) if info.last_price else None

            if price:
                prices[ticker] = {
                    "cmp": price,
                    "prev_close": round(info.previous_close, 2) if info.previous_close else None,
                    "day_high": round(info.day_high, 2) if info.day_high else None,
                    "day_low": round(info.day_low, 2) if info.day_low else None,
                    "week_52_high": round(info.year_high, 2) if info.year_high else None,
                    "week_52_low": round(info.year_low, 2) if info.year_low else None,
                    "change_pct": round(
                        (price - info.previous_close) / info.previous_close * 100, 2
                    ) if info.previous_close else None,
                }
                print(f"  ✓ {ticker}: ₹{price}")
            else:
                failed.append(ticker)
                print(f"  ✗ {ticker}: no price returned")

        except Exception as e:
            failed.append(ticker)
            print(f"  ✗ {ticker}: {e}")

    return prices, failed


def main():
    IST = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(IST)
    print(f"\n{'─'*50}")
    print(f"  Price update — {now_ist.strftime('%d %b %Y %H:%M IST')}")
    print(f"{'─'*50}")

    prices, failed = fetch_prices(TICKERS)

    output = {
        "updated_at": now_ist.isoformat(),
        "updated_at_readable": now_ist.strftime("%d %b %Y %H:%M IST"),
        "prices": prices,
        "failed": failed,
        "total": len(prices),
    }

    with open("prices.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n  ✓ prices.json written — {len(prices)} tickers, {len(failed)} failed")
    if failed:
        print(f"  ✗ Failed tickers: {', '.join(failed)}")
    print(f"{'─'*50}\n")


if __name__ == "__main__":
    main()
