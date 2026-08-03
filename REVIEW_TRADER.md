# Trader's review — DT_SCANNER

Independent audit, August 1 2026. Read alongside `FLAWS.md`, not instead of it.

I re-derived every number below myself from `research/validation_2023-2026_bothsides.csv`,
the code, and the live `reports/watchlist_2026-08-01.csv`. Where I overlap with
`FLAWS.md` I say so; the new material is §2.

---

## 0. Verdict

The engineering is good and the self-criticism is unusually honest — `FLAWS.md`
reproduces cleanly against the raw data, which is more than most published
research survives. The problem is not that the scanner is dishonest. It is that
**the one number a trader needs has never been reported anywhere in the repo,
and when you compute it, it is negative.**

Everything in the project measures whether the *setup* drifts (win rate, market
beat, 10-day hold return). Nothing reports whether the *trade the page prints* —
that entry, that stop, that T1 — makes money. It doesn't.

Usable as an attention filter. Not usable as a trade plan in its current
parameterisation.

---

## 1. What I reproduced

`FLAWS.md`'s within-date tests replicate almost exactly on my own pass:

| test | FLAWS.md | mine |
|---|---|---|
| rank top-half vs bottom-half | −0.12pp, p=1.00 | −0.112pp, 8/15, p=1.00 |
| align > 0.95 vs rest | +0.14pp | +0.135pp, 7/15, p=1.00 |
| 3-candle detectors vs other ten | −0.93pp, p=0.118 | −0.99pp, 4/14, p=0.180 |
| ascending_triangle vs rest | +0.58pp | +0.578pp, 11/15, p=0.118 |
| short side vs long side | −0.54pp | −0.545pp, 5/15, p=0.302 |
| published top-22 slice | 44.8% win / −0.64% | 42.7% win / −0.63% |

I also confirmed 227 weekly bars per ticker (so the 200-week MA is real but
computed with 27 bars of margin, as §4.2 says), and 1,087 daily bars per ticker
— note that's ~4.3 years, not the ~750 sessions `config.yaml` says
`history_days: 750` buys you.

**Treat `FLAWS.md` as reliable.** I found nothing in it that overstates a
problem, and several things it understates.

I extended the within-date framework to every remaining input of the sort key.
All null:

| input | within-date effect on 10d return | dates better |
|---|---|---|
| ADR top-half | +0.181pp | 7/15 |
| pattern score top-half | +0.216pp | 8/15 |
| pattern height top-half | +0.195pp | 8/15 |
| `\|ext20_adr\| < 1` (coiled) | −0.124pp | 7/15 |
| `accum_ratio > 0.6` | −0.058pp | 10/15 |

So it isn't only `w_alignment` that's inert. **Every one of the four ranking
terms tests null, individually, once you control for scan date.** `rank` isn't a
weighted blend of weak signals; it's a weighted blend of noise.

---

## 2. New findings

### 2.1 The published trade plan loses money — this is the headline

`research/validation_2023-2026_bothsides.csv` contains a `trade_return` column.
Nothing in `FLAWS.md`, `README.md` or `BACKTEST_FINDINGS.md` ever reports it.
Here it is. 6,424 simulated trades (73.2% of detections reached the trigger),
entry/stop/T1 exactly as the page prints them, no costs:

| | n | mean | median | win rate |
|---|---|---|---|---|
| **All** | 6,424 | **−0.260%** | −1.109% | 43.4% |
| Long | 4,634 | −0.240% | −0.877% | 44.2% |
| Short | 1,790 | −0.311% | −2.062% | 41.6% |
| **Published top-22 only** | 267 | **−0.750%** | — | — |

Profitable on 6 of 15 scan dates. Add 15bp of round-trip friction and the mean
goes to −0.41%; the published slice to roughly −0.90%.

Note the direction of the gap: the plain 10-day **hold** return is **+0.40%**.
The exit rule turns a small positive drift into a loss. The setups aren't the
main problem — the trade construction is.

### 2.2 Why: the stop is too tight for the names the ranking selects

Exit breakdown across the 6,424 trades:

| exit | n | share | avg return |
|---|---|---|---|
| stop | 2,627 | 40.9% | −4.09% |
| target (T1) | 1,587 | 24.7% | +5.19% |
| time (10d) | 2,210 | 34.4% | +0.38% |

Three things fall out of this:

- **Realised reward:risk is 1.27:1, not the 1.50:1 `config.yaml` specifies.**
  The gap comes from `forward_outcome`'s honest entry fill (`max(entry, open)`),
  which shaves winners and extends losers. `target_conservative_r: 1.5` is
  therefore an overstatement of what you actually collect.
