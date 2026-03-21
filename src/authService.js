/**
 * Auth Service — Firebase登录 + Protobuf积分查询 + Token缓存
 * 零外部依赖，纯Node.js https/http模块
 *
 * 认证链 (逆向自 Windsurf 1.108.2, 2026-03-20):
 *   1. Firebase登录(email+password) → idToken
 *   2. RegisterUser(idToken) → apiKey  (register.windsurf.com)
 *   3. 注入idToken到Windsurf PROVIDE_AUTH_TOKEN_TO_AUTH_PROVIDER
 *      → Windsurf内部调registerUser → session{accessToken: apiKey}
 *   4. GetPlanStatus(idToken) → 余额(credits/quota)
 *
 * v5.8.0: self-serve.windsurf.com已从Windsurf 1.108.2移除
 *         Auth注入改为idToken直传(Windsurf内部自行registerUser)
 */
const https = require('https');
const http = require('http');
const tls = require('tls');
const fs = require('fs');
const path = require('path');
const os = require('os');

// Dual Firebase API Keys (v5.6.29 primary, v5.0.20 fallback)
const FIREBASE_KEYS = [
  'AIzaSyDsOl-1XpT5err0Tcnx8FFod1H8gVGIycY',  // v5.6.29 (from windsurf.com)
  'AIzaSyDKm6GGxMJfCbNf-k0kPytiGLaqFJpeSac'   // v5.0.20 (legacy)
];

// Relay (works in China without proxy) — 自建优先，第三方降级
const RELAYS = [
  'https://aiotvr.xyz/wam',   // 自建阿里云中转 (笔记本CFW代理)
  'https://168666okfa.xyz',    // 第三方中转 (备选)
];
const RELAY = RELAYS[0];

// Windsurf gRPC endpoints (Connect-RPC over HTTPS)
const PLAN_STATUS_URLS = [
  'https://server.codeium.com/exa.seat_management_pb.SeatManagementService/GetPlanStatus',
  'https://web-backend.windsurf.com/exa.seat_management_pb.SeatManagementService/GetPlanStatus',
];
const REGISTER_URLS = [
  'https://register.windsurf.com/exa.seat_management_pb.SeatManagementService/RegisterUser',
  'https://server.codeium.com/exa.seat_management_pb.SeatManagementService/RegisterUser',
  'https://web-backend.windsurf.com/exa.seat_management_pb.SeatManagementService/RegisterUser',
];

const TOKEN_TTL = 50 * 60 * 1000; // 50 minutes
const PROXY_HOST = '127.0.0.1';
const PROXY_PORTS = [7890, 7897, 7891, 10808, 1080, 8080, 8118, 3128, 9090]; // 按优先级探测
let ACTIVE_PROXY_PORT = 7890; // 当前生效端口（自动探测更新）
let PROXY_CHECKED = false;
let _probeDetail = { source: 'none', verified: false, lastProbe: 0 }; // 探测详情

// 双模式: 'local' = 本地代理, 'relay' = 网站中转(无需VPN)
let ACTIVE_MODE = 'local';

class AuthService {
  constructor(storagePath) {
    this._tokenCache = new Map(); // email -> { idToken, expireTime }
    this._storagePath = storagePath || null;
    this._cachePath = null; // set lazily in _getCachePath()
    this._loadCache();
    // P1 fix: proxy probing is lazy — runs on first network request, not at construction
    // This prevents TCP socket operations during Extension Host activation
  }

  // ========== Proxy Auto-Detection (智能多源探测) ==========

  /** 从系统/环境变量读取代理配置 */
  _detectSystemProxy() {
    const candidates = [];
    // Source 1: Environment variables (HTTP_PROXY, HTTPS_PROXY, ALL_PROXY)
    for (const key of ['HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy', 'ALL_PROXY', 'all_proxy']) {
      const val = process.env[key];
      if (!val) continue;
      try {
        const u = new URL(val);
        const host = u.hostname || '127.0.0.1';
        const port = parseInt(u.port);
        if (port > 0 && port < 65536) {
          candidates.push({ host, port, source: `env:${key}` });
        }
      } catch {}
    }
    // Source 2: Windows registry proxy (best-effort, non-blocking)
    if (process.platform === 'win32') {
      try {
        const { execSync } = require('child_process');
        const out = execSync('reg query "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings" /v ProxyServer 2>nul', { timeout: 2000, encoding: 'utf8' });
        const m = out.match(/ProxyServer\s+REG_SZ\s+(.+)/i);
        if (m) {
          const proxy = m[1].trim();
          // Format: host:port or http=host:port;https=host:port
          const parts = proxy.includes('=') ? proxy.split(';').map(s => s.split('=').pop()) : [proxy];
          for (const p of parts) {
            const [h, pStr] = p.split(':');
            const port = parseInt(pStr);
            if (h && port > 0) candidates.push({ host: h, port, source: 'registry' });
          }
        }
      } catch {}
    }
    return candidates;
  }

  /** TCP端口连通性检测 */
  _tcpProbe(host, port, timeoutMs = 800) {
    return new Promise(resolve => {
      const net = require('net');
      const sock = new net.Socket();
      sock.setTimeout(timeoutMs);
      sock.on('connect', () => { sock.destroy(); resolve(true); });
      sock.on('error', () => resolve(false));
      sock.on('timeout', () => { sock.destroy(); resolve(false); });
      sock.connect(port, host);
    });
  }

  /** 验证代理真正可达外网(不只是端口开放) — 通过代理发HTTP请求到Google */
  _verifyProxyReachability(host, port, timeoutMs = 5000) {
    return new Promise(resolve => {
      try {
        const req = http.request({
          hostname: host, port, method: 'CONNECT',
          path: 'www.google.com:443', timeout: timeoutMs
        });
        req.on('connect', (res, socket) => {
          socket.destroy();
          resolve(res.statusCode === 200);
        });
        req.on('error', () => resolve(false));
        req.on('timeout', () => { req.destroy(); resolve(false); });
        req.end();
      } catch { resolve(false); }
    });
  }

  /** 智能探测本地可用代理：系统代理 → 环境变量 → 端口扫描 → 连通性验证 */
  async _probeProxy() {
    if (PROXY_CHECKED) return;
    const startTs = Date.now();
    // Phase 1: System/env proxy candidates
    const sysCandidates = this._detectSystemProxy();
    for (const c of sysCandidates) {
      const portOk = await this._tcpProbe(c.host, c.port, 600);
      if (portOk) {
        // Quick verify: can it actually reach the internet?
        const reachable = await this._verifyProxyReachability(c.host, c.port, 3000);
        if (reachable) {
          ACTIVE_PROXY_PORT = c.port;
          ACTIVE_MODE = 'local';
          PROXY_CHECKED = true;
          _probeDetail = { source: c.source, verified: true, lastProbe: Date.now(), host: c.host, elapsed: Date.now() - startTs };
          console.log(`WAM: proxy verified via ${c.source} → ${c.host}:${c.port} (${_probeDetail.elapsed}ms)`);
          return;
        }
        // Port open but not reachable — still usable as fallback
        ACTIVE_PROXY_PORT = c.port;
        _probeDetail = { source: c.source, verified: false, lastProbe: Date.now(), host: c.host };
        console.log(`WAM: proxy port open via ${c.source} → ${c.host}:${c.port} (unverified)`);
      }
    }

    // Phase 2: Scan common VPN ports on localhost
    for (const port of PROXY_PORTS) {
      const ok = await this._tcpProbe(PROXY_HOST, port, 600);
      if (ok) {
        ACTIVE_PROXY_PORT = port;
        ACTIVE_MODE = 'local';
        PROXY_CHECKED = true;
        _probeDetail = { source: `scan:${port}`, verified: false, lastProbe: Date.now(), host: PROXY_HOST, elapsed: Date.now() - startTs };
        console.log(`WAM: proxy detected on port ${port} (${_probeDetail.elapsed}ms)`);
        return;
      }
    }

    // Phase 3: No local proxy → relay mode
    ACTIVE_MODE = 'relay';
    PROXY_CHECKED = true;
    _probeDetail = { source: 'none', verified: false, lastProbe: Date.now(), elapsed: Date.now() - startTs };
    console.log(`WAM: no local proxy found, using relay mode (${_probeDetail.elapsed}ms)`);
  }

