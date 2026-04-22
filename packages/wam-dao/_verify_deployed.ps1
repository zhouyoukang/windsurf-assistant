# _verify_deployed.ps1 — 核验已部署扩展实体
$ext = Join-Path $env:USERPROFILE '.windsurf\extensions\dao-agi.dao-agi-17.45.0'

Write-Host '── 已部署扩展之实体 ──' -ForegroundColor Cyan
Get-ChildItem $ext -File -Force |
  Select-Object Name, @{N='KB'; E={ [Math]::Round($_.Length/1KB, 1) }} |
  Format-Table -AutoSize

Write-Host '── vendor/wam/bundled-origin ──' -ForegroundColor Cyan
Get-ChildItem (Join-Path $ext 'vendor\wam\bundled-origin') -File |
  Select-Object Name, @{N='KB'; E={ [Math]::Round($_.Length/1KB, 1) }} |
  Format-Table -AutoSize

Write-Host '── essence.js 首部 16 行 ──' -ForegroundColor Cyan
Get-Content (Join-Path $ext 'essence.js') -TotalCount 16 |
  ForEach-Object { Write-Host ('  ' + $_) -ForegroundColor DarkGray }
$essSz = [Math]::Round((Get-Item (Join-Path $ext 'essence.js')).Length/1KB, 1)
Write-Host "  ... ($essSz KB 总) " -ForegroundColor DarkGray

Write-Host ''
Write-Host '── package.json 核心段 ──' -ForegroundColor Cyan
$p = Get-Content (Join-Path $ext 'package.json') -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host ('  version:     v' + $p.version)
Write-Host ('  views[wam-container]: ' + (($p.contributes.views.'wam-container' | ForEach-Object { $_.id }) -join ', '))
$cmdEss = $p.contributes.commands | Where-Object { $_.command -eq 'wam.showEssence' }
if ($cmdEss) {
  Write-Host ('  wam.showEssence: ' + $cmdEss.title) -ForegroundColor Green
} else {
  Write-Host '  wam.showEssence: [X] 未注册' -ForegroundColor Red
}

Write-Host ''
Write-Host '── 道源 proxy 与 rule 对照 ──' -ForegroundColor Cyan
$daoRule = Join-Path 'e:\道\道生一\一生二\.windsurf\rules' 'dao-de-jing.md'
if (Test-Path $daoRule) {
  $hash = (Get-FileHash $daoRule -Algorithm SHA256).Hash.Substring(0, 16)
  $sz = (Get-Item $daoRule).Length
  Write-Host "  rule:  dao-de-jing.md · $sz B · sha16=$hash · trigger=always_on" -ForegroundColor Green
}
try {
  $ping = Invoke-RestMethod -Uri 'http://127.0.0.1:8889/origin/ping' -TimeoutSec 2 -ErrorAction Stop
  Write-Host "  proxy: :$($ping.port) mode=$($ping.mode) dao=$($ping.dao_chars)字 uptime=$($ping.uptime_s)s" -ForegroundColor Green
  $self = Invoke-RestMethod -Uri 'http://127.0.0.1:8889/origin/selftest' -TimeoutSec 5 -ErrorAction Stop
  if ($self.all_paths_pass) {
    Write-Host "  self:  all_paths_pass=True (四路径 0 泄露)" -ForegroundColor Green
  } else {
    Write-Host "  self:  all_paths_pass=False" -ForegroundColor Yellow
  }
} catch {
  Write-Host "  proxy: 未监听 (扩展将在 Reload Window 后启动)" -ForegroundColor DarkGray
}

Write-Host ''
Write-Host '╔══════════════════════════════════════════════════╗' -ForegroundColor Cyan
Write-Host '║   本源一览 · 已就绪 · 反者道之动                    ║' -ForegroundColor Cyan
Write-Host '╠══════════════════════════════════════════════════╣' -ForegroundColor Cyan
Write-Host '║   入口 1: 活动栏 "万法归宗" 图标 → 第二栏"本源一览" ║' -ForegroundColor White
Write-Host '║   入口 2: Ctrl+Shift+P → "道Agent: 本源一览"        ║' -ForegroundColor White
Write-Host '║   刷新:  视图内"◉刷新" · 8秒自动轮询                ║' -ForegroundColor White
Write-Host '║   复制:  "⧉复制" 导出完整 JSON 至剪贴板             ║' -ForegroundColor White
Write-Host '╚══════════════════════════════════════════════════╝' -ForegroundColor Cyan
