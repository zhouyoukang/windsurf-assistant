@echo off
chcp 65001 > nul 2>&1
title 无为守护 v5.0 — 道法自然

echo ╔══════════════════════════════════════════════════════╗
echo ║  无为守护 v5.0 — 用户零感知 · 后台完全自治          ║
echo ║  WAM智能切号 + 补丁守护 + 限流监控 · 全部集成       ║
echo ╚══════════════════════════════════════════════════════╝
echo.

cd /d "%~dp0"
set DIAG=%~dp0040-诊断工具_Diagnostics
set WAM_DIR=%~dp0010-道引擎_DaoEngine

:: ── 步骤1: 确保workbench.js补丁完整 ──────────────────
echo [1/4] 检查并应用 workbench.js 补丁...
python "%~dp0ws_repatch.py" 2>&1
echo.

:: ── 步骤2: 启动 WAM Hub (端口9876，已有则跳过) ───────
echo [2/4] 检查 WAM Hub (:9876)...
curl -s -m 2 http://127.0.0.1:9876/api/health >nul 2>&1
if %errorlevel%==0 (
    echo [2/4] WAM Hub 已在运行，跳过启动。
) else (
    echo [2/4] 启动 WAM Hub (后台)...
    start /min "WAM Hub :9876" python "%WAM_DIR%\wam_engine.py" serve
    timeout /t 2 /nobreak >nul
    echo [2/4] WAM Hub 已在后台启动。
)
echo.

:: ── 步骤3: IPC无感重启 extension host ─────────────────
echo [3/4] IPC无感重启 extension host (~1.5s)...
node "%DIAG%\_ipc_restart.js" 2>&1
echo.

:: ── 步骤4: 启动无为看门狗 (后台持久运行) ──────────────
echo [4/4] 启动无为看门狗 (监控限流+自动切号)...
tasklist /FI "WINDOWTITLE eq 无为看门狗" 2>nul | find "cmd" >nul
start /min "无为看门狗" node "%DIAG%\_watchdog_wuwei.js"
echo [4/4] 看门狗已在后台启动 (最小化窗口)
echo.

echo ✅ 无为守护 v5.0 已全部启动。
echo    - workbench.js 补丁: 活跃
echo    - WAM Hub :9876: 运行中 (智能切号/评分排序)
echo    - extension host: 已热重载
echo    - 看门狗: 后台运行 (5s轮询 → 限流后1s)
echo.
echo Dashboard: http://127.0.0.1:9876/
echo 提示: 下次Windsurf启动前双击此文件，自动完成所有初始化。
pause
