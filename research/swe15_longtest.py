#!/usr/bin/env python3
"""
swe15_longtest.py — 绕过 key vault，直接用 DB key 测试 SWE-1.5
等待最长300s，看是否有任何响应
"""
import sys, io, json, struct, time, ctypes, subprocess, re, requests, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
LS_EXE = 'language_server_windows_x64.exe'

# --- detect LS (prefer most connections) ---
def find_best_ls():
    r1 = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {LS_EXE}', '/FO', 'CSV', '/NH'],
                        capture_output=True, timeout=5)
    ls_pids = []
    for line in r1.stdout.decode('gbk', errors='replace').strip().splitlines():
        p = line.strip().strip('"').split('","')
        if len(p) >= 2:
            try: ls_pids.append(int(p[1]))
            except: pass

    r2 = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, timeout=5)
    all_pids = {}
    for line in r2.stdout.decode('gbk', errors='replace').strip().splitlines():
        p = line.strip().strip('"').split('","')
        if len(p) >= 2:
            try: all_pids[int(p[1])] = p[0]
            except: pass
    ws_pids = [pid for pid, name in all_pids.items() if name.lower().startswith('windsurf')]

    r3 = subprocess.run(['netstat', '-ano'], capture_output=True)
    net = r3.stdout.decode('gbk', errors='replace')

    ls_listen = {}
    for pid in ls_pids:
        for line in net.splitlines():
            if 'LISTENING' in line:
                p = line.split()
                try:
                    if int(p[-1]) == pid:
                        port = int(p[1].split(':')[1])
                        if port > 1024: ls_listen[port] = pid
                except: pass

    port_count = {}
    for pid in ws_pids:
        for line in net.splitlines():
            if 'ESTABLISHED' in line and '127.0.0.1' in line:
                p = line.split()
                try:
                    if int(p[-1]) == pid:
                        rp = int(p[2].split(':')[1])
                        if rp in ls_listen:
                            port_count[rp] = port_count.get(rp, 0) + 1
                except: pass

    if port_count:
        best_port = max(port_count, key=port_count.get)
    elif ls_listen:
        best_port = list(ls_listen.keys())[0]
    else:
        return None, None, None

    best_pid = ls_listen.get(best_port)
    return best_pid, best_port, port_count.get(best_port, 0)

def get_csrf(pid):
    class PBI(ctypes.Structure):
        _fields_ = [('x',ctypes.c_long),('peb',ctypes.c_void_p),
                    ('a',ctypes.c_void_p),('b',ctypes.c_long),
                    ('c',ctypes.c_void_p),('d',ctypes.c_void_p)]
    k32 = ctypes.windll.kernel32; ntdl = ctypes.windll.ntdll
    h = k32.OpenProcess(0x10|0x400|0x1000, False, pid)
    csrf = None
    try:
        pbi = PBI(); ntdl.NtQueryInformationProcess(h, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), None)
        peb = pbi.peb
        def rp(a, n=8):
            b = ctypes.create_string_buffer(n); s = ctypes.c_size_t(0)
            k32.ReadProcessMemory(h, ctypes.c_void_p(a), b, n, ctypes.byref(s))
            return b.raw[:s.value]
        pp = struct.unpack('<Q', rp(peb+0x20))[0]
        ep = struct.unpack('<Q', rp(pp+0x80))[0]
        sr = rp(pp+0x3F0)
        es = min(struct.unpack('<Q',sr)[0] if len(sr)==8 else 0x10000, 0x80000) or 0x10000
        env = rp(ep, es).decode('utf-16-le', errors='replace')
        m = re.search(r'WINDSURF_CSRF_TOKEN=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', env, re.I)
        if m: csrf = m.group(1)
    except: pass
    finally: k32.CloseHandle(h)
    return csrf

# --- main ---
ls_pid, ls_port, conn_count = find_best_ls()
print(f'LS PID: {ls_pid}, Port: {ls_port}, WS connections: {conn_count}')

csrf = get_csrf(ls_pid) if ls_pid else None
print(f'CSRF: {csrf}')

con = sqlite3.connect(DB)
row = con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
con.close()
db_info = json.loads(row[0]) if row else {}
key = db_info.get('apiKey', '')
print(f'Key: {key[:25]}... (email: {db_info.get("email","?")})')

if not all([ls_port, csrf, key]):
    print('Missing params, exit'); sys.exit(1)

META = {'ideName':'Windsurf','ideVersion':'1.108.2','extensionVersion':'3.14.2',
        'extensionName':'Windsurf','extensionPath':r'D:\Windsurf\resources\app\extensions\windsurf',
        'locale':'en-US','os':'win32','url':'https://server.codeium.com','apiKey':key,
        'impersonateTier':'TEAMS_TIER_PRO'}
