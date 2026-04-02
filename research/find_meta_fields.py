"""find_meta_fields.py — 找 Metadata 完整 proto 字段编号 + 正确请求构造"""

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
txt = open(EXT, 'r', encoding='utf-8', errors='replace').read()

needle = 'typeName="exa.language_server_pb.Metadata"'
idx = txt.find(needle)
if idx > 0:
    seg = txt[max(0,idx-2000):idx+3000]
    print('=== Metadata proto3 segment ===')
    print(seg[:5000])
else:
    print('Not found, searching variants...')
    for m in re.finditer(r'language_server_pb\.Metadata', txt):
        ctx = txt[max(0,m.start()-100):m.end()+500]
        if 'fields' in ctx or 'no:' in ctx:
            print(ctx[:600])
            print('---')

# Also search for csrfToken as a proto field
print('\n=== csrfToken in proto fields ===')
for m in re.finditer(r'name:"csrf_token".{0,200}', txt):
    print(m.group()[:300])
    print('---')
for m in re.finditer(r'csrfToken.{0,200}', txt):
    ctx = m.group()
    if 'no:' in ctx or 'kind:' in ctx or 'scalar' in ctx:
        print(ctx[:300])
        print('---')

# 1. Find all field definitions with names containing key words
key_fields = ['ide_name', 'ide_version', 'extension_version', 'api_key', 'url',
              'locale', 'user_id', 'organization_id', 'session_id', 'request_id',
              'installation_id', 'auth_source', 'ideName', 'ideVersion']

print("=== Metadata field numbers ===")
for field in key_fields:
    # Try proto3 field definition patterns
    patterns = [
        r'no:(\d+),name:"' + field + r'"',
        r'name:"' + field + r'",.*?no:(\d+)',
    ]
    for p in patterns:
        m = re.search(p, content)
        if m:
            ctx = content[max(0,m.start()-50):m.start()+200]
            print(f"  {field}: {repr(ctx[:220])}")
            break

print()

# 2. Find the complete Metadata newFieldList block
print("=== Metadata newFieldList (search by ide_name proximity) ===")
m = re.search(r'ide_name', content)
if m:
    # Find nearest newFieldList
    before = content[max(0,m.start()-2000):m.start()+500]
    fl = re.search(r'newFieldList\(\(\)=>\[(.*?)\]\)', before, re.DOTALL)
    if fl:
        print(f"Fields: {fl.group(1)[:1500]}")
    else:
        # Find the block manually
        ctx = content[max(0,m.start()-500):m.start()+500]
        print(f"Context: {repr(ctx[:800])}")
        
print()

# 3. Grep for Metadata class definition
print("=== language_server_pb Metadata definition ===")
for pat in ['Metadata.*ide_name', 'ide_name.*Metadata', 'exa.language_server_pb.Metadata']:
    m2 = re.search(pat, content)
    if m2:
        ctx = content[max(0,m2.start()-100):m2.start()+1000]
        print(f"[{pat}] @{m2.start()}: {repr(ctx[:800])}")
        print()
        break

# 4. Find where the extension reads api_key from storage
print("=== apiKey/api_key storage access ===")
for m3 in re.finditer(r'getApiKey|\.apiKey\b|api_key.*storage|storage.*api_key', content, re.I):
    ctx = content[max(0,m3.start()-50):m3.start()+200]
    print(f"@{m3.start()}: {repr(ctx[:220])}")
    print()
    if sum(1 for _ in re.finditer(r'getApiKey', content)) > 3:
        break

# 5. Find the LS port env variable
print("=== LS port / LSP_PORT ===")
for m4 in re.finditer(r'LSP.*PORT|PORT.*LSP|language.*server.*port|lsp.*port', content, re.I):
    ctx = content[max(0,m4.start()-50):m4.start()+150]
    print(f"@{m4.start()}: {repr(ctx[:180])}")
    
# 6. The ChatMessageSource enum values
print()
print("=== ChatMessageSource enum values ===")
m5 = re.search(r'ChatMessageSource.*?UNSPECIFIED.*?USER|USER.*?ChatMessageSource', content, re.DOTALL)
if not m5:
    m5 = re.search(r'ChatMessageSource', content)
if m5:
    ctx = content[max(0,m5.start()-20):m5.start()+500]
    print(f"@{m5.start()}: {repr(ctx[:450])}")

# 7. Find ChatIntent proto fields 
print()
print("=== ChatIntent / intent message fields ===")
for pat in ['typeName="exa.chat_pb.ChatIntent"', 'ChatIntent.*fields', 
            r'no:1,name:"user_input"', r'user_input.*intent']:
    m6 = re.search(pat, content)
    if m6:
        ctx = content[max(0,m6.start()-50):m6.start()+500]
        print(f"[{pat}] @{m6.start()}: {repr(ctx[:450])}")
        print()
