#!/usr/bin/env python3
"""
WS Backend v1.0 — Windsurf续命统一后端
======================================
复用已有4个成熟工具，新增Firebase热注入API，为VSIX薄壳提供全部能力。

启动: python ws_backend.py [port]  (默认19910)
API:
  GET  /                    → 统一Dashboard HTML
  GET  /api/health          → 健康检查
  GET  /api/status          → 积分状态 (credit_toolkit)
  GET  /api/telemetry       → 遥测ID状态 (telemetry_reset)
  GET  /api/patch           → 补丁状态 (patch_continue_bypass)
  GET  /api/accounts        → 账号池列表
  POST /api/firebase/login  → Firebase登录→返回apiKey (供VSIX热注入)
  POST /api/telemetry/reset → 重置遥测ID (需关闭Windsurf)
  POST /api/patch/apply     → 应用补丁 (需关闭Windsurf)
  POST /api/patch/rollback  → 回滚补丁
"""

import json, os, sys, time, sqlite3, hashlib, urllib.request, ssl
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

SCRIPT_DIR = Path(__file__).parent
VERSION = '1.0.0'
PORT = 19910

# ============================================================
# Import existing tools (复用, 不重写!)
# ============================================================
sys.path.insert(0, str(SCRIPT_DIR))

# credit_toolkit — 积分监控
from credit_toolkit import read_plan_info, read_account_usages, MODEL_COSTS

# telemetry_reset — 遥测重置
from telemetry_reset import (
    STORAGE_JSON, STATE_VSCDB, TELEMETRY_KEYS,
    show_current, reset_telemetry, gen_id
)

# patch_continue_bypass — 补丁系统
from patch_continue_bypass import (
    verify_patches, backup_files, apply_p5_parallel_rollout,
    FILES, PATCHES, WINDSURF_BASE, _get_windsurf_version, _file_hash
)

# ============================================================
# Account Pool
# ============================================================
POOL_FILE = SCRIPT_DIR / "_archive" / "_account_pool.json"

def load_accounts():
    if not POOL_FILE.exists():
        return []
    try:
        data = json.loads(POOL_FILE.read_text(encoding='utf-8'))
        return data.get('accounts', [])
    except:
        return []

def save_accounts(accounts):
    POOL_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": "2.0", "accounts": accounts, "current": None, "fingerprints": {}, "history": []}
    if POOL_FILE.exists():
        try:
            old = json.loads(POOL_FILE.read_text(encoding='utf-8'))
            data['current'] = old.get('current')
            data['fingerprints'] = old.get('fingerprints', {})
            data['history'] = old.get('history', [])
        except:
            pass
    POOL_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

# ============================================================
# Firebase Auth (从逆向提取, 用于热注入)
# ============================================================
FIREBASE_API_KEY = "AIzaSyDsOl-1XpT5err0Tcnx8FFod1H8gVGIycY"

# 5.0.20逆向提取的中继端点 (国内直连, 已验证HTTP 200)
RELAY_5020 = "https://168666okfa.xyz"
# 5.6.29逆向提取的中继端点 (需license, 备用)
RELAY_5629 = "https://api.zenghongchao.xyz"

def _http_post(url, payload_bytes, headers=None, timeout=10, binary=False):
    """HTTP POST with retry + optional proxy."""
    hdrs = headers or {"Content-Type": "application/json"}
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"https": proxy}))
    else:
        opener = urllib.request.build_opener()
    req = urllib.request.Request(url, data=payload_bytes, headers=hdrs, method="POST")
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
            if binary:
                return raw
            return json.loads(raw)
    except Exception:
        return None

