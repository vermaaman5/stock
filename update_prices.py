"""
update_prices.py
Dynamically reads tickers from stocks.json and watchlist.json,
fetches prices via yfinance, writes prices.json.
Runs daily via GitHub Actions at 9:00 AM IST (3:30 UTC).
"""

import json
import math
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


def _r(v, d=2):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else round(v, d)


def _ret(close, n):
    if len(close) <= n:
        return None
    return _r((close.iloc[-1] / close.iloc[-1 - n] - 1) * 100, 1)


def technicals(df):
    """Swing-trading indicators from daily OHLCV (oldest -> newest)."""
    c, h, l = df["Close"], df["High"], df["Low"]
    v = df["Volume"] if "Volume" in df else None
    n = len(c)
    sma = lambda k: _r(c.tail(k).mean()) if n >= k else None
    # RSI 14 and ATR 14, Wilder smoothing
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + up.iloc[-1] / dn.iloc[-1]) if dn.iloc[-1] > 0 else 100.0
    prev_c = c.shift(1)
    tr = (h - l).combine((h - prev_c).abs(), max).combine((l - prev_c).abs(), max)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    prior = df.iloc[:-1]  # levels exclude today, so a close above them is a breakout
    vol_ratio = None
    if v is not None and n > 21:
        avg = v.iloc[-21:-1].mean()
        vol_ratio = _r(v.iloc[-1] / avg, 2) if avg > 0 else None
    return {
        "dma20": sma(20), "dma50": sma(50), "dma200": sma(200),
        "rsi14": _r(rsi, 1) if n > 15 else None,
        "atr14": _r(atr) if n > 15 else None,
        "vol_ratio": vol_ratio,
        "hi20": _r(prior["High"].tail(20).max()) if n > 21 else None,
        "lo20": _r(prior["Low"].tail(20).min()) if n > 21 else None,
        "hi55": _r(prior["High"].tail(55).max()) if n > 56 else None,
        "ret_1m": _ret(c, 21), "ret_3m": _ret(c, 63), "ret_6m": _ret(c, 126),
        "spark": [_r(x) for x in c.tail(60)],
    }


def fetch_index():
    """Nifty 50 levels and returns, for relative strength and market regime."""
    try:
        df = yf.download("^NSEI", period="1y", interval="1d", progress=False, auto_adjust=False)
        if hasattr(df.columns, "levels"):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna()
        t = technicals(df)
        t.pop("spark", None)
        t["cmp"] = _r(df["Close"].iloc[-1])
        t["change_pct"] = _r((df["Close"].iloc[-1] / df["Close"].iloc[-2] - 1) * 100)
        return {"NIFTY": t}
    except Exception as e:  # noqa: BLE001
        print(f"  Nifty fetch failed: {e}")
        return {}


def fetch_prices(tickers, index=None):
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
            try:
                tech = technicals(df)
                nifty = (index or {}).get("NIFTY", {})
                for k in ("ret_3m", "ret_6m"):
                    if tech.get(k) is not None and nifty.get(k) is not None:
                        tech["rs_" + k[4:]] = round(tech[k] - nifty[k], 1)
                prices[t]["tech"] = tech
            except Exception as e:  # noqa: BLE001
                print(f"  tech failed for {t}: {e}")
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

    index = fetch_index()
    prices, failed = fetch_prices(tickers, index)

    output = {
        "updated_at": now_ist.isoformat(),
        "updated_at_readable": now_ist.strftime("%d %b %Y %H:%M IST"),
        "index": index,
        "prices": prices,
        "failed": failed,
        "total": len(prices),
    }

    with open("prices.json", "w") as f:
        json.dump(output, f, separators=(",", ":"))

    print(f"\n  ✓ prices.json written — {len(prices)} tickers, {len(failed)} failed")
    if failed:
        print(f"  ✗ Failed: {', '.join(failed)}")
    print(f"{'─'*50}\n")


if __name__ == "__main__":
    main()
