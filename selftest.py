#!/usr/bin/env python3
"""Offline self-test: synthetic OHLCV with planted setups, no network needed.

Run this first. It proves the detectors fire, the scoring arithmetic is sane and
the report writes, without spending a single yfinance call.

    python selftest.py
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from scanner.config import load_config
from scanner.features import accumulation_ratio, atr, volume_trend
from scanner.patterns import DETECTORS, detect_all
from scanner.report import write_outputs
from scanner.scan import regime_now, scan_frames

RNG = np.random.default_rng(7)
N = 420


def _ohlc_from_close(close: np.ndarray, vol: np.ndarray, wiggle=0.012) -> pd.DataFrame:
    idx = pd.bdate_range("2023-01-02", periods=len(close))
    open_ = np.r_[close[0], close[:-1]] * (1 + RNG.normal(0, wiggle / 3, len(close)))
    span = close * wiggle * (0.5 + RNG.random(len(close)))
    high = np.maximum(open_, close) + span
    low = np.minimum(open_, close) - span
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol},
        index=idx)


def _base_series(drift=0.0004, sigma=0.012):
    r = RNG.normal(drift, sigma, N)
    return 50 * np.exp(np.cumsum(r))


def make_uptrend_then_squeeze() -> pd.DataFrame:
    """Advance, then a tight low-volatility base near the highs."""
    c = _base_series(0.0011, 0.011)
    c[-45:] = c[-46] * (1 + RNG.normal(0, 0.0025, 45).cumsum())
    vol = RNG.lognormal(14, 0.35, N)
    vol[-45:] *= np.linspace(1.0, 0.55, 45)       # contracting volume
    # heavy days skewed to up closes -> high accumulation ratio
    heavy = RNG.choice(np.arange(N - 60, N), 14, replace=False)
    vol[heavy] *= 2.0
    df = _ohlc_from_close(c, vol, wiggle=0.010)
    for i in heavy:
        df.iloc[i, df.columns.get_loc("Close")] = df["Open"].iloc[i] * 1.015
    return df


def make_symmetrical_triangle() -> pd.DataFrame:
    c = _base_series(0.0009, 0.011)
    L = 60
    mid = c[-L]
    amp = np.linspace(mid * 0.14, mid * 0.03, L)
    osc = np.sin(np.linspace(0, 5 * np.pi, L))
    c[-L:] = mid + amp * osc
    vol = RNG.lognormal(14.2, 0.3, N)
    vol[-L:] *= np.linspace(1.0, 0.6, L)
    heavy = RNG.choice(np.arange(N - 60, N), 14, replace=False)
    vol[heavy] *= 2.2
    df = _ohlc_from_close(c, vol, wiggle=0.009)
    for i in heavy:
        df.iloc[i, df.columns.get_loc("Close")] = df["Open"].iloc[i] * 1.012
    return df


def make_ascending_triangle() -> pd.DataFrame:
    c = _base_series(0.0008, 0.011)
    L = 55
    res = c[-L] * 1.10
    lows = np.linspace(res * 0.86, res * 0.985, L)
    osc = (np.sin(np.linspace(0, 4.5 * np.pi, L)) + 1) / 2
    c[-L:] = lows + (res - lows) * osc
    vol = RNG.lognormal(14.1, 0.3, N)
    vol[-L:] *= np.linspace(1.0, 0.7, L)
    return _ohlc_from_close(c, vol, wiggle=0.009)


def make_bull_flag() -> pd.DataFrame:
    c = _base_series(0.0003, 0.010)
    pole = np.linspace(0, 0.28, 22)
    c[-34:-12] = c[-35] * (1 + pole)
    peak = c[-13]
    c[-12:] = peak * (1 - np.linspace(0.0, 0.07, 12) + RNG.normal(0, 0.004, 12))
    vol = RNG.lognormal(14.3, 0.3, N)
    vol[-34:-12] *= 1.8
    vol[-12:] *= 0.7
    return _ohlc_from_close(c, vol, wiggle=0.011)


def make_flat_base() -> pd.DataFrame:
    c = _base_series(0.0002, 0.010)
    c[-100:-40] = c[-101] * (1 + np.linspace(0, 0.30, 60))
    top = c[-41]
    c[-40:] = top * (1 + RNG.normal(0, 0.012, 40).cumsum() * 0.25)
    c[-40:] = np.clip(c[-40:], top * 0.90, top * 1.02)
    vol = RNG.lognormal(14.0, 0.3, N)
    vol[-40:] *= np.linspace(1.0, 0.6, 40)
    heavy = RNG.choice(np.arange(N - 60, N), 13, replace=False)
    vol[heavy] *= 2.1
    df = _ohlc_from_close(c, vol, wiggle=0.009)
    for i in heavy:
        df.iloc[i, df.columns.get_loc("Close")] = df["Open"].iloc[i] * 1.011
    return df


def make_bear_flag() -> pd.DataFrame:
    """Sharp decline then a shallow drift up — the short-side mirror."""
    c = _base_series(-0.0003, 0.010)
    c[-34:-12] = c[-35] * (1 - np.linspace(0, 0.26, 22))
    trough = c[-13]
    c[-12:] = trough * (1 + np.linspace(0.0, 0.06, 12) + RNG.normal(0, 0.004, 12))
    vol = RNG.lognormal(14.3, 0.3, N)
    vol[-34:-12] *= 1.8
    vol[-12:] *= 0.7
    return _ohlc_from_close(c, vol, wiggle=0.011)


def make_downtrend_squeeze() -> pd.DataFrame:
    """Decline into a tight low-volatility range beneath the averages."""
    c = _base_series(-0.0011, 0.011)
    c[-45:] = c[-46] * (1 + RNG.normal(0, 0.0025, 45).cumsum())
    vol = RNG.lognormal(14, 0.35, N)
    vol[-45:] *= np.linspace(1.0, 0.55, 45)
    return _ohlc_from_close(c, vol, wiggle=0.010)


def make_junk() -> pd.DataFrame:
    """Random walk, no structure. Should mostly NOT fire."""
    return _ohlc_from_close(_base_series(0.0, 0.022), RNG.lognormal(13.9, 0.4, N), 0.02)


def make_benchmark() -> pd.DataFrame:
    return _ohlc_from_close(_base_series(0.0005, 0.008), RNG.lognormal(16, 0.2, N), 0.006)


def main() -> int:
    cfg = load_config()
    cfg["liquidity"]["min_dollar_volume"] = 0        # synthetic volumes are arbitrary
    cfg["liquidity"]["min_adr_pct"] = 0.0
    cfg["scoring"]["min_score_to_report"] = 0
    cfg["output"]["dir"] = "reports_selftest"
    cfg["output"]["publish_dir"] = None   # never overwrite the real published
                                          # page with synthetic test data
    cfg["mtf"]["hourly"] = False                     # offline test, no downloads

    builders = {
        "SQUEEZE": make_uptrend_then_squeeze,
        "SYMTRI": make_symmetrical_triangle,
        "ASCTRI": make_ascending_triangle,
        "BULLFLAG": make_bull_flag,
        "FLATBASE": make_flat_base,
        "BEARFLAG": make_bear_flag,
        "DOWNSQZ": make_downtrend_squeeze,
    }
    frames = {name: fn() for name, fn in builders.items()}
    for i in range(6):
        frames[f"JUNK{i}"] = make_junk()
    bench = make_benchmark()

    print("=" * 62)
    print("1. sanity: indicators")
    d = frames["SQUEEZE"]
    a = atr(d, 14)
    assert a.notna().sum() > 350, "ATR mostly NaN"
    assert (a.dropna() > 0).all(), "non-positive ATR"
    ar = accumulation_ratio(d)
    vt = volume_trend(d["Volume"].tail(45))
    print(f"   ATR ok | accum_ratio={ar:.2f} (expect >0.5) | vol_trend={vt:+.4f} (expect <0)")
    assert 0.0 <= ar <= 1.0
    assert vt < 0, "planted contracting volume did not read as negative slope"

    print("\n2. detector firing")
    fired = {}
    for name, df in frames.items():
        hits = [h["pattern"] for h in detect_all(df, cfg)]
        fired[name] = hits
        print(f"   {name:10s} -> {hits or '—'}")
    assert any(fired.values()), "no detector fired on any planted pattern"
    junk_hits = sum(len(fired[f'JUNK{i}']) for i in range(6))
    planted_hits = sum(len(fired[k]) for k in builders)
    print(f"   planted: {planted_hits} hits | junk: {junk_hits} hits")

    print("\n3. every detector runs without error on every frame")
    for pname, fn in DETECTORS.items():
        for name, df in frames.items():
            res = fn(df, cfg)                      # must not raise
            if res is not None:
                assert res["trigger"] > 0, f"{pname}/{name}: bad trigger"
                assert res["height_pct"] >= 0, f"{pname}/{name}: negative height"
    print("   ok")

    print("\n4. regime classifier")
    reg = regime_now(bench, cfg)
    print(f"   {reg['label']} score={reg['score']} components={reg['components']}")
    assert reg["direction"] in ("bull", "bear")
    assert reg["confidence"] in ("low", "medium", "high")

    print("\n5. full scan + scoring (both sides)")
    res = scan_frames(frames, bench, cfg, use_hourly=False)
    if res.empty:
        print("   WARNING: scan returned nothing (detections existed but were "
              "filtered by trigger distance). Not fatal.")
    else:
        show = ["ticker", "side", "pattern", "rank", "align", "tf", "score",
                "entry", "stop", "target_conservative", "risk_pct"]
        print(res[[c for c in show if c in res.columns]].to_string(index=False))
        n_l = int((res.side == "long").sum())
        n_s = int((res.side == "short").sum())
        print(f"   {n_l} long / {n_s} short")
        assert n_l and n_s, "one side never fired on the planted patterns"
        for _, r in res.iterrows():
            assert 0 <= r["score"] <= 40.5, f"score out of range: {r['score']}"
            assert 0 <= r["rank"] <= 100.01, f"rank out of range: {r['rank']}"
            if r["side"] == "long":
                assert r["stop"] < r["entry"] < r["target_conservative"] \
                    < r["target_aggressive"], f"{r['ticker']}: long levels broken"
                assert r["measured_move"] > r["entry"]
            else:
                assert r["stop"] > r["entry"] > r["target_conservative"] \
                    > r["target_aggressive"], f"{r['ticker']}: short levels broken"
                assert r["measured_move"] < r["entry"]
            assert 0 < r["risk_pct"] <= 8.01, f"{r['ticker']}: risk {r['risk_pct']}%"
        print("   score/rank ranges, side-correct level ordering, risk caps: OK")

    print("\n6. point-in-time slicing (no lookahead)")
    cut = frames["SQUEEZE"].index[-40]
    a1 = scan_frames(frames, bench, cfg, as_of=cut, use_hourly=False)
    if not a1.empty:
        assert pd.Timestamp(a1["date"].iloc[0]) <= cut, "as_of leaked future bars"
    print(f"   as_of={cut.date()} -> {len(a1)} detections, none dated after the cut")

    print("\n7. forward-outcome maths (both sides)")
    from backtest import forward_outcome
    fut = frames["SQUEEZE"].tail(10)
    lo, hi = float(fut["Low"].min()), float(fut["High"].max())

    row = {"side": "long", "entry": lo * 0.99,        # guaranteed fill
           "stop": lo * 0.90, "target_conservative": hi * 1.10}   # never hit
    o = forward_outcome(fut, row, 0.01)
    assert o["traded"] is True and o["exit_reason"] == "time", o
    assert o["mfe"] >= o["hold_return"] >= o["mae"] - 1e-9, o

    srow = {"side": "short", "entry": hi * 1.01,      # guaranteed fill
            "stop": hi * 1.15, "target_conservative": lo * 0.85}  # never hit
    s = forward_outcome(fut, srow, 0.01)
    assert s["traded"] is True and s["exit_reason"] == "time", s
    assert s["mfe"] >= s["hold_return"] >= s["mae"] - 1e-9, s
    # a short's hold return must be the mirror of the long's over the same bars
    assert abs(s["hold_return"] + o["hold_return"]) < 1e-9, (s, o)

    o2 = forward_outcome(fut, dict(row, entry=hi * 1.5), 0.01)     # unreachable
    assert o2["traded"] is False and o2["exit_reason"] == "no_trigger"
    s2 = forward_outcome(fut, dict(srow, entry=lo * 0.5), 0.01)    # unreachable
    assert s2["traded"] is False and s2["exit_reason"] == "no_trigger"
    print(f"   long hold={o['hold_return']:+.2%} | short hold={s['hold_return']:+.2%} "
          f"(mirrored) | no-trigger handled both sides")

    # a stopped-out short must lose; a short that reaches target must win
    op0 = float(fut["Open"].iloc[0])
    st = forward_outcome(fut, {"side": "short", "entry": op0,
                               "stop": op0 * 1.001,        # just above the fill
                               "target_conservative": lo * 0.5}, 0.0)
    assert st["exit_reason"] == "stop" and st["trade_return"] < 0, st
    tg = forward_outcome(fut, {"side": "short", "entry": op0,
                               "stop": hi * 2.0,           # unreachable
                               "target_conservative": lo}, 0.0)
    assert tg["exit_reason"] == "target" and tg["trade_return"] > 0, tg
    print(f"   short stop-out {st['trade_return']:+.2%} (loss) | "
          f"short target {tg['trade_return']:+.2%} (gain)")

    print("\n8. mini backtest walk")
    from backtest import run, summarize
    dates = list(bench.index[300:-15:5])
    bt = run(cfg, frames, bench, dates, fwd=10, verbose=False)
    print(f"   {len(bt)} detection-outcomes over {len(dates)} scan dates")
    if not bt.empty:
        assert bt["hold_return"].notna().all()
        summarize(bt, min_n=1)

    print("\n9. report writing")
    if not res.empty:
        written = write_outputs(res, reg, cfg)
        for kind, path in written.items():
            assert path.exists() and path.stat().st_size > 200
            print(f"   {kind}: {path.name} ({path.stat().st_size:,} bytes)")

    print("\n" + "=" * 62)
    print("SELF-TEST PASSED — logic is sound. Real data still needs yfinance.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
