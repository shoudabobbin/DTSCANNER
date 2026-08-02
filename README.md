# Morning Watchlist Scanner

Narrows ~900 liquid US stocks down to ~20 names worth pulling up before the
open — long and short. Scanner only: no orders, no broker connection.

**It does not predict anything, and doesn't try to.** The backtest
(`research/BACKTEST_FINDINGS.md`) showed the pattern score has no predictive
power on this data. What survived is the useful part: a funnel that finds
structure, checks whether hourly / daily / weekly agree, and hands you a short
list. The judgment is yours.

> **Read `FLAWS.md` before trusting the order of this list.** A second backtest
> (8,781 detections, 15 scan dates, both sides) found that the `rank` key which
> replaced the discredited score **also has no ordering power** — Spearman
> −0.046, and nothing at all once you control for scan date. The 40%-weighted
> timeframe-alignment term is measurably inert. `FLAWS.md` also covers the
> survivorship bias in the universe, the missing earnings filter, and four code
> defects that are now fixed.

Everything here is informational. Not financial advice, and I'm not a financial
advisor.

## Published page

`run_daily.bat` writes `docs/index.html` and pushes it to GitHub Pages, so the
morning list is a URL you can open on your phone. Setup is in `PUBLISHING.md`
(about five minutes, one time).

## What it gives you each morning

| Column | Meaning |
|---|---|
| **H/D/W** | Hourly / daily / weekly trend agreement with the trade direction. Green agrees, red opposes, grey mixed. |
| **Rank** | Sort key: 40% timeframe alignment, 30% proximity to trigger, 15% structure, 15% average daily range. Not a probability. |
| **vs 20MA / vs 200MA** | % distance from each, on the daily. |
| **ADR%** | Average daily range — how much room there is to work with intraday. |
| **Ext (ADR)** | Distance from the 20MA in average-daily-ranges. Near zero is coiled; ±3 is stretched. Signed, so −2.4 means 2.4 ADR *below* the 20MA. |
| **To Trig%** | Signed. Positive means it hasn't triggered yet; negative means price is already through the level. |
| **Entry / Stop / T1 / T2** | ATR-derived starting points, oriented correctly for the side. |

Twelve detectors, six each way: volatility compression, flat base, symmetrical
triangle, ascending triangle, bull flag, three soldiers — and their mirrors:
downside compression, distribution top, short symmetrical triangle, descending
triangle, bear flag, three crows.

### The filters that do the real work

- **200MA, both directions.** Longs more than 12% below it are dropped (trend
  disagrees), and so are longs more than 60% above it (the move is spent).
  Mirrored for shorts.
- **20MA extension in ADR units.** Anything more than 3 ADR from its 20MA *in
  the trade's direction* is dropped as a chase, and more than 4 ADR against it
  as a falling knife. This is measured in ADR rather than percent because 8% is
  nothing on a 6%-ADR stock and enormous on a 1.5%-ADR one.

That second filter matters more than it sounds. A stock that gapped down 21% on
earnings keeps detecting as a "bear flag" or "three crows" for days afterward
while being the worst possible short entry — it's six average daily ranges below
its 20MA with the move already made. Same in reverse for post-gap longs.

Tune both in `config.yaml` under `ma:`, and the sort weights under `ranking:`.

---

## Setup

```bash
pip install -r requirements.txt
python selftest.py     # offline, no network — proves the logic works
python run_scan.py     # the real thing
```

`selftest.py` builds synthetic price series with patterns planted in them and runs
the whole pipeline. If it passes, any failure in `run_scan.py` is a data problem,
not a code problem.

## Daily use

```bash
python run_scan.py                        # writes reports/watchlist_YYYY-MM-DD.{csv,html}
python run_scan.py --tickers NVDA,AMD,TSM # ad-hoc
python run_scan.py --refresh              # ignore the cache
```

Run it after the close. Open the HTML file; click any row for the full breakdown
including per-timeframe MA distances.

