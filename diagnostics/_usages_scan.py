import sqlite3, os, json

db = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')
conn = sqlite3.connect('file:' + db + '?mode=ro', uri=True)
cur = conn.cursor()

# 1. Read usages keys
cur.execute("SELECT key, value FROM ItemTable WHERE key LIKE 'windsurf_auth-%-usages' LIMIT 5")
for k, v in cur.fetchall():
    print('KEY:', k)
    try:
        print(json.dumps(json.loads(v), indent=2)[:800])
    except:
        print(repr(v[:400]))
    print('---')

# 2. cachedPlanInfo
cur.execute("SELECT value FROM ItemTable WHERE key='windsurf.settings.cachedPlanInfo'")
r = cur.fetchone()
if r:
    print('=== cachedPlanInfo ===')
    try:
        print(json.dumps(json.loads(r[0]), indent=2)[:1500])
    except:
        print(repr(r[0][:500]))

# 3. windsurfAuthStatus (current active account)
cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
r = cur.fetchone()
if r:
    print('\n=== windsurfAuthStatus (keys only) ===')
    try:
        d = json.loads(r[0])
        for k in d.keys():
            v = d[k]
            if isinstance(v, (str, int, float, bool)):
                print(f'  {k}: {v}')
            elif isinstance(v, list):
                print(f'  {k}: list[{len(v)}]')
            elif isinstance(v, dict):
                print(f'  {k}: dict{{{list(v.keys())[:5]}}}')
    except Exception as e:
        print('ERROR:', e)

conn.close()