  /** 强制重新探测（切换网络环境后调用） */
  async reprobeProxy() {
    PROXY_CHECKED = false;
    await this._probeProxy();
    return { mode: ACTIVE_MODE, port: ACTIVE_PROXY_PORT };
  }

  /** 获取当前模式和端口 */
  getProxyStatus() {
    return { mode: ACTIVE_MODE, port: ACTIVE_PROXY_PORT, checked: PROXY_CHECKED, detail: _probeDetail };
  }

  /** 手动切换模式 */
  setMode(mode) {
    if (mode === 'local' || mode === 'relay') {
      ACTIVE_MODE = mode;
      PROXY_CHECKED = true;
      console.log(`WAM: mode switched to ${mode}`);
    }
  }

  /** 手动设置代理端口 */
  setPort(port) {
    if (port > 0 && port < 65536) {
      ACTIVE_PROXY_PORT = port;
      ACTIVE_MODE = 'local';
      PROXY_CHECKED = true;
      console.log(`WAM: proxy port manually set to ${port}`);
    }
  }

  _getCachePath() {
    if (this._cachePath) return this._cachePath;
    if (!this._storagePath) return null;
    try { if (!fs.existsSync(this._storagePath)) fs.mkdirSync(this._storagePath, { recursive: true }); } catch {}
    this._cachePath = path.join(this._storagePath, 'wam-token-cache.json');
    // One-time migration from legacy globalStorage root (P0 fix)
    if (!fs.existsSync(this._cachePath)) {
      try {
        const legacyPath = this._getLegacyCachePath();
        if (legacyPath && fs.existsSync(legacyPath)) {
          fs.copyFileSync(legacyPath, this._cachePath);
          console.log('WAM: migrated token cache from legacy location');
        }
      } catch {}
    }
    return this._cachePath;
  }

  _getLegacyCachePath() {
    const p = process.platform;
    let base;
    if (p === 'win32') {
      base = process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming');
      base = path.join(base, 'Windsurf', 'User', 'globalStorage');
    } else if (p === 'darwin') {
      base = path.join(os.homedir(), 'Library', 'Application Support', 'Windsurf', 'User', 'globalStorage');
    } else {
      base = path.join(os.homedir(), '.config', 'Windsurf', 'User', 'globalStorage');
    }
    return path.join(base, 'wam-token-cache.json');
  }

  // ========== Token Cache (disk-persistent in globalStorage, 50min TTL) ==========

  _loadCache() {
    try {
      const p = this._getCachePath();
      if (!p || !fs.existsSync(p)) return;
      const data = JSON.parse(fs.readFileSync(p, 'utf8'));
      const now = Date.now();
      for (const [email, entry] of Object.entries(data)) {
        if (entry.expireTime > now) {
          this._tokenCache.set(email, entry);
        }
      }
    } catch {}
  }

  _saveCache() {
    try {
      const p = this._getCachePath();
      if (!p) return;
      const obj = {};
      this._tokenCache.forEach((v, k) => { obj[k] = v; });
      fs.writeFileSync(p, JSON.stringify(obj), 'utf8');
    } catch {}
  }

  _getCachedToken(email) {
    const entry = this._tokenCache.get(email);
    if (entry && entry.expireTime > Date.now()) return entry.idToken;
    this._tokenCache.delete(email);
    return null;
  }

  _setCachedToken(email, idToken) {
    this._tokenCache.set(email, { idToken, expireTime: Date.now() + TOKEN_TTL });
    this._saveCache();
  }

  clearTokenCache(email) {
    if (email) this._tokenCache.delete(email);
    else this._tokenCache.clear();
    this._saveCache();
  }

  // ========== HTTP Helpers (with proxy support for China) ==========

  _needsProxy(hostname) {
    return /googleapis\.com|google\.com|codeium\.com|windsurf\.com/.test(hostname);
  }

  /** Create CONNECT tunnel through HTTP proxy, return TLS socket */
  _proxyTunnel(hostname) {
    return new Promise((resolve, reject) => {
      const proxyReq = http.request({
        hostname: PROXY_HOST, port: ACTIVE_PROXY_PORT,
        method: 'CONNECT', path: `${hostname}:443`, timeout: 8000
      });
      proxyReq.on('connect', (res, socket) => {
        if (res.statusCode !== 200) { socket.destroy(); return reject(new Error(`proxy CONNECT ${res.statusCode}`)); }
        const tlsSocket = tls.connect({ socket, servername: hostname, rejectUnauthorized: true }, () => {
          if (tlsSocket.authorized || tlsSocket.alpnProtocol) resolve(tlsSocket);
          else resolve(tlsSocket); // still usable even if not fully authorized
        });
        tlsSocket.on('error', e => reject(e));
      });
      proxyReq.on('error', e => reject(e));
      proxyReq.on('timeout', () => { proxyReq.destroy(); reject(new Error('proxy timeout')); });
      proxyReq.end();
    });
  }

  /** Raw HTTPS request over a TLS socket (for proxy path) */
  _rawRequest(tlsSocket, hostname, pathStr, method, headers, bodyData) {
    return new Promise((resolve, reject) => {
      let reqLine = `${method} ${pathStr} HTTP/1.1\r\n`;
      reqLine += `Host: ${hostname}\r\n`;
      for (const [k, v] of Object.entries(headers)) reqLine += `${k}: ${v}\r\n`;
      if (bodyData) reqLine += `Content-Length: ${Buffer.byteLength(bodyData)}\r\n`;
      reqLine += `Connection: close\r\n\r\n`;
      tlsSocket.write(reqLine);
      if (bodyData) tlsSocket.write(bodyData);

      const chunks = [];
      tlsSocket.on('data', c => chunks.push(c));
      tlsSocket.on('end', () => {
        const raw = Buffer.concat(chunks).toString('binary');
        const idx = raw.indexOf('\r\n\r\n');
        if (idx < 0) return reject(new Error('no HTTP header boundary'));
        const headerPart = raw.substring(0, idx);
        let bodyPart = raw.substring(idx + 4);
        const statusMatch = headerPart.match(/HTTP\/1\.[01] (\d+)/);
        const status = statusMatch ? parseInt(statusMatch[1]) : 0;
        // Decode chunked transfer encoding (P0 fix: Firebase via proxy uses chunked)
        if (/transfer-encoding:\s*chunked/i.test(headerPart)) {
          bodyPart = this._decodeChunked(bodyPart);
        }
        resolve({ status, ok: status === 200, headerPart, bodyBuffer: Buffer.from(bodyPart, 'binary') });
      });
      tlsSocket.on('error', e => reject(e));
      setTimeout(() => { tlsSocket.destroy(); reject(new Error('request timeout')); }, 12000);
    });
  }

  /** Decode HTTP chunked transfer encoding */
  _decodeChunked(raw) {
    const parts = [];
    let pos = 0;
    while (pos < raw.length) {
      const lineEnd = raw.indexOf('\r\n', pos);
      if (lineEnd < 0) break;
      const sizeStr = raw.substring(pos, lineEnd).trim();
      const chunkSize = parseInt(sizeStr, 16);
      if (isNaN(chunkSize) || chunkSize === 0) break;
      const dataStart = lineEnd + 2;
      if (dataStart + chunkSize > raw.length) {
        parts.push(raw.substring(dataStart));
        break;
      }
      parts.push(raw.substring(dataStart, dataStart + chunkSize));
      pos = dataStart + chunkSize + 2; // skip chunk data + trailing \r\n
    }
    return parts.join('');
  }

