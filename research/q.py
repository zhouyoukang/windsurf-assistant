import requests, json, struct, sqlite3, subprocess, ctypes, re, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

con = sqlite3.connect(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb')
key = json.loads(con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()[0]).get('apiKey','')
con.close()
print(f'WAM key: {key[:30]}...')

meta = {'ideName':'Windsurf','ideVersion':'1.108.2','extensionVersion':'3.14.2',
        'apiKey':key,'locale':'en-US','os':'win32','url':'https://server.codeium.com'}
body = json.dumps({'metadata':meta,'workspaceTrusted':True}).encode()

def get_trailer(raw):
    pos = 0
    while pos+5 <= len(raw):
        fl = raw[pos]; n = struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        chunk = raw[pos:pos+n]; pos+=n
        if fl == 0x80: return chunk.decode('utf-8','replace')
    return ''

# Step 1: Find LS port via netstat + probe
print('\n=== Finding LS port ===')
r = subprocess.run(['netstat','-ano'], capture_output=True)
r.stdout = r.stdout.decode('gbk', errors='replace')
candidate_ports = []
for line in r.stdout.splitlines():
    if 'LISTENING' in line and '127.0.0.1' in line:
        parts = line.split()
        try:
            port = int(parts[1].split(':')[1])
            if port > 50000:
                candidate_ports.append(port)
        except: pass
print(f'Candidate ports: {candidate_ports}')

ls_port = None
for port in candidate_ports:
    csrf = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'  # try old CSRF first
    try:
        r2 = requests.post(
            f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState',
            data=b'\x00'+struct.pack('>I',len(body))+body,
            headers={'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
                     'x-codeium-csrf-token':csrf,'x-grpc-web':'1'},
            timeout=3, stream=True)
        raw = b''.join(r2.iter_content(chunk_size=None))
        trailer = get_trailer(raw)
        ok = 'grpc-status: 0' in trailer
        print(f'  port={port} HTTP={r2.status_code} {"OK" if ok else "FAIL"} | {trailer.strip()[:60]}')
        if ok and not ls_port:
            ls_port = port
            print(f'  => LS port found: {ls_port} with old CSRF!')
        elif r2.status_code == 200 and not ok:
            print(f'  => port {port} is LS but CSRF wrong (HTTP 200, grpc error)')
            if not ls_port: ls_port = port  # record as candidate even with wrong CSRF
    except Exception as e:
        pass  # Not a gRPC endpoint

if not ls_port:
    print('No LS port found!')
else:
    print(f'\nLS port: {ls_port}')

# Step 2: Get PID owning ls_port and check process name
if ls_port:
    for line in r.stdout.splitlines():
        if f'127.0.0.1:{ls_port}' in line and 'LISTENING' in line:
            pid = line.split()[-1]
            ps = subprocess.run(['tasklist','/FI',f'PID eq {pid}','/FO','CSV','/NH'],
                                capture_output=True, text=True)
            print(f'Port {ls_port} owner: PID={pid} {ps.stdout.strip()[:80]}')

# Step 3: Read CSRF from state.vscdb or known locations
print('\n=== Looking for CSRF in data files ===')
import os, glob
search_dirs = [
    r'C:\Users\Administrator\AppData\Roaming\Windsurf',
    r'C:\Users\Administrator\AppData\Local\Windsurf',
]
uuid_re = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)
for d in search_dirs:
    for ext in ['*.log','*.json','*.txt']:
        for fp in glob.glob(os.path.join(d,'**',ext), recursive=True)[:50]:
            try:
                with open(fp,'r',encoding='utf-8',errors='ignore') as f:
                    content = f.read(10000)
                if 'CSRF' in content.upper() or 'csrf' in content:
                    uuids = uuid_re.findall(content)
                    if uuids:
                        print(f'  {fp}: CSRF-related UUIDs: {uuids[:3]}')
            except: pass
