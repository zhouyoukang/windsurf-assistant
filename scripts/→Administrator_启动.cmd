@echo off
chcp 65001 > nul 2>&1
title WAM Administrator 启动 v1.0

:: 确保Administrator的_pool_apikey.txt为空，让hot_patch fallback到state.vscdb真实auth
:: (hot_guardian v2.0修复: 不再跨用户写入, 但为安全起见每次启动主动清空)
echo. > "C:\Users\Administrator\AppData\Roaming\Windsurf\_pool_apikey.txt"

:: 应用workbench.js补丁 (如版本更新后补丁丢失，自动重新应用)
python "e:\道\道生一\一生二\Windsurf无限额度\ws_repatch.py" 2>&1

:: 启动WAM后端 (端口9877，避免与ai账号的9876冲突)
:: VSIX扩展内置切号逻辑，此后端提供Dashboard和API
set WAM_DIR=e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine
set PYTHON=C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe

netstat -ano 2>nul | findstr ":9877 " | findstr "LISTENING" > nul 2>&1
if %errorlevel%==0 (
    echo [OK] WAM Hub :9877 已在运行，跳过
) else (
    echo [启动] WAM Hub :9877...
    start /min "WAM Hub Admin :9877" %PYTHON% -c "import sys; sys.argv=['wam_engine.py','serve']; exec(open('%WAM_DIR%\\wam_engine.py').read().replace('HUB_PORT = 9876','HUB_PORT = 9877'))"
)

echo.
echo [完成] Administrator WAM 环境已就绪
echo   - pool_apikey.txt: 已清空 (fallback到state.vscdb auth)
echo   - workbench.js 补丁: 已检查/应用
echo   - WAM Hub :9877: 已启动 (或已在运行)
