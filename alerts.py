"""
alerts.py — Telegram alerts for the stock dashboard.

  python alerts.py prices    # after the price update: setups, breakdowns, SL/target hits
  python alerts.py results   # after the fundamentals update: new quarterly results

Needs GitHub secrets (Settings → Secrets and variables → Actions):
  TELEGRAM_BOT_TOKEN   token from @BotFather
  TELEGRAM_CHAT_ID     your chat id
  PORTFOLIO_PASSPHRASE the passphrase set in the dashboard's Settings; used to decrypt
                       portfolio.enc.json so alerts know your holdings, quantities and costs
  TELEGRAM_HOLDINGS    optional fallback if you don't use the encrypted portfolio:
                       comma-separated tickers, e.g. "BEML,COALINDIA,DBL"

Only alerts on NEW data: if the price file's close date hasn't changed since
the previous run, nothing is sent. Set ALERT_FORCE=1 to send anyway.
"""

import html
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
PASSPHRASE = os.environ.get("PORTFOLIO_PASSPHRASE", "")


def load_portfolio():
    """Decrypt portfolio.enc.json (written by the dashboard's Sync) with the
    PORTFOLIO_PASSPHRASE secret. PBKDF2-SHA256 -> AES-256-GCM, same as the browser."""
    if not PASSPHRASE:
        return []
    try:
        import base64
        import hashlib
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        with open("portfolio.enc.json") as f:
            enc = json.load(f)
        key = hashlib.pbkdf2_hmac("sha256", PASSPHRASE.encode(), base64.b64decode(enc["salt"]), int(enc["iter"]), 32)
        plain = AESGCM(key).decrypt(base64.b64decode(enc["iv"]), base64.b64decode(enc["ct"]), None)
        return json.loads(plain).get("holdings", [])
    except FileNotFoundError:
        print("No portfolio.enc.json yet — click Sync on the dashboard after setting a passphrase.")
    except Exception as e:  # noqa: BLE001
        print(f"Could not decrypt portfolio.enc.json ({type(e).__name__}) — check the PORTFOLIO_PASSPHRASE secret.")
    return []


PORTFOLIO = load_portfolio()
HELD = {h["ticker"].upper() for h in PORTFOLIO if h.get("ticker")} or \
    {t.strip().upper() for t in os.environ.get("TELEGRAM_HOLDINGS", "").split(",") if t.strip()}
FORCE = os.environ.get("ALERT_FORCE", "") == "1"
DASH = "https://vermaaman5.github.io/stock/"


