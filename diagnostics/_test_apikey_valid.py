#!/usr/bin/env python3
"""测试API key是否有效 + 找快照池中最新的key"""
import json, urllib.request, urllib.error
from pathlib import Path

SNAP_FILE = Path(__file__).parent.parent / '010-道引擎_DaoEngine' / '_wam_snapshots.json'

def test_key(api_key, label=""):
    """测试apiKey是否能访问Windsurf API"""
    try:
        req = urllib.request.Request(
            'https://api.codeium.com/exa/user_profile_service.v1.UserProfileService/GetUserInfo',
            data=b'{}',
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            }
        )
        resp = urllib.request.urlopen(req, timeout=8)
        body = resp.read().decode()
        return True, body[:200]
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        return False, f"HTTP {e.code}: {body}"
    except Exception as e:
        return False, str(e)[:100]

# Test current 179 key
current_key = "sk-ws-01-btQIpAWHcDJ3jLRUBQkcl785Ze5qR0479coPwtmUTSgxeVdmR8-lmnNTnT9bgHf_C_ejmnD5afw32O8m_KLa_O_7sDuV7g"
print(f"Testing current 179 key...")
ok, msg = test_key(current_key, "current_179")
print(f"  Valid: {ok}")
print(f"  Response: {msg[:300]}")

# Test a few snapshots
print("\nTesting snapshot keys (newest 5)...")
data = json.loads(SNAP_FILE.read_text('utf-8'))
snapshots = data.get('snapshots', {})
candidates = []
for email, snap in snapshots.items():
    blobs = snap.get('blobs', {})
    auth_blob = blobs.get('windsurfAuthStatus', '')
    if auth_blob:
        try:
            a = json.loads(auth_blob)
            ak = a.get('apiKey', '')
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

candidates.sort(key=lambda x: x['harvestedAt'], reverse=True)
print(f"Total candidates: {len(candidates)}")

valid_found = None
for i, c in enumerate(candidates[:10]):
    ok, msg = test_key(c['apiKey'], c['email'])
    status = "VALID" if ok else "DEAD"
    print(f"  [{status}] {c['email'][:40]} | {c['harvestedAt'][:19]}")
    if ok:
        print(f"         key={c['apiKey'][:40]}...")
        if not valid_found:
            valid_found = c
        break

if valid_found:
    print(f"\n==> BEST VALID ACCOUNT: {valid_found['email']}")
    print(f"    ApiKey: {valid_found['apiKey'][:60]}...")
    print(f"    AuthBlob: {valid_found['authBlob'][:100]}...")
else:
    print("\n==> No valid keys found in first 10, scanning more...")
    for c in candidates[10:30]:
        ok, msg = test_key(c['apiKey'])
        if ok:
            print(f"  FOUND VALID: {c['email']} | {c['harvestedAt'][:19]}")
            print(f"  key={c['apiKey'][:60]}...")
            valid_found = c
            break
    if not valid_found:
        print("  ==> All scanned keys are dead/expired")
