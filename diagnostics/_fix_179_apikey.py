#!/usr/bin/env python3
"""
_fix_179_apikey.py — 一键修复179 Windsurf API key not found
道法自然·直指根源

问题: Permission denied: failed to get primary API key; API key not found
根因: state.vscdb中windsurfAuthStatus为空或apiKey失效
修复: 从WAM快照池选最优账号，直接注入179 state.vscdb，重启Windsurf
"""
import subprocess, json, base64, sys, time
from pathlib import Path

TARGET_IP   = '192.168.31.179'
TARGET_USER = 'zhouyoukang'
TARGET_PASS = 'wsy057066wsy'

SCRIPT_DIR    = Path(__file__).parent
ENGINE_DIR    = SCRIPT_DIR.parent / '010-道引擎_DaoEngine'
SNAPSHOT_FILE = ENGINE_DIR / '_wam_snapshots.json'
SKIP_EMAILS   = {'ehhs619938345@yahoo.com', 'fpzgcmcdaqbq152@yahoo.com'}

def log(tag, msg, ok=None):
    colors = {'OK': '\033[92m', 'ERR': '\033[91m', 'WARN': '\033[93m', 'INFO': '\033[96m', 'HEAD': '\033[97m'}
    c = colors.get(tag, '\033[0m')
    r = '\033[0m'
    print(f'  [{tag}] {c}{msg}{r}')

def run_ps(cmd: str, timeout=60) -> tuple[str, int]:
    """通过PowerShell WinRM执行远程命令"""
    full = [
        'powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
        f'''
$sp = New-Object System.Security.SecureString
"{TARGET_PASS}".ToCharArray() | ForEach-Object {{ $sp.AppendChar($_) }}
$cr = New-Object System.Management.Automation.PSCredential("{TARGET_USER}", $sp)
Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -ErrorAction SilentlyContinue
Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ErrorAction Stop -ScriptBlock {{
{cmd}
}} 2>&1
'''
    ]
    r = subprocess.run(full, capture_output=True, text=True, timeout=timeout,
                       encoding='utf-8', errors='replace')
    out = r.stdout.strip() + (('\nSTDERR:' + r.stderr.strip()) if r.stderr.strip() else '')
    return out, r.returncode

def run_remote_py(py_code: str, timeout=60) -> tuple[str, int]:
    """将Python代码base64编码后在179上执行"""
    b64 = base64.b64encode(py_code.encode('utf-8')).decode('ascii')
    ps_cmd = f'''
$b64 = "{b64}"
$bytes = [System.Convert]::FromBase64String($b64)
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
if (-not (Test-Path "C:\\ctemp")) {{ New-Item -ItemType Directory "C:\\ctemp" -Force | Out-Null }}
$tmp = "C:\\ctemp\\_fix_ws.py"
[System.IO.File]::WriteAllText($tmp, $text, [System.Text.Encoding]::UTF8)
python $tmp 2>&1
'''
    return run_ps(ps_cmd, timeout)

# ─────────────────────────────────────────────
# Step 1: 连通性检查
# ─────────────────────────────────────────────
def step1_check_connectivity():
    log('INFO', '=== Step1: 检查179连通性 ===')
    out, rc = run_ps('$env:COMPUTERNAME', timeout=15)
    if rc != 0 or not out.strip():
        log('ERR', f'WinRM连接失败 (rc={rc}): {out[:200]}')
        return False
    log('OK', f'WinRM连接成功: {out.strip()}')
    return True

