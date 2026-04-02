import subprocess, re, ctypes, struct, requests, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

UUID_RE = re.compile(rb'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')

# 1. 找所有监听端口 + 进程名
print("=== 监听端口 (>50000) ===")
r = subprocess.run(
    ['powershell','-Command',
     'Get-NetTCPConnection -State Listen | Where-Object {$_.LocalPort -gt 50000} | '
     'ForEach-Object { $n=(Get-Process -Id $_.OwningProcess -EA 0).Name; '
     '"$($_.LocalPort)|$($_.OwningProcess)|$n" } | Sort-Object'],
    capture_output=True, text=True, timeout=15
)
ws_ports = []
for line in r.stdout.strip().splitlines():
    if '|' in line:
        parts = line.split('|')
        if len(parts)==3:
            port, pid, name = parts
            print(f"  port={port.strip()} pid={pid.strip()} name={name.strip()}")
            if any(x in name.lower() for x in ['windsurf','node','electron','helper']):
                ws_ports.append((int(port.strip()), int(pid.strip())))

# 2. 对每个候选端口扫描 CSRF
print("\n=== CSRF 扫描 ===")

def scan_pid_csrf(pid):
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x0010 | 0x0400, False, pid)
    if not h:
        return None

    class MBI(ctypes.Structure):
        _fields_ = [
            ("BaseAddress",       ctypes.c_void_p),
            ("AllocationBase",    ctypes.c_void_p),
            ("AllocationProtect", ctypes.c_ulong),
            ("__pad",             ctypes.c_ulong),
            ("RegionSize",        ctypes.c_size_t),
            ("State",             ctypes.c_ulong),
            ("Protect",           ctypes.c_ulong),
            ("Type",              ctypes.c_ulong),
        ]

    mbi = MBI()
    addr = 0
    found = []
    scan_limit = 200  # 最多扫 200 个区域避免超时

    for _ in range(scan_limit * 1000):
        ret = k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi))
        if ret == 0:
            break
        size = mbi.RegionSize
        if mbi.State == 0x1000 and 0 < size <= 0x2000000:
            buf = (ctypes.c_uint8 * size)()
            read = ctypes.c_size_t(0)
            ok = k32.ReadProcessMemory(h, ctypes.c_void_p(mbi.BaseAddress), buf, size, ctypes.byref(read))
            if ok and read.value > 0:
                data = bytes(buf[:read.value])
                if b'WINDSURF_CSRF_TOKEN' in data or b'CSRF' in data:
                    for m in UUID_RE.finditer(data):
                        ctx = data[max(0,m.start()-50):m.start()]
                        if b'CSRF' in ctx or b'csrf' in ctx:
                            found.append(m.group().decode())
                            if len(found) >= 3:
                                break
        addr = (mbi.BaseAddress or 0) + size
        if addr > 0x7FFFFFFFFFFF or found:
            break

    k32.CloseHandle(h)
    return found[0] if found else None

for port, pid in ws_ports:
    token = scan_pid_csrf(pid)
    print(f"  port={port} pid={pid}: CSRF={token}")

# 3. 测试 port 64956 with fallback CSRF
print("\n=== 测试 port 64956 CSRF 有效性 ===")
import sqlite3, json
con = sqlite3.connect(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb')
key = json.loads(con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()[0]).get('apiKey','')
con.close()

for test_csrf in ['38a7a689-1e2a-41ff-904b-eefbc9dcacfe']:
    meta = {"ideName":"Windsurf","ideVersion":"1.108.2","extensionVersion":"3.14.2",
            "apiKey":key,"locale":"en-US","os":"win32","url":"https://server.codeium.com"}
    body = json.dumps({"metadata":meta,"workspaceTrusted":True}).encode()
    hdr = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
           'x-codeium-csrf-token':test_csrf,'x-grpc-web':'1'}
    try:
        r = requests.post('http://127.0.0.1:64956/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState',
                          data=b'\x00'+struct.pack('>I',len(body))+body, headers=hdr, timeout=5, stream=True)
        raw = b''.join(r.iter_content(chunk_size=None))
        print(f"  CSRF={test_csrf[:8]}... -> HTTP {r.status_code}, {len(raw)}b response")
        # Check for grpc-status in trailer
        pos=0
        while pos+5<=len(raw):
            fl=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
            chunk=raw[pos:pos+n]; pos+=n
            if fl==0x80:
                print(f"  Trailer: {chunk[:80]}")
    except Exception as e:
        print(f"  CSRF={test_csrf[:8]}... -> ERROR: {e}")
