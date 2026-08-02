"""Market regime: direction (bull/bear) x confidence (low/medium/high).

Computed from the benchmark only, never the individual stock. The claim worth
testing is that *low-confidence* bull is the productive regime for breakout
setups and high-confidence bull is the worst (crowded trades). The multipliers
in config.yaml ship at 1.0 - turn them on only if your own backtest agrees.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Cfg
from .features import sma


def classify(bench: pd.DataFrame, cfg: Cfg, as_of: int | None = None) -> dict:
    """as_of = positional index into bench; None means the last bar."""
    rc = cfg.regime
    df = bench if as_of is None else bench.iloc[: as_of + 1]
    if len(df) < rc.get("slow_sma", 200) + 10:
        return {"direction": "unknown", "confidence": "unknown", "label": "unknown",
                "score": 0.0, "multiplier": 1.0}

    close = df["Close"]
    fast = sma(close, rc["fast_sma"]).iloc[-1]
    slow = sma(close, rc["slow_sma"]).iloc[-1]
    px = float(close.iloc[-1])

    # ---- direction: three independent votes
    votes = [px > fast, px > slow, fast > slow]
    direction = "bull" if sum(votes) >= 2 else "bear"

    # ---- confidence: how emphatic is the trend?
    # 1) distance from the slow SMA, normalised by realised volatility
    ret = close.pct_change()
    vol = float(ret.tail(rc["vol_window"]).std())
    dist = abs(px / slow - 1)
    dist_z = min(dist / (vol * np.sqrt(rc["vol_window"]) + 1e-9), 3.0) / 3.0

    # 2) directional persistence over the slope window
    w = rc["slope_window"]
    up_share = float((ret.tail(w) > 0).mean())
    persistence = abs(up_share - 0.5) * 2

    # 3) trend slope of the fast SMA, normalised
    fast_series = sma(close, rc["fast_sma"]).tail(w).dropna()
    if len(fast_series) >= 3:
        slope = np.polyfit(np.arange(len(fast_series)), fast_series.values, 1)[0]
        slope_norm = min(abs(slope / px) / 0.002, 1.0)
    else:
        slope_norm = 0.0

    # 4) calm markets trend more convincingly than violent ones
    lb = rc.get("vol_percentile_lookback", 252)
    vol_series = ret.rolling(rc["vol_window"]).std().tail(lb).dropna()
    vol_pct = float((vol_series < vol).mean()) if len(vol_series) > 20 else 0.5
    calm = 1.0 - vol_pct

    score = float(np.mean([dist_z, persistence, slope_norm, calm]))
    confidence = "low" if score < 0.38 else ("medium" if score < 0.60 else "high")

    label = f"{direction}_{confidence}"
    mult = float(rc.get("multipliers", {}).get(label, 1.0))
    return {
        "direction": direction,
        "confidence": confidence,
        "label": label,
        "score": round(score, 3),
        "multiplier": mult,
        "benchmark_close": px,
        "components": {
            "distance_z": round(dist_z, 3),
            "persistence": round(persistence, 3),
            "slope": round(slope_norm, 3),
            "calm": round(calm, 3),
        },
    }