  _httpsJson(url, method, body, useProxy) {
    return new Promise(async (resolve, reject) => {
      const u = new URL(url);
      const data = body ? JSON.stringify(body) : null;
      // 双模式：relay模式下跳过代理，local模式下按需代理
      let wantProxy;
      if (useProxy !== undefined) wantProxy = useProxy;
      else if (ACTIVE_MODE === 'relay') wantProxy = false;
      else wantProxy = this._needsProxy(u.hostname);

      if (wantProxy) {
        try {
          const sock = await this._proxyTunnel(u.hostname);
          const headers = { 'Content-Type': 'application/json' };
          const resp = await this._rawRequest(sock, u.hostname, u.pathname + u.search, method || 'GET', headers, data);
          try { resolve({ ok: resp.ok, status: resp.status, data: JSON.parse(resp.bodyBuffer.toString('utf8')) }); }
          catch { resolve({ ok: resp.ok, status: resp.status, data: {} }); }
        } catch (e) { reject(e); }
      } else {
        const agent = new https.Agent({ keepAlive: false });
        const req = https.request({
          hostname: u.hostname, port: 443, path: u.pathname + u.search,
          method: method || 'GET', headers: { 'Content-Type': 'application/json' }, agent
        }, (res) => {
          let buf = '';
          res.on('data', c => buf += c);
          res.on('end', () => {
            agent.destroy();
            try { resolve({ ok: res.statusCode === 200, status: res.statusCode, data: JSON.parse(buf) }); }
            catch { resolve({ ok: res.statusCode === 200, status: res.statusCode, data: {} }); }
          });
          res.on('error', () => { agent.destroy(); reject(new Error('response error')); });
        });
        req.on('error', e => { agent.destroy(); reject(e); });
        req.setTimeout(12000, () => { agent.destroy(); req.destroy(); reject(new Error('timeout')); });
        if (data) req.write(data);
        req.end();
      }
    });
  }

  _httpsBinary(url, method, bodyBuffer, useProxy) {
    return new Promise(async (resolve, reject) => {
      const u = new URL(url);
      let wantProxy;
      if (useProxy !== undefined) wantProxy = useProxy;
      else if (ACTIVE_MODE === 'relay') wantProxy = false;
      else wantProxy = this._needsProxy(u.hostname);

      if (wantProxy) {
        try {
          const sock = await this._proxyTunnel(u.hostname);
          const headers = { 'Content-Type': 'application/proto', 'connect-protocol-version': '1' };
          const resp = await this._rawRequest(sock, u.hostname, u.pathname + u.search, method || 'POST', headers, bodyBuffer ? Buffer.from(bodyBuffer) : null);
          resolve({ ok: resp.ok, status: resp.status, buffer: resp.bodyBuffer });
        } catch (e) { reject(e); }
      } else {
        const agent = new https.Agent({ keepAlive: false });
        const headers = { 'Content-Type': 'application/proto', 'connect-protocol-version': '1' };
        const req = https.request({
          hostname: u.hostname, port: 443, path: u.pathname + u.search,
          method: method || 'POST', headers, agent
        }, (res) => {
          const chunks = [];
          res.on('data', c => chunks.push(c));
          res.on('end', () => { agent.destroy(); resolve({ ok: res.statusCode === 200, status: res.statusCode, buffer: Buffer.concat(chunks) }); });
          res.on('error', () => { agent.destroy(); reject(new Error('response error')); });
        });
        req.on('error', e => { agent.destroy(); reject(e); });
        req.setTimeout(12000, () => { agent.destroy(); req.destroy(); reject(new Error('timeout')); });
        if (bodyBuffer) req.write(Buffer.from(bodyBuffer));
        req.end();
      }
    });
  }

  /** Try all relays for JSON endpoint, return first success */
  async _tryRelaysJson(path, body) {
    for (const relay of RELAYS) {
      try {
        const r = await this._httpsJson(`${relay}${path}`, 'POST', body, false);
        if (r.ok) return r;
      } catch {}
    }
    return null;
  }

  /** Try all relays for binary endpoint, return first success */
  async _tryRelaysBinary(path, bodyBuffer) {
    for (const relay of RELAYS) {
      try {
        const r = await this._httpsBinary(`${relay}${path}`, 'POST', bodyBuffer, false);
        if (r && r.ok) return r;
      } catch {}
    }
    return null;
  }

  /** Try request on multiple URLs, return first success */
  async _raceUrls(urls, bodyBuffer) {
    for (const url of urls) {
      try {
        const resp = await this._httpsBinary(url, 'POST', bodyBuffer);
        if (resp.ok) return resp;
      } catch {}
    }
    return null;
  }

  // ========== Firebase Login (双模式: relay优先 or local代理优先) ==========

  async login(email, password, forceFresh = false) {
    // Ensure proxy detection is done
    if (!PROXY_CHECKED) await this._probeProxy();

    // Check cache first
    if (!forceFresh) {
      const cached = this._getCachedToken(email);
      if (cached) return { ok: true, idToken: cached, email, cached: true };
    }

    const payload = { returnSecureToken: true, email, password, clientType: 'CLIENT_TYPE_WEB' };
    const errors = [];

    if (ACTIVE_MODE === 'relay') {
      // ═══ Relay模式（无需VPN，网站中转优先）═══
      // Channel 1: 多Relay降级 (自建→第三方)
      try {
        const r = await this._tryRelaysJson('/firebase/login', payload);
        if (r && r.ok && r.data.idToken) {
          this._setCachedToken(email, r.data.idToken);
          return { ok: true, idToken: r.data.idToken, email: r.data.email || email, channel: 'relay' };
        }
        if (r?.data?.error?.message) errors.push(`relay: ${r.data.error.message}`);
      } catch (e) { errors.push(`relay: ${e.message}`); }

      // Channel 2: 尝试本地代理作为fallback（可能用户中途开了VPN）
      for (const key of FIREBASE_KEYS) {
        try {
          const url = `https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${key}`;
          const r = await this._httpsJson(url, 'POST', payload, true);
          if (r.ok && r.data.idToken) {
            this._setCachedToken(email, r.data.idToken);
            return { ok: true, idToken: r.data.idToken, email: r.data.email || email, channel: `firebase-proxy-${key.slice(-4)}` };
          }
        } catch {}
      }
    } else {
      // ═══ Local模式（本地代理优先）═══
      // Channel 1: Firebase direct with dual keys (via local proxy)
      for (const key of FIREBASE_KEYS) {
        try {
          const url = `https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${key}`;
          const r = await this._httpsJson(url, 'POST', payload);
          if (r.ok && r.data.idToken) {
            this._setCachedToken(email, r.data.idToken);
            return { ok: true, idToken: r.data.idToken, email: r.data.email || email, channel: `firebase-${key.slice(-4)}` };
          }
          if (r.data?.error?.message) errors.push(`firebase: ${r.data.error.message}`);
        } catch (e) { errors.push(`firebase: ${e.message}`); }
      }

      // Channel 2: 多Relay降级（代理失败时自动降级）
      try {
        const r = await this._tryRelaysJson('/firebase/login', payload);
        if (r && r.ok && r.data.idToken) {
          this._setCachedToken(email, r.data.idToken);
          return { ok: true, idToken: r.data.idToken, email: r.data.email || email, channel: 'relay-fallback' };
        }
        if (r?.data?.error?.message) errors.push(`relay: ${r.data.error.message}`);
      } catch (e) { errors.push(`relay: ${e.message}`); }
    }

    return { ok: false, error: errors.join(' | ') || 'All login channels failed' };
  }

  // ========== Protobuf Encoding/Decoding ==========

