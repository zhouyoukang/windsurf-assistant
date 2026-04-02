#!/usr/bin/env python3
"""解析 CheckChatCapacity 完整响应 + 验证所有修复状态"""
import sqlite3, json, os, struct, hashlib, base64, urllib.request, urllib.error

STATE_DB = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')
PRODUCT_JSON = r'D:\Windsurf\resources\app\product.json'
WB_JS = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'

def ev(v):
    r = []
    while True:
        b = v & 0x7F; v >>= 7
        r.append(b | 0x80 if v else b)
        if not v: break
    return bytes(r)

def ef_str(fn, s): d = s.encode(); return ev((fn<<3)|2)+ev(len(d))+d
def ef_bytes(fn, b): return ev((fn<<3)|2)+ev(len(b))+b
def grpc_frame(pb): return b'\x00'+struct.pack('>I', len(pb))+pb

def decode_varint(data, pos):
    val = 0; shift = 0
    while pos < len(data):
        b = data[pos]; pos += 1
        val |= (b & 0x7F) << shift; shift += 7
        if not (b & 0x80): break
    return val, pos

def parse_pb(data):
    """Simple protobuf parser — returns {field_num: value}"""
    fields = {}
    pos = 0
    while pos < len(data):
        try:
            tag, pos = decode_varint(data, pos)
            fn = tag >> 3; wt = tag & 7
            if fn == 0: break
            if wt == 0:
                val, pos = decode_varint(data, pos)
                fields[fn] = val
            elif wt == 2:
                length, pos = decode_varint(data, pos)
                val = data[pos:pos+length]; pos += length
                try:
                    fields[fn] = val.decode('utf-8')
                except:
                    fields[fn] = val.hex()
            elif wt == 1: pos += 8
            elif wt == 5: pos += 4
            else: break
        except: break
    return fields

# ── 1. 完整获取 CheckChatCapacity 响应 ──
print("="*65)
print("CheckChatCapacity 完整响应解析")
print("="*65)

conn = sqlite3.connect('file:' + STATE_DB + '?mode=ro', uri=True)
api_key = json.loads(conn.execute(
    "SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'"
).fetchone()[0]).get('apiKey', '')
conn.close()

meta = ef_bytes(1, ef_str(1, api_key))
SERVICE = 'exa.language_server_pb.LanguageServerService'
PATH = f'/{SERVICE}/CheckChatCapacity'

for model_uid in ['claude-opus-4-6', 'claude-opus-4-5', 'MODEL_CLAUDE_4_5_OPUS']:
    req_pb = meta + ef_str(3, model_uid)
    body = grpc_frame(req_pb)
    url = f'http://127.0.0.1:1590{PATH}'
    h = {'Content-Type': 'application/grpc-web+proto', 'x-grpc-web': '1',
         'Accept': 'application/grpc-web+proto'}
    req = urllib.request.Request(url, data=body, headers=h, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw = resp.read(4000)
            print(f"\n[{model_uid}]")
            print(f"  HTTP: {resp.status}")
            print(f"  Raw ({len(raw)}B): {raw.hex()}")
            # Parse gRPC-web frames
            pos = 0
            while pos < len(raw):
                if pos + 5 > len(raw): break
                flag = raw[pos]
                length = struct.unpack('>I', raw[pos+1:pos+5])[0]
                pos += 5
                frame_data = raw[pos:pos+length]
                pos += length
                if flag == 0:  # Data frame
                    fields = parse_pb(frame_data)
                    print(f"  DATA frame ({length}B): fields={fields}")
                    # hasCapacity is typically F1 (bool)
                    has_cap = fields.get(1, 'NOT SET')
                    print(f"  hasCapacity (F1): {has_cap} {'✅ AVAILABLE' if has_cap == 1 else '❌ NO CAPACITY' if has_cap == 0 else '(unknown)'}")
                elif flag == 128:  # Trailers
                    print(f"  TRAILER frame ({length}B): {frame_data.decode('utf-8', errors='replace')[:200]}")
    except urllib.error.HTTPError as e:
        body_resp = e.read(300).decode('utf-8', errors='replace')
        print(f"\n[{model_uid}] HTTP {e.code}: {body_resp[:200]}")
    except Exception as ex:
        print(f"\n[{model_uid}] ERROR: {ex}")

# ── 2. 验证所有修复状态 ──
print("\n" + "="*65)
print("验证所有修复状态")
print("="*65)

# Check product.json hash
with open(PRODUCT_JSON, 'r') as f:
    prod = json.load(f)
stored_hash = prod.get('checksums', {}).get('vs/workbench/workbench.desktop.main.js', '')
wb_bytes = open(WB_JS, 'rb').read()
actual_hash = base64.b64encode(hashlib.sha256(wb_bytes).digest()).decode().rstrip('=')
hash_match = stored_hash == actual_hash
print(f"product.json hash: {'✅ MATCH' if hash_match else '❌ MISMATCH'}")
print(f"  stored: {stored_hash}")
print(f"  actual: {actual_hash}")

# Check workbench.js patch
wb_text = wb_bytes.decode('utf-8', errors='replace')
OPUS_B64 = 'Cg9DbGF1ZGUgT3B1cyA0LjayAQ9jbGF1ZGUtb3B1cy00LTYdAADAQCAAaASQAcCaDKABAMABAw=='
loc1_patched = '__wD' in wb_text
loc2_patched = '__wC' in wb_text
opus_present = OPUS_B64 in wb_text
print(f"\nworkbench.js patch:")
print(f"  LOC1 (__wD): {'✅' if loc1_patched else '❌'}")
print(f"  LOC2 (__wC): {'✅' if loc2_patched else '❌'}")
print(f"  OPUS_B64 present: {'✅' if opus_present else '❌'}")

# Check state.vscdb
conn = sqlite3.connect('file:' + STATE_DB + '?mode=ro', uri=True)
cfg_b64 = conn.execute(
    "SELECT value FROM ItemTable WHERE key='windsurfConfigurations'"
).fetchone()[0]
conn.close()
cfg_bytes = base64.b64decode(cfg_b64)
opus_in_db = b'claude-opus-4-6' in cfg_bytes
print(f"\nstate.vscdb:")
print(f"  claude-opus-4-6 injected: {'✅' if opus_in_db else '❌'}")

print("\n" + "="*65)
print("SUMMARY")
print("="*65)
all_ok = hash_match and loc1_patched and loc2_patched and opus_present and opus_in_db
status = "✅ ALL SYSTEMS GO" if all_ok else "⚠️ SOME ISSUES"
print(f"\n{status}")
print("\n次要步骤：")
print("  1. 在 Windsurf 执行 Ctrl+Shift+P → Reload Window")
print("  2. 点击 Cascade 底部模型选择器")
print("  3. 查找 'Claude Opus 4.6' 并选择")
print("  4. 发送测试消息确认服务端是否正常回复")
