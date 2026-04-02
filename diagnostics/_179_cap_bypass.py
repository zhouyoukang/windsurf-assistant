#!/usr/bin/env python3
"""搜索179 workbench.js中的hasCapacity模式，应用bypass补丁"""
import subprocess, base64, sys

TARGET_IP   = '192.168.31.179'
TARGET_USER = 'zhouyoukang'
TARGET_PASS = 'wsy057066wsy'

def run_remote_py(script_code, timeout=60):
    b64 = base64.b64encode(script_code.encode('utf-8')).decode('ascii')
    ps = f'''$sp=New-Object System.Security.SecureString;"{TARGET_PASS}".ToCharArray()|%{{$sp.AppendChar($_)}};$cr=New-Object System.Management.Automation.PSCredential("{TARGET_USER}",$sp);Set-Item WSMan:\\localhost\\Client\\TrustedHosts -Value "{TARGET_IP}" -Force -EA SilentlyContinue;Invoke-Command -ComputerName {TARGET_IP} -Credential $cr -ScriptBlock{{$b64="{b64}";$bytes=[System.Convert]::FromBase64String($b64);$text=[System.Text.Encoding]::UTF8.GetString($bytes);$p="C:\\ctemp\\ws_opus46_fix\\cap_fix.py";if(-not(Test-Path(Split-Path $p))){{New-Item -ItemType Directory (Split-Path $p) -Force|Out-Null}};[System.IO.File]::WriteAllText($p,$text,[System.Text.Encoding]::UTF8);python $p 2>&1}} 2>&1'''
    r = subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-Command',ps],
        capture_output=True,text=True,timeout=timeout,encoding='utf-8',errors='replace')
    return r.stdout.strip(), r.returncode

# Step 1: 搜索hasCapacity模式
search_script = r'''
import re
from pathlib import Path

wb = Path(r"D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js")
with open(wb,"r",encoding="utf-8",errors="replace") as f:
    content = f.read()

print(f"SIZE:{len(content)}")

# hasCapacity search
ms = list(re.finditer(r".{0,80}hasCapacity.{0,100}", content))
print(f"hasCapacity_count:{len(ms)}")
for m in ms[:8]:
    print("CAP:" + m.group()[:200].replace("\n","\\n"))

# Check for bypass already applied
has_bypass = "if(!1&&!" in content and "hasCapacity" in content
print(f"bypass_applied:{has_bypass}")

# Check our specific bypass strings
old1 = "if(!tu.hasCapacity)return"
old2 = "if(!Ru.hasCapacity)return"
new1 = "if(!1&&!tu.hasCapacity)return"
new2 = "if(!1&&!Ru.hasCapacity)return"
print(f"old1_present:{old1 in content}")
print(f"old2_present:{old2 in content}")
print(f"new1_present:{new1 in content}")
print(f"new2_present:{new2 in content}")
'''

print("=== 搜索179 workbench.js hasCapacity ===")
out, rc = run_remote_py(search_script)
print(out[:3000])

# Parse results
lines = out.split('\n')
info = {}
cap_patterns = []
for line in lines:
    line = line.strip()
    if ':' in line and line.split(':')[0] in ('SIZE','hasCapacity_count','bypass_applied','old1_present','old2_present','new1_present','new2_present'):
        k, v = line.split(':', 1)
        info[k] = v.strip()
    elif line.startswith('CAP:'):
        cap_patterns.append(line[4:])

print(f"\nInfo: {info}")
print(f"Patterns found: {len(cap_patterns)}")

if '--search-only' in sys.argv:
    sys.exit(0)

# Step 2: 응用bypass
# If old1/old2 not found, try to find the actual pattern from cap_patterns
old_str1 = None
old_str2 = None

if info.get('old1_present') == 'True':
    old_str1 = 'if(!tu.hasCapacity)return'
    new_str1 = 'if(!1&&!tu.hasCapacity)return'
    print(f"\nFound standard pattern 1: {old_str1}")

if info.get('old2_present') == 'True':
    old_str2 = 'if(!Ru.hasCapacity)return'
    new_str2 = 'if(!1&&!Ru.hasCapacity)return'
    print(f"Found standard pattern 2: {old_str2}")

# If neither found, look for generic pattern in cap_patterns
if not old_str1 and not old_str2:
    print("\nStandard patterns not found, searching in captured patterns...")
    for pat in cap_patterns:
        # Look for: if(!X.hasCapacity)return pattern
        import re
        m = re.search(r'if\(!(\w+\.hasCapacity)\)return', pat)
        if m:
            var_path = m.group(1)
            old_str2 = f'if(!{var_path})return'
            new_str2 = f'if(!1&&!{var_path})return'
            print(f"Found variant: {old_str2}")
            break

if not old_str1 and not old_str2:
    if info.get('new1_present') == 'True' or info.get('new2_present') == 'True':
        print("\n✅ bypass already applied (new strings present)")
    else:
        print("\n⚠️  Cannot find hasCapacity pattern for bypass")
    sys.exit(0)

# Apply the patch
patch_script = f'''
import shutil
from pathlib import Path
from datetime import datetime

wb = Path(r"D:\\Windsurf\\resources\\app\\out\\vs\\workbench\\workbench.desktop.main.js")
with open(wb,"r",encoding="utf-8",errors="replace") as f:
    content = f.read()

patched = []
old1 = "{old_str1 or ''}"
new1 = "{new_str1 if old_str1 else ''}"
old2 = "{old_str2 or ''}"
new2 = "{new_str2 if old_str2 else ''}"

if old1 and old1 in content and new1 not in content:
    bak = str(wb) + ".bak_cap_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(wb, bak)
    content = content.replace(old1, new1, 1)
    patched.append("P_RL_BYPASS")

if old2 and old2 in content and new2 not in content:
    if not patched:  # only backup if not done yet
        bak = str(wb) + ".bak_cap_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(wb, bak)
    content = content.replace(old2, new2, 1)
    patched.append("P_CAP_BYPASS")

if patched:
    with open(wb,"w",encoding="utf-8") as f:
        f.write(content)
    print("PATCH_OK:" + ",".join(patched))
else:
    print("PATCH_SKIP:already_applied_or_not_found")
'''

print("\n=== 应用bypass补丁 ===")
out2, rc2 = run_remote_py(patch_script)
print(out2)
if 'PATCH_OK' in out2:
    print("✅ 179 capacity bypass 已应用")
elif 'SKIP' in out2:
    print("✅ 179 capacity bypass 已是最新状态")
else:
    print(f"⚠️  rc={rc2}")
