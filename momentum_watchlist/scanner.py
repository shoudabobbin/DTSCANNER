#!/usr/bin/env python3
"""
Momentum Day-Trading Watchlist  —  live, self-hosting scanner
=============================================================
Builds a good-looking morning watchlist of in-play small/mid-cap movers and
(optionally) publishes it to GitHub Pages so you can pull it up on your phone.

- Data: Yahoo Finance via yfinance. No API key, no request limit, free.
- Runs 24/7: rescans every few minutes while the US market is open, idles
  nights and weekends.
- It does NOT trade or predict. It hands you a list to study. You trade.

QUICK START
-----------
    pip install -r requirements.txt
    python scanner.py --demo         # offline sample -> writes docs/index.html
    python scanner.py --once         # one live scan
    python scanner.py --loop         # run forever, rescan during market hours
    python scanner.py --loop --publish   # ...and push to GitHub Pages each time

See PUBLISHING.md for the one-time GitHub Pages setup (5 minutes).
"""

import os
import sys
import csv
import json
import math
import time
import shutil
import argparse
import subprocess
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# CONFIG  —  the whole control panel
# ============================================================
CONFIG = {
    "min_price": 1.0,
    "max_price": 20.0,
    "min_change_pct": 10.0,       # A-list: up (or down) at least this % on the day
    "min_rel_volume": 5.0,        # A-list: at least this x normal volume, TIME-OF-DAY ADJUSTED
    "require_news": False,        # True = only tag IN PLAY names that have a fresh news catalyst
    "min_dollar_volume": 1_000_000,  # liquidity floor, on AVERAGE daily $ volume (time-of-day proof)
    "max_market_cap": 3_000_000_000,   # skip megacap name brands (None to disable)

    # Never show an empty page: always fill up to this many of the day's biggest
    # movers, even ones that don't yet clear the "in play" bar (tagged MOVER).
    "min_names": 12,

    # Day-trading quality: to be "in play" a name must still be MOVING intraday,
    # not just gapped-and-flat. It needs to have moved at least this % since the
    # OPEN in its direction (or be pinned near the day's extreme). Gap-and-die
    # names get tagged MOVER and sink in the ranking.
    "min_since_open_pct": 1.0,

    "screeners_long":  ["day_gainers", "small_cap_gainers",
                        "most_actives", "aggressive_small_caps"],
    "screeners_short": ["day_losers"],
    "include_shorts": True,       # show both sides; tag each row

    "top_n": 24,
    "market_tone_symbol": "QQQ",

    # sizing calculator defaults (user can change them live on the page)
    "default_account": 2500,
    "default_risk_pct": 1.0,
    "default_max_position_pct": 25,

    # loop / hosting. 10 min keeps GitHub Pages builds under its ~10/hour limit;
    # each publish is a real deploy, so faster than this can get throttled/stale.
    "refresh_minutes": 10,
    "market_open":  (9, 5),       # ET hh,mm  (a little before the bell for pre-market)
    "market_close": (16, 5),      # ET hh,mm
    "publish_branch": "gh-pages",
    "out_dir": os.path.join(HERE, "docs"),
}

JUNK_KEYWORDS = ("ETF", "FUND", "TRUST", "ETN", "2X", "3X", "BULL", "BEAR",
                 "LEVERAGED", "ACQUISITION", "WARRANT", "RIGHT", "UNIT",
                 "DIREXION", "PROSHARES", "ISHARES", "SPDR")


# ============================================================
# Data layer (network) — only part that hits Yahoo
# ============================================================
def get_screener_rows(names):
    import yfinance as yf
    seen = {}
    for name in names:
        try:
            res = yf.screen(name, count=100)
            quotes = res.get("quotes", []) if isinstance(res, dict) else []
        except Exception as e:
            print(f"  ! screener '{name}' failed: {str(e)[:100]}")
            continue
        for q in quotes:
            if q.get("symbol"):
                seen[q["symbol"]] = q
        print(f"  {name}: {len(quotes)}")
    return list(seen.values())


def normalize(q):
    price = q.get("regularMarketPrice")
    vol = q.get("regularMarketVolume")
    avg = q.get("averageDailyVolume3Month") or q.get("averageDailyVolume10Day")
    op = q.get("regularMarketOpen")
    dh = q.get("regularMarketDayHigh")
    dl = q.get("regularMarketDayLow")
    pc = q.get("regularMarketPreviousClose")
    rng = (dh - dl) if (dh is not None and dl is not None) else None
    return {
        "symbol": q.get("symbol"),
        "name": q.get("shortName") or q.get("longName") or "",
        "price": price,
        "change": q.get("regularMarketChangePercent"),   # vs prior close = the gap
        "volume": vol,
        "rvol": (vol / avg) if (vol and avg) else None,
        "dollar_vol": (price * vol) if (price and vol) else None,      # today so far
        "avg_dollar_vol": (price * avg) if (price and avg) else None,  # normal day (stable)
        "market_cap": q.get("marketCap"),
        "quote_type": (q.get("quoteType") or "").upper(),
        "open": op, "day_high": dh, "day_low": dl,
        "gap": ((op - pc) / pc * 100) if (op and pc) else None,        # overnight jump
        # intraday drive since the OPEN — separates a live mover from a gap-and-die
        "since_open": ((price - op) / op * 100) if (price and op) else None,
        "range_pos": ((price - dl) / rng) if (rng and rng > 0 and price is not None) else None,
    }


