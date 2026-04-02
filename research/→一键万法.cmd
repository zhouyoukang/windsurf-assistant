@echo off
chcp 65001 >nul
title 一键万法 — Windsurf 全打通
cd /d "%~dp0"
echo.
echo ╔══════════════════════════════════════════╗
echo ║   一键万法 — 道生一·一生二·三生万物     ║
echo ╚══════════════════════════════════════════╝
echo.

:: 检测 python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 未安装或不在 PATH 中
    pause
    exit /b 1
)

:: 解析参数
set MODE=full
if "%1"=="--status"  set MODE=status
if "%1"=="--patch"   set MODE=patch
if "%1"=="--probe"   set MODE=probe
if "%1"=="--quick"   set MODE=quick
if "%1"=="--daemon"  set MODE=daemon
if "%1"=="--byok"    set MODE=byok

if "%MODE%"=="status" goto :status
if "%MODE%"=="patch"  goto :patch
if "%MODE%"=="probe"  goto :probe
if "%MODE%"=="quick"  goto :quick
if "%MODE%"=="daemon" goto :daemon
if "%MODE%"=="byok"   goto :byok
goto :full

:full
echo [完整模式] 状态→补丁→守护→探针→报告
python 一键万法.py
goto :end

:status
echo [状态查询]
python 一键万法.py --status
goto :end

:patch
echo [仅打补丁]
python 一键万法.py --patch
goto :end

:probe
echo [仅模型探针]
python 一键万法.py --probe
goto :end

:quick
echo [快速探针 - 只测 Claude 系列]
python 一键万法.py --probe --quick
goto :end

:daemon
echo [启动密钥守护]
python 一键万法.py --daemon
goto :end

:byok
echo [BYOK 通道 - 需要 Anthropic API Key]
if "%2"=="" (
    echo 用法: %~nx0 --byok sk-ant-YOUR_KEY
    echo 或直接运行: python 全打通_深度探针.py --byok sk-ant-YOUR_KEY
) else (
    python 全打通_深度探针.py --byok %2
)
goto :end

:end
echo.
echo 按任意键退出...
pause >nul
