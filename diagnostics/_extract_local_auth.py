#!/usr/bin/env python3
"""
从本机提取有效的Windsurf auth，准备注入179
"""
import sqlite3, json, os, urllib.request, urllib.error
from pathlib import Path

def test_key(api_key):
    """测试apiKey有效性（多个端点）"""
    endpoints = [
        ('https://server.codeium.com/exa/user_profile_service.v1.UserProfileService/GetUserInfo', b'{}', 'application/json'),
        ('https://www.codeium.com/api/get_user_info', None, None),
    ]
    for url, data, ct in endpoints:
        try:
            headers = {'Authorization': f'Bearer {api_key}'}
            if ct:
                headers['Content-Type'] = ct
            req = urllib.request.Request(url, data=data, headers=headers)
            resp = urllib.request.urlopen(req, timeout=8)
            body = resp.read().decode()[:200]
            return True, f"{url}: {body[:100]}"
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:100]
            if e.code != 404:
                return False, f"HTTP {e.code}: {body[:80]}"
            # 404 means wrong endpoint, try next
        except Exception as e:
            pass
    # Try simple check via codeium API
    try:
        req = urllib.request.Request(
            'https://server.codeium.com/auth/token',
            data=json.dumps({'api_key': api_key}).encode(),
            headers={'Content-Type': 'application/json'}
        )
        resp = urllib.request.urlopen(req, timeout=8)
        return True, resp.read().decode()[:100]
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:100]
        return False, f"token endpoint HTTP {e.code}: {body[:80]}"
    except Exception as e:
        return False, str(e)[:80]

# Read local state.vscdb
local_db = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')
print(f'Local DB: {local_db}')
print(f'DB exists: {os.path.exists(local_db)}')

conn = sqlite3.connect(local_db, timeout=5)
row = conn.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
if row:
    d = json.loads(row[0])
    ak = d.get('apiKey', '')
    em = d.get('email', '')
    print(f'\nLocal windsurfAuthStatus:')
    print(f'  email: {em}')
    print(f'  apiKey_len: {len(ak)}')
    print(f'  apiKey: {ak[:60]}...')
    print(f'  full blob: {row[0][:300]}')
else:
    print('NO windsurfAuthStatus in local DB')

# Also check optimal_key.txt
optimal_path = Path(__file__).parent.parent / '010-道引擎_DaoEngine' / '_optimal_key.txt'
if optimal_path.exists():
    opt_key = optimal_path.read_text().strip()
    print(f'\nOptimal key: {opt_key[:60]}...')
    ok, msg = test_key(opt_key)
    print(f'  Valid: {ok} | {msg}')

# Test local key too
if row and ak:
    ok2, msg2 = test_key(ak)
    print(f'\nLocal key valid: {ok2} | {msg2}')

conn.close()
