"""debug_proto.py — 检查 binary proto 响应内容"""
import sys, io, json, struct, re, requests, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SERVER = "https://server.codeium.com"
SVC    = "/exa.language_server_pb.LanguageServerService"
DB     = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'

HDR = {
    'Content-Type': 'application/grpc-web+proto',
    'Accept':       'application/grpc-web+proto',
    'x-grpc-web':   '1',
    'te':           'trailers',
}

con = sqlite3.connect(DB)
KEY = json.loads(con.execute("SELECT value FROM ItemTable WHERE key='windsurfAuthStatus'").fetchone()[0]).get('apiKey','')
con.close()
print(f"Key: {KEY[:30]}...")

def _varint(n):
    b = bytearray()
    while True:
        bits = n & 0x7F; n >>= 7
        b.append(bits | (0x80 if n else 0))
        if not n: break
    return bytes(b)

def pb_str(f, s):
    e = s.encode('utf-8')
    return _varint((f<<3)|2) + _varint(len(e)) + e

def pb_msg(f, data):
    return _varint((f<<3)|2) + _varint(len(data)) + data

def pb_int(f, v):
    return _varint((f<<3)|0) + _varint(v)

def pb_bool(f, v): return pb_int(f, 1 if v else 0)

def frame(b): return b'\x00' + struct.pack('>I', len(b)) + b

def call(method, body, timeout=10):
    r = requests.post(f"{SERVER}{SVC}/{method}", data=frame(body), headers=HDR,
                      timeout=timeout, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    frames = []; pos = 0
    while pos+5 <= len(raw):
        fl = raw[pos]; n = struct.unpack('>I', raw[pos+1:pos+5])[0]; pos+=5
        frames.append((fl, raw[pos:pos+n])); pos+=n
    return r.status_code, frames, raw

def meta(key):
    return (pb_str(1,"Windsurf") + pb_str(2,"1.108.2") + pb_str(3,"3.14.2") +
            pb_str(4,key) + pb_str(14,"https://server.codeium.com"))

def dump_proto(data, indent=0):
    """Dump binary proto with field numbers and values"""
    prefix = "  " * indent
    i = 0
    while i < len(data):
        try:
            tag = 0; shift = 0
            while i < len(data):
                b = data[i]; i+=1
                tag |= (b & 0x7F) << shift; shift+=7
                if not (b & 0x80): break
            if tag == 0: break
            wt = tag & 7; fn = tag >> 3
            if wt == 0:
                v = 0; shift = 0
                while i < len(data):
                    b = data[i]; i+=1
                    v |= (b & 0x7F) << shift; shift+=7
                    if not (b & 0x80): break
                print(f"{prefix}field_{fn}(varint) = {v}")
            elif wt == 2:
                ln = 0; shift = 0
                while i < len(data):
                    b = data[i]; i+=1
                    ln |= (b & 0x7F) << shift; shift+=7
                    if not (b & 0x80): break
                chunk = data[i:i+ln]; i+=ln
                try:
                    s = chunk.decode('utf-8')
                    if all(32 <= ord(c) < 127 or ord(c) > 127 for c in s):
                        print(f"{prefix}field_{fn}(string) = {repr(s[:200])}")
                    else:
                        raise ValueError()
                except:
                    print(f"{prefix}field_{fn}(message/{len(chunk)}b):")
                    dump_proto(chunk, indent+1)
            elif wt == 5: print(f"{prefix}field_{fn}(32bit) = {data[i:i+4].hex()}"); i+=4
            elif wt == 1: print(f"{prefix}field_{fn}(64bit) = {data[i:i+8].hex()}"); i+=8
            else: print(f"{prefix}unknown wt={wt}"); break
        except Exception as e:
            print(f"{prefix}[parse error: {e}]"); break

# Test 1: InitializeCascadePanelState
print("\n=== InitializeCascadePanelState ===")
sc, frames, raw = call("InitializeCascadePanelState",
                        pb_msg(1, meta(KEY)) + pb_bool(3, True))
print(f"HTTP {sc}, {len(raw)}b, {len(frames)} frames")
for fl, data in frames:
    print(f"  frame(fl={fl}, {len(data)}b):")
    dump_proto(data, 2)

# Test 2: StartCascade (try different source values)
for src_field, src_val in [(2,1),(2,0),(2,2),(None,None)]:
    print(f"\n=== StartCascade source=field{src_field}:{src_val} ===")
    body = pb_msg(1, meta(KEY))
    if src_field: body += pb_int(src_field, src_val)
    sc, frames, raw = call("StartCascade", body)
    print(f"HTTP {sc}, {len(raw)}b, {len(frames)} frames")
    for fl, data in frames:
        print(f"  frame(fl={fl}, {len(data)}b):")
        dump_proto(data, 2)
    # Check for UUID in raw response
    uuid_re = re.compile(rb'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)
    uuids = uuid_re.findall(raw)
    if uuids: print(f"  UUIDs in raw: {[u.decode() for u in uuids]}")
    # If got cascadeId, stop
    for fl, data in frames:
        if fl == 0 and len(data) > 0:
            print(f"  raw hex: {data[:50].hex()}")
