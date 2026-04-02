import struct, http.client, json, sqlite3, uuid

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
PORT = 57407
CSRF = '18e67ec6-8a9b-4781-bcea-ac61a722a640'
PATH = '/exa.language_server_pb.LanguageServerService/RawGetChatMessage'

conn = sqlite3.connect(DB); cur = conn.cursor()
cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
row = cur.fetchone(); conn.close()
api_key = json.loads(row[0]).get('apiKey', '')
print(f"api_key: {api_key[:20]}...")

payload = {
    'metadata': {
        'ideName': 'windsurf',
        'ideVersion': '1.9577.43',
        'extensionVersion': '1.9577.43',
        'apiKey': api_key,
    },
    'chatMessages': [{
        'messageId': str(uuid.uuid4()),
        'role': 1,
        'content': 'Reply with exactly three words: OPUS FOUR SIX',
        'timestamp': '2026-03-30T21:22:00Z',
        'conversationId': str(uuid.uuid4()),
    }],
}

body = json.dumps(payload).encode()
framed = b'\x00' + struct.pack('>I', len(body)) + body
headers = {
    'Content-Type': 'application/connect+json',
    'Accept': 'application/connect+json',
    'Connect-Protocol-Version': '1',
    'x-codeium-csrf-token': CSRF,
}

print(f"POST http://127.0.0.1:{PORT}{PATH}")
print(f"payload size: {len(body)} bytes")
c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=60)
c.request('POST', PATH, framed, headers)
r = c.getresponse()
print(f"HTTP {r.status}")
data = r.read(8192)
print(f"raw ({len(data)} bytes): {data[:800]}")

# Parse Connect-RPC response
pos = 0
while pos < len(data):
    if pos + 5 > len(data): break
    flag = data[pos]
    length = struct.unpack('>I', data[pos+1:pos+5])[0]
    chunk = data[pos+5:pos+5+length]
    pos += 5 + length
    try:
        obj = json.loads(chunk)
        print(f"\nchunk (flag={flag}): {json.dumps(obj, ensure_ascii=False, indent=2)[:600]}")
    except:
        print(f"\nchunk (flag={flag}, raw): {chunk[:200]}")