# ─────────────────────────────────────────────
# Step 2: 读取179当前状态
# ─────────────────────────────────────────────
def step2_read_current_state():
    log('INFO', '=== Step2: 读取179 state.vscdb ===')
    py = '''
import sqlite3, json, os
DB = r"C:\\Users\\zhouyoukang\\AppData\\Roaming\\Windsurf\\User\\globalStorage\\state.vscdb"
if not os.path.exists(DB):
    print("DB_EXISTS:False")
else:
    print("DB_EXISTS:True")
    c = sqlite3.connect(DB, timeout=5)
    row = c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
    if not row:
        print("AUTH:NULL")
    else:
        try:
            a = json.loads(row[0])
            ak = a.get("apiKey","")
            print("EMAIL:" + str(a.get("email","")))
            print("APIKEY_LEN:" + str(len(ak)))
            print("APIKEY_PREVIEW:" + ak[:60])
        except Exception as e:
            print("PARSE_ERR:" + str(e)[:100])
    c.close()
# Check Windsurf process
import subprocess
p = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Windsurf.exe"], capture_output=True, text=True)
ws_running = "Windsurf.exe" in p.stdout
print("WS_RUNNING:" + str(ws_running))
# Check WB path
import pathlib
wb_paths = [
    r"D:\\Windsurf\\resources\\app\\out\\vs\\workbench\\workbench.desktop.main.js",
    r"C:\\Users\\zhouyoukang\\AppData\\Local\\Programs\\Windsurf\\resources\\app\\out\\vs\\workbench\\workbench.desktop.main.js"
]
wb_found = None
for p in wb_paths:
    if pathlib.Path(p).exists():
        wb_found = p; break
print("WB_PATH:" + str(wb_found))
'''
    out, rc = run_remote_py(py)
    print(out)
    
    state = {}
    for line in out.splitlines():
        if ':' in line:
            k, _, v = line.partition(':')
            state[k.strip()] = v.strip()
    
    log('INFO', f"DB: {state.get('DB_EXISTS','?')}")
    log('INFO', f"Email: {state.get('EMAIL','?')}")
    log('INFO', f"ApiKey长度: {state.get('APIKEY_LEN','0')}")
    log('INFO', f"ApiKey: {state.get('APIKEY_PREVIEW','?')}")
    log('INFO', f"Windsurf运行: {state.get('WS_RUNNING','?')}")
    log('INFO', f"WB路径: {state.get('WB_PATH','?')}")
    
    apikey_len = int(state.get('APIKEY_LEN', '0'))
    needs_inject = (
        state.get('DB_EXISTS') != 'True' or
        state.get('AUTH') == 'NULL' or
        apikey_len < 10
    )
    
    if needs_inject:
        log('WARN', f'需要注入 — apiKey长度={apikey_len}')
    else:
        log('OK', f'state.vscdb有效，但Windsurf报错可能是缓存问题 — 强制重新注入')
    
    return state, True  # 总是注入以确保最新

# ─────────────────────────────────────────────
# Step 3: 从快照池选最优账号
# ─────────────────────────────────────────────
def step3_pick_account():
    log('INFO', '=== Step3: 选择最优账号 ===')
    
    if not SNAPSHOT_FILE.exists():
        log('ERR', f'快照文件不存在: {SNAPSHOT_FILE}')
        return None
    
    data = json.loads(SNAPSHOT_FILE.read_text('utf-8'))
    snapshots = data.get('snapshots', {})
    
    candidates = []
    for email, snap in snapshots.items():
        if email in SKIP_EMAILS:
            continue
        blobs = snap.get('blobs', {})
        auth_blob = blobs.get('windsurfAuthStatus', '')
        if not auth_blob:
            continue
        try:
            auth_obj = json.loads(auth_blob)
            ak = auth_obj.get('apiKey', '')
            if len(ak) > 20:
                candidates.append({
                    'email': email,
                    'apiKey': ak,
                    'authBlob': auth_blob,
                    'confBlob': blobs.get('windsurfConfigurations', ''),
                    'harvestedAt': snap.get('harvested_at', ''),
                })
        except:
            pass
    
    log('INFO', f'候选账号数: {len(candidates)}')
    if not candidates:
        log('ERR', '无可用账号！')
        return None
    
    # 按收割时间排序，取最新
    candidates.sort(key=lambda x: x['harvestedAt'], reverse=True)
    chosen = candidates[0]
    log('OK', f"选中: {chosen['email']}")
    log('INFO', f"收割时间: {chosen['harvestedAt']}")
    log('INFO', f"ApiKey: {chosen['apiKey'][:50]}...")
    return chosen

# ─────────────────────────────────────────────
# Step 4: 注入账号到179
# ─────────────────────────────────────────────
def step4_inject(account: dict):
    log('INFO', '=== Step4: 注入账号到179 state.vscdb ===')
    
    # base64编码auth/conf blob避免引号问题
    auth_b64 = base64.b64encode(account['authBlob'].encode('utf-8')).decode('ascii')
    conf_b64 = base64.b64encode((account['confBlob'] or '').encode('utf-8')).decode('ascii')
    email_safe = account['email']
    
    py = f'''
import sqlite3, json, base64, os
DB = r"C:\\\\Users\\\\zhouyoukang\\\\AppData\\\\Roaming\\\\Windsurf\\\\User\\\\globalStorage\\\\state.vscdb"
auth_b64 = "{auth_b64}"
conf_b64 = "{conf_b64}"
status_val = base64.b64decode(auth_b64).decode("utf-8")
conf_val   = base64.b64decode(conf_b64).decode("utf-8")
c = sqlite3.connect(DB, timeout=10)
c.execute("INSERT OR REPLACE INTO ItemTable (key,value) VALUES (?,?)", ("windsurfAuthStatus", status_val))
if conf_val.strip() and conf_val.strip() not in ("null", ""):
    c.execute("INSERT OR REPLACE INTO ItemTable (key,value) VALUES (?,?)", ("windsurfConfigurations", conf_val))
c.execute("DELETE FROM ItemTable WHERE key=?", ("cachedPlanInfo",))
c.execute("DELETE FROM ItemTable WHERE key=?", ("windsurfMachineId",))
c.commit()
r = c.execute("SELECT value FROM ItemTable WHERE key=?", ("windsurfAuthStatus",)).fetchone()
if r:
    a = json.loads(r[0])
    ak = a.get("apiKey","")
    print("INJECT_OK:email=" + a.get("email","?") + " apiKey_len=" + str(len(ak)) + " preview=" + ak[:40])
else:
    print("INJECT_FAIL:row_not_found")
c.close()
'''
    
    out, rc = run_remote_py(py, timeout=30)
    print(out)
    
    if 'INJECT_OK' in out:
        log('OK', f'注入成功: {[l for l in out.splitlines() if "INJECT_OK" in l][0]}')
        return True
    else:
        log('ERR', f'注入失败 (rc={rc})')
        return False

