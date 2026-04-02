@echo off
chcp 65001 >nul 2>&1
title Windsurf 一键换号
echo.
echo  ========================================
echo   Windsurf 一键换号
echo  ========================================
echo.
echo  用法:
echo    直接回车 = 自动切到下一个账号
echo    输入数字 = 切到指定账号
echo    s = 查看状态
echo    r = 刷新所有token
echo    q = 退出
echo.

:menu
set /p choice="  输入命令 (回车=next / 数字 / s / r / q): "
if "%choice%"=="" set choice=next
if /i "%choice%"=="q" goto :eof
if /i "%choice%"=="s" (
    python -u "%~dp0040-诊断工具_Diagnostics\_switch.py" status
    echo.
    goto menu
)
if /i "%choice%"=="r" (
    python -u "%~dp0040-诊断工具_Diagnostics\_switch.py" refresh
    echo.
    goto menu
)
python -u "%~dp0040-诊断工具_Diagnostics\_switch.py" %choice%
echo.
echo  提示: 在Windsurf中 Ctrl+Shift+P 输入 Reload Window 生效
echo.
goto menu
