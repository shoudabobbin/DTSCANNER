# Scanner review — flaws, weaknesses, and what I measured

Reviewed August 1 2026 against the repo as shipped. This is a critique, so it
reads negative; that's the assignment, not a verdict on the work. The code is
well-organised, the point-in-time discipline in `scan.py` is real, and
`research/BACKTEST_FINDINGS.md` is more honest than most published research. Several of
the problems below are ones the README already half-anticipates.

Four things are already fixed in the code. Everything else is described, not
changed.

---

## The short version

1. **The list you actually see every morning has never been tested.** The saved
   backtest predates both the short book and the current `rank` sort key. Six of
   the twelve detectors and the entire ordering logic shipped unmeasured. I ran
   it. Details in §2.
2. **`rank` does not rank.** No ordering power in either direction. The 40%
   weight on timeframe alignment — the single largest term — is measurably inert.
3. **The universe is survivorship-biased**, which contaminates every backtest
   number in the repo and hits the short side hardest.
4. **It is a swing scanner, not a day-trade scanner.** Worth naming, because it
   changes what you should expect from it.
5. **No earnings-date awareness** is the biggest practical omission for
   something you act on before the open.

---

## 1. Scope: this is not a day-trading tool

Everything in the pipeline is multi-day. Daily bars; patterns spanning 20–90
bars; a 10-day forward evaluation window; targets set at 1.5R and 3.0R off a
14-day ATR. On the 2026-07-31 list, T1 sits 5–9% away from entry. That is a
one-to-three week move on a typical S&P name, not an intraday one.

Nothing in the codebase looks at any of the things that actually drive a day
trade: overnight gap size, pre-market volume, relative volume in the first
thirty minutes, opening-range position, VWAP, float, short interest, or a news
catalyst. The only day-trade-flavoured input is `min_adr_pct`, which filters for
names that move enough to be worth watching.

This isn't a defect in the code — it does what it says internally. But if you
are day trading, the tool is answering a different question than the one you're
asking, and the mismatch will show up as trades that need three days to work
while you're flat by 3:45pm. Either treat it as what it is (an overnight-to-
swing idea generator) or add a genuinely intraday layer on top.

---

## 2. What I measured

`research/backtest_2023-2026_longonly.csv` has no `side`, `rank` or `align` column, and
`research/BACKTEST_FINDINGS.md` refers to "all six" patterns. That file was produced
before the short book and before the ranking rebuild. So I re-ran it.

**Setup:** 8,781 detections · 893 tickers · 15 scan dates evenly spaced across
Apr 2023 – Jul 2026 · 10-day forward window · hourly disabled (it can't be
reconstructed point-in-time, same as your harness).

### Overall

| | win | market-beat | avg 10d return |
|---|---|---|---|
| All detections | 52.3% | 47.3% | +0.40% |
| Long (n=6,189) | 54.1% | 48.2% | +0.49% |
| Short (n=2,592) | 47.8% | 45.3% | +0.18% |

Market-beat under 50% reproduces your original finding on a larger, side-aware
sample: the average detection underperformed simply holding SPY.

### `rank` — pooled, and why the pooled table is a trap

Grouping all 8,781 detections by rank band produces an alarming picture:

| rank band | n | win | market-beat | avg return |
|---|---|---|---|---|
| 45 | 244 | 55.3% | 48.8% | +0.34% |
| 55 | 650 | 55.2% | 49.7% | +0.59% |
| 65 | 1,305 | 56.6% | 49.7% | +1.01% |
| 75 | 1,658 | 51.6% | 46.3% | +0.52% |
| 85 | 504 | **42.5%** | **38.3%** | **−0.92%** |

And the published top-22 slice — literally what the page shows you — looked
worse than everything the scanner rejected: 44.8% win / −0.64% return, versus
52.5% / +0.44% for the rest. That's the sort of table that makes you want to
invert the sort key.

**Don't.** It's an artifact. Detections are not independent: every detection on
one scan date shares one market. High-rank detections cluster on particular
days, so a pooled table is partly measuring which days had more high-rank names,
not whether rank works.

