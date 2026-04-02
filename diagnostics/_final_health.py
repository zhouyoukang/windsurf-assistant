#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全系统最终健康检查"""
import subprocess, json, sqlite3, hashlib, base64, sys, os
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = Path(__file__).parent.parent
SNAPSHOT = BASE / '010-道引擎_DaoEngine' / '_wam_snapshots.json'

print("=" * 60)
print("  全系统最终健康检查")
print("=" * 60)

# === 1. Windsurf进程数 ===
r = subprocess.run(['powershell','-NoProfile','-Command',
    '(Get-Process Windsurf -EA SilentlyContinue).Count'],
    capture_output=True, text=True, timeout=10, encoding='utf-8', errors='replace')
ws_count = r.stdout.strip() or '0'
ok1 = int(ws_count) > 0
print(f"\n[1] Windsurf进程: {ws_count}  {'✅' if ok1 else '❌'}")

# === 2. Python守护进程 ===
r2 = subprocess.run(['powershell','-NoProfile','-Command',
    'Get-Process python,pythonw -EA SilentlyContinue | Measure-Object | Select-Object -Expand Count'],
    capture_output=True, text=True, timeout=10, encoding='utf-8', errors='replace')
py_count = r2.stdout.strip() or '0'
ok2 = int(py_count) > 0
print(f"[2] Python守护进程: {py_count}  {'✅' if ok2 else '⚠️'}")

# === 3. 本地workbench.js补丁状态 ===
wb = Path(r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js')
if wb.exists():
    data = wb.read_bytes()
    markers = {
        '__wamRateLimit': b'__wamRateLimit',
        'GBe_silent': b'errorParts:_rl?void 0',
        'opus-4-6': b'claude-opus-4-6',
    }
    ok3 = all(m in data for m in markers.values())
    # checksum
    digest = hashlib.sha256(data).digest()
    b64h = base64.b64encode(digest).decode().rstrip('=')
    prod = wb.parent.parent.parent.parent / 'product.json'
    pj = json.loads(prod.read_text(encoding='utf-8'))
    stored = pj.get('checksums', {}).get('vs/workbench/workbench.desktop.main.js', 'MISSING')
    ck_ok = (stored == b64h)
    print(f"[3] workbench补丁: {'✅ 全部' if ok3 else '❌ 缺失'}  checksum: {'✅' if ck_ok else '❌'}")
else:
    ok3, ck_ok = False, False
    print("[3] workbench: ❌ 未找到")

# === 4. ai用户auth ===
user = os.environ.get('USERNAME', 'ai')
db_ai = Path(f'C:/Users/{user}/AppData/Roaming/Windsurf/User/globalStorage/state.vscdb')
if db_ai.exists():
    c = sqlite3.connect(str(db_ai), timeout=3)
    row = c.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
    if row:
        a = json.loads(row[0])
        ak = a.get('apiKey', '')
        ok4 = len(ak) > 20
        wam_cnt = c.execute("SELECT count(*) FROM ItemTable WHERE key LIKE 'windsurf_auth-%'").fetchone()[0]
        print(f"[4] {user}用户auth: {'✅' if ok4 else '❌'} key={ak[:40]} WAM_accounts={wam_cnt}")
    else:
        ok4 = False
        print(f"[4] {user}用户auth: ❌ NULL")
    c.close()
else:
    ok4 = False
    print(f"[4] {user}用户auth: ❌ state.vscdb不存在")

# === 5. 账号快照池 ===
if SNAPSHOT.exists():
    with open(SNAPSHOT, 'r', encoding='utf-8') as f:
        snaps = json.load(f)
    total = len(snaps.get('snapshots', {}))
    valid = sum(1 for v in snaps.get('snapshots', {}).values()
                if v.get('blobs', {}).get('windsurfAuthStatus'))
    ok5 = valid > 0
    print(f"[5] 账号快照池: {valid}/{total} valid  {'✅' if ok5 else '❌'}")
else:
    ok5 = False
    print("[5] 账号快照池: ❌ 文件不存在")

# === 6. cloud pool DB ===
pool_db = BASE / '030-云端号池_CloudPool' / 'cloud_pool.db'
if pool_db.exists():
    size_mb = pool_db.stat().st_size / 1024 / 1024
    ok6 = size_mb > 1
    print(f"[6] cloud_pool.db: {size_mb:.1f}MB  {'✅' if ok6 else '⚠️'}")
else:
    ok6 = False
    print("[6] cloud_pool.db: ❌ 不存在")

# === 7. ARGs论文状态 ===
args_zip = Path('e:/道/道生一/一生二/ARGs论文/稿/ARGs论文_给导师_v12.0_20260329.zip')
args_docx = Path('e:/道/道生一/一生二/ARGs论文/稿/ARGs论文_给导师_v8.1_20260321/Manuscript_v12.0.docx')
ok7 = args_zip.exists() and args_docx.exists()
print(f"[7] ARGs论文v12.0: {'✅ zip+docx就绪' if ok7 else '❌ 文件缺失'}")

print("\n" + "=" * 60)
all_ok = all([ok1, ok3, ck_ok, ok4, ok5, ok6, ok7])
if all_ok:
    print("  ✅✅✅ 全系统健康 — 所有核心组件正常 ✅✅✅")
else:
    issues = []
    if not ok1: issues.append("Windsurf未运行")
    if not ok3: issues.append("workbench补丁缺失")
    if not ck_ok: issues.append("checksum不匹配")
    if not ok4: issues.append("ai用户auth无效")
    if not ok5: issues.append("账号池为空")
    if not ok6: issues.append("cloud pool DB缺失")
    if not ok7: issues.append("ARGs论文v12.0文件缺失")
    print(f"  ⚠️ 待处理: {', '.join(issues)}")
print("=" * 60)
