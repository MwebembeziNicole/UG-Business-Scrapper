@echo off
echo Starting Uganda Business Scraper...
echo.

REM Check if flask is installed; if not, run install first
python -c "import flask" >nul 2>&1
IF ERRORLEVEL 1 (
    echo Flask not found. Running setup first...
    echo.
    python -m pip install flask flask-cors firecrawl-py pandas openpyxl apscheduler playwright requests beautifulsoup4 python-dotenv
    python -m playwright install chromium
    echo.
)

python run.py
pause
