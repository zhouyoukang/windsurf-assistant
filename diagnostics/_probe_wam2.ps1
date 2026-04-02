$ErrorActionPreference = "Continue"
$TARGET_IP   = "192.168.31.179"
$TARGET_USER = "zhouyoukang"
$TARGET_PASS = "wsy057066wsy"

$sp = New-Object System.Security.SecureString
$TARGET_PASS.ToCharArray() | ForEach-Object { $sp.AppendChar($_) }
$cr = New-Object System.Management.Automation.PSCredential($TARGET_USER, $sp)
Set-Item WSMan:\localhost\Client\TrustedHosts -Value $TARGET_IP -Force -ErrorAction SilentlyContinue

$result = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ScriptBlock {

    # 1. 读取wam_hub.py前120行了解API和pool_key写入机制
    Write-Host "=== wam_hub.py源码 ===" -ForegroundColor Cyan
    $scriptPath = "E:\道\道生一\一生二\无感切号\scripts\wam_hub.py"
    if (Test-Path $scriptPath) {
        Get-Content $scriptPath -TotalCount 120 | ForEach-Object { Write-Host "SRC:$_" }
    } else {
        Write-Host "SRC:NOT_FOUND:$scriptPath"
        # Try to find it
        Get-ChildItem "E:\道" -Recurse -Filter "wam_hub.py" -ErrorAction SilentlyContinue | 
            ForEach-Object { Write-Host "FOUND:$($_.FullName)" }
    }

    # 2. 检查无感切号目录结构
    Write-Host "`n=== 无感切号目录 ===" -ForegroundColor Cyan
    $basePath = "E:\道\道生一\一生二\无感切号"
    if (Test-Path $basePath) {
        Get-ChildItem $basePath -Recurse -ErrorAction SilentlyContinue | 
            Select-Object -First 30 |
            ForEach-Object { Write-Host "DIR:$($_.FullName)" }
    }

    # 3. 检查pool_apikey.txt当前内容
    Write-Host "`n=== pool_apikey.txt当前状态 ===" -ForegroundColor Cyan
    $pk = "$env:APPDATA\Windsurf\_pool_apikey.txt"
    if (Test-Path $pk) {
        $k = [System.IO.File]::ReadAllText($pk).Trim()
        Write-Host "POOL_KEY:len=$($k.Length):key=$($k.Substring(0,[Math]::Min(50,$k.Length)))"
    }

    # 4. 检查WAM Hub是否同步了pool_apikey.txt (active账号的key)
    Write-Host "`n=== WAM Hub活跃账号信息 ===" -ForegroundColor Cyan
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:9870/api/pool/status" -UseBasicParsing -TimeoutSec 5
        $d = $r.Content | ConvertFrom-Json
        Write-Host "ACTIVE_EMAIL:$($d.activeEmail)"
        Write-Host "ACTIVE_REMAINING:$($d.activeRemaining)"
        Write-Host "ACTIVE_INDEX:$($d.activeIndex)"
        Write-Host "SWITCH_COUNT:$($d.switchCount)"
        Write-Host "PROXY_MODE:$($d.proxyMode)"
    } catch {
        Write-Host "WAM:STATUS_FAIL"
    }

    # 5. 检查state.vscdb的当前auth
    Write-Host "`n=== state.vscdb Auth ===" -ForegroundColor Cyan
    $db = "$env:APPDATA\Windsurf\User\globalStorage\state.vscdb"
    if (Test-Path $db) {
        python -c "
import sqlite3,json,os
db=os.environ.get('APPDATA','')+r'\Windsurf\User\globalStorage\state.vscdb'
try:
    c=sqlite3.connect(db,timeout=3)
    r=c.execute(\"SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'\").fetchone()
    if r:
        a=json.loads(r[0])
        print('AUTH_EMAIL:'+str(a.get('email','')))
        print('AUTH_KEYLEN:'+str(len(a.get('apiKey',''))))
        print('AUTH_KEY40:'+str(a.get('apiKey','')[:40]))
        # Print all keys in auth object
        print('AUTH_KEYS:'+','.join(a.keys()))
    else:
        print('AUTH:NULL')
    c.close()
except Exception as e:
    print('AUTH_ERR:'+str(e))
" 2>&1 | ForEach-Object { Write-Host $_ }
    }

    Write-Host "PROBE2_DONE"
} -ErrorAction Stop

$result | ForEach-Object { Write-Host $_ }
