"""
cdp_extract.py — 万法之资终极路: CDP + 内存读取 + gRPC header 分析
策略:
  1. 检查 CDP 端口 (9222-9229)
  2. 通过 CDP 执行 JS 获取 cascade session context
  3. 同时: 读取 grpcweb response 的 HTTP trailers
  4. 同时: 尝试从 LS 进程内存直接读取 cascade session ID
"""
import socket, http.client, json, struct, ssl, sqlite3, uuid
import ctypes, ctypes.wintypes, subprocess, re

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'

def get_api_key():
    conn = sqlite3.connect(DB); cur = conn.cursor()
    cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
    row = cur.fetchone(); conn.close()
    return json.loads(row[0]).get('apiKey', '')

api_key = get_api_key()
print(f"api: {api_key[:20]}...\n")

# ── 1. 检查 CDP 端口 ────────────────────────────────────────────────────────────
print("=== 1. CDP port scan ===")
cdp_port = None
for port in range(9220, 9240):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        if s.connect_ex(('127.0.0.1', port)) == 0:
            print(f"  port {port}: OPEN")
            # Try CDP endpoint
            try:
                c = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
                c.request('GET', '/json')
                r = c.getresponse()
                body = r.read(2000)
                if r.status == 200:
                    targets = json.loads(body)
                    print(f"  CDP on port {port}: {len(targets)} targets")
                    for t in targets[:3]:
                        print(f"    title={t.get('title','')} type={t.get('type','')} url={t.get('url','')[:60]}")
                    cdp_port = port
                    break
                else:
                    print(f"  port {port}: HTTP {r.status}")
            except Exception as e:
                print(f"  port {port}: not CDP ({e})")
        s.close()
    except: pass

if not cdp_port:
    print("  No CDP port found")

# ── 2. gRPC-Web response with full header reading ────────────────────────────
print("\n=== 2. gRPC-Web InitializeCascadePanelState - full response ===")
HOST = 'server.codeium.com'
PATH = '/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState'

def vi(n):
    out = []
    while n > 0x7F: out.append((n & 0x7F)|0x80); n >>= 7
    out.append(n & 0x7F); return bytes(out)
def fs(no, s):
    b = s.encode() if isinstance(s, str) else s
    return vi((no<<3)|2) + vi(len(b)) + b
def fm(no, m): return vi((no<<3)|2) + vi(len(m)) + m

meta = fs(1,'windsurf') + fs(7,'1.9577.43') + fs(3,'windsurf') + fs(4,api_key)

ctx = ssl.create_default_context()
conn = http.client.HTTPSConnection(HOST, 443, timeout=20, context=ctx)
body = b'\x00' + struct.pack('>I', len(meta)) + meta
headers = {
    'Content-Type': 'application/grpc-web+proto',
    'Accept': 'application/grpc-web+proto, application/grpc-web',
    'X-Grpc-Web': '1',
    'Authorization': f'Bearer {api_key}',
    'User-Agent': 'windsurf/1.9577.43',
    'X-User-Agent': 'grpc-python/1.56.0 grpc-c/31.0.0 (windows; chttp2)',
}
conn.request('POST', PATH, body, headers)
r = conn.getresponse()
print(f"  HTTP {r.status}")
print(f"  All headers:")
for k, v in r.headers.items():
    print(f"    {k}: {v}")
# Read response with timeout
import select
data = b''
raw_conn = r.fp  # underlying file
try:
    while True:
        chunk = r.read(4096)
        if not chunk: break
        data += chunk
        print(f"  read chunk: {len(chunk)} bytes")
except Exception as e:
    print(f"  read error: {e}")
print(f"  Total response body: {len(data)} bytes")
if data:
    print(f"  hex: {data[:200].hex()}")

# ── 3. Read LS process memory for cascade session ────────────────────────────
print("\n=== 3. Search LS memory for cascade session ID ===")
k32 = ctypes.windll.kernel32
nt  = ctypes.windll.ntdll

def open_proc(pid):
    return k32.OpenProcess(0x0010|0x0400, False, pid)

