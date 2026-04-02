"""scan_pid_memory.py — 全内存扫描找 CSRF 和 LS 端口"""
import ctypes, ctypes.wintypes, re

PROCESS_VM_READ = 0x10
PROCESS_QUERY_INFORMATION = 0x400
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01

k32 = ctypes.windll.kernel32

class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('BaseAddress', ctypes.c_void_p),
        ('AllocationBase', ctypes.c_void_p),
        ('AllocationProtect', ctypes.wintypes.DWORD),
        ('PartitionId', ctypes.wintypes.WORD),
        ('RegionSize', ctypes.c_size_t),
        ('State', ctypes.wintypes.DWORD),
        ('Protect', ctypes.wintypes.DWORD),
        ('Type', ctypes.wintypes.DWORD),
    ]

UUID_RE = re.compile(rb'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
CSRF_RE = re.compile(rb'WINDSURF_CSRF_TOKEN[\x00=]([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', re.IGNORECASE)
PORT_RE = re.compile(rb'LS_PORT[\x00=](\d{4,5})', re.IGNORECASE)

TARGET_PIDS = [46836]

for pid in TARGET_PIDS:
    h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        print(f"Cannot open PID {pid}"); continue
    
    print(f"Scanning PID {pid}...")
    found_csrf = set()
    found_ports = set()
    
    addr = 0
    mbi = MEMORY_BASIC_INFORMATION()
    total_scanned = 0
    
    while True:
        ret = k32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi))
        if not ret: break
        
        if (mbi.State == MEM_COMMIT and 
            mbi.Protect != PAGE_NOACCESS and
            mbi.Protect != 0 and
            mbi.RegionSize < 50 * 1024 * 1024):  # Skip huge regions
            
            buf = ctypes.create_string_buffer(mbi.RegionSize)
            read = ctypes.c_size_t(0)
            if k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, mbi.RegionSize, ctypes.byref(read)):
                data = buf.raw[:read.value]
                total_scanned += len(data)
                
                for m in CSRF_RE.finditer(data):
                    found_csrf.add(m.group(1).decode('ascii', 'ignore'))
                
                for m in PORT_RE.finditer(data):
                    found_ports.add(m.group(1).decode('ascii', 'ignore'))
                
                # Also look for UUID near "csrf" keyword (case insensitive)
                for m in re.finditer(rb'(?:csrf|CSRF).{0,50}?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', data, re.IGNORECASE):
                    found_csrf.add(m.group(1).decode('ascii', 'ignore'))
        
        addr = (addr + mbi.RegionSize) & 0xFFFFFFFFFFFFFFFF
        if addr >= 0x7FFFFFFFFFFF: break
    
    k32.CloseHandle(h)
    
    print(f"  Scanned: {total_scanned/1024/1024:.1f} MB")
    print(f"  CSRF tokens: {found_csrf}")
    print(f"  LS ports: {found_ports}")
