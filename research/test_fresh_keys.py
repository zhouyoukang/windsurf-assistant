"""
Clean test: RegisterUser for cr=100 accounts → test each key for Claude access
No daemon running. One test at a time with proper timing.
"""
import json, io, sys, struct, time, requests, ctypes, subprocess, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

CACHE    = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\zhouyoukang.windsurf-assistant\wam-token-cache.json'
ACCOUNTS = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\windsurf-assistant-accounts.json'
VAULT    = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\claude_key.vault'

REGISTER_URL = 'https://register.windsurf.com/exa.seat_management_pb.SeatManagementService/RegisterUser'

def encode_proto_string(value):
    b = value.encode('utf-8'); tag = 0x0a
    length = len(b); lb = []
    while length > 127: lb.append((length & 0x7f) | 0x80); length >>= 7
    lb.append(length)
    return bytes([tag] + lb) + b

def parse_proto_string(buf):
    if not buf or len(buf) < 3 or buf[0] != 0x0a: return None
    pos = 1; length = 0; shift = 0
    while pos < len(buf):
        b = buf[pos]; pos += 1; length |= (b & 0x7f) << shift
        if not (b & 0x80): break
        shift += 7
    return buf[pos:pos+length].decode('utf-8', errors='replace') if pos+length <= len(buf) else None

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

def test_claude(key, port, csrf, verbose=True):
    """Full cascade test for claude-opus-4-6. Returns True/False/None"""
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
        if verbose: print(f"    cascadeId={cid[:8] if cid else 'NONE'}...")
        if not cid: return None
    except Exception as e:
        if verbose: print(f"    startup err: {e}")
        return None
    try:
        call('SendUserCascadeMessage',{
            'metadata':meta,'cascadeId':cid,
            'items':[{'text':'hi'}],
            'cascadeConfig':{'plannerConfig':{'requestedModelUid':'claude-opus-4-6','conversational':{}}}
        },timeout=25)
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
                    if verbose: print(f"    frame: {s[:120]}")
                    if 'permission_denied' in s: denied=True
                except: pass
            if denied or time.time()-t0>8: break
        if verbose: print(f"    got={got} denied={denied}")
        if not got: return None
        return not denied
    except Exception as e:
        if verbose: print(f"    stream err: {e}")
        return None

# ── Main ──────────────────────────────────────────────────────────────────
print("Getting LS infra...")
port, csrf = get_infra()
print(f"port={port}  csrf={csrf[:8] if csrf else None}...")
print()

cache = json.load(open(CACHE,encoding='utf-8',errors='replace'))
accounts = json.load(open(ACCOUNTS,encoding='utf-8',errors='replace'))
cred_map = {a.get('email',''): a for a in accounts}

# Test cr=100 accounts only
cr100_emails = [
    'oexkeqxfxq9781@yahoo.com',
    'wnqhcrdmrx167@yahoo.com',
    'bbggykbo842070@yahoo.com',
    'gdpx383415503@yahoo.com',
    'YorkNathandLtMf@yahoo.com',
    'lwrjltdakthwk6@yahoo.com',
]

for email in cr100_emails:
    entry = cache.get(email,{})
    id_token = entry.get('idToken','')
    if not id_token:
        print(f"{email}: no cached token, skip")
        continue
    cr = cred_map.get(email,{}).get('credits',0)
    print(f"[cr={cr}] {email}")
    try:
        r = requests.post(REGISTER_URL, data=encode_proto_string(id_token),
                          headers={'Content-Type':'application/proto','connect-protocol-version':'1','User-Agent':'WindsurfIDE/1.108.2'},
                          timeout=12)
        key = parse_proto_string(r.content) if r.status_code==200 else None
        if not key:
            print(f"  RegisterUser failed: HTTP {r.status_code}")
            continue
        print(f"  apiKey: {key}")
        if port and csrf:
            result = test_claude(key, port, csrf, verbose=True)
            print(f"  => Claude result: {result}")
            if result is True:
                json.dump({'key':key,'ts':time.time(),'email':email,'cr':cr},open(VAULT,'w'))
                print(f"\n*** VAULT SAVED ***  key={key[:50]}...")
                print("Run: python opus46_ultimate.py '你的问题'")
                sys.exit(0)
        else:
            print("  No LS port available")
        print()
        time.sleep(3)  # brief pause between accounts
    except Exception as e:
        print(f"  error: {e}")
        print()

print("Done. No Claude key found in cr=100 accounts.")
print("These accounts may be 'Trial' plan without Claude Opus 4.6 access.")
