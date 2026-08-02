@echo off
REM Nightly watchlist scan + publish to GitHub Pages.
REM
REM Register with Windows Task Scheduler (run this once, from an admin prompt):
REM
REM   schtasks /create /tn "DT Scanner" /tr "C:\Users\shrek\Desktop\DT_SCANNER\run_daily.bat" ^
REM            /sc weekly /d MON,TUE,WED,THU,FRI /st 17:30
REM
REM Remove it again with:  schtasks /delete /tn "DT Scanner" /f
REM
REM 17:30 local is chosen so Yahoo has settled the daily bars for the session
REM that just closed. Running earlier can pick up an incomplete final bar.

cd /d "%~dp0"

if not exist "reports" mkdir "reports"
echo ============================================ >> "reports\scan_log.txt"
echo %DATE% %TIME% >> "reports\scan_log.txt"

python run_scan.py >> "reports\scan_log.txt" 2>&1
if errorlevel 1 (
    echo SCAN FAILED - see reports\scan_log.txt
    echo SCAN FAILED >> "reports\scan_log.txt"
    goto :open
)

REM Push docs\index.html to GitHub Pages.
REM Exits harmlessly with a message if git isn't set up yet.
python publish.py >> "reports\scan_log.txt" 2>&1

:open
REM Open the newest local copy in the default browser
for /f "delims=" %%f in ('dir /b /o-d "reports\watchlist_*.html" 2^>nul') do (
    start "" "reports\%%f"
    goto :done
)
:done
