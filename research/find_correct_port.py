#!/usr/bin/env python3
"""
找到正确的 LS 端口 (Cascade 活跃连接最多的那个) + 对应 CSRF
然后用该端口测试 cascade
"""
import sys, io, json, struct, time, ctypes, ctypes.wintypes, subprocess, re, requests, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

LS_EXE = 'language_server_windows_x64.exe'
DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'

# 1. 找所有 LS PIDs
r1 = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {LS_EXE}', '/FO', 'CSV', '/NH'],
                    capture_output=True, timeout=5)
ls_pids = []
for line in r1.stdout.decode('gbk', errors='replace').strip().splitlines():
    p = line.strip().strip('"').split('","')
    if len(p) >= 2:
        try: ls_pids.append(int(p[1]))
        except: pass
print(f'All LS PIDs: {ls_pids}')

# 2. 找所有 Windsurf PIDs
r2 = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, timeout=5)
all_pids = {}
for line in r2.stdout.decode('gbk', errors='replace').strip().splitlines():
    p = line.strip().strip('"').split('","')
    if len(p) >= 2:
        try: all_pids[int(p[1])] = p[0]
        except: pass
ws_pids = [pid for pid, name in all_pids.items() if name.lower().startswith('windsurf')]
print(f'Windsurf PIDs: {ws_pids}')

# 3. 从 netstat 找每个 LS PID 的监听端口，以及 WS→LS 连接数
r3 = subprocess.run(['netstat', '-ano'], capture_output=True)
net = r3.stdout.decode('gbk', errors='replace')

# LS 监听端口
ls_listen = {}  # {port: ls_pid}
for pid in ls_pids:
    for line in net.splitlines():
        if 'LISTENING' in line:
            p = line.split()
            try:
                if int(p[-1]) == pid:
                    port = int(p[1].split(':')[1])
                    if port > 1024:
                        ls_listen[port] = pid
            except: pass

print(f'LS listen ports: {ls_listen}')

# WS→LS 连接计数
port_conn_count = {}  # {port: count}
for pid in ws_pids:
    for line in net.splitlines():
        if 'ESTABLISHED' in line and '127.0.0.1' in line:
            p = line.split()
            try:
                if int(p[-1]) == pid:
                    remote_port = int(p[2].split(':')[1])
                    if remote_port in ls_listen:
                        port_conn_count[remote_port] = port_conn_count.get(remote_port, 0) + 1
            except: pass

print(f'WS→LS connection counts: {port_conn_count}')

# 4. 选最活跃的端口 (连接数最多)
if port_conn_count:
    best_port = max(port_conn_count, key=port_conn_count.get)
else:
    best_port = list(ls_listen.keys())[0] if ls_listen else None

print(f'\nBest port (most WS connections): {best_port}')

# 5. 找该端口对应 LS 的 CSRF
best_pid = ls_listen.get(best_port)
print(f'LS PID for best port: {best_pid}')

class PBI(ctypes.Structure):
    _fields_ = [('x',ctypes.c_long),('peb',ctypes.c_void_p),
                ('a',ctypes.c_void_p),('b',ctypes.c_long),
                ('c',ctypes.c_void_p),('d',ctypes.c_void_p)]

def get_csrf_for_pid(pid):
    if not pid: return None
    k32 = ctypes.windll.kernel32
    ntdl = ctypes.windll.ntdll
    h = k32.OpenProcess(0x10 | 0x400 | 0x1000, False, pid)
    csrf = None
    try:
        pbi = PBI()
        ntdl.NtQueryInformationProcess(h, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), None)
        peb = pbi.peb
        def rp(addr, n=8):
            buf = ctypes.create_string_buffer(n)
            sz = ctypes.c_size_t(0)
            k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(sz))
            return buf.raw[:sz.value]
        pp = struct.unpack('<Q', rp(peb + 0x20))[0]
        ep = struct.unpack('<Q', rp(pp + 0x80))[0]
        esz_raw = rp(pp + 0x3F0)
        esz = min(struct.unpack('<Q', esz_raw)[0] if len(esz_raw)==8 else 0x10000, 0x80000)
        if esz == 0: esz = 0x10000
        env = rp(ep, esz).decode('utf-16-le', errors='replace')
        m = re.search(r'WINDSURF_CSRF_TOKEN=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', env, re.I)
        if m: csrf = m.group(1)
    except Exception as e:
        print(f'  CSRF error for PID {pid}: {e}')
    finally:
        k32.CloseHandle(h)
    return csrf

# Get CSRF for all LS instances
csrf_map = {}
for pid in ls_pids:
    csrf = get_csrf_for_pid(pid)
    ports_for_pid = [p for p, lp in ls_listen.items() if lp == pid]
    print(f'  LS PID {pid} → ports {ports_for_pid}, CSRF: {csrf}')
    if csrf:
        for p in ports_for_pid:
            csrf_map[p] = csrf

