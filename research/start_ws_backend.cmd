@echo off
title WS Backend :19910
cd /d "%~dp0"
python ws_backend.py %*
pause
