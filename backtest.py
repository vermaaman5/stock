"""
backtest.py
Tests the dashboard's swing setups (Breakout, Pullback, Oversold) on ~5 years
of daily data for every stock in stocks.json, using the same rules as the
Technicals page, and writes backtest.json for the dashboard.

Trade rules (identical for every setup):
  - Signal on day T's close. Entry at day T+1's open.
  - Stop  = signal close - 2 x ATR(14) at signal.  Target = entry + 2 x (entry - stop).
  - Exit at stop or target using daily high/low. If both are touched the same
    day, the stop is assumed (conservative). Gaps through a level exit at the open.
  - Time stop: exit at the close after 20 trading days.
  - One open trade per stock per setup at a time.
  - Results in R (multiples of the risk taken). +2R = target hit, -1R = stopped.

Baseline: the same exits applied to an entry every 10th day in every stock,
so you can see whether a setup beats buying at random.
Costs: 0.25% round trip (brokerage, STT, slippage) deducted from every trade.
"""

import json
import math
import time
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

YEARS = 5
MAX_HOLD = 20
COST = 0.0025          # round-trip, as a fraction of entry price
BASELINE_EVERY = 10
SETUPS = ["Breakout", "Pullback", "Oversold"]
IST = timezone(timedelta(hours=5, minutes=30))


def load_tickers():
    with open("stocks.json") as f:
        stocks = json.load(f)
    return {s["ticker"].strip().upper(): s.get("sector", "Other") for s in stocks if s.get("ticker")}


