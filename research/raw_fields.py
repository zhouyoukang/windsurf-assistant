"""raw_fields.py — 找 RawGetChatMessageRequest 字段 + 查 WAM 账号"""
import re, os, json, sqlite3

EXT_JS = r"D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'

# === 1. Find RawGetChatMessageRequest fields ===
print("=== RawGetChatMessageRequest fields ===")
with open(EXT_JS, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

idx = content.find('RawGetChatMessageRequest')
if idx >= 0:
    region = content[idx:idx+3000]
    # Find static fields definition
    fields = re.findall(r'\{no:(\d+),name:"([^"]+)",kind:"([^"]+)"(?:,T:([^,}\]]+))?', region)
    for no, name, kind, T in fields[:20]:
        print(f"  field {no}: {name} ({kind}{',' + T[:30] if T else ''})")
    # Also print raw context
    print("\n  Raw context:")
    print(region[:800])

print()

# === 2. Find RawGetChatMessage related metadata ===
print("=== Metadata used for RawGetChatMessage ===")
# Search for where rawGetChatMessage is called
for m in re.finditer(r'rawGetChatMessage\b', content):
    pos = m.start()
    ctx = content[max(0, pos-200):pos+400]
    if any(x in ctx for x in ['metadata', 'request', 'payload', 'cascade']):
        print(f"  @{pos}: {ctx[:400]}")
        print()

# === 3. Check WAM account pool ===
print("=== WAM account pool status ===")
# Try local WAM state files
wam_dirs = [
    r'e:\道\道生一\一生二\Windsurf无限额度\010-道引擎_DaoEngine',
]
for d in wam_dirs:
    for fn in os.listdir(d):
        if fn.endswith('.json') and ('pool' in fn.lower() or 'account' in fn.lower() or 'snapshot' in fn.lower()):
            fp = os.path.join(d, fn)
            try:
                data = json.loads(open(fp, encoding='utf-8', errors='replace').read())
                print(f"\n{fn}:")
                if isinstance(data, list):
                    for acc in data[:5]:
                        if isinstance(acc, dict):
                            key = acc.get('api_key', acc.get('apiKey', ''))[:20]
                            avail = acc.get('available', acc.get('is_available', '?'))
                            credits = acc.get('credits', acc.get('daily_credits', '?'))
                            print(f"  {key}... avail={avail} credits={credits}")
                elif isinstance(data, dict):
                    print(f"  keys: {list(data.keys())[:10]}")
            except Exception as e:
                print(f"  {fn}: {e}")

# === 4. Check current state.vscdb api_key ===
print("\n=== Current state.vscdb ===")
conn = sqlite3.connect(DB); cur = conn.cursor()
cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
row = cur.fetchone(); conn.close()
auth = json.loads(row[0])
print(f"  api_key: {auth.get('apiKey','')[:30]}...")
print(f"  keys: {[k for k in auth.keys() if k != 'allowedCommandModelConfigsProtoBinaryBase64']}")
