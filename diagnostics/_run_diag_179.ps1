###############################################################################
# 179全面诊断 + 修复脚本 — 道法自然·推进到底
###############################################################################
$ErrorActionPreference = "Continue"
$TARGET_IP   = "192.168.31.179"
$TARGET_USER = "zhouyoukang"
$TARGET_PASS = "wsy057066wsy"

$sp = New-Object System.Security.SecureString
$TARGET_PASS.ToCharArray() | ForEach-Object { $sp.AppendChar($_) }
$cr = New-Object System.Management.Automation.PSCredential($TARGET_USER, $sp)
Set-Item WSMan:\localhost\Client\TrustedHosts -Value $TARGET_IP -Force -ErrorAction SilentlyContinue

Write-Host "=== Step1: 测试WinRM连接 ===" -ForegroundColor Cyan
try {
    $hostname = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ScriptBlock { $env:COMPUTERNAME } -ErrorAction Stop
    Write-Host "连接成功: $hostname" -ForegroundColor Green
} catch {
    Write-Host "WinRM连接失败: $_" -ForegroundColor Red
    exit 1
}

# 写入诊断Python脚本
$diagPy = @"
import subprocess, json, sqlite3, os, sys, socket
from pathlib import Path

users = ['zhouyoukang', 'Administrator', 'ai']
ws_paths = [
    r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js',
    r'C:\Users\zhouyoukang\AppData\Local\Programs\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js',
    r'C:\Users\Administrator\AppData\Local\Programs\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js',
]
ext_paths = [
    r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js',
    r'C:\Users\zhouyoukang\AppData\Local\Programs\Windsurf\resources\app\extensions\windsurf\dist\extension.js',
]

print('=== WINDSURF INSTALL ===')
wb_p = None
for p in ws_paths:
    if Path(p).exists():
        size = Path(p).stat().st_size // 1024
        print(f'WB_FOUND:{p}:{size}KB')
        wb_p = p
        break
if not wb_p:
    print('WB_FOUND:NONE')

print('=== PROCESSES ===')
try:
    r = subprocess.run(['tasklist','/FI','IMAGENAME eq Windsurf.exe','/FO','CSV'],capture_output=True,text=True,timeout=5)
    lines = [l for l in r.stdout.strip().split('\n') if 'Windsurf' in l]
    print(f'WS_PROCS:{len(lines)}')
except:
    print('WS_PROCS:ERROR')

print('=== AUTH STATUS ===')
for user in users:
    db = Path(f'C:/Users/{user}/AppData/Roaming/Windsurf/User/globalStorage/state.vscdb')
    if not db.exists():
        print(f'AUTH:{user}:NO_DB')
        continue
    try:
        c = sqlite3.connect(str(db), timeout=3)
        row = c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
        if not row:
            print(f'AUTH:{user}:NULL')
        else:
            a = json.loads(row[0])
            ak = a.get('apiKey','')
            em = a.get('email','')
            print(f'AUTH:{user}:email={em}:keylen={len(ak)}:key={ak[:40]}')
        c.close()
    except Exception as e:
        print(f'AUTH:{user}:ERROR:{e}')

print('=== PATCHES ===')
if wb_p:
    try:
        content = Path(wb_p).read_text(encoding='utf-8',errors='replace')
        checks = {
            'opus46_init': '__o46=' in content,
            'gbe_ratelimit': '__wamRateLimit' in content,
            'capacity_bypass': 'if(!1&&!Ru.hasCapacity)' in content,
            'maxgen_9999': 'maxGeneratorInvocations=9999' in content,
            'pool_hotpatch': 'POOL_HOT_PATCH_V1' in content,
        }
        for k,v in checks.items():
            print(f'PATCH:{k}:{"YES" if v else "NO"}')
    except Exception as e:
        print(f'PATCH:READ_ERROR:{e}')
else:
    print('PATCH:NO_WB_FOUND')

print('=== PORTS ===')
for port in [9870, 9876, 19875, 19877]:
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(('127.0.0.1', port))
        print(f'PORT:{port}:OPEN')
        s.close()
    except:
        print(f'PORT:{port}:CLOSED')

print('=== EXTENSION ===')
for p in ext_paths:
    if Path(p).exists():
        size = Path(p).stat().st_size // 1024
        content = Path(p).read_text(encoding='utf-8',errors='replace')[:3000]
        has_patch = 'POOL_HOT_PATCH_V1' in content
        print(f'EXT:{p}:{size}KB:hotpatch={has_patch}')
        break
else:
    print('EXT:NONE')

print('=== POOL KEY ===')
for user in users:
    pk = Path(f'C:/Users/{user}/AppData/Roaming/Windsurf/_pool_apikey.txt')
    if pk.exists():
        content = pk.read_text(encoding='utf-8',errors='replace').strip()
        print(f'POOL_KEY:{user}:len={len(content)}:key={content[:40]}')
    else:
        print(f'POOL_KEY:{user}:MISSING')

print('=== WAM HUB ===')
try:
    import urllib.request
    r = urllib.request.urlopen('http://127.0.0.1:9870/api/pool/status', timeout=3)
    data = json.loads(r.read())
    print(f'WAM_HUB:OK:{json.dumps(data)[:200]}')
except Exception as e:
    print(f'WAM_HUB:OFFLINE:{e}')

print('DIAG_DONE')
"@

$diagPyBytes = [System.Text.Encoding]::UTF8.GetBytes($diagPy)
$diagPyB64 = [Convert]::ToBase64String($diagPyBytes)

Write-Host "`n=== Step2: 运行全面诊断 ===" -ForegroundColor Cyan
$result = Invoke-Command -ComputerName $TARGET_IP -Credential $cr -ArgumentList $diagPyB64 -ScriptBlock {
    param($b64)
    if (-not (Test-Path 'C:\ctemp')) { New-Item -ItemType Directory 'C:\ctemp' -Force | Out-Null }
    $bytes = [Convert]::FromBase64String($b64)
    [System.IO.File]::WriteAllBytes('C:\ctemp\_full_diag.py', $bytes)
    python 'C:\ctemp\_full_diag.py' 2>&1
} -ErrorAction Stop

$result | ForEach-Object { Write-Host "  $_" }
Write-Host "`n=== 诊断完成 ===" -ForegroundColor Green
