@echo off
setlocal

cd /d "%~dp0\.."

echo ======================================
echo Quant Platform - Setup (Windows)
echo Folder: %cd%
echo ======================================

echo.
echo [1/3] Upgrade pip...
python -m pip install --upgrade pip
if errorlevel 1 (
  echo [ERROR] Failed at pip upgrade.
  goto :end
)

echo.
echo [2/3] Install project dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Failed installing requirements.
  goto :end
)

echo.
echo [3/3] Install Playwright Chromium...
python -m playwright install chromium
if errorlevel 1 (
  echo [ERROR] Failed installing Playwright Chromium.
  goto :end
)

echo.
echo [DONE] Setup completed.

:end
echo.
echo Press any key to close...
pause >nul
endlocal
