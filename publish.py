#!/usr/bin/env python3
"""Push the freshly-generated watchlist page to GitHub Pages.

Commits whatever is in `docs/` and pushes it. Nothing else in the repo is
touched, so a failed push never risks your code or your data cache.

    python publish.py                 # commit + push docs/
    python publish.py --dry-run       # show what would happen
    python publish.py --setup         # print one-time setup instructions

One-time setup is in PUBLISHING.md.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"

SETUP = """
One-time setup — about five minutes
===================================

1. Make a GitHub repo. It can be private; GitHub Pages works on private repos
   for personal accounts on any paid plan, and on public repos for free. If you
   want it free and are fine with the page being reachable by URL, use a public
   repo — but note the page will be publicly readable by anyone with the link.

2. In this folder:

       git init
       git add .
       git commit -m "scanner"
       git branch -M main
       git remote add origin https://github.com/<you>/<repo>.git
       git push -u origin main

3. On GitHub: Settings -> Pages -> Source = "Deploy from a branch",
   Branch = main, Folder = /docs. Save.

4. Wait ~1 minute. Your page is at:

       https://<you>.github.io/<repo>/

5. Add it to your phone's home screen. It loads instantly and works offline
   after the first visit, because the page is a single self-contained file.

Notes
-----
* `.gitignore` already excludes `data_cache/`. Keep it that way — it is ~56 MB
  of parquet and has no business in git.
* Every run overwrites `docs/index.html`, so the published page always shows
  the most recent scan. Dated archive copies stay in `reports/`.
* If you would rather not use GitHub at all: `docs/index.html` is a single
  self-contained file. Drag the `docs` folder onto https://app.netlify.com/drop
  and you get a URL with no account and no git.
"""


def git(*args, check=True, capture=True):
    return subprocess.run(["git", *args], cwd=ROOT, check=check,
                          capture_output=capture, text=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--setup", action="store_true")
    ap.add_argument("--message", default=None)
    args = ap.parse_args()

    if args.setup:
        print(SETUP)
        return 0

    page = DOCS / "index.html"
    if not page.exists():
        print(f"No page to publish — {page} does not exist.")
        print("Run `python run_scan.py` first, and make sure config.yaml has "
              "output.publish_dir set to 'docs'.")
        return 1

    if not (ROOT / ".git").exists():
        print("This folder is not a git repository yet.")
        print("Run `python publish.py --setup` for the one-time instructions.")
        return 1

    try:
        git("rev-parse", "--abbrev-ref", "HEAD")
    except subprocess.CalledProcessError as exc:
        print(f"git error: {exc.stderr.strip()}")
        return 1

    status = git("status", "--porcelain", "docs").stdout.strip()
    if not status:
        print("docs/ unchanged — nothing to publish.")
        return 0

    msg = args.message or f"watchlist {datetime.now():%Y-%m-%d %H:%M}"
    if args.dry_run:
        print("would commit:")
        print(status)
        print(f'would run: git commit -m "{msg}" && git push')
        return 0

    git("add", "docs")
    git("commit", "-m", msg)
    try:
        r = git("push", check=True)
    except subprocess.CalledProcessError as exc:
        print("Commit succeeded but push failed:")
        print((exc.stderr or exc.stdout or "").strip())
        print("\nThe commit is saved locally — fix the remote and run "
              "`git push` yourself.")
        return 1

    print("published.")
    if r.stderr.strip():
        print(r.stderr.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
