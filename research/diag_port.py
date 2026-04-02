#!/usr/bin/env python3
import subprocess, sys, io, os, json, struct, requests, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

print("=== 方式1: PowerShell Get-Process ===")
try:
    cmd = ['powershell', '-NoProfile', '-Command',
           'Get-Process | Where-Object {$_.Name -like "*language*" -or $_.Name -like "*windsurf*"} | Select-Object Id,Name | Format-Table -AutoSize']
    r = subprocess.run(cmd, capture_output=True, timeout=15)
    print(r.stdout.decode('utf-8', 'replace')[:1000])
    if r.returncode != 0:
        print("stderr:", r.stderr.decode('utf-8', 'replace')[:200])
except Exception as e:
    print(f"PS error: {e}")

print("\n=== 方式2: netstat 所有 LISTENING 端口 ===")
try:
    r2 = subprocess.run(['netstat', '-ano'], capture_output=True, timeout=15)
    net = r2.stdout.decode('gbk', 'replace')
    listen_ports = []
    for line in net.splitlines():
        if 'LISTENING' in line:
            parts = line.split()
            try:
                port = int(parts[1].split(':')[1])
                pid = int(parts[-1])
                if port > 50000:
                    listen_ports.append((port, pid))
            except: pass
    print(f"高端口 LISTENING: {listen_ports[:20]}")
except Exception as e:
    print(f"netstat error: {e}")

print("\n=== 方式3: gRPC 探测高端口 ===")
def probe(port):
    try:
        b = json.dumps({'metadata': {'ideName': 'Windsurf'}, 'workspaceTrusted': True}).encode()
        r = requests.post(
            f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState',
            data=b'\x00' + struct.pack('>I', len(b)) + b,
            headers={'Content-Type': 'application/grpc-web+json',
                     'Accept': 'application/grpc-web+json',
                     'x-codeium-csrf-token': 'probe', 'x-grpc-web': '1'},
            timeout=1.5, stream=True)
        b''.join(r.iter_content(chunk_size=None))
        return r.status_code
    except Exception as e:
        return str(e)[:40]

try:
    r3 = subprocess.run(['netstat', '-ano'], capture_output=True, timeout=15)
    net3 = r3.stdout.decode('gbk', 'replace')
    ports_to_probe = set()
    for line in net3.splitlines():
        if 'LISTENING' in line:
            parts = line.split()
            try:
                port = int(parts[1].split(':')[1])
                if 50000 <= port <= 70000:
                    ports_to_probe.add(port)
            except: pass
    print(f"探测端口数: {len(ports_to_probe)}")
    for p in sorted(ports_to_probe)[:15]:
        code = probe(p)
        print(f"  port {p}: {code}")
except Exception as e:
    print(f"probe error: {e}")

print("\n=== 方式4: WAM DB key ===")
DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
try:
    import sqlite3
    con = sqlite3.connect(DB)
    row = con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()
    con.close()
    if row:
        info = json.loads(row[0])
        print(f"email: {info.get('email','?')}")
        print(f"key: {info.get('apiKey','')[:25]}...")
    else:
        print("no auth row")
except Exception as e:
    print(f"DB error: {e}")
