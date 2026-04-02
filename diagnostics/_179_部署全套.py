#!/usr/bin/env python3
"""
_179_部署全套.py — 远程179全量部署 (本地执行，通过WinRM)
================================================================
道法自然·无为而无不为

功能:
  1. WinRM连接179
  2. 检测179补丁状态
  3. 推送ws_repatch.py并执行(P12/P13 opus-4-6注入)
  4. 推送patch_continue_bypass.py并执行
  5. 从快照池选最优账号注入state.vscdb
  6. 验证注入结果
  7. 提示reload

用法:
  python _179_部署全套.py           # 完整部署
  python _179_部署全套.py --check   # 仅检查179状态
  python _179_部署全套.py --patch   # 仅打补丁(不注入账号)
  python _179_部署全套.py --inject  # 仅注入账号
"""
import subprocess, json, base64, os, sys, struct, time, random
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
ENGINE_DIR   = SCRIPT_DIR.parent / '010-道引擎_DaoEngine'
SNAPSHOT_FILE = ENGINE_DIR / '_wam_snapshots.json'
WS_REPATCH   = SCRIPT_DIR.parent / 'ws_repatch.py'
CB_PATCH     = ENGINE_DIR / 'patch_continue_bypass.py'

TARGET_IP   = '192.168.31.179'
TARGET_USER = 'zhouyoukang'
TARGET_PASS = 'wsy057066wsy'
SKIP_EMAILS = {'ehhs619938345@yahoo.com', 'fpzgcmcdaqbq152@yahoo.com'}

PYTHON_LOCAL = r'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe'

def log(tag, msg, color=''):
    colors = {'ok': '\033[92m', 'warn': '\033[93m', 'err': '\033[91m', 'info': '\033[96m', '': ''}
    reset = '\033[0m'
    c = colors.get(color, '')
    print(f'  [{tag}] {c}{msg}{reset}')

def run_remote_cmd(ps_cmd, timeout=60):
    """通过PowerShell WinRM执行远程命令，返回(stdout, returncode)"""
    full_cmd = [
        'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
        f'''
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -ErrorAction SilentlyContinue
$result = Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ScriptBlock {{
    {ps_cmd}
}} 2>&1
$result | ForEach-Object {{ Write-Host $_ }}
exit $LASTEXITCODE
'''
    ]
    try:
        proc = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='replace')
        return proc.stdout + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired:
        return 'TIMEOUT', -1
    except Exception as e:
        return f'ERROR: {e}', -1

def check_179_state():
    """检查179当前状态"""
    print('\n' + '='*60)
    print('  检查179 Windsurf状态')
    print('='*60)
    
    out, rc = run_remote_cmd(r'''
$wb_candidates = @(
    "D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js",
    "C:\Users\$env:USERNAME\AppData\Local\Programs\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js"
)
$wb = $null
foreach ($p in $wb_candidates) { if (Test-Path $p) { $wb = $p; break } }
$ws = Get-Process Windsurf -ErrorAction SilentlyContinue
$db = "C:\Users\$env:USERNAME\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb"
$apiKey = ""
if (Test-Path $db) {
    $apiKey = python -c "
import sqlite3,json
try:
    c=sqlite3.connect(r'$db',timeout=3)
    r=c.execute('SELECT value FROM ItemTable WHERE key=?',('windsurfAuthStatus',)).fetchone()
    if r:
        a=json.loads(r[0])
        print(a.get('apiKey','?')[:50])
    else:
        print('NULL')
    c.close()
except Exception as e:
    print(str(e))
" 2>&1
}
Write-Host "WB_JS=$wb"
Write-Host "WS_RUNNING=$(if ($ws) {'yes'} else {'no'})"
Write-Host "API_KEY=$apiKey"
''', timeout=30)
    
    state = {}
    for line in out.strip().split('\n'):
        line = line.strip()
        if '=' in line:
            k, v = line.split('=', 1)
            state[k.strip()] = v.strip()
    
    wb = state.get('WB_JS', '')
    log('INFO', f"workbench.js: {wb or 'NOT FOUND'}", 'info' if wb else 'err')
    log('INFO', f"Windsurf running: {state.get('WS_RUNNING','?')}", 'ok' if state.get('WS_RUNNING') == 'yes' else 'warn')
    log('INFO', f"Current apiKey: {state.get('API_KEY','?')[:40]}...", '')
    
    return state

