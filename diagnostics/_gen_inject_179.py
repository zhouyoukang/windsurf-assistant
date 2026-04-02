#!/usr/bin/env python3
"""
179笔记本 Windsurf账号轮转注入器 v2
道法自然·无为而无不为·从根本解决

功能:
  - 自动追踪已用账号, 每次选不同账号
  - 通过PS Remoting推送注入脚本到179
  - schtasks执行 (DPAPI+safeStorage全更新)
  - 注入完成后在Session 2启动Windsurf
  - 全程自动化, 无需人工干预

用法:
  python _gen_inject_179.py          # 正常轮转切号
  python _gen_inject_179.py --force  # 强制切号(忽略轮转记录)
  python _gen_inject_179.py --check  # 仅检查179状态
"""
import json, os, sys, subprocess, random
from pathlib import Path
from datetime import datetime

SCRIPT_DIR    = Path(__file__).parent
SNAPSHOTS     = SCRIPT_DIR.parent / '010-道引擎_DaoEngine' / '_wam_snapshots.json'
TEMPLATE      = SCRIPT_DIR / '_inject_179.py'
TRACKER       = SCRIPT_DIR / '_179_used_accounts.json'   # 轮转追踪记录
TARGET_IP     = '192.168.31.179'
TARGET_USER   = 'zhouyoukang'
TARGET_PASS   = 'wsy057066wsy'
REMOTE_DIR    = r'C:\ctemp\ws_inject'
WS_EXE        = r'D:\Windsurf\Windsurf.exe'
# 永久跳过 (141当前活跃账号等)
SKIP_ALWAYS   = {'fpzgcmcdaqbq152@yahoo.com'}

FORCE  = '--force' in sys.argv
CHECK  = '--check' in sys.argv

def log(msg, level='INFO'):
    colors = {'INFO': '\033[36m', 'OK': '\033[32m', 'WARN': '\033[33m', 'ERR': '\033[31m'}
    c = colors.get(level, '')
    print(f"  {c}[{level}]\033[0m {msg}")

def title(msg):
    print(f"\n{'='*60}\n  {msg}\n{'='*60}")


# ── 读取轮转记录 ──
def load_tracker():
    if TRACKER.exists():
        try:
            return json.loads(TRACKER.read_text(encoding='utf-8'))
        except:
            pass
    return {'used': {}, 'current': None}

def save_tracker(t):
    TRACKER.write_text(json.dumps(t, indent=2, ensure_ascii=False), encoding='utf-8')

def mark_used(tracker, email):
    tracker['used'][email] = datetime.now().isoformat()
    tracker['current'] = email
    save_tracker(tracker)


# ── 1. 检查179状态 (可选) ──
if CHECK:
    title("检查179 Windsurf状态")
    sp_block = f"""
$sp = New-Object System.Security.SecureString
'{TARGET_PASS}'.ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential('{TARGET_USER}', $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value '{TARGET_IP}' -Force -ErrorAction SilentlyContinue
Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ScriptBlock {{
    python -c "
import sqlite3,json
db=r'C:\\Users\\zhouyoukang\\AppData\\Roaming\\Windsurf\\User\\globalStorage\\state.vscdb'
try:
    c=sqlite3.connect(db,timeout=3)
    r=c.execute('SELECT value FROM ItemTable WHERE key=?',('windsurfAuthStatus',)).fetchone()
    print('apiKey:', json.loads(r[0]).get('apiKey','')[:55] if r else 'NULL')
    c.close()
except Exception as e: print('err:',e)
" 2>&1
    $ws = Get-WmiObject Win32_Process -Filter \"Name='Windsurf.exe'\" | Group-Object SessionId
    $ws | %{{ Write-Host \"Session $($_.Name): $($_.Count) procs\" }}
}}
"""
    subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', sp_block],
                   encoding='utf-8', errors='replace')
    sys.exit(0)


# ── 2. 选账号 (带轮转追踪) ──
title("Step 1: 选择账号 (轮转机制)")

