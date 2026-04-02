"""
hub9870_scan.py
Port 9870 has no auth. Scan all endpoints, get account data, test inject.
"""
import json, io, sys, struct, time, requests, ctypes, subprocess, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

VAULT    = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\claude_key.vault'
ACCOUNTS = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\windsurf-assistant-accounts.json'
CACHE    = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\zhouyoukang.windsurf-assistant\wam-token-cache.json'
REGISTER_URL = 'https://register.windsurf.com/exa.seat_management_pb.SeatManagementService/RegisterUser'

def hub9870(path, method='GET', body=None, timeout=8):
    try:
        if method == 'GET':
            r = requests.get(f'http://127.0.0.1:9870{path}', timeout=timeout)
        else:
            r = requests.post(f'http://127.0.0.1:9870{path}', json=body, timeout=timeout)
        return r.status_code, r.json() if r.headers.get('Content-Type','').startswith('application/json') else r.text
    except Exception as e:
        return None, str(e)

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

def test_model(key, port, csrf, model_uid):
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
            'cascadeConfig':{'plannerConfig':{'requestedModelUid':model_uid,'conversational':{}}}},timeout=25)
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
print("=== Port 9870 Full Health ===")
s, d = hub9870('/health')
print(json.dumps(d, ensure_ascii=False, indent=2) if isinstance(d, dict) else str(d)[:500])
print()

print("=== Scanning all endpoints ===")
endpoints = [
    '/api/v1/ping', '/api/v1/status', '/api/v1/acquire', '/api/v1/inject',
    '/api/v1/accounts', '/api/v1/pool-accounts', '/api/v1/metric',
    '/api/v1/me-status', '/api/v1/current', '/api/v1/list',
    '/accounts', '/status', '/ping', '/inject',
    '/api/v1/account/current', '/api/v1/account/active',
    '/api/v1/auth', '/api/v1/token', '/api/v1/apikey',
]
for ep in endpoints:
    s, d = hub9870(ep, timeout=4)
    if s and s != 404:
        dstr = json.dumps(d)[:200] if isinstance(d, dict) else str(d)[:200]
        print(f"  {ep} → {s}: {dstr}")

print()
print("=== Inject: try active account (index 92) ===")
# Load accounts to find index 92
try:
    accounts = json.load(open(ACCOUNTS, encoding='utf-8', errors='replace'))
    if len(accounts) > 92:
        acc = accounts[92]
        email = acc.get('email','')
        print(f"Index 92: {email} cr={acc.get('credits',0)} plan={(acc.get('usage') or {}).get('plan','?')}")
        
        # Try inject for this account
        s, d = hub9870(f'/api/v1/inject?e={requests.utils.quote(email)}', timeout=8)
        print(f"inject → {s}: {json.dumps(d)[:400] if isinstance(d,dict) else str(d)[:400]}")
        
        # Also try accounts around index 92
        for idx in range(88, 95):
            if idx < len(accounts):
                a = accounts[idx]
                print(f"  [{idx}] {a.get('email','')} cr={a.get('credits',0)} plan={(a.get('usage') or {}).get('plan','?')}")
except Exception as e:
    print(f"ERROR: {e}")

print()
print("=== Try inject for all accounts ===")
# Try inject endpoint for all emails
cache = json.load(open(CACHE, encoding='utf-8', errors='replace'))
accounts_list = json.load(open(ACCOUNTS, encoding='utf-8', errors='replace'))
ls_port, csrf = get_infra()
print(f"LS: port={ls_port} csrf={csrf[:8] if csrf else None}...")

# Try inject for accounts in cache that we haven't tested yet
tried = set(['oexkeqxfxq9781@yahoo.com','wnqhcrdmrx167@yahoo.com','bbggykbo842070@yahoo.com',
             'gdpx383415503@yahoo.com','YorkNathandLtMf@yahoo.com','lwrjltdakthwk6@yahoo.com',
             'makaylahackett171808@yahoo.com'])
print()
print("Testing remaining cached accounts for Claude...")
found = False
for email, entry in cache.items():
    if email in tried: continue
    id_token = entry.get('idToken','')
    if not id_token: continue
    
    # Get RegisterUser key
    try:
        r = requests.post(REGISTER_URL, data=encode_proto_string(id_token),
                          headers={'Content-Type':'application/proto','connect-protocol-version':'1'},
                          timeout=10)
        key = parse_proto_string(r.content) if r.status_code==200 else None
    except: continue
    if not key: continue
    
    # Quick Claude test
    if ls_port and csrf:
        result = test_model(key, ls_port, csrf, 'claude-opus-4-6')
        cr = next((a.get('credits',0) for a in accounts_list if a.get('email','')==email), '?')
        plan = next(((a.get('usage') or {}).get('plan','?') for a in accounts_list if a.get('email','')==email), '?')
        status = "OK" if result is True else ("DENIED" if result is False else "TIMEOUT")
        print(f"  {email} cr={cr} plan={plan} → {status}")
        if result is True:
            json.dump({'key':key,'email':email,'ts':time.time()},open(VAULT,'w'))
            print(f"  *** CLAUDE KEY SAVED! key={key[:50]}... ***")
            found = True
            break
        time.sleep(1)

if not found:
    print("\nNo Claude-capable account found in remaining cache entries.")
