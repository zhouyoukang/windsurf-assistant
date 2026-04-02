import sys,io,ctypes,struct,re,sqlite3,json,requests,subprocess
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8',errors='replace')

# Get LS PID + port
r=subprocess.run(['tasklist','/FI','IMAGENAME eq language_server_windows_x64.exe','/FO','CSV','/NH'],capture_output=True,text=True)
pid=None
for line in r.stdout.strip().splitlines():
    parts=line.strip().strip('"').split('","')
    if len(parts)>=2:
        try: pid=int(parts[1]); break
        except: pass
print(f"LS PID: {pid}")

r2=subprocess.run(['netstat','-ano'],capture_output=True)
net=r2.stdout.decode('gbk',errors='replace')
ports=[]
for line in net.splitlines():
    if 'LISTENING' in line:
        p=line.split()
        if len(p)>=5 and p[-1]==str(pid):
            try:
                pt=int(p[1].split(':')[1])
                if pt>50000: ports.append(pt)
            except: pass
print(f"LS ports: {ports}")

# Read CSRF via PEB
class PBI(ctypes.Structure):
    _fields_=[('ExitStatus',ctypes.c_long),('PebBaseAddress',ctypes.c_void_p),
              ('AffinityMask',ctypes.c_void_p),('BasePriority',ctypes.c_long),
              ('UniqueProcessId',ctypes.c_void_p),('InheritedUniq',ctypes.c_void_p)]
def rp(h,a):
    b=ctypes.create_string_buffer(8); n=ctypes.c_size_t(0)
    ctypes.windll.kernel32.ReadProcessMemory(h,ctypes.c_void_p(a),b,8,ctypes.byref(n))
    return struct.unpack('<Q',b.raw)[0] if n.value==8 else 0
def rb(h,a,s):
    b=ctypes.create_string_buffer(s); n=ctypes.c_size_t(0)
    ctypes.windll.kernel32.ReadProcessMemory(h,ctypes.c_void_p(a),b,s,ctypes.byref(n))
    return b.raw[:n.value]

h=ctypes.windll.kernel32.OpenProcess(0x10|0x400|0x1000,False,pid)
pbi=PBI()
ctypes.windll.ntdll.NtQueryInformationProcess(h,0,ctypes.byref(pbi),ctypes.sizeof(pbi),None)
peb=pbi.PebBaseAddress; pp=rp(h,peb+0x20); ep=rp(h,pp+0x80)
sr=rb(h,pp+0x3F0,8); es=min(struct.unpack('<Q',sr)[0] if len(sr)==8 else 0x10000,0x80000)
if es==0: es=0x10000
env=rb(h,ep,es).decode('utf-16-le',errors='replace')
ctypes.windll.kernel32.CloseHandle(h)
m=re.search(r'WINDSURF_CSRF_TOKEN=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',env,re.I)
csrf=m.group(1) if m else None
print(f"CSRF: {csrf}")

# Test init
if ports and csrf:
    con=sqlite3.connect(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb')
    key=json.loads(con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()[0]).get('apiKey','')
    con.close()
    meta={'ideName':'Windsurf','ideVersion':'1.108.2','extensionVersion':'3.14.2','apiKey':key,'locale':'en-US','os':'win32','url':'https://server.codeium.com'}
    b=json.dumps({'metadata':meta,'workspaceTrusted':True}).encode()
    for port in ports:
        try:
            r3=requests.post(f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState',
                data=b'\x00'+struct.pack('>I',len(b))+b,
                headers={'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json','x-codeium-csrf-token':csrf,'x-grpc-web':'1'},
                timeout=4,stream=True)
            raw=b''.join(r3.iter_content(chunk_size=None))
            trailer=''
            pos=0
            while pos+5<=len(raw):
                fl=raw[pos];n=struct.unpack('>I',raw[pos+1:pos+5])[0];pos+=5;chunk=raw[pos:pos+n];pos+=n
                if fl==0x80: trailer=chunk.decode('utf-8','replace')
            print(f"port={port}: HTTP={r3.status_code} grpc={trailer.strip()[:50]}")
        except Exception as e:
            print(f"port={port}: ERR={e}")