def enrich(sym, have=None):
    """Adds 14-day ADR% (not in the quote), and backfills day high/low only if
    the screener quote didn't already provide them."""
    import yfinance as yf
    have = have or {}
    try:
        h = yf.Ticker(sym).history(period="1mo", interval="1d")
        if len(h) < 2:
            return {}
        adr = float(((h["High"] - h["Low"]) / h["Close"]).tail(14).mean() * 100)
        out = {"adr_pct": round(adr, 1)}
        if have.get("day_high") is None or have.get("day_low") is None:
            today = h.iloc[-1]
            out["day_high"] = float(today["High"]); out["day_low"] = float(today["Low"])
        return out
    except Exception:
        return {}


def get_market_tone(sym):
    import yfinance as yf
    try:
        h = yf.Ticker(sym).history(period="5d", interval="1d")
        chg = (float(h["Close"].iloc[-1]) - float(h["Close"].iloc[-2])) / float(h["Close"].iloc[-2]) * 100
        return tone_from(chg)
    except Exception:
        return {"label": "Unknown", "change": None, "cls": "flat",
                "mood": "Couldn't read the tape — check QQQ yourself."}


# ============================================================
# Core logic
# ============================================================
def tone_from(chg):
    if chg is None:
        return {"label": "Unknown", "change": None, "cls": "flat", "mood": "Check QQQ."}
    if chg > 0.4:
        return {"label": "Bull", "change": chg, "cls": "bull",
                "mood": "Favor long breakouts, normal size."}
    if chg < -0.4:
        return {"label": "Weak", "change": chg, "cls": "bear",
                "mood": "Tighten up. Smaller size, be selective, respect failed gappers."}
    return {"label": "Flat", "change": chg, "cls": "flat",
            "mood": "No edge from the tape. Trade only A+ setups."}


def is_junk(r):
    if r["quote_type"] and r["quote_type"] != "EQUITY":
        return True
    up = (r["name"] + " " + (r["symbol"] or "")).upper()
    if any(k in up for k in JUNK_KEYWORDS):
        return True
    s = r["symbol"] or ""
    return len(s) >= 5 and s[-1] in "WRU"


def passes(r, c):
    """Eligible universe: right price, liquid on a NORMAL day, not junk/megacap.

    % change and relative volume are deliberately NOT hard gates here. Early in
    the session only part of the day's volume has traded, so rvol (today vs a
    full-day average) reads artificially low and today's $-volume is tiny —
    that is exactly what made the 9:57am list come up empty. Those two signals
    drive the IN PLAY flag and the ranking instead (see is_in_play / build_rows).
    """
    p, mc = r["price"], r["market_cap"]
    if p is None or r["change"] is None or is_junk(r):
        return False
    if not (c["min_price"] <= p <= c["max_price"]):
        return False
    # liquidity on AVERAGE daily $ volume so it doesn't collapse mid-morning
    liq = r.get("avg_dollar_vol") or r.get("dollar_vol")
    if liq is not None and liq < c["min_dollar_volume"]:
        return False
    if c["max_market_cap"] and mc and mc > c["max_market_cap"]:
        return False
    return True


# Rough cumulative share of a normal day's volume traded by each minute after the
# 9:30 open (U-shaped, front-loaded). Lets "5x relative volume" mean something at
# 9:45am — by 10:00 a stock has only had time to trade ~17% of a full day.
_VOL_CURVE = [(0, 0.02), (15, 0.09), (30, 0.17), (60, 0.27), (90, 0.35),
              (120, 0.42), (180, 0.53), (240, 0.62), (300, 0.72), (360, 0.86), (390, 1.0)]


def _expected_vol_fraction(mins):
    if mins <= 0:
        return _VOL_CURVE[0][1]
    if mins >= 390:
        return 1.0
    for i in range(1, len(_VOL_CURVE)):
        m0, f0 = _VOL_CURVE[i - 1]; m1, f1 = _VOL_CURVE[i]
        if mins <= m1:
            return f0 + (f1 - f0) * (mins - m0) / (m1 - m0)
    return 1.0


def _adj_rvol(r, mins):
    """Relative volume put on a full-day pace. rvol is today-so-far vs a full-day
    average, which reads low intraday; dividing by the expected fraction of the
    day elapsed turns it into 'on pace for Nx a normal day'."""
    rv = r.get("rvol")
    if rv is None:
        return None
    return rv / (_expected_vol_fraction(mins) or 1.0)


def fetch_news(sym):
    """Most recent headline for a ticker (best-effort). has_news = something ran
    in the last ~48h. yfinance's news schema varies by version, so handle both."""
    import yfinance as yf
    try:
        items = yf.Ticker(sym).news or []
    except Exception:
        return {"has_news": False, "headline": None}
    now = dt.datetime.now(dt.timezone.utc)
    best = None; best_ts = -1.0
    for it in items:
        if not isinstance(it, dict):
            continue
        title = ts = None
        c = it.get("content") if isinstance(it.get("content"), dict) else None
        if c:
            title = c.get("title")
            pd = c.get("pubDate") or c.get("displayTime")
            if pd:
                try:
                    ts = dt.datetime.fromisoformat(str(pd).replace("Z", "+00:00"))
                except Exception:
                    ts = None
        if not title:
            title = it.get("title")
            ep = it.get("providerPublishTime")
            if ep:
                try:
                    ts = dt.datetime.fromtimestamp(ep, dt.timezone.utc)
                except Exception:
                    ts = None
        if not title:
            continue
        tsv = ts.timestamp() if ts else 0.0
        if tsv > best_ts:
            best_ts = tsv
            age_h = (now - ts).total_seconds() / 3600 if ts else 999
            best = {"headline": str(title)[:95], "age_h": age_h}
    if not best:
        return {"has_news": False, "headline": None}
    return {"has_news": best["age_h"] <= 48, "headline": best["headline"]}


