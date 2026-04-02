#!/usr/bin/env python3
"""
raw_stream_test.py — 最简流测试，自适应端口+CSRF
不指定模型，用服务器默认，等待最长120s
"""
import sys, io, json, struct, time, ctypes, ctypes.wintypes, subprocess, re, requests, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

LS_EXE = 'language_server_windows_x64.exe'
DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'

# --- get PID ---
r = subprocess.run(['tasklist','/FI',f'IMAGENAME eq {LS_EXE}','/FO','CSV','/NH'],
                   capture_output=True, text=True, timeout=5)
pid = None
for line in r.stdout.strip().splitlines():
    p = line.strip().strip('"').split('","')
    if len(p) >= 2:
        try: pid = int(p[1]); break
        except: pass
print(f'LS PID: {pid}')

# --- get ports ---
r2 = subprocess.run(['netstat','-ano'], capture_output=True)
net = r2.stdout.decode('gbk', errors='replace')
ports = []
for line in net.splitlines():
    if 'LISTENING' in line:
        p = line.split()
        try:
            if int(p[-1]) == pid:
                port = int(p[1].split(':')[1])
                if port > 50000: ports.append(port)
        except: pass
print(f'LS ports: {ports}')

# --- get CSRF from PEB ---
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
    print(f'CSRF err: {e}')
finally:
    k32.CloseHandle(h)

print(f'CSRF: {csrf}')

# --- get API key ---
con = sqlite3.connect(DB)
row = con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
con.close()
key = json.loads(row[0]).get('apiKey', '') if row else ''
print(f'Key: {key[:25]}...')

# Also check WAM cache for better key
WAM_CACHE = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\zhouyoukang.windsurf-assistant\wam-token-cache.json'
try:
    cache = json.load(open(WAM_CACHE, encoding='utf-8'))
    keys = []
    for v in cache.values():
        if isinstance(v, dict) and v.get('apiKey'):
            keys.append(v['apiKey'])
    if keys:
        print(f'WAM cache has {len(keys)} keys: {keys[0][:25]}...')
        # Use first cached key as alternative
        alt_key = keys[0]
    else:
        alt_key = None
except Exception as e:
    alt_key = None
    print(f'WAM cache error: {e}')

if not pid or not ports or not csrf or not key:
    print('Missing params, exit')
    sys.exit(1)

PORT = ports[0]
print(f'Using port: {PORT}')

def test_key(test_key_val, label):
    META = {
        'ideName': 'Windsurf', 'ideVersion': '1.108.2',
        'extensionVersion': '3.14.2', 'extensionName': 'Windsurf',
        'extensionPath': r'D:\Windsurf\resources\app\extensions\windsurf',
        'locale': 'en-US', 'os': 'win32',
        'url': 'https://server.codeium.com', 'apiKey': test_key_val
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

    print(f'\n=== Testing key: {label} ({test_key_val[:20]}...) ===')

    call('InitializeCascadePanelState', {'workspaceTrusted': True})
    call('UpdateWorkspaceTrust', {'workspaceTrusted': True})
    f1 = call('StartCascade', {'source': 'CORTEX_TRAJECTORY_SOURCE_USER'})
    cid = next((json.loads(d).get('cascadeId') for fl, d in f1 if fl == 0 and b'cascadeId' in d), None)
    print(f'  CascadeID: {cid}')
    if not cid:
        print('  FAIL: no cascade_id')
        return False

    # Send WITHOUT model specified (let server pick default)
    call('SendUserCascadeMessage', {
        'cascadeId': cid,
        'items': [{'text': 'Reply EXACTLY: STREAM_OK. Then: 1+1=?'}],
        # No cascadeConfig — let server use default model
    }, timeout=10)

    print(f'  Streaming... (max 90s)')
    sb = json.dumps({'id': cid, 'protocolVersion': 1}).encode()
    t0 = time.time()
    got_bytes = 0
    texts = []
    first_byte_at = None

    try:
        r2 = requests.post(
            f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
            data=b'\x00' + struct.pack('>I', len(sb)) + sb,
            headers=HDR, timeout=90, stream=True)

        buf = b''
        for chunk in r2.iter_content(chunk_size=64):
            if not first_byte_at:
                first_byte_at = time.time() - t0
                print(f'  First bytes at {first_byte_at:.1f}s')
            buf += chunk
            got_bytes += len(chunk)
            while len(buf) >= 5:
                nl = struct.unpack('>I', buf[1:5])[0]
                if len(buf) < 5 + nl: break
                fl = buf[0]; fr = buf[5:5+nl]; buf = buf[5+nl:]
                if fl == 0x80:
                    try: texts.append(f'TRAILER:{fr.decode("utf-8","replace")[:100]}')
                    except: pass
                else:
                    try:
                        def walk(o, d=0):
                            if d > 15: return
                            if isinstance(o, str) and 3 < len(o) < 800: texts.append(o)
                            elif isinstance(o, dict): [walk(v, d+1) for v in o.values()]
                            elif isinstance(o, list): [walk(i, d+1) for i in o]
                        walk(json.loads(fr))
                    except: pass
            if 'STREAM_OK' in '\n'.join(texts): break
            if time.time() - t0 > 85: break
    except Exception as e:
        print(f'  Stream error after {time.time()-t0:.1f}s: {e}')
        return False

    elapsed = time.time() - t0
    print(f'  Got {got_bytes} bytes in {elapsed:.1f}s, {len(texts)} strings')

    if texts:
        print('  Strings (first 30):')
        seen = set()
        for s in texts:
            if s not in seen:
                seen.add(s)
                if len(s) > 3:
                    print(f'    {repr(s[:200])}')
            if len(seen) >= 30: break
        if 'STREAM_OK' in '\n'.join(texts):
            print('  *** SUCCESS! Stream works! ***')
            return True
    else:
        print('  No text received (pure timeout or empty stream)')
    return False

# Test with DB key
success = test_key(key, 'DB key')

# If failed, try WAM cache key
if not success and alt_key and alt_key != key:
    success = test_key(alt_key, 'WAM cache key')

# Also try the old/known-good CSRF
if not success:
    print('\n=== Trying with old hardcoded CSRF ===')
    OLD_CSRF = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'
    csrf_bak = csrf
    csrf = OLD_CSRF
    success = test_key(key, 'DB key + old CSRF')
    if not success and alt_key:
        success = test_key(alt_key, 'WAM key + old CSRF')
    csrf = csrf_bak

print(f'\n=== Final: {"SUCCESS" if success else "FAILED"} ===')
