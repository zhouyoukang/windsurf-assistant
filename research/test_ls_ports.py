"""test_ls_ports.py — 测试 LS gRPC 端口上的 GetChatMessage"""
import struct, http.client, json, sqlite3, sys

DB_PATH = r"C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb"

def get_api_key():
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
    row  = cur.fetchone(); conn.close()
    return json.loads(row[0]).get('apiKey', '')

def varint(n):
    out = []
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80); n >>= 7
    out.append(n & 0x7F)
    return bytes(out)

def f_str(no, s):
    b = s.encode() if isinstance(s, str) else s
    return varint((no << 3)|2) + varint(len(b)) + b

def connect_frame(data):
    return b'\x00' + struct.pack('>I', len(data)) + data

def post(port, path, body, headers, timeout=8):
    try:
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
        conn.request('POST', path, connect_frame(body), headers)
        r = conn.getresponse()
        return r.status, r.read(2000)
    except Exception as e:
        return 0, str(e).encode()

api_key = get_api_key()
print(f"API key: {api_key[:25]}...")

csrf_31872 = '18e67ec6-8a9b-4781-bcea-ac61a722a640'
csrf_54108 = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'

# LS 端口 (random_port 分配的)
ls_ports = [
    (57407, csrf_31872, 'PID31872-A'),
    (57412, csrf_31872, 'PID31872-B'),
    (64958, csrf_54108, 'PID54108-A'),
    (64965, csrf_54108, 'PID54108-B'),
]

paths = [
    '/exa.language_server_pb.LanguageServerService/GetChatMessage',
    '/exa.language_server_pb.LanguageServerService/GetStatus',
    '/exa.language_server_pb.LanguageServerService/GetCompletions',
]

# 最小请求体: field1=model, field2=prompt
min_body = f_str(1, 'claude-opus-4-6') + f_str(2, 'Say OK')

for port, csrf, label in ls_ports:
    print(f"\n=== {label} port={port} ===")
    for path in paths:
        # 尝试多种认证方式
        for auth_name, h in [
            ('no_auth',   {'Content-Type':'application/connect+proto','Accept':'application/connect+proto','Connect-Protocol-Version':'1'}),
            ('bearer',    {'Content-Type':'application/connect+proto','Accept':'application/connect+proto','Connect-Protocol-Version':'1','Authorization':f'Bearer {api_key}'}),
            ('csrf',      {'Content-Type':'application/connect+proto','Accept':'application/connect+proto','Connect-Protocol-Version':'1','x-codeium-csrf-token':csrf}),
            ('both',      {'Content-Type':'application/connect+proto','Accept':'application/connect+proto','Connect-Protocol-Version':'1','Authorization':f'Bearer {api_key}','x-codeium-csrf-token':csrf}),
        ]:
            s, body = post(port, path, min_body, h, timeout=5)
            if s != 0:  # skip timeouts silently for speed
                short_path = path.split('/')[-1]
                print(f"  {short_path} [{auth_name}]: HTTP {s} | {body[:80]}")
        break  # only try first path for now
    if port == 64965:
        # also try all paths on last port
        pass

print("\n=== Extended test on best candidates ===")
for port, csrf, label in ls_ports:
    for path in paths[:1]:  # GetChatMessage only
        s, body = post(port, path, min_body,
                       {'Content-Type':'application/connect+proto',
                        'Accept':'application/connect+proto',
                        'Connect-Protocol-Version':'1',
                        'Authorization':f'Bearer {api_key}'},
                       timeout=6)
        print(f"  {label}:{port} bearer → HTTP {s}: {body[:100]}")
