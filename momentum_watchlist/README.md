# Momentum Watchlist

A live, good-looking day-trading watchlist. It finds today's in-play small/mid-cap
movers, ranks them, and builds a card page you open on your phone. Runs 24/7 on your
Dell: rescans every few minutes while the market is open, idles nights and weekends,
and pushes each update to your GitHub Pages URL.

**It does not trade or predict. It hands you a list to study. You do the trading.**

## Setup (once)

```bash
pip install -r requirements.txt
```

No API key. Data is free from Yahoo Finance.

## Try it right now (offline)

```bash
python scanner.py --demo
```

Opens nothing — it writes `docs/index.html`. Double-click that file to see the
page with sample data (cards, sorting, the sizing calculator, copy buttons).

## Run it for real

```bash
python scanner.py --once                # one live scan -> docs/index.html
python scanner.py --loop                # run forever, market-hours aware
python scanner.py --loop --publish      # ...and push to your phone URL each scan
```

For daily use, just leave **run_24_7.bat** running on the Dell (it does
`--loop --publish`). To start it automatically at login:

```bat
schtasks /create /tn "Momentum Watchlist" ^
  /tr "C:\Users\shrek\Desktop\DT_SCANNER\momentum_watchlist\run_24_7.bat" ^
  /sc onlogon
```

Getting it on your phone is a one-time GitHub Pages step — see **PUBLISHING.md**.

## What each card shows

| Field | Meaning |
|---|---|
| SCORE | Relative momentum rank for this list (% move weighted by relative volume). Not a probability. |
| PRICE / CHG | Last price and today's % move. |
| RVOL | Relative volume — today vs its normal. The single most important "is anyone here" filter. |
| $VOL | Dollar volume (liquidity). |
| GAP | Open vs prior close. |
| DAY LOW / HIGH | Intraday range — your reference levels. The bar shows where price sits in the range. |
| ADR | Average daily range % — how much room it has to move. |
| SHARES / POSITION | Risk-based size from your Account $ + Risk % inputs and a suggested stop. |
| STOP ≈ | Suggested stop (about half the ADR). Set your real stop on the chart. |

The three inputs at the top (Account $, Risk %, Max position %) recompute share
sizes live and are remembered on your device. Use the copy buttons to paste
symbols straight into a ThinkorSwim watchlist.

## Tuning

All knobs are in the `CONFIG` block at the top of `scanner.py`:

| Setting | Default | Meaning |
|---|---|---|
| `min_price` / `max_price` | 1 / 20 | Your price range. |
| `min_change_pct` | 5 | How big a move counts as in play. |
| `min_rel_volume` | 1.5 | Volume vs normal. Raise to tighten. |
| `max_market_cap` | 3B | Skip megacap name brands. |
| `include_shorts` | True | Show short candidates too. |
| `top_n` | 24 | Names on the list. |
| `refresh_minutes` | 5 | Rescan cadence during market hours. |

## Honest limits

- The list is an **attention filter**, not buy signals. A name being here just
  means "pull up the chart."
- Yahoo data is regular-hours/last-session, not a true pre-market tick feed. Best
  used from the open onward.
- Score orders THIS list on THIS refresh. It is not a prediction and has no
  backtested edge — don't treat a high score as "this one will work."
- Not financial advice.
