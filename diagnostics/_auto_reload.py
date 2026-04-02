#!/usr/bin/env python3
"""通过 port 1588 ExtensionServer 触发 Reload Window"""
import struct, json, urllib.request, urllib.error

CSRF = '9d439854-47f4-4dcd-ba4c-92229f43777f'
PORT = 1588

def ev(v):
    r=[]
    while True:
        b=v&0x7F; v>>=7; r.append(b|0x80 if v else b)
        if not v: break
    return bytes(r)
def ef_str(fn,s): d=s.encode(); return ev((fn<<3)|2)+ev(len(d))+d
def ef_bytes(fn,b): return ev((fn<<3)|2)+ev(len(b))+b

def call_ext(method, body_pb=b''):
    svc='exa.extension_server_pb.ExtensionServerService'
    url=f'http://127.0.0.1:{PORT}/{svc}/{method}'
    h={'Content-Type':'application/connect+proto',
       'Accept':'application/connect+proto',
       'x-codeium-csrf-token':CSRF,
       'Connect-Protocol-Version':'1'}
    req=urllib.request.Request(url,data=body_pb,headers=h,method='POST')
    try:
        with urllib.request.urlopen(req,timeout=5) as resp:
            raw=resp.read(500)
            return resp.status,raw.decode('utf-8',errors='replace')
    except urllib.error.HTTPError as e:
        return e.code,e.read(200).decode('utf-8',errors='replace')
    except Exception as ex:
        return -1,str(ex)

# 1. Try CheckHasCursorRules to test CSRF
print('=== CSRF Test ===')
s,b = call_ext('CheckHasCursorRules')
print(f'CheckHasCursorRules: HTTP {s} -> {b[:100]}')

# 2. ExecuteCommand: workbench.action.reloadWindow
print('\n=== ExecuteCommand: workbench.action.reloadWindow ===')
# ExecuteCommandRequest: F1=commandLine, F2=cwd, F3=terminalId
cmd_pb = ef_str(1, 'workbench.action.reloadWindow')
s,b = call_ext('ExecuteCommand', cmd_pb)
print(f'ExecuteCommand: HTTP {s} -> {b[:200]}')

# 3. Also try openSetting which might have a refresh option
print('\n=== Alternative: cascade refresh commands ===')
for cmd in ['workbench.action.reloadWindow',
            'windsurf.refreshAuth',
            'windsurf.reloadExtension',
            'workbench.action.refreshTheme']:
    cmd_pb = ef_str(1, cmd)
    s,b = call_ext('ExecuteCommand', cmd_pb)
    print(f'  {cmd}: HTTP {s} -> {b[:60]}')
