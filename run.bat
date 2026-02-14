@echo off
title Halal Stock Trading System
color 0A
echo.
echo ==========================================
echo   Halal Stock Trading System - Launcher
echo ==========================================
echo.

:: Install dependencies if needed
echo [1/2] Checking dependencies...
pip install -r requirements.txt --quiet

echo.
echo [2/2] Launching Streamlit dashboard...
echo.
echo Open your browser at: http://localhost:8501
echo Press CTRL+C to stop.
echo.

streamlit run app.py --server.headless false --browser.gatherUsageStats false

pause