def _node_firebase(email, password):
    """Firebase login via Node.js subprocess (绕过Python urllib SSL问题)."""
    import subprocess
    script = f"""
const https=require('https');const agent=new https.Agent({{keepAlive:false}});
const req=https.request({{hostname:'168666okfa.xyz',port:443,path:'/firebase/login',method:'POST',headers:{{'Content-Type':'application/json'}},agent}},res=>{{
  let d='';res.on('data',c=>d+=c);res.on('end',()=>{{agent.destroy();process.stdout.write(d);}});}});
req.on('error',e=>{{agent.destroy();process.stdout.write(JSON.stringify({{error:{{message:e.message}}}}));}});
req.setTimeout(12000,()=>{{agent.destroy();req.destroy();process.stdout.write(JSON.stringify({{error:{{message:'timeout'}}}}));}});
req.write(JSON.stringify({{returnSecureToken:true,email:'{email}',password:'{password}',clientType:'CLIENT_TYPE_WEB'}}));req.end();
"""
    try:
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=15)
        if result.stdout:
            return json.loads(result.stdout)
    except:
        pass
    return None

def firebase_login(email, password):
    """Firebase signInWithPassword → idToken. Node.js优先(绕SSL), Python备用."""
    # 路径1: Node.js via 168666okfa.xyz (最可靠, 绕过Python urllib SSL问题)
    try:
        data = _node_firebase(email, password)
        if data and data.get("idToken"):
            return {"ok": True, "idToken": data["idToken"], "email": data.get("email", email),
                    "localId": data.get("localId", ""), "displayName": data.get("displayName", ""),
                    "refreshToken": data.get("refreshToken", ""), "via": "node-relay"}
        if data and data.get("error"):
            err = data["error"]
            return {"ok": False, "error": err.get("message", str(err)) if isinstance(err, dict) else str(err), "via": "node-relay"}
    except:
        pass

    # 路径2: Python直连 (需代理)
    payload = json.dumps({"email": email, "password": password,
                          "returnSecureToken": True, "clientType": "CLIENT_TYPE_WEB"}).encode()
    direct_url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
    try:
        data = _http_post(direct_url, payload, timeout=10)
        if data and data.get("idToken"):
            return {"ok": True, "idToken": data["idToken"], "email": data.get("email", email),
                    "localId": data.get("localId", ""), "displayName": data.get("displayName", ""),
                    "refreshToken": data.get("refreshToken", ""), "via": "python-direct"}
        if data and data.get("error"):
            return {"ok": False, "error": str(data["error"].get("message", data["error"])) if isinstance(data["error"], dict) else str(data["error"])}
    except:
        pass

    return {"ok": False, "error": "All paths failed (node-relay + python-direct)"}


def _encode_proto_string(value, field_number=1):
    """Encode a string as protobuf field (from 5.0.20 reverse)."""
    token_bytes = value.encode('utf-8')
    length = len(token_bytes)
    varint = []
    while length > 127:
        varint.append((length & 0x7f) | 0x80)
        length >>= 7
    varint.append(length)
    tag = (field_number << 3) | 2
    return bytes([tag] + varint) + token_bytes


def register_user(id_token):
    """获取authToken. 三级降级: 5.0.20中继→5.6.29中继→gRPC直连."""
    proto = _encode_proto_string(id_token)
    proto_headers = {"Content-Type": "application/proto", "connect-protocol-version": "1"}

    # 路径1: 5.0.20中继 /windsurf/auth-token (返回authToken, 30-60字符)
    try:
        raw = _http_post(f"{RELAY_5020}/windsurf/auth-token", proto, headers=proto_headers, timeout=10, binary=True)
        if raw and len(raw) > 2:
            # Parse: 0x0A + length + authToken
            if raw[0] == 0x0A:
                tlen = raw[1]
                auth_token = raw[2:2+tlen].decode('utf-8', errors='ignore')
            else:
                auth_token = raw.decode('utf-8', errors='ignore')
                import re
                m = re.search(r'[a-zA-Z0-9_-]{35,60}', auth_token)
                if m:
                    auth_token = m.group(0)
            if auth_token and 30 <= len(auth_token) <= 60:
                return {"ok": True, "apiKey": auth_token, "source": "relay-5020"}
    except:
        pass

    # 路径2: gRPC直连 RegisterUser (需代理或海外)
    grpc_urls = [
        "https://server.codeium.com/exa.seat_management_pb.SeatManagementService/RegisterUser",
        "https://register.windsurf.com/exa.seat_management_pb.SeatManagementService/RegisterUser",
    ]
    for url in grpc_urls:
        try:
            raw = _http_post(url, proto, headers=proto_headers, timeout=12, binary=True)
            if raw:
                api_key = _extract_proto_string(raw, 1)
                if api_key:
                    return {"ok": True, "apiKey": api_key, "source": url}
        except:
            continue

    return {"ok": False, "error": "All auth-token endpoints failed"}


