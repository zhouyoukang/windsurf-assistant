"""
cascade_client.py — 完整后端直调方案
流程: StartCascade → SendUserCascadeMessage → StreamCascadeReactiveUpdates
"""
import json, sqlite3, os, re, uuid, struct, time, sys
import threading
import requests

# ===== 自动获取认证信息 =====
DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
con = sqlite3.connect(DB); cur = con.cursor()
cur.execute("SELECT key, value FROM ItemTable")
rows = dict(cur.fetchall()); con.close()

auth_status = json.loads(rows.get('windsurfAuthStatus', '{}'))
API_KEY = auth_status.get('apiKey', '')

# 从进程环境获取 CSRF token
CSRF_TOKEN = None
try:
    import subprocess, ctypes, ctypes.wintypes
    result = subprocess.run(
        ['powershell', '-Command',
         '(Get-WmiObject Win32_Process | Where-Object {$_.Name -like "*windsurf*" -and $_.CommandLine -like "*extensionHost*"} | Select-Object -First 2 ProcessId).ProcessId'],
        capture_output=True, text=True, timeout=5
    )
    pids = [int(p.strip()) for p in result.stdout.strip().split('\n') if p.strip().isdigit()]
    
    for pid in pids:
        try:
            env_result = subprocess.run(
                ['powershell', '-Command',
                 f'[System.Diagnostics.Process]::GetProcessById({pid}).StartInfo.EnvironmentVariables["WINDSURF_CSRF_TOKEN"]'],
                capture_output=True, text=True, timeout=3
            )
            token = env_result.stdout.strip()
            if token and '-' in token:
                CSRF_TOKEN = token
                print(f"Got CSRF from PID {pid}: {token}")
                break
        except: pass
except: pass

if not CSRF_TOKEN:
    # Use get_csrf.py result from known sessions
    CSRF_TOKEN = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'

LS_PORT = 64958
IDE_VERSION = '1.108.2'
EXT_VERSION = '3.14.2'
IDE_NAME = 'Windsurf'
BASE_URL = 'https://server.codeium.com'

print(f"=== Cascade Client ===")
print(f"API Key: {API_KEY[:40]}...")
print(f"CSRF: {CSRF_TOKEN}")
print(f"LS Port: {LS_PORT}")
print()

# ===== gRPC-Web helpers =====
def grpc_frame(data):
    return b'\x00' + struct.pack('>I', len(data)) + data

def parse_grpc_frames(raw):
    frames = []
    pos = 0
    while pos + 5 <= len(raw):
        flag = raw[pos]
        length = struct.unpack('>I', raw[pos+1:pos+5])[0]
        pos += 5
        frame_data = raw[pos:pos+length]
        pos += length
        frames.append({'flag': flag, 'data': frame_data})
    return frames

BASE_META = {
    "ideName": IDE_NAME,
    "ideVersion": IDE_VERSION,
    "extensionVersion": EXT_VERSION,
    "extensionName": "Windsurf",
    "extensionPath": r"D:\Windsurf\resources\app\extensions\windsurf",
    "apiKey": API_KEY,
    "locale": "en-US",
    "os": "win32",
    "url": BASE_URL,
}

def call_ls_unary(method, body_json, timeout=15):
    url = f'http://127.0.0.1:{LS_PORT}/exa.language_server_pb.LanguageServerService/{method}'
    headers = {
        'Content-Type': 'application/grpc-web+json',
        'Accept': 'application/grpc-web+json',
        'x-codeium-csrf-token': CSRF_TOKEN,
        'x-grpc-web': '1',
    }
    body = json.dumps(body_json).encode('utf-8')
    resp = requests.post(url, data=grpc_frame(body), headers=headers, timeout=timeout, stream=True)
    raw = b''.join(resp.iter_content(chunk_size=None))
    frames = parse_grpc_frames(raw)
    return resp.status_code, dict(resp.headers), frames

def stream_ls(method, body_json, on_data, timeout=60):
    url = f'http://127.0.0.1:{LS_PORT}/exa.language_server_pb.LanguageServerService/{method}'
    headers = {
        'Content-Type': 'application/grpc-web+json',
        'Accept': 'application/grpc-web+json',
        'x-codeium-csrf-token': CSRF_TOKEN,
        'x-grpc-web': '1',
    }
    body = json.dumps(body_json).encode('utf-8')
    
    with requests.post(url, data=grpc_frame(body), headers=headers, timeout=timeout, stream=True) as resp:
        buf = b''
        for chunk in resp.iter_content(chunk_size=64):
            buf += chunk
            # Try to parse complete frames
            while len(buf) >= 5:
                length = struct.unpack('>I', buf[1:5])[0]
                if len(buf) < 5 + length:
                    break
                frame = buf[:5+length]
                buf = buf[5+length:]
                flag = frame[0]
                data = frame[5:]
                if not on_data(flag, data):
                    return

