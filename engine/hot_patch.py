#!/usr/bin/env python3
"""
Hot Patch v1.0 — 热补丁·手术级注入
=====================================
道法自然: 最小变更，单点控制，热生效

原理:
  MetadataProvider.getMetadata() 是所有gRPC请求的apiKey唯一来源(41处调用)
  在此单点注入文件读取拦截器:
    每次gRPC请求 → getMetadata() → 读 _pool_apikey.txt → 返回最优apiKey
  Pool Engine 持续写入最优apiKey到文件
  结果: 切号 = 更新文件 = 即时生效 (无需重启Windsurf)

Usage:
  python hot_patch.py apply    # 应用补丁 (需Windsurf重启一次)
  python hot_patch.py restore  # 恢复原版
  python hot_patch.py verify   # 检查补丁状态
  python hot_patch.py watch    # 监视extension.js更新并自动重补丁
  python hot_patch.py test     # 热测试(无需重启)
"""

import os, sys, shutil, json, time, hashlib, threading
from pathlib import Path
from datetime import datetime

VERSION = '1.0.0'
SCRIPT_DIR = Path(__file__).parent

# ── 路径配置 ──
EXT_JS = Path(r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js')
APPDATA = Path(os.environ.get('APPDATA', ''))
POOL_KEY_FILE = APPDATA / 'Windsurf' / '_pool_apikey.txt'
PATCH_MARKER = '/* POOL_HOT_PATCH_V1 */'
BACKUP_DIR = SCRIPT_DIR / '_ext_backups'

# ── 手术精确目标 (经实测唯一) ──
PATCH_OLD = 'apiKey:this.apiKey,sessionId:this.sessionId,requestId:BigInt(this.requestId)'

# ── 注入的JS: 读文件→取最优apiKey→降级到原始key ──
# 注意: require 在 Node.js Extension Host 中可用
# v2.0: 改用 process.env.APPDATA 动态路径，支持任意Windows用户独立切号
# 不再硬编码 ai/Administrator 路径 — 每个用户读自己的 _pool_apikey.txt
# 若文件空/不存在 → fallback to this.apiKey (state.vscdb真实auth) → 切号正常生效
PATCH_NEW = (
    'apiKey:(function(){'
    'try{'
    'var _fs=require("fs"),_path=require("path");'
    'var _pf=_path.join(process.env.APPDATA||"","Windsurf","_pool_apikey.txt");'
    'var _k=_fs.readFileSync(_pf,"utf8").trim();'
    'if(_k&&_k.length>20&&_k.startsWith("sk-ws"))return _k;'
    '}'
    'catch(_e){}'
    'return this.apiKey;'
    '}).call(this)' + PATCH_MARKER + ','
    'sessionId:this.sessionId,requestId:BigInt(this.requestId)'
)


def log(msg, prefix=''):
    ts = datetime.now().strftime('%H:%M:%S')
    try:
        print(f'  [{ts}] {prefix}{msg}')
    except UnicodeEncodeError:
        safe = (f'  [{ts}] {prefix}{msg}').encode('gbk', errors='replace').decode('gbk')
        print(safe)


def _hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _backup(ext_path: Path) -> Path:
    """备份extension.js，返回备份路径。"""
    BACKUP_DIR.mkdir(exist_ok=True)
    h = _hash(ext_path)[:8]
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = BACKUP_DIR / f'extension_{ts}_{h}.js.bak'
    shutil.copy2(ext_path, backup)
    # 只保留最近10份
    baks = sorted(BACKUP_DIR.glob('*.js.bak'))
    for old in baks[:-10]:
        old.unlink()
    return backup


def verify(ext_path: Path = EXT_JS) -> dict:
    """检查补丁状态。"""
    if not ext_path.exists():
        return {'ok': False, 'error': 'extension.js not found', 'patched': False}
    src = ext_path.read_text(encoding='utf-8', errors='replace')
    patched = PATCH_MARKER in src
    original_present = PATCH_OLD in src
    pool_key_ok = POOL_KEY_FILE.exists() and len(POOL_KEY_FILE.read_text(encoding='utf-8', errors='replace').strip()) > 20
    return {
        'ok': True,
        'patched': patched,
        'original_present': original_present,
        'pool_key_file_exists': POOL_KEY_FILE.exists(),
        'pool_key_valid': pool_key_ok,
        'pool_key_preview': POOL_KEY_FILE.read_text(encoding='utf-8', errors='replace').strip()[:30] + '...' if pool_key_ok else None,
        'ext_size': ext_path.stat().st_size,
        'ext_hash': _hash(ext_path)[:8],
        'backups': len(list(BACKUP_DIR.glob('*.js.bak'))) if BACKUP_DIR.exists() else 0,
    }


def apply(ext_path: Path = EXT_JS, force: bool = False) -> bool:
    """应用热补丁到 extension.js。"""
    log('Applying hot patch to extension.js...', '⚡ ')

    if not ext_path.exists():
        log(f'extension.js not found: {ext_path}', '✖ ')
        return False

    src = ext_path.read_text(encoding='utf-8', errors='replace')

    # 已经打过
    if PATCH_MARKER in src:
        log('Patch already applied!', '✅ ')
        v = verify(ext_path)
        log(f'pool_key_valid={v["pool_key_valid"]}  ext_hash={v["ext_hash"]}', '   ')
        return True

    # 目标不存在
    if PATCH_OLD not in src:
        log('Patch target not found in extension.js! (Windsurf updated?)', '✖ ')
        log(f'Expected: {PATCH_OLD[:60]}...', '   ')
        return False

    # 验证唯一性
    count = src.count(PATCH_OLD)
    if count != 1:
        log(f'DANGER: Patch target appears {count} times (expected 1). Aborting.', '✖ ')
        return False

    # 备份
    backup = _backup(ext_path)
    log(f'Backup → {backup.name}', '💾 ')

    # 应用
    new_src = src.replace(PATCH_OLD, PATCH_NEW, 1)
    ext_path.write_text(new_src, encoding='utf-8')

    # 验证写入
    v = verify(ext_path)
    if v['patched']:
        log(f'Patch APPLIED ✅  size={v["ext_size"]:,}  hash={v["ext_hash"]}', '✅ ')
        log(f'Key file: {POOL_KEY_FILE}', '📁 ')
        log(f'Key valid: {v["pool_key_valid"]}', '🔑 ')
        print()
        log('⚠️  Windsurf needs ONE restart to activate the patch.', '⚠️  ')
        log('   After restart: cutting accounts = updating the key file (zero restart)', '   ')
        log('   Pool engine auto-updates the key file every 3 seconds.', '   ')
        return True
    else:
        log('Patch write FAILED — restoring backup', '✖ ')
        shutil.copy2(backup, ext_path)
        return False


def restore(ext_path: Path = EXT_JS) -> bool:
    """从备份恢复 extension.js。"""
    log('Restoring extension.js from backup...', '🔄 ')

    if not BACKUP_DIR.exists():
        log('No backup directory found.', '✖ ')
        return False

    baks = sorted(BACKUP_DIR.glob('*.js.bak'))
    if not baks:
        log('No backups found.', '✖ ')
        return False

    # 用最新的未打补丁的备份
    target_bak = None
    for bak in reversed(baks):
        bak_src = bak.read_text(encoding='utf-8', errors='replace')
        if PATCH_MARKER not in bak_src and PATCH_OLD in bak_src:
            target_bak = bak
            break

    if not target_bak:
        # 用最新备份
        target_bak = baks[-1]
        log(f'Warning: Using latest backup (may be patched): {target_bak.name}', '⚠️  ')
    else:
        log(f'Clean backup found: {target_bak.name}', '✅ ')

    shutil.copy2(target_bak, ext_path)
    v = verify(ext_path)
    log(f'Restored: patched={v["patched"]}  hash={v["ext_hash"]}', '✅ ')
    log('⚠️  Windsurf needs ONE restart to deactivate the patch.', '⚠️  ')
    return True


def watch(ext_path: Path = EXT_JS, interval: int = 30):
    """监视 extension.js 变化 (Windsurf更新后自动重补丁)。"""
    log(f'Watching {ext_path.name} every {interval}s...', '👁  ')
    last_hash = _hash(ext_path) if ext_path.exists() else ''

    while True:
        time.sleep(interval)
        try:
            if not ext_path.exists():
                continue
            h = _hash(ext_path)
            if h != last_hash:
                log(f'extension.js changed ({last_hash[:6]} → {h[:6]}), re-patching...', '🔄 ')
                last_hash = h
                v = verify(ext_path)
                if not v['patched']:
                    apply(ext_path)
                    last_hash = _hash(ext_path)
                else:
                    log('Already patched, skip.', '✅ ')
        except Exception as e:
            log(f'Watch error: {e}', '✖ ')


def hot_test():
    """热测试：不重启Windsurf，验证全链路是否就绪。"""
    import urllib.request
    print('=' * 60)
    print('  HOT TEST — 热测试 (无需重启Windsurf)')
    print('=' * 60)

    results = {}

    # T1: extension.js patch status
    v = verify()
    results['patch_applied'] = v['patched']
    results['patch_target_ok'] = not v['patched'] and v['original_present']
    icon = '✅' if v['patched'] else ('⚠️ ' if v['original_present'] else '❌')
    print(f'  {icon} Patch: {"APPLIED" if v["patched"] else "NOT YET (restart needed after apply)"}  hash={v["ext_hash"]}')

    # T2: Pool key file
    pkey_ok = v['pool_key_valid']
    results['pool_key_ok'] = pkey_ok
    icon = '✅' if pkey_ok else '❌'
    print(f'  {icon} Key file: {"exists, valid" if pkey_ok else "missing or invalid"}  {v["pool_key_preview"] or "N/A"}')

    # T3: Pool engine API
    try:
        r = urllib.request.urlopen('http://127.0.0.1:19877/api/status', timeout=2)
        d = json.loads(r.read())
        pool = d['pool']
        results['engine_ok'] = True
        print(f'  ✅ Engine :19877: {pool["total"]} accts, {pool["available"]} avail, D{pool["total_daily"]}% W{pool["total_weekly"]}%')
    except Exception as e:
        results['engine_ok'] = False
        print(f'  ❌ Engine :19877: {e}')

    # T4: Proxy
    try:
        r = urllib.request.urlopen('http://127.0.0.1:19876/pool/health', timeout=2)
        d = json.loads(r.read())
        results['proxy_ok'] = d.get('ok', False)
        print(f'  ✅ Proxy  :19876: running (proxy={d.get("proxy","?")})')
    except Exception as e:
        results['proxy_ok'] = False
        print(f'  ⚠️  Proxy  :19876: not running ({e})')

    # T5: apiServerUrl status
    try:
        import sqlite3
        STATE_DB = APPDATA / 'Windsurf' / 'User' / 'globalStorage' / 'state.vscdb'
        conn = sqlite3.connect(f'file:{STATE_DB}?mode=ro', uri=True)
        secret_key = 'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.apiServerUrl"}'
        row = conn.execute("SELECT length(value) FROM ItemTable WHERE key=?", (secret_key,)).fetchone()
        conn.close()
        print(f'  📡 apiServerUrl secret: {row[0]}B in state.vscdb (active only after restart)')
    except Exception as e:
        print(f'  ⚠️  apiServerUrl check: {e}')

    # T6: Current active account
    try:
        r = urllib.request.urlopen('http://127.0.0.1:19877/api/status', timeout=2)
        d = json.loads(r.read())
        active = d.get('active', {})
        if active:
            print(f'  🔑 Active: #{active["index"]} {active["email"][:30]} D{active["daily"]}%·W{active["weekly"]}% score={active["score"]}')
    except Exception:
        pass

    # T7: Model routing test
    try:
        r = urllib.request.urlopen('http://127.0.0.1:19877/api/pick?model=claude-sonnet-4-6', timeout=2)
        d = json.loads(r.read())
        acct = d.get('account', {})
        print(f'  🎯 Best for claude-sonnet: #{acct.get("index")} {acct.get("email","?")[:25]}')
    except Exception:
        pass

    print()
    ready = v['patched'] and pkey_ok and results.get('engine_ok', False)
    if ready:
        print('  🟢 SYSTEM FULLY HOT — 系统全热就绪')
        print('     切号 = pool_engine自动更新key文件 = 即时生效')
    elif v['original_present'] and not v['patched']:
        print('  🟡 ONE RESTART NEEDED — 执行 apply 后重启Windsurf一次')
        print('     执行: python hot_patch.py apply')
        print('     然后: 重启Windsurf')
        print('     之后: 永久热切换，无需再重启')
    else:
        print('  🔴 NOT READY — 检查上方错误')
    print('=' * 60)
    return results


def write_pool_key_now():
    """立即从pool engine写入最优apiKey到文件。"""
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        from pool_engine import PoolEngine
        eng = PoolEngine()
        best = eng.pick_best()
        if best and best.api_key:
            POOL_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
            POOL_KEY_FILE.write_text(best.api_key, encoding='utf-8')
            log(f'Key file written: #{best.index} {best.email[:25]} {best.api_key[:20]}...', '✅ ')
            return True
        else:
            log('No account with apiKey found', '✖ ')
            return False
    except Exception as e:
        log(f'write_pool_key_now error: {e}', '✖ ')
        return False


def start_pool_key_daemon():
    """后台线程: 每3秒更新pool key文件。"""
    sys.path.insert(0, str(SCRIPT_DIR))
    from pool_engine import PoolEngine, HealthMonitor

    engine = PoolEngine()
    monitor = HealthMonitor(engine, interval=10)
    monitor.start()

    def _loop():
        while True:
            try:
                best = engine.pick_best()
                if best and best.api_key:
                    POOL_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
                    POOL_KEY_FILE.write_text(best.api_key, encoding='utf-8')
            except Exception:
                pass
            time.sleep(3)

    t = threading.Thread(target=_loop, daemon=True, name='PoolKeyWriter')
    t.start()
    log(f'Pool key daemon started → {POOL_KEY_FILE}', '✅ ')
    return engine


def cli_apply():
    apply()
    # Also write pool key file immediately
    write_pool_key_now()


def restore_api_server_url() -> bool:
    """仅恢复 apiServerUrl (从 proxy --setup 备份)。"""
    import sqlite3
    try:
        STATE_DB = APPDATA / 'Windsurf' / 'User' / 'globalStorage' / 'state.vscdb'
        conn = sqlite3.connect(str(STATE_DB), timeout=10)
        conn.execute('PRAGMA journal_mode=WAL')
        secret_key = 'secret://{"extensionId":"codeium.windsurf","key":"windsurf_auth.apiServerUrl"}'
        backup_key = secret_key + '__proxy_backup'
        backup = conn.execute("SELECT value FROM ItemTable WHERE key=?", (backup_key,)).fetchone()
        if backup:
            conn.execute("INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)", (secret_key, backup[0]))
            conn.execute("DELETE FROM ItemTable WHERE key=?", (backup_key,))
            conn.commit()
            log('apiServerUrl restored to original ✅ (restart Windsurf to take effect)', '📡 ')
            conn.close()
            return True
        else:
            log('No apiServerUrl backup found (not modified by proxy --setup)', '⚠️  ')
            conn.close()
            return False
    except Exception as e:
        log(f'apiServerUrl restore error: {e}', '✖ ')
        return False


def cli_full_restore():
    """完全恢复: 移除extension.js补丁 + 恢复apiServerUrl。"""
    ok1 = restore()         # revert extension.js patch
    ok2 = restore_api_server_url()  # restore apiServerUrl
    if ok1:
        log('Full restore complete. Restart Windsurf to deactivate.', '✅ ')


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'verify'

    print('=' * 60)
    print(f'  Hot Patch v{VERSION} — 热补丁·MetadataProvider注入器')
    print('=' * 60)

    if cmd == 'apply':
        cli_apply()
    elif cmd == 'restore':
        cli_full_restore()
    elif cmd == 'restore-ext':
        restore()
    elif cmd == 'restore-url':
        restore_api_server_url()
    elif cmd == 'verify':
        v = verify()
        print(json.dumps(v, indent=2, ensure_ascii=False))
    elif cmd == 'test':
        hot_test()
    elif cmd == 'watch':
        watch()
    elif cmd == 'write-key':
        write_pool_key_now()
    elif cmd == 'daemon':
        eng = start_pool_key_daemon()
        print(f'  Daemon running. Ctrl+C to stop.')
        try:
            while True:
                time.sleep(5)
                best = eng.pick_best()
                if best:
                    print(f'  🔑 Key → #{best.index} {best.email[:25]} D{best.daily}%·W{best.weekly}%')
        except KeyboardInterrupt:
            print('\n  Daemon stopped.')
    else:
        print(f'  apply        — 应用补丁 (需重启Windsurf一次)')
        print(f'  restore      — 完全恢复 (patch+apiServerUrl)')
        print(f'  restore-ext  — 仅恢复extension.js')
        print(f'  restore-url  — 仅恢复apiServerUrl')
        print(f'  verify       — 检查状态')
        print(f'  test         — 热测试 (无需重启)')
        print(f'  watch        — 监视更新自动重补丁')
        print(f'  daemon       — 启动key文件自动更新守护进程')
        print(f'  write-key    — 立即写入最优apiKey到文件')


if __name__ == '__main__':
    main()
