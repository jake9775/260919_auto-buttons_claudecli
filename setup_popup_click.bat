@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Setup Popup Click
python setup_capture.py --popup-click
echo.
echo ---- finished. press any key to close ----
pause >nul
