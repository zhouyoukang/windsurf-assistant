# _install_local.ps1 — 本机闭环装载 dao-agi.vsix (new v17.45 + essence.js)
# 为而不争 · 太上不知有之
$ErrorActionPreference = 'Continue'

# 1. 定位 Windsurf CLI
$candidates = @(
  'E:\Windsurf\bin\windsurf.cmd',
  'D:\Windsurf\bin\windsurf.cmd',
  'C:\Program Files\Windsurf\bin\windsurf.cmd',
  "$env:LOCALAPPDATA\Programs\Windsurf\bin\windsurf.cmd"
)
$wsCli = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $wsCli) {
  $proc = Get-Process -Name 'Windsurf' -ErrorAction SilentlyContinue | Where-Object { $_.Path } | Select-Object -First 1
  if ($proc -and $proc.Path) {
    $guess = Join-Path (Split-Path (Split-Path $proc.Path)) 'bin\windsurf.cmd'
    if (Test-Path $guess) { $wsCli = $guess }
  }
}
if (-not $wsCli) {
  Write-Host '[X] Windsurf CLI 未找到' -ForegroundColor Red
  exit 1
}
Write-Host "[OK] Windsurf CLI: $wsCli"

# 2. 定位 VSIX
$vsix = Resolve-Path (Join-Path $PSScriptRoot 'dao-agi.vsix') -ErrorAction SilentlyContinue
if (-not $vsix) {
  Write-Host '[X] dao-agi.vsix 未找到' -ForegroundColor Red
  exit 1
}
Write-Host "[OK] VSIX: $($vsix.Path) ($([Math]::Round((Get-Item $vsix.Path).Length/1KB,1)) KB)"

# 3. 静默安装 (CLI 覆盖旧版)
Write-Host ''
Write-Host '── 安装 dao-agi.vsix (CLI) ──' -ForegroundColor Cyan
$installOut = & $wsCli --install-extension $vsix.Path --force 2>&1 | Out-String
Write-Host $installOut

# 4. 验证
Write-Host ''
Write-Host '── 验证 ──' -ForegroundColor Cyan
$extRoot = Join-Path $env:USERPROFILE '.windsurf\extensions'
$daoExts = Get-ChildItem $extRoot -Directory | Where-Object { $_.Name -match '^dao-agi\.dao-agi-\d' -and $_.Name -notmatch '\.bak' } | Sort-Object LastWriteTime -Descending
foreach ($e in $daoExts[0..1]) {
  if (-not $e) { continue }
  $pj = Join-Path $e.FullName 'package.json'
  if (-not (Test-Path $pj)) { continue }
  $p = Get-Content $pj -Raw -Encoding UTF8 | ConvertFrom-Json
  $hasEssence = Test-Path (Join-Path $e.FullName 'essence.js')
  $hasDaoEss = $false
  if ($p.contributes -and $p.contributes.views -and $p.contributes.views.'wam-container') {
    $hasDaoEss = @($p.contributes.views.'wam-container' | Where-Object { $_.id -eq 'dao.essence' }).Count -gt 0
  }
  $hasCmd = @($p.contributes.commands | Where-Object { $_.command -eq 'wam.showEssence' }).Count -gt 0
  Write-Host ("  {0}  v{1}  essence.js={2}  view={3}  cmd={4}" -f $e.Name.PadRight(32), $p.version, $hasEssence, $hasDaoEss, $hasCmd)
}

Write-Host ''
Write-Host '[OK] 已就绪 · Windsurf 内按 Ctrl+Shift+P → "道Agent: 本源一览" 或点活动栏"万法归宗"图标' -ForegroundColor Green
Write-Host '(无需重启 Windsurf · 扩展自动激活 · activationEvents=*)' -ForegroundColor DarkGray
