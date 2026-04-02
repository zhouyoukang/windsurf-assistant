"""sonnet46_stream.py — 用 claude-sonnet-4-6 做完整流测试，保存结果"""
import json, sqlite3, struct, time, requests, re

DB = r'C:\Users\Administrator\AppData\Roaming\Windsurf\User\globalStorage\state.vscdb'
con = sqlite3.connect(DB); cur = con.cursor()
cur.execute("SELECT key, value FROM ItemTable"); rows = dict(cur.fetchall()); con.close()
API_KEY = json.loads(rows.get('windsurfAuthStatus','{}')).get('apiKey','')
CSRF = '38a7a689-1e2a-41ff-904b-eefbc9dcacfe'
PORT = 64958
OUT = r'e:\道\道生一\一生二\Windsurf无限额度\sonnet46_result.txt'

META = {"ideName":"Windsurf","ideVersion":"1.108.2","extensionVersion":"3.14.2",
        "extensionName":"Windsurf","extensionPath":r"D:\Windsurf\resources\app\extensions\windsurf",
        "apiKey":API_KEY,"locale":"en-US","os":"win32","url":"https://server.codeium.com"}
HDR = {'Content-Type':'application/grpc-web+json','Accept':'application/grpc-web+json',
       'x-codeium-csrf-token':CSRF,'x-grpc-web':'1'}

def call(m, body, timeout=7):
    b = json.dumps(body).encode()
    r = requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/{m}',
                      data=b'\x00'+struct.pack('>I',len(b))+b, headers=HDR, timeout=timeout, stream=True)
    raw = b''.join(r.iter_content(chunk_size=None))
    frames=[]; pos=0
    while pos+5<=len(raw):
        flag=raw[pos]; n=struct.unpack('>I',raw[pos+1:pos+5])[0]; pos+=5
        frames.append((flag,raw[pos:pos+n])); pos+=n
    return frames

def log(s):
    print(s, flush=True)
    with open(OUT,'a',encoding='utf-8') as f: f.write(s+'\n')

open(OUT,'w').close()
log(f"Test: {time.strftime('%H:%M:%S')} | model: claude-sonnet-4-6")

call("InitializeCascadePanelState", {"metadata":META,"workspaceTrusted":True})
call("UpdateWorkspaceTrust", {"metadata":META,"workspaceTrusted":True})

f1 = call("StartCascade", {"metadata":META,"source":"CORTEX_TRAJECTORY_SOURCE_USER"})
cid = next((json.loads(d).get('cascadeId') for fl,d in f1 if fl==0 and b'cascadeId' in d), None)
log(f"cascade_id: {cid}")

f2 = call("SendUserCascadeMessage", {
    "metadata": META,
    "cascadeId": cid,
    "items": [{"text": "Reply exactly: SONNET_4_6_BACKEND_CONNECTED. Answer: 2+2=?"}],
    "cascadeConfig": {"plannerConfig": {"requestedModelUid": "claude-sonnet-4-6", "conversational": {}}},
})
trailer = next((d.decode('utf-8','replace') for fl,d in f2 if fl==0x80), '')
log(f"Send: {trailer.strip()[:60]}")

# Stream 25s
sb = json.dumps({"id":cid,"protocolVersion":1}).encode()
sd = b'\x00'+struct.pack('>I',len(sb))+sb

all_strings=[]; n=0
def walk(o,d=0):
    if d>25:return
    if isinstance(o,str) and 4<len(o)<500: all_strings.append(o)
    elif isinstance(o,dict): [walk(v,d+1) for v in o.values()]
    elif isinstance(o,list): [walk(i,d+1) for i in o]

try:
    r3=requests.post(f'http://127.0.0.1:{PORT}/exa.language_server_pb.LanguageServerService/StreamCascadeReactiveUpdates',
                     data=sd,headers=HDR,timeout=27,stream=True)
    buf=b''; t0=time.time()
    for chunk in r3.iter_content(chunk_size=128):
        buf+=chunk
        while len(buf)>=5:
            nl=struct.unpack('>I',buf[1:5])[0]
            if len(buf)<5+nl: break
            fl=buf[0]; fr=buf[5:5+nl]; buf=buf[5+nl:]
            if fl==0x80: log(f"TRAILER: {fr.decode('utf-8','replace')[:100]}"); break
            try: walk(json.loads(fr)); n+=1
            except: pass
        if time.time()-t0>25: break
except Exception as e:
    log(f"Stream: {type(e).__name__}: {str(e)[:80]}")

log(f"Frames: {n}, strings: {len(all_strings)}")

SKIP={'MODEL_','grpc-','D:\\','exa.','You are Cascade','The USER','communication',
      'tool_calling','making_code','Before each tool','You have the ability','IMPORTANT',
      'citation','Prefer minimal','Keep dependent','Batch independent'}

unique=[]
seen=set()
for s in all_strings:
    if s not in seen and not any(x in s for x in SKIP) and 5<len(s)<300:
        seen.add(s); unique.append(s)

log("\n=== AI Response Strings ===")
for s in unique:
    if any(x in s for x in ['SONNET','4_6','CONNECTED','2+2','denied','error occurred',
                             'permission','BACKEND','4','answer','Answer']):
        log(f">> {s[:250]}")

log("\n=== All unique strings (last 20) ===")
for s in unique[-20:]:
    log(f"  {repr(s[:150])}")
