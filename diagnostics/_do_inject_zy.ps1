$ErrorActionPreference = "Continue"
$TARGET_IP   = "192.168.31.179"
$TARGET_USER = "zhouyoukang"
$TARGET_PASS = "wsy057066wsy"

$sp = New-Object System.Security.SecureString
$TARGET_PASS.ToCharArray() | ForEach-Object { $sp.AppendChar($_) }
$cr = New-Object System.Management.Automation.PSCredential($TARGET_USER, $sp)
Set-Item WSMan:\localhost\Client\TrustedHosts -Value $TARGET_IP -Force -ErrorAction SilentlyContinue

Write-Host "[1] Testing connection..." -ForegroundColor Cyan
try {
    $pc = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ErrorAction Stop -ScriptBlock { $env:COMPUTERNAME + ":" + $env:USERNAME }
    Write-Host "  Connected: $pc" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: $_" -ForegroundColor Red
    exit 1
}

Write-Host "`n[2] Injecting account..." -ForegroundColor Cyan
$result = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ScriptBlock {
    $pyfiles = @(
        "C:\Program Files\Python311\python.exe",
        "C:\Python311\python.exe",
        "python"
    )
    $py = "python"
    foreach ($pf in $pyfiles) {
        if (Test-Path $pf) { $py = $pf; break }
    }
    Write-Host "  Using python: $py"
    & $py "C:\Users\Public\ws_inject\do_inject.py" 2>&1
}
Write-Host "  Result: $result"

Write-Host "`n[3] Restarting Windsurf..." -ForegroundColor Cyan
Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ScriptBlock {
    Stop-Process -Name Windsurf -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    $candidates = @(
        "D:\Windsurf\Windsurf.exe",
        "C:\Users\zhouyoukang\AppData\Local\Programs\Windsurf\Windsurf.exe"
    )
    $exe = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($exe) {
        $sh = New-Object -ComObject Shell.Application
        $sh.Open($exe)
        Write-Host "  Started: $exe"
    } else {
        Write-Host "  WARNING: No Windsurf.exe found"
    }
    Start-Sleep -Seconds 8
    $cnt = (Get-Process Windsurf -ErrorAction SilentlyContinue).Count
    Write-Host "  WS_PROCS: $cnt"
}

Write-Host "`n[4] Final verify..." -ForegroundColor Cyan
$v = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ScriptBlock {
    python -c "
import sqlite3,json,os
from pathlib import Path
u=os.environ.get('USERNAME','zhouyoukang')
db=Path(f'C:/Users/{u}/AppData/Roaming/Windsurf/User/globalStorage/state.vscdb')
if not db.exists():
    print('DB_NOT_FOUND')
else:
    c=sqlite3.connect(str(db))
    r=c.execute('SELECT value FROM ItemTable WHERE key=?',('windsurfAuthStatus',)).fetchone()
    if r:
        a=json.loads(r[0])
        print('FINAL_OK key=' + a.get('apiKey','')[:40])
    else:
        print('FINAL_NULL')
    c.close()
" 2>&1
}
Write-Host "  $v" -ForegroundColor Cyan
Write-Host "`n=== Done ===" -ForegroundColor Green
