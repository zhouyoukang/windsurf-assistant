"""scan_all_csrf.py — 扫描所有进程，找 WINDSURF_CSRF_TOKEN + LS 端口"""
import ctypes, re, struct, json, requests
from ctypes import wintypes

PROCESS_VM_READ = 0x10
PROCESS_QUERY_INFORMATION = 0x400
TH32CS_SNAPPROCESS = 0x2

k32 = ctypes.windll.kernel32
nt = ctypes.windll.ntdll

class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]

def all_pids():
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    pe = PROCESSENTRY32(); pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
    pids = []
    if k32.Process32First(snap, ctypes.byref(pe)):
        while True:
            pids.append((pe.th32ProcessID, pe.szExeFile.decode('utf-8','replace')))
            if not k32.Process32Next(snap, ctypes.byref(pe)): break
    k32.CloseHandle(snap)
    return pids

def get_csrf(pid):
    h = k32.OpenProcess(PROCESS_VM_READ|PROCESS_QUERY_INFORMATION, False, pid)
    if not h: return None
    try:
        pbi = ctypes.create_string_buffer(48)
        nt.NtQueryInformationProcess(h, 0, pbi, 48, ctypes.c_ulong(0))
        peb = int.from_bytes(pbi.raw[8:16], 'little')
        if not peb: return None
        
        b1 = ctypes.create_string_buffer(0x400)
        r1 = ctypes.c_size_t(0)
        if not k32.ReadProcessMemory(h, ctypes.c_void_p(peb), b1, 0x400, ctypes.byref(r1)): return None
        pp = int.from_bytes(b1.raw[0x20:0x28], 'little')
        
        b2 = ctypes.create_string_buffer(0x500)
        r2 = ctypes.c_size_t(0)
        if not k32.ReadProcessMemory(h, ctypes.c_void_p(pp), b2, 0x500, ctypes.byref(r2)): return None
        ea = int.from_bytes(b2.raw[0x80:0x88], 'little')
        
        b3 = ctypes.create_string_buffer(65536)
        r3 = ctypes.c_size_t(0)
        k32.ReadProcessMemory(h, ctypes.c_void_p(ea), b3, 65536, ctypes.byref(r3))
        raw = b3.raw[:r3.value]
        
        results = {}
        try:
            s = raw.decode('utf-16-le', errors='replace')
            for entry in s.split('\x00'):
                if '=' in entry:
                    k, _, v = entry.partition('=')
                    results[k.strip()] = v
        except: pass
        
        csrf = results.get('WINDSURF_CSRF_TOKEN', '')
        if not csrf:
            m = re.search(rb'WINDSURF_CSRF_TOKEN\x00=\x00([a-f0-9-]{36})', raw)
            if m: csrf = m.group(1).decode()
        
        return csrf if csrf else None
    except: return None
    finally: k32.CloseHandle(h)

print("Scanning all processes for WINDSURF_CSRF_TOKEN...")
pids = all_pids()
found = {}
for pid, name in pids:
    if pid <= 4: continue
    try:
        csrf = get_csrf(pid)
        if csrf:
            found[pid] = (name, csrf)
            print(f"  PID {pid:6d} ({name:30s}): CSRF={csrf}")
    except: pass

print(f"\nFound {len(found)} processes with CSRF token")

# Now test which port each CSRF works on
KEY = json.load(open(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\cascade-auth.json')).get('apiKey','')
META = {"ideName":"Windsurf","ideVersion":"1.108.2","extensionVersion":"3.14.2",
        "extensionName":"Windsurf","extensionPath":r"D:\Windsurf\resources\app\extensions\windsurf",
        "apiKey":KEY,"locale":"en-US","os":"win32","url":"https://server.codeium.com"}

seen_csrf = set()
for pid, (name, csrf) in found.items():
    if csrf in seen_csrf: continue
    seen_csrf.add(csrf)
    for port in [64956, 64958, 64965]:
        HDR = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
               'x-codeium-csrf-token':csrf,'x-grpc-web':'1'}
        b = json.dumps({'metadata':META,'source':'CORTEX_TRAJECTORY_SOURCE_USER'}).encode()
        try:
            r = requests.post(f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/StartCascade',
                              data=b'\x00'+struct.pack('>I',len(b))+b, headers=HDR, timeout=4, stream=True)
            raw = b''.join(r.iter_content(chunk_size=None))
            if r.status_code == 200 and len(raw) > 20:
                cid = re.search(rb'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', raw)
                print(f"  ✅ PORT {port} PID {pid} CSRF {csrf[:8]}: cascadeId={cid.group(0).decode() if cid else 'found'}")
        except: pass