def get_plan_status_online(id_token):
    """gRPC GetPlanStatus → 实时积分. 三级降级: 5.0.20中继→gRPC直连."""
    proto = _encode_proto_string(id_token)
    proto_headers = {"Content-Type": "application/proto", "connect-protocol-version": "1"}

    urls = [
        f"{RELAY_5020}/windsurf/plan-status",  # 5.0.20中继 (优先)
        "https://server.codeium.com/exa.seat_management_pb.SeatManagementService/GetPlanStatus",
        "https://web-backend.windsurf.com/exa.seat_management_pb.SeatManagementService/GetPlanStatus",
    ]

    for url in urls:
        try:
            raw = _http_post(url, proto, headers=proto_headers, timeout=12, binary=True)
            if raw and len(raw) > 10:
                credits = _parse_plan_credits(raw)
                if credits:
                    return {"ok": True, **credits, "source": url}
        except:
            continue
    return {"ok": False, "error": "All GetPlanStatus endpoints failed"}


def _parse_plan_credits(plan_bytes):
    """Parse protobuf GetPlanStatus response for credits (from 5.0.20 reverse)."""
    used_credits = 0
    total_credits = 100
    for i in range(max(0, len(plan_bytes) - 30), len(plan_bytes) - 2):
        if plan_bytes[i] == 0x30:  # field 6: used * 100
            val, _ = _read_varint(plan_bytes, i + 1)
            if 0 < val <= 10000:
                used_credits = val / 100
        if plan_bytes[i] == 0x40:  # field 8: total * 100
            val, _ = _read_varint(plan_bytes, i + 1)
            if 0 < val <= 10000:
                total_credits = val / 100
    remaining = round(total_credits - used_credits)
    return {"total": total_credits, "used": used_credits, "remaining": remaining}


def _read_varint(buf, pos):
    result = 0
    shift = 0
    while pos < len(buf):
        b = buf[pos]
        pos += 1
        result |= (b & 0x7f) << shift
        if (b & 0x80) == 0:
            break
        shift += 7
    return result, pos


def _extract_proto_string(data, field_number):
    """Extract a string field from protobuf binary."""
    i = 0
    while i < len(data):
        if i >= len(data):
            break
        byte = data[i]
        wire_type = byte & 0x07
        field = byte >> 3
        i += 1
        if wire_type == 2:  # length-delimited
            # Read varint length
            length = 0
            shift = 0
            while i < len(data):
                b = data[i]
                i += 1
                length |= (b & 0x7f) << shift
                if (b & 0x80) == 0:
                    break
                shift += 7
            if field == field_number and length > 0 and i + length <= len(data):
                try:
                    return data[i:i+length].decode('utf-8')
                except:
                    pass
            i += length
        elif wire_type == 0:  # varint
            while i < len(data) and (data[i] & 0x80):
                i += 1
            i += 1
        elif wire_type == 1:  # 64-bit
            i += 8
        elif wire_type == 5:  # 32-bit
            i += 4
        else:
            break
    return None


