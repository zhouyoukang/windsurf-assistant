"""
hub_api.py
Call local hub API (port 19881 admin / port 9870 local)
Compute HMAC auth from machine fingerprint (matches cloudPool.js logic)
"""
import hashlib, hmac, time, secrets, json, io, sys, platform, struct, requests, subprocess, re, ctypes
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

VAULT    = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\claude_key.vault'
REGISTER_URL = 'https://register.windsurf.com/exa.seat_management_pb.SeatManagementService/RegisterUser'
CACHE    = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\zhouyoukang.windsurf-assistant\wam-token-cache.json'

# ── Compute HMAC auth (mirrors cloudPool.js _machineId / _localSecret / _signHeaders) ──
def machine_id():
    """sha256(hostname|username|cpu_model|platform|arch)"""
    hostname = platform.node()
    username = 'Administrator'  # os.userInfo().username on Windows
    try:
        # Get CPU model from wmic
        r = subprocess.run(['wmic','cpu','get','Name','/value'],capture_output=True,text=True,timeout=3)
        cpu = r.stdout.strip().split('=')[-1].strip() if '=' in r.stdout else ''
    except: cpu = ''
    plat = 'win32'
    arch = 'x64'
    data = '|'.join([hostname, username, cpu, plat, arch])
    print(f"  machineId input: {data}")
    return hashlib.sha256(data.encode()).hexdigest()

def local_secret(mid):
    """HMAC-SHA256(machine_id, 'wam-relay-v1')"""
    return hmac.new(mid.encode(), b'wam-relay-v1', hashlib.sha256).hexdigest()

def device_id(hostname, username):
    """sha256(hostname|username)[:16]"""
    return hashlib.sha256(f'{hostname}|{username}'.encode()).hexdigest()[:16]

def sign_headers(local_sec, dev_id):
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    sig = hmac.new(local_sec.encode(), f'{ts}.{nonce}'.encode(), hashlib.sha256).hexdigest()
    return {'x-ts': ts, 'x-nc': nonce, 'x-sg': sig, 'x-di': dev_id,
            'Content-Type': 'application/json'}

def hub_get(path, port=19881, headers=None, timeout=6):
    try:
        r = requests.get(f'http://127.0.0.1:{port}{path}',
                        headers=headers or {}, timeout=timeout)
        return r.status_code, r.json()
    except Exception as e:
        return None, {'error': str(e)}

def hub_post(path, body, port=19881, headers=None, timeout=8):
    try:
        hdr = dict(headers or {}); hdr['Content-Type'] = 'application/json'
        r = requests.post(f'http://127.0.0.1:{port}{path}',
                         json=body, headers=hdr, timeout=timeout)
        return r.status_code, r.json()
    except Exception as e:
        return None, {'error': str(e)}

# Proto helpers
def encode_proto_string(value):
    b = value.encode('utf-8'); tag = 0x0a
    L = len(b); lb = []
    while L > 127: lb.append((L & 0x7f) | 0x80); L >>= 7
    lb.append(L)
    return bytes([tag] + lb) + b

def parse_proto_string(buf):
    if not buf or len(buf) < 3 or buf[0] != 0x0a: return None
    pos = 1; L = 0; shift = 0
    while pos < len(buf):
        b = buf[pos]; pos += 1; L |= (b & 0x7f) << shift
        if not (b & 0x80): break
        shift += 7
    return buf[pos:pos+L].decode('utf-8', errors='replace') if pos+L <= len(buf) else None

# Get LS infra
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

def test_claude_key(key, port, csrf):
    meta={'ideName':'Windsurf','ideVersion':'1.108.2','extensionVersion':'3.14.2',
          'locale':'en-US','os':'win32','url':'https://server.codeium.com','apiKey':key}
    hdr={'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
         'x-codeium-csrf-token':csrf,'x-grpc-web':'1'}
    def call(method, body, timeout=15):
        b=json.dumps(body).encode()
        r=requests.post(f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/{method}',
            data=b'\x00'+struct.pack('>I',len(b))+b,headers=hdr,timeout=timeout,stream=True)
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
        call('SendUserCascadeMessage',{
            'metadata':meta,'cascadeId':cid,'items':[{'text':'hi'}],
            'cascadeConfig':{'plannerConfig':{'requestedModelUid':'claude-opus-4-6','conversational':{}}}
        },timeout=25)
        sb=json.dumps({'id':cid,'protocolVersion':1}).encode()
        r3=requests.post(f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
            data=b'\x00'+struct.pack('>I',len(sb))+sb,headers=hdr,timeout=12,stream=True)
        buf=b''; t0=__import__('time').time(); denied=False; got=False
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
            if denied or __import__('time').time()-t0>8: break
        return False if denied else (True if got else None)
    except: return None

