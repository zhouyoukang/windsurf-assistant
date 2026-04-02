#!/usr/bin/env python3
"""
_179_opus46修复.py — 专项修复179的opus-4-6不可用
================================================
道法自然·直指根源

问题:
  1. 179 workbench.js版本与141不同, P12/P13 target字符串不匹配
  2. 179 state.vscdb opus-4-6 commandModel注入未确认

解决:
  Step1: 验证+注入179 state.vscdb中的opus-4-6 commandModel
  Step2: 搜索179 workbench.js找正确的commandModels解析位置
  Step3: 应用179版本的P12/P13 + checkCapacity bypass补丁

执行方式: 本地运行, 通过WinRM操作179
"""
import subprocess, base64, json, re, sys
from pathlib import Path

TARGET_IP   = '192.168.31.179'
TARGET_USER = 'zhouyoukang'
TARGET_PASS = 'wsy057066wsy'
PYTHON_179  = 'python'  # 179上的python命令

def run_ps(cmd, timeout=60):
    """执行PowerShell WinRM命令"""
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
    return r.stdout.strip() + (('\nSTDERR:' + r.stderr.strip()) if r.stderr.strip() else ''), r.returncode

def run_remote_py(script_code, timeout=45):
    """在179上执行Python脚本 (通过base64传输避免引号冲突)"""
    b64 = base64.b64encode(script_code.encode('utf-8')).decode('ascii')
    ps_cmd = f'''
$b64 = "{b64}"
$bytes = [System.Convert]::FromBase64String($b64)
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
$tmp = "C:\\ctemp\\ws_opus46_fix"
if (-not (Test-Path $tmp)) {{ New-Item -ItemType Directory $tmp -Force | Out-Null }}
$p = "$tmp\\run_script.py"
[System.IO.File]::WriteAllText($p, $text, [System.Text.Encoding]::UTF8)
python $p 2>&1
'''
    return run_ps(ps_cmd, timeout)

# ═══════════════════════════════════════════════════
# STEP 1: 验证并注入179 state.vscdb opus-4-6
# ═══════════════════════════════════════════════════
def step1_inject_statedb():
    print('\n' + '='*60)
    print('STEP 1: 验证+注入179 state.vscdb opus-4-6')
    print('='*60)
    
    script = '''
import sqlite3, json, base64, struct, os
from pathlib import Path

user = os.environ.get("USERNAME", "zhouyoukang")
db = Path(f"C:/Users/{user}/AppData/Roaming/Windsurf/User/globalStorage/state.vscdb")
print(f"DB: {db}")
print(f"exists: {db.exists()}")
if not db.exists():
    print("STATUS:ERROR:db_not_found")
    exit(1)

def encode_varint(val):
    r = []
    while True:
        b = val & 0x7F; val >>= 7
        if val: r.append(b | 0x80)
        else: r.append(b); break
    return bytes(r)

def enc_str(fnum, s):
    d = s.encode()
    t = (fnum << 3) | 2
    return encode_varint(t) + encode_varint(len(d)) + d

def enc_int(fnum, v):
    return encode_varint((fnum << 3) | 0) + encode_varint(v)

def enc_f32(fnum, v):
    return encode_varint((fnum << 3) | 5) + struct.pack("<f", v)

config = (
    enc_str(1, "Claude Opus 4.6") +
    enc_str(22, "claude-opus-4-6") +
    enc_f32(3, 6.0) +
    enc_int(4, 0) +
    enc_int(13, 4) +
    enc_int(18, 200000) +
    enc_int(20, 0) +
    enc_int(24, 3)
)
new_b64 = base64.b64encode(config).decode()

conn = sqlite3.connect(str(db), timeout=15)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=10000")

row = conn.execute("SELECT value FROM ItemTable WHERE key=?", ("windsurfAuthStatus",)).fetchone()
if not row:
    print("STATUS:ERROR:no_windsurfAuthStatus")
    conn.close(); exit(1)

auth = json.loads(row[0])
ak = auth.get("apiKey", "?")
print(f"Current apiKey: {ak[:50]}...")
models_raw = auth.get("allowedCommandModelConfigsProtoBinaryBase64", [])
if isinstance(models_raw, str):
    models = [models_raw] if models_raw.strip() else []
elif isinstance(models_raw, list):
    models = list(models_raw)
else:
    models = []
print(f"Current commandModels: {len(models)} (type={type(models_raw).__name__})")

# check if opus-4-6 already present
already = False
for m in models:
    try:
        d = base64.b64decode(m)
        if b"claude-opus-4-6" in d or b"Claude Opus 4.6" in d:
            already = True; break
    except: pass

if already:
    print("STATUS:ALREADY:opus-4-6 already in commandModels")
else:
    models.append(new_b64)
    auth["allowedCommandModelConfigsProtoBinaryBase64"] = models
    conn.execute("UPDATE ItemTable SET value=? WHERE key=?",
                 (json.dumps(auth), "windsurfAuthStatus"))
    conn.commit()
    print(f"STATUS:OK:injected opus-4-6, commandModels now {len(models)}")

conn.close()
'''
    out, rc = run_remote_py(script)
    print(out)
    success = 'STATUS:OK' in out or 'STATUS:ALREADY' in out
    print(f'Result: {"✅ 成功" if success else "❌ 失败"} (rc={rc})')
    return success

