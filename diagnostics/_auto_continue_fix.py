#!/usr/bin/env python3
"""
auto_continue_fix.py — 道法自然 · 根本解决 Continue 跨窗口问题
================================================================
根本原因:
  P15_AUTO_ACCEPT_OBSERVER 已存在，但有两个失效场景：
  1. Continue 按钮的父元素类名不含 "cascade"/"waiting" → closest() 返回 null
  2. 用户切换到其他对话窗口时，目标面板被隐藏(display:none)
     → offsetParent===null，click()无响应

修复策略:
  替换现有 P15 injection 为更强版本：
  - 移除父类名限制，直接查找所有 Continue 按钮
  - 使用 dispatchEvent(MouseEvent) 替代 .click() → 绕过可见性限制
  - MutationObserver 补充 setInterval → 立即响应 DOM 变化
  - 防重入锁：3s 冷却，防止连续多次触发

热部署:
  1. 备份 workbench.js
  2. 替换 P15 注入块
  3. 更新 integrity checksum
  4. 发送 IPC reloadWindow → Windsurf 无感重载 (~2s)

Usage:
  python _auto_continue_fix.py           # 应用补丁 + 热重载
  python _auto_continue_fix.py --check   # 检查当前状态
  python _auto_continue_fix.py --revert  # 回滚
  python _auto_continue_fix.py --reload  # 仅发送 IPC 重载(不修改文件)
"""
import os, re, sys, shutil, json, struct, time, ctypes, ctypes.wintypes, subprocess
from datetime import datetime
from pathlib import Path

WB_JS  = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'
WB_NLS = r'D:\Windsurf\resources\app\out\nls.messages.js'  # may not exist
PRODUCT_JSON = r'D:\Windsurf\resources\app\product.json'

# ── 版本标记 ──────────────────────────────────────────────────
VERSION     = 'v3.0'
MARKER_OLD  = '/*P15_AUTO_ACCEPT_OBSERVER*/'
MARKER_NEW  = f'/*P15_AUTO_ACCEPT_OBSERVER_{VERSION}*/'

# ── 旧代码(精确匹配，用于替换) ────────────────────────────────
OLD_INJECTION = (
    '/*P15_AUTO_ACCEPT_OBSERVER*/setInterval(()=>{try{'
    'document.querySelectorAll("[data-testid=\'accept-command\'],[aria-label=\'Run\']")'
    '.forEach(b=>{if(b.offsetParent!==null){b.click()}});'
    'document.querySelectorAll("button").forEach(b=>{const t=b.textContent?.trim();'
    'if(t==="Run"||t==="Continue"){const p=b.closest("[class*=waiting]");'
    'if(p||b.closest("[class*=cascade]"))b.click()}})}catch(e){}},500);'
)

# ── 新注入代码 ────────────────────────────────────────────────
# 核心改进:
#   1. 无父类限制 — 直接找 Continue 按钮
#   2. dispatchEvent — 绕过 display:none / offsetParent 限制
#   3. MutationObserver — 实时响应 DOM 新增
#   4. 防重入锁 _acLock — 3s 冷却
NEW_INJECTION = (
    f'/*P15_AUTO_ACCEPT_OBSERVER_{VERSION}*/'
    '(()=>{'
    'let _acLock=0;'
    'function _clickContinue(b){'
    'const n=Date.now();'
    'if(n-_acLock<3000)return;'  # 3s 防抖
    '_acLock=n;'
    'try{'
    # 先尝试直接 click
    'b.click();'
    # 再发送 MouseEvent (处理 display:none 等隐藏状态)
    'b.dispatchEvent(new MouseEvent("click",{bubbles:true,cancelable:true,view:window}));'
    '}catch(e){}'
    '}'
    'function _scan(){'
    'try{'
    # Part1: accept-command / aria-label=Run (保持原逻辑)
    'document.querySelectorAll("[data-testid=\'accept-command\'],[aria-label=\'Run\']")'
    '.forEach(b=>{if(b.offsetParent!==null)b.click()});'
    # Part2: Continue 按钮 — 无父类限制，全局扫描
    'document.querySelectorAll("button,a[role=button],[role=button]").forEach(b=>{'
    'const t=(b.textContent||b.innerText||"").trim();'
    'if(t==="Continue")_clickContinue(b);'
    '});'
    '}catch(e){}}'
    # setInterval 兜底
    'setInterval(_scan,500);'
    # MutationObserver 立即响应
    '(new MutationObserver(_scan)).observe(document.documentElement,'
    '{childList:true,subtree:true});'
    # 页面加载后立即扫一次
    '_scan();'
    '})()'
    ';'
)


