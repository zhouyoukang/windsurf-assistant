#!/usr/bin/env python3
"""
Sync Local Pool → Cloud — 道生一·统一管理
==========================================
读取本地号池(windsurf-login-accounts.json) + 认证快照(_wam_snapshots.json)
合并后推送至云端号池服务器(cloud_pool_server.py /api/admin/bulk-sync)

Usage:
  python sync_local_to_cloud.py                          # 同步到本地服务器 127.0.0.1:19880
  python sync_local_to_cloud.py --cloud https://aiotvr.xyz/pool  # 同步到阿里云
  python sync_local_to_cloud.py --status                 # 查看本地/云端状态对比
  python sync_local_to_cloud.py --dry-run                # 预览不实际推送

道法自然:
  本地96号 → 云端统一 → 公网用户无感换号 → 损之又损·以至于无为
"""

import os, sys, json, time, argparse, socket
from pathlib import Path
from datetime import datetime, timezone

SCRIPT_DIR = Path(__file__).parent
DAO_ENGINE_DIR = SCRIPT_DIR.parent / '010-道引擎_DaoEngine'

# Data sources
WS_APPDATA = Path(os.environ.get('APPDATA', '')) / 'Windsurf'
WS_GLOBALSTORE = WS_APPDATA / 'User' / 'globalStorage'

LOGIN_HELPER_PATHS = [
    WS_GLOBALSTORE / 'zhouyoukang.windsurf-assistant' / 'windsurf-login-accounts.json',
    WS_GLOBALSTORE / 'undefined_publisher.windsurf-login-helper' / 'windsurf-login-accounts.json',
    WS_GLOBALSTORE / 'windsurf-login-accounts.json',
]

SNAPSHOT_FILE = DAO_ENGINE_DIR / '_wam_snapshots.json'

# Cloud server
DEFAULT_SERVER = 'http://127.0.0.1:19880'
ADMIN_KEY = os.environ.get('CLOUD_POOL_ADMIN_KEY', '')

# Load secrets.env if available
SECRETS_FILE = SCRIPT_DIR.parent / 'secrets.env'
if SECRETS_FILE.exists():
    for line in SECRETS_FILE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            k, v = k.strip(), v.strip()
            if k and v and k not in os.environ:
                os.environ[k] = v
    ADMIN_KEY = ADMIN_KEY or os.environ.get('CLOUD_POOL_ADMIN_KEY', '')


def get_device_id():
    """Generate stable device identifier."""
    hostname = socket.gethostname()
    return f'{hostname}-{sys.platform}'


def load_login_accounts():
    """Load accounts from Login Helper extension JSON."""
    for p in LOGIN_HELPER_PATHS:
        if p.exists():
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    accounts = json.load(f)
                print(f'  ✓ Login Helper: {p.name} ({len(accounts)} accounts)')
                return accounts, p
            except Exception as e:
                print(f'  ✗ Error loading {p}: {e}')
    print('  ✗ No Login Helper accounts file found')
    return [], None