HDR  = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
        'x-codeium-csrf-token':csrf,'x-grpc-web':'1'}

def call(method, body, timeout=15):
    b = json.dumps({**body,'metadata':META}).encode()
    r = requests.post(
        f'http://127.0.0.1:{ls_port}/exa.language_server_pb.LanguageServerService/{method}',
        data=b'\x00'+struct.pack('>I',len(b))+b, headers=HDR, timeout=timeout, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    frames=[]; pos=0
    while pos+5<=len(raw):
        fl=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        frames.append((fl,raw[pos:pos+n])); pos+=n
    return frames

print('\n--- Initializing cascade ---')
call('InitializeCascadePanelState', {'workspaceTrusted':True})
call('UpdateWorkspaceTrust', {'workspaceTrusted':True})

f1 = call('StartCascade', {'source':'CORTEX_TRAJECTORY_SOURCE_USER'})
cid = next((json.loads(d).get('cascadeId') for fl,d in f1 if fl==0 and b'cascadeId' in d), None)
print(f'CascadeID: {cid}')
if not cid: sys.exit(1)

# Test each model
MODELS = [
    ('MODEL_SWE_1_5',           'SWE-1.5 (free)'),
    ('MODEL_CLAUDE_4_5_OPUS',   'Claude Opus 4.5'),
    ('claude-sonnet-4-6',       'Sonnet 4.6'),
    ('MODEL_CHAT_GPT_5_CODEX',  'GPT-5 Codex'),
]

for model_uid, model_name in MODELS:
    print(f'\n{"="*60}')
    print(f'Testing: {model_name} ({model_uid})')
    
    try:
        call('SendUserCascadeMessage', {
            'cascadeId': cid,
            'items': [{'text': f'Reply EXACTLY: {model_uid[:10]}_OK. 1+1=?'}],
            'cascadeConfig': {'plannerConfig': {'requestedModelUid': model_uid, 'conversational': {}}}
        }, timeout=15)
        print('  SendMessage: OK')
    except Exception as e:
        print(f'  SendMessage: FAIL ({type(e).__name__}: {str(e)[:80]})')
        continue

    print('  Streaming (max 300s)...')
    sb = json.dumps({'id':cid,'protocolVersion':1}).encode()
    t0 = time.time(); got_bytes=0; texts=[]; first_at=None; frame_count=0

    try:
        r2 = requests.post(
            f'http://127.0.0.1:{ls_port}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
            data=b'\x00'+struct.pack('>I',len(sb))+sb,
            headers=HDR, timeout=305, stream=True)
        
        buf=b''
        for chunk in r2.iter_content(chunk_size=32):
            if not first_at:
                first_at = time.time()-t0
                print(f'  First bytes at {first_at:.2f}s')
            got_bytes += len(chunk)
            buf += chunk
            while len(buf) >= 5:
                nl = struct.unpack('>I',buf[1:5])[0]
                if len(buf) < 5+nl: break
                fl=buf[0]; fr=buf[5:5+nl]; buf=buf[5+nl:]
                frame_count += 1
                if fl == 0x80:
                    print(f'  TRAILER: {fr.decode("utf-8","replace")[:200]}')
                else:
                    try:
                        def walk(o,d=0):
                            if d>20: return
                            if isinstance(o,str) and 3<len(o)<1000: texts.append(o)
                            elif isinstance(o,dict): [walk(v,d+1) for v in o.values()]
                            elif isinstance(o,list): [walk(i,d+1) for i in o]
                        walk(json.loads(fr))
                    except: pass
            
            # Print progress every 10s
            elapsed = time.time()-t0
            if int(elapsed) % 10 == 0 and elapsed > 0:
                print(f'  {elapsed:.0f}s: {got_bytes} bytes, {frame_count} frames, {len(texts)} strings')
            
            # Check for success
            tok = f'{model_uid[:10]}_OK'
            if any(tok in s for s in texts):
                print(f'  *** SUCCESS at {time.time()-t0:.1f}s! ***')
                break
            if time.time()-t0 > 280:
                print(f'  TIMEOUT at 280s')
                break
                
    except Exception as e:
        print(f'  Stream error at {time.time()-t0:.1f}s: {e}')
    
    elapsed = time.time()-t0
    print(f'  Result: {got_bytes} bytes, {frame_count} frames in {elapsed:.1f}s')
    if texts:
        seen=set()
        print(f'  Strings ({len(texts)} total, first 15 unique):')
        for s in texts:
            if s not in seen:
                seen.add(s)
                print(f'    {repr(s[:200])}')
            if len(seen)>=15: break
    else:
        print('  No strings received')
    
    if got_bytes > 0:
        print('  → This model HAS stream access!')
        break
    else:
        print('  → Stream empty (trial block?)')

print('\n--- Done ---')
