@echo off
REM start.bat - Windows startup script for Meezan Edge v3.0

echo Meezan Edge v3.0 - Autonomous Hedge Fund
echo ===========================================
echo.

REM Check if we're in the right directory
if not exist app.py (
    echo Error: app.py not found
    echo Please run this script from the project directory
    pause
    exit /b 1
)

REM Check if database exists
if not exist meezan_v3.db (
    echo Initializing database...
    python database_schema.py
    echo Database created
) else (
    echo Database exists
)

REM Check dependencies
python -c "import streamlit" 2>nul
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt
)

echo.
echo Launching Meezan Edge...
echo Access at: http://localhost:8501
echo.

REM Set Python path and run
set PYTHONPATH=%PYTHONPATH%;%CD%
streamlit run app.py
