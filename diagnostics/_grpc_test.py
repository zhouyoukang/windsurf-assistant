#!/usr/bin/env python3
"""
直接 gRPC-web 测试 — 验证 claude-opus-4-6 服务端接受性
语言服务器: 127.0.0.1:61591 (PID 55456)
"""
import sqlite3, json, os, base64, struct, urllib.request, urllib.error

STATE_DB = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')

def encode_varint(val):
    result = []
    while True:
        bits = val & 0x7F
        val >>= 7
        if val:
            result.append(bits | 0x80)
        else:
            result.append(bits)
            break
    return bytes(result)

def encode_string_field(fnum, s):
    data = s.encode('utf-8')
    tag = (fnum << 3) | 2
    return encode_varint(tag) + encode_varint(len(data)) + data

def encode_varint_field(fnum, val):
    tag = (fnum << 3) | 0
    return encode_varint(tag) + encode_varint(val)

def grpc_frame(pb_bytes):
    """gRPC-web frame: 1 byte flag (0) + 4 byte length + pb bytes"""
    return b'\x00' + struct.pack('>I', len(pb_bytes)) + pb_bytes

def decode_varint(data, pos):
    val=0; shift=0
    while pos < len(data):
        b=data[pos]; pos+=1
        val|=(b&0x7F)<<shift; shift+=7
        if not(b&0x80): break
    return val,pos

def decode_response(data):
    """解码 gRPC-web 响应"""
    if len(data) < 5:
        return None
    flag = data[0]
    length = struct.unpack('>I', data[1:5])[0]
    pb = data[5:5+length]
    
    # 解析 CheckChatCapacityResponse
    result = {}
    pos = 0
    while pos < len(pb):
        try:
            tag, pos = decode_varint(pb, pos)
            fnum = tag >> 3; wtype = tag & 7
            if wtype == 0:
                val, pos = decode_varint(pb, pos)
                result[fnum] = val
            elif wtype == 2:
                l, pos = decode_varint(pb, pos)
                val = pb[pos:pos+l]; pos += l
                try:
                    result[fnum] = val.decode('utf-8')
                except:
                    result[fnum] = val.hex()
            elif wtype == 1: pos += 8
            elif wtype == 5: pos += 4
            else: break
        except: break
    return result

# 读取认证数据
conn = sqlite3.connect('file:'+STATE_DB+'?mode=ro', uri=True)
cur = conn.cursor()
cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
auth = json.loads(cur.fetchone()[0])
conn.close()

api_key = auth.get('apiKey', '')
print(f"API Key: {api_key[:30]}...")

# 构造 Metadata 消息 (field 1 of CheckChatCapacityRequest)
# Metadata protobuf: {api_key, ide_name, ...}
# 从 workbench.js 逆向: Metadata 包含 api_key (F1) 和其他字段
metadata_pb = (
    encode_string_field(1, api_key) +      # api_key
    encode_string_field(7, 'windsurf') +   # ide_name  
    encode_string_field(6, '1.108.2') +    # extension_version
    encode_varint_field(2, 1)              # ide_type = WINDSURF
)

# CheckChatCapacity 测试模型列表
test_models = [
    'claude-opus-4-6',        # 目标: 测试是否仍可用
    'claude-opus-4-5',        # 对照: 已知可用
    'MODEL_CLAUDE_4_5_OPUS',  # 对照: 枚举形式
    'claude-sonnet-4-6',      # 对照: 已知可用
]

LS_PORTS = [61591, 61612]

for port in LS_PORTS:
    print(f"\n=== 语言服务器 127.0.0.1:{port} ===")
    
    for model_uid in test_models:
        # 构造 CheckChatCapacityRequest
        request_pb = (
            encode_string_field(1, '') +          # metadata (empty for now)
            encode_string_field(3, model_uid)      # model_uid
        )
        
        # 尝试完整 metadata
        request_pb_full = (
            # F1: metadata (nested)
            (lambda: (lambda d: encode_varint((1<<3)|2) + encode_varint(len(d)) + d)(metadata_pb))() +
            encode_string_field(3, model_uid)
        )
        
        body = grpc_frame(request_pb_full)
        
        url = f"http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/CheckChatCapacity"
        headers = {
            "Content-Type": "application/grpc-web+proto",
            "x-grpc-web": "1",
            "Accept": "application/grpc-web+proto",
            "x-codeium-ide-name": "windsurf",
        }
        
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                resp_data = resp.read()
                decoded = decode_response(resp_data)
                has_capacity = decoded.get(1, '?')
                message = decoded.get(2, '')
                active = decoded.get(3, 0)
                status = '✅ HAS_CAPACITY' if has_capacity == 1 else ('❌ NO_CAPACITY' if has_capacity == 0 else f'? {has_capacity}')
                print(f"  {model_uid:<35} {status}  active={active}  msg='{message[:80]}'")
        except urllib.error.HTTPError as e:
            body_resp = e.read(300)
            print(f"  {model_uid:<35} HTTP {e.code}: {body_resp[:150]}")
        except urllib.error.URLError as e:
            print(f"  {model_uid:<35} URLError: {e.reason}")
        except Exception as e:
            print(f"  {model_uid:<35} Error: {type(e).__name__}: {e}")

print("\n=== 测试完成 ===")
print("has_capacity=1 → 服务端接受该模型 → 可正常使用")
print("has_capacity=0 → 服务端拒绝 (限流/配额/模型不可用)")
print("HTTP 4xx/5xx → 请求格式错误或服务器问题")
