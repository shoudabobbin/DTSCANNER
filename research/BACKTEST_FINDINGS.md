# Backtest findings — first run

**Sample:** 5,705 detections · 247 tickers · 41 scan dates · Apr 2023 → Jun 2026 · 10-day forward window
**Raw data:** `reports/backtest_detections.csv`

---

## Headline

**As configured, the scanner has no demonstrable edge.**

| | |
|---|---|
| Overall win rate | 52.7% |
| Market beat rate | **47.9%** |
| Avg 10-day return | +0.36% |

A market beat rate under 50% means the average detection underperformed simply
holding SPY over the same window. The win rate above 50% is not evidence of
anything — stocks drift up, and the sample period was mostly a bull market.

## The score does not rank

| Score band | n | Win rate | Market beat | Avg return |
|---|---|---|---|---|
| 20–25 | 3,225 | 52.7% | 47.5% | +0.29% |
| 25–30 | 2,012 | 52.0% | 48.0% | +0.35% |
| 30+ | 455 | 54.9% | 50.1% | +0.92% |

A 2.2-point spread, non-monotonic. For comparison, the article claimed 50.7% →
78% across its score bands. Nothing resembling that appears here.

No individual pattern separates either — all six land between 51.6% and 53.8%.

---

## Three candidate findings, all rejected by the holdout

Split at the midpoint: train = Apr 2023–Oct 2024, test = Nov 2024–Jun 2026.
Nothing was fitted on the test half.

### 1. Accumulation ratio — the heaviest-weighted feature — looked inverted

Train showed a clean monotonic relationship, pointing the **opposite** way from
the article's claim that high accumulation predicts breakouts:

| Accum band | <40% | 40–50% | 50–60% | 60–70% | >70% |
|---|---|---|---|---|---|
| **Train** win | 63.8% | 51.7% | 54.3% | 50.7% | **44.9%** |
| **Test** win | 56.7% | 58.3% | 52.9% | 52.4% | **53.8%** |

Flat in test. The >70% bucket goes from worst (44.9%) to middling (53.8%).
Inverting the weight raised top-decile win rate in train (55.4% → 60.6%) but in
test produced +3.3 win points and **−2.6 market-beat points**. A wash.

**Verdict: noise.** This is 8 of the 40 score points and the single claim the
Reddit post leaned on hardest (~82% as a filter). It is not supported here.

### 2. Market regime — reversed outright

| | bull_low | bull_high |
|---|---|---|
| **Train** | 64.3% win / 63.3% beat | 50.5% / 44.5% |
| **Test** | **44.0% win / 46.1% beat** | 52.1% / 47.5% |

Train reproduced the article's headline claim almost too well. Test flipped the
sign completely. This is the least trustworthy finding in the set, and it was
the most exciting one in train — which is exactly how overfitting presents.

### 3. Pattern height → magnitude

Train: mean MFE flat across height quintiles (4.0% → 5.0%).
Test: rising (4.0% → 8.0%).

Directionally right in one half, absent in the other. Not established.

---

## What this actually demonstrates

All three findings failed **direction consistency** — the same test the article
describes as its most valuable protection, the one that "eliminated more than
half of our apparent discoveries." That is what just happened, on the first
serious look, to every promising result in this sample.

The in-sample tables looked genuinely convincing. Monotonic curves, sensible
economic stories, respectable bucket sizes. They were noise. That is the single
most useful thing this run produced, and it is worth more than a watchlist.

## Limits of this test

Read these before concluding the underlying ideas are wrong — they are not
disproven, they are unsupported by a sample too thin to resolve them:

- 247 tickers, not 6,000
- 41 scan dates over ~3 years, versus 39,037 trades in the article
- Sample is 53% high-confidence-bull regime — a period artifact
- Scores above 35 are almost absent, so the high-conviction tier where the
  article claims its edge lives is untested here
- One split, one holdout. No bootstrap, no multiple-comparison correction

Resolving a 2–3 point edge needs far more data than this. The honest reading is
"unproven," not "disproven."

## Do not

- Trade the current watchlist as signal
- Tune `config.yaml` against this sample — it cannot support the weight
- Read the in-sample tables as encouraging

## Reasonable next steps

1. **More data before more tuning.** Full universe, 10+ years, `--step 3`.
   Costs hours of runtime, not judgment.
2. **Use it as a study tool.** Journal what it surfaces, mark up the charts by
   hand, compare against what your courses teach. The scanner is a good way to
   see a thousand setups quickly.
3. **Drop the scoring model, keep the detectors.** Use it purely to narrow 900
   names to ~50 worth looking at, and make the judgment call yourself.
