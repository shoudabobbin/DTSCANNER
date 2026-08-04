@echo off
REM ============================================================
REM  Leave this running on the Dell. It rescans every few
REM  minutes while the US market is open, idles otherwise, and
REM  pushes the watchlist to your GitHub Pages URL each time.
REM ============================================================
cd /d "%~dp0"
echo Starting momentum watchlist loop. Leave this window open.
echo Ctrl+C to stop.
python scanner.py --loop --publish
pause