  _encodeProtoString(value, fieldNumber = 1) {
    const tokenBytes = Buffer.from(value, 'utf8');
    const tag = (fieldNumber << 3) | 2; // wire type 2 = length-delimited
    const lengthBytes = [];
    let len = tokenBytes.length;
    while (len > 127) { lengthBytes.push((len & 0x7f) | 0x80); len >>= 7; }
    lengthBytes.push(len);
    const buf = Buffer.alloc(1 + lengthBytes.length + tokenBytes.length);
    buf[0] = tag;
    Buffer.from(lengthBytes).copy(buf, 1);
    tokenBytes.copy(buf, 1 + lengthBytes.length);
    return buf;
  }

  _readVarint(data, pos) {
    let result = 0, shift = 0;
    while (pos < data.length) {
      const b = data[pos++];
      if (shift < 28) {
        result |= (b & 0x7f) << shift;
      } else {
        result += (b & 0x7f) * (2 ** shift);
      }
      if ((b & 0x80) === 0) break;
      shift += 7;
    }
    return { value: result, nextPos: pos };
  }

  _parseCredits(buf) {
    const bytes = new Uint8Array(buf);
    let used = 0, total = 100;
    // Full buffer scan for field 6 (tag=0x30) and field 8 (tag=0x40)
    for (let i = 0; i < bytes.length - 1; i++) {
      if (bytes[i] === 0x30) {
        const r = this._readVarint(bytes, i + 1);
        if (r.value > 0 && r.value <= 100000) used = r.value / 100;
      }
      if (bytes[i] === 0x40) {
        const r = this._readVarint(bytes, i + 1);
        if (r.value > 0 && r.value <= 100000) total = r.value / 100;
      }
    }
    return Math.round(total - used);
  }

  _parseProtoString(buf) {
    const bytes = new Uint8Array(buf);
    if (bytes.length < 3 || bytes[0] !== 0x0a) return null;
    let pos = 1;
    const lenResult = this._readVarint(bytes, pos);
    pos = lenResult.nextPos;
    const len = lenResult.value;
    if (pos + len > bytes.length) return null;
    return Buffer.from(bytes.slice(pos, pos + len)).toString('utf8');
  }

  // ========== Structure-Aware Protobuf Parser (reverse-engineered from Windsurf source) ==========
  //
  // GetPlanStatusResponse { f1: PlanStatus }
  // PlanStatus { f1: PlanInfo, f2: plan_start, f3: plan_end,
  //   f4: available_flex_credits, f5: used_flow_credits,
  //   f6: used_prompt_credits(int32/100), f7: used_flex_credits,
  //   f8: available_prompt_credits(int32/100), f9: available_flow_credits,
  //   f10: TopUpStatus, f11: was_reduced_by_orphaned, f12: grace_period_status, f13: grace_period_end }
  // PlanInfo { f1: teams_tier, f2: plan_name(str), f6: max_num_premium_chat_messages(int64),
  //   f12: monthly_prompt_credits, f13: monthly_flow_credits, f14: monthly_flex_credit_purchase_amount,
  //   f16: is_enterprise, f17: is_teams, f18: can_buy_more_credits, f32: has_paid_features }
  // TopUpStatus { f1: transaction_status, f2: top_up_enabled, f3: monthly_top_up_amount,
  //   f4: top_up_spent, f5: top_up_increment, f6: top_up_criteria_met }

  /** Parse a single protobuf message level into { fieldNum: [{ value?, bytes?, string? }] } */
  _parseProtoMsg(buf) {
    const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
    const fields = {};
    let pos = 0;
    while (pos < bytes.length) {
      // v5.11.0 FIX: Read tag as varint (fields ≥16 use multi-byte varint tags)
      // Previous bug: single-byte read corrupted fieldNum for field 16+ (e.g. billingStrategy=f35)
      const tagResult = this._readVarint(bytes, pos);
      const tag = tagResult.value;
      pos = tagResult.nextPos;
      const fieldNum = tag >>> 3;
      const wireType = tag & 0x07;
      if (fieldNum === 0 || fieldNum > 1000 || pos > bytes.length) break;
      switch (wireType) {
        case 0: {
          const r = this._readVarint(bytes, pos);
          if (!fields[fieldNum]) fields[fieldNum] = [];
          fields[fieldNum].push({ value: r.value });
          pos = r.nextPos;
          break;
        }
        case 2: {
          const r = this._readVarint(bytes, pos);
          const len = r.value;
          pos = r.nextPos;
          if (len < 0 || len > 65536 || pos + len > bytes.length) { pos = bytes.length; break; }
          const data = bytes.slice(pos, pos + len);
          let str = null;
          try { const s = Buffer.from(data).toString('utf8'); if (/^[\x20-\x7e]+$/.test(s)) str = s; } catch {}
          if (!fields[fieldNum]) fields[fieldNum] = [];
          fields[fieldNum].push({ bytes: data, string: str, length: len });
          pos += len;
          break;
        }
        case 1: {
          if (pos + 8 > bytes.length) { pos = bytes.length; break; }
          if (!fields[fieldNum]) fields[fieldNum] = [];
          fields[fieldNum].push({ bytes: bytes.slice(pos, pos + 8) });
          pos += 8;
          break;
        }
        case 5: {
          if (pos + 4 > bytes.length) { pos = bytes.length; break; }
          if (!fields[fieldNum]) fields[fieldNum] = [];
          fields[fieldNum].push({ bytes: bytes.slice(pos, pos + 4) });
          pos += 4;
          break;
        }
        default: pos = bytes.length;
      }
    }
    return fields;
  }

