@echo off
echo ============================================
echo   Uganda Business Scraper -- Setup
echo ============================================
echo.

REM Check Python is available
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo ERROR: Python not found. Please install Python from https://python.org
    echo Make sure to tick "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo Python found:
python --version
echo.

REM Upgrade pip first
echo Upgrading pip...
python -m pip install --upgrade pip

echo.
echo Installing dependencies...
python -m pip install flask flask-cors firecrawl-py pandas openpyxl apscheduler playwright requests beautifulsoup4 python-dotenv

IF ERRORLEVEL 1 (
    echo.
    echo ERROR: pip install failed. Trying with --user flag...
    python -m pip install --user flask flask-cors firecrawl-py pandas openpyxl apscheduler playwright requests beautifulsoup4 python-dotenv
)

echo.
echo Installing Playwright browser (Chromium - for TikTok, Instagram, Twitter)...
python -m playwright install chromium

echo.
echo ============================================
echo   Setup complete!
echo   Double-click start.bat to launch the app.
echo ============================================
pause
