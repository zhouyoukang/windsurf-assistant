#!/usr/bin/env python3
"""
Batch Harvest — 批量采集96账号auth快照
======================================
直接调Firebase Login + RegisterUser API获取所有账号的apiKey，
构建WAM快照，解决2/96快照瓶颈。

认证链 (逆向自 authService.js v5.8.0):
  1. Firebase signInWithPassword(email, password) → idToken
  2. RegisterUser(idToken) → apiKey (sk-ws-01-...)
  3. 构建windsurfAuthStatus JSON → WAM snapshot

Usage:
  python batch_harvest.py              # 批量采集所有未采集账号
  python batch_harvest.py --all        # 强制重新采集所有账号
  python batch_harvest.py --test 3     # 仅测试前3个账号
  python batch_harvest.py --status     # 查看采集状态
"""

import os, sys, json, time, struct, ssl, socket
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR = Path(__file__).parent
WS_APPDATA = Path(os.environ.get('APPDATA', '')) / 'Windsurf'
WS_GLOBALSTORE = WS_APPDATA / 'User' / 'globalStorage'

ACCOUNTS_PATHS = [
    WS_GLOBALSTORE / 'zhouyoukang.windsurf-assistant' / 'windsurf-login-accounts.json',
    WS_GLOBALSTORE / 'windsurf-login-accounts.json',
]
SNAPSHOT_FILE = SCRIPT_DIR / '_wam_snapshots.json'

FIREBASE_KEYS = [
    'AIzaSyDsOl-1XpT5err0Tcnx8FFod1H8gVGIycY',
    'AIzaSyDKm6GGxMJfCbNf-k0kPytiGLaqFJpeSac',
]
RELAY_URL = 'https://168666okfa.xyz'
REGISTER_URLS = [
    'https://register.windsurf.com/exa.seat_management_pb.SeatManagementService/RegisterUser',
    'https://server.codeium.com/exa.seat_management_pb.SeatManagementService/RegisterUser',
]

PROXY_HOST = '127.0.0.1'
PROXY_PORTS = [7890, 7897, 7891, 10808, 1080]
_active_proxy = None
_active_mode = None  # 'proxy' or 'relay'


# ============================================================
# Network Helpers
# ============================================================
def _detect_proxy():
    global _active_proxy
    if _active_proxy is not None:
        return _active_proxy
    for port in PROXY_PORTS:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect((PROXY_HOST, port))
            s.close()
            _active_proxy = port
            return port
        except:
            continue
    _active_proxy = 0
    return 0


def _https_json(url, data, use_proxy=True, timeout=15):
    """POST JSON, return parsed response."""
    body = json.dumps(data).encode('utf-8')
    req = Request(url, data=body, method='POST')
    req.add_header('Content-Type', 'application/json')

    proxy_port = _detect_proxy() if use_proxy else 0
    if proxy_port > 0 and use_proxy:
        import urllib.request
        proxy_handler = urllib.request.ProxyHandler({
            'https': f'http://{PROXY_HOST}:{proxy_port}',
            'http': f'http://{PROXY_HOST}:{proxy_port}',
        })
        opener = urllib.request.build_opener(proxy_handler)
        resp = opener.open(req, timeout=timeout)
    else:
        resp = urlopen(req, timeout=timeout)

    return json.loads(resp.read())


def _https_binary(url, data, use_proxy=True, timeout=15):
    """POST binary, return raw bytes."""
    req = Request(url, data=data, method='POST')
    req.add_header('Content-Type', 'application/proto')
    req.add_header('Accept', 'application/proto')

    proxy_port = _detect_proxy() if use_proxy else 0
    if proxy_port > 0 and use_proxy:
        import urllib.request
        proxy_handler = urllib.request.ProxyHandler({
            'https': f'http://{PROXY_HOST}:{proxy_port}',
            'http': f'http://{PROXY_HOST}:{proxy_port}',
        })
        opener = urllib.request.build_opener(proxy_handler)
        resp = opener.open(req, timeout=timeout)
    else:
        resp = urlopen(req, timeout=timeout)

    return resp.read()


