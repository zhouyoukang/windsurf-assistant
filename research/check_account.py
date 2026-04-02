"""check_account.py — 诊断账号权限 + 搜索工作账号"""
import json, sqlite3, base64, struct, re

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'

# === 1. Decode userStatusProtoBinaryBase64 ===
print("=== 1. Current account user status ===")
conn = sqlite3.connect(DB); cur = conn.cursor()
cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
row = cur.fetchone(); conn.close()
auth = json.loads(row[0])
api_key = auth.get('apiKey', '')
user_status_b64 = auth.get('userStatusProtoBinaryBase64', '')
print(f"api_key: {api_key[:30]}...")

if user_status_b64:
    try:
        raw = base64.b64decode(user_status_b64)
        print(f"userStatus bytes: {len(raw)}")
        # Try to find readable strings in the proto binary
        # Look for plan name, subscription type
        text_parts = re.findall(b'[\x20-\x7e]{4,}', raw)
        for t in text_parts:
            s = t.decode('ascii', errors='replace')
            print(f"  text: {s}")
        
        # Parse proto fields manually for known fields
        print(f"\n  Raw hex: {raw[:100].hex()}")
    except Exception as e:
        print(f"  decode error: {e}")

# === 2. Check WAM snapshots for plan types ===
print("\n=== 2. WAM account plan analysis ===")
SNAP = r'e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine\_wam_snapshots.json'
try:
    data = json.loads(open(SNAP, encoding='utf-8', errors='replace').read())
    snaps = data.get('snapshots', [])
    print(f"Total: {len(snaps)} accounts")
    
    # Check first account structure
    if snaps:
        snap = snaps[0]
        if isinstance(snap, dict):
            print(f"Fields: {list(snap.keys())[:15]}")
            print(f"Sample: {json.dumps(snap, ensure_ascii=False)[:500]}")
        elif isinstance(snap, str):
            # It's a JSON string itself
            try:
                snap_data = json.loads(snap)
                print(f"Fields: {list(snap_data.keys())[:15]}")
                print(f"Sample: {json.dumps(snap_data, ensure_ascii=False)[:500]}")
            except:
                print(f"String snap: {snap[:200]}")
except Exception as e:
    print(f"Snapshot error: {e}")

# === 3. Check if there's an active Windsurf Cascade session we can use ===
print("\n=== 3. Check local Windsurf state for active cascade ===")
DB2 = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
conn2 = sqlite3.connect(DB2); cur2 = conn2.cursor()
cur2.execute("SELECT key, length(value) FROM ItemTable")
rows = cur2.fetchall()
for k, l in rows:
    if any(x in k.lower() for x in ['cascade', 'session', 'conversation', 'chat']):
        cur2.execute("SELECT value FROM ItemTable WHERE key=?", (k,))
        val = cur2.fetchone()[0]
        print(f"  {k} ({l}B): {str(val)[:200]}")
conn2.close()