def _intraday_drive(r):
    """% moved since the OPEN, signed by trade direction. Positive = still pushing
    the way it gapped; <= 0 = gapped then stalled or faded (a gap-and-die)."""
    so = r.get("since_open")
    if so is None:
        return 0.0
    return so if (r["change"] or 0) >= 0 else -so


def _extension(r):
    """Where price sits in today's range, in the trade direction. 1 = at the
    extreme (near highs for a long / near lows for a short)."""
    rp = r.get("range_pos")
    if rp is None:
        return 0.5
    return rp if (r["change"] or 0) >= 0 else (1 - rp)


def is_in_play(r, c):
    """The A-list. Your momentum spec, all required:
      1. up/down >= min_change_pct on the day
      2. time-adjusted relative volume >= min_rel_volume (on pace for Nx a normal day)
      3. still moving intraday (drive since the open or pinned at the day's extreme)
      4. a fresh news catalyst — only if require_news is on
    Anything that misses one is still shown, tagged MOVER."""
    if abs(r["change"]) < c["min_change_pct"]:
        return False
    arv = r.get("adj_rvol")
    if arv is not None and arv < c["min_rel_volume"]:
        return False
    if c.get("require_news") and not r.get("has_news"):
        return False
    if r.get("since_open") is None and r.get("range_pos") is None:
        return True   # no intraday data — don't penalize
    return (_intraday_drive(r) >= c.get("min_since_open_pct", 1.0)
            or _extension(r) >= 0.66)


def raw_score(r):
    """Rank by intraday action: continuation since the open + being near the day's
    extreme + how heavy the (time-adjusted) volume is, with a nudge for a catalyst."""
    drive = max(_intraday_drive(r), 0.0)
    ext = _extension(r)                       # 0..1
    arv = r.get("adj_rvol") or r.get("rvol") or 1.0
    vol = math.log10(max(arv, 0.1) * 10 + 1)
    news = 1.15 if r.get("has_news") else 1.0
    return (drive * 2.0 + ext * 8.0 + abs(r["change"] or 0) * 0.3) * vol * news


def suggested_stop_pct(r):
    adr = r.get("adr_pct")
    base = adr * 0.5 if adr else 4.0
    return round(min(max(base, 2.0), 10.0), 1)


def build_rows(raw, cfg, live=False):
    mins = cfg.get("_mins_open", 390)
    rows = [normalize(q) for q in raw]
    elig = [r for r in rows if passes(r, cfg)]
    if not cfg["include_shorts"]:
        elig = [r for r in elig if r["change"] >= 0]
    # time-adjusted relative volume is available from the quote alone
    for r in elig:
        r["adj_rvol"] = _adj_rvol(r, mins)
        r["_s"] = raw_score(r)                       # preliminary (no news yet)
        r["_inplay"] = is_in_play(r, cfg)
    elig.sort(key=lambda r: (not r["_inplay"], -r["_s"]))
    kept = elig[: max(cfg["top_n"], cfg.get("min_names", 0))]

    if live:
        for r in kept:
            r.update(enrich(r["symbol"], r))         # ADR + level backfill
            r.update(fetch_news(r["symbol"]))        # catalyst
            r["_s"] = raw_score(r)                    # re-score WITH news
            r["_inplay"] = is_in_play(r, cfg)         # re-evaluate WITH news
        kept.sort(key=lambda r: (not r["_inplay"], -r["_s"]))

    if cfg.get("require_news"):
        kept = [r for r in kept if r.get("has_news")] or kept  # never blank the page

    if kept:
        lo = min(r["_s"] for r in kept); hi = max(r["_s"] for r in kept)
        span = (hi - lo) or 1
    out = []
    for r in kept:
        r["stop_pct"] = suggested_stop_pct(r)
        out.append({
            "symbol": r["symbol"], "name": r["name"][:34],
            "dir": "long" if r["change"] >= 0 else "short",
            "in_play": bool(r["_inplay"]),
            "has_news": bool(r.get("has_news")),
            "headline": r.get("headline"),
            "price": round(r["price"], 2),
            "change": round(r["change"], 1),
            "rvol": round(r["rvol"], 1) if r["rvol"] else None,
            "adj_rvol": round(r["adj_rvol"], 1) if r.get("adj_rvol") is not None else None,
            "dollar_vol": int(r["dollar_vol"]) if r["dollar_vol"] else None,
            "gap": round(r["gap"], 1) if r.get("gap") is not None else None,
            "since_open": round(r["since_open"], 1) if r.get("since_open") is not None else None,
            "range_pos": round(r["range_pos"], 2) if r.get("range_pos") is not None else None,
            "day_high": round(r["day_high"], 2) if r.get("day_high") else None,
            "day_low": round(r["day_low"], 2) if r.get("day_low") else None,
            "adr_pct": r.get("adr_pct"),
            "stop_pct": r["stop_pct"],
            "rank": round(60 + 39 * (r["_s"] - lo) / span, 1),
        })
    return out