  /**
   * Structure-aware usage info parser based on reverse-engineered Windsurf protobuf.
   * Returns: { mode, credits, plan, maxPremiumMessages, monthlyCredits, topUp, ... }
   */
  _parseUsageInfo(buf) {
    const result = {
      mode: 'unknown',
      credits: null,              // remaining prompt credits (available - used)
      plan: null,                 // plan_name string ("Free", "Pro", etc.)
      maxPremiumMessages: null,   // max_num_premium_chat_messages (daily limit for premium models)
      monthlyPromptCredits: null, // monthly_prompt_credits allocation
      monthlyFlowCredits: null,   // monthly_flow_credits allocation
      availablePromptCredits: null,
      usedPromptCredits: null,
      availableFlowCredits: null,
      usedFlowCredits: null,
      availableFlexCredits: null,
      usedFlexCredits: null,
      canBuyMore: null,
      isTeams: null,
      isEnterprise: null,
      hasPaidFeatures: null,
      topUp: null,                // { enabled, spent, increment, monthlyAmount }
      planStart: null,
      planEnd: null,
      gracePeriodStatus: null,
      daily: null,                // { used, total, remaining } if detectable
      weekly: null,
      resetTime: null,
      weeklyReset: null,
      extraBalance: null,
    };

    try {
      // Level 0: GetPlanStatusResponse → field 1 = PlanStatus (nested message)
      const outer = this._parseProtoMsg(buf);
      const planStatusEntry = outer[1]?.[0];
      if (!planStatusEntry?.bytes) {
        // Fallback: flat scan (legacy)
        result.credits = this._parseCredits(buf);
        if (result.credits !== null) result.mode = 'credits';
        return result;
      }

      // Level 1: PlanStatus fields
      const ps = this._parseProtoMsg(planStatusEntry.bytes);
      result.usedPromptCredits = ps[6]?.[0]?.value;
      result.availablePromptCredits = ps[8]?.[0]?.value;
      result.usedFlowCredits = ps[5]?.[0]?.value;
      result.availableFlowCredits = ps[9]?.[0]?.value;
      result.availableFlexCredits = ps[4]?.[0]?.value;
      result.usedFlexCredits = ps[7]?.[0]?.value;
      result.gracePeriodStatus = ps[12]?.[0]?.value;

      // Credits calculation (values stored as credits*100)
      const avail = result.availablePromptCredits;
      const used = result.usedPromptCredits;
      if (avail !== undefined && avail !== null) {
        const usedVal = used || 0;
        result.credits = Math.round(avail / 100 - usedVal / 100);
        result.mode = 'credits';
      }

      // Level 2: PlanInfo (PlanStatus field 1)
      const planInfoEntry = ps[1]?.[0];
      if (planInfoEntry?.bytes) {
        const pi = this._parseProtoMsg(planInfoEntry.bytes);
        result.plan = pi[2]?.[0]?.string || null;
        result.maxPremiumMessages = pi[6]?.[0]?.value || null;
        result.monthlyPromptCredits = pi[12]?.[0]?.value || null;
        result.monthlyFlowCredits = pi[13]?.[0]?.value || null;
        result.canBuyMore = pi[18]?.[0]?.value === 1;
        result.isTeams = pi[17]?.[0]?.value === 1;
        result.isEnterprise = pi[16]?.[0]?.value === 1;
        result.hasPaidFeatures = pi[32]?.[0]?.value === 1;
        result.isDevin = pi[36]?.[0]?.value === 1;  // v1.108.2: isDevin flag

        // Parse billing_strategy (field 35) — CREDITS=1, QUOTA=2, ACU=3
        const bs = pi[35]?.[0]?.value;
        result.billingStrategy = bs === 1 ? 'credits' : bs === 2 ? 'quota' : bs === 3 ? 'acu' : null;

        // Log plan info for debugging quota detection
        console.log(`WAM: [PLAN] name=${result.plan} billing=${result.billingStrategy} maxPremium=${result.maxPremiumMessages} monthly=${result.monthlyPromptCredits} credits=${result.credits} canBuy=${result.canBuyMore} isDevin=${result.isDevin}`);
      }

      // Level 2: TopUpStatus (PlanStatus field 10)
      const topUpEntry = ps[10]?.[0];
      if (topUpEntry?.bytes) {
        const tu = this._parseProtoMsg(topUpEntry.bytes);
        result.topUp = {
          enabled: tu[2]?.[0]?.value === 1,
          monthlyAmount: tu[3]?.[0]?.value || 0,
          spent: tu[4]?.[0]?.value || 0,
          increment: tu[5]?.[0]?.value || 0,
          criteriaMet: tu[6]?.[0]?.value === 1,
        };
      }

      // Timestamps (PlanStatus field 2=plan_start, field 3=plan_end, field 13=grace_end)
      // These are Timestamp messages with field 1=seconds, field 2=nanos
      for (const [field, key] of [[2, 'planStart'], [3, 'planEnd'], [13, 'gracePeriodEnd']]) {
        const tsEntry = ps[field]?.[0];
        if (tsEntry?.bytes) {
          const ts = this._parseProtoMsg(tsEntry.bytes);
          if (ts[1]?.[0]?.value) result[key] = ts[1][0].value * 1000; // seconds → ms
        }
      }

      // v7.4: Log plan dates for UFEF debugging
      if (result.planStart || result.planEnd) {
        console.log(`WAM: [PLAN_DATES] start=${result.planStart ? new Date(result.planStart).toLocaleDateString() : 'n/a'} end=${result.planEnd ? new Date(result.planEnd).toLocaleDateString() : 'n/a'} grace=${result.gracePeriodEnd ? new Date(result.gracePeriodEnd).toLocaleDateString() : 'n/a'} daysRemaining=${result.planEnd ? Math.ceil((result.planEnd - Date.now()) / 86400000) : '?'}`);
      }

      // ═══ QUOTA fields (PlanStatus f14-f18, added 2026-03-18 pricing reform) ═══
      // These are the REAL gate under billingStrategy=QUOTA — daily+weekly % limits
      const dailyPct = ps[14]?.[0]?.value;    // daily_quota_remaining_percent (0-100)
      const weeklyPct = ps[15]?.[0]?.value;   // weekly_quota_remaining_percent (0-100)
      const overageMicros = ps[16]?.[0]?.value; // overage_balance_micros (int64, USD÷1M)
      const dailyResetUnix = ps[17]?.[0]?.value;  // daily_quota_reset_at_unix
      const weeklyResetUnix = ps[18]?.[0]?.value; // weekly_quota_reset_at_unix

      if (dailyPct !== undefined && dailyPct !== null) {
        result.daily = {
          used: Math.max(0, Math.min(100, 100 - dailyPct)),
          total: 100,
          remaining: dailyPct,
        };
      }
      if (weeklyPct !== undefined && weeklyPct !== null) {
        result.weekly = {
          used: Math.max(0, Math.min(100, 100 - weeklyPct)),
          total: 100,
          remaining: weeklyPct,
        };
      }
      if (dailyResetUnix) result.resetTime = dailyResetUnix * 1000;
      if (weeklyResetUnix) result.weeklyReset = weeklyResetUnix * 1000;
      if (overageMicros !== undefined) result.extraBalance = overageMicros / 1000000; // → USD

      // ═══ Mode detection (billing_strategy > heuristic) ═══
      if (result.billingStrategy === 'quota' || result.billingStrategy === 'acu') {
        result.mode = 'quota';
      } else if (result.billingStrategy === 'credits') {
        result.mode = 'credits';
      } else if (result.daily && result.daily.remaining !== null) {
        // Fallback: if daily quota fields present, it's quota mode
        result.mode = 'quota';
      } else if (result.maxPremiumMessages && result.maxPremiumMessages > 0) {
        result.mode = result.credits !== null ? 'credits' : 'quota';
      }

      console.log(`WAM: [QUOTA] mode=${result.mode} daily=${dailyPct}% weekly=${weeklyPct}% overage=$${result.extraBalance?.toFixed(2) || '0'} reset=${dailyResetUnix ? new Date(dailyResetUnix*1000).toLocaleTimeString() : 'n/a'}`);

    } catch (e) {
      console.log('WAM: [PARSE] structure parse error, falling back:', e.message);
      result.credits = this._parseCredits(buf);
      if (result.credits !== null) result.mode = 'credits';
    }

    return result;
  }

  // ========== Usage Info Query (adaptive: credits + quota) ==========

  /**
   * Get comprehensive usage info — tries new quota format, falls back to credits
   * Returns: { mode, credits, daily, weekly, plan, resetTime, ... }
   */
  async getUsageInfo(email, password) {
    const loginResult = await this.login(email, password);
    if (!loginResult.ok) return null;

    const reqData = this._encodeProtoString(loginResult.idToken);
    let resp = await this._fetchPlanStatus(reqData);

    if (!resp && loginResult.cached) {
      this.clearTokenCache(email);
      const fresh = await this.login(email, password, true);
      if (fresh.ok) {
        const freshReq = this._encodeProtoString(fresh.idToken);
        resp = await this._fetchPlanStatus(freshReq);
      }
    }

    if (!resp) return null;
    return this._parseUsageInfo(resp.buffer);
  }

  /** Fetch PlanStatus from multi-endpoint (extracted for reuse) */
  async _fetchPlanStatus(reqData) {
    let resp = null;
    if (ACTIVE_MODE === 'relay') {
      resp = await this._tryRelaysBinary('/windsurf/plan-status', reqData);
      if (!resp) resp = await this._raceUrls(PLAN_STATUS_URLS, reqData);
    } else {
      resp = await this._raceUrls(PLAN_STATUS_URLS, reqData);
      if (!resp) resp = await this._tryRelaysBinary('/windsurf/plan-status', reqData);
    }
    return resp;
  }

  // ========== Credits Query (legacy, backward-compatible) ==========

  async getCredits(email, password) {
    const loginResult = await this.login(email, password);
    if (!loginResult.ok) return undefined;

    const reqData = this._encodeProtoString(loginResult.idToken);
    let resp = await this._fetchPlanStatus(reqData);

    // If cached token failed, retry with fresh login
    if (!resp && loginResult.cached) {
      this.clearTokenCache(email);
      const fresh = await this.login(email, password, true);
      if (fresh.ok) {
        const freshReq = this._encodeProtoString(fresh.idToken);
        resp = await this._fetchPlanStatus(freshReq);
      }
    }

    if (!resp) return undefined;
    return this._parseCredits(resp.buffer);
  }

