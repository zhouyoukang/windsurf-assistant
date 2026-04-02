@echo off
REM Windsurf Instance 2 - 快捷启动
REM 放到桌面或固定到任务栏即可
powershell -ExecutionPolicy Bypass -File "%~dp0windsurf-multi.ps1" -InstanceId 2 %*
