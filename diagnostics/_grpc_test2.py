#!/usr/bin/env python3
"""gRPC-web 测试 v2 — 修复解码问题，原始字节转储"""
import sqlite3, json, os, base64, struct, urllib.request, urllib.error

STATE_DB = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')

def encode_varint(val):
    result = []
    while True:
        bits = val & 0x7F; val >>= 7
        if val: result.append(bits | 0x80)
        else: result.append(bits); break
    return bytes(result)

def encode_string_field(fnum, s):
    data = s.encode('utf-8'); tag = (fnum << 3) | 2
    return encode_varint(tag) + encode_varint(len(data)) + data

def encode_varint_field(fnum, val):
    return encode_varint((fnum << 3) | 0) + encode_varint(val)

def grpc_frame(pb_bytes):
    return b'\x00' + struct.pack('>I', len(pb_bytes)) + pb_bytes

conn = sqlite3.connect('file:'+STATE_DB+'?mode=ro', uri=True)
cur = conn.cursor()
cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
auth = json.loads(cur.fetchone()[0])
conn.close()

api_key = auth.get('apiKey', '')
print(f"API Key: {api_key[:30]}...")

# 找到语言服务器的确切gRPC路径
# 尝试不同服务路径
TEST_PATHS = [
    "/exa.language_server_pb.LanguageServerService/CheckChatCapacity",
    "/languageserver.LanguageServerService/CheckChatCapacity",
    "/CheckChatCapacity",
]
TEST_MODELS = ['claude-opus-4-6', 'claude-opus-4-5']

PORT = 61591

print(f"\n=== Raw gRPC test on port {PORT} ===")

# 最简单的 CheckChatCapacity 请求 (只有 model_uid)
for path in TEST_PATHS:
    for model in TEST_MODELS[:1]:
        # 构造带metadata的请求
        metadata_pb = encode_string_field(1, api_key)  # F1 = api_key
        metadata_envelope = encode_varint((1 << 3) | 2) + encode_varint(len(metadata_pb)) + metadata_pb
        
        request_pb = metadata_envelope + encode_string_field(3, model)
        body = grpc_frame(request_pb)
        
        url = f"http://127.0.0.1:{PORT}{path}"
        headers = {
            "Content-Type": "application/grpc-web+proto",
            "x-grpc-web": "1",
            "Accept": "application/grpc-web+proto,application/grpc-web",
        }
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read()
                print(f"\n✅ {path} [{model}]: HTTP {resp.status}")
                print(f"   Response headers: {dict(resp.headers)}")
                print(f"   Raw ({len(raw)} bytes): {raw[:200].hex()}")
                if len(raw) >= 5:
                    flag = raw[0]
                    length = struct.unpack('>I', raw[1:5])[0]
                    pb = raw[5:5+length] if len(raw) >= 5+length else raw[5:]
                    print(f"   gRPC frame: flag={flag}, pb_len={length}, pb={pb.hex()}")
                    # Try to decode as strings
                    try:
                        txt = pb.decode('utf-8', errors='replace')
                        print(f"   pb text: {txt[:200]}")
                    except: pass
                break  # found working path
        except urllib.error.HTTPError as e:
            body_resp = e.read(300)
            print(f"\n❌ {path} [{model}]: HTTP {e.code}")
            print(f"   Response: {body_resp[:200]}")
        except Exception as e:
            print(f"\n⚠️  {path} [{model}]: {type(e).__name__}: {e}")

# 也测试无 metadata 的最简单请求
print(f"\n--- Minimal request (no metadata) ---")
for model in ['claude-opus-4-6', 'claude-opus-4-5']:
    simple_pb = encode_string_field(3, model)
    body = grpc_frame(simple_pb)
    url = f"http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/CheckChatCapacity"
    headers = {"Content-Type": "application/grpc-web+proto", "x-grpc-web": "1"}
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read()
            print(f"  {model}: HTTP {resp.status}, {len(raw)} bytes: {raw[:100].hex()}")
            if len(raw) >= 5:
                flag = raw[0]; length = struct.unpack('>I', raw[1:5])[0]
                pb = raw[5:5+min(length, len(raw)-5)]
                print(f"    frame: flag={flag}, len={length}, pb_hex={pb.hex()}")
                try:
                    print(f"    pb_text: {pb.decode('utf-8', errors='replace')[:200]}")
                except: pass
    except urllib.error.HTTPError as e:
        print(f"  {model}: HTTP {e.code}: {e.read(200)}")
    except Exception as e:
        print(f"  {model}: {type(e).__name__}: {e}")
