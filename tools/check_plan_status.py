"""
Fetch real PlanStatus for accounts to check maxPremiumMessages / hasPaidFeatures.
Also test pw=N accounts (cr=52-64) for Claude access.
"""
import json, io, sys, struct, time, requests, ctypes, subprocess, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

CACHE = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\zhouyoukang.windsurf-assistant\wam-token-cache.json'
VAULT = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\claude_key.vault'

REGISTER_URL  = 'https://register.windsurf.com/exa.seat_management_pb.SeatManagementService/RegisterUser'
PLAN_STATUS_URL = 'https://server.codeium.com/exa.seat_management_pb.SeatManagementService/GetPlanStatus'

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

def read_varint(data, pos):
    result = 0; shift = 0
    while pos < len(data):
        b = data[pos]; pos += 1
        result |= (b & 0x7f) << shift
        if not (b & 0x80): break
        shift += 7
    return result, pos

def parse_plan_status(buf):
    """Simple scan for key fields"""
    data = buf if isinstance(buf, (bytes, bytearray)) else bytes(buf)
    result = {'raw_len': len(data)}
    # Scan for readable strings
    strings = []
    i = 0
    while i < len(data) - 2:
        if data[i] & 0x07 == 2:  # wire type 2 = length-delimited
            pos = i + 1
            try:
                L, pos2 = read_varint(data, pos)
                if 0 < L < 100 and pos2 + L <= len(data):
                    s = data[pos2:pos2+L]
                    try:
                        decoded = s.decode('utf-8')
                        if all(0x20 <= ord(c) <= 0x7e for c in decoded) and len(decoded) > 2:
                            strings.append(decoded)
                    except: pass
            except: pass
        i += 1
    result['strings'] = strings[:20]
    return result

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

def test_model(key, port, csrf, model_uid, verbose=False):
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
        if not cid: return 'no-cascade'
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
                    if verbose: print(f"      {s[:100]}")
                    if 'permission_denied' in s: denied=True
                except: pass
            if denied or time.time()-t0>8: break
        if not got: return 'timeout'
        return 'DENIED' if denied else 'OK'
    except Exception as e:
        return f'ERR:{e}'

# ── Main ──────────────────────────────────────────────────────────────────
cache = json.load(open(CACHE, encoding='utf-8', errors='replace'))
print("Getting infra...")
port, csrf = get_infra()
print(f"port={port}  csrf={csrf[:8] if csrf else None}...")
print()

# 1. Test with a cr=100 key but sonnet model
TRIAL_KEY = 'sk-ws-01-u2rd8HSzUQTHBcC2-uMqhpqYhWVt9HZUyLWOaQCz1eyMOY9jDGrZNHqwP7D3P6hzyuuyqbKxwKbZF19c0re_mQ4dhWecsA'

if port and csrf:
    print("=== Testing Trial cr=100 key with different models ===")
    for model in ['claude-sonnet-4-6', 'claude-opus-4-6', 'gpt-4o', 'gemini-1.5-pro']:
        result = test_model(TRIAL_KEY, port, csrf, model)
        print(f"  {model}: {result}")
        time.sleep(2)

# 2. Test pw=N accounts (cr=52-64) - might have different plan
print("\n=== Testing pw=N accounts (cr=52-64) for claude-opus-4-6 ===")
pwN_emails = [
    'pqef903224053@yahoo.com',
    'tvscyv633290@yahoo.com',
    'wvvxdrqa75067@yahoo.com',
    'scsrj5883346@yahoo.com',
    'nqaaieg2262093@yahoo.com',
]
for email in pwN_emails:
    entry = cache.get(email, {})
    if not entry.get('idToken'): 
        print(f"  {email}: not in cache")
        continue
    try:
        r = requests.post(REGISTER_URL, data=encode_proto_string(entry['idToken']),
                          headers={'Content-Type':'application/proto','connect-protocol-version':'1'},
                          timeout=12)
        key = parse_proto_string(r.content) if r.status_code==200 else None
        if not key:
            print(f"  {email}: RegisterUser failed HTTP {r.status_code}")
            continue
        print(f"  {email} → {key[:30]}...")
        if port and csrf:
            result = test_model(key, port, csrf, 'claude-opus-4-6')
            print(f"    claude-opus-4-6: {result}")
            if result == 'OK':
                json.dump({'key':key,'email':email,'ts':time.time()},open(VAULT,'w'))
                print(f"  *** SAVED TO VAULT ***")
        time.sleep(2)
    except Exception as e:
        print(f"  {email}: {e}")

# 3. Fetch PlanStatus for one Trial account to see maxPremiumMessages
print("\n=== PlanStatus for oexkeqxfxq9781@yahoo.com ===")
try:
    entry = cache.get('oexkeqxfxq9781@yahoo.com', {})
    if entry.get('idToken'):
        body = encode_proto_string(entry['idToken'])
        r = requests.post(PLAN_STATUS_URL, data=body,
                          headers={'Content-Type':'application/proto','connect-protocol-version':'1'},
                          timeout=12)
        print(f"HTTP {r.status_code} len={len(r.content)}")
        info = parse_plan_status(r.content)
        print(f"Strings in response: {info['strings']}")
        print(f"Raw bytes (first 100): {r.content[:100].hex()}")
except Exception as e:
    print(f"ERROR: {e}")
