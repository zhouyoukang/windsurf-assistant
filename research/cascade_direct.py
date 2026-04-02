"""cascade_direct.py — 完整 Cascade 流程：StartCascade → SendUserCascadeMessage → Stream"""
import json, sqlite3, os, re, uuid, struct, time, requests

# ===== Auth =====
DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
con = sqlite3.connect(DB); cur = con.cursor()
cur.execute("SELECT key, value FROM ItemTable")
rows = dict(cur.fetchall()); con.close()

auth_status = json.loads(rows.get('windsurfAuthStatus', '{}'))
API_KEY = auth_status.get('apiKey', '')
CSRF_TOKEN = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'
LS_PORT = 64958
IDE_VERSION = '1.108.2'
EXT_VERSION = '3.14.2'
IDE_NAME = 'Windsurf'
URL = 'https://server.codeium.com'

print(f"API Key: {API_KEY[:50]}...")
print(f"CSRF: {CSRF_TOKEN}")
print()

def grpc_frame(data): return b'\x00' + struct.pack('>I', len(data)) + data

def call_ls(method, body_json, timeout=30):
    url = f'http://127.0.0.1:{LS_PORT}/exa.language_server_pb.LanguageServerService/{method}'
    headers = {
        'Content-Type': 'application/grpc-web+json',
        'Accept': 'application/grpc-web+json',
        'x-codeium-csrf-token': CSRF_TOKEN,
        'x-grpc-web': '1',
    }
    body = json.dumps(body_json).encode('utf-8')
    framed = grpc_frame(body)
    resp = requests.post(url, data=framed, headers=headers, timeout=timeout, stream=True)
    
    raw = b''
    for chunk in resp.iter_content(chunk_size=None):
        raw += chunk
    
    # Parse all gRPC-Web frames
    frames = []
    pos = 0
    while pos + 5 <= len(raw):
        flag = raw[pos]; length = struct.unpack('>I', raw[pos+1:pos+5])[0]; pos += 5
        frame_data = raw[pos:pos+length]; pos += length
        if flag == 0x80:  # trailer
            trailers = frame_data.decode('utf-8', errors='replace')
            frames.append({'type': 'trailer', 'data': trailers})
        else:
            frames.append({'type': 'data', 'data': frame_data})
    
    return resp.status_code, resp.headers, frames

BASE_META = {
    "ideName": IDE_NAME,
    "ideVersion": IDE_VERSION,
    "extensionVersion": EXT_VERSION,
    "extensionName": "Windsurf",
    "extensionPath": r"D:\Windsurf\resources\app\extensions\windsurf",
    "apiKey": API_KEY,
    "locale": "en-US",
    "os": "win32",
    "url": URL,
}

# ===== Step 1: InitializeCascadePanelState =====
print("=== Step 1: InitializeCascadePanelState ===")
status, headers, frames = call_ls("InitializeCascadePanelState", {"metadata": BASE_META})
print(f"Status: {status}")
for f in frames:
    if f['type'] == 'trailer':
        print(f"Trailer: {f['data'][:200]}")
    else:
        try: print(f"Data: {f['data'].decode('utf-8', errors='replace')[:200]}")
        except: print(f"Data (hex): {f['data'].hex()[:100]}")
print()

# ===== Step 2: StartCascade =====
print("=== Step 2: StartCascade ===")
# Find StartCascade proto fields
# From extension: startCascade({metadata, source, ...})
# source: CortexTrajectorySource enum - UNSPECIFIED=0, USER=1

start_cascade_req = {
    "metadata": BASE_META,
    "source": "CORTEX_TRAJECTORY_SOURCE_USER",
}

status2, headers2, frames2 = call_ls("StartCascade", start_cascade_req)
print(f"Status: {status2}")

cascade_id = None
for f in frames2:
    if f['type'] == 'data':
        try:
            text = f['data'].decode('utf-8', errors='replace')
            print(f"Data: {text[:400]}")
            # Try to parse cascade_id
            try:
                parsed = json.loads(text)
                cascade_id = (parsed.get('cascadeId') or 
                              parsed.get('cascade_id') or
                              parsed.get('trajectoryId') or
                              parsed.get('id'))
                if cascade_id: print(f"  >> cascade_id: {cascade_id}")
            except: pass
        except: print(f"Data (hex): {f['data'].hex()[:200]}")
    else:
        print(f"Trailer: {f['data'][:300]}")
print()

if not cascade_id:
    print("No cascade_id found, trying to extract from hex...")
    for f in frames2:
        if f['type'] == 'data' and len(f['data']) > 5:
            # Try to find UUID pattern
            text = f['data'].decode('utf-8', errors='replace')
            uuid_m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', text)
            if uuid_m:
                cascade_id = uuid_m.group(0)
                print(f"  >> Extracted cascade_id: {cascade_id}")
                break

# ===== Step 3: SendUserCascadeMessage =====
if cascade_id:
    print(f"=== Step 3: SendUserCascadeMessage (cascade_id={cascade_id}) ===")
    
    USER_MSG = "Hello, what is 2+2? Give a brief answer."
    MSG_ID = str(uuid.uuid4())
    CONV_ID = str(uuid.uuid4())
    
    # Try various field names for SendUserCascadeMessage
    send_req = {
        "metadata": BASE_META,
        "cascadeId": cascade_id,
        "message": {
            "messageId": MSG_ID,
            "source": "CHAT_MESSAGE_SOURCE_USER",
            "conversationId": CONV_ID,
            "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            "intent": {"userInput": USER_MSG}
        },
        "modelUid": "claude-opus-4-5",
    }
    
    try:
        status3, headers3, frames3 = call_ls("SendUserCascadeMessage", send_req)
        print(f"Status: {status3}")
        for f in frames3:
            if f['type'] == 'data':
                try:
                    text = f['data'].decode('utf-8', errors='replace')
                    print(f"Data: {text[:400]}")
                except: print(f"Data (hex): {f['data'].hex()[:100]}")
            else:
                print(f"Trailer: {f['data'][:300]}")
    except Exception as e:
        print(f"Error: {e}")
    print()

# ===== Also try RawGetChatMessage with cascade session established =====
print("=== RawGetChatMessage after cascade init ===")
MSG_ID2 = str(uuid.uuid4())
CONV_ID2 = str(uuid.uuid4())
rcm_req = {
    "metadata": BASE_META,
    "chatMessages": [{
        "messageId": MSG_ID2,
        "source": "CHAT_MESSAGE_SOURCE_USER",
        "conversationId": CONV_ID2,
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "intent": {"userInput": "Hello, what is 2+2?"}
    }],
    "chatModel": "MODEL_CLAUDE_4_5_OPUS",
    "chatModelName": "claude-opus-4-5",
}

try:
    status4, headers4, frames4 = call_ls("RawGetChatMessage", rcm_req)
    print(f"Status: {status4}")
    for f in frames4:
        if f['type'] == 'data':
            try:
                text = f['data'].decode('utf-8', errors='replace')
                print(f"Data: {text[:600]}")
            except: print(f"Data (hex): {f['data'].hex()[:100]}")
        else:
            print(f"Trailer: {f['data'][:300]}")
except Exception as e:
    print(f"Error: {e}")
