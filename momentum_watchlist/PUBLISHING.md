# Getting the watchlist on your phone (GitHub Pages)

This publishes to the **same repo you already have** (`DTSCANNER`), on a separate
branch called `gh-pages`, so your main branch and its history stay clean. Each
update is a single rolling commit (force-pushed), so you won't pile up hundreds
of commits a day.

The scanner does the git work for you. You only do the one-time steps below.

## One-time setup (about 3 minutes)

**1. Make sure the repo has its remote** (it already does):

```bat
cd C:\Users\shrek\Desktop\DT_SCANNER
git remote -v
```

You should see `origin  https://github.com/shoudabobbin/DTSCANNER.git`.

**2. First publish** — this creates the `gh-pages` branch and pushes the page:

```bat
cd C:\Users\shrek\Desktop\DT_SCANNER\momentum_watchlist
python scanner.py --once --publish
```

**3. Point GitHub Pages at the new branch.** On GitHub:
Settings → Pages → Source = **Deploy from a branch** → Branch = **gh-pages** →
Folder = **/(root)** → Save.

**4. Wait about a minute.** Your watchlist is live at:

```
https://shoudabobbin.github.io/DTSCANNER/
```

Open it on your phone and add it to your home screen. The page reloads itself
every few minutes, so it stays current while the Dell is running.

> This replaces your old swing page at that URL with the day-trading watchlist.
> The swing files on the `main` branch are not deleted — you're just serving the
> `gh-pages` branch now. To go back, switch the Pages source back to `main /docs`.

## Daily operation

Leave **run_24_7.bat** running on the Dell. It loops `--publish`, so every scan
during market hours updates the live page automatically. Nothing else to do.

## If a push ever fails

The loop keeps running and keeps writing `docs/index.html` locally even if a
push fails (e.g., network blip) — it just tries again next cycle. If it's stuck,
check that `git push` works from the repo manually, then restart the bat.
