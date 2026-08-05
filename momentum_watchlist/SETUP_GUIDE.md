# Momentum Watchlist — Full Setup Guide (start to finish)

This is the ONE guide to follow. It covers both machines. If you've already done
a step, just skip it.

```
LAPTOP  → pushes the code to GitHub (you're on this machine now)
DELL    → clones the code, runs the scanner 24/7, updates the web page
PHONE   → opens the web page
```

Your live URL: **https://shoudabobbin.github.io/DTSCANNER/**

---

# PART 1 — LAPTOP  (push the latest code) · ~3 min

1. Press Start, type `cmd`, hit Enter to open **Command Prompt**.
2. Go to the repo:
   ```
   cd C:\Users\shrek\Desktop\DT_SCANNER
   ```
3. Push everything (this includes the scanner and today's fixes):
   ```
   git add momentum_watchlist .gitignore
   git commit -m "Momentum watchlist + morning-filter fixes"
   git push
   ```
   If it opens a GitHub sign-in window, sign in and authorize.

That's the laptop done. Everything else is on the Dell.

---

# PART 2 — DELL  (one-time install) · ~15 min

### 2A. Install Python
1. Go to **https://www.python.org/downloads/**, download Python 3.
2. Run the installer. **CHECK "Add python.exe to PATH"** at the bottom. Click Install Now.
3. Open Command Prompt and verify:
   ```
   python --version
   ```

### 2B. Install Git
1. Go to **https://git-scm.com/download/win**, download, install with all defaults.
2. Verify in a new Command Prompt:
   ```
   git --version
   ```

### 2C. Set your Git identity
```
git config --global user.name "Holden"
git config --global user.email "holdentomanchek@gmail.com"
```

### 2D. Get the project onto the Dell
- **If the Dell does NOT already have the repo:**
  ```
  cd %USERPROFILE%\Desktop
  git clone https://github.com/shoudabobbin/DTSCANNER.git
  cd DTSCANNER\momentum_watchlist
  ```
- **If the Dell ALREADY has it** (you set it up before), just update it:
  ```
  cd %USERPROFILE%\Desktop\DTSCANNER
  git pull
  cd momentum_watchlist
  ```

### 2E. Install the requirements
```
python -m pip install -r requirements.txt
```

### 2F. First run + first publish
Prove it builds a page offline (instant):
```
python scanner.py --demo
```
Now the real run — this also signs the Dell into GitHub and creates the
`gh-pages` branch the first time:
```
python scanner.py --once --publish
```
> On the first `--publish`, a **GitHub sign-in window pops up** — sign in and
> Authorize. One time only.

---

# PART 3 — TURN ON THE WEB PAGE  (one-time, on GitHub) · ~2 min

You may have already done this. Verify it:

1. Go to **https://github.com/shoudabobbin/DTSCANNER → Settings → Pages**.
2. Source = **Deploy from a branch**. Branch = **gh-pages**, Folder = **/ (root)**. Save.
3. Wait ~1 minute, open **https://shoudabobbin.github.io/DTSCANNER/**.

You should see the "Momentum Watchlist" card page (NOT the old "Morning
Watchlist"). If it still shows the old one, the branch is still set to `main` —
change it to `gh-pages` here.

---

# PART 4 — RUN IT 24/7 ON THE DELL

### 4A. Stop the Dell from sleeping
Settings → **System → Power** → set **Sleep = Never** (when plugged in).

### 4B. Start the loop
**Simple way (recommended):** open the `momentum_watchlist` folder and
**double-click `run_24_7.bat`**. Leave that black window open. It rescans every
5 minutes during market hours and idles nights/weekends.

**Auto-start after reboot (optional):** in Command Prompt, replace
`YOURNAME` with the Dell's Windows username:
```
schtasks /create /tn "Momentum Watchlist" /tr "C:\Users\YOURNAME\Desktop\DTSCANNER\momentum_watchlist\run_24_7.bat" /sc onlogon
```
(Not sure of the username? Run `echo %USERNAME%` in Command Prompt.)

---

# PART 5 — PHONE

1. Open **https://shoudabobbin.github.io/DTSCANNER/**.
2. Share menu → **Add to Home Screen**.
3. The page reloads itself every 5 minutes while the Dell is running.

---

# DAILY LIFE
Nothing to do — it runs itself during market hours. Open the page whenever.

- **Change settings** (price range, list size, etc.): edit the `CONFIG` block at
  the top of `scanner.py` on the Dell, save, close and reopen `run_24_7.bat`.
- **Get a new version I send you:** on the laptop `git push`; on the Dell
  `git pull` then restart the bat.

---

# TROUBLESHOOTING
| Problem | Fix |
|---|---|
| `python` not recognized | Reinstall Python, check "Add python.exe to PATH". |
| `git push`/`--publish` asks for a password | Passwords don't work — complete the browser sign-in popup. |
| Page shows the OLD swing list | GitHub → Settings → Pages → branch = **gh-pages**. |
| Page not updating | Is `run_24_7.bat` still running? Is it a weekday, market hours (9:30–4 ET)? |
| List looks empty/thin in the morning | Should be fixed now — it always shows the day's movers (tagged IN PLAY vs MOVER). If still thin, tell me and we'll lower `min_change_pct`. |
| Screeners return nothing | Yahoo hiccup — it retries next cycle and shows the last good list meanwhile. |

*Reminder: the list is names to STUDY, not buy signals. Do your own chart work and size by risk. Not financial advice.*