tracker = load_tracker()
used_set = set(tracker.get('used', {}).keys()) | SKIP_ALWAYS
current  = tracker.get('current')

d = json.loads(SNAPSHOTS.read_text(encoding='utf-8'))
snaps = d.get('snapshots', {})

if FORCE:
    used_set = SKIP_ALWAYS
    log("强制模式: 忽略轮转记录", 'WARN')

# 构建候选列表 (未用过的, 优先2026-03-22)
unused = [(0 if '2026-03-22' in s.get('harvested_at', '') else 1, e, s)
          for e, s in snaps.items() if e not in used_set]
unused.sort(key=lambda x: x[0])

if not unused:
    log("所有账号已用尽! 重置轮转记录...", 'WARN')
    tracker['used'] = {}
    save_tracker(tracker)
    unused = [(0 if '2026-03-22' in s.get('harvested_at', '') else 1, e, s)
              for e, s in snaps.items() if e not in SKIP_ALWAYS]
    unused.sort(key=lambda x: x[0])

# 从同优先级组随机选 (避免总选第一个)
best_priority = unused[0][0]
top_group = [x for x in unused if x[0] == best_priority]
_, NEW_EMAIL, chosen_snap = random.choice(top_group)

NEW_AUTH_STATUS    = chosen_snap['blobs']['windsurfAuthStatus']
NEW_CONFIGURATIONS = chosen_snap['blobs'].get('windsurfConfigurations') or 'null'
NEW_API_KEY        = json.loads(NEW_AUTH_STATUS).get('apiKey', '')

log(f"选中: {NEW_EMAIL}  (剩余未用: {len(unused)-1}个)", 'OK')
log(f"API Key: {NEW_API_KEY[:40]}...", 'INFO')
log(f"Harvested: {chosen_snap.get('harvested_at','?')[:16]}", 'INFO')
if current:
    log(f"上次账号: {current}", 'INFO')


# ── 2. 生成注入脚本 ──
title("Step 2: 生成注入脚本")

template = TEMPLATE.read_text(encoding='utf-8')
inject_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# 安全替换 — 使用Python raw strings + repr()避免转义问题
script = template
script = script.replace('__INJECT_TIME__', inject_time)
script = script.replace('__NEW_EMAIL__', NEW_EMAIL)
script = script.replace('__NEW_API_KEY__', NEW_API_KEY)
# 用 json.dumps 确保合法的Python字符串
script = script.replace("'__NEW_AUTH_STATUS__'", repr(NEW_AUTH_STATUS))
script = script.replace("'__NEW_CONFIGURATIONS__'", repr(NEW_CONFIGURATIONS))

# 本地输出
out_path = SCRIPT_DIR / '_inject_179_live.py'
out_path.write_text(script, encoding='utf-8')
log(f"已生成: {out_path.name} ({len(script)} chars)", 'OK')


# ── 3. 写到ASCII临时路径 ──
title("Step 3: 远程推送+执行")

import tempfile
tmp_dir = Path(r'C:\Temp')  # 纯ASCII临时目录
tmp_dir.mkdir(parents=True, exist_ok=True)

# 注入脚本
tmp_script = tmp_dir / 'ws_inject_179_live.py'
tmp_script.write_text(out_path.read_text(encoding='utf-8'), encoding='utf-8')
log(f"注入脚本: {tmp_script}", 'INFO')

