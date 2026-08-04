# Day-Trading Watchlist Generator

A dead-simple morning watchlist. It gives you a short list of in-play
small/mid-cap momentum stocks to pull up and study each day. It does **not**
trade or predict — you do all the trading. It's just a "what's worth looking
at today" list.

## Setup (once)

```bash
pip install yfinance pandas
```

No API key. No account. Data comes free from Yahoo Finance.

## Run it

```bash
python daytrading_watchlist.py          # today's watchlist
python daytrading_watchlist.py --demo   # offline sample, no network
python daytrading_watchlist.py --shorts # include short candidates too
```

On Windows you can just double-click **run_watchlist.bat** — it runs the scan
and opens the list in your browser.

It writes a dated file to `watchlists/` (both `.html` and `.csv`). Open the
HTML. Run it in the morning around the open, and re-run every day — the list is
only good for the day it's built.

## What it does

1. Pulls today's movers from Yahoo's screeners (day gainers, small-cap gainers,
   most actives, aggressive small caps).
2. Keeps only names that are **in play**: in your price range, moved enough
   today, and trading on real relative volume.
3. Strips out ETFs, funds, warrants, and megacap name brands.
4. Ranks by momentum weighted by how unusual today's volume is.
5. For the top names, adds gap %, day range, and ADR%.
6. Writes the watchlist.

## Tuning

Open `daytrading_watchlist.py` and edit the `CONFIG` block at the top. The
knobs you'll actually touch:

| Setting | What it does |
|---|---|
| `min_price` / `max_price` | Your price range. Default $1–$20. |
| `min_change_pct` | How big a move counts as "in play". Default 5%. |
| `min_rel_volume` | Volume vs normal. Default 1.5x. Raise to tighten. |
| `max_market_cap` | Skip anything bigger (keeps it small/mid cap). Default $3B. |
| `include_shorts` | Add short candidates. Default off. |
| `top_n` | How many names on the list. Default 15. |

## Important

This is an **attention filter**, not a trade plan. It hands you names — you
still do the chart work: mark your levels, wait for the setup, size by risk.
A stock being on the list is not a reason to buy it. Not financial advice.