def read_mem(h, addr, size):
    buf = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t(0)
    ok = k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(read))
    return buf.raw[:read.value] if ok else None

def find_pattern_in_proc(pid, pattern, max_bytes=50*1024*1024):
    """Search for a pattern in process memory"""
    h = open_proc(pid)
    if not h: return []
    found = []
    try:
        # Walk memory regions
        addr = 0
        class MEMORY_BASIC_INFORMATION(ctypes.Structure):
            _fields_ = [('BaseAddress', ctypes.c_void_p), ('AllocationBase', ctypes.c_void_p),
                        ('AllocationProtect', ctypes.wintypes.DWORD), ('RegionSize', ctypes.c_size_t),
                        ('State', ctypes.wintypes.DWORD), ('Protect', ctypes.wintypes.DWORD),
                        ('Type', ctypes.wintypes.DWORD)]
        mbi = MEMORY_BASIC_INFORMATION()
        total_read = 0
        while True:
            size = ctypes.sizeof(mbi)
            ret = ctypes.windll.kernel32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), size)
            if not ret: break
            # Only search committed, readable memory
            MEM_COMMIT = 0x1000
            PAGE_READABLE = 0x02|0x04|0x20|0x40
            if (mbi.State == MEM_COMMIT and (mbi.Protect & 0xFF) in [0x02,0x04,0x20,0x40,0x80,0x10]):
                region_size = min(mbi.RegionSize, 4*1024*1024)  # cap at 4MB per region
                data_chunk = read_mem(h, mbi.BaseAddress, region_size)
                if data_chunk:
                    idx = 0
                    while True:
                        idx = data_chunk.find(pattern, idx)
                        if idx < 0: break
                        ctx_start = max(0, idx-50)
                        ctx = data_chunk[ctx_start:idx+200]
                        found.append((mbi.BaseAddress + idx, ctx))
                        idx += 1
                        if len(found) > 5: break
                total_read += region_size
                if total_read > max_bytes: break
            addr = (mbi.BaseAddress or 0) + (mbi.RegionSize or 1)
            if addr >= 0x7FFFFFFFFFFF: break
    finally:
        k32.CloseHandle(h)
    return found

# Search for cascade-related strings in LS process
LS_PID = 31872  # PID 31872 uses port 57407
print(f"  Searching PID {LS_PID} for 'cascade'...")
cascade_hits = find_pattern_in_proc(LS_PID, b'cascade', max_bytes=20*1024*1024)
print(f"  Found {len(cascade_hits)} hits")
for addr, ctx in cascade_hits[:5]:
    readable = ''.join(chr(b) if 32 <= b < 127 else '.' for b in ctx)
    print(f"  @{addr:x}: {readable[:150]}")

# Search for UUID patterns (cascade session IDs)
print(f"\n  Searching for UUID patterns (session IDs)...")
uuid_pat = re.compile(b'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
# Quick search - just look for cascade context
for pattern in [b'cascade_id', b'cascadeId', b'sessionId', b'initializeCascade']:
    hits2 = find_pattern_in_proc(LS_PID, pattern.lower(), max_bytes=10*1024*1024)
    if hits2:
        print(f"  '{pattern.decode()}': {len(hits2)} hits")
        for addr, ctx in hits2[:2]:
            # Look for UUID near the pattern
            uuids = uuid_pat.findall(ctx)
            if uuids:
                print(f"    UUID near pattern: {uuids[:3]}")

# ── 4. Try CDP if found ─────────────────────────────────────────────────────
if cdp_port:
    print(f"\n=== 4. CDP on port {cdp_port} - extract cascade session ===")
    try:
        c = http.client.HTTPConnection('127.0.0.1', cdp_port, timeout=5)
        c.request('GET', '/json')
        r2 = c.getresponse()
        targets = json.loads(r2.read())
        ext_target = next((t for t in targets if 'Extension' in t.get('type','') 
                          or 'background' in t.get('url','').lower()), None)
        if ext_target:
            print(f"  Extension target: {ext_target.get('webSocketDebuggerUrl','')}")
    except Exception as ex:
        print(f"  CDP error: {ex}")
