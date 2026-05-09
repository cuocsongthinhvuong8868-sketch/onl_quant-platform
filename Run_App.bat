@echo off
setlocal

cd /d "%~dp0"

echo ======================================
echo Quant Platform - Launch Streamlit App
echo Folder: %cd%
echo ======================================

echo.
streamlit run app.py
if errorlevel 1 (
  echo.
  echo [ERROR] Failed to run: streamlit run app.py
)

echo.
echo Press any key to close...
pause >nul
endlocal
