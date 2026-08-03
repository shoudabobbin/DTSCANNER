# Getting it running — complete runbook

Written August 1 2026. Four phases: finish on the laptop, move to the Dell,
automate it, then set up trading. Do them in order — later steps assume earlier
ones worked.

Every command block is copy-pasteable into Command Prompt.

---

## Phase A — Laptop: push everything to GitHub

The laptop is where today's edits live. Nothing is on GitHub or the Dell yet.

### A1. Open Command Prompt in the project

```bat
cd C:\Users\shrek\Desktop\DT_SCANNER
```

### A2. Confirm the edits are actually on disk

```bat
findstr /C:"copySyms" scanner\report.py
findstr /C:"sp600" config.yaml
```

Both should print a matching line. If either prints nothing, stop — the file
didn't save and the rest of this won't work.

### A3. Decide about `REVIEW_TRADER.md`

There's an untracked 311-line file in the folder — an independent audit that
cross-checks the numbers in `FLAWS.md`. Read it or don't, but know that step A5
will commit it. To exclude it instead:

```bat
echo REVIEW_TRADER.md >> .gitignore
```

### A4. Normalise line endings

`.gitattributes` is already written. This applies it to files already in git:

```bat
git add --renormalize .
```

Expect this to touch most files once. It's cosmetic and it stops `git diff` from
reporting hundreds of phantom changed lines from here on.

### A5. Commit and push

```bat
git add -A
git commit -m "position sizer, ToS symbol export, sp600 universe, line endings"
git push
```

If the push is rejected with "fetch first", run `git pull --rebase` then
`git push` again.

### A6. Remove the laptop's scheduled task, if it has one

```bat
schtasks /delete /tn "DT Scanner" /f
```

"cannot find the file specified" means there wasn't one. Fine either way.

---

## Phase B — Dell: pull and prove it works

### B1. Open Command Prompt on the Dell

```bat
cd C:\Users\Holden\DTSCANNER
```

### B2. Pull

```bat
git pull
```

### B3. Verify the new code arrived

```bat
findstr /C:"copySyms" scanner\report.py
findstr /C:"sp600" config.yaml
python publish.py --who
```

The first two must print matches. `--who` must show the **same machine name on
both lines** — that's the publisher lock confirming the Dell owns publishing.

### B4. Make sure dependencies are present

```bat
pip install -r requirements.txt
```

### B5. Run it by hand — this is the real test

```bat
run_daily.bat
```

**This run is slow.** Adding sp600 means ~600 new symbols to download on top of
the existing universe, and the whole thing re-fetches. Expect 10–20 minutes.
Later runs are much faster because of the cache.

Watch for these lines. They're new and they matter:

- `WARNING: N symbols served from STALE cache` — download failures, fell back
  to old data
- `WARNING: N symbols unavailable and excluded` — dropped entirely
- `WARNING: N symbols behind the ... consensus bar` — stale data, excluded

A handful is normal. Hundreds means something is wrong with the feed.

### B6. Check the log

```bat
type reports\scan_log.txt
```

Should end with a "Morning list (N names)" table and a `published:` line.

### B7. Check the live page

Open <https://shoudabobbin.github.io/DTSCANNER/> — give it about 60 seconds
after the push. Confirm all five:

1. Header date matches the last trading day
2. A **sizing bar** below the filters: Account $ / Risk % / Max position %
3. Three **thinkorswim copy buttons** below that
4. Short cards say **"Size (whole)"** with a share count, longs show a dollar
   amount
5. The **H/D/W badges** show `ho`/`up`/`do` etc, not `–` — dashes mean hourly
   data didn't download

### B8. Set your account numbers

On the page, set Account $ = `2500`, Risk % = `1`, Max position % = `25`. These
save in that browser and persist. Every card then shows what to actually buy.

---

## Phase C — Dell: automate it

### C1. Register the task

```bat
schtasks /create /tn "DT Scanner" /tr "C:\Users\Holden\DTSCANNER\run_daily.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 17:30
```

17:30 is the Dell's **local** time. The rule is at least 90 minutes after the
16:00 ET close, so Yahoo has settled the final daily bar.

### C2. Fix the two settings `schtasks` can't set

Open Task Scheduler:

```bat
taskschd.msc
```

Find **DT Scanner** in the library → right-click → Properties:

- **Conditions** tab → **uncheck** *Start the task only if the computer is on AC
  power*. It's checked by default and will silently skip runs.
- **Settings** tab → **check** *Run task as soon as possible after a scheduled
  start is missed*.

Click OK.

### C3. Test the schedule without waiting

```bat
schtasks /run /tn "DT Scanner"
```

Then confirm it actually ran:

```bat
schtasks /query /tn "DT Scanner" /v /fo LIST | findstr /C:"Last Run" /C:"Last Result"
```

`Last Result: 0` means success.

### C4. Confirm tomorrow

Open the page after 18:00. The header date should have advanced. If it hasn't,
read `reports\scan_log.txt` — the failure will be in there.

---

## Phase D — Trading setup

Independent of the software. Do it whenever.

### D1. thinkorswim

- Open a Schwab account if you don't have one.
- Request **margin approval** — required for shorting. The $2,000 minimum
  equity applies; your $2,500 clears it.
- Ask Schwab directly whether they've implemented the new intraday margin rule
  from [Regulatory Notice 26-10](https://www.finra.org/rules-guidance/notices/26-10).
  It killed the $25,000 pattern-day-trader minimum effective June 4 2026, but
  brokers may phase in until **October 20 2027**. If yours hasn't, the old
  3-day-trades-per-5-days limit still binds you.

### D2. Paper trade in paperMoney, not TradingView

Switch from TradingView's simulator to thinkorswim **paperMoney**. Same
platform, same order tickets, same hard-to-borrow rejections you'll hit live.
TradingView won't reject an unborrowable short; paperMoney will, and half your
list is shorts.

### D3. Daily workflow

1. Open the page before the open.
2. Click **Copy longs** (or all).
3. In thinkorswim, right-click a watchlist → Import Symbols → paste.
4. Work down the list on real charts. The Size figure tells you what to buy.
5. **Re-check the entry against pre-market.** The levels are from yesterday's
   close and have not been re-validated — the banner at the top says how stale
   they are. A gap through the entry means the level is gone and the printed
   stop no longer carries the risk it claims.

### D4. Keep a log

Record, for every trade you take: the entry the scanner printed, the fill you
actually got, and the outcome. After a few dozen trades that slippage number
tells you more about whether this is viable than any backtest — see `FLAWS.md`
§2 for why the backtests can't settle it.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Page date never advances | Task didn't run, or push failed | `type reports\scan_log.txt` |
| `Not the publisher — skipping push` | Wrong machine | Correct — only the Dell should publish |
| Push hangs forever | Git wants auth, nobody's watching | Run `git push` by hand once, then `git config --global credential.helper store` |
| H/D/W badges all `–` | Hourly download failed | Usually transient; check the log for hourly errors |
| Hundreds of stale/excluded warnings | Yahoo rate-limiting | Wait, re-run. Consider a real data API if it persists |
| `python` not recognised | PATH | Reopen Command Prompt; check with `python --version` |
| Nothing qualified today | Normal | Most days are quiet. `python run_scan.py --min-score 15` to see near-misses |

---

## What to remember

The scanner has **no demonstrated edge** — `FLAWS.md` §2 covers this in detail.
Market-beat rate was 47.3% across 8,781 detections, and the `rank` key that
orders the page has no measurable relationship to forward returns. It is a tool
for finding charts worth looking at, not a list of trades worth taking. The
judgment stays yours, and position sizing matters more than anything on the
page.
