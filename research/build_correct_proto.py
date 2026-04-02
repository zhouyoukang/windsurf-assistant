"""build_correct_proto.py — 用完整正确字段构建 RawGetChatMessage 请求并发送"""
import json, sqlite3, os, re, uuid, struct, time, requests, base64

# ===== Step 1: Get auth info =====
DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
con = sqlite3.connect(DB)
cur = con.cursor()
cur.execute("SELECT key, value FROM ItemTable")
rows = dict(cur.fetchall())
con.close()

# api_key from windsurfAuthStatus
auth_status = json.loads(rows.get('windsurfAuthStatus', '{}'))
API_KEY = auth_status.get('apiKey', '')
CSRF_TOKEN = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'  # PID 54108 session token

# ===== Step 2: Get versions =====
import json as _json
# Find the real windsurf extension version (check multiple paths)
EXT_VERSION = '3.14.2'  # fallback
for vpath in [
    r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js',
]:
    try:
        with open(vpath, 'r', encoding='utf-8', errors='ignore') as f:
            chunk = f.read(100000)  # first 100KB
        import re as _re
        vm = _re.search(r'extensionVersion[=:\s]+["\']([0-9]+\.[0-9]+\.[0-9]+)["\']', chunk)
        if vm: EXT_VERSION = vm.group(1); break
    except: pass
# Also try to read from the actual package
try:
    with open(r'D:\Windsurf\resources\app\extensions\windsurf\package.json', 'r') as f:
        pkg = _json.load(f)
    raw_ver = pkg.get('version', '')
    if raw_ver and raw_ver != '0.2.0': EXT_VERSION = raw_ver
except: pass
IDE_VERSION = '1.108.2'
IDE_NAME = 'Windsurf'
EXT_NAME = 'Windsurf'
EXT_PATH = r'D:\Windsurf\resources\app\extensions\windsurf'
URL = 'https://server.codeium.com'
OS_NAME = 'win32'
LOCALE = 'en-US'

print(f"API Key: {API_KEY[:50]}...")
print(f"Extension version: {EXT_VERSION}")
print(f"CSRF Token: {CSRF_TOKEN}")
print()

# ===== Step 3: Proto encoding helpers =====
def encode_varint(value):
    bits = value & 0x7f
    value >>= 7
    result = b''
    while value:
        result += bytes([0x80 | bits])
        bits = value & 0x7f
        value >>= 7
    result += bytes([bits])
    return result

def encode_string(field_num, value):
    if isinstance(value, str):
        value = value.encode('utf-8')
    tag = (field_num << 3) | 2  # wire type 2 = length-delimited
    return encode_varint(tag) + encode_varint(len(value)) + value

def encode_varint_field(field_num, value):
    tag = (field_num << 3) | 0  # wire type 0 = varint
    return encode_varint(tag) + encode_varint(value)

def encode_message(field_num, data):
    tag = (field_num << 3) | 2
    return encode_varint(tag) + encode_varint(len(data)) + data

# ===== Step 4: Build Metadata proto =====
# exa.codeium_common_pb.Metadata fields:
# 1=ide_name, 2=extension_version, 3=api_key, 4=locale, 5=os
# 7=ide_version, 12=extension_name, 14=url, 17=extension_path
meta = b''
meta += encode_string(1, IDE_NAME)           # ide_name
meta += encode_string(2, EXT_VERSION)        # extension_version
meta += encode_string(3, API_KEY)            # api_key
meta += encode_string(4, LOCALE)             # locale
meta += encode_string(5, OS_NAME)            # os
meta += encode_string(7, IDE_VERSION)        # ide_version
meta += encode_string(12, EXT_NAME)          # extension_name
meta += encode_string(14, URL)               # url
meta += encode_string(17, EXT_PATH)          # extension_path

print(f"Metadata proto: {len(meta)} bytes")

# ===== Step 5: Build ChatMessage proto =====
# exa.codeium_common_pb.ChatMessage fields:
# 1=message_id (string), 2=source (enum), 3=timestamp (message),
# 4=conversation_id (string), 5=intent (oneof content)
# ChatMessageSource: USER=1

# The 'intent' field (5) is a ChatIntent message
# Let's first try with just basic text content
# For ChatIntent, we'll try to encode the user text in field 1 (userInput)
MSG_ID = str(uuid.uuid4())
CONV_ID = str(uuid.uuid4())
USER_TEXT = "Hello! What is 2+2?"

# Simple intent: just try field 1 as user text
intent = encode_string(1, USER_TEXT)  # assume field 1 = user_input in ChatIntent

chat_msg = b''
chat_msg += encode_string(1, MSG_ID)          # message_id
chat_msg += encode_varint_field(2, 1)         # source = CHAT_MESSAGE_SOURCE_USER = 1
chat_msg += encode_string(4, CONV_ID)         # conversation_id
chat_msg += encode_message(5, intent)         # intent (oneof content)