# ============================================================
# HTML  (self-contained; all interactivity is client-side JS)
# ============================================================
TEMPLATE = r"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="__REFRESH__">
<title>Momentum Watchlist</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#15202b;--mut:#6b7480;--line:#e6e8ec;
--green:#0ca35a;--greenbg:#e8f6ee;--red:#d83a45;--redbg:#fbe9ea;--blue:#1f3a5f;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:14px}
.wrap{max-width:1180px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:0 0 2px}
.sub{color:var(--mut);font-size:12px;margin-bottom:10px}
.badges{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.badge{font-size:12px;padding:3px 10px;border-radius:20px;background:#eef0f3;color:#475060}
.badge.bull{background:var(--greenbg);color:var(--green)}
.badge.bear{background:var(--redbg);color:var(--red)}
.note{background:#fff7e6;border:1px solid #ffe2a8;color:#7a5a10;font-size:12px;
padding:8px 12px;border-radius:8px;margin-bottom:12px}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;background:var(--card);
border:1px solid var(--line);border-radius:10px;padding:10px;margin-bottom:12px}
.seg{display:flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.seg button{border:0;background:#fff;padding:6px 12px;font-size:13px;cursor:pointer;color:var(--mut)}
.seg button.on{background:var(--blue);color:#fff}
select,input{border:1px solid var(--line);border-radius:8px;padding:6px 8px;font-size:13px;background:#fff;color:var(--ink)}
.size input{width:70px}
.size label{font-size:11px;color:var(--mut);margin-right:3px}
.spacer{flex:1}
button.copy{border:1px solid var(--line);background:#fff;border-radius:8px;padding:6px 10px;font-size:12px;cursor:pointer;color:var(--blue)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--mut);
border-radius:12px;padding:12px}
.card.long{border-left-color:var(--green)} .card.short{border-left-color:var(--red)}
.chd{display:flex;justify-content:space-between;align-items:flex-start}
.tk{font-size:17px;font-weight:700}
.tag{font-size:10px;font-weight:700;padding:2px 6px;border-radius:5px;margin-left:6px;vertical-align:2px}
.tag.long{background:var(--greenbg);color:var(--green)} .tag.short{background:var(--redbg);color:var(--red)}
.tag.play{background:var(--greenbg);color:var(--green)} .tag.mover{background:#eef0f3;color:var(--mut)}
.tag.news{background:#fff3d6;color:#8a6d00}
.why .hl{color:var(--blue)}
.rk{font-size:16px;font-weight:700;text-align:right;line-height:1}
.rk span{font-size:9px;color:var(--mut);font-weight:500;letter-spacing:.05em}
.why{font-size:12px;color:var(--mut);margin:3px 0 8px}
.rangebar{height:6px;background:#eef0f3;border-radius:4px;position:relative;margin:10px 2px 12px}
.rangebar i{position:absolute;top:-3px;width:2px;height:12px;background:var(--blue)}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:8px 6px}
.st .k{font-size:9px;color:var(--mut);letter-spacing:.04em}
.st .v{font-size:13px;font-weight:600}
.st .v.g{color:var(--green)} .st .v.r{color:var(--red)}
.size-row{margin-top:10px;padding-top:10px;border-top:1px dashed var(--line);
display:grid;grid-template-columns:repeat(4,1fr);gap:8px 6px}
table{width:100%;border-collapse:collapse;font-size:13px;background:var(--card);border-radius:10px;overflow:hidden}
th,td{padding:8px 9px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{background:var(--blue);color:#fff;font-size:11px;font-weight:600}
.hide{display:none}
.foot{color:var(--mut);font-size:11px;margin-top:14px;line-height:1.6}
@media(max-width:520px){.grid{grid-template-columns:1fr}.wrap{padding:10px}}
</style></head><body><div class="wrap">
<h1>Momentum Watchlist</h1>
<div class="sub" id="sub"></div>
<div class="badges" id="badges"></div>
<div class="note" id="note"></div>

<div class="bar">
  <div class="seg" id="side"><button data-v="all" class="on">All</button>
    <button data-v="long">Long</button><button data-v="short">Short</button></div>
  <div class="seg" id="aplus"><button data-v="off" class="on">All names</button>
    <button data-v="on">A+ only</button></div>
  <div class="seg" id="layout"><button data-v="cards" class="on">Cards</button>
    <button data-v="table">Table</button></div>
  <select id="sort">
    <option value="rank">Sort: Score</option>
    <option value="change">Sort: % Change</option>
    <option value="rvol">Sort: Rel Volume</option>
    <option value="dollar_vol">Sort: $ Volume</option>
    <option value="price">Sort: Price</option></select>
  <input id="filter" placeholder="Filter ticker...">
  <div class="spacer"></div>
  <div class="size"><label>Account $</label><input id="acct" type="number"></div>
  <div class="size"><label>Risk %</label><input id="risk" type="number" step="0.1"></div>
  <div class="size"><label>Max pos %</label><input id="maxpos" type="number"></div>
</div>
<div class="bar" style="margin-top:-6px">
  <span style="font-size:12px;color:var(--mut)">Copy symbols to ThinkorSwim:</span>
  <button class="copy" onclick="copySy('all')">All</button>
  <button class="copy" onclick="copySy('long')">Longs</button>
  <button class="copy" onclick="copySy('short')">Shorts</button>
  <span id="sizenote" style="font-size:12px;color:var(--mut)"></span>
</div>

<div id="grid" class="grid"></div>
<div id="tablewrap" class="hide"></div>

<div class="foot">
<b>IN PLAY</b> = your full momentum spec: up/down 10%+, on pace for 5x+ normal volume, still moving intraday, and
(when required) a news catalyst. <b>MOVER</b> = a mover that misses one of those. Hit <b>A+ only</b> to see just the
IN PLAY names. <b>REL VOL</b> is time-adjusted — "on pace for Nx a normal day," so 5x means something at 9:45am too.
<b>SINCE OPEN</b> tells a live mover from a gap-and-die. <b>NEWS</b> shows the latest headline (free-source, best-effort —
it can miss or lag, and doesn't prove the news is the cause). Score orders THIS list on THIS refresh — not a
prediction. Shares/stop are risk-based suggestions; set your real stop on the chart. Names to STUDY, not signals to buy. Not financial advice.
</div></div>

<script>
const DATA = __DATA__;
const META = __META__;
const $ = s => document.querySelector(s);
const S = {
  side: localStorage.getItem('side') || 'all',
  layout: localStorage.getItem('layout') || 'cards',
  sort: localStorage.getItem('sort') || 'rank',
  aplus: localStorage.getItem('aplus')==='on',
  filter: '',
  acct: +localStorage.getItem('acct') || META.acct,
  risk: +localStorage.getItem('risk') || META.risk,
  maxpos: +localStorage.getItem('maxpos') || META.maxpos,
};
const money = n => n==null? '—' : '$'+Number(n).toLocaleString();
const mCap = n => n==null? '—' : '$'+(n/1e6).toFixed(0)+'M';

function sized(r){
  const riskD = S.acct * S.risk/100;
  const stopPer = r.price * r.stop_pct/100;
  let sh = stopPer>0 ? Math.floor(riskD/stopPer) : 0;
  const cap = S.acct * S.maxpos/100;
  if(sh*r.price > cap) sh = Math.floor(cap/r.price);
  if(sh<0) sh=0;
  return {shares: sh, pos: sh*r.price};
}
function rows(){
  let a = DATA.filter(r => S.side==='all' || r.dir===S.side);
  if(S.aplus) a = a.filter(r => r.in_play);
  if(S.filter) a = a.filter(r => r.symbol.toLowerCase().includes(S.filter.toLowerCase()));
  a.sort((x,y)=> (y[S.sort]??-1e9) - (x[S.sort]??-1e9));
  return a;
}
function rangeMark(r){
  if(r.day_low==null||r.day_high==null||r.day_high<=r.day_low) return '';
  const p = Math.max(0,Math.min(100,(r.price-r.day_low)/(r.day_high-r.day_low)*100));
  return `<div class="rangebar"><i style="left:${p}%"></i></div>`;
}
function card(r){
  const z = sized(r);
  const cc = r.change>=0?'g':'r';
  return `<div class="card ${r.dir}">
   <div class="chd"><div><span class="tk">${r.symbol}</span>
     <span class="tag ${r.dir}">${r.dir.toUpperCase()}</span>
     <span class="tag ${r.in_play?'play':'mover'}">${r.in_play?'IN PLAY':'MOVER'}</span>
     ${r.has_news?'<span class="tag news">NEWS</span>':''}</div>
     <div class="rk">${r.rank}<br><span>SCORE</span></div></div>
   <div class="why">${r.name}${r.headline?' &middot; <span class="hl">'+r.headline+'</span>':''}</div>
   ${rangeMark(r)}
   <div class="stats">
     <div class="st"><div class="k">PRICE</div><div class="v">$${r.price.toFixed(2)}</div></div>
     <div class="st"><div class="k">CHG (GAP)</div><div class="v ${cc}">${r.change>=0?'+':''}${r.change}%</div></div>
     <div class="st"><div class="k">SINCE OPEN</div><div class="v ${r.since_open==null?'':((r.since_open>=0)===(r.dir==='long')?'g':'r')}">${r.since_open==null?'—':(r.since_open>=0?'+':'')+r.since_open+'%'}</div></div>
     <div class="st"><div class="k">REL VOL</div><div class="v">${r.adj_rvol??'—'}${r.adj_rvol?'x':''}</div></div>
     <div class="st"><div class="k">$VOL</div><div class="v">${r.dollar_vol?'$'+(r.dollar_vol/1e6).toFixed(0)+'M':'—'}</div></div>
     <div class="st"><div class="k">DAY LOW</div><div class="v">${r.day_low?'$'+r.day_low:'—'}</div></div>
     <div class="st"><div class="k">DAY HIGH</div><div class="v">${r.day_high?'$'+r.day_high:'—'}</div></div>
     <div class="st"><div class="k">ADR</div><div class="v">${r.adr_pct?r.adr_pct+'%':'—'}</div></div>
   </div>
   <div class="size-row">
     <div class="st"><div class="k">SHARES</div><div class="v">${z.shares.toLocaleString()}</div></div>
     <div class="st"><div class="k">POSITION</div><div class="v">${money(Math.round(z.pos))}</div></div>
     <div class="st"><div class="k">STOP ≈</div><div class="v">${r.stop_pct}%</div></div>
     <div class="st"><div class="k">RISK</div><div class="v">${money(Math.round(S.acct*S.risk/100))}</div></div>
   </div></div>`;
}
function table(list){
  let h = `<table><tr><th>Ticker</th><th>Dir</th><th>Price</th><th>Chg (gap)</th><th>Since open</th><th>Rel Vol</th>
   <th>$Vol</th><th>Range</th><th>ADR</th><th>Shares</th><th>Score</th></tr>`;
  for(const r of list){ const z=sized(r);
    const soc = r.since_open==null?'var(--mut)':(((r.since_open>=0)===(r.dir==='long'))?'var(--green)':'var(--red)');
    h+=`<tr><td>${r.symbol}${r.has_news?' <span title="'+(r.headline||'news')+'" style="color:var(--green)">&#9679;</span>':''}</td><td>${r.dir}</td><td>$${r.price.toFixed(2)}</td>
     <td style="color:${r.change>=0?'var(--green)':'var(--red)'}">${r.change>=0?'+':''}${r.change}%</td>
     <td style="color:${soc}">${r.since_open==null?'—':(r.since_open>=0?'+':'')+r.since_open+'%'}</td>
     <td>${r.adj_rvol??'—'}${r.adj_rvol?'x':''}</td><td>${r.dollar_vol?'$'+(r.dollar_vol/1e6).toFixed(0)+'M':'—'}</td>
     <td>${r.day_low&&r.day_high?'$'+r.day_low+'–'+r.day_high:'—'}</td>
     <td>${r.adr_pct?r.adr_pct+'%':'—'}</td><td>${z.shares}</td><td>${r.rank}</td></tr>`; }
  return h+'</table>';
}
function render(){
  const list = rows();
  const nL = DATA.filter(r=>r.dir==='long').length, nS = DATA.filter(r=>r.dir==='short').length;
  const nP = DATA.filter(r=>r.in_play).length;
  $('#sub').textContent = `Updated ${META.generated} · refreshes every ${META.refresh_min} min`;
  const t = META.tone;
  $('#badges').innerHTML =
    `<span class="badge bull">${nP} in play</span>`+
    `<span class="badge">${nL} long</span><span class="badge">${nS} short</span>`+
    `<span class="badge ${t.cls}">market ${t.label}${t.change!=null?' · '+(t.change>=0?'+':'')+t.change.toFixed(2)+'%':''}</span>`+
    `<span class="badge">${META.scanned} scanned</span>`;
  $('#note').textContent = META.note;
  $('#sizenote').textContent = `Risking ${money(Math.round(S.acct*S.risk/100))} per trade · capped at ${S.maxpos}% of account`;
  if(S.layout==='cards'){
    $('#grid').classList.remove('hide'); $('#tablewrap').classList.add('hide');
    $('#grid').innerHTML = list.length? list.map(card).join('') :
      '<div style="color:var(--mut);padding:20px">Nothing eligible right now (pre-market or a very quiet tape). Once a good list has been saved, the page shows it automatically instead of going blank.</div>';
  } else {
    $('#grid').classList.add('hide'); $('#tablewrap').classList.remove('hide');
    $('#tablewrap').innerHTML = table(list);
  }
}
function copySy(side){
  const s = DATA.filter(r=> side==='all'||r.dir===side).map(r=>r.symbol).join(',');
  navigator.clipboard.writeText(s).then(()=>{ $('#sizenote').textContent='Copied '+s.split(',').length+' symbols'; });
}
document.querySelectorAll('#side button').forEach(b=>b.onclick=()=>{
  S.side=b.dataset.v; localStorage.setItem('side',S.side);
  document.querySelectorAll('#side button').forEach(x=>x.classList.toggle('on',x===b)); render();});
document.querySelectorAll('#layout button').forEach(b=>b.onclick=()=>{
  S.layout=b.dataset.v; localStorage.setItem('layout',S.layout);
  document.querySelectorAll('#layout button').forEach(x=>x.classList.toggle('on',x===b)); render();});
document.querySelectorAll('#aplus button').forEach(b=>b.onclick=()=>{
  S.aplus=(b.dataset.v==='on'); localStorage.setItem('aplus',b.dataset.v);
  document.querySelectorAll('#aplus button').forEach(x=>x.classList.toggle('on',x===b)); render();});
$('#sort').value=S.sort; $('#sort').onchange=e=>{S.sort=e.target.value;localStorage.setItem('sort',S.sort);render();};
$('#filter').oninput=e=>{S.filter=e.target.value;render();};
function bindNum(id,key){const el=$('#'+id);el.value=S[key];el.oninput=e=>{S[key]=+e.target.value||0;localStorage.setItem(key,S[key]);render();};}
bindNum('acct','acct');bindNum('risk','risk');bindNum('maxpos','maxpos');
document.querySelectorAll('#side button').forEach(x=>x.classList.toggle('on',x.dataset.v===S.side));
document.querySelectorAll('#layout button').forEach(x=>x.classList.toggle('on',x.dataset.v===S.layout));
document.querySelectorAll('#aplus button').forEach(x=>x.classList.toggle('on',x.dataset.v===(S.aplus?'on':'off')));
render();
</script></body></html>"""


def render_html(rows, tone, cfg, note):
    meta = {
        "generated": dt.datetime.now().strftime("%A %b %d, %I:%M %p"),
        "refresh_min": cfg["refresh_minutes"],
        "tone": {"label": tone["label"], "cls": tone["cls"], "change": tone["change"]},
        "scanned": cfg.get("_scanned", 0),
        "note": note,
        "acct": cfg["default_account"], "risk": cfg["default_risk_pct"],
        "maxpos": cfg["default_max_position_pct"],
    }
    html = (TEMPLATE
            .replace("__DATA__", json.dumps(rows))
            .replace("__META__", json.dumps(meta))
            .replace("__REFRESH__", str(cfg["refresh_minutes"] * 60)))
    return html


def write_outputs(rows, tone, cfg, note):
    os.makedirs(cfg["out_dir"], exist_ok=True)
    with open(os.path.join(cfg["out_dir"], ".nojekyll"), "a"):
        pass
    with open(os.path.join(cfg["out_dir"], "index.html"), "w", encoding="utf-8") as f:
        f.write(render_html(rows, tone, cfg, note))
    with open(os.path.join(cfg["out_dir"], "watchlist.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "dir", "in_play", "has_news", "price", "change_pct",
                    "since_open_pct", "adj_rvol", "dollar_volume", "gap_pct", "day_low",
                    "day_high", "adr_pct", "score", "headline"])
        for r in rows:
            w.writerow([r["symbol"], r["dir"], r.get("in_play"), r.get("has_news"),
                        r["price"], r["change"], r.get("since_open"), r.get("adj_rvol"),
                        r["dollar_vol"], r["gap"], r["day_low"], r["day_high"],
                        r["adr_pct"], r["rank"], r.get("headline")])


# ============================================================
# Publish to GitHub Pages (gh-pages branch, single rolling commit)
# ============================================================
def _git(args, cwd, check=True):
    return subprocess.run(["git"] + args, cwd=cwd, check=check,
                          capture_output=True, text=True)


def publish(cfg):
    """Publish docs/ to the gh-pages branch with a NORMAL fast-forward commit.

    Do NOT force-push here: GitHub Pages frequently does not rebuild on a
    force-pushed (rewritten) history, which leaves the live site stuck on an old
    deploy even though the branch moved on. A fresh commit pushed fast-forward
    reliably triggers a Pages build. See PUBLISHING.md."""
    repo = _find_repo_root(HERE)
    if not repo:
        print("  ! not inside a git repo — skipping publish"); return
    branch = cfg["publish_branch"]
    wt = os.path.join(repo, ".ghpages_wt")
    try:
        remote_has = bool(_git(["ls-remote", "--heads", "origin", branch], repo, check=False).stdout.strip())
        if not os.path.isdir(wt):
            if remote_has or _git(["branch", "--list", branch], repo).stdout.strip():
                _git(["worktree", "add", wt, branch], repo)
            else:
                _git(["worktree", "add", "--detach", wt], repo)
                _git(["checkout", "--orphan", branch], wt)
                _git(["reset", "--hard"], wt, check=False)
        # start from the latest remote so our commit fast-forwards (triggers a build)
        if remote_has:
            _git(["fetch", "origin", branch], repo, check=False)
            _git(["reset", "--hard", f"origin/{branch}"], wt, check=False)
        for fn in ("index.html", "watchlist.csv", ".nojekyll"):
            src = os.path.join(cfg["out_dir"], fn)
            if os.path.exists(src):
                shutil.copy(src, os.path.join(wt, fn))
        _git(["add", "-A"], wt)
        if _git(["diff", "--cached", "--quiet"], wt, check=False).returncode == 0:
            print("  no change — skipping publish"); return
        _git(["commit", "-m", "update " + dt.datetime.now().strftime("%Y-%m-%d %H:%M")], wt)
        _git(["push", "origin", branch], wt)   # normal push -> GitHub Pages rebuilds
        print("  published to gh-pages")
    except subprocess.CalledProcessError as e:
        print("  ! publish failed:", (e.stderr or str(e))[:200])


def _find_repo_root(start):
    d = start
    while d != os.path.dirname(d):
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        d = os.path.dirname(d)
    return None


# ============================================================
# Market hours + loop
# ============================================================
def now_et():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        return dt.datetime.utcnow() - dt.timedelta(hours=4)  # rough EDT fallback


def market_open_now(cfg):
    t = now_et()
    if t.weekday() >= 5:
        return False
    o = t.replace(hour=cfg["market_open"][0], minute=cfg["market_open"][1], second=0, microsecond=0)
    c = t.replace(hour=cfg["market_close"][0], minute=cfg["market_close"][1], second=0, microsecond=0)
    return o <= t <= c


def note_text(cfg, tone):
    return ("A list of names to study, not buy signals. Do your own chart work: "
            "mark levels, wait for the setup, size by risk. " + tone["mood"])


CACHE_FILE = os.path.join(HERE, "last_good.json")


def _minutes_since_open(cfg):
    t = now_et()
    o = t.replace(hour=cfg["market_open"][0], minute=cfg["market_open"][1],
                  second=0, microsecond=0)
    return (t - o).total_seconds() / 60


def save_cache(rows, tone):
    try:
        json.dump({"saved": dt.datetime.now().strftime("%b %d, %I:%M %p"),
                   "rows": rows, "tone": tone}, open(CACHE_FILE, "w"))
    except Exception:
        pass


def load_cache():
    try:
        return json.load(open(CACHE_FILE))
    except Exception:
        return None


def scan_once(cfg, publish_it=False):
    if cfg.get("_demo"):
        raw = DEMO
        cfg["_mins_open"] = 120          # pretend it's ~2h into the session
    else:
        screens = list(cfg["screeners_long"]) + (cfg["screeners_short"] if cfg["include_shorts"] else [])
        print("Scanning Yahoo screeners...")
        raw = get_screener_rows(screens)
        cfg["_mins_open"] = max(_minutes_since_open(cfg), 1)   # for time-adjusted rel volume
    cfg["_scanned"] = len(raw)
    tone = tone_from(-0.97) if cfg.get("_demo") else get_market_tone(cfg["market_tone_symbol"])
    rows = build_rows(raw, cfg, live=True)   # live=True enriches levels (patched offline in demo)
    note = note_text(cfg, tone)

    if rows:
        save_cache(rows, tone)               # remember the last good list
    else:
        cached = load_cache()                # nothing eligible -> fall back, clearly labeled
        if cached and cached.get("rows"):
            rows, tone = cached["rows"], cached["tone"]
            note = ("STALE — nothing was eligible on this scan, so this is the last good "
                    f"list from {cached['saved']}. Re-check once the market is active.")

    write_outputs(rows, tone, cfg, note)
    print(f"  {len(rows)} names -> {os.path.join(cfg['out_dir'],'index.html')}")
    if publish_it:
        publish(cfg)
    return rows


def loop(cfg, publish_it):
    print(f"Loop started. Rescan every {cfg['refresh_minutes']} min during market hours. Ctrl+C to stop.")
    while True:
        try:
            if market_open_now(cfg):
                scan_once(cfg, publish_it)
                time.sleep(cfg["refresh_minutes"] * 60)
            else:
                print(f"[{now_et():%a %H:%M} ET] market closed — idling")
                time.sleep(600)
        except KeyboardInterrupt:
            print("\nStopped."); return
        except Exception as e:
            print("  ! cycle error:", str(e)[:160]); time.sleep(120)


# ============================================================
# Demo data (Yahoo-shaped)
# ============================================================
# Yahoo-shaped quotes incl. intraday fields (open / day high / day low / prev close).
# GAPR is a deliberate "gap-and-die": gapped +26% but faded since the open and sits
# near the day's lows — it should be tagged MOVER and rank BELOW the live movers.
def _q(sym, name, price, chg, vol, avg, cap, op, hi, lo, prev, qt="EQUITY"):
    return {"symbol": sym, "shortName": name, "regularMarketPrice": price,
            "regularMarketChangePercent": chg, "regularMarketVolume": vol,
            "averageDailyVolume3Month": avg, "marketCap": cap, "quoteType": qt,
            "regularMarketOpen": op, "regularMarketDayHigh": hi,
            "regularMarketDayLow": lo, "regularMarketPreviousClose": prev}


DEMO = [
    _q("BIYA", "Baiya International", 6.44, 54.4, 30_000_000, 2_100_000, 180_000_000, 5.50, 6.82, 4.03, 4.17),
    _q("WLDS", "Wearable Devices", 3.83, 20.4, 12_000_000, 1_500_000, 60_000_000, 3.30, 4.05, 3.10, 3.18),
    _q("PSQH", "PSQ Holdings", 3.70, 20.1, 9_000_000, 2_000_000, 100_000_000, 3.25, 3.90, 3.05, 3.08),
    _q("PRLD", "Prelude Therapeutics", 4.64, 19.3, 4_500_000, 1_100_000, 250_000_000, 4.10, 4.80, 3.90, 3.89),
    _q("TTGT", "TechTarget Inc", 4.47, 17.6, 3_000_000, 900_000, 130_000_000, 4.30, 4.60, 3.95, 3.80),
    _q("GAPR", "Gap And Die Co", 5.05, 26.3, 6_000_000, 1_500_000, 150_000_000, 5.20, 5.35, 4.95, 4.00),
    _q("ENTX", "Entera Bio", 3.26, -16.8, 5_300_000, 900_000, 120_000_000, 3.90, 3.96, 3.02, 3.92),
    _q("NCLH", "Norwegian Cruise", 19.22, -8.4, 9_000_000, 1_200_000, 900_000_000, 20.90, 21.20, 19.00, 20.98),
    _q("SOXL", "Direxion Semi Bull 3X ETF", 40.0, 8.0, 80_000_000, 70_000_000, 8_000_000_000, 39.0, 41.0, 38.0, 37.0, "ETF"),
    _q("AVGO", "Broadcom Inc", 383.6, 6.0, 20_000_000, 18_000_000, 1_700_000_000_000, 380.0, 386.0, 379.0, 361.9),
]


def _demo_enrich_patch():
    """Offline enrich(): ADR% from the (demo) day range; day high/low already
    come from the quote via normalize()."""
    def fake(sym, have=None):
        have = have or {}
        dh, dl = have.get("day_high"), have.get("day_low")
        if dh and dl and dh > dl:
            return {"adr_pct": round((dh - dl) / ((dh + dl) / 2) * 100, 1)}
        return {"adr_pct": 8.0}
    return fake


_DEMO_NEWS = {
    "BIYA": "Baiya announces FDA clearance for lead device",
    "WLDS": "Wearable Devices signs major distribution deal",
    "PRLD": "Prelude Therapeutics posts positive trial data",
    "ENTX": "Entera Bio drops after disappointing update",
}


def _demo_news_patch():
    def fake(sym):
        h = _DEMO_NEWS.get(sym)
        return {"has_news": bool(h), "headline": h}
    return fake


def main():
    ap = argparse.ArgumentParser(description="Momentum day-trading watchlist")
    ap.add_argument("--once", action="store_true", help="one scan and exit")
    ap.add_argument("--loop", action="store_true", help="run forever (market-hours aware)")
    ap.add_argument("--demo", action="store_true", help="offline sample data")
    ap.add_argument("--publish", action="store_true", help="push to gh-pages after each scan")
    ap.add_argument("--no-shorts", action="store_true")
    a = ap.parse_args()

    cfg = dict(CONFIG)
    if a.no_shorts: cfg["include_shorts"] = False
    if a.demo:
        cfg["_demo"] = True
        global enrich, fetch_news
        enrich = _demo_enrich_patch()
        fetch_news = _demo_news_patch()

    if a.loop:
        loop(cfg, a.publish)
    else:
        scan_once(cfg, a.publish)
        print("Done. Open docs/index.html (or your GitHub Pages URL).")


if __name__ == "__main__":
    main()
