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
import platform
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
CONFIG = ROOT / "config.yaml"

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


# --------------------------------------------------------- publisher lock

def this_host() -> str:
    return platform.node().strip()


def declared_publisher() -> str | None:
    """Read output.publisher_host without importing yaml.

    Deliberately a regex rather than a yaml load: this check has to work even
    if the config is half-edited or pyyaml is missing on a fresh clone. If it
    can't read the line it returns None, which means "no restriction" — the
    lock should never be the reason a scan can't publish.
    """
    try:
        text = CONFIG.read_text(encoding="utf-8")
    except Exception:
        return None
    m = re.search(r"^\s*publisher_host:\s*(.+?)\s*$", text, re.M)
    if not m:
        return None
    val = m.group(1).strip().strip('"').strip("'")
    if val.lower() in ("null", "~", "", "none"):
        return None
    return val


def claim() -> int:
    """Record this machine as the sole publisher."""
    host = this_host()
    if not CONFIG.exists():
        print(f"config.yaml not found at {CONFIG}")
        return 1
    text = CONFIG.read_text(encoding="utf-8")
    if not re.search(r"^\s*publisher_host:", text, re.M):
        print("No `publisher_host:` key in config.yaml — add it under `output:`.")
        return 1

    current = declared_publisher()
    text = re.sub(r"^(\s*publisher_host:).*$", rf'\1 "{host}"', text,
                  count=1, flags=re.M)
    CONFIG.write_text(text, encoding="utf-8")

    if current and current.lower() != host.lower():
        print(f"Publisher moved: {current} -> {host}")
    else:
        print(f"Publisher set to: {host}")
    print("\nCommit and push this so the other clones pick it up:")
    print('  git add config.yaml && git commit -m "publish from '
          f'{host}" && git push')
    return 0


def check_publisher() -> bool:
    """True if this machine is allowed to push."""
    want = declared_publisher()
    if want is None:
        return True
    host = this_host()
    if want.lower() == host.lower():
        return True
    print(f"Not the publisher — skipping push.")
    print(f"  this machine : {host}")
    print(f"  publisher    : {want}   (config.yaml -> output.publisher_host)")
    print("\nThe scan still ran and docs/index.html is up to date locally.")
    print(f"To move publishing to this machine: python publish.py --claim")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--setup", action="store_true")
    ap.add_argument("--claim", action="store_true",
                    help="make THIS machine the only one allowed to publish")
    ap.add_argument("--who", action="store_true",
                    help="show which machine is the designated publisher")
    ap.add_argument("--message", default=None)
    args = ap.parse_args()

    if args.setup:
        print(SETUP)
        return 0

    if args.claim:
        return claim()

    if args.who:
        want = declared_publisher()
        print(f"this machine : {this_host()}")
        print(f"publisher    : {want or 'unrestricted (any machine may push)'}")
        return 0

    # Refuse to push from anywhere but the designated machine. This runs before
    # anything is committed, so a non-publisher clone leaves no trace at all.
    if not check_publisher():
        return 0        # not an error — the scan succeeded, publishing isn't ours

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
