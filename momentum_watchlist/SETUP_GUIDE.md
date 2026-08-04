# Complete Setup Guide — Momentum Watchlist

Follow this top to bottom. You do the LAPTOP part once, the DELL part once, and
then it runs itself.

## The plan in one picture

```
LAPTOP  → pushes the code to GitHub (one time)
DELL    → clones the code, runs the scanner 24/7, updates your web page
PHONE   → opens the web page URL
```

- **Laptop** = the computer you built this on (where the code is now).
- **Dell** = the always-on machine that does the real work.
- Your live URL will be: **https://shoudabobbin.github.io/DTSCANNER/**

---

# PART 1 — ON YOUR LAPTOP  (about 5 minutes, one time)

Goal: get the new `momentum_watchlist` folder onto GitHub so the Dell can grab it.

**1.1** Open **Command Prompt**. (Press Start, type `cmd`, Enter.)

**1.2** Go to the repo:

```bat
cd C:\Users\shrek\Desktop\DT_SCANNER
```

**1.3** Tell git to ignore the scratch folders (so they don't clutter the repo):

```bat
echo momentum_watchlist/docs/>> .gitignore
echo .ghpages_wt/>> .gitignore
```

**1.4** Commit and push the new tool:

```bat
git add momentum_watchlist .gitignore
git commit -m "Add momentum day-trading watchlist"
git push
```

> If `git push` asks you to sign in, a GitHub window will pop up — sign in and
> authorize. (You already did this once for the swing scanner, so it may just work.)

**1.5 (optional) Preview it here first:**

```bat
cd momentum_watchlist
python -m pip install -r requirements.txt
python scanner.py --demo
```

Then open `C:\Users\shrek\Desktop\DT_SCANNER\momentum_watchlist\docs\index.html`
in your browser to see the page with sample data.

**Laptop done.** Everything else happens on the Dell.

---

# PART 2 — ON THE DELL  (about 15 minutes, one time)

## 2A. Install Python

1. Go to **https://www.python.org/downloads/** and download the latest Python 3.
2. Run the installer. **CHECK THE BOX "Add python.exe to PATH"** at the bottom —
   this matters. Then click **Install Now**.
3. Verify: open **Command Prompt** and run:

```bat
python --version
```

You should see `Python 3.x.x`. (If it says "not recognized," re-run the installer
and make sure the PATH box is checked.)

## 2B. Install Git

1. Go to **https://git-scm.com/download/win**, download, and install with all the
   default options (just keep clicking Next).
2. Verify in a new Command Prompt:

```bat
git --version
```

## 2C. Set your git identity (needed to save updates)

```bat
git config --global user.name "Holden"
git config --global user.email "holdentomanchek@gmail.com"
```

## 2D. Download your project

```bat
cd %USERPROFILE%\Desktop
git clone https://github.com/shoudabobbin/DTSCANNER.git
cd DTSCANNER\momentum_watchlist
```

## 2E. Install the requirements

```bat
python -m pip install -r requirements.txt
```

## 2F. First run + first publish

First prove it builds a page (offline, instant):

```bat
python scanner.py --demo
```

Now do the real first publish. This also signs the Dell into GitHub and creates
the `gh-pages` branch:

```bat
python scanner.py --once --publish
```

> On the first `--publish`, a **GitHub sign-in window pops up** — sign in and
> click Authorize. That's the Dell getting permission to update your page. It
> only happens once.

## 2G. Turn on the web page (on GitHub, any device)

1. Go to **https://github.com/shoudabobbin/DTSCANNER** → **Settings** → **Pages**.
2. Under **Source**, choose **Deploy from a branch**.
3. Branch = **gh-pages**, Folder = **/ (root)**, click **Save**.
4. Wait about a minute, then open **https://shoudabobbin.github.io/DTSCANNER/** —
   your watchlist is live.

> This makes the day-trading watchlist your live page instead of the old swing
> one. Nothing is deleted — to switch back, set Pages source to `main` `/docs`.

## 2H. Stop the Dell from sleeping

Settings → **System** → **Power** → set **Sleep** to **Never** (when plugged in),
so it keeps scanning while you're away.

## 2I. Start the 24/7 loop

**Simple way:** double-click **run_24_7.bat** in the
`Desktop\DTSCANNER\momentum_watchlist` folder and leave that window open. It will
rescan every 5 minutes during market hours and idle otherwise.

**Auto-start way (so it restarts itself after a reboot):** in Command Prompt,
adjusting the username if the Dell isn't logged in as `shrek`:

```bat
schtasks /create /tn "Momentum Watchlist" /tr "\"%USERPROFILE%\Desktop\DTSCANNER\momentum_watchlist\run_24_7.bat\"" /sc onlogon
```

**Dell done.** It's now generating your watchlist all day.

---

# PART 3 — ON YOUR PHONE

1. Open **https://shoudabobbin.github.io/DTSCANNER/**.
2. Tap the share/menu button → **Add to Home Screen**.
3. That icon now opens your watchlist. The page reloads itself every 5 minutes
   while the Dell is running, so it's always current.

---

# PART 4 — EVERYDAY USE

Nothing. The Dell runs it during market hours automatically. Open the page on
your phone whenever you want.

**To change the settings** (price range, how many names, etc.): on the Dell, open
`momentum_watchlist\scanner.py`, edit the `CONFIG` block near the top, save, then
close and reopen `run_24_7.bat`.

**To update the code later** (if I send you a new version): on the laptop
`git push`, then on the Dell run `git pull` in the `DTSCANNER` folder and restart
the bat.

---

# PART 5 — TROUBLESHOOTING

| Problem | Fix |
|---|---|
| `python` not recognized | Reinstall Python, check "Add python.exe to PATH". |
| `git push` asks for a password | Passwords don't work anymore — the sign-in popup uses your browser. If it won't appear, run `git push` once manually and complete the browser sign-in. |
| Page not updating | Is `run_24_7.bat` still running? Is it a weekday during US market hours (9:30–4:00 ET)? Check the bat window for a red `! publish failed` line. |
| "No names match" | Quiet day, or filters too tight. Lower `min_change_pct` or `min_rel_volume` in `CONFIG`. |
| Screeners return nothing | Yahoo occasionally rate-limits; it retries next cycle. If persistent, `python -m pip install --upgrade yfinance`. |
| Want to test without waiting for market hours | Run `python scanner.py --once --publish` manually any time. |

---

*Reminder: this is a list of names to study, not buy signals. It has no backtested
edge. Do your own chart work and size by risk. Not financial advice.*
