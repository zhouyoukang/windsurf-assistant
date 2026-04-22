# _pack_deploy.ps1 — 打包 + 本机安装 + 旧版归档 + vsix 归档
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot

Write-Host '═══ 打包 ═══' -ForegroundColor Yellow
Remove-Item dao-agi.vsix -ErrorAction SilentlyContinue
$buildOut = & npx --yes @vscode/vsce package --no-dependencies --allow-missing-repository -o dao-agi.vsix 2>&1 | Out-String
if (-not (Test-Path dao-agi.vsix)) {
  Write-Host '[X] 打包失败' -ForegroundColor Red
  Write-Host $buildOut
  exit 1
}
$sz = [Math]::Round((Get-Item dao-agi.vsix).Length / 1KB, 1)
$pj = Get-Content package.json -Raw -Encoding UTF8 | ConvertFrom-Json
$ver = $pj.version
Write-Host "[OK] dao-agi.vsix v$ver ($sz KB)" -ForegroundColor Green

Write-Host ''
Write-Host '═══ 归档 vsix ═══' -ForegroundColor Yellow
$archiveDir = Resolve-Path (Join-Path $PSScriptRoot '..\..\..')
$archive = Join-Path $archiveDir ("rt-flow-dao-$ver.vsix")
Copy-Item dao-agi.vsix $archive -Force
Write-Host "[OK] $archive" -ForegroundColor Green

Write-Host ''
Write-Host '═══ 安装到本机 ═══' -ForegroundColor Yellow
$candidates = @(
  'E:\Windsurf\bin\windsurf.cmd',
  'D:\Windsurf\bin\windsurf.cmd',
  'C:\Program Files\Windsurf\bin\windsurf.cmd'
)
$wsCli = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $wsCli) {
  Write-Host '[X] Windsurf CLI 未找到' -ForegroundColor Red
  exit 1
}
$installOut = & $wsCli --install-extension (Resolve-Path dao-agi.vsix).Path --force 2>&1 | Out-String
Write-Host $installOut -ForegroundColor DarkGray

Write-Host ''
Write-Host '═══ 归档旧版 ═══' -ForegroundColor Yellow
$extRoot = Join-Path $env:USERPROFILE '.windsurf\extensions'
$olds = Get-ChildItem $extRoot -Directory | Where-Object {
  $_.Name -match '^dao-agi\.dao-agi-\d' -and
  $_.Name -notmatch '\.bak' -and
  $_.Name -notmatch "-$ver$"
}
foreach ($o in $olds) {
  $bak = $o.FullName + '.bak.' + (Get-Date -Format 'yyyyMMddHHmmss')
  try {
    Rename-Item $o.FullName $bak -ErrorAction Stop
    Write-Host "  [OK] $($o.Name) → .bak" -ForegroundColor Green
  } catch {
    Write-Host "  [WARN] $($o.Name): $($_.Exception.Message)" -ForegroundColor Yellow
  }
}

Write-Host ''
Write-Host '═══ 当前扩展状态 ═══' -ForegroundColor Yellow
Get-ChildItem $extRoot -Directory | Where-Object { $_.Name -match '^dao-agi\.dao-agi-\d' -and $_.Name -notmatch '\.bak' } | ForEach-Object {
  $p = Get-Content (Join-Path $_.FullName 'package.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  $hasEss = Test-Path (Join-Path $_.FullName 'essence.js')
  $views = ($p.contributes.views.'wam-container' | ForEach-Object { $_.id }) -join ', '
  Write-Host "  [ACTIVE] $($_.Name) v$($p.version) essence=$hasEss" -ForegroundColor Green
  Write-Host "           views = $views" -ForegroundColor DarkGray
}

Write-Host ''
Write-Host '╔═══════════════════════════════════════════╗' -ForegroundColor Cyan
Write-Host "║  道Agent v$ver · 已就绪                    ║" -ForegroundColor Cyan
Write-Host '║  Reload Window 后, 活动栏「万法归宗」:     ║' -ForegroundColor Cyan
Write-Host '║    ① 本源一览 (置顶 · 零·SP隔离核验)      ║' -ForegroundColor White
Write-Host '║    ② 模式 (双按钮 道/官方)                ║' -ForegroundColor DarkGray
Write-Host '║    ③ 切号面板                             ║' -ForegroundColor DarkGray
Write-Host '╚═══════════════════════════════════════════╝' -ForegroundColor Cyan
