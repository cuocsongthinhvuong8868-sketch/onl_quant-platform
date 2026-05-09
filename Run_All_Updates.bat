@echo off
cd /d "%~dp0"

echo ======================================
echo Quant Platform - Update Pipeline Start
echo Folder: %cd%
echo ======================================

echo.
echo [1/2] Running python -m command.update_data ...
python -m command.update_data
if errorlevel 1 (
  echo [ERROR] command.update_data failed.
  goto :end
)

echo.
echo [2/2] Running python -m command.update_bank_fundamentals ...
python -m command.update_bank_fundamentals
if errorlevel 1 (
  echo [ERROR] command.update_bank_fundamentals failed.
  goto :end
)

echo.
echo [DONE] All update scripts finished.

:end
echo.
echo Press any key to close...
pause >nul
