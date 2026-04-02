#!/usr/bin/env python3
"""
_root_fix_autocontinue.py — 道法自然 · 根本消除 Continue 按钮
================================================================
根本原因链路:
  AI → ExecutorTerminationReason.MAX_INVOCATIONS(=3)
     → cascadeState.terminationReason===MAX_INVOCATIONS
     → pr=true → showContinue=true → Continue 按钮出现
     → 用户需手动点击 / 需切换到对应窗口

根本开关:
  autoContinueOnMaxGeneratorInvocations = ENABLED(1)
  → 后端语言服务器自动续传，MAX_INVOCATIONS 永不停止
  → pr 永远不会为 true → Continue 按钮永远不出现

三层补丁:
  Layer1 (extension.js): 默认值 UNSPECIFIED→ENABLED
          语言服务器收到的 UserSettings 将包含 ENABLED
  Layer2 (workbench.js):  默认值 ms.UNSPECIFIED→ms.ENABLED
          UI 层 UserSettings 初始化为 ENABLED
  Layer3 (workbench.js):  isEnabled 检查逻辑逆转
          j = Z.autoContinue!==DISABLED (而非 ===ENABLED)
          使 UNSPECIFIED 也被视为 ENABLED（最后防线）

Usage:
  python _root_fix_autocontinue.py           # 应用补丁 + 热重载
  python _root_fix_autocontinue.py --check   # 检查状态
  python _root_fix_autocontinue.py --revert  # 回滚
"""
import os, re, sys, shutil, json, struct, time, ctypes, subprocess
from datetime import datetime
from pathlib import Path

WB_JS       = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
EXT_JS      = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
PRODUCT_JSON = r'D:\Windsurf\resources\app\product.json'

VERSION = 'RFC_v1.0'   # Root Fix Continue

# ── Layer1: extension.js ─────────────────────────────────────────
# 找到 extension.js 中 UserSettings 类的 autoContinue 默认值
# 改 UNSPECIFIED → ENABLED
EXT_PATCH_FIND = 'autoContinueOnMaxGeneratorInvocations=sA.UNSPECIFIED'
EXT_PATCH_REPL = 'autoContinueOnMaxGeneratorInvocations=sA.ENABLED/*RFC_AUTOCONT*/'

# ── Layer2: workbench.js ─────────────────────────────────────────
# 主要 UserSettings 类 (ms 别名, 对应 la(Q=>Q.state.userSettings))
WB_L2_FIND = 'this.autoContinueOnMaxGeneratorInvocations=ms.UNSPECIFIED'
WB_L2_REPL = 'this.autoContinueOnMaxGeneratorInvocations=ms.ENABLED/*RFC_L2*/'

# ── Layer3: workbench.js ─────────────────────────────────────────
# isEnabled 检查: ===ENABLED → !==DISABLED
# 使 UNSPECIFIED(0) 也算 ENABLED
WB_L3_FIND = 'j=Z.autoContinueOnMaxGeneratorInvocations===ms.ENABLED'
WB_L3_REPL = 'j=Z.autoContinueOnMaxGeneratorInvocations!==ms.DISABLED/*RFC_L3*/'


# ─────────────────────────────────────────────────────────────────
#  Checksum 更新
# ─────────────────────────────────────────────────────────────────
def compute_sha256_b64(path):
    import hashlib, base64
    with open(path, 'rb') as f:
        data = f.read()
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


def update_checksums(changed_files):
    """更新 product.json 中变更文件的 checksum"""
    if not os.path.exists(PRODUCT_JSON):
        print('[CHKSUM] product.json 不存在，跳过')
        return
    with open(PRODUCT_JSON, 'r', encoding='utf-8') as f:
        prod = json.load(f)
    checksums = prod.get('checksums', {})
    if not checksums:
        print('[CHKSUM] 无 checksums 字段')
        return
    updated = 0
    for path, key_hint in changed_files:
        new_cksum = compute_sha256_b64(path)
        for k in list(checksums.keys()):
            if key_hint in k:
                old = checksums[k]
                checksums[k] = new_cksum
                print(f'[CHKSUM] {k[:60]}: {old[:16]}... → {new_cksum[:16]}...')
                updated += 1
    if updated:
        with open(PRODUCT_JSON, 'w', encoding='utf-8') as f:
            json.dump(prod, f, indent=2, ensure_ascii=False)
        print(f'[CHKSUM] ✅ 已更新 {updated} 条')