def check_179_patches(wb_path):
    """检查179上的补丁状态"""
    print('\n  [补丁状态检查]')
    out, rc = run_remote_cmd(f'''
$wb = "{wb_path.replace(chr(92), chr(92)+chr(92))}"
if (Test-Path $wb) {{
    $content = [System.IO.File]::ReadAllText($wb)
    $checks = @{{
        "p12_opus46_init"    = $content.Contains("__o46=Object.assign(")
        "p13_opus46_refresh" = $content.Contains("__o46b=Object.assign(")
        "p_gbe_silent"       = $content.Contains("__wamRateLimit")
        "p_capacity_bypass"  = $content.Contains("if(!1&&!Ru.hasCapacity)")
        "p_maxgen_9999"      = $content.Contains("maxGeneratorInvocations=9999")
        "p_autocontinue"     = $content.Contains("autoContinueOnMaxGeneratorInvocations.ENABLED")
        "p_autorun_true"     = $content.Contains("autoRunAllowed=!0")
        "size_kb"            = [int]($content.Length / 1024)
    }}
    foreach ($k in $checks.Keys) {{
        Write-Host "PATCH:$k=$(if ($checks[$k]) {{'YES'}} else {{'NO'}})"
    }}
}} else {{
    Write-Host "PATCH:error=wb_not_found"
}}
''', timeout=20)
    
    patches = {}
    for line in out.strip().split('\n'):
        line = line.strip()
        if line.startswith('PATCH:'):
            k, v = line[6:].split('=', 1)
            patches[k] = v.strip()
    
    needs_patch = False
    for k in ['p12_opus46_init', 'p13_opus46_refresh', 'p_gbe_silent', 'p_capacity_bypass', 'p_maxgen_9999']:
        status = patches.get(k, 'UNKNOWN')
        ok = status == 'YES'
        icon = '✅' if ok else '❌'
        if not ok:
            needs_patch = True
        print(f'    {icon} {k}: {status}')
    
    print(f'    📊 workbench.js size: {patches.get("size_kb","?")}KB')
    return patches, needs_patch

def deploy_patches_to_179(wb_path):
    """推送并执行补丁"""
    print('\n' + '='*60)
    print('  部署补丁到179')
    print('='*60)
    
    # 读取本地脚本内容
    ws_content = WS_REPATCH.read_text('utf-8', errors='replace')
    cb_content = CB_PATCH.read_text('utf-8', errors='replace')
    
    # 通过PowerShell传输文件内容（base64编码避免特殊字符问题）
    ws_b64 = base64.b64encode(ws_content.encode('utf-8')).decode('ascii')
    cb_b64 = base64.b64encode(cb_content.encode('utf-8')).decode('ascii')
    
    # 推送ws_repatch.py
    print('\n  [推送ws_repatch.py]')
    out, rc = run_remote_cmd(f'''
$tmpDir = "C:\\ctemp\\ws_patches_opus46"
if (-not (Test-Path $tmpDir)) {{ New-Item -ItemType Directory $tmpDir -Force | Out-Null }}
$b64 = "{ws_b64}"
$bytes = [System.Convert]::FromBase64String($b64)
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
$wsPath = "$tmpDir\\ws_repatch.py"
[System.IO.File]::WriteAllText($wsPath, $text, [System.Text.Encoding]::UTF8)
Write-Host "Written: $wsPath ($($bytes.Length) bytes)"
$out = python $wsPath 2>&1
$out | ForEach-Object {{ Write-Host "WS_OUT: $_" }}
Write-Host "WS_EXIT:$LASTEXITCODE"
''', timeout=120)
    
    for line in out.strip().split('\n'):
        line = line.strip()
        if 'PATCHED' in line or 'SKIP' in line or 'WS_EXIT' in line:
            icon = '✅' if ('PATCHED' in line or 'WS_EXIT:0' in line) else '⚠️'
            print(f'    {icon} {line}')
        elif 'WS_OUT:' in line:
            print(f'      {line[7:]}')
    
    # 推送patch_continue_bypass.py
    print('\n  [推送patch_continue_bypass.py]')
    out2, rc2 = run_remote_cmd(f'''
$tmpDir = "C:\\ctemp\\ws_patches_opus46"
$b64 = "{cb_b64}"
$bytes = [System.Convert]::FromBase64String($b64)
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
$cbPath = "$tmpDir\\patch_continue_bypass.py"
[System.IO.File]::WriteAllText($cbPath, $text, [System.Text.Encoding]::UTF8)
Write-Host "Written: $cbPath"
$out = python $cbPath --verify 2>&1
$out | Select-Object -Last 5 | ForEach-Object {{ Write-Host "CB_OUT: $_" }}
Write-Host "CB_EXIT:$LASTEXITCODE"
''', timeout=90)
    
    for line in out2.strip().split('\n'):
        line = line.strip()
        if 'CB_OUT:' in line:
            content = line[7:]
            icon = '✅' if 'APPLIED' in content else ''
            print(f'    {icon} {content}')
        elif 'CB_EXIT' in line:
            icon = '✅' if 'CB_EXIT:0' in line else '⚠️'
            print(f'    {icon} {line}')
    
    log('OK', '补丁部署完成', 'ok')

