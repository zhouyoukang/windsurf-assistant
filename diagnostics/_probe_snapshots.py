import json
from pathlib import Path

snap_file = Path(__file__).parent.parent / '010-道引擎_DaoEngine' / '_wam_snapshots.json'
data = json.loads(snap_file.read_text('utf-8'))
snapshots = data.get('snapshots', {})
print(f'Total snapshots: {len(snapshots)}')

# Sample first 3
for i, (email, snap) in enumerate(list(snapshots.items())[:3]):
    blobs = snap.get('blobs', {})
    auth_blob = blobs.get('windsurfAuthStatus', '')
    print(f'\n--- {email} ---')
    print(f'  harvested_at: {snap.get("harvested_at","")}')
    print(f'  auth_blob present: {bool(auth_blob)}')
    if auth_blob:
        try:
            a = json.loads(auth_blob)
            print(f'  email in auth: {repr(a.get("email",""))}')
            print(f'  apiKey_len: {len(a.get("apiKey",""))}')
        except Exception as e:
            print(f'  parse err: {e}')
    print(f'  blob keys: {list(blobs.keys())[:8]}')

# Count valid ones
valid = 0
with_email = 0
for email, snap in snapshots.items():
    blobs = snap.get('blobs', {})
    auth_blob = blobs.get('windsurfAuthStatus', '')
    if auth_blob:
        try:
            a = json.loads(auth_blob)
            ak = a.get('apiKey', '')
            em = a.get('email', '')
            if len(ak) > 20:
                valid += 1
                if em:
                    with_email += 1
        except:
            pass

print(f'\nValid (apiKey>20): {valid}')
print(f'With email: {with_email}')

# Find top 3 newest with email
candidates = []
for email, snap in snapshots.items():
    blobs = snap.get('blobs', {})
    auth_blob = blobs.get('windsurfAuthStatus', '')
    if auth_blob:
        try:
            a = json.loads(auth_blob)
            ak = a.get('apiKey', '')
            em = a.get('email', '')
            if len(ak) > 20 and em:
                candidates.append({
                    'snap_email': email,
                    'auth_email': em,
                    'apiKey': ak,
                    'harvestedAt': snap.get('harvested_at', ''),
                })
        except:
            pass

candidates.sort(key=lambda x: x['harvestedAt'], reverse=True)
print(f'\nTop 3 newest with email:')
for c in candidates[:3]:
    print(f"  {c['snap_email']} | {c['auth_email']} | harvested={c['harvestedAt'][:19]} | key={c['apiKey'][:40]}...")