def load_snapshots():
    """Load auth snapshots from _wam_snapshots.json."""
    if not SNAPSHOT_FILE.exists():
        print(f'  ✗ Snapshot file not found: {SNAPSHOT_FILE}')
        return {}
    try:
        with open(SNAPSHOT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        snapshots = data.get('snapshots', {})
        print(f'  ✓ Auth snapshots: {len(snapshots)} accounts')
        return snapshots
    except Exception as e:
        print(f'  ✗ Error loading snapshots: {e}')
        return {}


def get_health(acc):
    """Extract health data from Login Helper account format."""
    u = acc.get('usage', {})
    d = u.get('daily', {})
    w = u.get('weekly', {})
    dr = d.get('remaining', 100) if d else 100
    wr = w.get('remaining', 100) if w else 100
    plan = u.get('plan', 'Trial')
    plan_end = u.get('planEnd', 0)
    now_ms = time.time() * 1000
    days_left = max(0, (plan_end - now_ms) / 86400000) if plan_end else 0
    return {
        'daily': dr, 'weekly': wr,
        'plan': plan, 'days_left': round(days_left, 1),
    }


def merge_accounts(login_accounts, snapshots):
    """Merge Login Helper accounts with auth snapshots into cloud-ready format."""
    merged = []
    for acc in login_accounts:
        email = acc.get('email', '')
        if not email:
            continue
        health = get_health(acc)
        entry = {
            'email': email,
            'plan': health['plan'],
            'daily': health['daily'],
            'weekly': health['weekly'],
            'days_left': health['days_left'],
            'password': acc.get('password', ''),
        }
        # Attach auth blob if snapshot exists
        snap = snapshots.get(email)
        if snap:
            blobs = snap.get('blobs', {})
            if blobs:
                entry['auth_blob'] = blobs
                entry['api_key_preview'] = snap.get('api_key_preview', '')
                entry['harvested_at'] = snap.get('harvested_at', '')
                # Extract apiKey from auth status
                try:
                    auth = json.loads(blobs.get('windsurfAuthStatus', '{}'))
                    entry['api_key'] = auth.get('apiKey', '')
                except (json.JSONDecodeError, TypeError):
                    pass
        merged.append(entry)

    # Also add snapshots that aren't in login_accounts (orphan snapshots)
    login_emails = {a.get('email', '') for a in login_accounts}
    for email, snap in snapshots.items():
        if email not in login_emails:
            blobs = snap.get('blobs', {})
            entry = {
                'email': email,
                'plan': 'Trial',
                'daily': 100, 'weekly': 100, 'days_left': 12,
                'auth_blob': blobs,
                'api_key_preview': snap.get('api_key_preview', ''),
                'harvested_at': snap.get('harvested_at', ''),
            }
            try:
                auth = json.loads(blobs.get('windsurfAuthStatus', '{}'))
                entry['api_key'] = auth.get('apiKey', '')
            except (json.JSONDecodeError, TypeError):
                pass
            merged.append(entry)

    return merged


def push_to_cloud(server_url, admin_key, accounts, device_id, dry_run=False):
    """Push merged accounts to cloud server via /api/admin/bulk-sync."""
    import urllib.request, urllib.error

    if dry_run:
        print(f'\n  [DRY RUN] Would push {len(accounts)} accounts to {server_url}')
        with_blob = sum(1 for a in accounts if a.get('auth_blob'))
        with_key = sum(1 for a in accounts if a.get('api_key'))
        print(f'    With auth blob: {with_blob}')
        print(f'    With apiKey:    {with_key}')
        return True

    payload = {
        'accounts': accounts,
        'source': 'local_sync',
        'device_id': device_id,
    }
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')

    url = f'{server_url.rstrip("/")}/api/admin/bulk-sync'
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'Content-Type': 'application/json',
            'X-Admin-Key': admin_key,
        },
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            if result.get('ok'):
                print(f'\n  ✓ Sync success!')
                print(f'    Synced:      {result.get("synced", 0)}')
                print(f'    Skipped:     {result.get("skipped", 0)}')
                print(f'    Pool total:  {result.get("pool_total", 0)}')
                print(f'    With blob:   {result.get("with_auth_blob", 0)}')
                return True
            else:
                print(f'\n  ✗ Sync failed: {result.get("error", "unknown")}')
                return False
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        print(f'\n  ✗ HTTP {e.code}: {body[:200]}')
        return False
    except urllib.error.URLError as e:
        print(f'\n  ✗ Connection error: {e.reason}')
        print(f'    Is cloud_pool_server.py running on {server_url}?')
        return False


