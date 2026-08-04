@echo off
REM Day-trading momentum watchlist + publish to GitHub Pages.
REM
REM Register with Windows Task Scheduler (run this once, from an admin prompt):
REM
REM   schtasks /create /tn "DT Scanner" /tr "C:\Users\Holden\DTSCANNER\run_daily.bat" ^
REM            /sc weekly /d MON,TUE,WED,THU,FRI /st 09:45
REM
REM Remove it again with:  schtasks /delete /tn "DT Scanner" /f
REM
REM TIMING MATTERS AND IT CHANGED.
REM
REM The old swing scanner ran at 17:30 because it needed the completed daily
REM bar. This engine is the opposite: it reads LIVE intraday quotes
REM (regularMarketPrice / ChangePercent / Volume) and asks "what is moving
REM right now". So:
REM
REM   09:45 ET  - roughly 15 min after the open. Enough real volume for RVOL
REM               to mean something, early enough that the day is still ahead
REM               of you. This is the useful slot.
REM   Pre-open  - regularMarketVolume is near zero, RVOL collapses, the list
REM               comes back empty. Do not schedule before the open.
REM   17:30     - technically works, but it publishes yesterday's movers for
REM               you to read tomorrow morning. Stale by definition.

cd /d "%~dp0"

if not exist "reports" mkdir "reports"
echo ============================================ >> "reports\scan_log.txt"
echo %DATE% %TIME% >> "reports\scan_log.txt"

python daytrading_watchlist\daytrading_watchlist.py --publish >> "reports\scan_log.txt" 2>&1
if errorlevel 1 (
    echo SCAN FAILED - see reports\scan_log.txt
    echo SCAN FAILED >> "reports\scan_log.txt"
    goto :open
)

REM Push docs\index.html to GitHub Pages.
REM Unchanged: publish.py commits whatever is in docs\ and does not care which
REM script produced it. The publisher lock still applies.
python publish.py >> "reports\scan_log.txt" 2>&1

:open
REM Open the newest local copy in the default browser
for /f "delims=" %%f in ('dir /b /o-d "daytrading_watchlist\watchlists\watchlist_*.html" 2^>nul') do (
    start "" "daytrading_watchlist\watchlists\%%f"
    goto :done
)
:done
