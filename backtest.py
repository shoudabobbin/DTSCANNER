#!/usr/bin/env python3
"""Walk the scanner across history and measure what the scores were worth.

This is the part that matters. The scoring weights shipped in config.yaml come
from someone else's blog post about their own proprietary data. Until you have
run this and seen the win rate actually rise with the score on YOUR universe and
YOUR date range, treat the scanner as an idea generator and nothing more.

    python backtest.py --limit 200 --step 5
    python backtest.py --limit 300 --start 2023-01-01 --calibrate

Two outcome definitions are recorded, because they answer different questions:

  hold   - buy the next open, sell N days later. Measures whether the SETUP
           predicts drift. Independent of any exit rule, so it is the honest
           way to compare score bands against each other.
  trade  - wait for the entry trigger; exit at target, stop, or N days.
           Measures whether the setup survives a real exit plan.

A detection that never trades (price never reaches the trigger) is reported
separately rather than silently counted as a loss.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from scanner.config import load_config, resolve
from scanner.data import download, filter_universe, load_benchmark
from scanner.scan import scan_frames
from scanner.universe import build_universe


def forward_outcome(future: pd.DataFrame, row, bench_fwd: float | None) -> dict:
    """Evaluate one detection over its forward window. Side-aware: a short's
    return is the inverse of the price change, and its stop sits above entry."""
    if len(future) < 2:
        return {}

    side = row.get("side", "long") if hasattr(row, "get") else "long"
    sign = 1.0 if side == "long" else -1.0

    entry_ref = float(future["Open"].iloc[0])
    exit_ref = float(future["Close"].iloc[-1])
    if entry_ref <= 0:
        return {}

    hold_ret = sign * (exit_ref / entry_ref - 1)
    best = float(future["High"].max()) if sign > 0 else float(future["Low"].min())
    worst = float(future["Low"].min()) if sign > 0 else float(future["High"].max())
    mfe = sign * (best / entry_ref - 1)
    mae = sign * (worst / entry_ref - 1)

    out = {
        "side": side,
        "hold_return": hold_ret,
        "hold_win": bool(hold_ret > 0),
        "mfe": mfe,
        "mae": mae,
        "market_return": bench_fwd,
        # a short "beats the market" by returning more than holding the index
        "market_beat": (bool(hold_ret > bench_fwd) if bench_fwd is not None else None),
    }

    # --- simulated trade with the published levels
    entry, stop, target = row["entry"], row["stop"], row["target_conservative"]
    filled_i = None
    for i in range(len(future)):
        hi, lo = float(future["High"].iloc[i]), float(future["Low"].iloc[i])
        if (hi >= entry) if sign > 0 else (lo <= entry):
            filled_i = i
            break

    if filled_i is None:
        out.update(traded=False, trade_return=np.nan, exit_reason="no_trigger")
        return out

    op = float(future["Open"].iloc[filled_i])           # gap-through realism
    fill = max(entry, op) if sign > 0 else min(entry, op)

    reason, exit_px = "time", float(future["Close"].iloc[-1])
    for i in range(filled_i, len(future)):
        lo, hi = float(future["Low"].iloc[i]), float(future["High"].iloc[i])
        stopped = (lo <= stop) if sign > 0 else (hi >= stop)
        hit = (hi >= target) if sign > 0 else (lo <= target)
        # assume the worst when both levels trade in the same bar
        if stopped:
            reason, exit_px = "stop", stop
            break
        if hit:
            reason, exit_px = "target", target
            break

    out.update(traded=True, trade_return=sign * (exit_px / fill - 1),
               exit_reason=reason)
    return out


def run(cfg, frames, bench, dates, fwd: int, verbose=True) -> pd.DataFrame:
    records = []
    bench_close = bench["Close"] if bench is not None else None

    for n, d in enumerate(dates, 1):
        if verbose:
            print(f"  [{n}/{len(dates)}] {d.date()}", end="\r", flush=True)
        res = scan_frames(frames, bench, cfg, as_of=d)
        if res.empty:
            continue

        # benchmark forward return over the same window
        bench_fwd = None
        if bench_close is not None:
            bpos = bench_close.index.searchsorted(d)
            if bpos + fwd + 1 < len(bench_close):
                b0 = float(bench_close.iloc[bpos + 1])
                b1 = float(bench_close.iloc[bpos + fwd])
                bench_fwd = b1 / b0 - 1 if b0 > 0 else None

        for _, row in res.iterrows():
            full = frames[row["ticker"]]
            pos = full.index.searchsorted(d)
            future = full.iloc[pos + 1 : pos + 1 + fwd]
            if len(future) < fwd:
                continue
            rec = {
                "date": d.date(), "ticker": row["ticker"], "pattern": row["pattern"],
                "rank": row.get("rank"), "align": row.get("align"),
                "adr_pct": row.get("adr_pct"),
                "score": row["score"], "structure": row["structure"],
                "volume": row["volume"], "readiness": row["readiness"],
                "regime": row["regime"], "accum_ratio": row["accum_ratio"],
                "volume_ratio": row["volume_ratio"], "height_pct": row["height_pct"],
                "touches": row["touches"],
            }
            rec.update(forward_outcome(future, row, bench_fwd))
            if rec.get("hold_return") is not None:
                records.append(rec)

    if verbose:
        print()
    return pd.DataFrame(records)


def _band(s: pd.Series, width: int = 5) -> pd.Series:
    return (s // width * width).astype(int)


def summarize(df: pd.DataFrame, min_n: int) -> None:
    if df.empty:
        print("No detections in the backtest window.")
        return

    def block(title, group_col):
        print(f"\n=== {title} ===")
        g = df.groupby(group_col, observed=True)
        rows = []
        for key, sub in g:
            if len(sub) < min_n:
                continue
            rows.append({
                group_col: key,
                "n": len(sub),
                "win_rate": sub["hold_win"].mean(),
                "mkt_beat": sub["market_beat"].mean() if sub["market_beat"].notna().any() else np.nan,
                "hold_ret": sub["hold_return"].mean(),
                "mfe": sub["mfe"].mean(),
                "trade_ret": sub.loc[sub["traded"] == True, "trade_return"].mean(),
                "trigger_rate": (sub["traded"] == True).mean(),
            })
        if not rows:
            print(f"  (every bucket below the {min_n}-detection minimum — "
                  f"widen the date range or the universe)")
            return
        out = pd.DataFrame(rows).sort_values(group_col)
        for c in ["win_rate", "mkt_beat", "trigger_rate"]:
            out[c] = (out[c] * 100).round(1)
        for c in ["hold_ret", "mfe", "trade_ret"]:
            out[c] = (out[c] * 100).round(2)
        print(out.to_string(index=False))

    df = df.copy()
    df["score_band"] = _band(df["score"])
    print(f"\nTotal detections: {len(df):,}   "
          f"overall win rate: {df['hold_win'].mean():.1%}   "
          f"market beat: {df['market_beat'].mean():.1%}")
    print("Baseline to beat is not 50% — it is the market's own hit rate over "
          "the same windows.")

    block("By score band", "score_band")
    if "side" in df.columns:
        block("By side", "side")
    if "rank" in df.columns and df["rank"].notna().any():
        df["rank_band"] = (df["rank"] // 10 * 10).astype("Int64")
        block("By watchlist rank band", "rank_band")
    block("By pattern", "pattern")
    block("By market regime", "regime")

    # the one filter claimed to be strongest — check it directly
    df["accum_band"] = pd.cut(df["accum_ratio"], [0, .4, .5, .6, .7, 1.01],
                              labels=["<40%", "40-50%", "50-60%", "60-70%", ">70%"])
    block("By accumulation ratio (heavy-volume up-day share)", "accum_band")

    df["height_band"] = pd.qcut(df["height_pct"], 5, duplicates="drop")
    block("By pattern height quintile", "height_band")


def write_calibration(df: pd.DataFrame, cfg, min_n: int) -> Path:
    out = {}
    d = df.copy()
    d["score_band"] = _band(d["score"])
    for pattern, sub in d.groupby("pattern"):
        tbl = {}
        for band, s in sub.groupby("score_band"):
            if len(s) >= min_n:
                tbl[str(band)] = {"n": int(len(s)), "win_rate": float(s["hold_win"].mean())}
        if tbl:
            out[pattern] = tbl
    allt = {}
    for band, s in d.groupby("score_band"):
        if len(s) >= min_n:
            allt[str(band)] = {"n": int(len(s)), "win_rate": float(s["hold_win"].mean())}
    if allt:
        out["_all"] = allt

    path = resolve(cfg, cfg.output["dir"]) / "calibration.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2))
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--limit", type=int, default=200,
                    help="universe cap — full-universe backtests are slow")
    ap.add_argument("--step", type=int, default=None, help="trading days between scans")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--calibrate", action="store_true",
                    help="write reports/calibration.json for the scanner to use")
    ap.add_argument("--save", default=None, help="dump raw detections to this CSV")
    args = ap.parse_args()

    cfg = load_config(args.config)
    fwd = int(cfg.backtest.get("forward_days", 10))
    step = args.step or int(cfg.backtest.get("step", 5))
    min_n = int(cfg.backtest.get("min_detections_per_bucket", 75))

    print("[1/4] universe + data")
    tickers = build_universe(cfg)[: args.limit]
    frames = filter_universe(download(tickers, cfg), cfg)
    bench = load_benchmark(cfg)
    print(f"      {len(frames)} tickers")
    if not frames or bench is None:
        print("Not enough data to backtest.")
        return 1

    idx = bench.index
    if args.start:
        idx = idx[idx >= pd.Timestamp(args.start)]
    if args.end:
        idx = idx[idx <= pd.Timestamp(args.end)]
    warmup = cfg.liquidity.get("min_history_bars", 260)
    idx = idx[warmup:]
    dates = list(idx[:-(fwd + 1)][::step])
    print(f"[2/4] {len(dates)} scan dates, {fwd}-day forward window")
    if not dates:
        print("Date range too short. Increase data.history_days or widen --start/--end.")
        return 1

    print("[3/4] walking history")
    res = run(cfg, frames, bench, dates, fwd)

    print("[4/4] results")
    summarize(res, min_n)

    if args.save:
        res.to_csv(args.save, index=False)
        print(f"\nraw detections -> {args.save}")
    if args.calibrate and not res.empty:
        print(f"calibration -> {write_calibration(res, cfg, min_n)}")

    print("\nRead the score-band table first. If win rate does not climb "
          "monotonically with score, the weights in config.yaml are not earning "
          "their keep and should be changed before you trade any of this.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
