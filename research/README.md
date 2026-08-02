# Research artifacts

The evidence behind `FLAWS.md` and `BACKTEST_FINDINGS.md`. These live here
rather than in `reports/` because `reports/` is gitignored — it holds generated
output that changes every night, and these don't. They are the record of what
was actually measured, so they belong in version control.

| File | What it is |
|---|---|
| `BACKTEST_FINDINGS.md` | The original write-up. Long side only. |
| `backtest_2023-2026_longonly.csv` | 5,705 detections · 247 tickers · 41 scan dates · Apr 2023 – Jun 2026. The data behind that write-up. |
| `validation_2023-2026_bothsides.csv` | 8,781 detections · 893 tickers · 15 scan dates · Apr 2023 – Jul 2026. The data behind `FLAWS.md` §2. |

## Why there are two

`backtest_2023-2026_longonly.csv` has no `side`, `rank`, `align` or `adr_pct`
column. It predates the short book and the ranking rebuild, so it cannot say
anything about six of the twelve detectors or about the sort key that currently
decides what appears on the page. `BACKTEST_FINDINGS.md` is still correct about
what it measured; it just measures a scanner that no longer exists.

`validation_2023-2026_bothsides.csv` was produced to close that gap. Both sides,
all twelve detectors, and the `rank` column recorded so it can be tested.

## Reproducing the validation run

Hourly is disabled — Yahoo only serves ~730 days of intraday history, so it
can't be reconstructed point-in-time for older scan dates. Everything else is
the shipped config.

```bash
python backtest.py --limit 900 --step 58 --save research/validation_rerun.csv
```

Your numbers will differ from mine. `universe.py` scrapes *current* index
membership, so the constituent list drifts every time you run it, and with it
the survivorship bias described in `FLAWS.md` §3.1.

## The one analysis to run on these files

Detections are clustered by scan date — every detection on one day shares one
market. Any comparison that pools across dates is partly measuring which days
happened to be good, not whether the feature works.

```python
import pandas as pd
d = pd.read_csv('research/validation_2023-2026_bothsides.csv')

# pooled — looks meaningful, mostly isn't
d.groupby(d['rank'] // 5 * 5).hold_win.mean()

# within-date — compares like against like, same day, same market
for dt, g in d.groupby('date'):
    g = g.sort_values('rank', ascending=False); h = len(g) // 2
    print(dt, round(g.head(h).hold_return.mean() - g.tail(h).hold_return.mean(), 4))
```

The first produces a clean monotonic-looking table. The second shows the effect
isn't there. That gap is the single most important thing in this folder.
