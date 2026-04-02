#!/usr/bin/env python3
"""Windows截图 + CSRF token读取 + 语言服务器端口发现"""
import os, sys, struct, json, subprocess, ctypes, ctypes.wintypes

# ── 1. 截图 Windows 桌面 ──
print("="*65)
print("SCREENSHOT: 截取 Windows 桌面")
print("="*65)

SAVE_PATH = r'v:\道\道生一\一生二\Windsurf无限额度\040-诊断工具_Diagnostics\windsurf_ui_screenshot.png'

try:
    import PIL.ImageGrab
    img = PIL.ImageGrab.grab()
    img.save(SAVE_PATH)
    print(f"PIL screenshot saved: {SAVE_PATH} ({img.size})")
except ImportError:
    # 用 ctypes 截图
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    
    # Get screen dimensions
    SW = user32.GetSystemMetrics(0)
    SH = user32.GetSystemMetrics(1)
    print(f"Screen size: {SW}x{SH}")
    
    # Fallback: use PowerShell
    ps_cmd = f"""
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
$bitmap = New-Object System.Drawing.Bitmap([System.Windows.Forms.SystemInformation]::VirtualScreen.Width, [System.Windows.Forms.SystemInformation]::VirtualScreen.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen([System.Windows.Forms.SystemInformation]::VirtualScreen.Location, [System.Drawing.Point]::Empty, $bitmap.Size)
$bitmap.Save('{SAVE_PATH.replace("'", "''")}')
Write-Output 'Saved'
"""
    r = subprocess.run(['powershell', '-Command', ps_cmd], capture_output=True, text=True, timeout=15)
    if r.returncode == 0:
        print(f"PowerShell screenshot: {r.stdout.strip()}")
    else:
        print(f"Screenshot failed: {r.stderr[:200]}")

# ── 2. 读取 PID 44176 环境变量 (WINDSURF_CSRF_TOKEN) ──
print("\n" + "="*65)
print("PROCESS ENV: PID 44176 (language_server)")
print("="*65)

try:
    import winreg
    # Try to get process info via psutil
    import importlib.util
    if importlib.util.find_spec('psutil'):
        import psutil
        p = psutil.Process(44176)
        env = p.environ()
        csrf = env.get('WINDSURF_CSRF_TOKEN', 'NOT FOUND')
        print(f"WINDSURF_CSRF_TOKEN: {csrf}")
        # Also print relevant env vars
        for k, v in env.items():
            if any(x in k.upper() for x in ['CSRF', 'TOKEN', 'API', 'PORT', 'CODEIUM', 'WINDSURF']):
                print(f"  {k} = {v[:100]}")
    else:
        print("psutil not available, trying ctypes approach...")
        raise ImportError("psutil not available")
except ImportError:
    # Use ctypes/Windows API
    import ctypes
    
    PROCESS_VM_READ = 0x0010
    PROCESS_QUERY_INFORMATION = 0x0400
    
    # First try using subprocess with PowerShell
    ps_cmd = """
$pid = 44176
$proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
if ($proc) {
    $handle = [System.Diagnostics.Process]::GetProcessById($pid)
    # Get env via WMI
    $wmiProc = Get-CimInstance Win32_Process -Filter "ProcessId = $pid"
    $env_path = $wmiProc.GetRelated('Win32_Environment') | Select Name, VariableValue
    Write-Output $env_path
}
"""
    # Alternative: Read from process memory
    # Simpler: use WMIC + environment dump
    r = subprocess.run(['wmic', 'process', 'where', 'ProcessId=44176',
                       'get', 'ExecutablePath,ProcessId,CommandLine'],
                      capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10)
    print(f"Process info:\n{r.stdout[:500]}")
    
except Exception as e:
    print(f"Error: {e}")
    
# Try psutil install
try:
    import psutil
    p = psutil.Process(44176)
    env = p.environ()
    csrf = env.get('WINDSURF_CSRF_TOKEN', 'NOT FOUND')
    print(f"\nWINDSURF_CSRF_TOKEN via psutil: {csrf}")
    for k, v in env.items():
        if any(x in k.upper() for x in ['CSRF', 'TOKEN', 'PORT', 'WINDSURF', 'CODEIUM']):
            print(f"  {k} = {v[:150]}")
except Exception as e:
    print(f"psutil error: {e}")

# ── 3. 发现语言服务器实际 gRPC 端口 ──
print("\n" + "="*65)
print("DISCOVER: 语言服务器 gRPC 端口")  
print("="*65)

import urllib.request, urllib.error

def probe_grpc_port(port):
    """Probe a port to see if it's the language server gRPC port"""
    service_paths = [
        '/exa.language_server_pb.LanguageServerService/CheckChatCapacity',
        '/exa.language_server_pb.LanguageServerService/GetPlanStatus',
        '/exa.language_server_pb.LanguageServerService/HeartBeat',
        '/windsurf.LanguageServerService/CheckChatCapacity',
        '/LanguageServerService/CheckChatCapacity',
    ]
    
    for path in service_paths:
        url = f'http://127.0.0.1:{port}{path}'
        req = urllib.request.Request(url, data=b'', 
            headers={'Content-Type': 'application/connect+proto', 'Connect-Protocol-Version': '1'},
            method='POST')
        try:
            with urllib.request.urlopen(req, timeout=2) as resp:
                body = resp.read(200).decode(errors='replace')
                return port, path, resp.status, body
        except urllib.error.HTTPError as e:
            body = e.read(100).decode(errors='replace')
            if e.code != 404 or 'not found' not in body.lower():
                return port, path, e.code, body
        except: pass
    return port, None, None, None

# Check all language server ports
result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True, timeout=10)
ls_ports = set()
for line in result.stdout.split('\n'):
    if 'LISTENING' in line and '127.0.0.1' in line:
        parts = line.split()
        if len(parts) >= 5 and parts[-1] == '44176':
            port = parts[1].split(':')[-1]
            if port.isdigit():
                ls_ports.add(int(port))
print(f"Language server (PID 44176) ports: {sorted(ls_ports)}")

for port in sorted(ls_ports):
    result_tuple = probe_grpc_port(port)
    p, path, status, body = result_tuple
    print(f"  Port {p}: path={path}, status={status}, body={body[:100] if body else ''}")

print("\n=== DONE ===")
