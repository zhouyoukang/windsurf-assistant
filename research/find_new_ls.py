"""find_new_ls.py — 找新 LS 端口和 CSRF"""
import subprocess, re, struct, json, requests

# 1. 获取所有监听端口及进程
r = subprocess.run(['powershell', '-Command',
    'Get-NetTCPConnection -State Listen | Where-Object {$_.LocalPort -ge 50000} | '
    'Select-Object LocalPort, OwningProcess | Sort-Object LocalPort | Format-Table -AutoSize'],
    capture_output=True, text=True, timeout=10)
print("Listening ports >50000:")
print(r.stdout)

# 2. 对每个疑似 LS 端口测试 StartCascade（不带 CSRF）
KEY = json.load(open(r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\cascade-auth.json')).get('apiKey','')
META = {"ideName":"Windsurf","ideVersion":"1.108.2","extensionVersion":"3.14.2",
        "extensionName":"Windsurf","extensionPath":r"D:\Windsurf\resources\app\extensions\windsurf",
        "apiKey":KEY,"locale":"en-US","os":"win32","url":"https://server.codeium.com"}

# Extract ports from output
ports = re.findall(r'(\d{5})\s+(\d+)', r.stdout)
print("\nTesting ports for LS...")
for port_str, pid_str in ports:
    port = int(port_str)
    if port < 55000: continue
    for csrf in ['7de33f15-f528-4329-9453-3618de08b9a6', '38a7a689-1e2a-41ff-904b-eefbc9dcacfe']:
        HDR = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
               'x-codeium-csrf-token':csrf,'x-grpc-web':'1'}
        b = json.dumps({'metadata':META,'source':'CORTEX_TRAJECTORY_SOURCE_USER'}).encode()
        try:
            resp = requests.post(f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/StartCascade',
                                  data=b'\x00'+struct.pack('>I',len(b))+b, headers=HDR, timeout=3, stream=True)
            raw = b''.join(resp.iter_content(chunk_size=None))
            if resp.status_code == 200 and len(raw) > 0:
                print(f"  ✅ PORT {port} PID {pid_str} CSRF {csrf[:8]}: len={len(raw)} data={repr(raw[:80])}")
            elif resp.status_code == 200:
                print(f"  PORT {port} PID {pid_str} CSRF {csrf[:8]}: 200 EMPTY")
            # else: skip 403/404
        except: pass

# 3. 也扫描所有进程的 CSRF token
print("\nScanning process envs for WINDSURF_CSRF_TOKEN...")
r2 = subprocess.run(['powershell', '-Command',
    '''$procs = Get-WmiObject Win32_Process | Where-Object {$_.CommandLine -like "*windsurf*" -or $_.Name -like "*windsurf*" -or $_.Name -eq "node.exe"}
    foreach ($p in $procs) { Write-Output "$($p.ProcessId) $($p.Name) $($p.CommandLine.Substring(0, [Math]::Min(80, $p.CommandLine.Length)))" }'''],
    capture_output=True, text=True, timeout=10)
print(r2.stdout[:2000])
