"""Pattern detectors.

Design notes, since these deliberately diverge from textbook definitions:

* Thresholds are LOOSE. The premise being tested is that clean, obvious setups
  are crowded and therefore already priced, while messier ones are not. Tight
  textbook filters would throw away exactly the detections that matter.
* Every detector returns geometry (height, length, touch count, volume slope)
  rather than a verdict. Scoring is a separate, swappable step.
* `trigger` is the price level a breakout has to clear. Nothing here decides
  whether the setup is good - that is scoring's job.

Each detector returns a dict or None:
    {pattern, trigger, height_pct, length, touches, vol_trend, extras{...}}
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Cfg
from .features import atr, fit_line, line_at, pivot_highs, pivot_lows, sma, volume_trend


def _candidate_lengths(min_len: int, max_len: int, n_avail: int) -> list[int]:
    """A handful of window sizes to try, longest first."""
    hi = min(max_len, n_avail - 5)
    out = []
    L = hi
    while L >= min_len:
        out.append(int(L))
        L = int(L * 0.75)
    return out


# --------------------------------------------------------- volatility compression

def volatility_compression(df: pd.DataFrame, cfg: Cfg) -> dict | None:
    p = cfg.patterns["volatility_compression"]
    lb, sq = int(p["lookback"]), int(p["squeeze_window"])
    if len(df) < lb + 30:
        return None

    close = df["Close"]
    a = atr(df, 14) / close
    win = a.tail(lb).dropna()
    if len(win) < lb // 2:
        return None
    cur = float(win.iloc[-1])
    pct = float((win < cur).mean() * 100)
    if pct > p["max_atr_percentile"]:
        return None
    if p.get("min_trend_filter", True) and close.iloc[-1] < sma(close, 50).iloc[-1]:
        return None

    seg = df.tail(sq)
    hi, lo = float(seg["High"].max()), float(seg["Low"].min())
    if lo <= 0:
        return None
    return {
        "pattern": "volatility_compression",
        "trigger": hi,
        "height_pct": (hi - lo) / float(close.iloc[-1]),
        "length": sq,
        "touches": 0,
        "vol_trend": volume_trend(seg["Volume"]),
        "extras": {"atr_percentile": round(pct, 1), "atr_pct": round(cur * 100, 2)},
    }


# ----------------------------------------------------------------------- flat base

def flat_base(df: pd.DataFrame, cfg: Cfg) -> dict | None:
    p = cfg.patterns["flat_base"]
    min_len, max_len = int(p["min_len"]), int(p["max_len"])
    if len(df) < max_len + 70:
        return None

    close = float(df["Close"].iloc[-1])
    hi52 = float(df["High"].tail(252).max())

    best = None
    for L in _candidate_lengths(min_len, max_len, len(df)):
        seg = df.tail(L)
        hi, lo = float(seg["High"].max()), float(seg["Low"].min())
        if hi <= 0:
            continue
        depth = (hi - lo) / hi
        if depth > p["max_depth"]:
            continue
        if (hi52 - hi) / hi52 > p["max_dist_from_high"]:
            continue

        # a base only means something after an advance into it
        prior = df.iloc[-(L + 60) : -L]
        if len(prior) < 30:
            continue
        p_lo = float(prior["Close"].min())
        advance = (float(seg["Close"].iloc[0]) - p_lo) / p_lo if p_lo > 0 else 0.0
        if advance < p["min_prior_advance"]:
            continue

        best = {
            "pattern": "flat_base",
            "trigger": hi,
            "height_pct": depth,
            "length": L,
            "touches": 0,
            "vol_trend": volume_trend(seg["Volume"]),
            "extras": {"base_depth_pct": round(depth * 100, 1),
                       "prior_advance_pct": round(advance * 100, 1)},
        }
        break  # longest qualifying base wins
    return best


# -------------------------------------------------------------- triangle helpers

def _triangle_fit(seg: pd.DataFrame, pw: int):
    high = seg["High"].to_numpy(dtype=float)
    low = seg["Low"].to_numpy(dtype=float)
    ph, pl = pivot_highs(high, pw), pivot_lows(low, pw)
    if len(ph) < 2 or len(pl) < 2:
        return None
    su, iu = fit_line(ph, [high[i] for i in ph])
    sl, il = fit_line(pl, [low[i] for i in pl])
    return {"ph": ph, "pl": pl, "slope_up": su, "int_up": iu,
            "slope_lo": sl, "int_lo": il, "high": high, "low": low}


def _count_touches(fit, tol: float) -> int:
    n = 0
    for i in fit["ph"]:
        if abs(fit["high"][i] - line_at(fit["slope_up"], fit["int_up"], i)) <= tol:
            n += 1
    for i in fit["pl"]:
        if abs(fit["low"][i] - line_at(fit["slope_lo"], fit["int_lo"], i)) <= tol:
            n += 1
    return n


# ------------------------------------------------------------ symmetrical triangle

def symmetrical_triangle(df: pd.DataFrame, cfg: Cfg) -> dict | None:
    p = cfg.patterns["symmetrical_triangle"]
    min_len, max_len, pw = int(p["min_len"]), int(p["max_len"]), int(p["pivot_window"])
    if len(df) < min_len + 20:
        return None

    close = float(df["Close"].iloc[-1])
    tol = float(atr(df, 14).iloc[-1]) * 0.5

    for L in _candidate_lengths(min_len, max_len, len(df)):
        seg = df.tail(L)
        fit = _triangle_fit(seg, pw)
        if fit is None:
            continue
        su, sl = fit["slope_up"], fit["slope_lo"]
        if su >= 0 or sl <= 0:          # must actually converge
            continue

        start_w = line_at(su, fit["int_up"], 0) - line_at(sl, fit["int_lo"], 0)
        end_w = line_at(su, fit["int_up"], L - 1) - line_at(sl, fit["int_lo"], L - 1)
        if start_w <= 0 or end_w <= 0:
            continue
        if end_w > (1 - p["min_convergence"]) * start_w:
            continue

        height_pct = start_w / close
        if height_pct < p["min_height_pct"]:
            continue

        n_touch = _count_touches(fit, tol)
        if n_touch < p["min_touches"]:
            continue

        # apex location, kept for reporting only - it did not predict anything
        conv = sl - su
        apex_x = (fit["int_up"] - fit["int_lo"]) / conv if conv != 0 else float("inf")
        progress = (L - 1) / apex_x if apex_x and np.isfinite(apex_x) and apex_x > 0 else np.nan

        return {
            "pattern": "symmetrical_triangle",
            "trigger": line_at(su, fit["int_up"], L - 1),
            "height_pct": height_pct,
            "length": L,
            "touches": n_touch,
            "vol_trend": volume_trend(seg["Volume"]),
            "extras": {
                "slope_ratio": round(abs(su) / abs(sl), 2) if sl else None,
                "apex_progress": None if not np.isfinite(progress) else round(float(progress), 2),
                "convergence": round(1 - end_w / start_w, 2),
            },
        }
    return None


# -------------------------------------------------------------- ascending triangle

def ascending_triangle(df: pd.DataFrame, cfg: Cfg) -> dict | None:
    p = cfg.patterns["ascending_triangle"]
    min_len, max_len, pw = int(p["min_len"]), int(p["max_len"]), int(p["pivot_window"])
    if len(df) < min_len + 20:
        return None

    close = float(df["Close"].iloc[-1])
    tol = float(atr(df, 14).iloc[-1]) * 0.5

    for L in _candidate_lengths(min_len, max_len, len(df)):
        seg = df.tail(L)
        fit = _triangle_fit(seg, pw)
        if fit is None:
            continue
        su, sl = fit["slope_up"], fit["slope_lo"]
        if abs(su) / close > p["max_resistance_slope"]:   # top must be roughly flat
            continue
        if sl / close < p["min_support_slope"]:           # lows must be rising
            continue

        resistance = float(np.mean([fit["high"][i] for i in fit["ph"]]))
        base_low = line_at(sl, fit["int_lo"], 0)
        if resistance <= base_low:
            continue

        return {
            "pattern": "ascending_triangle",
            "trigger": resistance,
            "height_pct": (resistance - base_low) / close,
            "length": L,
            "touches": _count_touches(fit, tol),
            "vol_trend": volume_trend(seg["Volume"]),
            "extras": {"resistance": round(resistance, 2),
                       "support_slope_pct_per_bar": round(sl / close * 100, 3)},
        }
    return None


# ------------------------------------------------------------------------ bull flag

def bull_flag(df: pd.DataFrame, cfg: Cfg) -> dict | None:
    p = cfg.patterns["bull_flag"]
    pole_lb = int(p["pole_lookback"])
    fmin, fmax = int(p["flag_min_len"]), int(p["flag_max_len"])
    if len(df) < pole_lb + fmax + 10:
        return None

    close = float(df["Close"].iloc[-1])
    for flen in range(fmax, fmin - 1, -1):
        flag = df.tail(flen)
        pole = df.iloc[-(flen + pole_lb) : -flen]
        if len(pole) < pole_lb // 2:
            continue

        pole_lo = float(pole["Low"].min())
        pole_hi = float(pole["High"].max())
        if pole_lo <= 0 or pole_hi <= pole_lo:
            continue
        pole_gain = (pole_hi - pole_lo) / pole_lo
        if pole_gain < p["min_pole_gain"]:
            continue
        # the high should sit late in the pole, not at its start
        if pole["High"].to_numpy().argmax() < len(pole) * 0.5:
            continue

        flag_hi, flag_lo = float(flag["High"].max()), float(flag["Low"].min())
        retrace = (pole_hi - flag_lo) / (pole_hi - pole_lo)
        if retrace > p["flag_max_retrace"] or retrace < 0:
            continue
        if (flag_hi - flag_lo) / flag_lo > p["flag_max_range"]:
            continue

        return {
            "pattern": "bull_flag",
            # height = the flag's own consolidation amplitude, so it is measured
            # the same way as a triangle's or a base's. Using the pole here
            # inflated bull_flag structure scores relative to every other
            # pattern and made it dominate the watchlist.
            "height_pct": (flag_hi - flag_lo) / close,
            "move_pct": pole_gain,            # measured-move target basis
            "trigger": flag_hi,
            "length": flen,
            "touches": 0,
            "vol_trend": volume_trend(flag["Volume"]),
            "extras": {"pole_gain_pct": round(pole_gain * 100, 1),
                       "flag_retrace_pct": round(retrace * 100, 1),
                       "flag_range_pct": round((flag_hi - flag_lo) / flag_lo * 100, 1),
                       "flag_len": flen},
        }
    return None


# ------------------------------------------------------- three white soldiers (loose)

def three_soldiers(df: pd.DataFrame, cfg: Cfg) -> dict | None:
    p = cfg.patterns["three_soldiers"]
    if len(df) < 60:
        return None
    last3 = df.tail(3)
    rets = (last3["Close"] / last3["Close"].shift(1) - 1)
    rets.iloc[0] = last3["Close"].iloc[0] / float(df["Close"].iloc[-4]) - 1
    if (rets < p["min_candle_return"]).any():
        return None

    total = float(last3["Close"].iloc[-1] / df["Close"].iloc[-4] - 1)
    if total < p["min_total_return"]:
        return None

    rng = (last3["High"] - last3["Low"]).replace(0, np.nan)
    pos = ((last3["Close"] - last3["Low"]) / rng).fillna(0.5).mean()
    if pos < p["min_close_position"]:
        return None

    close = float(df["Close"].iloc[-1])
    hi = float(last3["High"].max())
    return {
        "pattern": "three_soldiers",
        "trigger": hi,
        "height_pct": (hi - float(last3["Low"].min())) / close,
        "length": 3,
        "touches": 0,
        "vol_trend": volume_trend(df["Volume"].tail(10)),
        "extras": {"three_day_return_pct": round(total * 100, 1),
                   "avg_close_position": round(float(pos), 2)},
    }


# =============================================================================
# SHORT SIDE
#
# Mirrors of the long detectors. `trigger` is always the level the trade needs
# price to CROSS, so for a short it sits below the current price and entry /
# stop / targets are oriented downward by scoring.trade_levels.
# =============================================================================

def downside_compression(df: pd.DataFrame, cfg: Cfg) -> dict | None:
    """Volatility squeeze resolving beneath the 50-day average."""
    p = cfg.patterns["volatility_compression"]
    lb, sq = int(p["lookback"]), int(p["squeeze_window"])
    if len(df) < lb + 30:
        return None

    close = df["Close"]
    a = atr(df, 14) / close
    win = a.tail(lb).dropna()
    if len(win) < lb // 2:
        return None
    cur = float(win.iloc[-1])
    pct = float((win < cur).mean() * 100)
    if pct > p["max_atr_percentile"]:
        return None
    if p.get("min_trend_filter", True) and close.iloc[-1] > sma(close, 50).iloc[-1]:
        return None                      # mirror: must be UNDER the 50MA

    seg = df.tail(sq)
    hi, lo = float(seg["High"].max()), float(seg["Low"].min())
    if lo <= 0:
        return None
    return {
        "pattern": "downside_compression",
        "trigger": lo,
        "height_pct": (hi - lo) / float(close.iloc[-1]),
        "length": sq,
        "touches": 0,
        "vol_trend": volume_trend(seg["Volume"]),
        "extras": {"atr_percentile": round(pct, 1), "atr_pct": round(cur * 100, 2)},
    }


def distribution_top(df: pd.DataFrame, cfg: Cfg) -> dict | None:
    """Tight range that formed after a decline — the flat base, upside down."""
    p = cfg.patterns["flat_base"]
    min_len, max_len = int(p["min_len"]), int(p["max_len"])
    if len(df) < max_len + 70:
        return None

    close = float(df["Close"].iloc[-1])
    lo52 = float(df["Low"].tail(252).min())

    for L in _candidate_lengths(min_len, max_len, len(df)):
        seg = df.tail(L)
        hi, lo = float(seg["High"].max()), float(seg["Low"].min())
        if lo <= 0:
            continue
        depth = (hi - lo) / hi
        if depth > p["max_depth"]:
            continue
        if (lo - lo52) / lo52 > p["max_dist_from_high"]:
            continue                      # range must sit near the 52w low

        prior = df.iloc[-(L + 60) : -L]
        if len(prior) < 30:
            continue
        p_hi = float(prior["Close"].max())
        decline = (p_hi - float(seg["Close"].iloc[0])) / p_hi if p_hi > 0 else 0.0
        if decline < p["min_prior_advance"]:
            continue

        return {
            "pattern": "distribution_top",
            "trigger": lo,
            "height_pct": depth,
            "length": L,
            "touches": 0,
            "vol_trend": volume_trend(seg["Volume"]),
            "extras": {"range_depth_pct": round(depth * 100, 1),
                       "prior_decline_pct": round(decline * 100, 1)},
        }
    return None


def symmetrical_triangle_short(df: pd.DataFrame, cfg: Cfg) -> dict | None:
    """Same converging geometry, traded on a break of the LOWER trendline."""
    p = cfg.patterns["symmetrical_triangle"]
    min_len, max_len, pw = int(p["min_len"]), int(p["max_len"]), int(p["pivot_window"])
    if len(df) < min_len + 20:
        return None

    close = float(df["Close"].iloc[-1])
    tol = float(atr(df, 14).iloc[-1]) * 0.5

    for L in _candidate_lengths(min_len, max_len, len(df)):
        seg = df.tail(L)
        fit = _triangle_fit(seg, pw)
        if fit is None:
            continue
        su, sl = fit["slope_up"], fit["slope_lo"]
        if su >= 0 or sl <= 0:
            continue

        start_w = line_at(su, fit["int_up"], 0) - line_at(sl, fit["int_lo"], 0)
        end_w = line_at(su, fit["int_up"], L - 1) - line_at(sl, fit["int_lo"], L - 1)
        if start_w <= 0 or end_w <= 0:
            continue
        if end_w > (1 - p["min_convergence"]) * start_w:
            continue
        height_pct = start_w / close
        if height_pct < p["min_height_pct"]:
            continue
        n_touch = _count_touches(fit, tol)
        if n_touch < p["min_touches"]:
            continue

        return {
            "pattern": "symmetrical_triangle_short",
            "trigger": line_at(sl, fit["int_lo"], L - 1),
            "height_pct": height_pct,
            "length": L,
            "touches": n_touch,
            "vol_trend": volume_trend(seg["Volume"]),
            "extras": {"slope_ratio": round(abs(su) / abs(sl), 2) if sl else None,
                       "convergence": round(1 - end_w / start_w, 2)},
        }
    return None


def descending_triangle(df: pd.DataFrame, cfg: Cfg) -> dict | None:
    """Flat support with descending highs — the ascending triangle, mirrored."""
    p = cfg.patterns["ascending_triangle"]
    min_len, max_len, pw = int(p["min_len"]), int(p["max_len"]), int(p["pivot_window"])
    if len(df) < min_len + 20:
        return None

    close = float(df["Close"].iloc[-1])
    tol = float(atr(df, 14).iloc[-1]) * 0.5

    for L in _candidate_lengths(min_len, max_len, len(df)):
        seg = df.tail(L)
        fit = _triangle_fit(seg, pw)
        if fit is None:
            continue
        su, sl = fit["slope_up"], fit["slope_lo"]
        if abs(sl) / close > p["max_resistance_slope"]:    # support roughly flat
            continue
        if -su / close < p["min_support_slope"]:           # highs must be falling
            continue

        support = float(np.mean([fit["low"][i] for i in fit["pl"]]))
        top = line_at(su, fit["int_up"], 0)
        if top <= support:
            continue

        return {
            "pattern": "descending_triangle",
            "trigger": support,
            "height_pct": (top - support) / close,
            "length": L,
            "touches": _count_touches(fit, tol),
            "vol_trend": volume_trend(seg["Volume"]),
            "extras": {"support": round(support, 2),
                       "resistance_slope_pct_per_bar": round(su / close * 100, 3)},
        }
    return None


def bear_flag(df: pd.DataFrame, cfg: Cfg) -> dict | None:
    """Sharp decline, then a shallow drift back up."""
    p = cfg.patterns["bull_flag"]
    pole_lb = int(p["pole_lookback"])
    fmin, fmax = int(p["flag_min_len"]), int(p["flag_max_len"])
    if len(df) < pole_lb + fmax + 10:
        return None

    close = float(df["Close"].iloc[-1])
    for flen in range(fmax, fmin - 1, -1):
        flag = df.tail(flen)
        pole = df.iloc[-(flen + pole_lb) : -flen]
        if len(pole) < pole_lb // 2:
            continue

        pole_hi = float(pole["High"].max())
        pole_lo = float(pole["Low"].min())
        if pole_lo <= 0 or pole_hi <= pole_lo:
            continue
        pole_drop = (pole_hi - pole_lo) / pole_hi
        if pole_drop < p["min_pole_gain"]:
            continue
        # the low should sit late in the pole
        if pole["Low"].to_numpy().argmin() < len(pole) * 0.5:
            continue

        flag_hi, flag_lo = float(flag["High"].max()), float(flag["Low"].min())
        retrace = (flag_hi - pole_lo) / (pole_hi - pole_lo)
        if retrace > p["flag_max_retrace"] or retrace < 0:
            continue
        if (flag_hi - flag_lo) / flag_lo > p["flag_max_range"]:
            continue

        return {
            "pattern": "bear_flag",
            "trigger": flag_lo,
            "height_pct": (flag_hi - flag_lo) / close,
            "move_pct": pole_drop,
            "length": flen,
            "touches": 0,
            "vol_trend": volume_trend(flag["Volume"]),
            "extras": {"pole_drop_pct": round(pole_drop * 100, 1),
                       "flag_retrace_pct": round(retrace * 100, 1),
                       "flag_len": flen},
        }
    return None


def three_crows(df: pd.DataFrame, cfg: Cfg) -> dict | None:
    """Three declining candles, relaxed the same way three_soldiers is."""
    p = cfg.patterns["three_soldiers"]
    if len(df) < 60:
        return None
    last3 = df.tail(3)
    rets = (last3["Close"] / last3["Close"].shift(1) - 1)
    rets.iloc[0] = last3["Close"].iloc[0] / float(df["Close"].iloc[-4]) - 1
    if (rets > -p["min_candle_return"]).any():        # mirrored tolerance
        return None

    total = float(last3["Close"].iloc[-1] / df["Close"].iloc[-4] - 1)
    if total > -p["min_total_return"]:
        return None

    rng = (last3["High"] - last3["Low"]).replace(0, np.nan)
    pos = ((last3["Close"] - last3["Low"]) / rng).fillna(0.5).mean()
    if pos > 1 - p["min_close_position"]:             # must close weak in range
        return None

    close = float(df["Close"].iloc[-1])
    lo = float(last3["Low"].min())
    return {
        "pattern": "three_crows",
        "trigger": lo,
        "height_pct": (float(last3["High"].max()) - lo) / close,
        "length": 3,
        "touches": 0,
        "vol_trend": volume_trend(df["Volume"].tail(10)),
        "extras": {"three_day_return_pct": round(total * 100, 1),
                   "avg_close_position": round(float(pos), 2)},
    }


DETECTORS = {
    # long
    "volatility_compression": volatility_compression,
    "flat_base": flat_base,
    "symmetrical_triangle": symmetrical_triangle,
    "ascending_triangle": ascending_triangle,
    "bull_flag": bull_flag,
    "three_soldiers": three_soldiers,
    # short
    "downside_compression": downside_compression,
    "distribution_top": distribution_top,
    "symmetrical_triangle_short": symmetrical_triangle_short,
    "descending_triangle": descending_triangle,
    "bear_flag": bear_flag,
    "three_crows": three_crows,
}

SIDE = {
    "volatility_compression": "long", "flat_base": "long",
    "symmetrical_triangle": "long", "ascending_triangle": "long",
    "bull_flag": "long", "three_soldiers": "long",
    "downside_compression": "short", "distribution_top": "short",
    "symmetrical_triangle_short": "short", "descending_triangle": "short",
    "bear_flag": "short", "three_crows": "short",
}

# Short detectors reuse their long counterpart's config block.
CONFIG_KEY = {
    "downside_compression": "volatility_compression",
    "distribution_top": "flat_base",
    "symmetrical_triangle_short": "symmetrical_triangle",
    "descending_triangle": "ascending_triangle",
    "bear_flag": "bull_flag",
    "three_crows": "three_soldiers",
}


def _is_enabled(name: str, cfg: Cfg) -> bool:
    """Is this detector switched on?

    A short detector reuses its long counterpart's thresholds, but it can now
    be enabled/disabled on its own: an exact-name block in config.yaml wins,
    and only if there isn't one does it inherit the counterpart's flag. So

        patterns:
          three_crows:
            enabled: false

    turns off three_crows while leaving three_soldiers running, which the
    original CONFIG_KEY-only lookup made impossible.
    """
    own = cfg.patterns.get(name)
    if isinstance(own, dict) and "enabled" in own:
        return bool(own["enabled"])
    return bool(cfg.patterns.get(CONFIG_KEY.get(name, name), {}).get("enabled", False))


def detect_all(df: pd.DataFrame, cfg: Cfg) -> list[dict]:
    """Run every enabled detector against one ticker's history."""
    dirs = cfg.get("direction", {"long": True, "short": True})
    out = []
    for name, fn in DETECTORS.items():
        side = SIDE[name]
        if not dirs.get(side, True):
            continue
        if not _is_enabled(name, cfg):
            continue
        try:
            res = fn(df, cfg)
        except Exception:
            res = None          # a malformed series should never kill the scan
        if res:
            res["side"] = side
            out.append(res)
    return out