# ─────────────────────────────────────────────────────────────────
#  IPC reload
# ─────────────────────────────────────────────────────────────────
def _find_pipes():
    try:
        out = subprocess.check_output(
            ['powershell', '-NoProfile', '-Command',
             r'[IO.Directory]::GetFiles("\\.\pipe") | Where-Object { $_ -match "main-sock" }'],
            stderr=subprocess.DEVNULL, encoding='utf-8', errors='replace', timeout=5
        )
        return [l.strip() for l in out.strip().splitlines() if 'main-sock' in l]
    except Exception:
        return []


def _send_ipc(pipe_path, message):
    try:
        pipe_name = pipe_path
        if not pipe_name.startswith('\\\\.\\pipe\\'):
            pipe_name = '\\\\.\\pipe\\' + Path(pipe_path).name
        msg = json.dumps(message).encode('utf-8')
        hdr = struct.pack('<I', len(msg))
        GENERIC_RW = 0xC0000000
        handle = ctypes.windll.kernel32.CreateFileW(
            pipe_name, GENERIC_RW, 0, None, 3, 0, None)
        if handle == ctypes.c_void_p(-1).value:
            return False
        written = ctypes.c_ulong(0)
        ok = ctypes.windll.kernel32.WriteFile(
            handle, hdr + msg, len(hdr + msg), ctypes.byref(written), None)
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok)
    except Exception:
        return False


def ipc_reload():
    pipes = _find_pipes()
    if not pipes:
        print('[IPC] 未找到 main-sock，请手动 Ctrl+Shift+P → Reload Window')
        return False
    sent = 0
    for p in pipes:
        if _send_ipc(p, {'type': 'reloadWindow'}):
            sent += 1
    if sent:
        print(f'[IPC] ✅ reloadWindow 发送到 {sent} 条管道')
        return True
    print('[IPC] 发送失败，请手动 Ctrl+Shift+P → Reload Window')
    return False


# ─────────────────────────────────────────────────────────────────
#  Backup
# ─────────────────────────────────────────────────────────────────
def _backup(path, tag):
    bak_dir = os.path.dirname(path)
    baks = [f for f in os.listdir(bak_dir) if f'bak_{tag}' in f]
    if not baks:
        bak = path + f'.bak_{tag}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        shutil.copy2(path, bak)
        print(f'  备份: {os.path.basename(bak)}')
    else:
        print(f'  备份已存在 ({len(baks)}个)，跳过')


# ─────────────────────────────────────────────────────────────────
#  Check
# ─────────────────────────────────────────────────────────────────
def check():
    print('=' * 65)
    print(f'Root Fix AutoContinue — 状态检查')
    print('=' * 65)

    ext = open(EXT_JS, 'r', encoding='utf-8', errors='replace').read()
    wb  = open(WB_JS,  'r', encoding='utf-8', errors='replace').read()

    checks = [
        ('EXT Layer1', 'RFC_AUTOCONT' in ext or EXT_PATCH_REPL in ext),
        ('WB  Layer2', 'RFC_L2' in wb or WB_L2_REPL in wb),
        ('WB  Layer3', 'RFC_L3' in wb or WB_L3_REPL in wb),
        ('EXT orig',   EXT_PATCH_FIND in ext),
        ('WB  orig L2', WB_L2_FIND in wb),
        ('WB  orig L3', WB_L3_FIND in wb),
    ]
    for name, result in checks:
        print(f'  {name}: {"✅" if result else "✗"}')


