"""find_csrf_v2.py — 多策略找 CSRF token"""
import subprocess, re, ctypes, struct, requests, json, socket, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)

# 1. 找所有 Windsurf LS 端口
def scan_ports():
    active = []
    for p in range(50000, 65536):
        try:
            s = socket.socket(); s.settimeout(0.1)
            if s.connect_ex(('127.0.0.1', p)) == 0:
                active.append(p)
            s.close()
        except: pass
    return active

# Fast scan of known range
print("=== 端口扫描 ===")
candidates = []
for p in [64956, 64958, 64965, 64960, 64950, 64940, 57407, 57400, 60000, 62000]:
    try:
        s = socket.socket(); s.settimeout(0.3)
        if s.connect_ex(('127.0.0.1', p)) == 0:
            candidates.append(p)
            print(f"  Port {p}: OPEN")
        s.close()
    except: pass

# 2. 获取每个端口的 owning PID 和命令行
print("\n=== 端口 -> 进程信息 ===")
port_info = {}
for port in candidates:
    r = subprocess.run(
        ['powershell', '-NoProfile', '-Command',
         f'$p=(Get-NetTCPConnection -LocalPort {port} -State Listen -EA 0 | Select-Object -First 1).OwningProcess;'
         f'if($p){{$proc=Get-WmiObject -Class Win32_Process -Filter "ProcessId=$p" -EA 0;'
         f'"PID=$p Name=$($proc.Name) CMD=$($proc.CommandLine)"}}'],
        capture_output=True, text=True, timeout=10
    )
    info = r.stdout.strip()
    print(f"  Port {port}: {info[:200]}")
    port_info[port] = info
    
    # Look for UUIDs in command line (CSRF might be there)
    uuids = UUID_RE.findall(info)
    if uuids:
        print(f"    UUIDs found: {uuids}")

# 3. 扫描进程内存 (正确的 MBI 结构)
print("\n=== 内存扫描 ===")
CSRF_RE = re.compile(rb'WINDSURF_CSRF_TOKEN[\x00=]([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', re.I)
CSRF_RE2 = re.compile(rb'csrf.token[\x00\s=:]+([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', re.I)

class MBI(ctypes.Structure):
    _fields_ = [
        ('BaseAddress',       ctypes.c_void_p),
        ('AllocationBase',    ctypes.c_void_p),
        ('AllocationProtect', ctypes.c_ulong),
        ('PartitionId',       ctypes.c_ushort),
        ('_pad',              ctypes.c_ushort),
        ('RegionSize',        ctypes.c_size_t),
        ('State',             ctypes.c_ulong),
        ('Protect',           ctypes.c_ulong),
        ('Type',              ctypes.c_ulong),
    ]

def scan_pid(pid):
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x10|0x400, False, pid)
    if not h: return set()
    found = set()
    mbi = MBI(); addr = 0
    while True:
        if not k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)): break
        if mbi.State == 0x1000 and mbi.Protect not in (1,0) and 0 < mbi.RegionSize <= 100*1024*1024:
            buf = ctypes.create_string_buffer(mbi.RegionSize)
            read = ctypes.c_size_t(0)
            if k32.ReadProcessMemory(h, ctypes.c_void_p(mbi.BaseAddress), buf, mbi.RegionSize, ctypes.byref(read)):
                data = buf.raw[:read.value]
                for m in CSRF_RE.finditer(data):
                    found.add(('DIRECT', m.group(1).decode('ascii','ignore')))
                for m in CSRF_RE2.finditer(data):
                    found.add(('NEAR', m.group(1).decode('ascii','ignore')))
        addr = (addr + mbi.RegionSize) & 0xFFFFFFFFFFFFFFFF
        if addr >= 0x7FFFFFFFFFFF: break
    k32.CloseHandle(h)
    return found

# Get all Windsurf PIDs
r = subprocess.run(
    ['powershell', '-NoProfile', '-Command',
     'Get-Process | Where-Object {$_.Name -match "windsurf|Windsurf"} | '
     'Select-Object Id,Name | ConvertTo-Csv -NoTypeInformation'],
    capture_output=True, text=True, timeout=8
)
ws_pids = []
for line in r.stdout.strip().splitlines()[1:]:
    parts = line.strip().strip('"').split('","')
    if len(parts) == 2:
        try: ws_pids.append((int(parts[0]), parts[1]))
        except: pass

print(f"Windsurf PIDs: {ws_pids}")

for pid, name in ws_pids:
    tokens = scan_pid(pid)
    if tokens:
        print(f"  PID {pid} ({name}): {tokens}")

# 4. 试验哪个 CSRF 对哪个端口有效
print("\n=== CSRF 有效性测试 ===")
db_path = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
import sqlite3
con = sqlite3.connect(db_path)
key = json.loads(con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()[0]).get('apiKey','')
con.close()

test_csrfs = ['38a7a689-1e2a-41ff-904b-eefbc9dcacfe']  # known old one

for port in candidates:
    for csrf in test_csrfs:
        meta = {"ideName":"Windsurf","ideVersion":"1.108.2","extensionVersion":"3.14.2",
                "apiKey":key,"locale":"en-US","os":"win32","url":"https://server.codeium.com"}
        body = json.dumps({"metadata":meta,"workspaceTrusted":True}).encode()
        hdr = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
               'x-codeium-csrf-token':csrf,'x-grpc-web':'1'}
        try:
            r = requests.post(f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState',
                              data=b'\x00'+struct.pack('>I',len(body))+body, headers=hdr, timeout=5, stream=True)
            raw = b''.join(r.iter_content(chunk_size=None))
            status = r.status_code
            # find grpc-status in trailer
            trailer = ''
            pos = 0
            while pos+5 <= len(raw):
                fl=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
                chunk=raw[pos:pos+n]; pos+=n
                if fl==0x80: trailer = chunk.decode('utf-8','replace')
            print(f"  port={port} csrf={csrf[:8]}... HTTP={status} trailer={trailer[:50]}")
        except Exception as e:
            print(f"  port={port} csrf={csrf[:8]}... ERROR: {e}")
