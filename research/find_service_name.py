"""find_service_name.py — 找 InitializeCascadePanelState 所在 service 的 typeName"""
import re

EXT_JS = r"D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js"
with open(EXT_JS, 'r', encoding='utf-8', errors='replace') as f:
    content = f.read()

# Find where initializeCascadePanelState is defined and its surrounding service typeName
idx = content.find('initializeCascadePanelState')
print(f"initializeCascadePanelState @{idx}")
# Look for typeName 2000 chars before
region_before = content[max(0, idx-3000):idx+500]
type_names = re.findall(r'typeName:\s*["\']([^"\']+)["\']', region_before)
print(f"typeNames before: {type_names[-5:]}")

# Search for the object containing initializeCascadePanelState
# Find where the service object starts (has 'typeName' and 'methods')
print("\n--- service object context ---")
# Find opening brace before initializeCascadePanelState
idx2 = content.rfind('typeName:', 0, idx)
print(f"nearest typeName before: @{idx2}: {content[idx2:idx2+100]}")

# Find all service registrations with their typeName and methods
print("\n--- All service typeNames ---")
service_patterns = re.findall(
    r'typeName:\s*["\']([^"\']+)["\'][^}]{0,300}methods',
    content
)
for p in service_patterns[:15]:
    print(f"  {p}")

# Try: search for 'InitializeCascadePanelState' near a typeName
for m in re.finditer(r'InitializeCascadePanelState', content):
    pos = m.start()
    # Look for typeName within 2000 chars before
    before = content[max(0, pos-2000):pos]
    tnames = re.findall(r'typeName:\s*["\']([^"\']+)["\']', before)
    if tnames:
        print(f"\n@{pos} nearest typeName: {tnames[-1]}")

# Try direct path variants
import struct, http.client, json, sqlite3, uuid

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
conn = sqlite3.connect(DB); cur = conn.cursor()
cur.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'")
row = cur.fetchone(); conn.close()
api_key = json.loads(row[0]).get('apiKey', '')

PORT = 57407; CSRF = '18e67ec6-8a9b-4781-bcea-ac61a722a640'

def json_post(service_path, payload, timeout=8):
    body = json.dumps(payload).encode()
    framed = b'\x00' + struct.pack('>I', len(body)) + body
    h = {'Content-Type':'application/connect+json','Accept':'application/connect+json',
         'Connect-Protocol-Version':'1','x-codeium-csrf-token':CSRF}
    try:
        c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=timeout)
        c.request('POST', service_path, framed, h)
        r = c.getresponse()
        return r.status, r.read(500)
    except Exception as e:
        return 0, str(e).encode()

meta = {'metadata': {'ideName':'windsurf','ideVersion':'1.9577.43','extensionVersion':'1.9577.43','apiKey':api_key}}

print("\n--- Testing different service paths ---")
candidates = [
    '/exa.language_server_pb.LanguageServerService/InitializeCascadePanelState',
    '/exa.cascade_pb.CascadeService/InitializeCascadePanelState',
    '/exa.language_server_pb.CascadeService/InitializeCascadePanelState',
    '/exa.cascade_pb.LanguageServerService/InitializeCascadePanelState',
    '/exa.chat_pb.LanguageServerService/InitializeCascadePanelState',
    '/exa.language_server_pb.LanguageServerService/GetStatus',
    '/exa.language_server_pb.LanguageServerService/GetCompletions',
]
for path in candidates:
    s, body = json_post(path, meta)
    print(f"  {path} → HTTP {s}: {body[:80]}")