# ── Main ──────────────────────────────────────────────────────────────────
print("=== Computing HMAC auth ===")
mid = machine_id()
print(f"  machineId: {mid[:16]}...")
lsec = local_secret(mid)
print(f"  localSecret: {lsec[:16]}...")
dev_id = device_id(platform.node(), 'Administrator')
print(f"  deviceId: {dev_id}")
auth_hdr = sign_headers(lsec, dev_id)
print(f"  headers: x-ts={auth_hdr['x-ts']} x-nc={auth_hdr['x-nc'][:8]}... x-sg={auth_hdr['x-sg'][:16]}...")
print()

# ── Port 19881 calls (admin hub, needs HMAC) ──────────────────────────────
print("=== Admin Hub (19881) ===")
status, data = hub_get('/api/v1/ping', 19881, auth_hdr)
print(f"ping → {status}: {data}")
print()

status, data = hub_get('/api/v1/status', 19881, auth_hdr)
print(f"status → {status}: {json.dumps(data)[:400]}")
print()

status, data = hub_get('/api/v1/acquire', 19881, auth_hdr)
print(f"acquire → {status}: {json.dumps(data)[:600]}")
print()

status, data = hub_get('/api/v1/metric', 19881, auth_hdr)
print(f"metric → {status}: {json.dumps(data)[:400]}")
print()

# ── Port 9870 calls (local hub, no auth needed) ───────────────────────────
print("=== Local Hub (9870) ===")
status, data = hub_get('/api/v1/pool-accounts', 9870)
print(f"pool-accounts → {status}: {json.dumps(data)[:600]}")
print()

status, data = hub_get('/api/v1/ping', 9870)
print(f"ping → {status}: {data}")
print()

# Try all paths with both ports
for path in ['/api/v1/ping', '/api/v1/status', '/api/v1/acquire', '/api/v1/inject']:
    for port in [9870, 19881]:
        hdr = auth_hdr if port == 19881 else {}
        s, d = hub_get(path, port, hdr, timeout=4)
        if s and s != 404:
            print(f"  {port}{path} → {s}: {json.dumps(d)[:200]}")
print()

# ── If acquire returned an account, try to get its API key ───────────────
print("=== Testing acquired accounts ===")
ls_port, csrf = get_infra()
print(f"LS port={ls_port} csrf={csrf[:8] if csrf else None}...")
print()

# Re-run acquire in case it returned something
status, data = hub_get('/api/v1/acquire', 19881, auth_hdr)
if status == 200 and data.get('ok'):
    print(f"Acquired account: {json.dumps(data)[:400]}")
    # Try to get idToken from cache or use inject
    email = data.get('email', '')
    id_token = data.get('idToken') or data.get('token') or data.get('firebase_token')
    if not id_token:
        # Try inject
        qs_email = requests.utils.quote(email) if email else ''
        si, di = hub_get(f'/api/v1/inject?e={qs_email}', 9870)
        print(f"inject → {si}: {json.dumps(di)[:300]}")
        id_token = di.get('idToken') or di.get('token') if isinstance(di, dict) else None
    if id_token and 'eyJ' in id_token:
        r = requests.post(REGISTER_URL, data=encode_proto_string(id_token),
                          headers={'Content-Type':'application/proto','connect-protocol-version':'1'}, timeout=12)
        key = parse_proto_string(r.content) if r.status_code==200 else None
        if key:
            print(f"API key: {key}")
            if ls_port and csrf:
                result = test_claude_key(key, ls_port, csrf)
                print(f"Claude test: {result}")
                if result is True:
                    json.dump({'key':key,'email':email,'ts':__import__('time').time()},open(VAULT,'w'))
                    print("*** VAULT SAVED ***")
else:
    print(f"No account acquired: {data}")