# ============================================================
# Telemetry Status (read-only, no restart needed)
# ============================================================
def get_telemetry_status():
    result = {"storage_path": STORAGE_JSON, "vscdb_path": STATE_VSCDB, "ids": {}}
    if os.path.exists(STORAGE_JSON):
        try:
            data = json.load(open(STORAGE_JSON, 'r', encoding='utf-8'))
            for key in TELEMETRY_KEYS:
                result["ids"][key] = data.get(key, None)
        except:
            pass
    if os.path.exists(STATE_VSCDB):
        try:
            conn = sqlite3.connect(f'file:{STATE_VSCDB}?mode=ro', uri=True)
            cur = conn.cursor()
            cur.execute("SELECT value FROM ItemTable WHERE key='windsurf.settings.cachedPlanInfo'")
            row = cur.fetchone()
            if row:
                plan = json.loads(row[0])
                result["plan"] = plan.get("planName", "?")
                usage = plan.get("usage", {})
                result["remaining"] = usage.get("remainingMessages", 0)
                result["total"] = usage.get("messages", 0)
                result["used"] = usage.get("usedMessages", 0)
            # Count auth records
            cur.execute("SELECT COUNT(*) FROM ItemTable WHERE key LIKE '%windsurf_auth%'")
            result["auth_records"] = cur.fetchone()[0]
            conn.close()
        except Exception as e:
            result["vscdb_error"] = str(e)
    return result


# ============================================================
# Patch Status (read-only)
# ============================================================
def get_patch_status():
    results = verify_patches()
    applied = sum(1 for r in results if r.get("status") == "APPLIED")
    total = len(results)
    return {
        "windsurf_version": _get_windsurf_version(),
        "windsurf_path": str(WINDSURF_BASE),
        "patches": results,
        "applied": applied,
        "total": total,
        "summary": f"{applied}/{total} APPLIED",
    }


