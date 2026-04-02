#!/usr/bin/env python3
"""找到extension.js中实际使用的API server URL"""
import re, os

EXT = r'D:\Windsurf\resources\app\extensions\windsurf\dist\extension.js'
WB = r'D:\Windsurf\resources\app\out\vs\workbench\workbench.desktop.main.js'

with open(EXT,'r',encoding='utf-8',errors='replace') as f:
    ext = f.read()

print("=== Extension.js API URLs ===")
# Find server.codeium.com references
for pat in ['server.codeium.com', 'inference.codeium', 'api_server', '_route/api']:
    hits = [m.start() for m in re.finditer(re.escape(pat), ext)]
    if hits:
        pos = hits[0]
        print(f'\n[{pat}] {len(hits)} hits, first @{pos}:')
        print(ext[max(0,pos-150):pos+300][:400])

# Find baseUrl in connect transport
for m in re.finditer(r'baseUrl', ext):
    pos = m.start()
    ctx = ext[pos:pos+200]
    if 'https' in ctx or 'http' in ctx:
        print(f'\n[baseUrl] @{pos}: {ctx[:200]}')
        break

# Find the correct gRPC service path
print('\n=== gRPC Service Paths ===')
for pat in ['LanguageServerService', 'ChatClientServerService', 'SeatManagementService']:
    idx = ext.find(pat)
    if idx >= 0:
        print(f'\n[{pat}] @{idx}:')
        print(ext[max(0,idx-200):idx+400][:500])

# Also check workbench.js for the local LSP connection
print('\n=== workbench.js LSP connection ===')
with open(WB,'r',encoding='utf-8',errors='replace') as f:
    wb = f.read()

# Find local port setup
for pat in ['this.port', 'lsPort', 'languageServerPort', '127.0.0.1']:
    m = re.search(re.escape(pat), wb)
    if m:
        pos = m.start()
        ctx = wb[max(0,pos-100):pos+300]
        if 'codeium' in ctx.lower() or 'windsurf' in ctx.lower() or 'grpc' in ctx.lower() or 'connect' in ctx.lower():
            print(f'\n[{pat}] @{pos}: {ctx[:300]}')
            break

# Find where the port is actually set/used
idx = wb.find('createConnectTransport({baseUrl')
if idx >= 0:
    print(f'\n[createConnectTransport] @{idx}:')
    print(wb[max(0,idx-200):idx+400])