Controlling for that — comparing the top half of rank against the bottom half
*within each scan date*, same day, same market:

| | result |
|---|---|
| Top-half-of-rank worse on | 7 of 15 dates |
| Mean difference | −0.12pp |
| Sign test | p = 1.00 |

Nothing. Spearman(rank, 10-day return) = −0.046 pooled, −0.014 in the first
half, −0.059 in the second.

**Conclusion: `rank` carries no ordering information, positive or negative.**
It was built to replace a score the backtest had discredited, and it has the
same problem. The README's claim that it ranks "how well this fits what I look
at" is fair — but it should say plainly that it has been tested and does not
rank outcomes.

I flag the pooled-vs-within-date gap prominently because it is the exact failure
mode `research/BACKTEST_FINDINGS.md` warns about, and I walked into it before checking.

### The heaviest-weighted component does nothing

`w_alignment: 0.40` is the largest term in the sort key. Within-date:

| | n | win rate | mean return diff |
|---|---|---|---|
| align > 0.95 | 5,181 | 52.2% | +0.14pp |
| everything else | 3,600 | 52.3% | — |

Zero. Forty percent of the sort key is a coin flip. Note also that 59% of all
detections score above 0.95 — the measure barely discriminates in the first
place.

### By detector (all twelve, first time)

| pattern | side | n | win | market-beat | avg return |
|---|---|---|---|---|---|
| three_crows | short | 283 | **37.1%** | 34.6% | **−1.22%** |
| three_soldiers | long | 332 | 46.7% | 43.1% | −0.49% |
| symmetrical_triangle_short | short | 485 | 45.8% | 43.3% | −0.23% |
| descending_triangle | short | 611 | 47.3% | 43.9% | −0.12% |
| bull_flag | long | 1,514 | 51.3% | 46.0% | +0.10% |
| flat_base | long | 1,586 | 53.3% | 46.9% | +0.47% |
| distribution_top | short | 294 | 46.9% | 48.0% | +0.52% |
| volatility_compression | long | 1,504 | 55.5% | 48.7% | +0.67% |
| symmetrical_triangle | long | 539 | 55.3% | 51.8% | +0.74% |
| bear_flag | short | 616 | 51.8% | 48.2% | +0.87% |
| downside_compression | short | 303 | 55.1% | 52.8% | +1.00% |
| ascending_triangle | long | 714 | **61.5%** | 54.2% | **+1.25%** |

Within-date, controlling for market conditions:

| test | worse on | p | mean diff | win rate |
|---|---|---|---|---|
| both 3-candle detectors vs the other ten | 11/15 dates | 0.118 | −0.93pp | 45.9% vs 52.6% |
| short side vs long side | 10/15 dates | 0.302 | −0.54pp | 45.0% vs 53.1% |
| ascending_triangle vs the rest | 4/15 (i.e. better on 11) | 1.00 | +0.58pp | 58.6% vs 51.4% |

**None of this is statistically significant at 15 scan dates.** Fifteen dates
cannot resolve a 1pp effect. But the 3-candle result is the most economically
coherent thing in the data: `three_soldiers` and `three_crows` are the two worst
of the twelve, they are worst in *both* directions, and they are the only two
detectors with `length: 3` — they fire on no structure at all, just three
consecutive directional closes. Three closes in one direction is a well-known
short-horizon mean-reversion setup, and this scanner trades it as continuation.

If you disable anything on this evidence, disable those two. Note you currently
can't disable `three_crows` without also disabling `three_soldiers` — see §4.6.

---

## 3. Methodology problems that affect every number in the repo

### 3.1 Survivorship bias — the most consequential one

`universe.py` scrapes **current** S&P 500/400 membership from Wikipedia. A
backtest over Apr 2023 – Jul 2026 therefore only ever sees companies still in
the index in August 2026. Everything acquired, delisted, collapsed or demoted
during the window is invisible.

This is not a small correction. Index deletions are disproportionately the names
that fell hardest — which is to say, **exactly the names a short scanner exists
to find**. Your short book is being graded on a sample with the best short
candidates removed. The long side is inflated by the same mechanism.

