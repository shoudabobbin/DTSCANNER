#!/usr/bin/env python3
"""Nightly scan -> ranked watchlist.

    python run_scan.py                    # normal run
    python run_scan.py --refresh          # ignore cache, re-download everything
    python run_scan.py --tickers AAPL,MSFT  # ad-hoc subset
    python run_scan.py --min-score 28     # override the config floor
"""
from __future__ import annotations

import argparse
import sys
import time

from scanner.config import load_config
from scanner.data import (download, filter_universe, load_benchmark,
                          staleness_report)
from scanner.report import write_outputs
from scanner.scan import regime_now, scan_frames
from scanner.universe import build_universe


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--refresh", action="store_true", help="bypass all caches")
    ap.add_argument("--tickers", default=None, help="comma-separated override list")
    ap.add_argument("--min-score", type=float, default=None)
    ap.add_argument("--limit", type=int, default=None, help="cap universe size (testing)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.min_score is not None:
        cfg["scoring"]["min_score_to_report"] = args.min_score
    if args.refresh:
        cfg["data"]["max_cache_age_hours"] = 0

    t0 = time.time()

    print("[1/5] building universe")
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = build_universe(cfg, force_refresh=args.refresh)
    if args.limit:
        tickers = tickers[: args.limit]
    print(f"      {len(tickers)} tickers")

    print("[2/5] downloading prices")
    frames = download(tickers, cfg)
    print(f"      {len(frames)} with usable history")
    n_missing = len(tickers) - len(frames)

    # A cache that quietly stopped updating produces a confident, wrong scan.
    # Drop anything behind the consensus last bar and say so.
    st = staleness_report(frames)
    bar_date = st["latest"]
    if st["stale_tickers"]:
        print(f"      WARNING: {len(st['stale_tickers'])} symbols behind the "
              f"{bar_date.date()} consensus bar; excluded from this scan")
        for t in st["stale_tickers"]:
            frames.pop(t, None)

    print("[3/5] applying liquidity filter")
    frames = filter_universe(frames, cfg)
    print(f"      {len(frames)} pass")
    if not frames:
        print("No tickers passed the liquidity filter. Loosen config -> liquidity.")
        return 1

    print("[4/5] benchmark + regime")
    bench = load_benchmark(cfg)
    regime = regime_now(bench, cfg)
    print(f"      {regime['label']} (score {regime['score']})")

    print("[5/5] scanning")
    results = scan_frames(frames, bench, cfg, verbose=True)
    if not results.empty:
        n_l = int((results.side == "long").sum())
        n_s = int((results.side == "short").sum())
        print(f"      {len(results)} raw detections ({n_l} long / {n_s} short)")

    if results.empty:
        print("\nNothing qualified today. That is a normal outcome — most days "
              "should be quiet. Lower --min-score to inspect what was close.")
        return 0

    written = write_outputs(results, regime, cfg, data_note={
        "bar_date": str(bar_date.date()) if bar_date is not None else None,
        "universe": len(frames),
        "raw_detections": len(results),
        "stale_tickers": len(st["stale_tickers"]),
        "dropped": n_missing,
    })

    from scanner.report import shortlist
    top = shortlist(results, cfg)
    cols = ["ticker", "side", "pattern", "rank", "tf", "close", "adr_pct",
            "ext20_adr", "d_vs_20ma", "d_vs_200ma", "entry", "stop", "risk_pct"]
    cols = [c for c in cols if c in top.columns]
    print(f"\nMorning list ({len(top)} names):")
    print(top[cols].to_string(index=False))

    print()
    for kind, path in written.items():
        print(f"  {kind}: {path}")
    print(f"\nDone in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