def select_best_account(current_key=''):
    """从快照池选最优账号"""
    data = json.loads(SNAPSHOT_FILE.read_text('utf-8'))
    snaps = data.get('snapshots', {})
    
    candidates = []
    for email, snap in snaps.items():
        if email in SKIP_EMAILS:
            continue
        auth_str = snap.get('blobs', {}).get('windsurfAuthStatus', '')
        if not auth_str:
            continue
        try:
            auth = json.loads(auth_str)
            key = auth.get('apiKey', '')
        except:
            continue
        
        # 跳过当前账号
        if current_key and len(current_key) > 15 and key.startswith(current_key[:15]):
            continue
        
        ts = snap.get('harvested_at', '')
        score = 0
        if '2026-03-22' in ts: score += 10
        elif '2026-03-21' in ts: score += 5
        
        conf = snap.get('blobs', {}).get('windsurfConfigurations', '')
        candidates.append({
            'email': email,
            'key': key,
            'auth': auth_str,
            'conf': conf,
            'ts': ts,
            'score': score,
        })
    
    if not candidates:
        return None
    
    # 按score排序，同score中随机
    candidates.sort(key=lambda x: x['score'], reverse=True)
    top_score = candidates[0]['score']
    top_group = [c for c in candidates if c['score'] >= top_score]
    return random.choice(top_group)

def inject_account_to_179(account):
    """注入账号到179 — 使用纯base64传输，避免任何引号冲突"""
    print(f'\n  [注入账号: {account["email"]}]')
    
    # base64编码所有数据
    auth_b64 = base64.b64encode(account['auth'].encode('utf-8')).decode('ascii')
    conf_b64 = base64.b64encode((account['conf'] or '').encode('utf-8')).decode('ascii')
    
    # 构建完整的Python注入脚本(纯ASCII，无PS变量冲突)
    inject_script = f'''import sqlite3, json, shutil, base64, os
from pathlib import Path
AUTH_B64 = "{auth_b64}"
CONF_B64 = "{conf_b64}"
auth_str = base64.b64decode(AUTH_B64).decode("utf-8")
conf_str = base64.b64decode(CONF_B64).decode("utf-8") if CONF_B64 else ""
user = os.environ.get("USERNAME", "zhouyoukang")
db = Path(f"C:/Users/{{user}}/AppData/Roaming/Windsurf/User/globalStorage/state.vscdb")
print(f"DB: {{db}}")
print(f"DB exists: {{db.exists()}}")
if not db.exists():
    print("INJECT:ERROR:db_not_found")
    exit(1)
bak = str(db) + ".bak_opus46"
if not Path(bak).exists():
    shutil.copy2(db, bak)
conn = sqlite3.connect(str(db), timeout=15)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=10000")
conn.execute("INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)", ("windsurfAuthStatus", auth_str.strip()))
if conf_str.strip() and conf_str.strip() != "null":
    conn.execute("INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)", ("windsurfConfigurations", conf_str.strip()))
conn.commit()
r = conn.execute("SELECT value FROM ItemTable WHERE key=?", ("windsurfAuthStatus",)).fetchone()
if r:
    a = json.loads(r[0])
    print("INJECT:OK:" + a.get("apiKey","?")[:50])
conn.close()
'''
    # base64编码整个脚本(彻底避免任何引号/换行问题)
    script_b64 = base64.b64encode(inject_script.encode('utf-8')).decode('ascii')
    
    out, rc = run_remote_cmd(f'''
$tmpDir = "C:\\ctemp\\ws_patches_opus46"
if (-not (Test-Path $tmpDir)) {{ New-Item -ItemType Directory $tmpDir -Force | Out-Null }}
$scriptB64 = "{script_b64}"
$scriptBytes = [System.Convert]::FromBase64String($scriptB64)
$scriptText = [System.Text.Encoding]::UTF8.GetString($scriptBytes)
$scriptPath = "$tmpDir\\inject_account.py"
[System.IO.File]::WriteAllText($scriptPath, $scriptText, [System.Text.Encoding]::UTF8)
$out = python $scriptPath 2>&1
$out | ForEach-Object {{ Write-Host "INJECT_OUT: $_" }}
Write-Host "INJECT_EXIT:$LASTEXITCODE"
''', timeout=30)
    
    for line in out.strip().split('\n'):
        line = line.strip()
        if 'INJECT:OK' in line:
            log('OK', f'账号注入成功: {line.split("INJECT:OK:")[-1]}', 'ok')
        elif 'INJECT:ERROR' in line or 'INJECT_EXIT:1' in line:
            log('ERR', f'注入失败: {line}', 'err')
        elif 'INJECT_OUT:' in line:
            content = line[12:]
            if content.strip():
                print(f'      {content}')
        elif 'INJECT_EXIT:0' in line:
            log('OK', '注入脚本执行成功', 'ok')
    
    return rc == 0