Fixing it properly requires point-in-time index membership (CRSP, Compustat, or
your broker's historical constituent file). A cheap partial fix: build the
universe from a historical snapshot list rather than today's, and accept the
staleness. Until then, treat all backtest figures — mine included — as an upper
bound on the longs and a lower bound on the shorts.

### 3.2 `auto_adjust=True` quietly breaks point-in-time

`scan.py`'s docstring promises the backtest "sees exactly what it would have
seen that evening." Slicing `df.loc[:as_of]` handles the time axis. It does not
handle the *price* axis: yfinance back-adjusts the entire series for splits and
dividends using today's factors. A 2023 scan date sees 2023 prices retroactively
restated by corporate actions that hadn't happened yet.

Effects: `min_price: 5.0` and `min_dollar_volume: 5000000` are evaluated against
counterfactual prices, so the historical liquidity gate admits and rejects the
wrong names; and any stock that split later has its entire pre-split dollar
volume rescaled. Returns computed on a consistently-adjusted series are mostly
fine, so this is a second-order problem — but the docstring's claim is stronger
than what the code delivers.

### 3.3 Standard errors are badly understated

`backtest.py`'s `summarize()` pools detections and treats them as independent.
They are not — they're clustered by scan date. With 41 dates and 5,705
detections, the effective sample size for anything market-driven is closer to 41
than 5,705, and every confidence interval implied by those bucket sizes is
several times too narrow.

This is the mechanism that produced the false "top-22 underperforms" result in
§2 and, I'd suggest, is worth suspecting for the three rejected findings in
`research/BACKTEST_FINDINGS.md` too. **Recommendation:** add a within-date comparison to
`summarize()`. Comparing buckets against each other *inside* a single scan date
removes the market factor entirely and is the right default for a
cross-sectional scanner.

### 3.4 Multiple comparisons in live use

~900 names × 12 detectors ≈ 10,800 tests every night, from which 22 are
published. `selftest.py` already establishes that pure random walks fire these
detectors about as often as planted patterns do. Nothing anywhere corrects for
the selection. The README says this well; the code does nothing about it.

### 3.5 No transaction costs

No spread, no slippage, no commission. `forward_outcome` does model gap-through
fills on entry (`max(entry, open)`) which is good practice, but exits assume you
get filled at the exact stop or target price. A stop is a market order that
fills *through* the level — and this scanner preferentially selects high-ADR
names (`adr_ceiling: 4.0` gives full marks at 4%+), which are precisely the ones
that slip most. On a trade risking 5–8% per share, 20–30bp of round-trip
friction is a real fraction of a 1.5R target.

---

## 4. Signal-construction weaknesses

### 4.1 The rank components are collinear with each other and with the filters

The same fact — *is price above its moving averages* — is used four times:

- `passes_soft_ma()` filters on price vs the 20MA (in ADR units) and the 200MA
- `score_structure()` awards 3 points for price vs the 50MA and 200MA
- `alignment()` scores price vs the 20/200MA on three timeframes
- `watchlist_rank()` then weights that alignment at 40%

So `rank` is largely a trend-persistence factor wearing four hats. Its three
components are not the independent dimensions the scoring docstring describes.
This is consistent with the measured result that it adds nothing.

### 4.2 The three timeframes are not three views of the same horizon

`build_context()` applies `ma.fast: 20` / `ma.slow: 200` literally on every
timeframe. In practice:

| timeframe | "20MA" is really | "200MA" is really |
|---|---|---|
| hourly | ~3 trading days | ~29 trading days |
| daily | 1 month | 10 months |
| weekly | 5 months | **~4 years** |

These aren't three lenses on one trend; they're three unrelated lookbacks being
counted as a three-vote consensus. Two specific consequences:

- The 200-week MA needs 200 weekly bars and your cache holds ~227. It's computed
  at the very edge of available data. I measured the universe: **75.7% of names
  sit above their 200-week MA** (vs 70.4% above the 200-day). For a long, that
  vote is nearly free; for a short, nearly impossible. A structural side bias in
  a component weighted at 35% of alignment.
- 17 names (2%) have too little history for it at all and silently score on two
  of three checks.

Standard practice is to scale the periods: 20/200 daily ≈ 4/40 weekly ≈
140/1400 hourly. That would make the three votes comparable.

### 4.3 The hourly shortlist creates a rank discontinuity

Only the top 80 daily candidates get hourly data. `alignment()` skips
unavailable timeframes and renormalises over what's left. So a name in the
shortlist is scored on H(0.20) + D(0.45) + W(0.35), and a name outside it on
D + W renormalised to 1.0 — and then the two are sorted against each other in
one list.

The perverse consequence: a name whose hourly trend *disagreed* is penalised
relative to a name that simply never had hourly fetched. Names ranked 81+ can
leapfrog names in the top 80 purely because they were measured on fewer
dimensions. There's a discontinuity in the sort key at exactly position 80.

### 4.4 Partial-window moving averages

`sma()` uses `min_periods=max(2, n // 2)`, so a "200MA" silently returns a
100-bar mean when only 100 bars exist. On daily this is mostly covered by
`min_history_bars: 260`, but the same function is used on weekly and hourly
where nothing guards it. A label that says 200 should either be 200 or be `NaN`.

### 4.5 Neutral defaults leak free points into the score

- `volume_ratio()` returns `1.0` when there's insufficient data. That value lands
  exactly inside `ratio_ideal_low..high`, scoring the **full 4/4**.
- `accumulation_ratio()` returns `0.5` on no signal → 2 of 8 points.
- `volume_trend()` returns `0.0` on short input → 0 of 2.

A name with thin or broken data is scored as though it had ideal volume
characteristics, rather than being flagged as unmeasured. Missing data should
propagate as missing, not as the most favourable value in range.

### 4.6 Short detectors can't be disabled independently

`detect_all()` resolves `CONFIG_KEY[name]` before checking `enabled`, so
`bear_flag` is gated by `patterns.bull_flag.enabled`, `three_crows` by
`three_soldiers`, and so on. Given §2 says the two 3-candle detectors are the
weakest of the twelve and `three_crows` is by far the worst single one, not
being able to turn it off alone is an immediate practical problem.

Also note the short detectors reuse the long thresholds wholesale. `bear_flag`
uses `min_pole_gain` for a *drop*, and drops and rallies are not symmetric —
downside moves are faster and more volatile. The mirroring is structurally
correct but the parameters were never re-tuned for the other side.

### 4.7 `accumulation_ratio` ignores gaps

It counts heavy-volume days where `Close > Open`. That measures the intraday
session only. A stock that gaps down 4% and then closes 1% above its open is
counted as an accumulation day. `Close > previous Close` would be a truer
measure of who won the day. (The backtest found no value in this feature either
way, so this is a correctness note, not a performance one.)

### 4.8 Already-triggered setups are published as if actionable

`scan.py` admits detections down to `dist_atr > -1.0`, i.e. up to one full ATR
*through* the trigger. Those rows print an Entry that is already gone and a Stop
measured from a price that no longer applies. `To Trig%` goes negative to signal
it and `score_readiness` drops proximity points to 1.0 — so it's handled, not
hidden. But it is the single easiest way to misread the page at 9:20am, which is
why the new report renders negative `To Trig%` in red.

---

## 5. Things that are simply absent

### 5.1 Earnings dates — the biggest practical gap

Nothing in the scanner knows when a company reports. A flat base that breaks out
on the morning of an earnings release is not the setup the pattern describes;
it's a binary event wearing a chart pattern.

Rough magnitude: with quarterly reporting, roughly 1 name in 13 has earnings in
any given two-week window. A 22-name list will routinely contain **1–3 names
reporting inside your holding horizon**, and the backtest's 10-day forward
window silently swallows those events as if they were pattern outcomes.

This is also the cheapest thing to fix. You already have a Financial Modeling
Prep connector available, and yfinance exposes `Ticker.calendar`. A single
`earnings_in_days` column, with anything under 5 flagged, would remove the most
common way this list produces a surprise.

### 5.2 Borrow availability on the short side

Half the detectors produce shorts. Nothing checks whether the name is
borrowable, or at what rate. S&P 400/600 constituents are routinely hard-to-
borrow, and the scanner will happily rank one 96.0 at the top of the page.

### 5.3 Correlation and sector concentration

`one_per_ticker` prevents the same ticker appearing twice. Nothing prevents the
list being one bet expressed eleven ways. The 2026-07-31 output has APA, VLO and
EOG — three energy names — plus AVGO, NTAP and ZBRA in tech hardware. Read as 22
independent ideas, that list is closer to 8. A sector cap, or just showing the
sector column, would make the concentration visible.

### 5.4 Trading-day awareness

Nothing checks whether today was a trading day. Run on a holiday, the scan
happily re-publishes the previous session's data under today's date. (The new
report now shows the actual last bar date and how old it is, which surfaces this
rather than preventing it.)

---

## 6. Code defects — all four fixed

**6.1 Failed download batch silently dropped up to 100 tickers.** `data.py`
caught the exception, printed *"retrying one at a time"*, and then did not
retry — every symbol in the failed chunk was skipped with no error surfaced.
Since `yf.download` also returns NaN columns rather than raising on partial
failures, `_extract()` returned `None` and those names vanished too. A scan
could silently lose 11% of its universe and print no warning.
**Fixed:** per-symbol retry, then stale-cache fallback, then an explicit warning
naming what was excluded and why.

**6.2 Dead branch.**
`df = _extract(raw, t) if len(chunk) > 1 else _extract(raw, t)` — both branches
identical. **Fixed.**

**6.3 No staleness check.** A cache that quietly stopped updating produced a
confident, wrong scan with no indication anything was off. **Fixed:** new
`staleness_report()`; `run_scan.py` now drops any symbol behind the consensus
last bar, warns, and passes the real bar date through to the report.

**6.4 `arrows()` produced corrupt H/D/W badges.** `tf_state()` returns the label
`"n/a"` for an unavailable timeframe, and `arrows()` joins the three trends with
`"/"`. The `/` inside `"n/a"` meant the string became four fields, and the
report's badge renderer — which split on `"/"` — shifted every badge one slot
right. **Daily's trend was displayed under the weekly label.** Silent, and it
triggered exactly when hourly data was missing, which is whenever a name fell
outside the top-80 shortlist or the hourly fetch failed. **Fixed** in both
`mtf.py` (labels no longer contain `/`, plus a new `trend_list()`) and
`report.py` (badges built from an explicit 3-element list, never from a string
split).

---

## 7. What I'd actually do next

In order of value per hour spent:

1. **Add earnings dates.** Cheapest fix, largest practical effect. Flag anything
   reporting within 5 trading days and exclude it from the backtest windows too.
2. **Fix the survivorship bias**, or stop quoting backtest numbers. Everything in
   §2 and in `research/BACKTEST_FINDINGS.md` is measured on a sample that excludes the
   losers. This is the difference between "unproven" and "unmeasurable."
3. **Add a within-date comparison to `summarize()`.** One function, and it
   removes the single most likely source of false findings in this project.
   Every bucket table should show both pooled and within-date results.
4. **Decide what `rank` is for.** It doesn't rank outcomes — tested, twice, on
   two different sort keys. That's fine if it's an *attention* ordering rather
   than a *quality* ordering, but then say so and stop weighting alignment at
   40% when alignment is measurably inert. A simpler key — proximity to trigger
   plus ADR — would be more honest and no worse.
5. **Split the pattern config so short detectors can be disabled alone**, then
   turn off `three_crows` and `three_soldiers` and see whether the rest improves.
6. **Scale the MA periods per timeframe** (4/40 weekly, 140/1400 hourly) so
   "H/D/W agree" means something.
7. **Add slippage** to `forward_outcome` — even a flat 15bp each way. It won't
   change the rankings, but it will change whether a 1.5R target looks viable.

And the thing the README already says, which the data supports: keep a log of
what you actually take. Fifteen scan dates can't resolve a 1pp edge, and neither
can forty-one. Your own filled trades are a smaller sample but they measure the
right thing.

---

*Nothing here is financial advice. The measurements in §2 are from a
survivorship-biased universe over 15 scan dates and should be read as
directional, not conclusive.*