def indicators(df):
    c, h, l, v = df["Close"], df["High"], df["Low"], df["Volume"]
    out = pd.DataFrame(index=df.index)
    out["c"], out["o"], out["h"], out["l"] = c, df["Open"], h, l
    out["dma20"] = c.rolling(20).mean()
    out["dma50"] = c.rolling(50).mean()
    out["dma200"] = c.rolling(200).mean()
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    out["rsi"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    out["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    out["hi20"] = h.shift(1).rolling(20).max()
    out["lo20"] = l.shift(1).rolling(20).min()
    avgv = v.shift(1).rolling(20).mean()
    out["vr"] = v / avgv.replace(0, np.nan)
    return out


def classify(x):
    """Vectorised version of techOf() in index.html. Returns a Series of setup names."""
    c = x["c"]
    d20 = (c / x["dma20"] - 1) * 100
    d50 = (c / x["dma50"] - 1) * 100
    up = (c > x["dma50"]) & (x["dma50"] > x["dma200"])
    breakdown = (c < x["lo20"]) & (x["vr"] >= 1.5)
    breakout = (c > x["hi20"]) & (x["vr"] >= 1.5) & (c > x["dma50"])
    pullback = up & x["rsi"].between(38, 55) & ((d20.abs() <= 2.5) | (d50.abs() <= 2.5))
    oversold = (c > x["dma200"]) & (x["rsi"] < 35)
    s = pd.Series(None, index=x.index, dtype=object)
    # same priority order as the dashboard
    s[oversold] = "Oversold"
    s[pullback] = "Pullback"
    s[breakout] = "Breakout"
    s[breakdown] = "Breakdown"
    s[x["dma200"].isna()] = None
    return s


def simulate(x, i):
    """Trade signalled on bar i. Returns (R, days, outcome) or None."""
    n = len(x)
    if i + 1 >= n:
        return None
    sig_c, atr = x["c"].iat[i], x["atr"].iat[i]
    if not (atr > 0):
        return None
    entry = x["o"].iat[i + 1]
    stop = sig_c - 2 * atr
    if not (entry > stop):
        return None  # gapped below the stop: no trade
    risk = entry - stop
    target = entry + 2 * risk
    cost_r = entry * COST / risk
    for j in range(i + 1, min(i + 1 + MAX_HOLD, n)):
        o, h, l = x["o"].iat[j], x["h"].iat[j], x["l"].iat[j]
        if j > i + 1 and o <= stop:
            return ((o - entry) / risk - cost_r, j - i, "stop")
        if j > i + 1 and o >= target:
            return ((o - entry) / risk - cost_r, j - i, "target")
        if l <= stop:
            return (-1 - cost_r, j - i, "stop")
        if h >= target:
            return (2 - cost_r, j - i, "target")
    j = min(i + MAX_HOLD, n - 1)
    if j <= i:
        return None
    return ((x["c"].iat[j] - entry) / risk - cost_r, j - i, "time")


def regime_series(nifty):
    c = nifty["Close"]
    d50, d200 = c.rolling(50).mean(), c.rolling(200).mean()
    r = pd.Series("mixed", index=nifty.index)
    r[(c > d50) & (c > d200)] = "risk_on"
    r[(c < d50) & (c < d200)] = "risk_off"
    r[d200.isna()] = None
    return r


def summarise(trades):
    if not trades:
        return {"trades": 0}
    R = np.array([t["r"] for t in trades])
    wins = R[R > 0]
    losses = R[R <= 0]
    gross_win, gross_loss = wins.sum(), -losses.sum()
    return {
        "trades": int(len(R)),
        "win_rate": round(float((R > 0).mean() * 100), 1),
        "avg_r": round(float(R.mean()), 3),
        "avg_win_r": round(float(wins.mean()), 2) if len(wins) else None,
        "avg_loss_r": round(float(losses.mean()), 2) if len(losses) else None,
        "profit_factor": round(float(gross_win / gross_loss), 2) if gross_loss > 0 else None,
        "target_pct": round(sum(t["out"] == "target" for t in trades) / len(R) * 100, 1),
        "stop_pct": round(sum(t["out"] == "stop" for t in trades) / len(R) * 100, 1),
        "avg_days": round(float(np.mean([t["days"] for t in trades])), 1),
    }


def download(symbols):
    for attempt in (1, 2, 3):
        try:
            return yf.download(symbols, period=f"{YEARS}y", interval="1d", group_by="ticker",
                               auto_adjust=True, progress=False, threads=True)
        except Exception as e:  # noqa: BLE001
            print(f"  download attempt {attempt} failed: {e}")
            time.sleep(10 * attempt)
    return None


def main():
    now = datetime.now(IST)
    sectors = load_tickers()
    tickers = sorted(sectors)
    print(f"Backtest — {now:%d %b %Y %H:%M IST} — {len(tickers)} stocks, {YEARS}y")

    nifty = yf.download("^NSEI", period=f"{YEARS}y", interval="1d", auto_adjust=True, progress=False)
    if hasattr(nifty.columns, "levels"):
        nifty.columns = nifty.columns.get_level_values(0)
    regime = regime_series(nifty.dropna(subset=["Close"]))

    trades = {s: [] for s in SETUPS}
    baseline = []
    failed = []
    first_date = None
    for k in range(0, len(tickers), 40):
        batch = tickers[k:k + 40]
        raw = download([t + ".NS" for t in batch])
        if raw is None:
            failed += batch
            continue
        for t in batch:
            try:
                df = raw[t + ".NS"].dropna(subset=["Close", "Open", "High", "Low"])
                if len(df) < 260:
                    raise ValueError("not enough history")
                x = indicators(df)
                setups = classify(x)
                first_date = min(first_date or x.index[230], x.index[230])
                reg = regime.reindex(x.index, method="ffill")
                busy = {s: -1 for s in SETUPS}
                for i in range(200, len(x) - 1):
                    s = setups.iat[i]
                    if s in SETUPS and i > busy[s]:
                        res = simulate(x, i)
                        if res:
                            r, days, out = res
                            trades[s].append({"t": t, "d": x.index[i].strftime("%Y-%m-%d"), "r": r,
                                              "days": days, "out": out, "reg": reg.iat[i],
                                              "sec": sectors[t], "y": x.index[i].year})
                            busy[s] = i + days
                    if i % BASELINE_EVERY == 0:
                        res = simulate(x, i)
                        if res:
                            baseline.append({"r": res[0], "days": res[1], "out": res[2], "reg": reg.iat[i]})
            except Exception as e:  # noqa: BLE001
                failed.append(t)
                print(f"  ✗ {t}: {e}")
        print(f"  … {min(k + 40, len(tickers))}/{len(tickers)}")

    out = {
        "updated_at_readable": now.strftime("%d %b %Y %H:%M IST"),
        "period": f"{first_date:%b %Y} – {now:%b %Y}" if first_date is not None else None,
        "rules": {"entry": "next day open", "stop": "2×ATR(14) below signal close",
                  "target": "2R", "max_hold_days": MAX_HOLD, "cost_round_trip_pct": COST * 100},
        "baseline": summarise(baseline),
        "baseline_by_regime": {g: summarise([b for b in baseline if b["reg"] == g])
                               for g in ("risk_on", "mixed", "risk_off")},
        "setups": {},
        "failed": failed,
    }
    for s in SETUPS:
        T = trades[s]
        by_sec = {}
        for sec in sorted({x["sec"] for x in T}):
            by_sec[sec] = summarise([x for x in T if x["sec"] == sec])
        out["setups"][s] = {
            "all": summarise(T),
            "by_regime": {g: summarise([x for x in T if x["reg"] == g]) for g in ("risk_on", "mixed", "risk_off")},
            "by_year": {str(y): summarise([x for x in T if x["y"] == y]) for y in sorted({x["y"] for x in T})},
            "by_sector": by_sec,
            "recent": sorted(T, key=lambda x: x["d"])[-15:],
        }
    for s in SETUPS:
        for r in out["setups"][s]["recent"]:
            r["r"] = round(r["r"], 2)
    with open("backtest.json", "w") as f:
        json.dump(out, f, separators=(",", ":"))
    for s in SETUPS:
        a = out["setups"][s]["all"]
        print(f"  {s:9} trades {a.get('trades', 0):5}  win {a.get('win_rate')}%  avg {a.get('avg_r')}R")
    b = out["baseline"]
    print(f"  Baseline  trades {b.get('trades', 0):5}  win {b.get('win_rate')}%  avg {b.get('avg_r')}R")
    print(f"✓ backtest.json written — {len(failed)} failed")


if __name__ == "__main__":
    main()