def check_status(server_url, admin_key):
    """Compare local vs cloud pool status."""
    import urllib.request, urllib.error

    print('\n=== Local Pool ===')
    login_accounts, _ = load_login_accounts()
    snapshots = load_snapshots()
    if login_accounts:
        td = tw = 0
        for a in login_accounts:
            h = get_health(a)
            td += h['daily']
            tw += h['weekly']
        print(f'  Total: {len(login_accounts)}')
        print(f'  With snapshot: {sum(1 for a in login_accounts if a.get("email","") in snapshots)}')
        print(f'  Pool D: {td}% | W: {tw}%')

    print(f'\n=== Cloud Pool ({server_url}) ===')
    try:
        req = urllib.request.Request(
            f'{server_url.rstrip("/")}/api/admin/overview',
            headers={'X-Admin-Key': admin_key},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get('ok'):
                p = data.get('pool', {})
                print(f'  Total: {p.get("total", 0)} | Available: {p.get("available", 0)}')
                print(f'  Pool D: {p.get("total_d", 0)}% | W: {p.get("total_w", 0)}%')
                print(f'  Last sync: {data.get("last_synced", "never")}')
                print(f'  Version: {data.get("version", "?")}')
            else:
                print(f'  Error: {data.get("error", "unknown")}')
    except Exception as e:
        print(f'  ✗ Cannot reach cloud: {e}')

    # Also check blob count
    try:
        req = urllib.request.Request(
            f'{server_url.rstrip("/")}/api/public/pool',
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get('ok'):
                p = data.get('pool', {})
                with_blob = p.get('with_blob', '?')
                print(f'  With auth blob: {with_blob}')
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description='Sync Local Pool → Cloud')
    parser.add_argument('--cloud', default=DEFAULT_SERVER,
                       help=f'Cloud server URL (default: {DEFAULT_SERVER})')
    parser.add_argument('--admin-key', default=ADMIN_KEY,
                       help='Admin key (or set CLOUD_POOL_ADMIN_KEY env)')
    parser.add_argument('--status', action='store_true',
                       help='Show local/cloud status comparison')
    parser.add_argument('--dry-run', action='store_true',
                       help='Preview without pushing')
    args = parser.parse_args()

    admin_key = args.admin_key
    if not admin_key:
        print('⚠ No admin key. Set CLOUD_POOL_ADMIN_KEY in secrets.env or use --admin-key')
        # Try to auto-detect from running server (localhost only)
        if '127.0.0.1' in args.cloud or 'localhost' in args.cloud:
            admin_key = 'admin_test'  # Will fail if server has real key
            print(f'  Using fallback key for localhost: {admin_key}')

    if args.status:
        check_status(args.cloud, admin_key)
        return

    print(f'=== Sync Local Pool → Cloud ===')
    print(f'  Target: {args.cloud}')
    print(f'  Device: {get_device_id()}')
    print()

    # Step 1: Load local data
    print('Step 1: Load local pool data')
    login_accounts, login_path = load_login_accounts()
    snapshots = load_snapshots()

    if not login_accounts and not snapshots:
        print('\n✗ No local data found. Nothing to sync.')
        return

    # Step 2: Merge
    print('\nStep 2: Merge accounts + snapshots')
    merged = merge_accounts(login_accounts, snapshots)
    with_blob = sum(1 for a in merged if a.get('auth_blob'))
    with_key = sum(1 for a in merged if a.get('api_key'))
    print(f'  Merged: {len(merged)} accounts')
    print(f'  With auth blob: {with_blob} (hot-switch ready)')
    print(f'  With apiKey: {with_key}')

    # Step 3: Push
    print(f'\nStep 3: Push to cloud ({args.cloud})')
    ok = push_to_cloud(args.cloud, admin_key, merged, get_device_id(), args.dry_run)

    if ok:
        print(f'\n道生一·统一管理 — {"DRY RUN" if args.dry_run else "同步完成"} ✓')
    else:
        print(f'\n同步失败 — 请检查服务器状态和admin key')


if __name__ == '__main__':
    main()