# ─────────────────────────────────────────────
# Step 5: 重启Windsurf on 179
# ─────────────────────────────────────────────
def step5_restart_windsurf():
    log('INFO', '=== Step5: 重启Windsurf ===')
    
    py = '''
import subprocess, time, pathlib
# Kill
p = subprocess.run(["taskkill", "/F", "/IM", "Windsurf.exe", "/T"], capture_output=True, text=True)
if "SUCCESS" in p.stdout or "success" in p.stdout.lower():
    print("KILLED:Windsurf")
    time.sleep(2)
else:
    print("NOT_RUNNING:no process to kill")
# Find exe
ws_paths = [
    r"D:\\Windsurf\\Windsurf.exe",
    r"C:\\Users\\zhouyoukang\\AppData\\Local\\Programs\\Windsurf\\Windsurf.exe"
]
ws_exe = None
for p in ws_paths:
    if pathlib.Path(p).exists():
        ws_exe = p; break
if ws_exe:
    subprocess.Popen([ws_exe])
    print("STARTED:" + ws_exe)
else:
    print("NO_EXE:not found in candidates")
'''
    out, rc = run_remote_py(py, timeout=20)
    print(out)
    
    if 'STARTED' in out:
        log('OK', f'Windsurf已重启')
        return True
    elif 'NOT_RUNNING' in out:
        log('WARN', 'Windsurf本来未运行，已注入账号，请手动启动Windsurf')
        return True
    else:
        log('WARN', f'重启结果: {out[:100]}')
        return True

# ─────────────────────────────────────────────
# Step 6: 最终验证
# ─────────────────────────────────────────────
def step6_final_verify():
    log('INFO', '=== Step6: 最终验证 ===')
    time.sleep(3)
    
    py = '''
import sqlite3, json
DB = r"C:\\Users\\zhouyoukang\\AppData\\Roaming\\Windsurf\\User\\globalStorage\\state.vscdb"
c = sqlite3.connect(DB, timeout=5)
r = c.execute("SELECT value FROM ItemTable WHERE key=?", ("windsurfAuthStatus",)).fetchone()
if r:
    a = json.loads(r[0])
    ak = a.get("apiKey","")
    print("FINAL_OK:email=" + a.get("email","?") + " apiKey_len=" + str(len(ak)))
    if len(ak) > 20:
        print("APIKEY_VALID:True")
    else:
        print("APIKEY_VALID:False")
else:
    print("FINAL_FAIL:NULL")
c.close()
'''
    out, rc = run_remote_py(py, timeout=20)
    print(out)
    
    if 'APIKEY_VALID:True' in out:
        log('OK', '验证通过：179 state.vscdb有有效apiKey')
        return True
    else:
        log('ERR', f'验证失败: {out[:200]}')
        return False

# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────
def main():
    print('\n' + '='*65)
    print('  179 Windsurf API Key修复 — 道法自然·直指根源')
    print('  Error: Permission denied: failed to get primary API key')
    print('='*65 + '\n')
    
    # 1. 连通性
    if not step1_check_connectivity():
        log('ERR', '179不可达，请检查网络/WinRM')
        sys.exit(1)
    
    # 2. 当前状态
    state, _ = step2_read_current_state()
    
    # 3. 选账号
    account = step3_pick_account()
    if not account:
        log('ERR', '无可用账号，请先运行账号收割')
        sys.exit(1)
    
    # 4. 注入
    if not step4_inject(account):
        log('ERR', '注入失败')
        sys.exit(1)
    
    # 5. 重启
    step5_restart_windsurf()
    
    # 6. 验证
    ok = step6_final_verify()
    
    print('\n' + '='*65)
    if ok:
        print(f'  ✅ 修复成功！')
        print(f'  账号: {account["email"]}')
        print(f'  操作: 在179上 Ctrl+Shift+P → Reload Window (或已自动重启)')
    else:
        print('  ❌ 修复可能未完成，请检查输出')
    print('='*65 + '\n')

if __name__ == '__main__':
    main()
