@echo off
:: build.cmd — 道Agent v17.51 · 万法归宗 一键打包
:: 大制不割 · 圣人抱一为天下式 · 反向出发 · 解剖观本源
setlocal
cd /d "%~dp0"

echo.
echo ========================================
echo   道Agent v17.51 · 万法归宗 · 一键打包
echo   (010-WAM本源_Origin · 回归本源)
echo ========================================
echo.

call npx --yes @vscode/vsce package --no-dependencies --allow-missing-repository -o dao-agi.vsix
if errorlevel 1 goto :err

echo.
echo ========================================
for %%F in (dao-agi.vsix) do echo   产物: %%F  (%%~zF bytes)
echo ========================================
echo.

:: 复制到 010 根目录 (向后兼容 rt-flow-dao-*.vsix 命名)
for /f "tokens=2 delims=:," %%V in ('findstr /C:"\"version\"" package.json') do (
  set VER=%%V
)
set VER=%VER:"=%
set VER=%VER: =%
copy /Y dao-agi.vsix "..\..\..\rt-flow-dao-%VER%.vsix" >nul
echo   归档: ..\..\..\rt-flow-dao-%VER%.vsix

echo.
echo 安装: windsurf.cmd --install-extension dao-agi.vsix
echo.
exit /b 0

:err
echo.
echo [失败] 构建中止
exit /b 1
