"""Scoring: 40 points across structure (16), volume (14), breakout readiness (10).

The three components are meant to be independent, so a high total reflects
agreement rather than one dimension carrying a weak setup.

Where this deliberately contradicts textbook technical analysis:
  * touch count is NOT rewarded, and is penalised above 6 (visibility -> crowding)
  * trendline symmetry is not scored at all (no measured predictive value)
  * volume gets its highest marks for MODERATE expansion (~1.0-1.5x), not spikes
  * a big up-day at detection is penalised, not rewarded ("loud start")
  * pattern height is the most heavily weighted geometric feature

None of that is proven. It is a hypothesis lifted from someone else's writeup.
backtest.py exists so you can check it against your own data before trusting it.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .config import Cfg, resolve


def _ramp(x: float, lo: float, hi: float, points: float) -> float:
    """Linear 0 -> points as x moves from lo to hi (handles hi < lo)."""
    if hi == lo:
        return 0.0
    t = (x - lo) / (hi - lo)
    return float(np.clip(t, 0.0, 1.0) * points)


# ---------------------------------------------------------------------- volume

def score_volume(det: dict, snap: dict, cfg: Cfg) -> tuple[float, dict]:
    v = cfg.scoring["volume"]
    detail = {}

    # 1) accumulation vs distribution on the heaviest-volume days (8 pts)
    # For shorts the same evidence points the other way, so the ratio is
    # mirrored. NOTE: the backtest found no predictive value in this feature
    # either direction — it is retained as descriptive context, and the
    # watchlist ranking weights it lightly for that reason.
    accum = snap["accum_ratio"]
    if det.get("side", "long") == "short":
        accum = 1.0 - accum
    pts_accum = _ramp(accum, v["accum_weak"], v["accum_strong"], 8.0)
    detail["accum_ratio"] = round(snap["accum_ratio"], 3)

    # 2) recent volume expansion - moderate beats extreme (4 pts)
    r = snap["volume_ratio"]
    if r < v["ratio_ideal_low"]:
        pts_ratio = _ramp(r, 0.5, v["ratio_ideal_low"], 4.0)
    elif r <= v["ratio_ideal_high"]:
        pts_ratio = 4.0
    else:
        pts_ratio = 4.0 - _ramp(r, v["ratio_ideal_high"], v["ratio_penalty_above"], 4.0)
    detail["volume_ratio"] = round(r, 2)

    # 3) volume contracting through the formation (2 pts)
    vt = det.get("vol_trend", 0.0)
    pts_contract = _ramp(vt, 0.0, v["contraction_full"], 2.0)
    detail["vol_trend"] = round(vt, 4)

    total = pts_accum + pts_ratio + pts_contract
    detail.update(pts_accum=round(pts_accum, 2), pts_ratio=round(pts_ratio, 2),
                  pts_contract=round(pts_contract, 2))
    return float(np.clip(total, 0, 14)), detail


# ------------------------------------------------------------------- structure

def score_structure(det: dict, snap: dict, cfg: Cfg) -> tuple[float, dict]:
    s = cfg.scoring["structure"]
    detail = {}

    # 1) height - the strongest geometric predictor (10 pts)
    h = det.get("height_pct", 0.0)
    pts_height = _ramp(h, s["height_zero"], s["height_full"], 10.0)
    detail["height_pct"] = round(h * 100, 1)

    # 2) trend alignment (3 pts) — mirrored for shorts
    up = det.get("side", "long") == "long"
    pts_trend = 0.0
    if (snap["close"] > snap["sma50"]) == up:
        pts_trend += 1.5
    if not np.isnan(snap["sma200"]):
        if (snap["close"] > snap["sma200"]) == up:
            pts_trend += 1.0
        if (snap["sma50"] > snap["sma200"]) == up:
            pts_trend += 0.5

    # 3) 52-week position - mid-range beats both extremes (3 pts)
    above_low = snap["pct_above_52w_low"]
    if above_low < 0.15:
        pts_pos = 1.0
    elif above_low <= 0.75:
        pts_pos = 3.0
    else:
        pts_pos = 1.5
    detail["pct_above_52w_low"] = round(above_low * 100, 1)

    # 4) crowding penalty - many trendline touches means many eyes
    n = det.get("touches", 0)
    penalty = s["touch_penalty_points"] if n > s["touch_penalty_above"] else 0.0
    detail["touches"] = n

    total = pts_height + pts_trend + pts_pos - penalty
    detail.update(pts_height=round(pts_height, 2), pts_trend=round(pts_trend, 2),
                  pts_position=round(pts_pos, 2), touch_penalty=penalty)
    return float(np.clip(total, 0, 16)), detail


# ------------------------------------------------------------------- readiness

def score_readiness(det: dict, snap: dict, cfg: Cfg) -> tuple[float, dict]:
    r = cfg.scoring["readiness"]
    detail = {}

    trigger, close, a = det["trigger"], snap["close"], max(snap["atr"], 1e-6)
    sign = 1.0 if det.get("side", "long") == "long" else -1.0
    # positive = price still has to travel to reach the trigger, either way
    dist_atr = sign * (trigger - close) / a
    detail["dist_to_trigger_atr"] = round(dist_atr, 2)
    # signed in the direction of the trade: positive = price still has to move
    # to reach the trigger, negative = it has already gone through
    detail["dist_to_trigger_pct"] = round(sign * (trigger - close) / close * 100, 2)

    # 1) proximity to the trigger (6 pts) - closer is more actionable
    pts_prox = 6.0 - _ramp(dist_atr, 0.25, r["max_atr_to_trigger"], 6.0)
    if dist_atr < -0.5:            # already well through the level
        pts_prox = 1.0

    # 2) closing strength within the day's range (2 pts) — inverted for shorts
    cp = snap["close_position"] if sign > 0 else 1 - snap["close_position"]
    pts_close = _ramp(cp, 0.3, 0.9, 2.0)
    detail["close_position"] = round(snap["close_position"], 2)

    # 3) still coiled rather than already extended (2 pts)
    pts_coil = 2.0 if dist_atr > 0 else 0.5

    # 4) "loud start" penalty — a big move toward the trigger already spent it
    lr = sign * snap["last_return"]
    penalty = r["loud_start_penalty"] if lr > r["loud_start_threshold"] else 0.0
    detail["last_return_pct"] = round(lr * 100, 2)
    detail["loud_start_penalty"] = penalty

    total = pts_prox + pts_close + pts_coil - penalty
    detail.update(pts_proximity=round(pts_prox, 2), pts_close=round(pts_close, 2),
                  pts_coil=pts_coil)
    return float(np.clip(total, 0, 10)), detail


# ------------------------------------------------------------------ trade levels

def trade_levels(det: dict, snap: dict, cfg: Cfg) -> dict:
    """Side-aware. For a short, entry sits BELOW the trigger, stop above it,
    and targets run downward."""
    t = cfg.trade_levels
    a, close = snap["atr"], snap["close"]
    sign = 1.0 if det.get("side", "long") == "long" else -1.0
    move = det.get("move_pct", det.get("height_pct", 0.0))

    entry = det["trigger"] + sign * t["trigger_buffer_atr"] * a
    raw_stop = entry - sign * t["stop_atr_mult"] * a
    capped = entry * (1 - sign * t["stop_max_pct"])
    stop = max(raw_stop, capped) if sign > 0 else min(raw_stop, capped)
    risk = max(abs(entry - stop), 1e-6)

    return {
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "risk_per_share": round(risk, 2),
        "risk_pct": round(risk / entry * 100, 2),
        "target_conservative": round(entry + sign * t["target_conservative_r"] * risk, 2),
        "target_aggressive": round(entry + sign * t["target_aggressive_r"] * risk, 2),
        # measured move uses move_pct where a pattern defines one (a flag
        # projects its pole, not its flag), else the pattern height
        "measured_move": round(entry + sign * move * close, 2),
    }


# ------------------------------------------------------------------- calibration

_CAL_CACHE: dict | None = None


def load_calibration(cfg: Cfg) -> dict:
    """Score -> historical win rate, produced by backtest.py --calibrate.

    Empty until you have run a backtest. That is intentional: the scanner should
    not quote a win probability it has not measured on your own data.
    """
    global _CAL_CACHE
    if _CAL_CACHE is None:
        path = Path(resolve(cfg, cfg.output["dir"])) / "calibration.json"
        try:
            _CAL_CACHE = json.loads(path.read_text())
        except Exception:
            _CAL_CACHE = {}
    return _CAL_CACHE


def estimate_win_rate(pattern: str, score: float, cfg: Cfg):
    cal = load_calibration(cfg)
    table = cal.get(pattern) or cal.get("_all")
    if not table:
        return None
    band = str(int(score // 5 * 5))
    entry = table.get(band)
    if not entry or entry.get("n", 0) < cfg.backtest.get("min_detections_per_bucket", 75):
        return None
    return round(entry["win_rate"], 3)


# ------------------------------------------------------------------------- main

def inplay_score(snap: dict, cfg: Cfg) -> float:
    """0-1: how much is actually happening in this name today.

    Geometric mean of relative volume and range expansion, each normalised
    against its threshold. Geometric rather than arithmetic so a name cannot
    compensate for a dead price with a volume spike — both have to be present.
    """
    ip = cfg.get("inplay", {})
    min_rv = float(ip.get("min_rvol", 1.5))
    full_rv = max(float(ip.get("rvol_full", 3.0)), min_rv + 1e-6)
    min_re = float(ip.get("min_range_expansion", 1.2))

    rv = float(snap.get("rvol", 1.0))
    re = float(snap.get("range_exp", 1.0))

    rv_n = np.clip((rv - min_rv) / (full_rv - min_rv), 0.0, 1.0)
    re_n = np.clip((re - min_re) / (2.0 - min_re), 0.0, 1.0)
    return float(np.sqrt(max(rv_n, 1e-9) * max(re_n, 1e-9)))


def passes_inplay(snap: dict, cfg: Cfg) -> bool:
    """Hard gate. Set `inplay.enabled: false` in config.yaml to scan everything."""
    ip = cfg.get("inplay", {})
    if not ip.get("enabled", False):
        return True
    return (float(snap.get("rvol", 1.0)) >= float(ip.get("min_rvol", 1.5))
            and float(snap.get("range_exp", 1.0)) >= float(ip.get("min_range_expansion", 1.2)))


def watchlist_rank(scored: dict, snap: dict, align: float, cfg: Cfg) -> float:
    """The sort key for the morning list. 0-100.

    This is NOT a probability and does not claim predictive power — the
    backtest showed neither the pattern score nor the previous version of this
    key ranked outcomes. It answers a narrower question: "how well does this
    fit what I look at?"
      * in play      - is volume and range actually elevated today
      * readiness    - is price near the trigger
      * alignment    - do H/D/W agree with the direction (measured inert, §2)
      * tradeability - is there enough daily range to bother
      * structure    - is the formation clean enough to read
    """
    w = cfg.get("ranking", {})
    lo = float(w.get("adr_floor", 1.0))
    hi = float(w.get("adr_ceiling", 4.0))
    adr = float(snap.get("adr_pct", 0.0))
    tradeability = float(np.clip((adr - lo) / max(hi - lo, 1e-6), 0, 1))

    r = (float(w.get("w_inplay", 0.30)) * inplay_score(snap, cfg)
         + float(w.get("w_readiness", 0.30)) * (scored["readiness"] / 10.0)
         + float(w.get("w_alignment", 0.20)) * align
         + float(w.get("w_tradeability", 0.10)) * tradeability
         + float(w.get("w_structure", 0.10)) * (scored["structure"] / 16.0))
    return round(r * 100, 1)


def score_detection(det: dict, snap: dict, cfg: Cfg, regime: dict) -> dict:
    vol_pts, vol_d = score_volume(det, snap, cfg)
    str_pts, str_d = score_structure(det, snap, cfg)
    rdy_pts, rdy_d = score_readiness(det, snap, cfg)

    raw = vol_pts + str_pts + rdy_pts
    adjusted = raw * regime.get("multiplier", 1.0)

    out = {
        "pattern": det["pattern"],
        "side": det.get("side", "long"),
        "score": round(adjusted, 1),
        "raw_score": round(raw, 1),
        "structure": round(str_pts, 1),
        "volume": round(vol_pts, 1),
        "readiness": round(rdy_pts, 1),
        "trigger": round(det["trigger"], 2),
        "dist_to_trigger_pct": rdy_d["dist_to_trigger_pct"],
        "dist_to_trigger_atr": rdy_d["dist_to_trigger_atr"],
        "length": det.get("length"),
        "regime": regime.get("label"),
        "est_win_rate": estimate_win_rate(det["pattern"], adjusted, cfg),
    }
    out.update(trade_levels(det, snap, cfg))
    out["_detail"] = {"volume": vol_d, "structure": str_d, "readiness": rdy_d,
                      "pattern_extras": det.get("extras", {})}
    return out