best_csrf = csrf_map.get(best_port)
print(f'\nBest CSRF for port {best_port}: {best_csrf}')

# 6. Get API key
con = sqlite3.connect(DB)
row = con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
con.close()
key = json.loads(row[0]).get('apiKey', '') if row else ''
print(f'Key: {key[:25]}...')

if not best_port or not best_csrf or not key:
    print('Missing params')
    sys.exit(1)

# 7. Quick cascade test on best port
META = {
    'ideName': 'Windsurf', 'ideVersion': '1.108.2',
    'extensionVersion': '3.14.2', 'extensionName': 'Windsurf',
    'extensionPath': r'D:\Windsurf\resources\app\extensions\windsurf',
    'locale': 'en-US', 'os': 'win32',
    'url': 'https://server.codeium.com', 'apiKey': key
}
HDR = {
    'Content-Type': 'application/grpc-web+json',
    'Accept': 'application/grpc-web+json',
    'x-codeium-csrf-token': best_csrf, 'x-grpc-web': '1'
}

def call(method, body, timeout=10):
    b_body = dict(body); b_body['metadata'] = META
    b = json.dumps(b_body).encode()
    r = requests.post(
        f'http://127.0.0.1:{best_port}/exa.language_server_pb.LanguageServerService/{method}',
        data=b'\x00' + struct.pack('>I', len(b)) + b,
        headers=HDR, timeout=timeout, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    frames = []; pos = 0
    while pos + 5 <= len(raw):
        fl = raw[pos]; n = struct.unpack('>I', raw[pos+1:pos+5])[0]; pos += 5
        frames.append((fl, raw[pos:pos+n])); pos += n
    return frames

print(f'\n=== Cascade test on port {best_port} ===')
call('InitializeCascadePanelState', {'workspaceTrusted': True})
call('UpdateWorkspaceTrust', {'workspaceTrusted': True})
f1 = call('StartCascade', {'source': 'CORTEX_TRAJECTORY_SOURCE_USER'})
cid = next((json.loads(d).get('cascadeId') for fl, d in f1 if fl == 0 and b'cascadeId' in d), None)
print(f'CascadeID: {cid}')

if not cid:
    print('FAIL: no cascade_id')
    sys.exit(1)

# Test without specifying model
print('Sending message...')
try:
    f2 = call('SendUserCascadeMessage', {
        'cascadeId': cid,
        'items': [{'text': 'Reply EXACTLY: PORT_OK. 1+1=?'}],
    }, timeout=12)
    print(f'Send OK, frames: {len(f2)}')
    for fl, fr in f2[:3]:
        if fl == 0x80:
            print(f'  Trailer: {fr.decode("utf-8","replace")[:100]}')
        else:
            try:
                print(f'  Frame: {json.dumps(json.loads(fr))[:200]}')
            except:
                print(f'  Raw: {fr.hex()[:60]}')
except Exception as e:
    print(f'Send error: {e}')
    sys.exit(1)

print('Streaming (60s)...')
sb = json.dumps({'id': cid, 'protocolVersion': 1}).encode()
t0 = time.time()
got = 0; texts = []; first_at = None
try:
    rs = requests.post(
        f'http://127.0.0.1:{best_port}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
        data=b'\x00' + struct.pack('>I', len(sb)) + sb,
        headers=HDR, timeout=65, stream=True)
    buf = b''
    for chunk in rs.iter_content(chunk_size=64):
        if not first_at:
            first_at = time.time() - t0
            print(f'  First bytes at {first_at:.1f}s')
        buf += chunk; got += len(chunk)
        while len(buf) >= 5:
            nl = struct.unpack('>I', buf[1:5])[0]
            if len(buf) < 5 + nl: break
            fl = buf[0]; fr = buf[5:5+nl]; buf = buf[5+nl:]
            if fl == 0x80:
                print(f'  Trailer: {fr.decode("utf-8","replace")[:200]}')
            else:
                try:
                    def walk(o, d=0):
                        if d > 15: return
                        if isinstance(o, str) and 3 < len(o) < 800: texts.append(o)
                        elif isinstance(o, dict): [walk(v, d+1) for v in o.values()]
                        elif isinstance(o, list): [walk(i, d+1) for i in o]
                    walk(json.loads(fr))
                except: pass
        if 'PORT_OK' in '\n'.join(texts): break
        if time.time() - t0 > 58: break
except Exception as e:
    print(f'Stream error at {time.time()-t0:.1f}s: {e}')

print(f'Received {got} bytes, {len(texts)} strings in {time.time()-t0:.1f}s')
seen = set()
for s in texts:
    if s not in seen:
        seen.add(s)
        if len(s) > 5:
            print(f'  {repr(s[:200])}')
    if len(seen) >= 30: break
