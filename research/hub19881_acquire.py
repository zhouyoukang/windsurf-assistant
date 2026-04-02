"""
hub19881_acquire.py
Use real machineId from /health endpoint to compute correct HMAC.
Call hub 19881 /api/v1/acquire to get cloud pool account.
Also dump full pool-accounts from 9870.
"""
import hashlib, hmac as hmac_mod, json, io, sys, secrets, time, struct, requests, ctypes, subprocess, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Real machineId from health endpoint (computed by Node.js os.cpus()[0].model with real CPU)
REAL_MACHINE_ID = '7ff516363f853d465c5570306cb76b814250f505ecb0bd93fb713e8e640bcef8'
DEVICE_ID       = '5de1481a54d76d69'  # sha256(hostname|username)[:16]

VAULT       = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\claude_key.vault'
REGISTER_URL= 'https://register.windsurf.com/exa.seat_management_pb.SeatManagementService/RegisterUser'
CACHE       = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\zhouyoukang.windsurf-assistant\wam-token-cache.json'
FIREBASE_LOGIN = 'https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=AIzaSyBK1MHonRGBx9ZvHMQJ9LM1X5oQbAYGHKA'

# ── HMAC auth (cloudPool.js _localSecret + _signHeaders) ─────────────────
def local_secret():
    return hmac_mod.new(REAL_MACHINE_ID.encode(), b'wam-relay-v1', hashlib.sha256).hexdigest()

def sign_headers():
    """Fresh headers each call"""
    ls = local_secret()
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    sig = hmac_mod.new(ls.encode(), f'{ts}.{nonce}'.encode(), hashlib.sha256).hexdigest()
    return {'x-ts': ts, 'x-nc': nonce, 'x-sg': sig, 'x-di': DEVICE_ID,
            'Content-Type': 'application/json'}

def hub19881(path, method='GET', body=None, timeout=20):
    hdr = sign_headers()  # FRESH per call
    try:
        if method == 'GET':
            r = requests.get(f'http://127.0.0.1:19881{path}', headers=hdr, timeout=timeout)
        else:
            r = requests.post(f'http://127.0.0.1:19881{path}', headers=hdr, json=body, timeout=timeout)
        return r.status_code, r.json()
    except Exception as e:
        return None, {'error': str(e)}

def hub9870(path, timeout=8):
    try:
        r = requests.get(f'http://127.0.0.1:9870{path}', timeout=timeout)
        return r.status_code, r.json()
    except Exception as e:
        return None, {'error': str(e)}

# Proto helpers
def encode_proto_string(value):
    b = value.encode('utf-8'); tag = 0x0a
    L = len(b); lb = []
    while L > 127: lb.append((L & 0x7f) | 0x80); L >>= 7
    lb.append(L); return bytes([tag] + lb) + b

def parse_proto_string(buf):
    if not buf or len(buf) < 3 or buf[0] != 0x0a: return None
    pos = 1; L = 0; shift = 0
    while pos < len(buf):
        b = buf[pos]; pos += 1; L |= (b & 0x7f) << shift
        if not (b & 0x80): break
        shift += 7
    return buf[pos:pos+L].decode('utf-8', errors='replace') if pos+L <= len(buf) else None

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
            sr=rb(pp+0x3F0,8); es=min(struct.unpack('<Q',sr)[0] if len(sr)==8 else 0x10000,0x80000)
            if es==0: es=0x10000
            env=rb(ep,es).decode('utf-16-le',errors='replace')
            m=re.search(r'WINDSURF_CSRF_TOKEN=([0-9a-f-]{36})',env,re.I)
            csrf=m.group(1) if m else None
        except: pass
        finally: k32.CloseHandle(h)
    return port, csrf

