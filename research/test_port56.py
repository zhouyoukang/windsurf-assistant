"""test_port56.py — 直接测试 port 64956 + 所有可能 CSRF"""
import re, ctypes, json, struct, sqlite3, time, requests, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PORT = 64956
DB   = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'

def get_key():
    con = sqlite3.connect(DB)
    k = json.loads(con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()[0]).get('apiKey','')
    con.close()
    return k

META_BASE = {"ideName":"Windsurf","ideVersion":"1.108.2","extensionVersion":"3.14.2",
             "extensionName":"Windsurf","extensionPath":r"D:\Windsurf\resources\app\extensions\windsurf",
             "locale":"en-US","os":"win32","url":"https://server.codeium.com"}

def call(port, csrf, body_dict, method, timeout=6):
    b = json.dumps(body_dict).encode()
    hdr = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
           'x-codeium-csrf-token':csrf,'x-grpc-web':'1'}
    r = requests.post(f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/{method}',
                      data=b'\x00'+struct.pack('>I',len(b))+b, headers=hdr, timeout=timeout, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    return r.status_code, raw

# ── Step 1: collect all UUIDs from Windsurf process memory ──────────────
print("=== Collecting UUIDs from all Windsurf processes ===")
import subprocess
UUID_RE  = re.compile(rb'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
CSRF_CTX = re.compile(rb'(?:CSRF|csrf|xsrf|x-codeium).{0,30}([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', re.I)

class MBI(ctypes.Structure):
    _fields_ = [('BaseAddress',ctypes.c_void_p),('AllocationBase',ctypes.c_void_p),
                ('AllocationProtect',ctypes.c_ulong),('PartitionId',ctypes.c_ushort),
                ('_pad',ctypes.c_ushort),('RegionSize',ctypes.c_size_t),
                ('State',ctypes.c_ulong),('Protect',ctypes.c_ulong),('Type',ctypes.c_ulong)]

def scan_pid(pid):
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x10|0x400, False, pid)
    if not h: return []
    found = []
    mbi = MBI(); addr = 0
    while True:
        if not k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)): break
        if mbi.State==0x1000 and mbi.Protect not in (1,0) and 0<mbi.RegionSize<=20*1024*1024:
            buf = ctypes.create_string_buffer(mbi.RegionSize)
            read = ctypes.c_size_t(0)
            if k32.ReadProcessMemory(h, ctypes.c_void_p(mbi.BaseAddress), buf, mbi.RegionSize, ctypes.byref(read)):
                data = buf.raw[:read.value]
                for m in CSRF_CTX.finditer(data):
                    token = m.group(1).decode('ascii','ignore')
                    if token not in found: found.append(token)
        addr = (addr+mbi.RegionSize)&0xFFFFFFFFFFFFFFFF
        if addr>=0x7FFFFFFFFFFF: break
    k32.CloseHandle(h)
    return found

# Get port owner PID
r = subprocess.run(['powershell','-NoProfile','-Command',
    f'(Get-NetTCPConnection -LocalPort {PORT} -State Listen -EA 0 | Select-Object -First 1).OwningProcess'],
    capture_output=True, text=True, timeout=6)
owner_pid = int(r.stdout.strip()) if r.stdout.strip().isdigit() else None
print(f"Port {PORT} owner PID: {owner_pid}")

# Scan pids
r2 = subprocess.run(['powershell','-NoProfile','-Command',
    'Get-Process | Where-Object {$_.Name -match "[Ww]indsurf"} | Select-Object -ExpandProperty Id'],
    capture_output=True, text=True, timeout=8)
ws_pids = [int(x) for x in r2.stdout.strip().split() if x.strip().isdigit()]
print(f"Windsurf PIDs: {ws_pids}")

csrf_candidates = ['38a7a689-1e2a-41ff-904b-eefbc9dcacfe']  # always try known one first
for pid in ([owner_pid] if owner_pid else []) + ws_pids:
    tokens = scan_pid(pid)
    for t in tokens:
        if t not in csrf_candidates:
            csrf_candidates.append(t)
    if tokens:
        print(f"  PID {pid}: found CSRF candidates {tokens[:3]}")

print(f"\nTotal CSRF candidates: {len(csrf_candidates)}")

# ── Step 2: try each CSRF against port 64956 ────────────────────────────
print(f"\n=== Testing CSRFs against port {PORT} ===")
key = get_key()
meta = {**META_BASE, 'apiKey': key}

for csrf in csrf_candidates[:10]:
    status, raw = call(PORT, csrf, {"metadata":meta,"workspaceTrusted":True}, "InitializeCascadePanelState")
    # parse trailer
    trailer = ''
    pos=0
    while pos+5<=len(raw):
        fl=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        chunk=raw[pos:pos+n]; pos+=n
        if fl==0x80: trailer=chunk.decode('utf-8','replace')
    result = f"HTTP={status} trailer={trailer.strip()[:40]}"
    ok = 'grpc-status: 0' in trailer
    print(f"  {'✓' if ok else '✗'} CSRF={csrf[:8]}...  {result}")
    if ok:
        print(f"\n  *** FOUND WORKING CSRF: {csrf} ***")
        # Now test full cascade flow
        meta2 = {**META_BASE, 'apiKey': key}
        call(PORT, csrf, {"metadata":meta2,"workspaceTrusted":True}, "UpdateWorkspaceTrust")
        s, r2 = call(PORT, csrf, {"metadata":meta2,"source":"CORTEX_TRAJECTORY_SOURCE_USER"}, "StartCascade")
        pos2=0; cid=None
        while pos2+5<=len(r2):
            fl=r2[pos2]; n=struct.unpack('>I',r2[pos2+1:pos2+5])[0]; pos2+=5
            chunk=r2[pos2:pos2+n]; pos2+=n
            if fl==0:
                try: cid=json.loads(chunk).get('cascadeId')
                except: pass
        print(f"  cascadeId: {cid}")
        break