# PS调度脚本 — 写到同一ASCII目录
ps_body = f'''$ErrorActionPreference = 'Stop'
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value '{TARGET_IP}' -Force -ErrorAction SilentlyContinue

# 用纯.NET SecureString, 不依赖Microsoft.PowerShell.Security
$sp = New-Object System.Security.SecureString
'{TARGET_PASS}'.ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential('{TARGET_USER}', $sp)

Write-Host '[1/4] 建立远程会话...'
$sess = New-PSSession -ComputerName {TARGET_IP} -Credential $cr -ErrorAction Stop
Write-Host "[OK] 会话建立: {TARGET_IP} ({TARGET_USER})"

Write-Host '[2/4] 创建远程目录...'
Invoke-Command -Session $sess -ScriptBlock {{
    if (-not (Test-Path '{REMOTE_DIR}')) {{
        New-Item -ItemType Directory '{REMOTE_DIR}' -Force | Out-Null
    }}
    Write-Host "[OK] 目录: {REMOTE_DIR}"
}}

Write-Host '[3/4] 推送注入脚本...'
$content = [IO.File]::ReadAllText('{str(tmp_script).replace(chr(92), '/')}', [Text.Encoding]::UTF8)
Invoke-Command -Session $sess -ScriptBlock {{
    param($c, $p)
    [IO.File]::WriteAllText($p, $c, [Text.Encoding]::UTF8)
    Write-Host "[OK] 脚本已写入: $p ($($c.Length) chars)"
}} -ArgumentList $content, '{REMOTE_DIR}\\inject_live.py'

Write-Host '[4/5] 注入执行 (schtasks — DPAPI全面更新)...'
Invoke-Command -Session $sess -ScriptBlock {{
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pyCmd) {{ $py = $pyCmd.Source }} else {{ $py = 'C:\\Program Files\\Python311\\python.exe' }}
    Write-Host "  python: $py"
    schtasks /delete /tn WSInjectNow /f 2>$null
    $t = (Get-Date).AddSeconds(30).ToString('HH:mm')
    $tr = "`"$py`" `"{REMOTE_DIR}\\inject_live.py`" --no-restart"
    schtasks /create /tn WSInjectNow /tr $tr /sc once /st $t /ru {TARGET_USER} /rp {TARGET_PASS} /rl HIGHEST /f 2>&1 | Write-Host
    Write-Host "  Inject task at $t, waiting 45s..."
    Start-Sleep 45
    schtasks /delete /tn WSInjectNow /f 2>$null
    Write-Host "  Inject task done"
}}

Write-Host '[5/5] Kill 旧Windsurf + 在Session 2重启...'
Invoke-Command -Session $sess -ScriptBlock {{
    # Kill all Windsurf
    Get-Process Windsurf -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep 3
    # Schedule Windsurf start in user session (2min to avoid past-time)
    $st2 = (Get-Date).AddMinutes(2).ToString('HH:mm')
    schtasks /delete /tn WSLaunchUser /f 2>$null
    schtasks /create /tn WSLaunchUser /tr "`"{WS_EXE}`"" /sc once /st $st2 /ru {TARGET_USER} /rp {TARGET_PASS} /it /rl HIGHEST /f 2>&1 | Write-Host
    Write-Host "Windsurf scheduled at $st2 (Session 2)"
}}

Remove-PSSession $sess
Write-Host '[DONE]'
'''

tmp_ps = tmp_dir / 'ws_run_inject_179.ps1'
tmp_ps.write_text(ps_body, encoding='utf-8')
log(f"PS脚本: {tmp_ps}", 'OK')

# ── 4. 执行 ──
title("Step 4: 执行远程注入")

result = subprocess.run(
    ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(tmp_ps)],
    encoding='utf-8', errors='replace'
)

if result.returncode == 0:
    log("注入流程完成", 'OK')
    mark_used(tracker, NEW_EMAIL)
    log(f"已记录: {NEW_EMAIL} 加入已用列表", 'INFO')
else:
    log(f"PS执行返回码: {result.returncode} (可能部分成功)", 'WARN')
    log("手动确认注入结果...", 'WARN')

title("完成")
log(f"账号切换: {NEW_EMAIL}", 'OK')
log(f"API Key: {NEW_API_KEY[:40]}...", 'OK')
log(f"剩余可用账号: {len(unused)-1}个", 'INFO')
print("""
  后续操作:
  ├─ Windsurf将在约2分钟后在179 RDP Session 2自动启动
  ├─ 如不自动出现: 在179桌面手动双击Windsurf图标
  ├─ 如仍显示旧账号: Ctrl+Shift+P → Reload Window
  └─ 切号工具: python _gen_inject_179.py
""")
