@echo off
title BCTC Auto Scraper Server
color 0B
echo =====================================================================
echo   🚀 STARTING BCTC AUTO SCRAPER & PREMIUM EXCEL GENERATOR 🚀
echo =====================================================================
echo.
echo [+] Hướng dẫn: Giữ cửa sổ này mở trong suốt quá trình trình duyệt cào.
echo [+] Thư mục làm việc: C:\Users\ADMIN\Desktop\bctc-scrape
echo [+] Đầu ra: Các tệp Excel Navy sẽ được lưu tại bctc-scrape trên Desktop.
echo.
echo ---------------------------------------------------------------------
cd /d "%~dp0"
node run.mjs
echo.
echo ---------------------------------------------------------------------
echo [!] Máy chủ đã dừng hoạt động. Nhấn phím bất kỳ để đóng cửa sổ.
pause