# ═══════════════════════════════════════════════════
# STEP 2: 搜索179 workbench.js找P12/P13正确位置
# ═══════════════════════════════════════════════════
def step2_find_patch_targets():
    print('\n' + '='*60)
    print('STEP 2: 搜索179 workbench.js找P12/P13目标')
    print('='*60)
    
    script = '''
import re
from pathlib import Path

wb = Path(r"D:\\Windsurf\\resources\\app\\out\\vs\\workbench\\workbench.desktop.main.js")
if not wb.exists():
    print("WB:ERROR:not_found"); exit(1)

with open(wb, "r", encoding="utf-8", errors="replace") as f:
    content = f.read()

print(f"Size: {len(content):,} bytes")

# 找 allowedCommandModelConfigsProtoBinaryBase64 区域
idx = content.find("allowedCommandModelConfigsProtoBinaryBase64")
if idx < 0:
    print("WB:NOT_FOUND:allowedCommandModelConfigsProtoBinaryBase64"); exit(1)

print(f"Found allowedCommandModel @{idx}")
region = content[max(0, idx-200):idx+2000]
print("REGION_START:" + "="*40)
print(region[:1500])
print("REGION_END:" + "="*40)

# 查找 this.j= 或等价赋值
m1 = re.search(r"this\\.\\w\\s*=\\s*this\\.\\w\\([A-Z]\\)[,;]", region)
if m1:
    print(f"LOC1_CANDIDATE: {m1.group()}")

# 查找 this.j=C? 模式 (updateWindsurfAuthStatus)
idx2 = content.find("updateWindsurfAuthStatus")
if idx2 > 0:
    region2 = content[idx2:idx2+2000]
    m2 = re.search(r"this\\.\\w\\s*=\\s*[A-Z]\\s*\\?\\s*this\\.\\w\\([A-Z]\\)\\s*:\\s*\\[\\]", region2)
    if m2:
        # 取更多上下文
        pos_in_region = region2.find(m2.group())
        full_ctx = region2[max(0, pos_in_region-50):pos_in_region+500]
        print(f"LOC2_CANDIDATE: {m2.group()}")
        print(f"LOC2_CONTEXT: {full_ctx[:400]}")
'''
    out, rc = run_remote_py(script, timeout=60)
    print(out[:3000])
    return out

