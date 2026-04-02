$ErrorActionPreference = "Continue"
$TARGET_IP   = "192.168.31.179"
$TARGET_USER = "zhouyoukang"
$TARGET_PASS = "wsy057066wsy"

$sp = New-Object System.Security.SecureString
$TARGET_PASS.ToCharArray() | ForEach-Object { $sp.AppendChar($_) }
$cr = New-Object System.Management.Automation.PSCredential($TARGET_USER, $sp)
Set-Item WSMan:\localhost\Client\TrustedHosts -Value $TARGET_IP -Force -ErrorAction SilentlyContinue

$result = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ScriptBlock {
    $procs = Get-Process Windsurf -ErrorAction SilentlyContinue
    Write-Host "WS_PROCS:$($procs.Count)"

    # WAM Hub
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:9870/api/pool/status" -UseBasicParsing -TimeoutSec 3
        $d = $r.Content | ConvertFrom-Json
        Write-Host "WAM:OK:available=$($d.available):total=$($d.total)"
    } catch {
        Write-Host "WAM:OFFLINE"
    }

    # Pool key
    $pk = "$env:APPDATA\Windsurf\_pool_apikey.txt"
    if (Test-Path $pk) {
        $k = [System.IO.File]::ReadAllText($pk).Trim()
        Write-Host "POOL_KEY:len=$($k.Length)"
    } else {
        Write-Host "POOL_KEY:MISSING"
    }

    # Extension patch
    $ep = "D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
    if (Test-Path $ep) {
        $ec = [System.IO.File]::ReadAllText($ep)
        Write-Host "EXT_PATCH:$($ec.Contains('POOL_HOT_PATCH_V1'))"
    }

    # Start Windsurf if not running
    if ($procs.Count -eq 0) {
        $wsExe = "D:\Windsurf\Windsurf.exe"
        if (-not (Test-Path $wsExe)) {
            $wsExe = "$env:LOCALAPPDATA\Programs\Windsurf\Windsurf.exe"
        }
        if (Test-Path $wsExe) {
            Start-Process $wsExe
            Write-Host "WS:STARTING:$wsExe"
            Start-Sleep -Seconds 5
            $p2 = Get-Process Windsurf -ErrorAction SilentlyContinue
            Write-Host "WS_AFTER_START:$($p2.Count)"
        } else {
            Write-Host "WS:EXE_NOT_FOUND"
        }
    }
} -ErrorAction Stop

$result | ForEach-Object { Write-Host $_ }
