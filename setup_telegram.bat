@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Setup Telegram
python setup_capture.py --telegram
echo.
echo ---- finished. press any key to close ----
pause >nul