  // ========== RegisterUser → apiKey (for hot injection, mode-aware) ==========

  async registerUser(email, password) {
    const loginResult = await this.login(email, password, true);
    if (!loginResult.ok) return null;

    const reqData = this._encodeProtoString(loginResult.idToken);
    let resp = null;

    if (ACTIVE_MODE === 'relay') {
      // Relay模式: 多relay优先
      resp = await this._tryRelaysBinary('/windsurf/register', reqData);
      if (!resp) resp = await this._raceUrls(REGISTER_URLS, reqData);
    } else {
      // Local模式: 直连优先
      resp = await this._raceUrls(REGISTER_URLS, reqData);
      if (!resp) resp = await this._tryRelaysBinary('/windsurf/register', reqData);
    }

    if (!resp) return null;
    const apiKey = this._parseProtoString(resp.buffer);
    return apiKey ? { apiKey, email, idToken: loginResult.idToken } : null;
  }

  // ========== GetOneTimeAuthToken (legacy v5.0.20 flow, mode-aware) ==========

  // v5.8.0: In Windsurf 1.108.2, PROVIDE_AUTH_TOKEN_TO_AUTH_PROVIDER accepts
  // firebase idToken directly and internally calls registerUser. So the preferred
  // injection path is: login → idToken → inject idToken via command.
  // getOneTimeAuthToken is kept as FALLBACK only (relay path).
  async getOneTimeAuthToken(email, password) {
    const loginResult = await this.login(email, password, true);
    if (!loginResult.ok) return null;

    const reqData = this._encodeProtoString(loginResult.idToken);
    // v5.8.0: self-serve.windsurf.com removed from Windsurf 1.108.2
    // Try relay only (the only known working OneTimeAuthToken endpoint)
    const resp = await this._tryRelaysBinary('/windsurf/auth-token', reqData);
    if (!resp) return null;

    return this._parseProtoString(resp.buffer);
  }

  /** v5.8.0: Get fresh firebase idToken for direct injection into Windsurf command.
   *  This is the PRIMARY auth injection path in Windsurf 1.108.2+.
   *  The command internally calls registerUser(firebaseIdToken) → {apiKey, name} → session */
  async getFreshIdToken(email, password) {
    const loginResult = await this.login(email, password, true);
    if (!loginResult.ok) return null;
    return loginResult.idToken;
  }

  // ========== Cached Quota Reader (reads Windsurf's internal state.vscdb) ==========
  // v5.11.0: With varint tag fix, GetPlanStatus CAN return quota fields (f14-f18).
  // But some accounts may not have quota data yet (first use after 3/18 reform).
  // cachedPlanInfo in state.vscdb is the most reliable source for CURRENT account.

  /**
   * Read real quota % from Windsurf's state.vscdb (cachedPlanInfo).
   * Returns: { daily, weekly, billing, plan, resetTime, weeklyReset, extraBalance } or null
   */
  readCachedQuota() {
    try {
      const p = process.platform;
      let dbPath;
      if (p === 'win32') {
        const appdata = process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming');
        dbPath = path.join(appdata, 'Windsurf', 'User', 'globalStorage', 'state.vscdb');
      } else if (p === 'darwin') {
        dbPath = path.join(os.homedir(), 'Library', 'Application Support', 'Windsurf', 'User', 'globalStorage', 'state.vscdb');
      } else {
        dbPath = path.join(os.homedir(), '.config', 'Windsurf', 'User', 'globalStorage', 'state.vscdb');
      }
      if (!fs.existsSync(dbPath)) return null;

      // Copy to temp to avoid locking issues with Windsurf's open db
      const tmpDb = path.join(os.tmpdir(), 'wam_state_read.vscdb');
      try { fs.copyFileSync(dbPath, tmpDb); } catch { return null; }

      const { execSync } = require('child_process');
      // Use Python for SQLite (available everywhere, avoids native module dependency)
      const pyCmd = `python -c "import sqlite3,json,sys; conn=sqlite3.connect(r'${tmpDb.replace(/\\/g, '\\\\')}'); cur=conn.cursor(); cur.execute('SELECT value FROM ItemTable WHERE key=?',('windsurf.settings.cachedPlanInfo',)); row=cur.fetchone(); print(row[0] if row else ''); conn.close()"`;
      const raw = execSync(pyCmd, { timeout: 5000, encoding: 'utf8' }).trim();
      if (!raw) return null;

      const plan = JSON.parse(raw);
      const q = plan.quotaUsage || {};
      // v6.9: Extract plan dates for official alignment (Trial "Plan ends in X days")
      const planStartRaw = plan.planStartDate || plan.planStart || plan.plan_start;
      const planEndRaw = plan.planEndDate || plan.planEnd || plan.plan_end;
      const planStartMs = planStartRaw ? (typeof planStartRaw === 'number' ? (planStartRaw < 1e12 ? planStartRaw * 1000 : planStartRaw) : Date.parse(planStartRaw)) : null;
      const planEndMs = planEndRaw ? (typeof planEndRaw === 'number' ? (planEndRaw < 1e12 ? planEndRaw * 1000 : planEndRaw) : Date.parse(planEndRaw)) : null;
      const result = {
        daily: q.dailyRemainingPercent !== undefined ? q.dailyRemainingPercent : null,
        weekly: q.weeklyRemainingPercent !== undefined ? q.weeklyRemainingPercent : null,
        billing: plan.billingStrategy || null,
        plan: plan.planName || plan.plan || null,
        email: plan.email || plan.accountEmail || null,
        resetTime: q.dailyResetAtUnix ? q.dailyResetAtUnix * 1000 : null,
        weeklyReset: q.weeklyResetAtUnix ? q.weeklyResetAtUnix * 1000 : null,
        extraBalance: q.overageBalanceMicros ? q.overageBalanceMicros / 1000000 : 0,
        exhausted: (q.dailyRemainingPercent !== undefined && q.dailyRemainingPercent <= 0)
                || (q.weeklyRemainingPercent !== undefined && q.weeklyRemainingPercent <= 0),
        planStart: planStartMs || null,
        planEnd: planEndMs || null,
      };
      console.log(`WAM: [CACHED_QUOTA] daily=${result.daily}% weekly=${result.weekly}% billing=${result.billing} plan=${result.plan} planEnd=${result.planEnd ? new Date(result.planEnd).toLocaleDateString() : 'n/a'} exhausted=${result.exhausted}`);
      return result;
    } catch (e) {
      console.log('WAM: readCachedQuota error:', e.message);
      return null;
    }
  }

