"""find_ls_csrf.py — 找到当前 LS 端口和 CSRF token"""
import subprocess, re, ctypes, struct, io, sys, json, sqlite3, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)
DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'

# Get current WAM key for probing
con = sqlite3.connect(DB)
WAM_KEY = json.loads(con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()[0]).get('apiKey','')
con.close()

# ── Step 1: get all process command lines (maybe CSRF is a CLI arg) ──────
print("=== All process command lines containing 'ls' or 'language' ===")
r = subprocess.run(
    ['powershell', '-NoProfile', '-Command',
     'Get-WmiObject Win32_Process | Where-Object {$_.CommandLine -match "language.server|language_server|ls.exe|windsurf-ls"} | '
     'Select-Object ProcessId,Name,CommandLine | ConvertTo-Csv -NoTypeInformation'],
    capture_output=True, text=True, timeout=15
)
for line in r.stdout.strip().splitlines()[1:]:
    parts = line.strip().strip('"').split('","')
    if len(parts) >= 3:
        pid, name, cmd = parts[0], parts[1], parts[2]
        print(f"  PID={pid} Name={name}")
        print(f"  CMD={cmd[:300]}")
        uuids = UUID_RE.findall(cmd)
        if uuids: print(f"  UUIDs in CMD: {uuids}")
        print()

# ── Step 2: Read env via PEB ──────────────────────────────────────────────
print("=== PEB env reading ===")

class PROCESS_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('ExitStatus',        ctypes.c_long),
        ('PebBaseAddress',    ctypes.c_void_p),
        ('AffinityMask',      ctypes.c_void_p),
        ('BasePriority',      ctypes.c_long),
        ('UniqueProcessId',   ctypes.c_void_p),
        ('InheritedUniq',     ctypes.c_void_p),
    ]

def read_ptr(h, addr):
    buf = ctypes.create_string_buffer(8)
    read = ctypes.c_size_t(0)
    ctypes.windll.kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, 8, ctypes.byref(read))
    return struct.unpack('<Q', buf.raw)[0]

def read_bytes(h, addr, size):
    buf = ctypes.create_string_buffer(size)
    read = ctypes.c_size_t(0)
    ctypes.windll.kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size, ctypes.byref(read))
    return buf.raw[:read.value]

def get_process_env(pid):
    k32  = ctypes.windll.kernel32
    ntdl = ctypes.windll.ntdll
    h = k32.OpenProcess(0x10|0x400|0x1000, False, pid)  # VM_READ|QUERY_INFO|VM_OPERATION
    if not h: return ''
    try:
        pbi = PROCESS_BASIC_INFORMATION()
        ntdl.NtQueryInformationProcess(h, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), None)
        peb = pbi.PebBaseAddress
        # PEB.ProcessParameters at offset 0x20 (64-bit)
        pp = read_ptr(h, peb + 0x20)
        # RTL_USER_PROCESS_PARAMETERS.Environment at offset 0x80 (64-bit)
        env_ptr = read_ptr(h, pp + 0x80)
        # Size at offset 0x3F0
        env_size_raw = read_bytes(h, pp + 0x3F0, 8)
        env_size = min(struct.unpack('<Q', env_size_raw)[0] if env_size_raw else 0x10000, 0x100000)
        if env_size == 0: env_size = 0x10000
        env_data = read_bytes(h, env_ptr, env_size)
        return env_data.decode('utf-16-le', errors='replace')
    except Exception as e:
        return f'[error: {e}]'
    finally:
        k32.CloseHandle(h)

# Get port-owning PIDs for Windsurf-related ports
r2 = subprocess.run(['netstat','-ano'], capture_output=True)
net = r2.stdout.decode('gbk', errors='replace')

for line in net.splitlines():
    if 'LISTENING' in line and '127.0.0.1' in line:
        parts = line.split()
        try:
            port = int(parts[1].split(':')[1])
            pid  = int(parts[-1])
            if port > 50000:
                env = get_process_env(pid)
                if 'CSRF' in env or 'csrf' in env.lower():
                    # Found it!
                    for m in re.finditer(r'WINDSURF_CSRF_TOKEN=([0-9a-f\-]{36})', env, re.I):
                        print(f"  PORT {port} PID {pid}: CSRF={m.group(1)}")
        except: pass

# ── Step 3: Probe each port for LS identity + test with multiple CSRFs ──
print("\n=== Port probe ===")

def probe_port(port, csrf_candidates):
    meta = {'ideName':'Windsurf','ideVersion':'1.108.2','extensionVersion':'3.14.2',
            'apiKey':WAM_KEY,'locale':'en-US','os':'win32','url':'https://server.codeium.com'}
    body = json.dumps({'metadata':meta,'workspaceTrusted':True}).encode()
    for csrf in csrf_candidates:
        try:
            r = requests.post(
                f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState',
                data=b'\x00'+struct.pack('>I',len(body))+body,
                headers={'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
                         'x-codeium-csrf-token':csrf,'x-grpc-web':'1'},
                timeout=3, stream=True)
            raw = b''.join(r.iter_content(chunk_size=None))
            # Find trailer
            trailer = ''
            pos=0
            while pos+5<=len(raw):
                fl=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
                chunk=raw[pos:pos+n]; pos+=n
                if fl==0x80: trailer=chunk.decode('utf-8','replace')
            ok = 'grpc-status: 0' in trailer
            if ok:
                print(f"  PORT {port} CSRF {csrf[:8]}... OK!")
                return csrf
            elif r.status_code == 200:
                print(f"  PORT {port} CSRF {csrf[:8]}... HTTP200 grpc_err: {trailer.strip()[:40]}")
        except Exception as e:
            if 'Connection' not in str(e):
                print(f"  PORT {port} err: {e}")
    return None

# test ports with various CSRF candidates
csrf_cands = ['38a7a689-1e2a-41ff-904b-eefbc9dcacfe',
              '00000000-0000-0000-0000-000000000000']  # will be extended
for line in net.splitlines():
    if 'LISTENING' in line and '127.0.0.1' in line:
        parts = line.split()
        try:
            port = int(parts[1].split(':')[1])
            if port > 50000:
                probe_port(port, csrf_cands)
        except: pass
