"""The scan engine: frames in, ranked watchlist out.

Two stages, so hourly data is only fetched for names that survive stage 1:
  stage 1  daily bars -> detections -> soft 200MA filter -> weekly context
  stage 2  hourly bars for the top N -> full H/D/W alignment -> final ranking

`as_of` is the important argument. Every slice is taken as `df.loc[:as_of]`, so
the backtester sees exactly what the scanner would have seen on that date and
nothing after it. Any change to a detector must respect that or the backtest
numbers become fiction. (Hourly is skipped during backtests — Yahoo only serves
~730 days of intraday history, so it cannot be reconstructed point-in-time for
older dates.)
"""
from __future__ import annotations

import pandas as pd

from .config import Cfg
from .data import passes_liquidity
from .features import snapshot
from .mtf import (alignment, arrows, build_context, extension_adr, fetch_hourly,
                  passes_soft_ma)
from .patterns import detect_all
from .regime import classify
from .scoring import passes_inplay, score_detection, watchlist_rank

COLUMNS = [
    "date", "ticker", "side", "pattern", "rank", "align", "tf",
    "close", "trigger", "entry", "stop", "target_conservative",
    "target_aggressive", "measured_move", "risk_pct", "dist_to_trigger_pct",
    "rvol", "range_exp", "gap_pct",
    "adr_pct", "ext20_adr", "atr_pct", "score", "structure", "volume", "readiness",
    "accum_ratio", "volume_ratio", "height_pct", "touches", "length",
    "d_vs_20ma", "d_vs_200ma", "w_trend", "h_trend", "regime", "dollar_volume",
]


def _fmt(v):
    return "—" if v is None else v


def scan_frames(frames: dict[str, pd.DataFrame], bench: pd.DataFrame | None,
                cfg: Cfg, as_of: pd.Timestamp | None = None,
                use_hourly: bool | None = None, verbose: bool = False
                ) -> pd.DataFrame:
    if bench is not None and len(bench):
        b = bench.loc[:as_of] if as_of is not None else bench
        regime = classify(b, cfg)
    else:
        regime = {"label": "unknown", "multiplier": 1.0}

    if use_hourly is None:
        use_hourly = bool(cfg.get("mtf", {}).get("hourly", False)) and as_of is None

    min_score = cfg.scoring.get("min_score_to_report", 0)
    max_atr = cfg.scoring["readiness"]["max_atr_to_trigger"]
    min_adr = float(cfg.liquidity.get("min_adr_pct", 0.0))

    # ------------------------------------------------------------- stage 1
    stage1 = []
    for ticker, full in frames.items():
        df = full.loc[:as_of] if as_of is not None else full
        if len(df) < cfg.liquidity.get("min_history_bars", 260):
            continue
        if not passes_liquidity(df, cfg):
            continue
        try:
            snap = snapshot(df)
        except Exception:
            continue
        if snap["adr_pct"] < min_adr:
            continue
        # "In play" gate: elevated volume AND an expanded range today. Applied
        # before detection so the detectors only ever run on names where
        # something is happening. Disable via inplay.enabled in config.yaml.
        if not passes_inplay(snap, cfg):
            continue

        dets = detect_all(df, cfg)
        if not dets:
            continue
        ctx_dw = build_context(df, None, cfg)
        ext20 = extension_adr(df, cfg)

        for det in dets:
            side = det.get("side", "long")
            if not passes_soft_ma(df, side, cfg):
                continue
            sign = 1.0 if side == "long" else -1.0
            dist_atr = sign * (det["trigger"] - snap["close"]) / max(snap["atr"], 1e-6)
            if dist_atr > max_atr or dist_atr < -1.0:
                continue

            scored = score_detection(det, snap, cfg, regime)
            if scored["score"] < min_score:
                continue
            stage1.append({"ticker": ticker, "df": df, "snap": snap,
                           "det": det, "scored": scored, "ctx": ctx_dw,
                           "ext20": ext20})

    if not stage1:
        return pd.DataFrame(columns=COLUMNS)

    # ------------------------------------------------------------- stage 2
    # provisional rank on daily+weekly only, to decide who gets hourly data
    for r in stage1:
        r["align_dw"] = alignment(r["ctx"], r["det"].get("side", "long"), cfg)
        r["rank_dw"] = watchlist_rank(r["scored"], r["snap"], r["align_dw"], cfg)
    stage1.sort(key=lambda r: r["rank_dw"], reverse=True)

    hourly = {}
    if use_hourly:
        n = int(cfg.get("mtf", {}).get("hourly_shortlist", 80))
        shortlist, seen = [], set()
        for r in stage1:
            if r["ticker"] not in seen:
                seen.add(r["ticker"])
                shortlist.append(r["ticker"])
            if len(shortlist) >= n:
                break
        if verbose:
            print(f"      hourly context for top {len(shortlist)} names")
        hourly = fetch_hourly(shortlist, cfg, verbose=verbose)

    rows = []
    for r in stage1:
        ctx = build_context(r["df"], hourly.get(r["ticker"]), cfg) if hourly \
            else r["ctx"]
        side = r["det"].get("side", "long")
        align = alignment(ctx, side, cfg)
        rank = watchlist_rank(r["scored"], r["snap"], align, cfg)
        snap, scored = r["snap"], r["scored"]

        rows.append({
            "date": r["df"].index[-1].date(),
            "ticker": r["ticker"],
            "rank": rank,
            "align": align,
            "tf": arrows(ctx),
            "close": round(snap["close"], 2),
            "adr_pct": round(snap["adr_pct"], 2),
            "rvol": round(snap["rvol"], 2),
            "range_exp": round(snap["range_exp"], 2),
            "gap_pct": round(snap["gap_pct"], 2),
            "ext20_adr": round(r["ext20"], 2),
            "atr_pct": round(snap["atr_pct"] * 100, 2),
            "accum_ratio": round(snap["accum_ratio"], 3),
            "volume_ratio": round(snap["volume_ratio"], 2),
            "height_pct": round(r["det"].get("height_pct", 0) * 100, 1),
            "touches": r["det"].get("touches", 0),
            "dollar_volume": int(snap["dollar_volume"]),
            "d_vs_20ma": _fmt(ctx["D"].get("dist_fast_pct")),
            "d_vs_200ma": _fmt(ctx["D"].get("dist_slow_pct")),
            "w_trend": ctx["W"].get("trend"),
            "h_trend": ctx["H"].get("trend"),
            **{k: v for k, v in scored.items() if k != "_detail"},
            "_detail": {**scored["_detail"], "timeframes": ctx},
        })

    out = pd.DataFrame(rows).sort_values("rank", ascending=False).reset_index(drop=True)
    ordered = [c for c in COLUMNS if c in out.columns]
    rest = [c for c in out.columns if c not in ordered and c != "_detail"]
    return out[ordered + rest + ["_detail"]]


def regime_now(bench: pd.DataFrame | None, cfg: Cfg, as_of=None) -> dict:
    if bench is None or not len(bench):
        return {"label": "unknown", "multiplier": 1.0, "direction": "unknown",
                "confidence": "unknown", "score": 0.0}
    b = bench.loc[:as_of] if as_of is not None else bench
    return classify(b, cfg)
