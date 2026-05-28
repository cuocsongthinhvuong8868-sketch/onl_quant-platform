@echo off
setlocal

cd /d "%~dp0"

echo ======================================
echo Quant Platform - Launch Streamlit App
echo Folder: %cd%
echo ======================================

echo.
streamlit run app.py --server.port=8502
if errorlevel 1 (
  echo.
  echo [ERROR] Failed to run: streamlit run app.py --server.port=8502
)

echo.
echo Press any key to close...
pause >nul
endlocal