# ============================================================
# Protobuf Helpers (minimal — field 1 string only)
# ============================================================
def proto_encode_string(value, field_number=1):
    """Encode a string as protobuf field (wire type 2 = length-delimited)."""
    data = value.encode('utf-8')
    tag = (field_number << 3) | 2
    length = len(data)
    varint = []
    while length > 127:
        varint.append((length & 0x7f) | 0x80)
        length >>= 7
    varint.append(length)
    return bytes([tag] + varint) + data


def proto_parse_string(buf):
    """Parse first string field from protobuf bytes."""
    if len(buf) < 3 or buf[0] != 0x0a:
        return None
    pos = 1
    length = 0
    shift = 0
    while pos < len(buf):
        b = buf[pos]
        pos += 1
        length |= (b & 0x7f) << shift
        shift += 7
        if not (b & 0x80):
            break
    if pos + length > len(buf):
        return None
    return buf[pos:pos + length].decode('utf-8')


# ============================================================
# Auth Chain
# ============================================================
def firebase_login(email, password):
    """Firebase signInWithPassword → idToken."""
    payload = {
        'email': email,
        'password': password,
        'returnSecureToken': True,
    }

    # Try relay first (works in China)
    try:
        result = _https_json(f'{RELAY_URL}/firebase/login', payload, use_proxy=False, timeout=10)
        if result.get('idToken'):
            return result['idToken'], 'relay'
    except:
        pass

    # Try Firebase direct with proxy
    for key in FIREBASE_KEYS:
        try:
            url = f'https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={key}'
            result = _https_json(url, payload, use_proxy=True, timeout=10)
            if result.get('idToken'):
                return result['idToken'], f'firebase-{key[-4:]}'
        except:
            continue

    return None, 'failed'


def register_user(id_token):
    """RegisterUser(idToken) → apiKey."""
    req_data = proto_encode_string(id_token)

    # Try relay first
    try:
        resp = _https_binary(f'{RELAY_URL}/windsurf/register', req_data, use_proxy=False, timeout=15)
        api_key = proto_parse_string(resp)
        if api_key:
            return api_key, 'relay'
    except:
        pass

    # Try direct endpoints with proxy
    for url in REGISTER_URLS:
        try:
            resp = _https_binary(url, req_data, use_proxy=True, timeout=15)
            api_key = proto_parse_string(resp)
            if api_key:
                return api_key, url.split('/')[2]
        except:
            continue

    return None, 'failed'


def harvest_one(email, password):
    """Full auth chain for one account. Returns (apiKey, channel_info) or (None, error)."""
    id_token, login_ch = firebase_login(email, password)
    if not id_token:
        return None, f'login failed ({login_ch})'

    api_key, reg_ch = register_user(id_token)
    if not api_key:
        return None, f'register failed ({reg_ch})'

    return api_key, f'login={login_ch} reg={reg_ch}'


# ============================================================
# Snapshot Builder
# ============================================================
def load_accounts():
    for p in ACCOUNTS_PATHS:
        if p.exists():
            with open(p, 'r', encoding='utf-8') as f:
                return json.load(f)
    return []


def load_snapshots():
    if SNAPSHOT_FILE.exists():
        with open(SNAPSHOT_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'version': '4.0', 'snapshots': {}}


