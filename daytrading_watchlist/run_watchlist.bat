@echo off
REM Double-click to build today's watchlist and open it in your browser.
cd /d "%~dp0"
echo Building today's day-trading watchlist...
python daytrading_watchlist.py
echo.
REM Open the newest watchlist HTML
for /f "delims=" %%f in ('dir /b /o-d watchlists\watchlist_*.html 2^>nul') do (
    start "" "watchlists\%%f"
    goto :opened
)
:opened
echo.
echo Done. If nothing opened, look in the watchlists\ folder.
pause
