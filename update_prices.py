"""
update_prices.py
Dynamically reads tickers from stocks.json and watchlist.json,
fetches prices via yfinance, writes prices.json.
Runs daily via GitHub Actions at 9:00 AM IST (3:30 UTC).
"""

import json
import yfinance as yf
from datetime import datetime, timezone, timedelta

def load_tickers_from_json():
    """Read tickers dynamically from stocks.json and watchlist.json"""
    tickers = set()
    
    # Load from stocks.json
    try:
        with open("stocks.json", "r") as f:
            stocks = json.load(f)
            for s in stocks:
                if s.get("ticker"):
                    tickers.add(s["ticker"].strip().upper())
        print(f"  Loaded {len(tickers)} tickers from stocks.json")
    except FileNotFoundError:
        print("  stocks.json not found — using fallback list")
    except Exception as e:
        print(f"  Error reading stocks.json: {e}")

    # Load from watchlist.json
    try:
        with open("watchlist.json", "r") as f:
            watchlist = json.load(f)
            before = len(tickers)
            for w in watchlist:
                if w.get("ticker"):
                    tickers.add(w["ticker"].strip().upper())
            print(f"  Added {len(tickers)-before} tickers from watchlist.json")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"  Error reading watchlist.json: {e}")

    # Fallback if no files found
    if not tickers:
        print("  Using fallback ticker list")
        tickers = {
            "NTPC","POWERGRID","COALINDIA","TATAPOWER","RELIANCE","HDFCBANK",
            "ICICIBANK","SBIN","INFY","TCS","WIPRO","KECINTER","LT","SUNPHARMA",
            "MARUTI","TATAMOTORS","TATASTEEL","JSWSTEEL","HAL","BEL",
        }

    return sorted(list(tickers))


def fetch_prices(tickers):
    prices = {}
    failed = []

    for ticker in tickers:
        # Skip placeholder/invalid tickers
        if not ticker or len(ticker) < 2:
            continue
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

    tickers = load_tickers_from_json()
    print(f"\n  Fetching prices for {len(tickers)} tickers...\n")

    prices, failed = fetch_prices(tickers)

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
        print(f"  ✗ Failed: {', '.join(failed)}")
    print(f"{'─'*50}\n")


if __name__ == "__main__":
    main()
