"""Indicators and the volume analytics the scoring engine leans on.

All functions take a plain OHLCV DataFrame and return either a Series aligned to
its index or a scalar computed on the tail.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------- basic series

def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Close"].shift(1)
    a = df["High"] - df["Low"]
    b = (df["High"] - prev_close).abs()
    c = (df["Low"] - prev_close).abs()
    return pd.concat([a, b, c], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=max(2, n // 2)).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = up / down.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


# ------------------------------------------------------------ volume analytics

def accumulation_ratio(df: pd.DataFrame, lookback: int = 60, top_pct: float = 0.22) -> float:
    """Of the heaviest-volume days, what share closed above their open?

    This is the "volume spike direction" filter: institutions accumulating leave
    heavy-volume up days behind them, distribution leaves heavy-volume down days.
    Returns 0.5 when there is no signal or not enough data.
    """
    win = df.tail(lookback)
    if len(win) < 20:
        return 0.5
    k = max(5, int(round(len(win) * top_pct)))
    heavy = win.nlargest(k, "Volume")
    up = int((heavy["Close"] > heavy["Open"]).sum())
    down = int((heavy["Close"] < heavy["Open"]).sum())
    total = up + down
    return 0.5 if total == 0 else up / total


def volume_trend(vol: pd.Series) -> float:
    """Linear slope of volume across a window, as fraction-of-mean per session.

    Negative = volume contracting through the formation.
    """
    v = vol.dropna().astype(float)
    if len(v) < 5 or v.mean() <= 0:
        return 0.0
    x = np.arange(len(v), dtype=float)
    slope = np.polyfit(x, v.values, 1)[0]
    return float(slope / v.mean())


def volume_ratio(df: pd.DataFrame, recent: int = 5, base: int = 50) -> float:
    """Recent average volume vs the longer baseline. ~1.5 is the sweet spot."""
    if len(df) < base + recent:
        return 1.0
    r = df["Volume"].tail(recent).mean()
    b = df["Volume"].tail(base).mean()
    return float(r / b) if b > 0 else 1.0


# ------------------------------------------------------------------- position

def pct_from_52w_low(df: pd.DataFrame) -> float:
    win = df["Close"].tail(252)
    lo = float(win.min())
    return float((win.iloc[-1] - lo) / lo) if lo > 0 else 0.0


def pct_from_52w_high(df: pd.DataFrame) -> float:
    win = df["High"].tail(252)
    hi = float(win.max())
    return float((hi - df["Close"].iloc[-1]) / hi) if hi > 0 else 1.0


def close_position_in_range(row) -> float:
    """0 = closed at the low of the day, 1 = closed at the high."""
    rng = row["High"] - row["Low"]
    return 0.5 if rng <= 0 else float((row["Close"] - row["Low"]) / rng)


def adr_pct(df: pd.DataFrame, n: int = 20) -> float:
    """Average daily range as % of close. How much room there is to work with
    intraday — the number that decides whether a name is worth watching."""
    seg = df.tail(n)
    if len(seg) < 5:
        return 0.0
    rng = (seg["High"] - seg["Low"]) / seg["Close"].replace(0, np.nan)
    return float(rng.mean() * 100)


def last_return(df: pd.DataFrame) -> float:
    """Today's close-to-close return. Large values = 'loud start'."""
    if len(df) < 2:
        return 0.0
    return float(df["Close"].iloc[-1] / df["Close"].iloc[-2] - 1)


# --------------------------------------------------------------------- pivots

def pivot_highs(high: np.ndarray, w: int = 3) -> list[int]:
    idx = []
    for i in range(w, len(high) - w):
        seg = high[i - w : i + w + 1]
        if high[i] == seg.max() and (seg.argmax() == w):
            idx.append(i)
    return idx


def pivot_lows(low: np.ndarray, w: int = 3) -> list[int]:
    idx = []
    for i in range(w, len(low) - w):
        seg = low[i - w : i + w + 1]
        if low[i] == seg.min() and (seg.argmin() == w):
            idx.append(i)
    return idx


def fit_line(xs: list[int], ys: list[float]) -> tuple[float, float]:
    """Least-squares slope/intercept. Returns (0, mean) when underdetermined."""
    if len(xs) < 2:
        return 0.0, float(np.mean(ys)) if len(ys) else 0.0
    slope, intercept = np.polyfit(np.array(xs, dtype=float), np.array(ys, dtype=float), 1)
    return float(slope), float(intercept)


def line_at(slope: float, intercept: float, x: int) -> float:
    return float(slope * x + intercept)


def touches(xs: list[int], ys: list[float], slope: float, intercept: float,
            tol: float) -> int:
    """How many pivots sit within `tol` (absolute price) of the fitted line."""
    n = 0
    for x, y in zip(xs, ys):
        if abs(y - line_at(slope, intercept, x)) <= tol:
            n += 1
    return n


# --------------------------------------------------------------- bundled snapshot

def snapshot(df: pd.DataFrame) -> dict:
    """Common per-ticker metrics computed once and reused by every detector."""
    a = atr(df, 14)
    close = df["Close"]
    return {
        "close": float(close.iloc[-1]),
        "atr": float(a.iloc[-1]) if not np.isnan(a.iloc[-1]) else float(close.iloc[-1] * 0.02),
        "atr_pct": float(a.iloc[-1] / close.iloc[-1]) if close.iloc[-1] else 0.02,
        "sma50": float(sma(close, 50).iloc[-1]),
        "sma200": float(sma(close, 200).iloc[-1]) if len(df) >= 200 else float("nan"),
        "rsi14": float(rsi(close, 14).iloc[-1]),
        "dollar_volume": float((close * df["Volume"]).tail(20).median()),
        "adr_pct": adr_pct(df),
        "volume_ratio": volume_ratio(df),
        "accum_ratio": accumulation_ratio(df),
        "pct_above_52w_low": pct_from_52w_low(df),
        "pct_below_52w_high": pct_from_52w_high(df),
        "last_return": last_return(df),
        "close_position": close_position_in_range(df.iloc[-1]),
    }