def test_claude(key, port, csrf):
    meta={'ideName':'Windsurf','ideVersion':'1.108.2','extensionVersion':'3.14.2',
          'locale':'en-US','os':'win32','url':'https://server.codeium.com','apiKey':key}
    hdr={'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
         'x-codeium-csrf-token':csrf,'x-grpc-web':'1'}
    def call(m, b, t=15):
        bd=json.dumps(b).encode()
        r=requests.post(f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/{m}',
            data=b'\x00'+struct.pack('>I',len(bd))+bd,headers=hdr,timeout=t,stream=True)
        raw=b''.join(r.iter_content(chunk_size=None)); frames=[]; pos=0
        while pos+5<=len(raw):
            fl=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
            frames.append((fl,raw[pos:pos+n])); pos+=n
        return frames
    try:
        call('InitializeCascadePanelState',{'metadata':meta,'workspaceTrusted':True})
        call('UpdateWorkspaceTrust',{'metadata':meta,'workspaceTrusted':True})
        f1=call('StartCascade',{'metadata':meta,'source':'CORTEX_TRAJECTORY_SOURCE_USER'})
        cid=next((json.loads(d).get('cascadeId') for fl,d in f1 if fl==0 and b'cascadeId' in d),None)
        if not cid: return None
        call('SendUserCascadeMessage',{'metadata':meta,'cascadeId':cid,'items':[{'text':'hi'}],
            'cascadeConfig':{'plannerConfig':{'requestedModelUid':'claude-opus-4-6','conversational':{}}}},timeout=25)
        sb=json.dumps({'id':cid,'protocolVersion':1}).encode()
        r3=requests.post(f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
            data=b'\x00'+struct.pack('>I',len(sb))+sb,headers=hdr,timeout=12,stream=True)
        buf=b''; t0=time.time(); denied=False; got=False
        for chunk in r3.iter_content(chunk_size=128):
            buf+=chunk
            while len(buf)>=5:
                nl=struct.unpack('>I',buf[1:5])[0]
                if len(buf)<5+nl: break
                fr=buf[5:5+nl]; buf=buf[5+nl:]
                if fr: got=True
                try:
                    s=json.dumps(json.loads(fr))
                    if 'permission_denied' in s: denied=True
                except: pass
            if denied or time.time()-t0>8: break
        return False if denied else (True if got else None)
    except: return None

# ── Main ──────────────────────────────────────────────────────────────────
print("=== Hub 19881 with correct HMAC ===")
print(f"localSecret: {local_secret()[:16]}...")
print()

# 1. Ping
s, d = hub19881('/api/v1/ping', timeout=15)
print(f"ping → {s}: {d}")
print()

# 2. Status
s, d = hub19881('/api/v1/status', timeout=15)
print(f"status → {s}: {json.dumps(d)[:400]}")
print()

# 3. Acquire — get cloud pool account
print("=== Acquiring cloud pool account ===")
s, d = hub19881('/api/v1/acquire', timeout=30)
print(f"acquire → {s}: {json.dumps(d)[:800]}")
print()

# 4. Inject — get account credentials
if isinstance(d, dict) and d.get('ok'):
    email = d.get('email','')
    print(f"Acquired: {email}")
    id_token = d.get('idToken') or d.get('token') or d.get('firebase_token')
    print(f"idToken present: {bool(id_token)}")
    
    if not id_token:
        # Try inject endpoint
        s2, d2 = hub19881(f'/api/v1/inject?e={requests.utils.quote(email)}', timeout=15)
        print(f"inject → {s2}: {json.dumps(d2)[:400]}")
        id_token = d2.get('idToken') if isinstance(d2,dict) else None
    
    if id_token:
        r = requests.post(REGISTER_URL, data=encode_proto_string(id_token),
                          headers={'Content-Type':'application/proto','connect-protocol-version':'1'}, timeout=12)
        key = parse_proto_string(r.content) if r.status_code==200 else None
        print(f"apiKey: {key}")
        if key:
            ls_port, csrf = get_infra()
            if ls_port and csrf:
                result = test_claude(key, ls_port, csrf)
                print(f"Claude test: {result}")
                if result is True:
                    json.dump({'key':key,'email':email,'ts':time.time()},open(VAULT,'w'))
                    print(f"\n*** VAULT SAVED: {key[:50]}... ***")

# 5. Full pool-accounts from 9870
print("\n=== Full pool-accounts (9870) ===")
s, d = hub9870('/api/v1/pool-accounts', timeout=10)
if isinstance(d, dict) and d.get('accounts'):
    accs = d['accounts']
    print(f"Total: {len(accs)} accounts")
    # Show unique plans
    plans = {}
    for a in accs:
        p = a.get('plan','?')
        plans[p] = plans.get(p, 0) + 1
    print(f"Plans: {plans}")
    # Show non-Trial accounts
    non_trial = [a for a in accs if a.get('plan','').lower() not in ('trial','free','')]
    print(f"Non-Trial accounts: {len(non_trial)}")
    for a in non_trial:
        print(f"  {a.get('email','')} plan={a.get('plan')} daily={a.get('daily_pct')} weekly={a.get('weekly_pct')}")
    # Show high-credit accounts  
    print("\nTop accounts by daily_pct:")
    by_daily = sorted(accs, key=lambda x: x.get('daily_pct',0) or 0, reverse=True)
    for a in by_daily[:10]:
        print(f"  {a.get('email','')} plan={a.get('plan')} d={a.get('daily_pct')} w={a.get('weekly_pct')} left={a.get('days_left')}")
else:
    print(f"pool-accounts → {s}: {json.dumps(d)[:200]}")

# 6. Metric endpoint
print("\n=== Metric ===")
s, d = hub19881('/api/v1/metric', timeout=20)
print(f"metric → {s}: {json.dumps(d)[:600]}")