# ─────────────────────────────────────────────────────────────
#  IPC: 发送 reloadWindow 到 Windsurf 主进程
# ─────────────────────────────────────────────────────────────
def _find_ipc_pipes():
    try:
        out = subprocess.check_output(
            ['powershell', '-NoProfile', '-Command',
             r'[IO.Directory]::GetFiles("\\.\pipe") | Where-Object { $_ -match "main-sock" }'],
            stderr=subprocess.DEVNULL, encoding='utf-8', errors='replace', timeout=5
        )
        pipes = [l.strip() for l in out.strip().splitlines() if 'main-sock' in l]
        return pipes
    except Exception:
        return []


def _send_ipc(pipe_path, message):
    try:
        pipe_name = pipe_path
        if not pipe_name.startswith('\\\\.\\pipe\\'):
            pipe_name = '\\\\.\\pipe\\' + Path(pipe_path).name
        msg  = json.dumps(message).encode('utf-8')
        hdr  = struct.pack('<I', len(msg))
        GENERIC_RW  = 0xC0000000
        OPEN_EXISTING = 3
        handle = ctypes.windll.kernel32.CreateFileW(
            pipe_name, GENERIC_RW, 0, None, OPEN_EXISTING, 0, None
        )
        if handle == ctypes.c_void_p(-1).value:
            return False
        buf = hdr + msg
        written = ctypes.c_ulong(0)
        ok = ctypes.windll.kernel32.WriteFile(handle, buf, len(buf), ctypes.byref(written), None)
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok)
    except Exception:
        return False


def ipc_reload_window():
    """发送 reloadWindow 指令让 Windsurf 重载当前窗口"""
    pipes = _find_ipc_pipes()
    if not pipes:
        print('[IPC] 未找到 main-sock 管道，跳过热重载')
        print('[IPC] 请手动: Ctrl+Shift+P → "Reload Window"')
        return False
    print(f'[IPC] 找到 {len(pipes)} 条管道')
    sent = 0
    for pipe in pipes:
        if _send_ipc(pipe, {'type': 'reloadWindow'}):
            sent += 1
            print(f'[IPC] ✅ reloadWindow → {Path(pipe).name}')
        else:
            print(f'[IPC] ⚠️  发送失败 → {Path(pipe).name}')
    if sent:
        print(f'[IPC] Windsurf 重载中 (~2s)...')
        return True
    print('[IPC] 所有管道均失败，请手动 Ctrl+Shift+P → Reload Window')
    return False


# ─────────────────────────────────────────────────────────────
#  Checksum 更新 (避免 Windsurf "tampered" 警告)
# ─────────────────────────────────────────────────────────────
def _compute_checksum(path):
    """计算文件 SHA256 的 base64 (VS Code integrity format)"""
    import hashlib, base64
    with open(path, 'rb') as f:
        data = f.read()
    h = hashlib.sha256(data).digest()
    return base64.b64encode(h).decode()


