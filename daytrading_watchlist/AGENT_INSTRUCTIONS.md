# Instructions for the agent editing the DT_SCANNER repo

**Goal:** Make the GitHub Pages site publish the **day-trading momentum
watchlist** (small/mid-cap in-play movers) instead of the swing-setup list,
reusing the existing publish pipeline unchanged.

**Do NOT** rebuild the publishing setup. `docs/` → GitHub Pages, `publish.py`,
`run_daily.bat`, and the Windows Task Scheduler job all already work. We are only
swapping which script generates `docs/index.html`.

The new engine already exists in the repo at:
`daytrading_watchlist/daytrading_watchlist.py`
It is a single self-contained script that pulls today's movers from Yahoo
Finance screeners (`yf.screen`), filters to small/mid-cap momentum names, ranks
them, and writes an HTML + CSV watchlist. It does not need an API key.

---

## Step 1 — Confirm prerequisites

- `requirements.txt` must include a recent `yfinance` (screener support needs
  `yfinance >= 0.2.40`; newer is fine) and `pandas`. Add/bump if missing.
- Everything else the script needs is standard library.

## Step 2 — Add a publish step to `daytrading_watchlist/daytrading_watchlist.py`

The script currently writes only dated files into `watchlists/`. Add the ability
to also write the repo-root `docs/index.html` and `docs/watchlist.csv` that
GitHub Pages serves.

**2a.** Near the top of the file (after the imports), add:

```python
# Repo root = one level above this script's folder (daytrading_watchlist/)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def publish_to_docs(tone, rows):
    """Write the page GitHub Pages serves: <repo>/docs/index.html + watchlist.csv"""
    docs = os.path.join(REPO_ROOT, "docs")
    os.makedirs(docs, exist_ok=True)
    open(os.path.join(docs, ".nojekyll"), "a").close()   # keep Pages from running Jekyll
    write_html(tone, rows, os.path.join(docs, "index.html"))
    write_csv(rows, os.path.join(docs, "watchlist.csv"))
    print(f"Published to {os.path.join(docs, 'index.html')}")
```

> If you instead move `daytrading_watchlist.py` to the repo root next to
> `run_scan.py`, change `REPO_ROOT` to
> `os.path.dirname(os.path.abspath(__file__))`.

**2b.** In `main()`, add a `--publish` flag to the argparse block:

```python
ap.add_argument("--publish", action="store_true",
                help="Also write docs/index.html for GitHub Pages")
```

**2c.** In `main()`, after the existing `write_html(...)` / `write_csv(...)`
calls that save the dated files, add:

```python
    if a.publish:
        publish_to_docs(tone, rows)
```

`write_html` and `write_csv` already exist in the file with signatures
`write_html(tone, rows, path)` and `write_csv(rows, path)` — reuse them, don't
duplicate.

## Step 3 — Repoint `run_daily.bat` to the new engine

In `run_daily.bat`, find the line that runs the swing scan (something like
`python run_scan.py ...`) and replace **only that line** with:

```bat
python daytrading_watchlist\daytrading_watchlist.py --publish
```

Leave every other line — the `git add` / `git commit` / `git push` block — exactly
as it is. The flow stays: scan → write `docs/index.html` → commit → push.

## Step 4 — Leave `publish.py` and Pages settings alone

`publish.py` pushes the `docs/` folder; it does not care what generated the
file. No change. GitHub Pages (Settings → Pages → branch `main`, folder `/docs`)
also stays as-is.

## Step 5 — Retire the swing engine (optional, recommended)

Nothing should call `run_scan.py` anymore. You can leave the swing files
(`run_scan.py`, `scanner/`, `config.yaml`, `backtest.py`) in place — they're
harmless once unused — or delete them for tidiness. Do NOT delete `publish.py`,
`run_daily.bat`, `docs/`, or `.nojekyll`.

---

## Optional variant — keep BOTH pages instead of replacing

If the swing page should stay live too, don't overwrite `docs/index.html`.
Instead, in `publish_to_docs`, write to a subfolder:

```python
    docs = os.path.join(REPO_ROOT, "docs", "daytrading")
```

The day-trading list is then served at `https://<user>.github.io/<repo>/daytrading/`
and the swing page stays at the root. In that case, keep `run_scan.py` in
`run_daily.bat` and add the new `python daytrading_watchlist\... --publish` line
after it.

---

## Acceptance test (run before pushing)

1. `python daytrading_watchlist\daytrading_watchlist.py --publish`
2. Confirm `docs/index.html` was just regenerated (check the file's timestamp)
   and opens in a browser showing today's momentum names — NOT the swing setups.
3. Confirm `docs/watchlist.csv` updated and `docs/.nojekyll` still exists.
4. Run `run_daily.bat` end to end; confirm it scans, commits, and pushes.
5. Wait ~60s, load the Pages URL, confirm it shows the day-trading watchlist.

## Keep these facts intact (do not "fix" them away)

- The page is a **static snapshot**, updated only when the machine runs the
  scanner and pushes. GitHub Pages cannot scan live. This is expected.
- Best run around the market open on a weekday; the Task Scheduler time may need
  changing from the swing scanner's evening slot to a morning slot.
- The list is an **attention filter**, not buy signals. Keep the disclaimer in
  the HTML footer.
- Tuning knobs (price range, min % move, min relative volume, market-cap ceiling,
  list length, shorts on/off) all live in the `CONFIG` dict at the top of
  `daytrading_watchlist.py`.
