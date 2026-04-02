#!/usr/bin/env python3
"""
concurrent_stream_test.py — 先开流再发消息，匹配真实 Windsurf 使用模式
"""
import sys, io, json, struct, time, threading, requests
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, r'e:\道\道生一\一生二\Windsurf无限额度')
from opus46_ultimate import find_ls_port, find_csrf, vault_load, META_TMPL, _get_wam_key

port = find_ls_port()
csrf = find_csrf()
key = vault_load() or _get_wam_key()
print(f"Port: {port}, CSRF: {csrf[:8] if csrf else None}, Key: {key[:20] if key else None}...")

if not all([port, csrf, key]):
    print("Missing params"); sys.exit(1)

meta = {**META_TMPL, 'apiKey': key}
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

# Init cascade
call('InitializeCascadePanelState', {'metadata': meta, 'workspaceTrusted': True})
call('UpdateWorkspaceTrust', {'metadata': meta, 'workspaceTrusted': True})
f1 = call('StartCascade', {'metadata': meta, 'source': 'CORTEX_TRAJECTORY_SOURCE_USER'})
cid = next((json.loads(d).get('cascadeId') for fl,d in f1 if fl==0 and b'cascadeId' in d), None)
print(f'CascadeID: {cid}')

MODEL = 'MODEL_SWE_1_5'
MSG = '1+1=? Reply ONLY with the number.'
frames_collected = []
stream_ready = threading.Event()
stream_done = threading.Event()

def stream_reader():
    """Background: connect to stream and collect frames"""
    sb = json.dumps({'id': cid, 'protocolVersion': 1}).encode()
    try:
        r2 = requests.post(
            f'http://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
            data=b'\x00' + struct.pack('>I', len(sb)) + sb,
            headers=hdr, timeout=90, stream=True)
        buf=b''; t0=time.time(); frame_no=0
        for chunk in r2.iter_content(chunk_size=256):
            buf += chunk
            while len(buf) >= 5:
                nl = struct.unpack('>I', buf[1:5])[0]
                if len(buf) < 5+nl: break
                fl=buf[0]; fr=buf[5:5+nl]; buf=buf[5+nl:]
                frame_no += 1
                elapsed = time.time()-t0
                frames_collected.append((elapsed, fl, len(fr), fr[:500]))
                # Signal ready after first frame
                if frame_no == 1:
                    stream_ready.set()
                if fl == 0x80:  # trailer
                    stream_done.set()
                    return
            if time.time()-t0 > 85:
                break
    except Exception as e:
        print(f'[stream] error: {e}')
    stream_done.set()

# Start stream reader in background
t = threading.Thread(target=stream_reader, daemon=True)
t.start()

# Wait for stream to connect (first frame received)
print('Waiting for stream to connect...')
stream_ready.wait(timeout=10)
print(f'Stream connected. Sending message...')

# Now send message
time.sleep(0.2)  # small delay to ensure stream is fully initialized
call('SendUserCascadeMessage', {
    'metadata': meta, 'cascadeId': cid,
    'items': [{'text': MSG}],
    'cascadeConfig': {'plannerConfig': {'requestedModelUid': MODEL, 'conversational': {}}}
}, timeout=15)
print(f'Message sent at t={time.time():.1f}')

# Wait for stream to complete or timeout
print('Waiting for AI response (up to 90s)...')
stream_done.wait(timeout=90)

# Analyze collected frames
print(f'\n=== Collected {len(frames_collected)} frames ===')
for i, (elapsed, fl, flen, raw) in enumerate(frames_collected):
    if fl == 0x80:
        print(f'  [F{i+1}] @{elapsed:.1f}s TRAILER: {raw[:100]}')
        continue
    try:
        obj = json.loads(raw)
        keys = list(obj.keys()) if isinstance(obj, dict) else ['non-dict']
        print(f'  [F{i+1}] @{elapsed:.1f}s len={flen} keys={keys}')
        
        # Extract all readable strings recursively
        def all_strings(o, depth=0, path=''):
            if depth > 12: return []
            result = []
            if isinstance(o, str):
                if 3 < len(o) < 300 and not o.startswith('Ci') and '\x00' not in o:
                    result.append((path, o))
            elif isinstance(o, dict):
                for k, v in o.items():
                    result.extend(all_strings(v, depth+1, f'{path}.{k}'))
            elif isinstance(o, list):
                for idx, v in enumerate(o):
                    result.extend(all_strings(v, depth+1, f'{path}[{idx}]'))
            return result
        
        strings = all_strings(obj)
        # Show only short strings that look like actual content (not base64)
        for path, s in strings:
            if len(s) < 100 and not s.startswith('Ci') and s.count(' ') < 20:
                print(f'    {path}: {repr(s[:80])}')
    except:
        print(f'  [F{i+1}] @{elapsed:.1f}s len={flen} RAW: {repr(raw[:80])}')

# Look specifically for AI response text
print('\n=== Looking for response content ===')
all_strs = []
for elapsed, fl, flen, raw in frames_collected:
    if fl == 0x80: continue
    try:
        obj = json.loads(raw)
        def walk(o, d=0):
            if d>12: return []
            r=[]
            if isinstance(o,str) and 2<len(o)<200: r.append(o)
            elif isinstance(o,dict): [r.extend(walk(v,d+1)) for v in o.values()]
            elif isinstance(o,list): [r.extend(walk(i,d+1)) for i in o]
            return r
        strs = walk(obj)
        for s in strs:
            if any(c.isdigit() for c in s) or '=' in s:
                all_strs.append((elapsed, s))
    except: pass

print('Strings containing digits or = signs:')
for elapsed, s in all_strs[:20]:
    print(f'  @{elapsed:.1f}s: {repr(s[:100])}')
