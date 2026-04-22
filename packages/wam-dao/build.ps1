# build.ps1 — 道Agent v17.51 · 万法归宗 一键打包
# 大制不割 · 圣人抱一为天下式 · 唯 vsce 一链，无需 tsc/esbuild
# 反向出发 · 解剖观本源 · 不一叶障泰山
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Write-Host ''
Write-Host '════════════════════════════════════════' -ForegroundColor Cyan
Write-Host '  道Agent v17.51 · 万法归宗 · 一键打包' -ForegroundColor Cyan
Write-Host '  (010-WAM本源_Origin · 回归本源)' -ForegroundColor DarkGray
Write-Host '════════════════════════════════════════' -ForegroundColor Cyan
Write-Host ''

# 读版本
$pkg = Get-Content 'package.json' -Raw -Encoding UTF8 | ConvertFrom-Json
$ver = $pkg.version
Write-Host "  版本: v$ver" -ForegroundColor Green

# 语法自检
Write-Host '  [1/3] 语法检查 extension.js...' -ForegroundColor Yellow
node --check extension.js
if ($LASTEXITCODE -ne 0) { Write-Host '  ✗ 语法错误' -ForegroundColor Red; exit 1 }
Write-Host '  ✓ extension.js 语法通过' -ForegroundColor Green

# vsce 打包
Write-Host '  [2/3] vsce package...' -ForegroundColor Yellow
$localVsix = Join-Path $PSScriptRoot 'dao-agi.vsix'
if (Test-Path $localVsix) { Remove-Item $localVsix -Force }
& npx --yes '@vscode/vsce' package --no-dependencies --allow-missing-repository -o dao-agi.vsix
if ($LASTEXITCODE -ne 0) { Write-Host '  ✗ vsce 失败' -ForegroundColor Red; exit 1 }

$sz = [math]::Round((Get-Item $localVsix).Length / 1KB, 1)
Write-Host "  ✓ 产物: dao-agi.vsix ($sz KB)" -ForegroundColor Green

# 归档至 010 根目录
Write-Host '  [3/3] 归档至 010 根目录...' -ForegroundColor Yellow
$archive = Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
$archiveVsix = Join-Path $archive "rt-flow-dao-$ver.vsix"
Copy-Item $localVsix $archiveVsix -Force
Write-Host "  ✓ 归档: $archiveVsix" -ForegroundColor Green

Write-Host ''
Write-Host '════════════════════════════════════════' -ForegroundColor Cyan
Write-Host '  构建完成 · 道法自然 · 无为而无不为' -ForegroundColor Cyan
Write-Host '════════════════════════════════════════' -ForegroundColor Cyan
Write-Host ''
Write-Host '部署到 179:' -ForegroundColor White
Write-Host "  cd ..\..\..\..\020-道VSIX_DaoAgi" -ForegroundColor DarkGray
Write-Host "  .\deploy-dao-agi-179.ps1 -VsixPath '$archiveVsix' -Force -Restart" -ForegroundColor DarkGray
Write-Host '  .\e2e-179.ps1' -ForegroundColor DarkGray
Write-Host ''
