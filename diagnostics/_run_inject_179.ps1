
$ErrorActionPreference = 'Stop'
Set-Item WSMan:\localhost\Client\TrustedHosts -Value '192.168.31.179' -Force -ErrorAction SilentlyContinue

# 用纯.NET构建SecureString — 不依赖Security模块
$SecPass = New-Object System.Security.SecureString
'wsy057066wsy'.ToCharArray() | ForEach-Object { $SecPass.AppendChar($_) }
$cred = New-Object System.Management.Automation.PSCredential('zhouyoukang', $SecPass)

$sess = New-PSSession -ComputerName 192.168.31.179 -Credential $cred -ErrorAction Stop
Write-Host "  [OK] Session: 192.168.31.179 (zhouyoukang)"

# 目标目录
Invoke-Command -Session $sess -ScriptBlock {
    if (-not (Test-Path 'C:\ctemp\ws_inject')) { New-Item -ItemType Directory 'C:\ctemp\ws_inject' -Force | Out-Null }
}

# 推送脚本
$scriptPath = 'e:\\道\\道生一\\一生二\\Windsurf无限额度\\040-诊断工具_Diagnostics\\_inject_179_live.py'
$content = [System.IO.File]::ReadAllText($scriptPath, [System.Text.Encoding]::UTF8)
Write-Host "  [INFO] Pushing script: $($content.Length) chars"

Invoke-Command -Session $sess -ScriptBlock {
    param($c, $p)
    [System.IO.File]::WriteAllText($p, $c, [System.Text.Encoding]::UTF8)
    Write-Host "  [OK] Script at: $p"
} -ArgumentList $content, 'C:\ctemp\ws_inject\inject_live.py'

# 执行注入
Write-Host "  [INFO] Running injection..."
$result = Invoke-Command -Session $sess -ScriptBlock {
    param($u, $p)
    $env:TARGET_WS_USER = $u
    & python $p
} -ArgumentList 'zhouyoukang', 'C:\ctemp\ws_inject\inject_live.py'

$result | ForEach-Object { Write-Host "    $_" }

Remove-PSSession $sess -ErrorAction SilentlyContinue
Write-Host "  [DONE]"
