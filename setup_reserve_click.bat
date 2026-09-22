@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Setup Reserve Click
python setup_capture.py --reserve-click
echo.
echo ---- finished. press any key to close ----
pause >nul