print(f"ChatMessage proto: {len(chat_msg)} bytes")

# ===== Step 6: Build RawGetChatMessageRequest =====
# fields: 1=metadata, 2=chat_messages (repeated), 4=chat_model (enum), 5=chat_model_name (string)
# MODEL_CLAUDE_4_5_OPUS = 391 (confirmed)
MODEL_NAME = "claude-opus-4-5"
MODEL_ENUM = 391  # MODEL_CLAUDE_4_5_OPUS

req = b''
req += encode_message(1, meta)               # metadata
req += encode_message(2, chat_msg)           # chat_messages (first element)
req += encode_varint_field(4, MODEL_ENUM)    # chat_model (enum)
req += encode_string(5, MODEL_NAME)          # chat_model_name

print(f"Request proto: {len(req)} bytes")
print()

# ===== Step 7: gRPC-Web framing =====
def grpc_frame(data):
    return b'\x00' + struct.pack('>I', len(data)) + data

framed = grpc_frame(req)

# ===== Step 8: Send to local LS =====
# Find LS port
LS_PORT = 64958  # active port

# Try to find actual port
try:
    import subprocess
    result = subprocess.run(
        ['powershell', '-Command',
         'Get-NetTCPConnection -State Listen | Where-Object {$_.LocalPort -in @(57407,64958,57408,57409)} | Select-Object LocalPort'],
        capture_output=True, text=True, timeout=5
    )
    print(f"Listening ports: {result.stdout}")
except: pass

URL_LS = f'http://127.0.0.1:{LS_PORT}/exa.language_server_pb.LanguageServerService/RawGetChatMessage'

headers = {
    'Content-Type': 'application/grpc-web+proto',
    'Accept': 'application/grpc-web+proto',
    'x-codeium-csrf-token': CSRF_TOKEN,
    'x-grpc-web': '1',
}

print(f"POST {URL_LS}")
print(f"Payload (hex): {req.hex()[:100]}...")
print()

try:
    resp = requests.post(URL_LS, data=framed, headers=headers, timeout=30, stream=True)
    print(f"Status: {resp.status_code}")
    print(f"Response headers: {dict(resp.headers)}")
    
    raw = b''
    for chunk in resp.iter_content(chunk_size=None):
        raw += chunk
        if len(raw) > 10000:
            break
    
    print(f"Response body ({len(raw)} bytes): {raw[:500].hex()}")
    print()
    
    # Try to find grpc-status in response
    grpc_status_m = re.search(rb'grpc-status:(\d+)', raw)
    grpc_msg_m = re.search(rb'grpc-message:([^\r\n]+)', raw)
    if grpc_status_m:
        print(f"grpc-status: {grpc_status_m.group(1).decode()}")
    if grpc_msg_m:
        print(f"grpc-message: {grpc_msg_m.group(1).decode(errors='replace')}")
    
    # Try to decode as text (might be JSON response)
    try:
        text = raw.decode('utf-8', errors='replace')
        print(f"As text: {text[:500]}")
    except:
        pass

except Exception as e:
    print(f"Error: {e}")

# ===== Also try with JSON encoding =====
print()
print("=== Also trying gRPC-Web JSON ===")
import time as _time

json_req = {
    "metadata": {
        "ideName": IDE_NAME,
        "ideVersion": IDE_VERSION,
        "extensionVersion": EXT_VERSION,
        "extensionName": EXT_NAME,
        "extensionPath": EXT_PATH,
        "apiKey": API_KEY,
        "locale": LOCALE,
        "os": OS_NAME,
        "url": URL,
    },
    "chatMessages": [{
        "messageId": MSG_ID,
        "source": "CHAT_MESSAGE_SOURCE_USER",
        "conversationId": CONV_ID,
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        "intent": {
            "userInput": USER_TEXT
        }
    }],
    "chatModel": "MODEL_CLAUDE_4_5_OPUS",
    "chatModelName": MODEL_NAME
}

json_headers = {
    'Content-Type': 'application/grpc-web+json',
    'Accept': 'application/grpc-web+json',
    'x-codeium-csrf-token': CSRF_TOKEN,
    'x-grpc-web': '1',
}

json_body_bytes = json.dumps(json_req).encode('utf-8')
json_framed = grpc_frame(json_body_bytes)

try:
    resp2 = requests.post(URL_LS, data=json_framed, headers=json_headers, timeout=30, stream=True)
    print(f"JSON Status: {resp2.status_code}")
    print(f"JSON Headers: {dict(resp2.headers)}")
    
    raw2 = b''
    for chunk in resp2.iter_content(chunk_size=None):
        raw2 += chunk
        if len(raw2) > 10000: break
    
    print(f"JSON Response ({len(raw2)} bytes): {raw2[:500].hex()}")
    try:
        text2 = raw2.decode('utf-8', errors='replace')
        print(f"JSON Text: {text2[:500]}")
    except: pass

except Exception as e:
    print(f"JSON Error: {e}")
