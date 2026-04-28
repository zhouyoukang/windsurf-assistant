# _build_vsix.ps1 · 道Agent · 极简构建脚本
# 用:
#   .\_build_vsix.ps1                  # 仅打包
#   .\_build_vsix.ps1 -InstallLocal    # 打包 + 装本机 Windsurf
#   .\_build_vsix.ps1 -RunL1           # 打包前先跑 L1 自检 (任失即终止)
#   .\_build_vsix.ps1 -RunL2Syn        # 打包前先跑 L2 合成自举 (要反代 8889 在跑)
#   .\_build_vsix.ps1 -RunL1 -RunL2Syn # 全测

param(
    [switch]$InstallLocal,
    [switch]$RunL1,
    [switch]$RunL2Syn,
    [int]$Port = $(if ($env:ORIGIN_PORT) { [int]$env:ORIGIN_PORT } else { 8889 })
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

Write-Host "═══ 道Agent · 构建 vsix ═══" -ForegroundColor Cyan
Write-Host ""

# ── 0. 校验文件齐 ──
$requiredFiles = @(
    "extension.js",
    "package.json",
    "README.md",
    "LICENSE",
    "vendor\bundled-origin\source.js",
    "vendor\bundled-origin\_dao_81.txt",
    "media\icon.png"
)
foreach ($f in $requiredFiles) {
    if (-not (Test-Path $f)) {
        Write-Host "✗ 缺: $f" -ForegroundColor Red
        exit 1
    }
}
Write-Host "✓ 文件齐 ($($requiredFiles.Count) 必)" -ForegroundColor Green

# ── 1a. (可选) L1 自检 ──
if ($RunL1) {
    Write-Host ""
    Write-Host "── L1 单元自检 ──" -ForegroundColor Cyan
    & node --preserve-symlinks --preserve-symlinks-main tests\L1_unit.js
    if ($LASTEXITCODE -ne 0) {
        Write-Host "✗ L1 失 · 不打包" -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host "✓ L1 全绿" -ForegroundColor Green
}

# ── 1b. (可选) L2 合成自举 (反代须在跑) ──
if ($RunL2Syn) {
    Write-Host ""
    Write-Host "── L2 合成自举 (须反代 :$Port 在跑) ──" -ForegroundColor Cyan
    try {
        $null = Invoke-RestMethod "http://127.0.0.1:${Port}/origin/ping" -TimeoutSec 2
    } catch {
        Write-Host "✗ 反代 :$Port 不在 · 启法: node vendor\bundled-origin\source.js" -ForegroundColor Red
        Write-Host "  (跳 L2 合成 · 续打包)" -ForegroundColor Yellow
    }
    if ($?) {
        $env:ORIGIN_PORT = $Port
        & node --preserve-symlinks --preserve-symlinks-main tests\L2_synthetic.js
        if ($LASTEXITCODE -ne 0) {
            Write-Host "✗ L2 合成失 · 不打包" -ForegroundColor Red
            exit $LASTEXITCODE
        }
        Write-Host "✓ L2 合成 · 反代+道德经替换闭环 ✓" -ForegroundColor Green
    }
}

# ── 2. 删旧 vsix ──
Write-Host ""
Write-Host "── 删旧 vsix ──"
Get-ChildItem -Path . -Filter "dao-proxy-min*.vsix" | ForEach-Object {
    Remove-Item $_.FullName -Force
    Write-Host "  DEL $($_.Name)"
}

# ── 3. 打包 ──
Write-Host ""
Write-Host "── 打包 (vsce package) ──" -ForegroundColor Cyan
$pkgVersion = (Get-Content package.json -Raw -Encoding utf8 | ConvertFrom-Json).version
Write-Host "  version: $pkgVersion"

$vsceArgs = @(
    "@vscode/vsce", "package",
    "--no-dependencies",
    "--allow-missing-repository"
)
& npx @vsceArgs 2>&1 | ForEach-Object { Write-Host "  $_" }
if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ vsce 打包失" -ForegroundColor Red
    exit $LASTEXITCODE
}

$vsixFile = Get-ChildItem -Path . -Filter "dao-proxy-min*.vsix" | Select-Object -First 1
if (-not $vsixFile) {
    Write-Host "✗ 未生成 vsix" -ForegroundColor Red
    exit 1
}
Write-Host ""
Write-Host "✓ 打包: $($vsixFile.Name) ($([math]::Round($vsixFile.Length / 1KB, 1)) KB)" -ForegroundColor Green

# ── 4. (可选) 装本机 ──
if ($InstallLocal) {
    Write-Host ""
    Write-Host "── 装本机 Windsurf ──" -ForegroundColor Cyan

    $windsurfBin = $null
    $candidates = @(
        "E:\Windsurf\bin\windsurf.cmd",
        "C:\Program Files\Windsurf\bin\windsurf.cmd",
        "$env:LOCALAPPDATA\Programs\Windsurf\bin\windsurf.cmd"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $windsurfBin = $c; break }
    }
    if (-not $windsurfBin) {
        $found = Get-Command windsurf -ErrorAction SilentlyContinue
        if ($found) { $windsurfBin = $found.Source }
    }
    if (-not $windsurfBin) {
        Write-Host "✗ 找不 windsurf.cmd · 手装: windsurf --install-extension $($vsixFile.FullName)" -ForegroundColor Yellow
        exit 0
    }

    Write-Host "  windsurf: $windsurfBin"
    & $windsurfBin --install-extension $vsixFile.FullName --force 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ 装毕 · 重载 Windsurf 窗口生效" -ForegroundColor Green
    } else {
        Write-Host "✗ 装失 (exit $LASTEXITCODE)" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "════════════════════════════════════════" -ForegroundColor Cyan
