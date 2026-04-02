@echo off
chcp 65001 >nul
echo [ws_repatch] Applying Windsurf workbench patches...
python "%~dp0ws_repatch.py"
echo.
echo [ws_repatch] Done. Reload Windsurf window to take effect.
pause
