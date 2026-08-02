"""Multi-timeframe context: hourly / daily / weekly.

Weekly bars are resampled from the daily cache — free, no extra download.
Hourly bars are fetched only for the daily shortlist (two-stage), so the scan
doesn't pay for 900 hourly downloads to end up showing you 20 names.

Nothing here predicts anything. It reports where price sits relative to the
20MA and 200MA on each timeframe so you can see at a glance whether the
timeframes agree before you pull up the chart.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Cfg, resolve
from .features import sma

OHLCV = ["Open", "High", "Low", "Close", "Volume"]


# --------------------------------------------------------------- resampling

def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    return df.resample("W-FRI").agg(
        {"Open": "first", "High": "max", "Low": "min",
         "Close": "last", "Volume": "sum"}).dropna(how="any")


# ------------------------------------------------------------ hourly fetch

def fetch_hourly(tickers: list[str], cfg: Cfg, verbose: bool = True
                 ) -> dict[str, pd.DataFrame]:
    """60-minute bars for a shortlist. Yahoo caps intraday history at ~730d."""
    mcfg = cfg.get("mtf", {})
    cache_dir = resolve(cfg, cfg.data["cache_dir"]) / "hourly"
    cache_dir.mkdir(parents=True, exist_ok=True)
    max_age = mcfg.get("hourly_cache_hours", 6)
    days = int(mcfg.get("hourly_period_days", 180))

    frames, stale = {}, []
    for t in tickers:
        p = cache_dir / f"{t}.parquet"
        if p.exists() and (time.time() - p.stat().st_mtime) < max_age * 3600:
            try:
                frames[t] = pd.read_parquet(p)
                continue
            except Exception:
                pass
        stale.append(t)

    if not stale:
        return frames
    if verbose:
        print(f"      hourly: {len(frames)} cached, {len(stale)} to fetch")

    try:
        import yfinance as yf
    except ImportError:
        print("      yfinance unavailable — skipping hourly")
        return frames

    batch = int(mcfg.get("hourly_batch", 50))
    for i in range(0, len(stale), batch):
        chunk = stale[i : i + batch]
        try:
            raw = yf.download(chunk, period=f"{days}d", interval="60m",
                              auto_adjust=True, group_by="ticker",
                              threads=True, progress=False)
        except Exception as exc:
            if verbose:
                print(f"      hourly batch failed ({exc})")
            continue
        if raw is None or not len(raw):
            continue
        for t in chunk:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    if t not in raw.columns.get_level_values(0):
                        continue
                    d = raw[t].copy()
                else:
                    d = raw.copy()
                if any(c not in d.columns for c in OHLCV):
                    continue
                d = d[OHLCV].dropna(how="all")
                d = d[d["Close"].notna()]
                if len(d) < 60:
                    continue
                d.index = pd.to_datetime(d.index)
                try:
                    d.index = d.index.tz_localize(None)
                except (TypeError, AttributeError):
                    d.index = d.index.tz_convert(None)
                frames[t] = d
                d.to_parquet(cache_dir / f"{t}.parquet")
            except Exception:
                continue
    return frames


# ------------------------------------------------------- per-timeframe state

def tf_state(df: pd.DataFrame, fast: int, slow: int) -> dict:
    """Where price sits vs the two moving averages on one timeframe."""
    if df is None or len(df) < fast + 5:
        return {"trend": "n/a", "above_fast": None, "above_slow": None,
                "fast_slope_up": None, "dist_fast_pct": None}

    close = df["Close"]
    px = float(close.iloc[-1])
    f = sma(close, fast)
    s = sma(close, slow) if len(df) >= slow else pd.Series([np.nan] * len(df),
                                                          index=df.index)
    fv = float(f.iloc[-1]) if not np.isnan(f.iloc[-1]) else np.nan
    sv = float(s.iloc[-1]) if len(s) and not np.isnan(s.iloc[-1]) else np.nan

    above_f = None if np.isnan(fv) else px > fv
    above_s = None if np.isnan(sv) else px > sv

    slope_up = None
    tail = f.dropna().tail(max(3, fast // 4))
    if len(tail) >= 3:
        slope_up = bool(np.polyfit(np.arange(len(tail)), tail.values, 1)[0] > 0)

    if above_f is True and above_s is True:
        trend = "up"
    elif above_f is False and above_s is False:
        trend = "down"
    elif above_f is None and above_s is None:
        trend = "n/a"
    else:
        trend = "mixed"

    return {
        "trend": trend,
        "above_fast": above_f,
        "above_slow": above_s,
        "fast_slope_up": slope_up,
        "dist_fast_pct": None if np.isnan(fv) else round((px / fv - 1) * 100, 2),
        "dist_slow_pct": None if np.isnan(sv) else round((px / sv - 1) * 100, 2),
    }


def build_context(daily: pd.DataFrame, hourly: pd.DataFrame | None,
                  cfg: Cfg) -> dict:
    """Hourly / daily / weekly state for one ticker."""
    ma = cfg.get("ma", {})
    fast, slow = int(ma.get("fast", 20)), int(ma.get("slow", 200))
    ctx = {
        "D": tf_state(daily, fast, slow),
        "W": tf_state(to_weekly(daily), fast, slow),
    }
    ctx["H"] = tf_state(hourly, fast, slow) if hourly is not None else \
        {"trend": "n/a", "above_fast": None, "above_slow": None,
         "fast_slope_up": None, "dist_fast_pct": None}
    return ctx


# ------------------------------------------------------------ alignment score

def alignment(ctx: dict, side: str, cfg: Cfg) -> float:
    """0-1: how well the timeframes agree with the trade direction.

    A sort key, not a probability. Weighted toward the daily and weekly since
    those are the timeframes the setup itself was measured on.
    """
    want_up = side == "long"
    weights = {"D": 0.45, "W": 0.35, "H": 0.20}
    got = total = 0.0

    for tf, w in weights.items():
        st = ctx.get(tf, {})
        if st.get("trend") == "n/a":
            continue
        total += w
        checks, hits = 0, 0
        for key in ("above_fast", "above_slow", "fast_slope_up"):
            v = st.get(key)
            if v is None:
                continue
            checks += 1
            if v == want_up:
                hits += 1
        if checks:
            got += w * (hits / checks)

    return round(got / total, 3) if total > 0 else 0.5


def extension_adr(daily: pd.DataFrame, cfg: Cfg) -> float:
    """Distance from the 20MA measured in average-daily-ranges.

    Percentages are misleading across names — 8% is nothing on a 6% ADR stock
    and enormous on a 1.5% ADR one. ADR units make the two comparable.
    """
    from .features import adr_pct

    ma = cfg.get("ma", {})
    fast = int(ma.get("fast", 20))
    if len(daily) < fast + 2:
        return 0.0
    m = sma(daily["Close"], fast).iloc[-1]
    adr = adr_pct(daily)
    if np.isnan(m) or m <= 0 or adr <= 0:
        return 0.0
    return float((float(daily["Close"].iloc[-1]) / float(m) - 1) * 100 / adr)


def passes_soft_ma(daily: pd.DataFrame, side: str, cfg: Cfg) -> bool:
    """Loose gate. Drops three things:

    1. Wrong side of the 200MA by a wide margin (trend disagrees outright)
    2. Too far from the 200MA in the trade's own direction (nothing left to give)
    3. Too extended from the 20MA in ADR units — the post-gap chase.

    (3) is the one that matters most in practice. A stock that just fell six
    average daily ranges below its 20MA on an earnings gap will keep showing up
    as a "bear flag" or "three crows" while being the worst possible short entry.
    """
    ma = cfg.get("ma", {})
    slow = int(ma.get("slow", 200))
    long_side = side == "long"

    # --- 20MA extension, in ADR units
    ext = extension_adr(daily, cfg)
    chase = float(ma.get("max_ext_fast_adr", 3.0))          # in trade direction
    counter = float(ma.get("max_pullback_fast_adr", 4.0))   # against it
    if long_side:
        if ext > chase or ext < -counter:
            return False
    else:
        if ext < -chase or ext > counter:
            return False

    # --- 200MA position
    if len(daily) < slow:
        return True                      # not enough history to judge
    s = sma(daily["Close"], slow).iloc[-1]
    if np.isnan(s) or s <= 0:
        return True
    rel = float(daily["Close"].iloc[-1]) / float(s) - 1

    if long_side:
        if rel < -float(ma.get("max_pct_below_slow_long", 0.12)):
            return False
        return rel <= float(ma.get("max_pct_above_slow_long", 0.60))
    if rel > float(ma.get("max_pct_above_slow_short", 0.12)):
        return False
    return rel >= -float(ma.get("max_pct_below_slow_short", 0.60))


def arrows(ctx: dict) -> str:
    """Compact H/D/W trend string for the report, e.g. 'up/up/mixed'.

    The separator is '/', so the trend labels must not contain one. `tf_state`
    returns 'n/a' for an unavailable timeframe, which used to split into two
    fake timeframes here and silently shift every badge in the report one slot
    to the right — daily would be rendered under the 'weekly' label. Normalised
    to 'na' so the string always has exactly three fields.
    """
    return "/".join(
        str(ctx.get(tf, {}).get("trend", "na")).replace("/", "")
        for tf in ("H", "D", "W")
    )


def trend_list(ctx: dict) -> list[str]:
    """H/D/W trends as a list — the unambiguous form, for the HTML report."""
    return [str(ctx.get(tf, {}).get("trend", "na")).replace("/", "")
            for tf in ("H", "D", "W")]