def save_snapshots(data):
    with open(SNAPSHOT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_template_configs():
    """Get windsurfConfigurations from existing snapshot as template."""
    data = load_snapshots()
    for snap in data.get('snapshots', {}).values():
        conf = snap.get('blobs', {}).get('windsurfConfigurations')
        if conf:
            return conf
    return None


def build_auth_blob(api_key):
    """Build windsurfAuthStatus JSON string (minimal — Windsurf refreshes on reload)."""
    return json.dumps({
        'apiKey': api_key,
        'allowedCommandModelConfigsProtoBinaryBase64': '',
        'userStatusProtoBinaryBase64': '',
    })


def batch_harvest(accounts, snapshots_data, force=False, limit=None):
    """Harvest all accounts sequentially."""
    template_conf = get_template_configs()
    total = len(accounts)
    if limit:
        accounts = accounts[:limit]

    harvested = 0
    skipped = 0
    failed = 0
    results = []

    for i, acc in enumerate(accounts):
        email = acc.get('email', '')
        password = acc.get('password', '')

        if not email or not password:
            results.append((i + 1, email, 'skip', 'no credentials'))
            skipped += 1
            continue

        if not force and email in snapshots_data.get('snapshots', {}):
            results.append((i + 1, email, 'skip', 'already harvested'))
            skipped += 1
            continue

        print(f'  [{i+1:2d}/{len(accounts)}] {email[:35]:35s}', end=' ', flush=True)

        try:
            api_key, info = harvest_one(email, password)
        except Exception as e:
            api_key, info = None, str(e)

        if api_key:
            blobs = {'windsurfAuthStatus': build_auth_blob(api_key)}
            if template_conf:
                blobs['windsurfConfigurations'] = template_conf

            snapshots_data.setdefault('snapshots', {})[email] = {
                'blobs': blobs,
                'harvested_at': datetime.now(timezone.utc).isoformat(),
                'api_key_preview': api_key[:20] + '...',
                'source': 'batch_harvest',
            }
            save_snapshots(snapshots_data)
            harvested += 1
            print(f'✅ {api_key[:25]}... ({info})')
            results.append((i + 1, email, 'ok', api_key[:20]))
        else:
            failed += 1
            print(f'❌ {info}')
            results.append((i + 1, email, 'fail', info))

        time.sleep(0.3)  # rate limit courtesy

    return harvested, skipped, failed, results


# ============================================================
# CLI
# ============================================================
def cmd_status():
    accounts = load_accounts()
    snapshots = load_snapshots()
    snap_emails = set(snapshots.get('snapshots', {}).keys())
    total = len(accounts)
    have = sum(1 for a in accounts if a.get('email') in snap_emails)
    print(f'\n  Batch Harvest Status')
    print(f'  {"="*50}')
    print(f'  Accounts:  {total}')
    print(f'  Harvested: {have}/{total} ({100*have//max(total,1)}%)')
    print(f'  Missing:   {total - have}')
    proxy = _detect_proxy()
    print(f'  Proxy:     {":" + str(proxy) if proxy else "none (relay mode)"}')
    print(f'  {"="*50}\n')

    for i, acc in enumerate(accounts):
        email = acc.get('email', '?')
        mark = '●' if email in snap_emails else '○'
        print(f'  {i+1:2d} {mark} {email[:40]}')


def cmd_harvest(force=False, limit=None):
    accounts = load_accounts()
    snapshots = load_snapshots()
    snap_count_before = len(snapshots.get('snapshots', {}))

    print(f'\n  Batch Harvest {"(FORCE)" if force else ""}')
    print(f'  {"="*50}')
    print(f'  Accounts: {len(accounts)}')
    print(f'  Existing: {snap_count_before}')
    if limit:
        print(f'  Limit:    {limit}')
    proxy = _detect_proxy()
    print(f'  Proxy:    {":" + str(proxy) if proxy else "none (relay mode)"}')
    print(f'  {"="*50}\n')

    h, s, f, results = batch_harvest(accounts, snapshots, force=force, limit=limit)

    snap_count_after = len(snapshots.get('snapshots', {}))
    print(f'\n  {"="*50}')
    print(f'  Results: ✅{h} harvested, ⏭{s} skipped, ❌{f} failed')
    print(f'  Snapshots: {snap_count_before} → {snap_count_after}')
    print(f'  {"="*50}\n')


def main():
    args = sys.argv[1:]
    if '--status' in args or 'status' in args:
        cmd_status()
    elif '--test' in args:
        idx = args.index('--test')
        limit = int(args[idx + 1]) if idx + 1 < len(args) else 3
        cmd_harvest(limit=limit)
    elif '--all' in args:
        cmd_harvest(force=True)
    else:
        cmd_harvest(force=False)


if __name__ == '__main__':
    main()
