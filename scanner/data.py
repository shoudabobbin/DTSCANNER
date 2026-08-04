"""Price data: download via yfinance, cache to local parquet, filter for liquidity.

This is the only module that touches the network. Everything downstream operates
on plain OHLCV DataFrames, so you can swap yfinance for a broker/vendor feed by
reimplementing `load_prices` alone.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Cfg, resolve

OHLCV = ["Open", "High", "Low", "Close", "Volume"]


def _cache_path(cache_dir: Path, ticker: str) -> Path:
    return cache_dir / f"{ticker}.parquet"


def _is_fresh(path: Path, max_age_hours: float) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < max_age_hours * 3600


def _extract(raw: pd.DataFrame, ticker: str) -> pd.DataFrame | None:
    """Pull one ticker's OHLCV out of a (possibly MultiIndex) yfinance frame."""
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            if ticker in raw.columns.get_level_values(0):
                df = raw[ticker].copy()
            elif ticker in raw.columns.get_level_values(1):
                df = raw.xs(ticker, axis=1, level=1).copy()
            else:
                return None
        else:
            df = raw.copy()
    except Exception:
        return None

    missing = [c for c in OHLCV if c not in df.columns]
    if missing:
        return None
    df = df[OHLCV].dropna(how="all")
    df = df[df["Close"].notna() & (df["Volume"].notna())]
    return df if len(df) else None


def download(tickers: list[str], cfg: Cfg, verbose: bool = True) -> dict[str, pd.DataFrame]:
    """Return {ticker: OHLCV DataFrame}, using cache where fresh."""
    cache_dir = resolve(cfg, cfg.data["cache_dir"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    max_age = cfg.data.get("max_cache_age_hours", 12)
    period_days = int(cfg.data.get("history_days", 750) * 1.45)  # calendar vs trading days

    frames: dict[str, pd.DataFrame] = {}
    stale: list[str] = []
    for t in tickers:
        p = _cache_path(cache_dir, t)
        if _is_fresh(p, max_age):
            try:
                frames[t] = pd.read_parquet(p)
                continue
            except Exception:
                pass
        stale.append(t)

    if verbose:
        print(f"  {len(frames)} cached, {len(stale)} to download")

    if not stale:
        return frames        # fully cached: no need for yfinance at all
    import yfinance as yf

    def _fetch(chunk: list[str]):
        return yf.download(
            chunk,
            period=f"{period_days}d",
            interval="1d",
            auto_adjust=True,
            group_by="ticker",
            threads=True,
            progress=False,
        )

    def _store(t: str, df: pd.DataFrame) -> None:
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        frames[t] = df
        try:
            df.to_parquet(_cache_path(cache_dir, t))
        except Exception:
            pass  # cache write failure is non-fatal

    missed: list[str] = []
    batch = int(cfg.data.get("batch_size", 100))
    for i in range(0, len(stale), batch):
        chunk = stale[i : i + batch]
        if verbose:
            print(f"  downloading {i + 1}-{i + len(chunk)} of {len(stale)}...", flush=True)
        try:
            raw = _fetch(chunk)
        except Exception as exc:
            print(f"  batch failed ({exc})")
            raw = None

        for t in chunk:
            df = _extract(raw, t) if raw is not None and len(raw) else None
            if df is None:
                missed.append(t)   # do NOT drop silently — retried below
                continue
            _store(t, df)

    # Retry the misses one at a time. A single bad symbol in a batch can poison
    # the whole request, so a name that failed in a group of 100 often succeeds
    # alone. Anything still missing falls back to its stale cache rather than
    # vanishing from the scan without a word.
    if missed:
        if verbose:
            print(f"  retrying {len(missed)} failed symbols individually...", flush=True)
        still_missing = []
        for t in missed:
            try:
                raw = _fetch([t])
            except Exception:
                raw = None
            df = _extract(raw, t) if raw is not None and len(raw) else None
            if df is None:
                still_missing.append(t)
            else:
                _store(t, df)

        recovered = []
        for t in still_missing:
            p = _cache_path(cache_dir, t)
            if not p.exists():
                continue
            try:
                frames[t] = pd.read_parquet(p)
                recovered.append(t)
            except Exception:
                pass

        dropped = [t for t in still_missing if t not in frames]
        if recovered:
            print(f"  WARNING: {len(recovered)} symbols served from STALE cache "
                  f"(download failed): {', '.join(recovered[:12])}"
                  f"{' ...' if len(recovered) > 12 else ''}")
        if dropped:
            print(f"  WARNING: {len(dropped)} symbols unavailable and excluded "
                  f"from this scan: {', '.join(dropped[:12])}"
                  f"{' ...' if len(dropped) > 12 else ''}")

    return frames


def incomplete_bar(bar_date) -> dict:
    """Is the newest bar still forming?

    True when the last bar is dated today (US Eastern) and it's before 16:00 ET.
    That bar then holds a partial session: partial volume, a partial range, and
    a close that is really just the last print.

    This matters more than it looks. The in-play filter compares today's volume
    to a 50-day average of *full* days — halfway through a session that ratio is
    roughly halved, so nothing clears the threshold and the scan returns an
    empty list that looks like a quiet market rather than a broken input.
    """
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        now_et = datetime.now(ZoneInfo("America/New_York"))
    except Exception:                      # no tzdata — assume complete
        return {"incomplete": False, "reason": "timezone unavailable"}

    if bar_date is None:
        return {"incomplete": False, "reason": "no data"}

    bd = pd.Timestamp(bar_date).date()
    if bd != now_et.date():
        return {"incomplete": False, "reason": "last bar is a prior session"}

    close_h, close_m = 16, 0
    if (now_et.hour, now_et.minute) >= (close_h, close_m):
        return {"incomplete": False, "reason": "after the close"}

    mins = (close_h * 60 + close_m) - (now_et.hour * 60 + now_et.minute)
    return {"incomplete": True, "minutes_to_close": mins,
            "now_et": now_et.strftime("%H:%M"),
            "reason": f"{mins} minutes before the 16:00 ET close"}


def staleness_report(frames: dict[str, pd.DataFrame]) -> dict:
    """How current is the data actually? The scan happily runs on a cache that
    silently stopped updating, so surface the last bar date before trusting it."""
    if not frames:
        return {"latest": None, "stale_tickers": [], "n": 0}
    lasts = {t: df.index[-1] for t, df in frames.items() if len(df)}
    if not lasts:
        return {"latest": None, "stale_tickers": [], "n": 0}
    latest = max(lasts.values())
    stale = sorted(t for t, d in lasts.items() if d < latest)
    return {"latest": latest, "stale_tickers": stale, "n": len(lasts)}


def load_benchmark(cfg: Cfg) -> pd.DataFrame | None:
    bench = cfg.data.get("benchmark", "SPY")
    got = download([bench], cfg, verbose=False)
    return got.get(bench)


def passes_liquidity(df: pd.DataFrame, cfg: Cfg) -> bool:
    lq = cfg.liquidity
    if len(df) < lq.get("min_history_bars", 260):
        return False
    last = df.iloc[-1]
    if not (lq["min_price"] <= last["Close"] <= lq["max_price"]):
        return False
    lb = int(lq.get("dollar_volume_lookback", 60))
    dv = (df["Close"] * df["Volume"]).tail(lb)
    if len(dv) < lb // 2:
        return False
    return float(np.nanmedian(dv)) >= lq["min_dollar_volume"]


def filter_universe(frames: dict[str, pd.DataFrame], cfg: Cfg) -> dict[str, pd.DataFrame]:
    return {t: df for t, df in frames.items() if passes_liquidity(df, cfg)}
