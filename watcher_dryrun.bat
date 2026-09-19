@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
title Watcher DryRun
python watcher.py --dry-run
echo.
echo ---- finished. press any key to close ----
pause >nul
