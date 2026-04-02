#!/usr/bin/env python3
"""尝试触发 Windsurf auth 刷新 — 无需 Reload Window"""
import sqlite3, json, os, struct, urllib.request, urllib.error

STATE_DB = os.path.expandvars(r'%APPDATA%\Windsurf\User\globalStorage\state.vscdb')

def ev(v):
    r=[]
    while True:
        b=v&0x7F; v>>=7; r.append(b|0x80 if v else b)
        if not v: break
    return bytes(r)
def ef_str(fn,s): d=s.encode(); return ev((fn<<3)|2)+ev(len(d))+d
def ef_bytes(fn,b): return ev((fn<<3)|2)+ev(len(b))+b
def grpc_frame(pb): return b'\x00'+struct.pack('>I',len(pb))+pb

conn=sqlite3.connect('file:'+STATE_DB+'?mode=ro',uri=True)
auth=json.loads(conn.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()[0])
conn.close()
api_key=auth.get('apiKey','')
print(f'API Key: {api_key[:20]}...')

# Check current model list in windsurfAuthStatus
models=auth.get('allowedCommandModelConfigsProtoBinaryBase64',[])
print(f'Models in auth status: {len(models)} items')
print(f'claude-opus-4-6 present: {any("4-6" in m for m in models)}')

# Try HeartBeat to trigger state refresh
print('\n--- HeartBeat RPC ---')
meta=ef_bytes(1,ef_str(1,api_key))
for method in ['HeartBeat','GetPlanStatus','GetUserStatus','RefreshSettings']:
    path=f'/exa.language_server_pb.LanguageServerService/{method}'
    body=grpc_frame(meta)
    url=f'http://127.0.0.1:1590{path}'
    h={'Content-Type':'application/grpc-web+proto','x-grpc-web':'1','Accept':'application/grpc-web+proto'}
    req=urllib.request.Request(url,data=body,headers=h,method='POST')
    try:
        with urllib.request.urlopen(req,timeout=5) as resp:
            raw=resp.read(500)
            print(f'  {method}: HTTP {resp.status} ({len(raw)}B) {raw[:80].hex()}')
    except urllib.error.HTTPError as e:
        print(f'  {method}: HTTP {e.code} {e.read(100).decode(errors="replace")[:60]}')
    except Exception as ex:
        print(f'  {method}: {type(ex).__name__}: {str(ex)[:60]}')

# Also try writing a "touch" to state.vscdb to trigger file watcher
print('\n--- state.vscdb 触发 file watcher ---')
conn2=sqlite3.connect(STATE_DB)
# Update a non-critical timestamp key to trigger SQLite WAL notification
conn2.execute("UPDATE ItemTable SET value=value WHERE key='windsurfChangelog/dismissedVersion'")
conn2.commit()
conn2.close()
print('Triggered SQLite WAL write (file watcher may detect change)')

import time
time.sleep(3)
print('Waited 3s — check Windsurf model picker now')
