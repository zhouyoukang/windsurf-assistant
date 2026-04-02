"""
exchange_token.py
Exchange Firebase idToken -> Windsurf API key for cr=100 accounts
Then test the key for Claude access via local LS
"""
import json, io, sys, struct, time, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

CACHE    = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\zhouyoukang.windsurf-assistant\wam-token-cache.json'
ACCOUNTS = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\windsurf-assistant-accounts.json'
VAULT    = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\claude_key.vault'

cache    = json.load(open(CACHE,    encoding='utf-8', errors='replace'))
accounts = json.load(open(ACCOUNTS, encoding='utf-8', errors='replace'))
cred_map = {a.get('email',''): a for a in accounts}

# Endpoints to try
ENDPOINTS = [
    ('server.codeium.com',   'POST', 'https://server.codeium.com/register_user_v1'),
    ('register.windsurf.com','POST', 'https://register.windsurf.com/register_user_v1'),
    ('register.windsurf.com','POST', 'https://register.windsurf.com/api/register_user_v1'),
    ('register.windsurf.com','POST', 'https://register.windsurf.com/auth/register'),
    ('register.windsurf.com','POST', 'https://register.windsurf.com/auth/token'),
    ('register.windsurf.com','POST', 'https://register.windsurf.com/user/apikey'),
]

def try_exchange(email, id_token):
    """Try all known endpoints to get an API key for this account"""
    for server, method, url in ENDPOINTS:
        try:
            body = {"firebase_id_token": id_token, "email": email}
            r = requests.post(url, json=body, timeout=8,
                headers={'Content-Type':'application/json','User-Agent':'WindsurfIDE/1.108.2'})
            print(f"  {url} -> HTTP {r.status_code} | {r.text[:200]}")
            if r.status_code == 200:
                data = r.json()
                key = (data.get('api_key') or data.get('apiKey') or 
                       data.get('token') or data.get('authToken') or '')
                if key:
                    print(f"  => KEY: {key[:40]}...")
                    return key
        except Exception as e:
            print(f"  {url} -> ERR: {e}")
    return ''

# Get port/CSRF for testing
def _get_ls_state():
    import subprocess, re, ctypes
    r = subprocess.run(['tasklist','/FI','IMAGENAME eq language_server_windows_x64.exe','/FO','CSV','/NH'],
                       capture_output=True, text=True, timeout=5)
    pid = None
    for line in r.stdout.strip().splitlines():
        parts = line.strip().strip('"').split('","')
        if len(parts)>=2:
            try: pid=int(parts[1]); break
            except: pass
    if not pid: return None, None

    net = subprocess.run(['netstat','-ano'],capture_output=True).stdout.decode('gbk',errors='replace')
    port = None
    for line in net.splitlines():
        if 'LISTENING' in line:
            p=line.split()
            try:
                if int(p[-1])==pid:
                    pt=int(p[1].split(':')[1])
                    if pt>50000: port=pt; break
            except: pass

    # PEB CSRF
    class _PBI(ctypes.Structure):
        _fields_=[('ExitStatus',ctypes.c_long),('PebBaseAddress',ctypes.c_void_p),
                  ('AffinityMask',ctypes.c_void_p),('BasePriority',ctypes.c_long),
                  ('UniqueProcessId',ctypes.c_void_p),('InheritedUniq',ctypes.c_void_p)]
    k32=ctypes.windll.kernel32; ntdl=ctypes.windll.ntdll
    h=k32.OpenProcess(0x10|0x400|0x1000,False,pid)
    csrf=None
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
            import re as _re
            env=rb(ep,es).decode('utf-16-le',errors='replace')
            m=_re.search(r'WINDSURF_CSRF_TOKEN=([0-9a-f-]{36})',env,_re.I)
            csrf=m.group(1) if m else None
        except: pass
        finally: k32.CloseHandle(h)
    return port, csrf

def test_key(key, port, csrf):
    """Quick Claude test — returns True/False/None"""
    meta={'ideName':'Windsurf','ideVersion':'1.108.2','extensionVersion':'3.14.2',
          'locale':'en-US','os':'win32','url':'https://server.codeium.com','apiKey':key}
    hdr={'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
         'x-codeium-csrf-token':csrf,'x-grpc-web':'1'}
    def call(method, body, timeout=15):
        b=json.dumps(body).encode()
        r=requests.post(f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/{method}',
                        data=b'\x00'+struct.pack('>I',len(b))+b, headers=hdr, timeout=timeout, stream=True)
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
    except Exception as e:
        print(f"  startup err: {e}"); return None
    try:
        call('SendUserCascadeMessage',{
            'metadata':meta,'cascadeId':cid,
            'items':[{'text':'hi'}],
            'cascadeConfig':{'plannerConfig':{'requestedModelUid':'claude-opus-4-6','conversational':{}}}
        }, timeout=20)
        sb=json.dumps({'id':cid,'protocolVersion':1}).encode()
        r3=requests.post(f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
                         data=b'\x00'+struct.pack('>I',len(sb))+sb, headers=hdr, timeout=10, stream=True)
        buf=b''; t0=time.time(); denied=False; got=False
        for chunk in r3.iter_content(chunk_size=128):
            buf+=chunk
            while len(buf)>=5:
                nl=struct.unpack('>I',buf[1:5])[0]
                if len(buf)<5+nl: break
                fr=buf[5:5+nl]; buf=buf[5+nl:]
                if fr: got=True
                try:
                    if 'permission_denied' in json.dumps(json.loads(fr)): denied=True
                except: pass
            if denied or time.time()-t0>6: break
        if not got: return None
        return not denied
    except Exception as e:
        print(f"  stream err: {e}"); return None

# ── Main ──────────────────────────────────────────────────────────────────
print("Getting LS port/CSRF...")
port, csrf = _get_ls_state()
print(f"Port={port} CSRF={csrf[:8] if csrf else None}...")
print()

# Try all cr>=100 accounts
for email, entry in cache.items():
    acct = cred_map.get(email, {})
    cr = acct.get('credits', 0) or 0
    if cr < 100:
        continue
    id_token = entry.get('idToken', '')
    if not id_token:
        continue
    print(f"Trying {email} (cr={cr})...")
    api_key = try_exchange(email, id_token)
    if api_key:
        print(f"Got key: {api_key[:40]}...")
        if port and csrf:
            print("Testing Claude access...")
            result = test_key(api_key, port, csrf)
            print(f"Claude test result: {result}")
            if result is True:
                json.dump({'key': api_key, 'ts': time.time()}, open(VAULT, 'w'))
                print(f"\n*** SUCCESS! Key saved to vault ***")
                print(f"Run: python opus46_ultimate.py '你的问题'")
                sys.exit(0)
    print()

print("No key obtained from any endpoint. WAM daemon will continue in background.")