- **Breakeven needs a 29.7% target-hit rate. You get 24.7%.** That five-point
  gap is the whole deficit. It is closable by widening the stop or lowering T1 —
  this is a tuning problem, not a fatal one.
- **34.7% of stopped-out trades would have been profitable on a plain 10-day
  hold**, at an average of −1.46% instead of −4.09%. You are being shaken out of
  trades that work.

The mechanism is in `scoring.trade_levels`:

```python
capped = entry * (1 - sign * t["stop_max_pct"])   # 8%
stop   = max(raw_stop, capped) if sign > 0 else min(raw_stop, capped)
```

`stop_max_pct: 0.08` only ever makes the stop **tighter**, never wider. It binds
on 5 of the 22 names on the current list — and it binds precisely on the
highest-ADR names, which is exactly what `w_tradeability` (15% of rank,
`adr_ceiling: 4.0`) promotes to the top of the page:

| ticker | ADR% | ATR% | stop in ATR |
|---|---|---|---|
| NXT | 6.46 | 8.96 | **0.89** |
| IPGP | 5.46 | 7.49 | **1.07** |
| BLDR | 4.79 | 5.69 | 1.41 |
| ECHO | 4.40 | 5.77 | 1.39 |
| WHR | 4.94 | 5.16 | 1.55 |

A 0.89-ATR stop is inside one day's normal noise. Mean 10-day MAE across all
detections is −4.53%, i.e. the *median* detection trades against you by roughly
the width of the cap before the window is out. The 8% cap is a
position-sizing control masquerading as a stop, and it is doing damage. Size the
position off a volatility-appropriate stop instead; don't clip the stop to
control the risk.

### 2.3 The 40% alignment term isn't just inert — it's saturated

`FLAWS.md` reports that alignment adds nothing. The mechanical reason it *can't*
add anything:

- **59.0% of all 8,781 detections have `align` = 1.000 exactly.**
- 17 of the 22 names on the current live list have `align` = 1.000.
- `rank` correlates 0.759 with `align`, and the whole published list spans
  **86.4 to 96.0** — 9.6 points of a 100-point scale.

The largest term in the sort key is pinned at its ceiling for most candidates,
so the ordering of the top of the page is effectively decided by the 15%
structure term breaking ties. There is no discrimination left to measure. This
also means "rank 96.0 vs rank 86.4" conveys nothing; that gap is inside the
noise floor of a saturated metric.

### 2.4 `rank` has never been tested in the form you actually see

`scan.py`:

```python
use_hourly = bool(cfg.get("mtf", {}).get("hourly", False)) and as_of is None
```

Hourly is unavailable point-in-time, so every backtest runs with H missing and
`alignment()` renormalising over D+W. Live, `mtf.hourly: true` and the top 80
names get an H vote worth 0.20 of the alignment weight.

So the `rank` that was measured and the `rank` printed on the page are different
quantities. `FLAWS.md` notes hourly is disabled in the backtest but doesn't draw
the conclusion: the live sort key remains untested, and given §4.3's shortlist
discontinuity, the untested part is the part that reorders the top of the list.

### 2.5 Look-ahead in the backtest universe (not in `FLAWS.md`)

`backtest.py` line 256:

```python
frames = filter_universe(download(tickers, cfg), cfg)
```

`filter_universe` runs `passes_liquidity` on the **full frame through today**,
before any date slicing. A name that trades below `min_price: 5.0` or under
$5M/day *as of August 2026* is excluded from every historical scan date, even
dates when it was liquid and expensive.

`scan_frames` re-checks liquidity on the sliced frame, so the effective universe
is the intersection of "liquid then" and "liquid now". The second condition is
look-ahead, it compounds the survivorship bias in §3.1, and it removes the same
class of names — the ones that fell apart. **It is a two-line fix** (drop the
outer `filter_universe`; `scan_frames` already does the point-in-time check).

### 2.6 The benchmark comparison is measured over a different window

```python
b0 = bench.iloc[bpos + 1]   # CLOSE of day+1
b1 = bench.iloc[bpos + fwd]
```

versus the stock's `entry_ref = future["Open"].iloc[0]` — the **open** of day+1,
held to the close of day+`fwd`. The stock gets `fwd` sessions of exposure
including day+1's open-to-close; SPY gets `fwd − 1` and misses it. `market_beat`
is therefore not a like-for-like comparison. It's a small bias, but it runs in
the direction that *flatters* the scanner in an up market, and market beat is
still only 47.3%.

### 2.7 Earnings — confirmed on the live list, not just estimated

`FLAWS.md` §5.1 estimates 1–3 names per list report inside the holding window. I
checked the actual 2026-07-31 list against the earnings calendar. Within **three
trading days** of the Monday open:

