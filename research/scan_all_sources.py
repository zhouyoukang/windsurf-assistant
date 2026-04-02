"""
Scan all account sources for Pro/Claude-capable accounts
And also test the current WAM key from state.vscdb
"""
import json, io, sys, os, sqlite3, struct, time, requests, ctypes, subprocess, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DB_PATH  = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
CACHE    = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\zhouyoukang.windsurf-assistant\wam-token-cache.json'
VAULT    = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\claude_key.vault'

# ── 1. Print current WAM key from state.vscdb ─────────────────────────────
print("=== Current WAM key from state.vscdb ===")
try:
    conn = sqlite3.connect(f'file:///{DB_PATH}?mode=ro', uri=True)
    cur = conn.cursor()
    r = cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
    if r:
        d = json.loads(r[0])
        print(f"apiKey: {d.get('apiKey','?')}")
        print(f"email: {d.get('email','?')}")
        print(f"plan: {d.get('plan','?')}")
    conn.close()
except Exception as e:
    print(f"ERROR: {e}")

# ── 2. Sample windsurf-login-accounts.json ─────────────────────────────────
print("\n=== windsurf-login-accounts.json sample ===")
login_path = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\windsurf-login-accounts.json'
try:
    login_accounts = json.load(open(login_path, encoding='utf-8', errors='replace'))
    if isinstance(login_accounts, list):
        print(f"List of {len(login_accounts)} accounts")
        # Show first few
        for a in login_accounts[:3]:
            print(json.dumps(a, ensure_ascii=False)[:300])
            print()
        # Check for any with special plan
        special = [a for a in login_accounts if (a.get('usage') or {}).get('plan','').lower() not in ('','trial','free','?')]
        print(f"Non-Trial/Free accounts: {len(special)}")
        for a in special[:5]:
            print(json.dumps(a, ensure_ascii=False)[:300])
    elif isinstance(login_accounts, dict):
        print(f"Dict with keys: {list(login_accounts.keys())[:5]}")
        print(json.dumps(login_accounts, ensure_ascii=False)[:500])
except Exception as e:
    print(f"ERROR: {e}")

# ── 3. Pool-admin extension ────────────────────────────────────────────────
print("\n=== Pool-Admin Extension ===")
pool_src = r'C:\Users\Administrator\.windsurf\extensions\zhouyoukang.pool-admin-2.2.0\src'
if os.path.exists(pool_src):
    for fname in os.listdir(pool_src):
        fpath = os.path.join(pool_src, fname)
        print(f"  {fname} ({os.path.getsize(fpath)} bytes)")
        if fname.endswith('.js') and os.path.getsize(fpath) < 100000:
            with open(fpath, encoding='utf-8', errors='replace') as f:
                content = f.read()
            # Find URLs and account sources
            for m in re.finditer(r'https://[^\s\"\'\`\)]{10,80}', content):
                print(f"    URL: {m.group()}")
            # Find Pro references
            for kw in ['pro', 'enterprise', 'claude', 'opus', 'premium']:
                idx = content.lower().find(kw)
                if idx >= 0:
                    print(f"    [{kw}] ...{content[max(0,idx-50):idx+100]}...")

# ── 4. Check wam-token-cache for accounts NOT in assistant-accounts ─────────
print("\n=== Accounts in token cache but with pw=N (may have different plan) ===")
cache = json.load(open(CACHE, encoding='utf-8', errors='replace'))
asst_path = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\windsurf-assistant-accounts.json'
assistant_accounts = json.load(open(asst_path, encoding='utf-8', errors='replace'))
asst_map = {a.get('email',''): a for a in assistant_accounts}
for email, entry in cache.items():
    a = asst_map.get(email, {})
    cr = a.get('credits', 0) or 0
    pw = bool(a.get('password'))
    plan = (a.get('usage') or {}).get('plan', '?')
    if not pw and cr >= 50:
        print(f"  [cr={cr}] pw=N plan={plan} {email}")

# ── 5. Test claude-sonnet-4-6 with a Trial key (quick check) ──────────────
print("\n=== Testing claude-sonnet-4-6 with a Trial cr=100 key ===")
# Use a key we just obtained
TEST_KEY = 'sk-ws-01-u2rd8HSzUQTHBcC2-uMqhpqYhWVt9HZUyLWOaQCz1eyMOY9jDGrZNHqwP7D3P6hzyuuyqbKxwKbZF19c0re_mQ4dhWecsA'