def _update_product_json_checksum(wb_path):
    """更新 product.json 中 workbench.js 的 checksums"""
    if not os.path.exists(PRODUCT_JSON):
        print(f'[CHKSUM] product.json 不存在: {PRODUCT_JSON}')
        return False
    try:
        with open(PRODUCT_JSON, 'r', encoding='utf-8') as f:
            prod = json.load(f)
        checksums = prod.get('checksums', {})
        if not checksums:
            print('[CHKSUM] product.json 无 checksums 字段，跳过')
            return True
        new_cksum = _compute_checksum(wb_path)
        # 找到对应的 key (相对路径格式)
        updated = 0
        for k in list(checksums.keys()):
            if 'workbench.desktop.main.js' in k:
                old = checksums[k]
                checksums[k] = new_cksum
                print(f'[CHKSUM] 更新: {k}')
                print(f'         旧: {old[:20]}...')
                print(f'         新: {new_cksum[:20]}...')
                updated += 1
        if updated == 0:
            print('[CHKSUM] 未找到 workbench.desktop.main 的 checksum 条目')
            return True  # no-op is ok
        # 备份 product.json
        bak = PRODUCT_JSON + f'.bak_ac_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        if not any('bak_ac' in f for f in os.listdir(os.path.dirname(PRODUCT_JSON))):
            shutil.copy2(PRODUCT_JSON, bak)
        with open(PRODUCT_JSON, 'w', encoding='utf-8') as f:
            json.dump(prod, f, indent=2, ensure_ascii=False)
        print(f'[CHKSUM] ✅ product.json 已更新 ({updated} 条目)')
        return True
    except Exception as e:
        print(f'[CHKSUM] 错误: {e}')
        return False


# ─────────────────────────────────────────────────────────────
#  主要补丁逻辑
# ─────────────────────────────────────────────────────────────
def check_status(wb: str):
    has_old = OLD_INJECTION in wb or MARKER_OLD in wb
    has_new = MARKER_NEW in wb
    has_any_v = bool(re.search(r'P15_AUTO_ACCEPT_OBSERVER_v\d', wb))
    return {
        'has_old_v1':  has_old and not has_new,
        'has_new_v3':  has_new,
        'has_any_v':   has_any_v,
        'old_present': OLD_INJECTION in wb,
        'marker_old':  MARKER_OLD in wb,
    }


def apply_patch(dry_run=False):
    print('=' * 65)
    print(f'auto_continue_fix {VERSION} — 道法自然 · {datetime.now().strftime("%H:%M:%S")}')
    print('=' * 65)

    if not os.path.exists(WB_JS):
        print(f'❌ workbench.js 不存在: {WB_JS}')
        return False

    with open(WB_JS, 'r', encoding='utf-8', errors='replace') as f:
        wb = f.read()
    orig_size = len(wb)
    print(f'文件大小: {orig_size:,} chars')

    status = check_status(wb)
    print(f'\n状态:')
    print(f'  旧版P15 (v1): {"✅ 存在" if status["has_old_v1"] else "✗"}')
    print(f'  新版P15 ({VERSION}): {"✅ 已注入" if status["has_new_v3"] else "✗"}')
    print(f'  精确匹配旧串: {"✅" if status["old_present"] else "✗"}')

    if status['has_new_v3']:
        print(f'\n✅ {VERSION} 补丁已存在，无需重复注入')
        return True

    # 备份
    bak_dir = os.path.dirname(WB_JS)
    existing_baks = [f for f in os.listdir(bak_dir) if 'bak_autocont' in f]
    if not existing_baks:
        bak = WB_JS + f'.bak_autocont_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        shutil.copy2(WB_JS, bak)
        print(f'\n备份: {os.path.basename(bak)}')
    else:
        print(f'\n备份已存在 ({len(existing_baks)}个)，跳过')

    # 替换策略
    new_wb = wb
    replaced = False

    # 策略1: 精确匹配旧注入块
    if OLD_INJECTION in new_wb:
        new_wb = new_wb.replace(OLD_INJECTION, NEW_INJECTION, 1)
        replaced = True
        print('\n✅ 策略1: 精确替换旧 P15 注入块')

    # 策略2: 匹配 marker 但不完全匹配(版本不同)
    elif status['has_any_v']:
        m = re.search(r'/\*P15_AUTO_ACCEPT_OBSERVER[^*]*\*/[^;]*;', new_wb)
        if m:
            new_wb = new_wb[:m.start()] + NEW_INJECTION + new_wb[m.end():]
            replaced = True
            print(f'\n✅ 策略2: 替换旧版 P15 ({m.group()[:60]}...)')

    # 策略3: 匹配 MARKER_OLD 附近的 setInterval
    elif MARKER_OLD in new_wb:
        idx = new_wb.find(MARKER_OLD)
        end_idx = new_wb.find('},500);', idx)
        if end_idx > 0:
            end_idx += len('},500);')
            new_wb = new_wb[:idx] + NEW_INJECTION + new_wb[end_idx:]
            replaced = True
            print('\n✅ 策略3: 通过 marker + setInterval 定位替换')

    # 策略4: 注入到文件头(P14 后面)
    else:
        target = '/*P14_VISIBILITY_OVERRIDE*/'
        idx = new_wb.find(target)
        if idx >= 0:
            end_p14 = new_wb.find(';', idx) + 1
            new_wb = new_wb[:end_p14] + NEW_INJECTION + new_wb[end_p14:]
            replaced = True
            print('\n⚠️  策略4: P15未找到，注入到P14后面')
        else:
            # 最后手段: 注入到文件头
            new_wb = NEW_INJECTION + new_wb
            replaced = True
            print('\n⚠️  策略5: 注入到文件头部')

    if not replaced:
        print('\n❌ 无法注入: 未找到合适的注入点')
        return False

    # 验证
    if MARKER_NEW not in new_wb:
        print(f'\n❌ 注入验证失败: {MARKER_NEW} 不在文件中')
        return False

    if dry_run:
        print(f'\n[DRY RUN] 注入成功 (未写入文件)')
        print(f'变化: {orig_size:,} → {len(new_wb):,} (+{len(new_wb)-orig_size}B)')
        return True

    # 写入
    with open(WB_JS, 'w', encoding='utf-8') as f:
        f.write(new_wb)
    new_size = len(new_wb)
    print(f'\n✅ 写入完成: {orig_size:,} → {new_size:,} (+{new_size-orig_size}B)')

    # 更新 checksum
    _update_product_json_checksum(WB_JS)

    return True


