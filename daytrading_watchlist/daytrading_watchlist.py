#!/usr/bin/env python3
"""
Day-Trading Watchlist Generator
============================================================
Gives you a short list of in-play stocks to look at each morning.
It does NOT trade, predict, or place orders — you do the trading.
It just answers one question: "what's worth pulling up today?"

Style: small/mid-cap intraday momentum (Emmanuel-style). It looks for
the day's movers, keeps the ones in your price range that are trading
on real volume, strips out ETFs / funds / junk, ranks them, and writes
a clean watchlist you open in your browser.

DATA: Yahoo Finance via the `yfinance` library.
  - No API key.
  - No daily request limit.
  - Free.

USAGE
-----
    pip install yfinance pandas
    python daytrading_watchlist.py            # today's live watchlist
    python daytrading_watchlist.py --demo      # offline sample, no network
    python daytrading_watchlist.py --shorts    # include short candidates too

Then open the newest file in the watchlists/ folder.

Best run in the morning before/around the open. Re-run it any day — the
list is only good for the day it's built. A stale watchlist is a trap.
"""

import os
import sys
import csv
import math
import argparse
import datetime as dt

# Repo root = one level above this script's folder (daytrading_watchlist/).
# If this file is ever moved to the repo root, change to:
#   REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)


def publish_to_docs(tone, rows):
    """Write the page GitHub Pages serves: <repo>/docs/index.html + watchlist.csv

    Nothing else in the publish chain changes — publish.py commits and pushes
    whatever is in docs/, and does not care which script produced it.
    """
    docs = os.path.join(REPO_ROOT, "docs")
    os.makedirs(docs, exist_ok=True)
    open(os.path.join(docs, ".nojekyll"), "a").close()   # stop Pages running Jekyll
    write_html(tone, rows, os.path.join(docs, "index.html"))
    write_csv(rows, os.path.join(docs, "watchlist.csv"))
    print(f"Published to {os.path.join(docs, 'index.html')}")


# ============================================================
# CONFIG  —  tune these. This is the whole control panel.
# ============================================================
CONFIG = {
    # Price range you actually trade. Emmanuel's lane is low/mid-priced names.
    "min_price": 1.0,
    "max_price": 20.0,

    # A name is "in play" only if BOTH are true:
    "min_change_pct": 5.0,      # moved at least this % today (abs value)
    "min_rel_volume": 1.5,      # trading at least this x its normal volume

    # Liquidity floor so you can actually get filled
    "min_dollar_volume": 1_000_000,

    # Keep it small/mid cap — skip the megacap name brands (set None to disable)
    "max_market_cap": 3_000_000_000,   # $3B

    # Which Yahoo screeners to pull the universe from
    "screeners_long":  ["day_gainers", "small_cap_gainers",
                         "most_actives", "aggressive_small_caps"],
    "screeners_short": ["day_losers"],

    "include_shorts": False,    # lean long while learning; --shorts overrides
    "top_n": 15,                # how many names on the final list
    "enrich_levels": True,      # pull gap / day range / ADR for the top names
    "market_tone_symbol": "QQQ",
    "out_dir": "watchlists",
}

# Ticker/name patterns that mark things we don't day trade
JUNK_KEYWORDS = ("ETF", "FUND", "TRUST", "ETN", "2X", "3X", "BULL", "BEAR",
                 "LEVERAGED", "ACQUISITION", "WARRANT", "RIGHT", "UNIT",
                 "DIREXION", "PROSHARES", "ISHARES", "SPDR")


# ============================================================
# Data layer (live) — the only part that touches the network
# ============================================================
def get_screener_rows(screen_names):
    """Pull quotes from Yahoo predefined screeners. Returns list of dicts."""
    import yfinance as yf
    seen = {}
    for name in screen_names:
        try:
            res = yf.screen(name, count=100)
            quotes = res.get("quotes", []) if isinstance(res, dict) else []
        except Exception as e:
            print(f"  ! screener '{name}' failed: {str(e)[:120]}")
            continue
        for q in quotes:
            sym = q.get("symbol")
            if sym:
                seen[sym] = q          # dedupe by symbol
        print(f"  {name}: {len(quotes)} names")
    return list(seen.values())