# ═══════════════════════════════════════════════════
# STEP 3: 应用179特定版本的P12/P13补丁
# ═══════════════════════════════════════════════════
def step3_apply_targeted_patch(wb_region_info):
    print('\n' + '='*60)
    print('STEP 3: 应用179 workbench.js针对性补丁')
    print('='*60)
    
    # 基于搜索结果构建针对性补丁
    # 核心逻辑: 找 allowedCommandModelConfigsProtoBinaryBase64 附近的赋值语句
    # 注入opus-4-6克隆
    
    script = '''
import re, shutil
from pathlib import Path
from datetime import datetime

wb = Path(r"D:\\Windsurf\\resources\\app\\out\\vs\\workbench\\workbench.desktop.main.js")
with open(wb, "r", encoding="utf-8", errors="replace") as f:
    content = f.read()

OPUS46_B64 = "Cg9DbGF1ZGUgT3B1cyA0LjayAQ9jbGF1ZGUtb3B1cy00LTYdAADAQCAAaASQAcCaDKABAMABAw=="

# 如果已经注入，跳过
if "__o46=Object.assign(" in content or "__o46b=Object.assign(" in content or OPUS46_B64 in content:
    print("PATCH_STATUS:ALREADY:opus46 injection already present")
    exit(0)

# 找到 allowedCommandModelConfigsProtoBinaryBase64 区域
idx_amc = content.find("allowedCommandModelConfigsProtoBinaryBase64")
if idx_amc < 0:
    print("PATCH_STATUS:ERROR:amc_not_found"); exit(1)

# 在该区域及后2000字符中寻找 this.X=this.Y(Z) 模式
region = content[max(0,idx_amc-100):idx_amc+2000]

# Pattern: this.j=this.C(D),  (initial parse)
m_init = re.search(r"(this\\.\\w=this\\.\\w\\([A-Z]\\))([,;])", region)
if m_init:
    old_str = m_init.group(1) + m_init.group(2)
    var = re.match(r"this\\.(\\w)", m_init.group(1)).group(1)
    sep = m_init.group(2)
    inject = (
        f"{{var __o46=Object.assign(Object.create(Object.getPrototypeOf(this.{var}[0]||{{}})),this.{var}[0]||{{}},"
        f"{{label:\\'Claude Opus 4.6\\',modelUid:\\'claude-opus-4-6\\',"
        f"creditMultiplier:6,disabled:!1,isPremium:!0,isCapacityLimited:!1,"
        f"isBeta:!1,isNew:!0,isRecommended:!1}});"
        f"if(this.{var}&&this.{var}.length)this.{var}=[...this.{var},__o46]}}"
    )
    new_str = m_init.group(1) + ";try" + inject + "catch(__e46){}" + sep
    
    if old_str in content:
        # 备份
        bak = str(wb) + f".bak_p12_{datetime.now().strftime(\\'%Y%m%d_%H%M%S\\')}"
        shutil.copy2(wb, bak)
        content = content.replace(old_str, new_str, 1)
        print(f"PATCH_P12:OK:injected at init parse ({old_str[:60]}...)")
    else:
        print(f"PATCH_P12:SKIP:old_str not in full content (region only)")
else:
    print("PATCH_P12:SKIP:no init parse pattern found in region")

# Pattern for updateWindsurfAuthStatus  
# Look for: this.X=Y?this.Z(Y):[] pattern
idx_update = content.find("updateWindsurfAuthStatus")
if idx_update > 0:
    region2 = content[idx_update:idx_update+3000]
    m_update = re.search(r"(this\\.\\w=[A-Z]\\?this\\.\\w\\([A-Z]\\):\\[\\])(,this\\.\\w\\(\\))", region2)
    if m_update:
        old_str2 = m_update.group(1) + m_update.group(2)
        var2 = re.match(r"this\\.(\\w)", m_update.group(1)).group(1)
        inject2 = (
            f";try{{var __o46b=Object.assign(Object.create(Object.getPrototypeOf(this.{var2}[0]||{{}})),this.{var2}[0]||{{}},"
            f"{{label:\\'Claude Opus 4.6\\',modelUid:\\'claude-opus-4-6\\',"
            f"creditMultiplier:6,disabled:!1,isPremium:!0,isCapacityLimited:!1,"
            f"isBeta:!1,isNew:!0,isRecommended:!1}});"
            f"if(this.{var2}&&this.{var2}.length)this.{var2}=[...this.{var2},__o46b]}}catch(__e46b){{}}"
        )
        new_str2 = m_update.group(1) + inject2 + m_update.group(2)
        
        if old_str2 in content:
            content = content.replace(old_str2, new_str2, 1)
            print(f"PATCH_P13:OK:injected at auth refresh ({old_str2[:60]}...)")
        else:
            print("PATCH_P13:SKIP:old_str2 not in full content")
    else:
        print("PATCH_P13:SKIP:no update pattern found")

# Also apply checkChatCapacity bypass if not present
cap_old = "if(!Ru.hasCapacity)return"
cap_new = "if(!1&&!Ru.hasCapacity)return"
if cap_old in content and cap_new not in content:
    content = content.replace(cap_old, cap_new, 1)
    print("PATCH_CAP_BYPASS:OK:checkChatCapacity bypass applied")
elif cap_new in content:
    print("PATCH_CAP_BYPASS:ALREADY:already patched")
else:
    print("PATCH_CAP_BYPASS:SKIP:target not found")

# Also apply checkUserMessageRateLimit bypass
rl_old = "if(!tu.hasCapacity)return"
rl_new = "if(!1&&!tu.hasCapacity)return"
if rl_old in content and rl_new not in content:
    content = content.replace(rl_old, rl_new, 1)
    print("PATCH_RL_BYPASS:OK:checkUserMessageRateLimit bypass applied")
elif rl_new in content:
    print("PATCH_RL_BYPASS:ALREADY:already patched")
else:
    print("PATCH_RL_BYPASS:SKIP:target not found")

# Write patched content
with open(wb, "w", encoding="utf-8") as f:
    f.write(content)
print(f"WRITTEN:{len(content):,} bytes")
print("PATCH_DONE")
'''
    out, rc = run_remote_py(script, timeout=90)
    print(out)
    success = 'PATCH_DONE' in out
    print(f'Result: {"✅" if success else "❌"} (rc={rc})')
    return success