# ============================================================
# Dashboard HTML (统一前端, 嵌入后端)
# ============================================================
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WS Toolkit</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#e6edf3;--dim:#8b949e;--accent:#58a6ff;--green:#3fb950;--yellow:#d29922;--red:#f85149;--purple:#bc8cff}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;background:var(--bg);color:var(--text);font-size:13px;padding:12px}
h1{font-size:16px;color:var(--accent);margin-bottom:12px;display:flex;align-items:center;gap:8px}
.grid{display:grid;grid-template-columns:1fr;gap:10px;max-width:480px}
.card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:14px}
.card h3{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin-bottom:8px}
.metric{font-size:28px;font-weight:700}
.metric.ok{color:var(--green)}.metric.warn{color:var(--yellow)}.metric.danger{color:var(--red)}
.sub{font-size:11px;color:var(--dim);margin-top:4px}
.bar{height:6px;background:var(--border);border-radius:3px;margin:6px 0;overflow:hidden}
.bar-fill{height:100%;border-radius:3px;transition:width .5s}
.bar-fill.ok{background:var(--green)}.bar-fill.warn{background:var(--yellow)}.bar-fill.danger{background:var(--red)}
.tag{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
.tag.applied{background:#1a3a1a;color:var(--green)}.tag.not{background:#3a1a1a;color:var(--red)}
.btn{display:block;width:100%;padding:8px;border:1px solid var(--border);border-radius:6px;background:var(--card);color:var(--text);cursor:pointer;font-size:12px;margin-top:6px;transition:all .2s}
.btn:hover{border-color:var(--accent);color:var(--accent)}
.btn.primary{background:var(--accent);color:#000;border-color:var(--accent);font-weight:600}
.btn.primary:hover{opacity:.85}
.btn.danger{border-color:var(--red);color:var(--red)}
.btn.danger:hover{background:var(--red);color:#fff}
.accounts{max-height:200px;overflow-y:auto}
.account{display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid var(--border)}
.account:last-child{border:none}
.account .email{font-size:11px;color:var(--text);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.account .status{font-size:10px}
.patch-row{display:flex;justify-content:space-between;align-items:center;padding:4px 0}
.loading{color:var(--dim);text-align:center;padding:20px}
.toast{position:fixed;top:12px;right:12px;padding:8px 16px;border-radius:6px;font-size:12px;z-index:999;opacity:0;transition:opacity .3s}
.toast.show{opacity:1}
.toast.ok{background:var(--green);color:#000}.toast.err{background:var(--red);color:#fff}
#log{font-family:monospace;font-size:10px;color:var(--dim);max-height:120px;overflow-y:auto;margin-top:8px;white-space:pre-wrap}
</style></head><body>
<h1>&#9889; WS Toolkit</h1>
<div class="grid">
  <div class="card" id="credits-card"><h3>Credits</h3><div class="loading">Loading...</div></div>
  <div class="card" id="patch-card"><h3>Patches</h3><div class="loading">Loading...</div></div>
  <div class="card" id="accounts-card"><h3>Accounts (Hot Switch)</h3><div class="loading">Loading...</div></div>
  <div class="card" id="tools-card"><h3>Tools</h3>
    <button class="btn" onclick="refreshAll()">Refresh All</button>
    <button class="btn danger" onclick="resetTelemetry()">Reset Machine ID (need close WS)</button>
    <button class="btn danger" onclick="applyPatches()">Apply Patches (need close WS)</button>
    <button class="btn" onclick="rollbackPatches()">Rollback Patches</button>
    <div id="log"></div>
  </div>
</div>
<div class="toast" id="toast"></div>
<script>
const API=window._wsBackendUrl||'http://127.0.0.1:"""+str(PORT)+"""';
function $(id){return document.getElementById(id)}
function toast(msg,ok=true){const t=$('toast');t.textContent=msg;t.className='toast show '+(ok?'ok':'err');setTimeout(()=>t.className='toast',2500)}
function log(msg){const l=$('log');l.textContent+=new Date().toLocaleTimeString()+' '+msg+'\\n';l.scrollTop=l.scrollHeight}

async function api(path,method='GET',body=null){
  try{
    const opts={method,headers:{'Content-Type':'application/json'}};
    if(body)opts.body=JSON.stringify(body);
    const r=await fetch(API+path,opts);
    return await r.json();
  }catch(e){return{error:e.message}}
}

async function loadCredits(){
  const d=await api('/api/status');
  if(d.error){$('credits-card').innerHTML='<h3>Credits</h3><div class="sub">'+d.error+'</div>';return}
  const pct=d.total>0?(d.used/d.total*100):0;
  const cls=pct>80?'danger':pct>50?'warn':'ok';
  $('credits-card').innerHTML=`<h3>Credits</h3>
    <div class="metric ${cls}">${d.remaining.toLocaleString()}</div>
    <div class="sub">remaining of ${d.total.toLocaleString()} | ${d.plan}</div>
    <div class="bar"><div class="bar-fill ${cls}" style="width:${pct}%"></div></div>
    <div class="sub">${pct.toFixed(1)}% used | ~${d.daily_rate.toFixed(1)}/day | ${d.days_left.toFixed(0)}d left</div>`;
}

async function loadPatches(){
  const d=await api('/api/patch');
  if(d.error){$('patch-card').innerHTML='<h3>Patches</h3><div class="sub">'+d.error+'</div>';return}
  let html='<h3>Patches ('+d.summary+')</h3><div class="sub">Windsurf '+d.windsurf_version+'</div>';
  d.patches.forEach(p=>{
    const cls=p.status==='APPLIED'?'applied':'not';
    html+=`<div class="patch-row"><span>${p.id}: ${p.desc.substring(0,40)}</span><span class="tag ${cls}">${p.status}</span></div>`;
  });
  $('patch-card').innerHTML=html;
}

async function loadAccounts(){
  const d=await api('/api/accounts');
  if(d.error){$('accounts-card').innerHTML='<h3>Accounts</h3><div class="sub">'+d.error+'</div>';return}
  let html='<h3>Accounts ('+d.available+'/'+d.total+' available)</h3><div class="accounts">';
  (d.accounts||[]).forEach(a=>{
    const cls=a.status==='terminated'?'color:var(--red)':a.status==='untested'?'color:var(--dim)':'color:var(--green)';
    html+=`<div class="account">
      <span class="email">${a.email}</span>
      <span class="status" style="${cls}">${a.status}</span>
      ${a.status!=='terminated'?'<button class="btn" style="width:auto;margin:0;padding:2px 8px;font-size:10px" onclick="hotSwitch(\''+a.email+'\',\''+a.password+'\')">Switch</button>':''}
    </div>`;
  });
  html+='</div>';
  $('accounts-card').innerHTML=html;
}

async function hotSwitch(email,password){
  log('Firebase login: '+email+'...');
  toast('Switching to '+email+'...', true);
  const r=await api('/api/firebase/login','POST',{email,password});
  if(!r.ok){toast(r.error||'Login failed',false);log('ERROR: '+JSON.stringify(r));return}
  log('Firebase OK, registering user...');
  const reg=await api('/api/firebase/register','POST',{idToken:r.idToken});
  if(!reg.ok){toast(reg.error||'Register failed',false);log('ERROR: '+JSON.stringify(reg));return}
  log('apiKey obtained: '+reg.apiKey.substring(0,12)+'...');
  // Signal to VSIX for hot injection (postMessage bridge)
  if(window._vscodeApi){
    window._vscodeApi.postMessage({type:'hotInject',apiKey:reg.apiKey,name:r.displayName||r.email,email:r.email});
    toast('Hot injected! Zero restart!',true);
    log('Hot inject command sent to VSIX');
  }else{
    // Fallback: copy apiKey to clipboard
    navigator.clipboard.writeText(JSON.stringify({apiKey:reg.apiKey,name:r.displayName||r.email}));
    toast('apiKey copied (paste in VSIX command)',true);
    log('apiKey copied to clipboard (no VSIX bridge)');
  }
  setTimeout(loadCredits,3000);
}

async function resetTelemetry(){
  if(!confirm('Reset Machine ID? Windsurf must be CLOSED.'))return;
  log('Resetting telemetry...');
  const r=await api('/api/telemetry/reset','POST');
  toast(r.ok?'Telemetry reset!':r.error,r.ok);log(JSON.stringify(r));
}

async function applyPatches(){
  if(!confirm('Apply patches? Windsurf must be CLOSED.'))return;
  log('Applying patches...');
  const r=await api('/api/patch/apply','POST');
  toast(r.ok?'Patches applied!':r.error,r.ok);log(JSON.stringify(r));
  loadPatches();
}

async function rollbackPatches(){
  if(!confirm('Rollback all patches?'))return;
  log('Rolling back...');
  const r=await api('/api/patch/rollback','POST');
  toast(r.ok?'Rolled back!':r.error,r.ok);log(JSON.stringify(r));
  loadPatches();
}

async function refreshAll(){loadCredits();loadPatches();loadAccounts()}
refreshAll();
setInterval(loadCredits,30000);
</script></body></html>"""


# ============================================================
# HTTP Handler
# ============================================================
class WsHandler(BaseHTTPRequestHandler):

    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _html(self, html):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode())

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}

    def do_OPTIONS(self):
        self._json({})

    def do_GET(self):
        path = urlparse(self.path).path

        if path in ('/', '/dashboard'):
            self._html(DASHBOARD_HTML)

        elif path == '/api/health':
            self._json({'status': 'ok', 'version': VERSION, 'port': PORT})

        elif path == '/api/status':
            info = read_plan_info()
            billing = info.get('billingStrategy', 'credits')
            usage = info.get('usage', {})
            total = usage.get('messages', 0)
            used = usage.get('usedMessages', 0)
            remaining = usage.get('remainingMessages', 0)
            start_ts = info.get('startTimestamp', 0)
            end_ts = info.get('endTimestamp', 0)
            now = datetime.now()
            start_dt = datetime.fromtimestamp(start_ts / 1000) if start_ts else now
            end_dt = datetime.fromtimestamp(end_ts / 1000) if end_ts else None
            days_elapsed = max((now - start_dt).days, 1)
            daily_rate = used / days_elapsed if used > 0 else 0
            days_left = remaining / daily_rate if daily_rate > 0 else 999
            # QUOTA billing: D/W percentages
            quota = info.get('quotaUsage', {})
            daily_remaining = quota.get('dailyRemainingPercent', -1)
            weekly_remaining = quota.get('weeklyRemainingPercent', -1)
            daily_reset = quota.get('dailyResetAtUnix', 0)
            weekly_reset = quota.get('weeklyResetAtUnix', 0)
            overage = quota.get('overageBalanceMicros', 0)
            self._json({
                'plan': info.get('planName', '?'), 'billing': billing,
                'total': total, 'used': used, 'remaining': remaining,
                'daily_rate': daily_rate, 'days_left': days_left,
                'end_date': end_dt.strftime('%Y-%m-%d') if end_dt else None,
                'accounts': len(read_account_usages()),
                'quota': {
                    'daily_remaining': daily_remaining,
                    'weekly_remaining': weekly_remaining,
                    'daily_used': max(0, 100 - daily_remaining) if daily_remaining >= 0 else -1,
                    'weekly_used': max(0, 100 - weekly_remaining) if weekly_remaining >= 0 else -1,
                    'daily_reset_unix': daily_reset,
                    'weekly_reset_unix': weekly_reset,
                    'overage_usd': round(overage / 1e6, 2) if overage else 0,
                } if daily_remaining >= 0 else None,
            })

        elif path == '/api/telemetry':
            self._json(get_telemetry_status())

        elif path == '/api/patch':
            self._json(get_patch_status())

        elif path == '/api/accounts':
            accounts = load_accounts()
            available = sum(1 for a in accounts if a.get('status') != 'terminated')
            self._json({
                'total': len(accounts),
                'available': available,
                'accounts': [{'email': a['email'], 'password': a['password'],
                              'status': a.get('status', 'unknown'),
                              'plan': a.get('plan', 'unknown')} for a in accounts],
            })

        else:
            self._json({'error': 'not found'}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_body()

        if path == '/api/firebase/login':
            email = body.get('email', '')
            password = body.get('password', '')
            if not email or not password:
                self._json({'ok': False, 'error': 'email and password required'})
                return
            result = firebase_login(email, password)
            self._json(result)

        elif path == '/api/firebase/register':
            id_token = body.get('idToken', '')
            if not id_token:
                self._json({'ok': False, 'error': 'idToken required'})
                return
            result = register_user(id_token)
            self._json(result)

        elif path == '/api/telemetry/reset':
            try:
                ok = reset_telemetry(also_cache=body.get('also_cache', True))
                self._json({'ok': ok, 'message': 'Telemetry reset. Restart Windsurf.'})
            except Exception as e:
                self._json({'ok': False, 'error': str(e)})

        elif path == '/api/patch/apply':
            try:
                from patch_continue_bypass import apply_patches as _apply
                _apply()
                status = get_patch_status()
                self._json({'ok': True, 'patches': status})
            except Exception as e:
                self._json({'ok': False, 'error': str(e)})

        elif path == '/api/patch/rollback':
            try:
                from patch_continue_bypass import rollback as _rollback
                _rollback()
                status = get_patch_status()
                self._json({'ok': True, 'patches': status})
            except Exception as e:
                self._json({'ok': False, 'error': str(e)})

        else:
            self._json({'error': 'not found'}, 404)

    def log_message(self, fmt, *args):
        pass  # suppress


# ============================================================
# Entry
# ============================================================
def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    server = HTTPServer(('127.0.0.1', port), WsHandler)
    print(f'WS Backend v{VERSION}')
    print(f'Dashboard: http://127.0.0.1:{port}/')
    print(f'API: http://127.0.0.1:{port}/api/health')
    print(f'VSIX connects to: http://127.0.0.1:{port}')
    print('Press Ctrl+C to stop')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()

if __name__ == '__main__':
    main()