def get_infra():
    r = subprocess.run(['tasklist','/FI','IMAGENAME eq language_server_windows_x64.exe','/FO','CSV','/NH'],
                       capture_output=True, text=True, timeout=5)
    pid = None
    for line in r.stdout.strip().splitlines():
        parts = line.strip().strip('"').split('","')
        if len(parts)>=2:
            try: pid=int(parts[1]); break
            except: pass
    if not pid: return None, None
    net = subprocess.run(['netstat','-ano'],capture_output=True)
    netstr = net.stdout.decode('gbk',errors='replace')
    port = None
    for line in netstr.splitlines():
        if 'LISTENING' in line:
            p = line.split()
            try:
                if int(p[-1])==pid:
                    pt=int(p[1].split(':')[1])
                    if pt>50000:
                        try:
                            b=b'{"metadata":{"ideName":"W"},"workspaceTrusted":true}'
                            resp=requests.post(f'http://127.0.0.1:{pt}/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState',
                                data=b'\x00'+struct.pack('>I',len(b))+b,
                                headers={'Content-Type':'application/grpc-web+json','x-codeium-csrf-token':'probe','x-grpc-web':'1'},
                                timeout=1.5,stream=True)
                            list(resp.iter_content(chunk_size=None))
                            if resp.status_code in (200,403): port=pt; break
                        except: pass
            except: pass
    class _PBI(ctypes.Structure):
        _fields_=[('ExitStatus',ctypes.c_long),('PebBaseAddress',ctypes.c_void_p),
                  ('AffinityMask',ctypes.c_void_p),('BasePriority',ctypes.c_long),
                  ('UniqueProcessId',ctypes.c_void_p),('InheritedUniq',ctypes.c_void_p)]
    k32=ctypes.windll.kernel32; ntdl=ctypes.windll.ntdll
    h=k32.OpenProcess(0x10|0x400|0x1000,False,pid); csrf=None
    if h:
        try:
            pbi=_PBI(); ntdl.NtQueryInformationProcess(h,0,ctypes.byref(pbi),ctypes.sizeof(pbi),None)
            peb=pbi.PebBaseAddress
            def rp(a):
                b=ctypes.create_string_buffer(8); n=ctypes.c_size_t(0)
                k32.ReadProcessMemory(h,ctypes.c_void_p(a),b,8,ctypes.byref(n))
                return struct.unpack('<Q',b.raw)[0] if n.value==8 else 0
            def rb(a,s):
                b=ctypes.create_string_buffer(s); n=ctypes.c_size_t(0)
                k32.ReadProcessMemory(h,ctypes.c_void_p(a),b,s,ctypes.byref(n))
                return b.raw[:n.value]
            pp=rp(peb+0x20); ep=rp(pp+0x80)
            sr=rb(pp+0x3F0,8)
            es=min(struct.unpack('<Q',sr)[0] if len(sr)==8 else 0x10000,0x80000)
            if es==0: es=0x10000
            env=rb(ep,es).decode('utf-16-le',errors='replace')
            m=re.search(r'WINDSURF_CSRF_TOKEN=([0-9a-f-]{36})',env,re.I)
            csrf=m.group(1) if m else None
        except: pass
        finally: k32.CloseHandle(h)
    return port, csrf

port, csrf = get_infra()
print(f"port={port} csrf={csrf[:8] if csrf else None}...")
if port and csrf:
    meta={'ideName':'Windsurf','ideVersion':'1.108.2','extensionVersion':'3.14.2',
          'locale':'en-US','os':'win32','url':'https://server.codeium.com','apiKey':TEST_KEY}
    hdr={'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
         'x-codeium-csrf-token':csrf,'x-grpc-web':'1'}
    def call(method, body, timeout=15):
        b=json.dumps(body).encode()
        r=requests.post(f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/{method}',
            data=b'\x00'+struct.pack('>I',len(b))+b,headers=hdr,timeout=timeout,stream=True)
        raw=b''.join(r.iter_content(chunk_size=None)); pos=0; frames=[]
        while pos+5<=len(raw):
            fl=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
            frames.append((fl,raw[pos:pos+n])); pos+=n
        return frames
    try:
        call('InitializeCascadePanelState',{'metadata':meta,'workspaceTrusted':True})
        call('UpdateWorkspaceTrust',{'metadata':meta,'workspaceTrusted':True})
        f1=call('StartCascade',{'metadata':meta,'source':'CORTEX_TRAJECTORY_SOURCE_USER'})
        cid=next((json.loads(d).get('cascadeId') for fl,d in f1 if fl==0 and b'cascadeId' in d),None)
        print(f"cascadeId={cid}")
        if cid:
            # Test sonnet
            call('SendUserCascadeMessage',{
                'metadata':meta,'cascadeId':cid,'items':[{'text':'hi'}],
                'cascadeConfig':{'plannerConfig':{'requestedModelUid':'claude-sonnet-4-6','conversational':{}}}
            },timeout=25)
            sb=json.dumps({'id':cid,'protocolVersion':1}).encode()
            r3=requests.post(f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
                data=b'\x00'+struct.pack('>I',len(sb))+sb,headers=hdr,timeout=12,stream=True)
            buf=b''; t0=time.time(); denied=False; got=False; frames_seen=0
            for chunk in r3.iter_content(chunk_size=128):
                buf+=chunk
                while len(buf)>=5:
                    nl=struct.unpack('>I',buf[1:5])[0]
                    if len(buf)<5+nl: break
                    fr=buf[5:5+nl]; buf=buf[5+nl:]
                    if fr:
                        got=True; frames_seen+=1
                        try:
                            s=json.dumps(json.loads(fr))
                            if 'permission_denied' in s: denied=True
                        except: pass
                if denied or time.time()-t0>8: break
            print(f"claude-sonnet-4-6: got={got} denied={denied} frames={frames_seen}")
    except Exception as e:
        print(f"ERROR: {e}")