# ===== Step 1: StartCascade =====
print("=== [1] StartCascade ===")
status, hdrs, frames = call_ls_unary("StartCascade", {
    "metadata": BASE_META,
    "source": "CORTEX_TRAJECTORY_SOURCE_USER",
})
print(f"Status: {status}")

cascade_id = None
for f in frames:
    if f['flag'] == 0:
        try:
            d = json.loads(f['data'])
            cascade_id = d.get('cascadeId') or d.get('cascade_id')
            print(f"Response: {json.dumps(d)[:300]}")
        except:
            text = f['data'].decode('utf-8', errors='replace')
            # Extract UUID
            m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', text)
            if m: cascade_id = m.group(0)
            print(f"Raw: {text[:200]}")
    else:
        trailer = f['data'].decode('utf-8', errors='replace')
        print(f"Trailer: {trailer[:100]}")

if not cascade_id:
    print("ERROR: No cascade_id. Exiting.")
    sys.exit(1)

print(f"CascadeID: {cascade_id}\n")

# ===== Step 2: Start streaming BEFORE sending message =====
print("=== [2] StreamCascadeReactiveUpdates (background) ===")
stream_output = []
stream_done = threading.Event()

def handle_stream_data(flag, data):
    if flag == 0x80:  # trailer
        trailer = data.decode('utf-8', errors='replace')
        print(f"[Stream Trailer] {trailer[:200]}")
        stream_done.set()
        return False
    try:
        text = data.decode('utf-8', errors='replace')
        try:
            parsed = json.loads(text)
            stream_output.append(parsed)
            # Print meaningful content
            if 'trajectoryStep' in parsed:
                step = parsed['trajectoryStep']
                if 'text' in step:
                    print(f"[AI] {step['text'][:200]}", flush=True)
                elif 'step' in step:
                    print(f"[Step] {str(step['step'])[:200]}", flush=True)
                else:
                    print(f"[Traj] {str(step)[:150]}", flush=True)
            elif 'deltaMessage' in parsed:
                dm = parsed['deltaMessage']
                if dm.get('text'):
                    print(f"[Delta] {dm['text'][:200]}", flush=True)
                    if dm.get('isError'):
                        print("[ERROR - stopping stream]")
                        stream_done.set()
                        return False
            elif 'error' in parsed:
                print(f"[Error] {parsed['error']}", flush=True)
                stream_done.set()
                return False
            else:
                keys = list(parsed.keys())
                print(f"[Data] keys={keys}", flush=True)
        except:
            print(f"[Raw] {text[:150]}", flush=True)
    except: pass
    return True

def stream_thread():
    try:
        stream_ls("StreamCascadeReactiveUpdates", {
            "metadata": BASE_META,
            "cascadeId": cascade_id,
        }, handle_stream_data, timeout=60)
    except Exception as e:
        print(f"[Stream Error] {e}")
    finally:
        stream_done.set()

t = threading.Thread(target=stream_thread, daemon=True)
t.start()
time.sleep(0.5)  # Let stream connect

# ===== Step 3: SendUserCascadeMessage =====
print("=== [3] SendUserCascadeMessage ===")

# Get user input or use default
if len(sys.argv) > 1:
    USER_MSG = ' '.join(sys.argv[1:])
else:
    USER_MSG = "Hello! Please say 'Backend connected!' and confirm you are Claude."

print(f"Sending: {USER_MSG}")

send_req = {
    "metadata": BASE_META,
    "cascadeId": cascade_id,
    "items": [
        {"text": USER_MSG}
    ],
}

# Add cascadeConfig with model if desired
MODEL_UID = "claude-opus-4-5"  # use known allowed model first
# MODEL_UID = "claude-opus-4-6"  # uncomment after verifying

# Try to include model in cascadeConfig
# Based on extension usage: cascadeConfig.requestedModelUid
# Since we don't know the exact field number, try JSON key directly
send_req["cascadeConfig"] = {
    "requestedModelUid": MODEL_UID
}

status3, hdrs3, frames3 = call_ls_unary("SendUserCascadeMessage", send_req, timeout=10)
print(f"Status: {status3}")
for f in frames3:
    if f['flag'] == 0:
        print(f"Data: {f['data'].decode('utf-8', errors='replace')[:200]}")
    else:
        trailer = f['data'].decode('utf-8', errors='replace')
        print(f"Trailer: {trailer[:200]}")

print("\nWaiting for stream response (30s)...")
stream_done.wait(timeout=30)

print("\n=== Stream output summary ===")
print(f"Total frames: {len(stream_output)}")
if stream_output:
    print(f"Last 3 frames:")
    for item in stream_output[-3:]:
        print(f"  {str(item)[:200]}")
