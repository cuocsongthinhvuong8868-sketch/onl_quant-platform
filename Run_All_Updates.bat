@echo off
cd /d "%~dp0"

echo ======================================
echo Quant Platform - Update Pipeline Start
echo Folder: %cd%
echo ======================================

echo.
echo [1/5] Running python -m command.update_data ...
python -m command.update_data
if errorlevel 1 (
  echo [ERROR] command.update_data failed.
  goto :end
)

echo.
echo [2/5] Refreshing Risk-Adjusted Growth bank JSON feeds if local scrape exists ...
if exist "%USERPROFILE%\Desktop\bctc-scrape\Statistics\json" if exist "%USERPROFILE%\Desktop\bctc-scrape\BCTC\json" (
  python -m command.update_risk_adjusted_growth_statistics --source-dir "%USERPROFILE%\Desktop\bctc-scrape\Statistics\json" --financial-report-source-dir "%USERPROFILE%\Desktop\bctc-scrape\BCTC\json"
  if errorlevel 1 (
    echo [ERROR] command.update_risk_adjusted_growth_statistics failed.
    goto :end
  )
) else (
  echo [SKIP] Local scrape folders not found: %USERPROFILE%\Desktop\bctc-scrape\Statistics\json and %USERPROFILE%\Desktop\bctc-scrape\BCTC\json
)

echo.
echo [3/5] Running python -m command.update_pvgo_valuation ...
python -m command.update_pvgo_valuation
if errorlevel 1 (
  echo [ERROR] command.update_pvgo_valuation failed.
  goto :end
)

echo.
echo [4/5] Running python -m command.update_vnibor ...
python -m command.update_vnibor
if errorlevel 1 (
  echo [ERROR] command.update_vnibor failed.
  goto :end
)

echo.
echo [5/5] Syncing ABM data from LTMM if available ...
python -m command.update_abm_data
if errorlevel 1 (
  echo [ERROR] command.update_abm_data failed.
  goto :end
)

echo.
echo [DONE] All update scripts finished.

:end
echo.
echo Press any key to close...
pause >nul
