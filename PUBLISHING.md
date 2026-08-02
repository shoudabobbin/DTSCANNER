# Putting the watchlist on the web

The scan already writes `docs/index.html` — one self-contained file, no server,
no build step, no dependencies. All that's left is getting that file to a URL.

Two options. Pick one.

---

## Option A — GitHub Pages (recommended)

Free, versioned, and updates itself every evening once it's wired up.

### One-time setup, about five minutes

**1. Create a repo on GitHub.** Public is free. Private also works if you have
any paid personal plan.

> A public repo means anyone with the URL can read your watchlist. It contains
> no credentials — `data_cache/` and `reports/` are already gitignored — but the
> page itself is readable. If that bothers you, use a private repo or Option B.

**2. From `C:\Users\shrek\Desktop\DT_SCANNER`:**

```bat
git init
git add .
git commit -m "scanner"
git branch -M main
git remote add origin https://github.com/YOURNAME/YOURREPO.git
git push -u origin main
```

**3. On GitHub:** Settings → Pages → Source = **Deploy from a branch**,
Branch = **main**, Folder = **/docs** → Save.

**4. Wait about a minute.** Your page is live at:

```
https://YOURNAME.github.io/YOURREPO/
```

**5. On your phone**, open that URL and add it to your home screen. It's a
single file, so it loads instantly and still works if you're offline.

### Daily operation

`run_daily.bat` now does the whole thing:

```
scan  →  write docs/index.html  →  git commit  →  git push  →  live in ~60s
```

You already have it registered with Task Scheduler. If not:

```bat
schtasks /create /tn "DT Scanner" /tr "C:\Users\shrek\Desktop\DT_SCANNER\run_daily.bat" ^
         /sc weekly /d MON,TUE,WED,THU,FRI /st 17:30
```

17:30 is deliberate — Yahoo needs time after the close to settle the final daily
bar. Running earlier can pick up an incomplete bar for the session that just
ended.

To publish by hand at any point:

```bat
python publish.py            # commit + push docs/
python publish.py --dry-run  # show what it would do
python publish.py --setup    # reprint these instructions
```

`publish.py` only ever touches `docs/`. A failed push can't affect your code or
your data cache, and if the push fails the commit is still saved locally.

### Making sure only one machine publishes

Two clones pushing to one repo diverge. Git will reject the second push rather
than corrupt anything, so the damage is a stale page and a silent failure in a
log you aren't reading — but that's still a bad way to find out.

`publish.py` enforces this rather than leaving it to memory. On the machine that
should own publishing:

```bat
python publish.py --claim
git add config.yaml
git commit -m "publish from DELL-TOWER"
git push
```

That writes the machine's hostname into `config.yaml` under
`output.publisher_host`. Every other clone refuses to push as soon as it pulls
that file:

```
Not the publisher — skipping push.
  this machine : SHREK-LAPTOP
  publisher    : DELL-TOWER   (config.yaml -> output.publisher_host)

The scan still ran and docs/index.html is up to date locally.
```

The check runs **before** anything is committed, so a non-publisher clone leaves
no trace at all — no dangling commit to clean up later. It also exits 0, because
"this machine doesn't publish" isn't a failure; `run_daily.bat` still succeeds
and you still get a local page for development.

To see where things stand on any machine:

```bat
python publish.py --who
```

To move publishing to a different machine, run `--claim` there and push. The old
publisher stands down the next time it pulls.

Leaving `publisher_host: null` means no restriction — fine if you only ever have
one clone.

---

## Option B — Netlify Drop (no account, no git)

Go to <https://app.netlify.com/drop> and drag the `docs` folder onto the page.
You get a URL immediately, with no signup.

The catch: it's a manual upload, so you'd re-drag the folder each evening. Fine
if you want to try the page before committing to the GitHub setup.

---

## What the page gives you

- **Green = long, red = short**, as a left border on every card and row.
- **Staleness banner**, computed live in your browser each time you open it. It
  tells you how many hours old the data is and reminds you the levels have not
  been re-validated against this morning's pre-market. That matters: a gap
  through the entry means the printed level is gone and the risk on the printed
  stop is no longer what it says.
- **Level ladder** on each card — stop, entry, current price, T1, T2 on one
  scale, with the risk leg in red and the reward leg in green. Tells you at a
  glance whether price has already run past the entry.
- **Filter by side**, search by ticker, and six sort orders. "Closest to
  trigger" is the useful one if you're short on time.
- **Cards or table view.** Cards on a phone, table on a monitor.
- **Click "detail"** on any card for the full scoring breakdown and per-timeframe
  MA distances.
- Dark or light automatically, following your system setting.

### Reading it in the morning

The honest use is: this is a list of charts worth opening, ordered by a key that
has been tested and does **not** predict outcomes (see `FLAWS.md` §2). Use the
sort control rather than trusting the default order, check the H/D/W badges
against what you see on the actual chart, and re-check the entry against the
pre-market before you act on any level.

---

## Config

```yaml
output:
  publish_dir: "docs"   # set to null to stop writing the published copy
```

Dated archive copies still go to `reports/watchlist_YYYY-MM-DD.{csv,html}`.
`docs/index.html` is overwritten every run, so the published page is always the
latest scan.
