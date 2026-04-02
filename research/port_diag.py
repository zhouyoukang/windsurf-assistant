#!/usr/bin/env python3
"""诊断 LS 端口状态 + 找 Windsurf UI 正在使用的端口"""
import sys, io, json, struct, time, subprocess, re, requests, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

LS_EXE = 'language_server_windows_x64.exe'
WS_EXE = 'Windsurf.exe'

r = subprocess.run(['netstat', '-ano'], capture_output=True)
net = r.stdout.decode('gbk', errors='replace')

# 找 LS PID
r2 = subprocess.run(['tasklist','/FO','CSV','/NH'], capture_output=True, timeout=5)
pids = {}
for line in r2.stdout.decode('gbk',errors='replace').strip().splitlines():
    p = line.strip().strip('"').split('","')
    if len(p) >= 2:
        try: pids[int(p[1])] = p[0]
        except: pass

ls_pids = [pid for pid, name in pids.items() if LS_EXE.lower() in name.lower()]
ws_pids = [pid for pid, name in pids.items() if name.lower().startswith('windsurf')]
print(f'LS PIDs:        {ls_pids}')
print(f'Windsurf PIDs:  {ws_pids}')

# 找 LS 监听端口
print('\n=== LS LISTENING ports ===')
ls_listen = []
for pid in ls_pids:
    for line in net.splitlines():
        if 'LISTENING' in line:
            p = line.split()
            try:
                if int(p[-1]) == pid:
                    port = int(p[1].split(':')[1])
                    ls_listen.append(port)
                    print(f'  LISTEN :{port} (PID {pid})')
            except: pass

# 找 Windsurf → LS 的 ESTABLISHED 连接
print('\n=== Windsurf → LS ESTABLISHED connections ===')
for pid in ws_pids:
    for line in net.splitlines():
        if 'ESTABLISHED' in line and '127.0.0.1' in line:
            p = line.split()
            try:
                if int(p[-1]) == pid:
                    local = p[1]; remote = p[2]
                    remote_port = int(remote.split(':')[1])
                    if remote_port in ls_listen:
                        print(f'  WS PID {pid}: {local} → {remote} (LS port {remote_port})')
            except: pass

# 快速测试每个端口
print('\n=== Quick gRPC test each port ===')
DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
con = sqlite3.connect(DB)
row = con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
con.close()
key = json.loads(row[0]).get('apiKey', '') if row else ''

CSRF_TEST = 'probe-token-00000000'

for port in sorted(set(ls_listen)):
    try:
        b = json.dumps({'metadata': {'ideName':'W', 'apiKey': key}, 'workspaceTrusted': True}).encode()
        r3 = requests.post(
            f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState',
            data=b'\x00' + struct.pack('>I', len(b)) + b,
            headers={'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
                     'x-codeium-csrf-token': CSRF_TEST, 'x-grpc-web':'1'},
            timeout=3, stream=True)
        raw = b''.join(r3.iter_content(chunk_size=None))
        print(f'  Port {port}: HTTP {r3.status_code}, {len(raw)} bytes')
        if raw:
            try:
                frames = []
                pos = 0
                while pos + 5 <= len(raw):
                    fl = raw[pos]; n = struct.unpack('>I', raw[pos+1:pos+5])[0]; pos += 5
                    frames.append((fl, raw[pos:pos+n])); pos += n
                for fl, fr in frames[:3]:
                    try:
                        obj = json.loads(fr)
                        print(f'    Frame: {json.dumps(obj)[:200]}')
                    except:
                        if fl == 0x80:
                            print(f'    Trailer: {fr.decode("utf-8","replace")[:200]}')
                        else:
                            print(f'    Raw bytes: {fr.hex()[:60]}')
            except Exception as e:
                print(f'    Parse error: {e}')
    except Exception as e:
        print(f'  Port {port}: ERROR {e}')

print('\n=== Recommendation ===')
print('Use the port that shows HTTP 200 from the test above')
