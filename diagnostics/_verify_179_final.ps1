$ErrorActionPreference = "Continue"
$TARGET_IP   = "192.168.31.179"
$TARGET_USER = "zhouyoukang"
$TARGET_PASS = "wsy057066wsy"

$sp = New-Object System.Security.SecureString
$TARGET_PASS.ToCharArray() | ForEach-Object { $sp.AppendChar($_) }
$cr = New-Object System.Management.Automation.PSCredential($TARGET_USER, $sp)
Set-Item WSMan:\localhost\Client\TrustedHosts -Value $TARGET_IP -Force -ErrorAction SilentlyContinue

Write-Host "=== 179 Windsurf最终状态验证 ===" -ForegroundColor Cyan
Write-Host "时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Gray

$result = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ScriptBlock {
    $APPDATA = $env:APPDATA
    $USER    = $env:USERNAME

    Write-Host "=== FINAL STATE ===" -ForegroundColor Cyan

    # 1. Auth via Python
    $pyCode = @"
import sqlite3,json,os
db=os.environ.get('APPDATA','')+r'\Windsurf\User\globalStorage\state.vscdb'
try:
    c=sqlite3.connect(db,timeout=3)
    r=c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
    if r:
        a=json.loads(r[0])
        print('AUTH:email='+str(a.get('email','EMPTY'))+':keylen='+str(len(a.get('apiKey',''))))
    else:
        print('AUTH:NULL')
    c.close()
except Exception as e:
    print('AUTH:ERR:'+str(e)[:50])
"@
    $pyCode | python 2>&1 | ForEach-Object { Write-Host "  $_" }

    # 2. Pool key
    $pk = "$APPDATA\Windsurf\_pool_apikey.txt"
    if (Test-Path $pk) {
        $k = [System.IO.File]::ReadAllText($pk).Trim()
        Write-Host "  POOL_KEY:len=$($k.Length):starts=$($k.Substring(0,[Math]::Min(30,$k.Length)))"
    } else {
        Write-Host "  POOL_KEY:MISSING"
    }

    # 3. Extension patch
    $ep = "D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
    if (-not (Test-Path $ep)) {
        $ep = "$env:LOCALAPPDATA\Programs\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
    }
    if (Test-Path $ep) {
        $ec = [System.IO.File]::ReadAllText($ep)
        Write-Host "  EXT_HOTPATCH:$($ec.Contains('POOL_HOT_PATCH_V1'))"
        Write-Host "  EXT_SIZE:$([int]($ec.Length/1024))KB"
    } else {
        Write-Host "  EXT:NOT_FOUND"
    }

    # 4. workbench patches
    $wb = "D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js"
    if (Test-Path $wb) {
        $wc = [System.IO.File]::ReadAllText($wb)
        Write-Host "  WB_GBE:$($wc.Contains('__wamRateLimit'))"
        Write-Host "  WB_MAXGEN:$($wc.Contains('maxGeneratorInvocations=9999'))"
        Write-Host "  WB_OPUS46:$($wc.Contains('__o46='))"
    }

    # 5. WAM Hub
    $tcp = New-Object System.Net.Sockets.TcpClient
    try {
        $tcp.Connect("127.0.0.1", 9870)
        Write-Host "  WAM_9870:ONLINE"
        $tcp.Close()
    } catch {
        Write-Host "  WAM_9870:OFFLINE"
    }

    # 6. WAM Hub status (HTTP)
    try {
        $r2 = Invoke-WebRequest "http://127.0.0.1:9870/api/pool/status" -UseBasicParsing -TimeoutSec 4
        $d = $r2.Content | ConvertFrom-Json
        Write-Host "  WAM_STATUS:total=$($d.total):available=$($d.available)"
    } catch {
        Write-Host "  WAM_STATUS:FAIL"
    }

    # 7. Scheduled tasks (compatible syntax)
    $t1 = Get-ScheduledTask -TaskName "WAMHub" -ErrorAction SilentlyContinue
    if ($t1) { Write-Host "  TASK_WAMHUB:$($t1.State)" } else { Write-Host "  TASK_WAMHUB:MISSING" }
    
    $t2 = Get-ScheduledTask -TaskName "WAMHubWatchdog" -ErrorAction SilentlyContinue
    if ($t2) { Write-Host "  TASK_WATCHDOG:$($t2.State)" } else { Write-Host "  TASK_WATCHDOG:MISSING" }

    # 8. Windsurf process (from all sessions via WMI)
    $wmiProcs = Get-WmiObject Win32_Process -Filter "Name='Windsurf.exe'" -ErrorAction SilentlyContinue
    Write-Host "  WS_PROCS_WMI:$(@($wmiProcs).Count)"

    Write-Host "=== END ===" -ForegroundColor Cyan
} -ErrorAction Stop

$result | ForEach-Object { Write-Host $_ }
