#!/usr/bin/env python3
"""
csrf_key_match_test.py — 测试 CSRF 与 DB Key 必须同源假设
用当前 Windsurf 活跃的 DB key + CSRF 发送 SWE-1.5 请求
"""
import sys, io, json, struct, time, threading, requests, base64
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, r'e:\道\道生一\一生二\Windsurf无限额度')
from opus46_ultimate import (find_ls_port, find_csrf, META_TMPL, _get_wam_key,
                              _deep_strings, _classify_error)

port = find_ls_port()
csrf = find_csrf()
db_key = _get_wam_key()  # 当前 Windsurf 活跃账号的 key
print(f"Port: {port}, CSRF: {csrf[:8] if csrf else None}")
print(f"DB key (active account): {db_key[:25] if db_key else None}...")

# Test 1: Use DB key (same account as CSRF)
print("\n=== Test 1: DB key (same account as CSRF) ===")
meta = {**META_TMPL, 'apiKey': db_key}
hdr = {'Content-Type': 'application/grpc-web+json', 'Accept': 'application/grpc-web+json',
       'x-codeium-csrf-token': csrf, 'x-grpc-web': '1'}

def call(method, body, timeout=15):
    b = json.dumps(body).encode()
    r = requests.post(f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/{method}',
                      data=b'\x00' + struct.pack('>I', len(b)) + b, headers=hdr, timeout=timeout, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    frames=[]; pos=0
    while pos+5 <= len(raw):
        fl=raw[pos]; n=struct.unpack('>I', raw[pos+1:pos+5])[0]; pos+=5
        frames.append((fl, raw[pos:pos+n])); pos+=n
    return frames

call('InitializeCascadePanelState', {'metadata': meta, 'workspaceTrusted': True})
call('UpdateWorkspaceTrust', {'metadata': meta, 'workspaceTrusted': True})
f1 = call('StartCascade', {'metadata': meta, 'source': 'CORTEX_TRAJECTORY_SOURCE_USER'})
cid = next((json.loads(d).get('cascadeId') for fl,d in f1 if fl==0 and b'cascadeId' in d), None)
print(f'CascadeID: {cid}')

frames_raw = []; ready = threading.Event(); done = threading.Event()
def sr():
    sb = json.dumps({'id': cid, 'protocolVersion': 1}).encode()
    try:
        r = requests.post(f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
                          data=b'\x00' + struct.pack('>I', len(sb)) + sb, headers=hdr, timeout=30, stream=True)
        buf=b''; t0=time.time(); fn=0
        for chunk in r.iter_content(chunk_size=256):
            buf += chunk
            while len(buf) >= 5:
                nl = struct.unpack('>I', buf[1:5])[0]
                if len(buf) < 5+nl: break
                fl=buf[0]; fr=buf[5:5+nl]; buf=buf[5+nl:]
                fn+=1; frames_raw.append(fr)
                if fn==1: ready.set()
                if fl==0x80: done.set(); return
            if time.time()-t0 > 25: break
    except Exception as e:
        print(f'  stream error: {type(e).__name__}')
    done.set()

t = threading.Thread(target=sr, daemon=True); t.start()
ready.wait(timeout=8)
time.sleep(0.2)
call('SendUserCascadeMessage', {
    'metadata': meta, 'cascadeId': cid,
    'items': [{'text': '1+1=? Reply with ONLY the number 2.'}],
    'cascadeConfig': {'plannerConfig': {'requestedModelUid': 'MODEL_SWE_1_5', 'conversational': {}}}
})
print('  Message sent, waiting 25s...')
done.wait(timeout=25)

# Analyze
errors = []; responses = []
for fr in frames_raw:
    try:
        obj = json.loads(fr)
        strs = _deep_strings(obj)
        for s in strs:
            sl = s.lower()
            if 'permission_denied' in sl or 'failed_precondition' in sl or 'error' in sl:
                errors.append(s[:200])
            elif len(s) > 2 and len(s) < 100:
                if any(c.isdigit() for c in s) or s.strip() == '2':
                    responses.append(s[:100])
    except: pass

print(f'  Frames received: {len(frames_raw)}')
print(f'  Error messages: {errors[:3]}')
print(f'  Short responses with digits: {responses[:5]}')