  /**
   * Read rate limit state from Windsurf's state.vscdb.
   * Windsurf stores rate limit info in multiple keys — we scan for:
   *   - windsurf.settings.rateLimitState (direct)
   *   - cachedPlanInfo.rateLimitInfo (nested)
   *   - Any key containing 'rateLimit' or 'rate_limit'
   * Returns: { limited, resetAt, resetsInSec, type, model, raw } or null
   */
  readCachedRateLimit() {
    try {
      const p = process.platform;
      let dbPath;
      if (p === 'win32') {
        const appdata = process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming');
        dbPath = path.join(appdata, 'Windsurf', 'User', 'globalStorage', 'state.vscdb');
      } else if (p === 'darwin') {
        dbPath = path.join(os.homedir(), 'Library', 'Application Support', 'Windsurf', 'User', 'globalStorage', 'state.vscdb');
      } else {
        dbPath = path.join(os.homedir(), '.config', 'Windsurf', 'User', 'globalStorage', 'state.vscdb');
      }
      if (!fs.existsSync(dbPath)) return null;

      const tmpDb = path.join(os.tmpdir(), 'wam_rl_read.vscdb');
      try { fs.copyFileSync(dbPath, tmpDb); } catch { return null; }

      const { execSync } = require('child_process');
      // Scan for rate limit related keys in state.vscdb
      const pyCmd = `python -c "
import sqlite3,json,sys
conn=sqlite3.connect(r'${tmpDb.replace(/\\/g, '\\\\')}')
cur=conn.cursor()
# Check multiple potential keys for rate limit state
keys_to_check = [
  'windsurf.settings.cachedPlanInfo',
  'windsurf.rateLimitState',
  'windsurf.settings.rateLimitState',
  'cascade.rateLimitState',
]
results = {}
for k in keys_to_check:
  cur.execute('SELECT value FROM ItemTable WHERE key=?',(k,))
  row = cur.fetchone()
  if row and row[0]:
    results[k] = row[0]
# Also scan for any key containing rateLimit
cur.execute('SELECT key,value FROM ItemTable WHERE key LIKE ? OR key LIKE ?',('%rateLimit%','%rate_limit%'))
for row in cur.fetchall():
  if row[0] not in results:
    results[row[0]] = row[1]
conn.close()
print(json.dumps(results))
"`;
      const raw = execSync(pyCmd, { timeout: 5000, encoding: 'utf8', maxBuffer: 200 * 1024 }).trim();
      if (!raw || raw === '{}') return null;

      const data = JSON.parse(raw);
      const result = { limited: false, resetAt: null, resetsInSec: null, type: null, model: null, raw: {} };

      // Parse cachedPlanInfo for embedded rate limit data
      const cachedPlan = data['windsurf.settings.cachedPlanInfo'];
      if (cachedPlan) {
        try {
          const plan = JSON.parse(cachedPlan);
          // Check for rate limit fields in the plan info
          if (plan.rateLimitInfo || plan.rateLimit) {
            const rl = plan.rateLimitInfo || plan.rateLimit;
            result.limited = true;
            if (rl.resetAt) result.resetAt = typeof rl.resetAt === 'number' ? rl.resetAt : Date.parse(rl.resetAt);
            if (rl.resetsInSeconds) result.resetsInSec = rl.resetsInSeconds;
            if (rl.type) result.type = rl.type;
            if (rl.model) result.model = rl.model;
          }
          // Check quotaUsage for rate limit indicators
          if (plan.quotaUsage) {
            const qu = plan.quotaUsage;
            if (qu.rateLimited || qu.messageRateLimited) {
              result.limited = true;
              if (qu.rateLimitResetAt) result.resetAt = qu.rateLimitResetAt * 1000;
            }
          }
        } catch {}
      }

      // Parse dedicated rate limit state keys
      for (const [key, val] of Object.entries(data)) {
        if (key === 'windsurf.settings.cachedPlanInfo') continue;
        try {
          const parsed = typeof val === 'string' ? JSON.parse(val) : val;
          result.raw[key] = parsed;
          if (parsed.resetAt || parsed.reset_at || parsed.resets_at) {
            result.limited = true;
            const ts = parsed.resetAt || parsed.reset_at || parsed.resets_at;
            result.resetAt = typeof ts === 'number' ? (ts < 1e12 ? ts * 1000 : ts) : Date.parse(ts);
          }
          if (parsed.resetsInSeconds || parsed.resets_in_seconds) {
            result.resetsInSec = parsed.resetsInSeconds || parsed.resets_in_seconds;
          }
          if (parsed.type) result.type = parsed.type;
          if (parsed.model) result.model = parsed.model;
        } catch {}
      }

      // Calculate resetsInSec from resetAt if needed
      if (result.resetAt && !result.resetsInSec) {
        result.resetsInSec = Math.max(0, Math.ceil((result.resetAt - Date.now()) / 1000));
      }

      console.log(`WAM: [CACHED_RL] limited=${result.limited} resetAt=${result.resetAt ? new Date(result.resetAt).toLocaleTimeString() : 'n/a'} resetsIn=${result.resetsInSec}s type=${result.type} keys=${Object.keys(data).join(',')}`);
      return result;
    } catch (e) {
      console.log('WAM: readCachedRateLimit error:', e.message);
      return null;
    }
  }

  // ========== v7.2: Generic state.vscdb value reader ==========

  /** Read any key from state.vscdb (for per-model rate limit detection) */
  readCachedValue(key) {
    try {
      const p = process.platform;
      let dbPath;
      if (p === 'win32') {
        const appdata = process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming');
        dbPath = path.join(appdata, 'Windsurf', 'User', 'globalStorage', 'state.vscdb');
      } else if (p === 'darwin') {
        dbPath = path.join(os.homedir(), 'Library', 'Application Support', 'Windsurf', 'User', 'globalStorage', 'state.vscdb');
      } else {
        dbPath = path.join(os.homedir(), '.config', 'Windsurf', 'User', 'globalStorage', 'state.vscdb');
      }
      if (!fs.existsSync(dbPath)) return null;
      const tmpDb = path.join(os.tmpdir(), `wam_read_${Date.now()}.db`);
      try { fs.copyFileSync(dbPath, tmpDb); } catch { return null; }
      const { execSync } = require('child_process');
      const pyCmd = `python -c "import sqlite3,sys;conn=sqlite3.connect(r'${tmpDb.replace(/\\/g, '\\\\')}');r=conn.cursor().execute('SELECT value FROM ItemTable WHERE key=?',('${key.replace(/'/g, "\\'")}',)).fetchone();print(r[0] if r else '');conn.close()"`;
      const out = execSync(pyCmd, { encoding: 'utf-8', timeout: 5000 }).trim();
      try { fs.unlinkSync(tmpDb); } catch {}
      return out || null;
    } catch {
      return null;
    }
  }