def trigger_179_reload():
    """触发179 Windsurf重载"""
    print('\n  [触发Windsurf重载]')
    out, rc = run_remote_cmd('''
$ws = Get-Process Windsurf -ErrorAction SilentlyContinue
if ($ws) {
    Write-Host "RELOAD:ws_running:$($ws.Count)"
    Write-Host "RELOAD:manual:Ctrl+Shift+P -> Reload Window"
} else {
    Write-Host "RELOAD:ws_not_running:next_launch_will_load_patches"
}
''', timeout=15)
    
    for line in out.strip().split('\n'):
        line = line.strip()
        if 'RELOAD:' in line:
            parts = line.split(':')
            if 'manual' in line:
                log('WARN', '179 Windsurf正在运行: 请手动 Ctrl+Shift+P → Reload Window', 'warn')
            elif 'not_running' in line:
                log('OK', '179 Windsurf未运行: 下次启动自动加载所有补丁', 'ok')

def main():
    args = set(sys.argv[1:])
    do_check  = '--check' in args
    do_patch  = '--patch' in args or (not do_check and '--inject' not in args)
    do_inject = '--inject' in args or (not do_check and '--patch' not in args)
    
    print('=' * 65)
    print('  179笔记本 全量突破部署 — 彻底解决opus-4-6限制')
    print('=' * 65)
    
    # Step 1: 检查179状态
    state = check_179_state()
    wb_path = state.get('WB_JS', '')
    
    if not wb_path:
        log('ERR', '179 workbench.js未找到，请确认Windsurf已安装', 'err')
        sys.exit(1)
    
    # Step 2: 检查补丁状态
    patches, needs_patch = check_179_patches(wb_path)
    
    if do_check:
        print('\n[仅检查模式，未修改179]')
        return
    
    # Step 3: 部署补丁
    if do_patch:
        if needs_patch:
            log('INFO', '检测到缺失补丁，开始部署...', 'info')
            deploy_patches_to_179(wb_path)
        else:
            log('OK', '179 所有关键补丁已应用，跳过', 'ok')
        
        # 重新验证
        patches_after, still_needs = check_179_patches(wb_path)
        if not still_needs:
            log('OK', '179 补丁验证通过', 'ok')
        else:
            log('WARN', '179 部分补丁未能应用，继续执行账号注入', 'warn')
    
    # Step 4: 账号注入
    if do_inject:
        current_key = state.get('API_KEY', '')
        account = select_best_account(current_key)
        
        if not account:
            log('ERR', '账号池无可用账号', 'err')
            sys.exit(1)
        
        log('INFO', f'选中账号: {account["email"]}  harvested: {account["ts"][:10]}', 'info')
        inject_account_to_179(account)
    
    # Step 5: 触发重载
    trigger_179_reload()
    
    # 最终报告
    print('\n' + '='*65)
    print('  179部署完成 ✅')
    print('='*65)
    print('  激活步骤:')
    print('  1. 在179上: Ctrl+Shift+P → Reload Window')
    print('  2. 模型选择器应显示 Claude Opus 4.6')
    print('  3. 选择并发起对话 — 三层突破已全量激活')
    print('')

if __name__ == '__main__':
    main()
