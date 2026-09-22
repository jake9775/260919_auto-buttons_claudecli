@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Setup Recapture
python setup_capture.py --recapture
echo.
echo ---- finished. press any key to close ----
pause >nul