Daily bars for the whole universe take a few minutes on the first run, then
cache for 12 hours. Hourly bars are fetched **only for the top 80 daily
candidates** — that two-stage design is why adding hourly costs seconds rather
than another full download. Set `mtf.hourly: false` in `config.yaml` to skip it
entirely (weekly still works, it's resampled from the daily cache for free).

Long/short balance is capped by `output.max_per_side` so one direction can't
crowd out the other, and `output.one_per_ticker` keeps a name from appearing
three times because three detectors fired on it.

## Backtesting — do this before you trade any of it

```bash
python backtest.py --limit 200 --step 5              # start here (~10-20 min)
python backtest.py --limit 400 --start 2022-01-01 --calibrate
```

This walks the scanner across history, one scan date at a time, slicing every
series to `df.loc[:as_of]` so the scan sees exactly what it would have seen that
evening. It logs every detection with its forward 10-day outcome and prints win
rate / market-beat / return broken out by score band, pattern, regime,
accumulation ratio and height quintile.

**Read the score-band table first.** If win rate doesn't climb roughly
monotonically with score, the weights in `config.yaml` aren't earning their keep.
That's the whole point of the harness: it can tell you the scanner doesn't work.

`--calibrate` writes `reports/calibration.json`, after which the scanner reports a
measured win rate per score band instead of leaving that column blank. It stays
blank until you've measured it — the scanner won't quote a probability it hasn't
earned.

Two outcome definitions are recorded because they answer different questions:

- **hold** — buy next open, sell N days later. Independent of any exit rule, so
  it's the fair way to compare score bands.
- **trade** — wait for the entry trigger, exit at target / stop / N days. Tests
  whether the edge survives a real exit plan. Detections that never reach the
  trigger are reported separately, not counted as losses.

## Files

| File | What it does |
|---|---|
| `config.yaml` | Every threshold and weight. Change numbers here, not code. |
| `run_scan.py` | Nightly entry point |
| `backtest.py` | Historical walk + score calibration |
| `selftest.py` | Offline correctness check on synthetic data |
| `scanner/universe.py` | S&P 500/400/600 from Wikipedia, cached; custom lists |
| `scanner/data.py` | yfinance download, parquet cache, liquidity filter |
| `scanner/features.py` | ATR/RSI/SMA, volume analytics, pivot + trendline fitting |
| `scanner/patterns.py` | Twelve detectors, six per side |
| `scanner/mtf.py` | Weekly resample, two-stage hourly fetch, MA state, alignment |
| `scanner/regime.py` | Market regime from SPY: bull/bear × low/med/high confidence |
| `scanner/scoring.py` | 40-point score + entry/stop/target construction |
| `scanner/scan.py` | The engine — point-in-time safe |
| `scanner/report.py` | CSV + the self-contained HTML page |
| `publish.py` | Commits and pushes `docs/` to GitHub Pages |
| `FLAWS.md` | Review: measured weaknesses, methodology problems, bug fixes |
| `PUBLISHING.md` | One-time setup to get the page on a URL |
| `research/` | Backtest write-ups and the raw detection data behind them |

## Expanding the universe

In `config.yaml`:

```yaml
universe:
  sources: [sp500, sp400, sp600]   # ~1500 names
  custom: [PLTR, SOFI]             # always included
```

Or `sources: [file]` with `file_path: my_tickers.txt` for your own list. Going to
the full ~6000 NYSE+NASDAQ needs a different symbol source (the SEC or your
broker publishes one) — but be aware that most of those extra 4500 names are
thin. The `min_dollar_volume: 5000000` filter exists so you don't get a watchlist
full of stocks you can't actually get filled in.

## Adding a broker later

`scanner/data.py` is the only module that touches the network. Everything
downstream takes plain OHLCV DataFrames. To swap in a broker feed, reimplement
`download()` to return `{ticker: DataFrame}` with Open/High/Low/Close/Volume and
nothing else changes. Alpaca's free tier is the easiest drop-in, and its paper
account would let you bolt on order placement later without touching the scanner.

---

## What the scoring is based on, and how much to trust it

The 40-point model (structure 16 / volume 14 / readiness 10) implements the
claims from the StockDataAnalytics writeups you sent. Where those claims
contradict textbook technical analysis, I followed the writeup:

- **Touch count is not rewarded**, and is penalised above 6. Textbook says more
  touches confirm the pattern; the claim is that more touches means more eyes,
  which means a crowded trade.
- **Trendline symmetry isn't scored at all.** Reported for information only.
- **Volume scores highest at moderate expansion (1.0–1.5×)**, and decays above
  2.5×. Inverted from the usual "bigger spike is better."
- **A big up-day at detection is penalised 4 points** ("loud start" — the move
  consumed the breakout and attracted attention).
- **Pattern height is the most heavily weighted geometric feature** (10 of 16
  structure points).
- **Apex position is computed but not scored.** The 74% rule reportedly has no
  predictive power.
- **Accumulation ratio gets the single largest weight** (8 points): of the
  heaviest-volume days in the last 60, what share closed above their open.

Now the honest part. Those articles are marketing for a paid subscription
service. The statistics are self-reported, the detectors are proprietary and
unpublished, and nobody has audited them. The stated methodology is genuinely
better than most trading content — the Bonferroni correction, the train/validate/
holdout split, the direction-consistency rule, and openly naming a calibration
weakness in their own model are all things a person fabricating results wouldn't
bother with. But "describes rigorous methods" and "obtained those results" are
different claims, and only the first one is verifiable from outside.

Two specific things to hold loosely:

1. **The regime finding is the shakiest headline.** "Low-confidence bull beats
   high-confidence bull by 20+ win-rate points" rests on a regime classifier they
   don't publish. Mine is a reasonable reconstruction, not theirs, so their
   numbers can't transfer to it. That's why every regime multiplier in
   `config.yaml` ships at 1.0 — the classification is reported, not acted on,
   until your own data says it should be.
2. **Win rate as they define it is not profitability.** "Closes higher two weeks
   later" says nothing about the size of wins versus losses. A 70% win rate with
   an 8% stop and a 2% average win loses money. The backtester reports average
   return and MFE alongside win rate for exactly this reason — read those columns,
   not just the win rate.

## One finding from the self-test worth internalizing

In `selftest.py` I plant five real patterns and generate six pure random walks.
The random walks fire the detectors about as often as the planted patterns do.

That isn't a bug — it's the single most useful thing in this repo. Random data
produces convincing triangles, flags and bases. Chart patterns are largely a
perception artifact, which is why the unfiltered symmetrical triangle in that
article wins 50.7%: a coin flip. Any edge lives entirely in the filters, and
filters have to be measured, not assumed.

Corollary: the tables the backtester prints on synthetic data look meaningful —
score bands rising, regimes differing, quintiles spreading. They're noise, from
random walks with no signal in them at all. When you run it on real data you'll
get tables that look exactly as convincing. Sample size and out-of-sample
validation are what separate the two, not how good the table looks.

## What the backtest actually found

Full write-up in `research/BACKTEST_FINDINGS.md`. Short version, from 5,705
detections over Apr 2023 – Jun 2026:

- Market beat rate **47.9%** — the average detection underperformed holding SPY
- Score bands essentially flat: 52.7% / 52.0% / 54.9%
- Three promising findings (accumulation ratio inverted, regime effect, height →
  magnitude) all **failed a train/test holdout**. The regime effect reversed sign
  outright between halves.

That's why the pattern score was demoted to a minor input and the sort key was
rebuilt around things that are simply *true* about a chart — where price sits
relative to its averages, how far it is from the trigger, how much it moves in a
day — rather than things claimed to predict the future.

If you ever want to re-test, `backtest.py` still works and is side-aware. Just
don't tune `config.yaml` against a single sample; that's how the three findings
above got manufactured in the first place.

## Suggested path from here

1. `python selftest.py` — confirm it runs offline.
2. `python run_scan.py` after the close. Review the ~20 names with your own
   process: price action, multi-timeframe, 20MA/200MA.
3. Tune the knobs that control *what you see*, not what it claims:
   - `liquidity.min_adr_pct` — raise it if names feel too slow to day trade
   - `output.max_rows` / `max_per_side` — list length
   - `ma.max_pct_below_slow_long` — tighten to 0.05 for a stricter trend filter
   - `ranking.w_*` — reweight if alignment matters more or less to you than
     proximity to the trigger
4. Keep a log of which names you actually took and how they went. After a few
   months that's a real dataset about *your* process — worth more than any
   backtest of someone else's.

The thing most likely to blow up an account isn't a bad scanner. It's position
sizing. No filter in here changes that.