  /** Write model selection to state.vscdb (for per-model rate limit variant switching) */
  writeModelSelection(modelUid) {
    try {
      const p = process.platform;
      let dbPath;
      if (p === 'win32') {
        const appdata = process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming');
        dbPath = path.join(appdata, 'Windsurf', 'User', 'globalStorage', 'state.vscdb');
      } else if (p === 'darwin') {
        dbPath = path.join(os.homedir(), 'Library', 'Application Support', 'Windsurf', 'User', 'globalStorage', 'state.vscdb');
      } else {
        dbPath = path.join(os.homedir(), '.config', 'Windsurf', 'User', 'globalStorage', 'state.vscdb');
      }
      if (!fs.existsSync(dbPath)) return false;
      const { execSync } = require('child_process');
      const escaped = modelUid.replace(/'/g, "\\'");
      const pyCmd = `python -c "import sqlite3,json;conn=sqlite3.connect(r'${dbPath.replace(/\\/g, '\\\\')}');cur=conn.cursor();r=cur.execute('SELECT value FROM ItemTable WHERE key=?',('codeium.windsurf',)).fetchone();d=json.loads(r[0]) if r else {};d['windsurf.state.lastSelectedCascadeModelUids']=['${escaped}'];cur.execute('INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)',('codeium.windsurf',json.dumps(d)));conn.commit();conn.close();print('OK')"`;
      const out = execSync(pyCmd, { encoding: 'utf-8', timeout: 5000 }).trim();
      console.log(`WAM: writeModelSelection(${modelUid}) => ${out}`);
      return out === 'OK';
    } catch (e) {
      console.log(`WAM: writeModelSelection error: ${e.message}`);
      return false;
    }
  }

  // ========== Proactive Rate Limit Capacity Check ==========
  // 逆向自 @exa/chat-client: CheckUserMessageRateLimit 是 Cascade 发送消息前的预检端点
  // 服务端对每个(apiKey, model)维护滑动窗口速率桶，此端点返回精确容量数据
  // WAM主动调用此端点 → 在用户消息失败前获知容量 → 提前切号 = 永不触发rate limit

  // ApiServerService returns 400 (recognized), LanguageServerService returns 404 (missing)
  static CHECK_RATE_LIMIT_URLS = [
    'https://server.codeium.com/exa.api_server_pb.ApiServerService/CheckUserMessageRateLimit',
    'https://web-backend.windsurf.com/exa.api_server_pb.ApiServerService/CheckUserMessageRateLimit',
    'https://server.codeium.com/exa.language_server_pb.LanguageServerService/CheckUserMessageRateLimit',
  ];

  /**
   * Read current session apiKey from state.vscdb windsurfAuthStatus.
   * This is the ACTIVE apiKey that Windsurf uses for all API calls.
   * Returns: string (apiKey) or null
   */
  readCurrentApiKey() {
    try {
      const p = process.platform;
      let dbPath;
      if (p === 'win32') {
        const appdata = process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming');
        dbPath = path.join(appdata, 'Windsurf', 'User', 'globalStorage', 'state.vscdb');
      } else if (p === 'darwin') {
        dbPath = path.join(os.homedir(), 'Library', 'Application Support', 'Windsurf', 'User', 'globalStorage', 'state.vscdb');
      } else {
        dbPath = path.join(os.homedir(), '.config', 'Windsurf', 'User', 'globalStorage', 'state.vscdb');
      }
      if (!fs.existsSync(dbPath)) return null;
      const tmpDb = path.join(os.tmpdir(), 'wam_apikey_read.vscdb');
      try { fs.copyFileSync(dbPath, tmpDb); } catch { return null; }
      const { execSync } = require('child_process');
      const pyCmd = `python -c "import sqlite3,json;conn=sqlite3.connect(r'${tmpDb.replace(/\\/g, '\\\\')}');r=conn.cursor().execute('SELECT value FROM ItemTable WHERE key=?',('windsurfAuthStatus',)).fetchone();conn.close();d=json.loads(r[0]) if r else {};print(d.get('apiKey',''))"`;
      const out = execSync(pyCmd, { encoding: 'utf-8', timeout: 5000, maxBuffer: 200 * 1024 }).trim();
      try { fs.unlinkSync(tmpDb); } catch {}
      return out || null;
    } catch (e) {
      console.log('WAM: readCurrentApiKey error:', e.message);
      return null;
    }
  }

  /**
   * Encode CheckUserMessageRateLimitRequest protobuf
   * Structure (逆向自 @exa/chat-client index.js):
   *   field 1 (metadata): nested message { field 1 (api_key): string }
   *   field 3 (model_uid): string
   */
  _encodeCheckRateLimitRequest(apiKey, modelUid) {
    // Inner: metadata message with api_key as field 1
    const apiKeyBytes = Buffer.from(apiKey, 'utf8');
    const innerTag = 0x0a; // field 1, wire type 2
    const innerLen = this._encodeVarintBuf(apiKeyBytes.length);
    const metadataPayload = Buffer.concat([Buffer.from([innerTag]), innerLen, apiKeyBytes]);

    // Outer field 1: metadata (wire type 2 = length-delimited)
    const outerTag1 = 0x0a; // field 1, wire type 2
    const outerLen1 = this._encodeVarintBuf(metadataPayload.length);

    // Outer field 3: model_uid (wire type 2 = length-delimited)
    const modelBytes = Buffer.from(modelUid, 'utf8');
    const outerTag3 = 0x1a; // field 3, wire type 2 = (3 << 3) | 2
    const outerLen3 = this._encodeVarintBuf(modelBytes.length);

    return Buffer.concat([
      Buffer.from([outerTag1]), outerLen1, metadataPayload,
      Buffer.from([outerTag3]), outerLen3, modelBytes,
    ]);
  }

  /** Encode integer as varint bytes */
  _encodeVarintBuf(value) {
    const bytes = [];
    let v = value;
    while (v > 127) { bytes.push((v & 0x7f) | 0x80); v >>>= 7; }
    bytes.push(v & 0x7f);
    return Buffer.from(bytes);
  }

  /**
   * Parse CheckUserMessageRateLimitResponse protobuf
   * Fields (逆向自 @exa/chat-client):
   *   field 1: has_capacity (bool, T:8)
   *   field 2: message (string, T:9)
   *   field 3: messages_remaining (int32, T:5)
   *   field 4: max_messages (int32, T:5)
   *   field 5: resets_in_seconds (int64, T:3)
   */
  _parseCheckRateLimitResponse(buf) {
    const result = {
      hasCapacity: true,
      message: '',
      messagesRemaining: -1,
      maxMessages: -1,
      resetsInSeconds: 0,
    };
    try {
      const fields = this._parseProtoMsg(buf);
      // field 1: has_capacity (bool as varint — 0=false, 1=true)
      if (fields[1]?.[0]?.value !== undefined) {
        result.hasCapacity = fields[1][0].value !== 0;
      }
      // field 2: message (string)
      if (fields[2]?.[0]?.string) {
        result.message = fields[2][0].string;
      } else if (fields[2]?.[0]?.bytes) {
        try { result.message = Buffer.from(fields[2][0].bytes).toString('utf8'); } catch {}
      }
      // field 3: messages_remaining (int32)
      if (fields[3]?.[0]?.value !== undefined) {
        result.messagesRemaining = fields[3][0].value;
      }
      // field 4: max_messages (int32)
      if (fields[4]?.[0]?.value !== undefined) {
        result.maxMessages = fields[4][0].value;
      }
      // field 5: resets_in_seconds (int64 — may be varint or fixed64)
      if (fields[5]?.[0]?.value !== undefined) {
        result.resetsInSeconds = fields[5][0].value;
      } else if (fields[5]?.[0]?.bytes) {
        // Fixed64 encoding — read as little-endian uint64
        const b = fields[5][0].bytes;
        if (b.length >= 8) {
          result.resetsInSeconds = b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24);
        }
      }
    } catch (e) {
      console.log('WAM: _parseCheckRateLimitResponse error:', e.message);
    }
    return result;
  }

  /**
   * Proactive Rate Limit Capacity Check
   * Calls CheckUserMessageRateLimit gRPC endpoint to get real-time capacity data.
   * Returns: { hasCapacity, message, messagesRemaining, maxMessages, resetsInSeconds } or null
   *
   * @param {string} apiKey - Session apiKey (from windsurfAuthStatus or RegisterUser)
   * @param {string} modelUid - Model UID (e.g. 'claude-opus-4-6-thinking-1m')
   */
  async checkRateLimitCapacity(apiKey, modelUid) {
    if (!apiKey || !modelUid) return null;
    if (!PROXY_CHECKED) await this._probeProxy();

    const reqData = this._encodeCheckRateLimitRequest(apiKey, modelUid);

    // Try direct endpoints first (via proxy if needed)
    for (const url of AuthService.CHECK_RATE_LIMIT_URLS) {
      try {
        const resp = await this._httpsBinary(url, 'POST', reqData);
        if (resp.ok && resp.buffer && resp.buffer.length > 0) {
          const result = this._parseCheckRateLimitResponse(resp.buffer);
          console.log(`WAM: [CAPACITY] hasCapacity=${result.hasCapacity} remaining=${result.messagesRemaining}/${result.maxMessages} resets=${result.resetsInSeconds}s msg="${result.message}" (via ${new URL(url).hostname})`);
          return result;
        }
        // Non-200 but got response — might be error body
        if (resp.buffer && resp.buffer.length > 0) {
          try {
            const errText = resp.buffer.toString('utf8');
            console.log(`WAM: [CAPACITY] non-ok response (${resp.status}): ${errText.substring(0, 200)}`);
          } catch {}
        }
      } catch (e) {
        console.log(`WAM: [CAPACITY] ${new URL(url).hostname} error: ${e.message}`);
      }
    }

    // 多Relay降级 — 自建→第三方
    try {
      const resp = await this._tryRelaysBinary('/windsurf/check-rate-limit', reqData);
      if (resp && resp.buffer && resp.buffer.length > 0) {
        const result = this._parseCheckRateLimitResponse(resp.buffer);
        console.log(`WAM: [CAPACITY] hasCapacity=${result.hasCapacity} remaining=${result.messagesRemaining}/${result.maxMessages} (via relay)`);
        return result;
      }
    } catch {}

    return null;
  }

  dispose() {
    this._saveCache();
  }
}

module.exports = { AuthService };