| ticker | rank | side / pattern | reports |
|---|---|---|---|
| TOST | 89.4 | long bull_flag | Aug 4, post-market |
| DASH | 90.2 | long bull_flag | Aug 5, post-market |
| ELAN | 90.2 | long symmetrical_triangle | Aug 5, **pre-market** |

Three of 22, all in the top half by rank, all long. ELAN is the sharpest case:
it shows `To Trig% = −1.59`, i.e. already through its trigger, so the page reads
as "act now" — and it prints earnings before the open two sessions later. The
5.05% stop is not a stop against an earnings gap; it's a suggestion.

This is the single cheapest fix in the project and I'd do it before anything
else.

### 2.8 Smaller code notes

- **`min_history_bars: 260` is checked twice but `history_days: 750` delivers
  1,087 bars.** Harmless, but the config comment ("500 ~ 2 years") is wrong
  about what you're getting — `yf.download(period="1087d")` is returning 1,087
  *bars*, ~4.3 years.
- **`snapshot()` computes `dollar_volume` as a 20-day median; `passes_liquidity`
  uses 60.** Two different liquidity numbers, one of which is displayed.
- **`sma()` uses `min_periods=max(2, n//2)`** — `FLAWS.md` §4.4 flags this. Worth
  adding: it also silently affects `regime.classify`, where the 200-day SPY MA
  would return a 100-day mean if the benchmark series were ever short.

---

## 3. The framing problem, stated plainly

The folder is called DT_SCANNER and the README opens with "before the open". But
`forward_days: 10`, patterns spanning 20–90 daily bars, and T1 targets 5–9% away
describe a **two-week swing horizon**. `FLAWS.md` §1 says this well.

The trader's version of the point: on the current list, `risk_pct` runs 3.9% to
8.0% per share. At a 1% account risk per trade that's 12–25% of a $100k account
deployed per position, held overnight through earnings, in names selected partly
*for* having the widest daily ranges in the index. There is no version of that
which is day trading, and the overnight gap risk it carries is the largest
unmodelled term in the whole backtest.

---

## 4. What I'd change, in order

1. **Earnings filter.** Exclude or flag anything reporting within 5 sessions,
   and exclude those windows from the backtest too. `yfinance.Ticker.calendar`
   or the FMP connector; an afternoon's work. Highest value per hour by a wide
   margin.
2. **Re-tune the exits before anything else.** The setups drift +0.40%; the exit
   rule gives back −0.26%. Specifically: remove `stop_max_pct` as a stop clamp
   and move it to position sizing; test 2.0–2.5 ATR stops; test T1 at 1.0R and a
   trailing exit. You need to move the target-hit rate from 24.7% to ~30%, and
   the MAE data says the room exists.
3. **Fix the backtest look-ahead (§2.5) and the benchmark window (§2.6).** Both
   are a few lines, and until they're fixed every figure in the repo — mine
   included — is measured on a slightly rigged sample.
4. **Add `trade_return` to `summarize()` as the headline row.** The harness
   already records it. Not printing it is why nobody in the project noticed the
   plan is negative-expectancy.
5. **Simplify or retire `rank`.** Every component tests null. If it's an
   attention ordering, sort by proximity-to-trigger alone and say so; the
   saturated 40% alignment term is actively misleading because it makes 96.0
   look meaningfully better than 86.4.
6. **Split the pattern config** so `three_crows` can be disabled alone, then
   disable both 3-candle detectors. Worst two of twelve, worst in both
   directions, and the mean-reversion story explains why.
7. **Show sector.** Three energy names and three tech-hardware names on a 22-row
   list is not 22 ideas.
8. **Borrow check on shorts**, or drop the short book until the survivorship
   bias is fixed — it is graded on a sample with the best short candidates
   deleted, and it's the weaker side even so.

---

## 5. What's genuinely good

Worth saying, because the list above is one-sided:

- Point-in-time slicing in `scan.py` is real and correctly plumbed through the
  backtester. Most retail backtests fail here.
- `forward_outcome` assumes the worst when stop and target trade in the same
  bar, and models gap-through entry fills. Both are the honest choice.
- Detections that never trigger are reported separately rather than counted as
  losses.
- `est_win_rate` stays blank until calibration is measured. Refusing to print an
  unearned number is the right instinct and rarer than it should be.
- The `selftest.py` finding — random walks fire the detectors as often as
  planted patterns — is the most valuable single sentence in the repo.
- Regime multipliers ship at 1.0.
- `FLAWS.md` exists, reproduces, and understates rather than overstates.

The instincts are right. The gap is that the honesty is all aimed at the signal
and none of it at the trade.

---

*Informational only. Not financial advice. Every figure here is measured on a
survivorship-biased universe over 15 scan dates and should be read as
directional, not conclusive — the same caveat applies to my numbers as to
`FLAWS.md`'s.*