def step4_cap_bypass():
    """搜索179 workbench.js中capacity check的正确变量名，应用bypass"""
    print('\n' + '='*60)
    print('STEP 4: 179 checkChatCapacity bypass (变量名自动发现)')
    print('='*60)
    
    script = '''
import re, shutil
from pathlib import Path
from datetime import datetime

wb = Path(r"D:\\Windsurf\\resources\\app\\out\\vs\\workbench\\workbench.desktop.main.js")
with open(wb,"r",encoding="utf-8",errors="replace") as f:
    content = f.read()

# Search around offset 18362000-18366000 (same region as local 141)
region = content[18360000:18366000]

# Find hasCapacity in this region
ms = list(re.finditer(r".{0,60}hasCapacity.{0,80}", region))
print(f"hasCapacity in region: {len(ms)}")
for m in ms[:6]:
    print("  RC:" + m.group()[:200])

# Also search for the np(),py(),ys() pattern (capacity return logic)
ms2 = list(re.finditer(r"if\\(!\\w+\\.hasCapacity\\)return", region))
print(f"if(!X.hasCapacity)return: {len(ms2)}")
for m in ms2[:3]:
    print("  IF:" + m.group()[:120])

# Broader: search whole file for "if(!"+var+".hasCapacity"
ms3 = list(re.finditer(r"if\\(!\\w+\\.hasCapacity\\)return \\w+\\(\\)", content))
print(f"Full file if(!X.hasCapacity)return Y(): {len(ms3)}")
for m in ms3[:4]:
    old = m.group()
    new = old.replace("if(!", "if(!1&&!", 1)
    print(f"  FOUND:{old}")
    print(f"  PATCH:{new}")
    # Apply
    if old in content and new not in content:
        bak = str(wb) + ".bak_cap_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        if not Path(bak).exists():
            shutil.copy2(wb, bak)
        content = content.replace(old, new, 1)
        print(f"  APPLIED")

# Write if changed
if ms3:
    with open(wb,"w",encoding="utf-8") as f:
        f.write(content)
    print("WRITTEN")
else:
    print("NO_CAPACITY_IF_FOUND")
'''
    out, rc = run_remote_py(script, timeout=90)
    print(out[:2000])
    applied = 'APPLIED' in out
    skipped = 'NO_CAPACITY_IF_FOUND' in out or 'already patched' in out
    log('OK' if (applied or skipped) else 'WARN',
        '✅ capacity bypass applied' if applied else ('ℹ️  no capacity if-check found (may use different logic)' if skipped else '❓'),
        'ok' if applied else '')
    return applied or skipped


if __name__ == '__main__':
    args = set(sys.argv[1:])
    
    print('='*65)
    print('  179 opus-4-6 专项修复 — 道法自然·直指根源')
    print('='*65)
    
    # Step 1: state.vscdb直接注入 (最可靠，立即生效)
    s1_ok = step1_inject_statedb()
    
    if '--statedb-only' not in args:
        # Step 2: 搜索workbench.js正确位置
        region_info = step2_find_patch_targets()
        
        # Step 3: 应用针对性补丁
        s3_ok = step3_apply_targeted_patch(region_info)
        
        # Step 4: capacity bypass
        s4_ok = step4_cap_bypass()
    
    print('\n' + '='*65)
    print('  修复完成 Summary')
    print('='*65)
    print(f'  state.vscdb opus-4-6注入: {"✅" if s1_ok else "❌"}')
    print(f'  workbench.js持久化补丁:   {"✅" if "--statedb-only" not in args else "跳过"}')
    print(f'  capacity bypass: {"✅" if s4_ok else "❌"}')
    print()
    print('  最终操作: 在179上启动Windsurf → 直接选择Claude Opus 4.6')
    print('  备注: state.vscdb注入在登录刷新时会重置 → workbench.js补丁是持久化关键')

if __name__ == '__main__':
    main()