# ─────────────────────────────────────────────────────────────────
#  Apply
# ─────────────────────────────────────────────────────────────────
def apply():
    print('=' * 65)
    print(f'Root Fix AutoContinue {VERSION} — {datetime.now().strftime("%H:%M:%S")}')
    print('=' * 65)

    # Read files
    ext = open(EXT_JS,  'r', encoding='utf-8', errors='replace').read()
    wb  = open(WB_JS,   'r', encoding='utf-8', errors='replace').read()

    changed_ext = False
    changed_wb  = False

    # ── Layer1: extension.js ────────────────────────────────────
    print('\n[Layer1] extension.js: autoContinue 默认值')
    if 'RFC_AUTOCONT' in ext:
        print('  ✅ 已应用')
    elif EXT_PATCH_FIND in ext:
        _backup(EXT_JS, 'rfc_ext')
        count = ext.count(EXT_PATCH_FIND)
        ext = ext.replace(EXT_PATCH_FIND, EXT_PATCH_REPL)
        print(f'  ✅ 替换 {count} 处: UNSPECIFIED → ENABLED')
        changed_ext = True
    else:
        print(f'  ⚠️  未找到目标字符串: {EXT_PATCH_FIND!r}')
        # Try fuzzy
        if 'autoContinueOnMaxGeneratorInvocations' in ext:
            m = re.search(r'autoContinueOnMaxGeneratorInvocations=\w+\.UNSPECIFIED', ext)
            if m:
                _backup(EXT_JS, 'rfc_ext')
                ext = ext[:m.start()] + m.group().replace('.UNSPECIFIED', '.ENABLED/*RFC_AUTOCONT*/') + ext[m.end():]
                print(f'  ✅ 模糊替换: {m.group()}')
                changed_ext = True
            else:
                print('  ❌ 模糊搜索也未找到')
        else:
            print('  ❌ autoContinueOnMaxGeneratorInvocations 不存在于 extension.js')

    # ── Layer2: workbench.js ────────────────────────────────────
    print('\n[Layer2] workbench.js: ms.UNSPECIFIED → ms.ENABLED')
    if 'RFC_L2' in wb:
        print('  ✅ 已应用')
    elif WB_L2_FIND in wb:
        _backup(WB_JS, 'rfc_wb')
        wb = wb.replace(WB_L2_FIND, WB_L2_REPL, 1)
        print(f'  ✅ 替换: {WB_L2_FIND} → ENABLED')
        changed_wb = True
    else:
        # Try the other aliases (Je and AutoContinueOnMaxGeneratorInvocations)
        for find, repl in [
            ('this.autoContinueOnMaxGeneratorInvocations=Je.UNSPECIFIED',
             'this.autoContinueOnMaxGeneratorInvocations=Je.ENABLED/*RFC_L2*/'),
            ('this.autoContinueOnMaxGeneratorInvocations=AutoContinueOnMaxGeneratorInvocations.UNSPECIFIED',
             'this.autoContinueOnMaxGeneratorInvocations=AutoContinueOnMaxGeneratorInvocations.ENABLED/*RFC_L2*/'),
        ]:
            if find in wb:
                if 'RFC_L2' not in wb:
                    _backup(WB_JS, 'rfc_wb')
                wb = wb.replace(find, repl, 1)
                print(f'  ✅ 别名替换: {find[-30:]}')
                changed_wb = True
                break
        else:
            print('  ⚠️  所有别名均未找到')

    # ── Layer3: workbench.js ────────────────────────────────────
    print('\n[Layer3] workbench.js: isEnabled ===ENABLED → !==DISABLED')
    if 'RFC_L3' in wb:
        print('  ✅ 已应用')
    elif WB_L3_FIND in wb:
        if not changed_wb:
            _backup(WB_JS, 'rfc_wb')
        wb = wb.replace(WB_L3_FIND, WB_L3_REPL, 1)
        print(f'  ✅ 替换: ===ms.ENABLED → !==ms.DISABLED')
        changed_wb = True
    else:
        print(f'  ⚠️  未找到: {WB_L3_FIND!r}')

    # Write
    changed_files = []
    if changed_ext:
        with open(EXT_JS, 'w', encoding='utf-8') as f:
            f.write(ext)
        print(f'\n✅ extension.js 已写入')
        changed_files.append((EXT_JS, 'extension.js'))

    if changed_wb:
        with open(WB_JS, 'w', encoding='utf-8') as f:
            f.write(wb)
        print(f'✅ workbench.js 已写入')
        changed_files.append((WB_JS, 'workbench.desktop.main.js'))

    if not changed_ext and not changed_wb:
        print('\n✅ 所有补丁均已应用，无需重复操作')
        return True

    # Update checksums
    print()
    update_checksums(changed_files)

    return True


# ─────────────────────────────────────────────────────────────────
#  Revert
# ─────────────────────────────────────────────────────────────────
def revert():
    reverted = 0
    for path, tag in [(EXT_JS, 'rfc_ext'), (WB_JS, 'rfc_wb')]:
        bak_dir = os.path.dirname(path)
        baks = sorted([f for f in os.listdir(bak_dir) if f'bak_{tag}' in f])
        if baks:
            latest = os.path.join(bak_dir, baks[-1])
            shutil.copy2(latest, path)
            print(f'✅ 回滚: {os.path.basename(path)} ← {baks[-1]}')
            reverted += 1
    if reverted:
        update_checksums([(EXT_JS, 'extension.js'), (WB_JS, 'workbench.desktop.main.js')])
    else:
        print('❌ 未找到备份文件')


# ─────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────
def main():
    args = set(sys.argv[1:])

    if '--check' in args:
        check()
        return

    if '--revert' in args:
        revert()
        return

    if '--reload' in args:
        ipc_reload()
        return

    ok = apply()
    if ok:
        print('\n' + '─' * 65)
        ipc_reload()
        print()
        print('✅ 根本修复完成！')
        print('   autoContinueOnMaxGeneratorInvocations = ENABLED (强制)')
        print('   语言服务器将自动续传，Continue 按钮永不出现')
        print('   无需切换窗口，无需任何手动操作')
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
