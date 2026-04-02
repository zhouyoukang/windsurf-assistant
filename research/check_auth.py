"""check_auth.py — 全面检查 Windsurf 认证数据"""
import sqlite3, json, subprocess, ctypes, re, io, sys, struct
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'

# 1. Dump all auth-related keys from state.vscdb
print("=== state.vscdb auth keys ===")
con = sqlite3.connect(DB)
rows = con.execute("SELECT key, value FROM ItemTable").fetchall()
con.close()
for key, val in rows:
    kl = key.lower()
    if any(x in kl for x in ['auth','token','key','api','session','user','account','login','cred']):
        try:
            v = json.loads(val)
            print(f"  {key}: {json.dumps(v)[:200]}")
        except:
            print(f"  {key}: {str(val)[:200]}")
print()

# 2. Check who owns ports 61469, 61476, 65444
print("=== Port owners ===")
r = subprocess.run(['netstat','-ano'], capture_output=True)
net = r.stdout.decode('gbk', errors='replace')
for line in net.splitlines():
    if 'LISTENING' in line and '127.0.0.1' in line:
        parts = line.split()
        try:
            port = int(parts[1].split(':')[1])
            pid  = parts[-1]
            if port > 50000:
                ps = subprocess.run(['tasklist','/FI',f'PID eq {pid}','/FO','CSV','/NH'],
                                    capture_output=True, text=True, errors='replace')
                print(f"  {port} PID={pid}: {ps.stdout.strip()[:80]}")
        except: pass
print()

# 3. UTF-16LE CSRF search in the LS process
print("=== UTF-16LE CSRF scan ===")
TARGET_KEY = 'WINDSURF_CSRF_TOKEN='
TARGET_UTF16 = TARGET_KEY.encode('utf-16-le')
UUID_ASCII = re.compile(rb'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)

class MBI(ctypes.Structure):
    _fields_ = [('BaseAddress',ctypes.c_void_p),('AllocationBase',ctypes.c_void_p),
                ('AllocationProtect',ctypes.c_ulong),('PartitionId',ctypes.c_ushort),
                ('_pad',ctypes.c_ushort),('RegionSize',ctypes.c_size_t),
                ('State',ctypes.c_ulong),('Protect',ctypes.c_ulong),('Type',ctypes.c_ulong)]

def scan_pid_full(pid):
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x10|0x400, False, pid)
    if not h: return []
    results = []
    mbi = MBI(); addr = 0
    while True:
        if not k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)): break
        if mbi.State==0x1000 and mbi.Protect not in (1,0) and 0<mbi.RegionSize<=30*1024*1024:
            buf = ctypes.create_string_buffer(mbi.RegionSize)
            read = ctypes.c_size_t(0)
            if k32.ReadProcessMemory(h, ctypes.c_void_p(mbi.BaseAddress), buf, mbi.RegionSize, ctypes.byref(read)):
                data = buf.raw[:read.value]
                # ASCII search
                for m in re.finditer(rb'WINDSURF_CSRF_TOKEN[\x00=]([0-9a-f\-]{36})', data, re.I):
                    results.append(('ascii', m.group(1).decode('ascii','ignore')))
                # UTF-16LE search
                idx = data.find(TARGET_UTF16)
                if idx >= 0:
                    # extract UUID after the '=' in UTF-16LE (36 chars * 2 bytes = 72 bytes)
                    uuid_utf16 = data[idx+len(TARGET_UTF16):idx+len(TARGET_UTF16)+72]
                    try:
                        uuid_str = uuid_utf16.decode('utf-16-le', errors='replace')
                        results.append(('utf16', uuid_str))
                    except: pass
                # Broad search: any UUID near "csrf" (case insensitive)
                for m in re.finditer(rb'(?:csrf|CSRF).{0,100}([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', data, re.I):
                    results.append(('broad', m.group(1).decode('ascii','ignore')))
        addr = (addr+mbi.RegionSize)&0xFFFFFFFFFFFFFFFF
        if addr>=0x7FFFFFFFFFFF or len(results)>=3: break
    k32.CloseHandle(h)
    return results

# Get port-owning PIDs
for port in [61469, 61476, 65444]:
    r2 = subprocess.run(['powershell','-NoProfile','-Command',
        f'(Get-NetTCPConnection -LocalPort {port} -State Listen -EA 0 | Select-Object -First 1).OwningProcess'],
        capture_output=True, text=True, timeout=6)
    pid_s = r2.stdout.strip()
    if pid_s.isdigit():
        results = scan_pid_full(int(pid_s))
        print(f"  Port {port} PID {pid_s}: {results[:5]}")

# Also check if Windsurf has a codeium config file
print("\n=== Codeium config files ===")
import os, glob
dirs = [
    r'C:\Users\Administrator\.codeium',
    r'C:\Users\Administrator\AppData\Roaming\Windsurf',
    r'C:\Users\Administrator\AppData\Local\Windsurf',
]
for d in dirs:
    for f in glob.glob(os.path.join(d,'**','*.json'), recursive=True)[:20]:
        try:
            with open(f,'r',encoding='utf-8',errors='ignore') as fp:
                c = fp.read(2000)
            if any(x in c.lower() for x in ['api_key','apikey','token','auth']):
                print(f"  {f}: {c[:300]}")
        except: pass
