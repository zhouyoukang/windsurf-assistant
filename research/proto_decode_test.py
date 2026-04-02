#!/usr/bin/env python3
"""
proto_decode_test.py — 递归解码嵌套 proto binary blobs，找出 AI 响应文本
"""
import sys, io, json, struct, time, threading, requests, base64, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, r'e:\道\道生一\一生二\Windsurf无限额度')
from opus46_ultimate import find_ls_port, find_csrf, vault_load, META_TMPL, _get_wam_key

port = find_ls_port()
csrf = find_csrf()
key = vault_load() or _get_wam_key()
print(f"Port: {port}, CSRF: {csrf[:8] if csrf else None}, Key: {key[:20] if key else None}...")

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
MSG = '1+1=? Reply with ONLY the number 2.'

frames_collected = []
stream_ready = threading.Event()
stream_done = threading.Event()

def stream_reader():
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
                frames_collected.append((elapsed, fl, fr))
                if frame_no == 1: stream_ready.set()
                if fl == 0x80:
                    stream_done.set(); return
            if time.time()-t0 > 85: break
    except Exception as e:
        print(f'[stream] error: {type(e).__name__}: {str(e)[:80]}')
    stream_done.set()

t = threading.Thread(target=stream_reader, daemon=True)
t.start()
stream_ready.wait(timeout=10)
print(f'Stream connected. Sending message...')
time.sleep(0.3)

call('SendUserCascadeMessage', {
    'metadata': meta, 'cascadeId': cid,
    'items': [{'text': MSG}],
    'cascadeConfig': {'plannerConfig': {'requestedModelUid': MODEL, 'conversational': {}}}
}, timeout=15)
print(f'Message sent. Waiting for response...')
stream_done.wait(timeout=90)
print(f'Stream done. {len(frames_collected)} frames total.')


# ── Proto binary string extractor ────────────────────────────────────────────
def extract_proto_strings(data, depth=0, max_depth=8, min_len=3, max_len=500):
    """Recursively extract UTF-8 strings from proto3 binary data."""
    if depth > max_depth or not isinstance(data, (bytes, bytearray)): return []
    strings = []
    i = 0
    while i < len(data):
        try:
            # Parse varint tag
            tag = 0; shift = 0
            while True:
                if i >= len(data): return strings
                b = data[i]; i += 1
                tag |= (b & 0x7F) << shift; shift += 7
                if not (b & 0x80): break
                if shift > 63: break
            wire_type = tag & 0x7
            
            if wire_type == 0:  # varint
                while i < len(data) and (data[i] & 0x80): i += 1
                i += 1
            elif wire_type == 1:  # 64-bit
                i += 8
            elif wire_type == 2:  # length-delimited
                length = 0; shift = 0
                while True:
                    if i >= len(data): return strings
                    b = data[i]; i += 1
                    length |= (b & 0x7F) << shift; shift += 7
                    if not (b & 0x80): break
                    if shift > 35: break
                if i + length > len(data): return strings
                chunk = data[i:i+length]; i += length
                # Try as UTF-8 string
                try:
                    text = chunk.decode('utf-8')
                    if min_len <= len(text) <= max_len and '\x00' not in text:
                        strings.append(text)
                except UnicodeDecodeError:
                    pass
                # Also try as embedded proto message
                sub = extract_proto_strings(chunk, depth+1, max_depth, min_len, max_len)
                strings.extend(sub)
            elif wire_type == 5:  # 32-bit
                i += 4
            else:
                i += 1  # unknown, skip
        except Exception:
            i += 1
    return strings


# ── JSON walk with base64 decode ──────────────────────────────────────────────
_B64 = re.compile(r'^[A-Za-z0-9+/]{16,}={0,2}$')

def extract_all(obj, depth=0):
    """Walk JSON object, find strings and decode base64/proto blobs."""
    if depth > 15: return []
    results = []
    if isinstance(obj, str):
        if _B64.match(obj) and len(obj) > 20:
            # Try to decode as base64 proto
            try:
                binary = base64.b64decode(obj + '==')
                proto_strs = extract_proto_strings(binary)
                results.extend(proto_strs)
            except: pass
        elif 2 < len(obj) < 500:
            results.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            results.extend(extract_all(v, depth+1))
    elif isinstance(obj, list):
        for v in obj:
            results.extend(extract_all(v, depth+1))
    return results


# ── Known system prompt fragments to skip ────────────────────────────────────
SYSTEM_FRAGS = [
    'You are Cascade', 'communication_style', 'tool_calling', 'read_file',
    'run_command', 'grep_search', 'additionalProperties', 'CORTEX_', 'CASCADE_',
    'ask_user_question', 'browser_preview', 'command_status', 'edit_notebook',
    'find_by_name', 'todo_list', 'trajectory_search', 'Making code changes',
    'making_code_changes', 'citation_guidelines', 'Prefer minimal',
    'Before each tool call', 'Long-horizon workflow', 'Verification tools',
    'Progress notes', 'Planning cadence', 'Testing discipline',
    'Bug fixing discipline', 'user_rules', 'MEMORY[', 'MODEL_',
    'Performs a web search', 'Reads a file', 'Spin up a browser',
    'Perform click', 'Fill multiple', 'Handle a dialog', 'Hover over',
    'Navigate to', 'Take a screenshot', 'Type text', 'Wait for text',
    'Save important context', 'Semantic search',
]
_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)

def is_real_response(s):
    if _UUID.match(s): return False
    if _B64.match(s) and len(s) > 20: return False
    if len(s) < 2 or len(s) > 300: return False
    return not any(frag in s for frag in SYSTEM_FRAGS)


# ── Analyze all frames ─────────────────────────────────────────────────────────
print('\n=== Extracting all strings from all frames ===')
all_strs_by_time = []
for elapsed, fl, raw in frames_collected:
    if fl == 0x80: continue
    try:
        obj = json.loads(raw)
        strs = extract_all(obj)
        for s in strs:
            if is_real_response(s):
                all_strs_by_time.append((elapsed, s))
    except: pass

# Deduplicate and show unique strings
seen = set()
unique_responses = []
for elapsed, s in all_strs_by_time:
    if s not in seen:
        seen.add(s)
        unique_responses.append((elapsed, s))

print(f'Total unique real-response strings: {len(unique_responses)}')
print()
for elapsed, s in unique_responses:
    print(f'  @{elapsed:.1f}s: {repr(s[:120])}')

# Also show the last 20 strings to see what appears near the end of stream
print('\n=== Last 20 strings in stream order ===')
for elapsed, s in all_strs_by_time[-20:]:
    print(f'  @{elapsed:.1f}s: {repr(s[:120])}')