def load(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def esc(s):
    return html.escape(str(s), quote=False)


def send(text):
    if not TOKEN or not CHAT:
        print("Telegram secrets not set — message not sent:\n")
        print(text)
        return
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 3900:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    chunks.append(cur)
    for c in chunks:
        data = urllib.parse.urlencode({"chat_id": CHAT, "text": c, "parse_mode": "HTML",
                                       "disable_web_page_preview": "true"}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=20) as r:
            print("Telegram:", r.status)


# ── technical setups: same rules as techOf() in index.html ──────────────────
def pct(a, b):
    return (a / b - 1) * 100 if a and b else None


def tech(p):
    x = (p or {}).get("tech")
    if not x:
        return None
    c = p["cmp"]
    d20, d50, d200 = pct(c, x.get("dma20")), pct(c, x.get("dma50")), pct(c, x.get("dma200"))
    dma50, dma200 = x.get("dma50"), x.get("dma200")
    trend = None
    if dma50 and dma200:
        trend = "up" if c > dma50 > dma200 else "down" if c < dma50 < dma200 else "side"
    v, rsi = x.get("vol_ratio") or 0, x.get("rsi14")
    setup = None
    if x.get("lo20") and c < x["lo20"] and v >= 1.5:
        setup = "Breakdown"
    elif x.get("hi20") and c > x["hi20"] and v >= 1.5 and (not dma50 or c > dma50):
        setup = "Breakout"
    elif trend == "up" and rsi is not None and 38 <= rsi <= 55 and (
            (d20 is not None and abs(d20) <= 2.5) or (d50 is not None and abs(d50) <= 2.5)):
        setup = "Pullback"
    elif dma200 and c > dma200 and rsi is not None and rsi < 35:
        setup = "Oversold"
    elif (rsi is not None and rsi > 75) or (d20 is not None and d20 > 12):
        setup = "Extended"
    atr = x.get("atr14")
    plan = None
    if setup in ("Breakout", "Pullback", "Oversold") and atr:
        stop = c - 2 * atr
        plan = (stop, c + 2 * (c - stop))
    return {"c": c, "trend": trend, "setup": setup, "rsi": rsi, "rs": x.get("rs_3m"), "vr": v,
            "d200": d200, "plan": plan}


def close_date(prices):
    dates = [p.get("date") for p in (prices or {}).get("prices", {}).values() if p.get("date")]
    return Counter(dates).most_common(1)[0][0] if dates else None


def inr(v):
    """Indian digit grouping: ₹1,48,153"""
    if v < 100:
        return f"₹{v:,.2f}"
    s = f"{v:.0f}"
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return "₹" + ",".join(parts + [tail]) if parts else "₹" + tail


def prices_alert():
    new, old = load("prices.json", {}), load("prices_prev.json", None)
    if old is None:
        print("No previous prices to compare — first run, no alert.")
        return
    stocks = {s["ticker"]: s for s in load("stocks.json", [])}
    nd, od = close_date(new), close_date(old)
    if nd and nd == od and not FORCE:
        print(f"No new close since last run ({nd}) — no alert.")
        return
    P, O = new.get("prices", {}), old.get("prices", {})
    lines = [f"<b>📊 Market close {esc(nd or new.get('updated_at_readable', ''))}</b>"]

    n = (new.get("index") or {}).get("NIFTY")
    if n and n.get("dma50") and n.get("dma200"):
        a50, a200 = n["cmp"] > n["dma50"], n["cmp"] > n["dma200"]
        mood = "🟢 Risk-on" if a50 and a200 else "🔴 Risk-off — size down" if not a50 and not a200 else "🟡 Mixed — be selective"
        lines.append(f"Nifty {n['cmp']:,.0f} ({n.get('change_pct', 0):+.2f}%) · {mood}")

    # Holdings
    if HELD:
        hl = []
        for t in sorted(HELD):
            p, k = P.get(t), tech(P.get(t))
            if not p:
                continue
            k0 = tech(O.get(t))
            s = stocks.get(t, {})
            why = []
            if k and k["setup"] == "Breakdown":
                why.append(f"broke 20-day low on {k['vr']}× volume")
            if k and k["d200"] is not None and k["d200"] < 0 and (not k0 or (k0["d200"] or 0) >= 0):
                why.append("fell below 200 DMA")
            if s.get("sl") and p["cmp"] <= s["sl"] < (O.get(t, {}).get("cmp") or 1e12):
                why.append(f"hit your SL {inr(s['sl'])}")
            if s.get("target") and p["cmp"] >= s["target"] > (O.get(t, {}).get("cmp") or 0):
                why.append(f"hit target {inr(s['target'])}")
            if p.get("change_pct", 0) <= -5:
                why.append(f"down {p['change_pct']:.1f}% today")
            if k and k["setup"] in ("Breakout",) and (not k0 or k0["setup"] != "Breakout"):
                why.append("breakout on volume — trail your stop")
            if why:
                hl.append(f"• <b>{esc(t)}</b> {inr(p['cmp'])}: " + "; ".join(why))
        lines.append("\n<b>💼 Your holdings</b>")
        if PORTFOLIO:
            inv = val = day = 0.0
            for h in PORTFOLIO:
                p = P.get(h["ticker"])
                if not p:
                    continue
                inv += h["qty"] * h["avg"]
                val += h["qty"] * p["cmp"]
                day += h["qty"] * (p["cmp"] - (p.get("prev_close") or p["cmp"]))
            if inv:
                lines.append(f"Value {inr(val)} · today {'+' if day >= 0 else '−'}{inr(abs(day))} "
                             f"({day / (val - day) * 100:+.2f}%) · total P&L {'+' if val >= inv else '−'}{inr(abs(val - inv))} "
                             f"({(val / inv - 1) * 100:+.1f}%)")
        lines += hl or ["• Nothing new. No breakdowns, SL hits or 200 DMA breaks."]

    # New long setups (not the same setup yesterday), strongest relative strength first
    longs = []
    for t, p in P.items():
        k = tech(p)
        if not k or k["setup"] not in ("Breakout", "Pullback", "Oversold"):
            continue
        k0 = tech(O.get(t))
        if k0 and k0["setup"] == k["setup"]:
            continue
        if k["setup"] != "Oversold" and (k["rs"] is None or k["rs"] < 0):
            continue
        longs.append((k["rs"] or -99, t, k))
    longs.sort(reverse=True)
    lines.append(f"\n<b>🚀 New long setups ({len(longs)})</b>")
    for _, t, k in longs[:10]:
        st, tg = k["plan"]
        held = " (held)" if t in HELD else ""
        lines.append(f"• <b>{esc(t)}</b>{held} {k['setup']} {inr(k['c'])} · RS {k['rs']:+.0f} · "
                     f"stop {inr(st)} · target {inr(tg)}")
    if not longs:
        lines.append("• None today with positive relative strength.")
    elif len(longs) > 10:
        lines.append(f"• +{len(longs) - 10} more on the dashboard")

    # New breakdowns in coverage (excluding holdings, already above)
    bd = [t for t, p in P.items() if t not in HELD and (tech(p) or {}).get("setup") == "Breakdown"
          and (tech(O.get(t)) or {}).get("setup") != "Breakdown"]
    if bd:
        lines.append(f"\n<b>⚠️ Breakdowns</b>: " + ", ".join(esc(t) for t in sorted(bd)[:15]))

    # Coverage SL / target crossings today
    hits = []
    for t, s in stocks.items():
        p, o = P.get(t), O.get(t)
        if not p or not o or t in HELD:
            continue
        if s.get("sl") and p["cmp"] <= s["sl"] < o["cmp"]:
            hits.append(f"{esc(t)} hit SL {inr(s['sl'])}")
        if s.get("target") and p["cmp"] >= s["target"] > o["cmp"]:
            hits.append(f"{esc(t)} hit target {inr(s['target'])}")
    if hits:
        lines.append("\n<b>🎯 Coverage levels</b>\n• " + "\n• ".join(hits))

    lines.append(f"\n<a href=\"{DASH}\">Open dashboard</a>")
    send("\n".join(lines))


# ── results: simplified port of eqAnalyse() in index.html ───────────────────
def margin(q):
    return q["ebitda"] / q["rev"] * 100 if q.get("rev") and q.get("ebitda") is not None else None


def growth(a, b):
    return (a - b) / abs(b) * 100 if a is not None and b not in (None, 0) else None


def results_flags(Q, sector):
    L = Q[-1]
    Y = None
    from datetime import date
    lq = date.fromisoformat(L["q"])
    for q in reversed(Q[:-1]):
        gap = (lq - date.fromisoformat(q["q"])).days
        if 330 < gap < 400:
            Y = q
            break
    flags = []
    rev_y = growth(L.get("rev"), Y.get("rev")) if Y else None
    pat_y = growth(L.get("pat"), Y.get("pat")) if Y else None
    if L.get("pat") is not None and L["pat"] < 0:
        flags.append((3, "loss quarter"))
    if rev_y is not None and pat_y is not None and rev_y >= 5 and pat_y <= -15:
        flags.append((3, f"sales {rev_y:+.0f}% but PAT {pat_y:+.0f}%"))
    m, my = margin(L), margin(Y) if Y else None
    if m is not None and my is not None and (m - my) * 100 <= -300:
        flags.append((3 if (m - my) * 100 <= -600 else 2, f"margin {m:.1f}% ({(m - my) * 100:+.0f} bps)"))
    if (L.get("pbt") or 0) > 0 and L.get("tax") is not None and (L["tax"] < 0 or L["tax"] / L["pbt"] < 0.10):
        flags.append((2, "tax-boosted profit"))
    if sector != "BFSI" and (L.get("other_inc") or 0) > 0 and (L.get("pbt") or 0) > 0 and L["other_inc"] / L["pbt"] >= 0.25:
        flags.append((2, f"other income {L['other_inc'] / L['pbt'] * 100:.0f}% of PBT"))
    if rev_y is not None and rev_y <= -10:
        flags.append((2, f"sales {rev_y:+.0f}%"))
    s3 = sum(1 for f in flags if f[0] >= 3)
    s2 = sum(1 for f in flags if f[0] == 2)
    grade = "weak" if s3 or s2 >= 2 else "watch" if s2 else "good"
    return grade, rev_y, pat_y, [f[1] for f in flags]


def results_alert():
    new, old = load("fundamentals.json", {}), load("fundamentals_prev.json", None)
    if old is None:
        print("No previous results file to compare — first run, no alert.")
        return
    stocks = {s["ticker"]: s for s in load("stocks.json", [])}
    N, O = new.get("data", {}), old.get("data", {})
    fresh = []
    for t, Q in N.items():
        if not Q:
            continue
        prev_last = (O.get(t) or [{}])[-1].get("q")
        if prev_last == Q[-1]["q"] and not FORCE:
            continue
        s = stocks.get(t, {})
        active = t in HELD or s.get("action") in ("buy", "accumulate", "sell") or s.get("view", "neutral") != "neutral"
        grade, rv, pt, flags = results_flags(Q, s.get("sector"))
        fresh.append((t in HELD, active, grade, t, rv, pt, flags))
    if not fresh:
        print("No new quarterly results — no alert.")
        return
    order = {"weak": 0, "watch": 1, "good": 2}
    fresh.sort(key=lambda x: (not x[0], not x[1], order[x[2]], x[3]))
    icon = {"weak": "🔴", "watch": "🟡", "good": "🟢"}
    lines = [f"<b>🧾 New quarterly results ({len(fresh)})</b>"]
    shown = [f for f in fresh if f[0] or f[1] or f[2] == "weak"][:25]
    for held, _, grade, t, rv, pt, flags in shown:
        g = f"sales {rv:+.0f}% · PAT {pt:+.0f}%" if rv is not None and pt is not None else "no YoY yet"
        lines.append(f"{icon[grade]} <b>{esc(t)}</b>{' (held)' if held else ''}: {g}" + (f" — {esc('; '.join(flags))}" if flags else ""))
    rest = len(fresh) - len(shown)
    if rest > 0:
        lines.append(f"+{rest} more on the Earnings page")
    lines.append(f"\n<a href=\"{DASH}\">Open dashboard</a>")
    send("\n".join(lines))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "prices"
    if mode == "results":
        results_alert()
    else:
        prices_alert()
