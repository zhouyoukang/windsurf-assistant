param()
$ErrorActionPreference = "Continue"

$TARGET_IP   = "192.168.31.179"
$TARGET_USER = "zhouyoukang"
$TARGET_PASS = "wsy057066wsy"
$SRC_DIR     = "e:\dao\daoshengy\yishengerL\wam\src"
$HOT_REMOTE  = "C:\Users\zhouyoukang\.wam-hot"
$ACCOUNTS_SRC = "C:\Users\ai\AppData\Roaming\Windsurf\User\globalStorage\windsurf-login-accounts.json"

# Resolve actual paths
$SRC_DIR = "e:\`u9053\`u9053`u751f`u4e00\`u4e00`u751f`u4e8c\`u65e0`u611f`u5207`u53f7\src"

$sp = New-Object System.Security.SecureString
$TARGET_PASS.ToCharArray() | ForEach-Object { $sp.AppendChar($_) }
$cr = New-Object System.Management.Automation.PSCredential($TARGET_USER, $sp)
Set-Item WSMan:\localhost\Client\TrustedHosts -Value $TARGET_IP -Force -EA SilentlyContinue

Write-Host "=== WAM v3.22.0 Deploy to 179 ===" -ForegroundColor Cyan

$sess = New-PSSession -ComputerName $TARGET_IP -Credential $cr -ErrorAction Stop
Write-Host "[OK] Session: $TARGET_IP" -ForegroundColor Green

Invoke-Command -Session $sess -ScriptBlock {
    param($hd)
    if (-not (Test-Path $hd)) { New-Item -ItemType Directory $hd -Force | Out-Null }
} -ArgumentList $HOT_REMOTE

$files = @("extension.js","accountManager.js","authService.js","cloudPool.js","fingerprintManager.js","webviewProvider.js")
$realSrc = [System.IO.Path]::GetFullPath("e:\`u9053\`u9053`u751f`u4e00\`u4e00`u751f`u4e8c\`u65e0`u611f`u5207`u53f7\src")
