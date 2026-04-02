@echo off
chcp 65001 >nul
echo ==============================
echo  Windsurf Credit Toolkit v1.0
echo ==============================
echo.
echo  1. 积分监控 (monitor)
echo  2. 模型成本矩阵 (models)
echo  3. 优化建议 (recommend)
echo  4. Dashboard (:19910)
echo  5. P5 Patch验证 (verify)
echo  6. E2E自测 (test)
echo.
set /p choice="选择 (1-6): "
if "%choice%"=="1" python "%~dp0credit_toolkit.py" monitor
if "%choice%"=="2" python "%~dp0credit_toolkit.py" models
if "%choice%"=="3" python "%~dp0credit_toolkit.py" recommend
if "%choice%"=="4" python "%~dp0credit_toolkit.py" serve
if "%choice%"=="5" python "%~dp0patch_continue_bypass.py" --verify
if "%choice%"=="6" python "%~dp0credit_toolkit.py" test
pause