def normalize(q):
    """Map a Yahoo quote dict to the fields we use."""
    price = q.get("regularMarketPrice")
    chg = q.get("regularMarketChangePercent")
    vol = q.get("regularMarketVolume")
    avgvol = q.get("averageDailyVolume3Month") or q.get("averageDailyVolume10Day")
    rvol = (vol / avgvol) if (vol and avgvol) else None
    return {
        "symbol": q.get("symbol"),
        "name": q.get("shortName") or q.get("longName") or "",
        "price": price,
        "change": chg,
        "volume": vol,
        "rvol": rvol,
        "dollar_vol": (price * vol) if (price and vol) else None,
        "market_cap": q.get("marketCap"),
        "quote_type": (q.get("quoteType") or "").upper(),
        "exchange": q.get("fullExchangeName") or q.get("exchange") or "",
    }


def enrich(sym):
    """Pull recent bars for gap %, day range, and ADR%. Best-effort."""
    import yfinance as yf
    try:
        h = yf.Ticker(sym).history(period="1mo", interval="1d")
        if len(h) < 2:
            return {}
        prev_close = float(h["Close"].iloc[-2])
        today = h.iloc[-1]
        op, hi, lo = float(today["Open"]), float(today["High"]), float(today["Low"])
        gap = (op - prev_close) / prev_close * 100 if prev_close else None
        adr = float(((h["High"] - h["Low"]) / h["Close"]).tail(14).mean() * 100)
        return {"gap": gap, "day_high": hi, "day_low": lo, "adr_pct": adr,
                "prev_close": prev_close}
    except Exception:
        return {}


def get_market_tone(sym):
    import yfinance as yf
    try:
        h = yf.Ticker(sym).history(period="5d", interval="1d")
        last = float(h["Close"].iloc[-1]); prev = float(h["Close"].iloc[-2])
        chg = (last - prev) / prev * 100
        return tone_from(chg)
    except Exception:
        return {"label": "Unknown", "change": None,
                "mood": "Couldn't read the tape — check QQQ yourself."}


# ============================================================
# Core logic (shared by live + demo)
# ============================================================
def tone_from(chg):
    if chg is None:
        return {"label": "Unknown", "change": None, "mood": "Check QQQ yourself."}
    if chg > 0.4:
        return {"label": "Bullish / risk-on", "change": chg,
                "mood": "Favor long breakouts, normal size."}
    if chg < -0.4:
        return {"label": "Weak / risk-off", "change": chg,
                "mood": "Tighten up. Smaller size, be selective, respect failed gappers."}
    return {"label": "Flat / mixed", "change": chg,
            "mood": "No edge from the tape. Trade only A+ setups."}


def is_junk(row):
    if row["quote_type"] and row["quote_type"] != "EQUITY":
        return True                      # ETF, MUTUALFUND, etc.
    up = (row["name"] + " " + (row["symbol"] or "")).upper()
    if any(kw in up for kw in JUNK_KEYWORDS):
        return True
    sym = row["symbol"] or ""
    if len(sym) >= 5 and sym[-1] in "WRU":   # warrants / rights / units
        return True
    return False


def passes(row, cfg):
    p, c, dv, rv, mc = (row["price"], row["change"], row["dollar_vol"],
                        row["rvol"], row["market_cap"])
    if p is None or c is None:
        return False
    if is_junk(row):
        return False
    if not (cfg["min_price"] <= p <= cfg["max_price"]):
        return False
    if abs(c) < cfg["min_change_pct"]:
        return False
    if rv is not None and rv < cfg["min_rel_volume"]:
        return False
    if dv is not None and dv < cfg["min_dollar_volume"]:
        return False
    if cfg["max_market_cap"] and mc and mc > cfg["max_market_cap"]:
        return False
    return True


