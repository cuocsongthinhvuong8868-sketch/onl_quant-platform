@echo off
setlocal

cd /d "%~dp0"

set "SOURCE_DIR=%LTMM_SILVER_DIR%"
if not defined SOURCE_DIR set "SOURCE_DIR=%USERPROFILE%\Desktop\LTMM\data\silver"

echo ============================================================
echo Quant Platform - Update Credit Spread Data
echo Project: %cd%
echo Source:  %SOURCE_DIR%
echo ============================================================
echo.

if not exist "%SOURCE_DIR%" (
  echo [ERROR] Source folder not found: %SOURCE_DIR%
  echo Set LTMM_SILVER_DIR or verify the local LTMM workspace.
  set "EXIT_CODE=1"
  goto :end
)

python -m command.update_credit_spread_data --source-dir "%SOURCE_DIR%"
if errorlevel 1 (
  echo.
  echo [ERROR] Credit Spread data update failed.
  set "EXIT_CODE=1"
  goto :end
)

echo.
echo [DONE] Credit Spread data updated successfully.
set "EXIT_CODE=0"

:end
echo.
if /i not "%~1"=="/nopause" (
  echo Press any key to close...
  pause >nul
)

endlocal & exit /b %EXIT_CODE%