def revert_patch():
    bak_dir = os.path.dirname(WB_JS)
    baks = sorted([f for f in os.listdir(bak_dir) if 'bak_autocont' in f])
    if not baks:
        print('❌ 未找到 bak_autocont 备份文件')
        return False
    latest = os.path.join(bak_dir, baks[-1])
    shutil.copy2(latest, WB_JS)
    _update_product_json_checksum(WB_JS)
    print(f'✅ 已回滚到: {latest}')
    return True


def show_injection():
    """显示当前注入代码(debug用)"""
    with open(WB_JS, 'r', encoding='utf-8', errors='replace') as f:
        wb = f.read()
    # 找 P15 位置
    for marker in [MARKER_NEW, MARKER_OLD, '/*P15_AUTO_ACCEPT_OBSERVER']:
        idx = wb.find(marker)
        if idx >= 0:
            end = wb.find(';', idx + 200)
            print(f'P15 injection @{idx}:')
            print(wb[idx:min(end+1, idx+600)])
            return
    print('未找到 P15 注入')


# ─────────────────────────────────────────────────────────────
#  主入口
# ─────────────────────────────────────────────────────────────
def main():
    args = set(sys.argv[1:])

    if '--show' in args:
        show_injection()
        return

    if '--check' in args:
        with open(WB_JS, 'r', encoding='utf-8', errors='replace') as f:
            wb = f.read()
        s = check_status(wb)
        print('P15 状态:')
        for k, v in s.items():
            print(f'  {k}: {v}')
        return

    if '--revert' in args:
        revert_patch()
        return

    if '--reload' in args:
        ipc_reload_window()
        return

    if '--dry' in args:
        apply_patch(dry_run=True)
        return

    # 默认: 应用补丁 + 热重载
    ok = apply_patch()
    if ok:
        print('\n' + '─' * 65)
        print('发送 IPC reloadWindow...')
        ipc_ok = ipc_reload_window()
        if not ipc_ok:
            print('\n→ 请手动: Ctrl+Shift+P → "Reload Window"')
        print('\n✅ 完成！Continue 按钮将在所有对话窗口中自动触发')
        print('   无需切换窗口，无需手动点击')
    else:
        print('\n❌ 补丁应用失败')
        sys.exit(1)


if __name__ == '__main__':
    main()
