#!/usr/bin/env python3
import sys, io, json, struct, time, ctypes, ctypes.wintypes, subprocess, re, requests, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

LS_EXE = 'language_server_windows_x64.exe'
DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'

def get_pid():
    r = subprocess.run(['tasklist','/FI',f'IMAGENAME eq {LS_EXE}','/FO','CSV','/NH'],
                       capture_output=True, text=True, timeout=5)
    for line in r.stdout.strip().splitlines():
        p = line.strip().strip('"').split('","')
        if len(p) >= 2:
            try: return int(p[1])
            except: pass
    return None

pid = get_pid()
print(f'LS PID: {pid}')

r = subprocess.run(['netstat','-ano'], capture_output=True)
net = r.stdout.decode('gbk', errors='replace')
ports = []
for line in net.splitlines():
    if 'LISTENING' in line:
        p = line.split()
        try:
            if int(p[-1]) == pid:
                port = int(p[1].split(':')[1])
                if port > 50000: ports.append(port)
        except: pass
print(f'Candidate ports: {ports}')

class PBI(ctypes.Structure):
    _fields_ = [('x',ctypes.c_long),('peb',ctypes.c_void_p),
                ('a',ctypes.c_void_p),('b',ctypes.c_long),
                ('c',ctypes.c_void_p),('d',ctypes.c_void_p)]

k32 = ctypes.windll.kernel32
ntdl = ctypes.windll.ntdll
csrf = None
h = k32.OpenProcess(0x10 | 0x400 | 0x1000, False, pid)
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
    print(f'CSRF error: {e}')
finally:
    k32.CloseHandle(h)
print(f'CSRF: {csrf}')

con = sqlite3.connect(DB)
row = con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
con.close()
key = json.loads(row[0]).get('apiKey', '') if row else ''
print(f'Key: {key[:25]}...')

PORT = ports[0] if ports else None
if not PORT or not csrf or not key:
    print('Missing required params, exit')
    sys.exit(1)

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
    'x-codeium-csrf-token': csrf, 'x-grpc-web': '1'
}

def call(method, body, timeout=10):
    body['metadata'] = META
    b = json.dumps(body).encode()
    r = requests.post(
        f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/{method}',
        data=b'\x00' + struct.pack('>I', len(b)) + b,
        headers=HDR, timeout=timeout, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    frames = []; pos = 0
    while pos + 5 <= len(raw):
        fl = raw[pos]; n = struct.unpack('>I', raw[pos+1:pos+5])[0]; pos += 5
        frames.append((fl, raw[pos:pos+n])); pos += n
    return frames

print('\n--- Init Cascade ---')
call('InitializeCascadePanelState', {'workspaceTrusted': True})
call('UpdateWorkspaceTrust', {'workspaceTrusted': True})
f1 = call('StartCascade', {'source': 'CORTEX_TRAJECTORY_SOURCE_USER'})
cid = next((json.loads(d).get('cascadeId') for fl, d in f1 if fl == 0 and b'cascadeId' in d), None)
print(f'CascadeID: {cid}')
if not cid:
    print('No cascade ID')
    sys.exit(1)

# Test with FREE model first
for MODEL in ['MODEL_SWE_1_5', 'MODEL_SWE_1_5_SLOW', 'MODEL_CHAT_GPT_5_CODEX']:
    print(f'\n--- Testing model: {MODEL} ---')
    call('SendUserCascadeMessage', {
        'cascadeId': cid,
        'items': [{'text': 'Reply EXACTLY: PROBE_OK. Then: 1+1=?'}],
        'cascadeConfig': {'plannerConfig': {'requestedModelUid': MODEL, 'conversational': {}}}
    }, timeout=12)

    print('Streaming (timeout=45s)...')
    sb = json.dumps({'id': cid, 'protocolVersion': 1}).encode()
    t0 = time.time()
    got = 0
    texts = []
    try:
        r2 = requests.post(
            f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
            data=b'\x00' + struct.pack('>I', len(sb)) + sb,
            headers=HDR, timeout=45, stream=True)
        buf = b''
        for chunk in r2.iter_content(chunk_size=256):
            buf += chunk
            got += len(chunk)
            while len(buf) >= 5:
                nl = struct.unpack('>I', buf[1:5])[0]
                if len(buf) < 5 + nl: break
                fl = buf[0]; fr = buf[5:5+nl]; buf = buf[5+nl:]
                if fl != 0x80:
                    try:
                        def walk(o, d=0):
                            if d > 15: return
                            if isinstance(o, str) and 3 < len(o) < 500: texts.append(o)
                            elif isinstance(o, dict): [walk(v, d+1) for v in o.values()]
                            elif isinstance(o, list): [walk(i, d+1) for i in o]
                        walk(json.loads(fr))
                    except: pass
            if 'PROBE_OK' in ''.join(texts): break
            if time.time() - t0 > 40: break
        elapsed = time.time() - t0
        print(f'Received {got} bytes in {elapsed:.1f}s')
        print('Strings (first 25):')
        seen = set()
        for s in texts:
            if s not in seen and len(s) > 3:
                seen.add(s)
                print(f'  {repr(s[:200])}')
            if len(seen) >= 25: break
        if 'PROBE_OK' in ''.join(texts):
            print(f'\n*** SUCCESS: {MODEL} works! ***')
            break
    except Exception as e:
        print(f'Stream error: {e}')
    
    time.sleep(1)
