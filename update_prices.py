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
    syms = [t + ".NS" for t in tickers if t and len(t) >= 2]
    raw = yf.download(syms, period="1y", interval="1d", group_by="ticker",
                      threads=False, progress=False, auto_adjust=False)
    prices, failed = {}, []
    for t in tickers:
        try:
            df = raw[t + ".NS"].dropna()
            if df.empty:
                raise ValueError("no data")
            last = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2])
            prices[t] = {
                "cmp": round(last, 2),
                "prev_close": round(prev, 2),
                "day_high": round(float(df["High"].iloc[-1]), 2),
                "day_low": round(float(df["Low"].iloc[-1]), 2),
                "week_52_high": round(float(df["High"].tail(250).max()), 2),
                "week_52_low": round(float(df["Low"].tail(250).min()), 2),
                "change_pct": round((last - prev) / prev * 100, 2),
            }
        except Exception:
            failed.append(t)
    if len(failed) > len(tickers) * 0.5:
        raise SystemExit(f"Aborting: {len(failed)}/{len(tickers)} failed — likely rate-limited by Yahoo")
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