def score(row):
    """Momentum weighted by how unusual today's volume is. RVol is king."""
    rv = row["rvol"] or 1.0
    return round(abs(row["change"]) * math.log10((rv * 10) + 1), 1)


def read_of(row):
    c = row["change"]; rv = row["rvol"] or 0; gap = row.get("gap")
    if rv and rv >= 5:
        vtag = "huge relative volume"
    elif rv and rv >= 2:
        vtag = "strong volume"
    else:
        vtag = "volume present"
    if c >= 0:
        return f"Up {c:.0f}% on {vtag}. Long-watch — wait for a clean setup, don't chase."
    return f"Down {abs(c):.0f}% on {vtag}. Weak — short candidate or avoid; don't catch it."


def build(rows, cfg, live=False):
    rows = [normalize(q) if "regularMarketPrice" in q else q for q in rows]
    kept = [r for r in rows if passes(r, cfg)]
    if not cfg["include_shorts"]:
        kept = [r for r in kept if r["change"] >= 0]
    for r in kept:
        r["score"] = score(r)
    kept.sort(key=lambda r: -r["score"])
    top = kept[: cfg["top_n"]]
    if live and cfg["enrich_levels"]:
        for r in top:
            r.update(enrich(r["symbol"]))
    return top


# ============================================================
# Output
# ============================================================
def print_report(tone, rows):
    print("\n" + "=" * 70)
    print(f" DAY-TRADING WATCHLIST  |  {dt.datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 70)
    if tone["change"] is not None:
        print(f" Market tone (QQQ): {tone['label']}  ({tone['change']:+.2f}%)")
    print(f"   -> {tone['mood']}")
    print("-" * 70)
    print(f"{'TICKER':8}{'PRICE':>8}{'CHG%':>7}{'RVOL':>7}{'$VOL(M)':>9}  NAME")
    print("-" * 70)
    for r in rows:
        rv = f"{r['rvol']:.1f}" if r["rvol"] else "-"
        dv = f"{r['dollar_vol']/1e6:.0f}" if r["dollar_vol"] else "-"
        print(f"{r['symbol']:8}{r['price']:>8.2f}{r['change']:>7.1f}"
              f"{rv:>7}{dv:>9}  {r['name'][:28]}")
        print(f"        {read_of(r)}")
    print("=" * 70 + "\n")


def write_html(tone, rows, path):
    tcol = "#0ca30c" if (tone["change"] or 0) >= 0 else "#d03b3b"
    trs = ""
    for r in rows:
        cc = "#0ca30c" if r["change"] >= 0 else "#d03b3b"
        rv = f"{r['rvol']:.1f}x" if r["rvol"] else "&mdash;"
        dv = f"${r['dollar_vol']/1e6:.0f}M" if r["dollar_vol"] else "&mdash;"
        gap = f"{r['gap']:+.0f}%" if r.get("gap") is not None else "&mdash;"
        rng = (f"{r['day_low']:.2f}&ndash;{r['day_high']:.2f}"
               if r.get("day_high") else "&mdash;")
        trs += (f"<tr><td class='t'>{r['symbol']}</td>"
                f"<td>${r['price']:.2f}</td>"
                f"<td style='color:{cc}'>{r['change']:+.1f}%</td>"
                f"<td>{rv}</td><td>{dv}</td><td>{gap}</td><td>{rng}</td>"
                f"<td class='n'>{r['name'][:30]}</td>"
                f"<td class='rd'>{read_of(r)}</td></tr>\n")
    tone_txt = (f"{tone['label']} ({tone['change']:+.2f}%)"
                if tone["change"] is not None else tone["label"])
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Day-Trading Watchlist</title><style>
body{{font-family:Arial,Helvetica,sans-serif;max-width:1050px;margin:24px auto;padding:0 16px;color:#1a1a1a}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#666;font-size:13px;margin-bottom:16px}}
.tone{{padding:10px 14px;border-radius:8px;background:#f3f4f6;margin-bottom:20px}}
.tone b{{color:{tcol}}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{text-align:left;padding:7px 9px;border-bottom:1px solid #e5e7eb;white-space:nowrap}}
th{{background:#1f3a5f;color:#fff;font-size:11px}}
.t{{font-weight:bold}} .n{{color:#555}} .rd{{color:#444;white-space:normal;min-width:230px}}
</style></head><body>
<h1>Day-Trading Watchlist</h1>
<div class="sub">Generated {dt.datetime.now():%A %Y-%m-%d %H:%M} &middot; small/mid-cap momentum</div>
<div class="tone">Market tone (QQQ): <b>{tone_txt}</b><br><span style="color:#555">{tone['mood']}</span></div>
<table><tr><th>Ticker</th><th>Price</th><th>Chg</th><th>RVol</th><th>$Vol</th>
<th>Gap</th><th>Day range</th><th>Name</th><th>The read</th></tr>
{trs}</table>
<p style="color:#999;font-size:12px;margin-top:16px">
A list of names to STUDY, not signals to buy. Do your own chart work: mark your levels,
wait for the setup, size by risk. Re-run every day. Not financial advice.</p>
</body></html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "price", "change_pct", "rvol", "dollar_volume",
                    "gap_pct", "day_low", "day_high", "adr_pct", "name"])
        for r in rows:
            w.writerow([r["symbol"], r["price"], round(r["change"], 1),
                        round(r["rvol"], 2) if r["rvol"] else "",
                        int(r["dollar_vol"]) if r["dollar_vol"] else "",
                        round(r["gap"], 1) if r.get("gap") is not None else "",
                        r.get("day_low", ""), r.get("day_high", ""),
                        round(r["adr_pct"], 1) if r.get("adr_pct") else "",
                        r["name"]])


# ============================================================
# Demo data (Yahoo-shaped) so you can see it work with no network
# ============================================================
DEMO_QUOTES = [
    {"symbol": "BIYA", "shortName": "Baiya International", "regularMarketPrice": 6.44,
     "regularMarketChangePercent": 54.4, "regularMarketVolume": 30_000_000,
     "averageDailyVolume3Month": 2_100_000, "marketCap": 180_000_000, "quoteType": "EQUITY"},
    {"symbol": "ENTX", "shortName": "Entera Bio", "regularMarketPrice": 3.26,
     "regularMarketChangePercent": -16.8, "regularMarketVolume": 5_300_000,
     "averageDailyVolume3Month": 900_000, "marketCap": 120_000_000, "quoteType": "EQUITY"},
    {"symbol": "NCTY", "shortName": "The9 Ltd", "regularMarketPrice": 4.62,
     "regularMarketChangePercent": 1.8, "regularMarketVolume": 306_000,
     "averageDailyVolume3Month": 400_000, "marketCap": 90_000_000, "quoteType": "EQUITY"},
    {"symbol": "SOXL", "shortName": "Direxion Semi Bull 3X ETF", "regularMarketPrice": 40.0,
     "regularMarketChangePercent": 8.0, "regularMarketVolume": 80_000_000,
     "averageDailyVolume3Month": 70_000_000, "marketCap": 8_000_000_000, "quoteType": "ETF"},
    {"symbol": "AVGO", "shortName": "Broadcom Inc", "regularMarketPrice": 383.6,
     "regularMarketChangePercent": 6.0, "regularMarketVolume": 20_000_000,
     "averageDailyVolume3Month": 18_000_000, "marketCap": 1_700_000_000_000, "quoteType": "EQUITY"},
    {"symbol": "WLDS", "shortName": "Wearable Devices", "regularMarketPrice": 3.83,
     "regularMarketChangePercent": 20.4, "regularMarketVolume": 12_000_000,
     "averageDailyVolume3Month": 1_500_000, "marketCap": 60_000_000, "quoteType": "EQUITY"},
    {"symbol": "PSQH", "shortName": "PSQ Holdings", "regularMarketPrice": 3.70,
     "regularMarketChangePercent": 20.1, "regularMarketVolume": 9_000_000,
     "averageDailyVolume3Month": 2_000_000, "marketCap": 100_000_000, "quoteType": "EQUITY"},
    {"symbol": "PRLD", "shortName": "Prelude Therapeutics", "regularMarketPrice": 4.64,
     "regularMarketChangePercent": 19.3, "regularMarketVolume": 4_500_000,
     "averageDailyVolume3Month": 1_100_000, "marketCap": 250_000_000, "quoteType": "EQUITY"},
    {"symbol": "LVWRW", "shortName": "LiveWire Warrant", "regularMarketPrice": 0.05,
     "regularMarketChangePercent": 122.0, "regularMarketVolume": 1_600_000,
     "averageDailyVolume3Month": 200_000, "marketCap": None, "quoteType": "EQUITY"},
    {"symbol": "TTGT", "shortName": "TechTarget Inc", "regularMarketPrice": 4.47,
     "regularMarketChangePercent": 17.6, "regularMarketVolume": 3_000_000,
     "averageDailyVolume3Month": 900_000, "marketCap": 130_000_000, "quoteType": "EQUITY"},
]


def run_demo(cfg):
    tone = tone_from(-0.97)
    rows = build([normalize(q) for q in DEMO_QUOTES], cfg, live=False)
    return tone, rows


def run_live(cfg):
    try:
        import yfinance  # noqa
    except ImportError:
        sys.exit("Needs yfinance. Run: pip install yfinance pandas")
    screens = list(cfg["screeners_long"])
    if cfg["include_shorts"]:
        screens += cfg["screeners_short"]
    print("Pulling movers from Yahoo screeners...")
    raw = get_screener_rows(screens)
    print(f"Fetched {len(raw)} candidate names. Filtering + ranking...")
    tone = get_market_tone(cfg["market_tone_symbol"])
    rows = build(raw, cfg, live=True)
    return tone, rows


def main():
    ap = argparse.ArgumentParser(description="Daily day-trading watchlist generator")
    ap.add_argument("--demo", action="store_true", help="Run offline on sample data")
    ap.add_argument("--shorts", action="store_true", help="Include short candidates")
    ap.add_argument("--max-price", type=float)
    ap.add_argument("--min-change", type=float)
    ap.add_argument("--top", type=int)
    ap.add_argument("--publish", action="store_true",
                    help="Also write docs/index.html for GitHub Pages")
    a = ap.parse_args()

    cfg = dict(CONFIG)
    if a.shorts: cfg["include_shorts"] = True
    if a.max_price is not None: cfg["max_price"] = a.max_price
    if a.min_change is not None: cfg["min_change_pct"] = a.min_change
    if a.top is not None: cfg["top_n"] = a.top

    tone, rows = run_demo(cfg) if a.demo else run_live(cfg)

    if not rows:
        print("\nNo names cleared the filters today. That happens on quiet days — "
              "loosen min_change/min_rel_volume in CONFIG, or just sit out.\n")
    print_report(tone, rows)

    # Resolve the archive folder against this script, not the shell's cwd —
    # run_daily.bat runs from the repo root, which would otherwise scatter a
    # second watchlists/ folder there.
    out_dir = cfg["out_dir"]
    if not os.path.isabs(out_dir):
        out_dir = os.path.join(HERE, out_dir)
    os.makedirs(out_dir, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d")
    hp = os.path.join(out_dir, f"watchlist_{stamp}.html")
    cp = os.path.join(out_dir, f"watchlist_{stamp}.csv")
    write_html(tone, rows, hp)
    write_csv(rows, cp)
    print(f"Saved {hp} and {cp}. Open the HTML in your browser.\n")

    if a.publish:
        publish_to_docs(tone, rows)


if __name__ == "__main__":
    main()
