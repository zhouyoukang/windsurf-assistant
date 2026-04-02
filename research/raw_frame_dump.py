#!/usr/bin/env python3
"""
raw_frame_dump.py — 打印 StreamCascadeReactiveUpdates 原始帧结构
确认 AI 响应在哪个 JSON 字段里
"""
import sys, io, json, struct, time, sqlite3, subprocess, re, ctypes, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ── 加载 opus46_ultimate 的核心函数 ──
sys.path.insert(0, r'e:\道\道生一\一生二\Windsurf无限额度')
from opus46_ultimate import find_ls_port, find_csrf, vault_load, META_TMPL, DB_PATH, _get_wam_key

port = find_ls_port()
csrf = find_csrf()
print(f"Port: {port}, CSRF: {csrf[:8] if csrf else None}...")

key = vault_load() or _get_wam_key()
print(f"Key: {key[:25]}...")

if not all([port, csrf, key]):
    print("Missing params"); sys.exit(1)

meta = {**META_TMPL, 'apiKey': key}
hdr = {'Content-Type': 'application/grpc-web+json', 'Accept': 'application/grpc-web+json',
       'x-codeium-csrf-token': csrf, 'x-grpc-web': '1'}

def call(method, body, timeout=10):
    b = json.dumps(body).encode()
    r = requests.post(f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/{method}',
                      data=b'\x00' + struct.pack('>I', len(b)) + b, headers=hdr, timeout=timeout, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    frames=[]; pos=0
    while pos+5 <= len(raw):
        fl=raw[pos]; n=struct.unpack('>I', raw[pos+1:pos+5])[0]; pos+=5
        frames.append((fl, raw[pos:pos+n])); pos+=n
    return frames

# Init cascade
call('InitializeCascadePanelState', {'metadata': meta, 'workspaceTrusted': True})
call('UpdateWorkspaceTrust', {'metadata': meta, 'workspaceTrusted': True})
f1 = call('StartCascade', {'metadata': meta, 'source': 'CORTEX_TRAJECTORY_SOURCE_USER'})
cid = next((json.loads(d).get('cascadeId') for fl,d in f1 if fl==0 and b'cascadeId' in d), None)
print(f'CascadeID: {cid}')

# Send message with SWE-1.5 (known-working model)
MODEL = 'MODEL_SWE_1_5'
MSG = '1+1=? Reply with just the number.'
call('SendUserCascadeMessage', {
    'metadata': meta, 'cascadeId': cid,
    'items': [{'text': MSG}],
    'cascadeConfig': {'plannerConfig': {'requestedModelUid': MODEL, 'conversational': {}}}
}, timeout=12)

# Stream and dump frames
sb = json.dumps({'id': cid, 'protocolVersion': 1}).encode()
r2 = requests.post(
    f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
    data=b'\x00' + struct.pack('>I', len(sb)) + sb, headers=hdr, timeout=60, stream=True)

print(f'\n=== Streaming frames (timeout=60s) ===')
buf=b''; t0=time.time(); frame_no=0; total_bytes=0
for chunk in r2.iter_content(chunk_size=256):
    buf += chunk; total_bytes += len(chunk)
    while len(buf) >= 5:
        nl = struct.unpack('>I', buf[1:5])[0]
        if len(buf) < 5+nl: break
        fl=buf[0]; fr=buf[5:5+nl]; buf=buf[5+nl:]
        frame_no += 1
        elapsed = time.time()-t0
        
        if fl == 0x80:
            # Trailer frame
            print(f'\n[F{frame_no}] TRAILER at {elapsed:.1f}s: {fr[:200]}')
            break
        
        # Data frame - try to parse JSON
        try:
            obj = json.loads(fr)
            # Print top-level keys
            top_keys = list(obj.keys()) if isinstance(obj, dict) else []
            
            if frame_no <= 3:
                # First 3 frames: print full structure summary
                print(f'\n[F{frame_no}] @{elapsed:.1f}s len={len(fr)} keys={top_keys}')
                for k, v in (obj.items() if isinstance(obj, dict) else []):
                    if isinstance(v, str):
                        print(f'  {k}: {repr(v[:100])}')
                    elif isinstance(v, dict):
                        print(f'  {k}: dict with keys {list(v.keys())[:5]}')
                    elif isinstance(v, list):
                        print(f'  {k}: list[{len(v)}]')
                    else:
                        print(f'  {k}: {repr(v)[:100]}')
            else:
                # Later frames: look for text-like content
                def find_texts(o, path='', depth=0):
                    if depth > 8: return
                    if isinstance(o, str) and 2 < len(o) < 200:
                        # Check if this looks like actual response text
                        if any(c.isalpha() for c in o) and '\\' not in o:
                            print(f'  [{path}]: {repr(o[:120])}')
                    elif isinstance(o, dict):
                        for k, v in o.items():
                            find_texts(v, f'{path}.{k}', depth+1)
                    elif isinstance(o, list):
                        for i, v in enumerate(o[:3]):
                            find_texts(v, f'{path}[{i}]', depth+1)
                
                if frame_no % 5 == 0 or frame_no <= 10:
                    print(f'\n[F{frame_no}] @{elapsed:.1f}s len={len(fr)}')
                    find_texts(obj)
        except json.JSONDecodeError:
            print(f'[F{frame_no}] @{elapsed:.1f}s RAW (not JSON) len={len(fr)}: {repr(fr[:100])}')
        
        if time.time()-t0 > 45: 
            print(f'\nTimeout at {elapsed:.1f}s, {frame_no} frames, {total_bytes} bytes')
            break
    
    if time.time()-t0 > 45: break

print(f'\n=== Done: {frame_no} frames, {total_bytes} bytes, {time.time()-t0:.1f}s ===')
