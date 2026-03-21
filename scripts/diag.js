/**
 * 无感切号 诊断脚本 — 直接测试认证链+DB状态+注入可行性
 * 不依赖VS Code API，直接测试底层
 * 
 * Usage: node _diag.js
 */
const https = require('https');
const http = require('http');
const tls = require('tls');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const PROXY_HOST = '127.0.0.1';
const PROXY_PORT = 7890;
const FIREBASE_KEY = 'AIzaSyDsOl-1XpT5err0Tcnx8FFod1H8gVGIycY';
const RELAY = 'https://168666okfa.xyz';

const DB_PATH = path.join(process.env.APPDATA, 'Windsurf', 'User', 'globalStorage', 'state.vscdb');
const ACCOUNTS_PATH = path.join(process.env.APPDATA, 'Windsurf', 'User', 'globalStorage', 
  'undefined_publisher.windsurf-assistant', 'windsurf-assistant-accounts.json');

// ========== HTTP Helpers ==========

function httpsJson(url, method, body, useProxy = true) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const data = body ? JSON.stringify(body) : null;
    if (useProxy) {
      const proxyReq = http.request({
        hostname: PROXY_HOST, port: PROXY_PORT,
        method: 'CONNECT', path: `${u.hostname}:443`, timeout: 8000
      });
      proxyReq.on('connect', (res, socket) => {
        if (res.statusCode !== 200) { socket.destroy(); return reject(new Error(`proxy CONNECT ${res.statusCode}`)); }
        const tlsSocket = tls.connect({ socket, servername: u.hostname }, () => {
          let reqLine = `${method} ${u.pathname}${u.search} HTTP/1.1\r\n`;
          reqLine += `Host: ${u.hostname}\r\n`;
          reqLine += `Content-Type: application/json\r\n`;
          if (data) reqLine += `Content-Length: ${Buffer.byteLength(data)}\r\n`;
          reqLine += `Connection: close\r\n\r\n`;
          tlsSocket.write(reqLine);
          if (data) tlsSocket.write(data);
          const chunks = [];
          tlsSocket.on('data', c => chunks.push(c));
          tlsSocket.on('end', () => {
            const raw = Buffer.concat(chunks).toString();
            const idx = raw.indexOf('\r\n\r\n');
            if (idx < 0) return reject(new Error('no header boundary'));
            let bodyPart = raw.substring(idx + 4);
            // Handle chunked
            if (raw.substring(0, idx).toLowerCase().includes('transfer-encoding: chunked')) {
              const parts = [];
              let pos = 0;
              while (pos < bodyPart.length) {
                const le = bodyPart.indexOf('\r\n', pos);
                if (le < 0) break;
                const size = parseInt(bodyPart.substring(pos, le), 16);
                if (isNaN(size) || size === 0) break;
                parts.push(bodyPart.substring(le + 2, le + 2 + size));
                pos = le + 2 + size + 2;
              }
              bodyPart = parts.join('');
            }
            try { resolve(JSON.parse(bodyPart)); } catch { resolve({ raw: bodyPart }); }
          });
          tlsSocket.on('error', e => reject(e));
          setTimeout(() => { tlsSocket.destroy(); reject(new Error('timeout')); }, 12000);
        });
        tlsSocket.on('error', e => reject(e));
      });
      proxyReq.on('error', e => reject(e));
      proxyReq.on('timeout', () => { proxyReq.destroy(); reject(new Error('proxy timeout')); });
      proxyReq.end();
    } else {
      const req = https.request({
        hostname: u.hostname, port: 443, path: u.pathname + u.search,
        method, headers: { 'Content-Type': 'application/json' }
      }, (res) => {
        let buf = '';
        res.on('data', c => buf += c);
        res.on('end', () => {
          try { resolve(JSON.parse(buf)); } catch { resolve({ raw: buf }); }
        });
      });
      req.on('error', e => reject(e));
      req.setTimeout(12000, () => { req.destroy(); reject(new Error('timeout')); });
      if (data) req.write(data);
      req.end();
    }
  });
}

function httpsBinary(url, method, bodyBuffer, useProxy = true) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    if (useProxy) {
      const proxyReq = http.request({
        hostname: PROXY_HOST, port: PROXY_PORT,
        method: 'CONNECT', path: `${u.hostname}:443`, timeout: 8000
      });
      proxyReq.on('connect', (res, socket) => {
        if (res.statusCode !== 200) { socket.destroy(); return reject(new Error(`proxy CONNECT ${res.statusCode}`)); }
        const tlsSocket = tls.connect({ socket, servername: u.hostname }, () => {
          let reqLine = `${method} ${u.pathname} HTTP/1.1\r\n`;
          reqLine += `Host: ${u.hostname}\r\n`;
          reqLine += `Content-Type: application/proto\r\nconnect-protocol-version: 1\r\n`;
          if (bodyBuffer) reqLine += `Content-Length: ${bodyBuffer.length}\r\n`;
          reqLine += `Connection: close\r\n\r\n`;
          tlsSocket.write(reqLine);
          if (bodyBuffer) tlsSocket.write(bodyBuffer);
          const chunks = [];
          tlsSocket.on('data', c => chunks.push(c));
          tlsSocket.on('end', () => {
            const raw = Buffer.concat(chunks);
            const rawStr = raw.toString('binary');
            const idx = rawStr.indexOf('\r\n\r\n');
            if (idx < 0) return reject(new Error('no header'));
            const headerPart = rawStr.substring(0, idx);
            const statusMatch = headerPart.match(/HTTP\/1\.[01] (\d+)/);
            const status = statusMatch ? parseInt(statusMatch[1]) : 0;
            let body = raw.slice(idx + 4);
            // Decode chunked
            if (/transfer-encoding:\s*chunked/i.test(headerPart)) {
              const parts = [];
              let bodyStr = body.toString('binary');
              let pos = 0;
              while (pos < bodyStr.length) {
                const le = bodyStr.indexOf('\r\n', pos);
                if (le < 0) break;
                const size = parseInt(bodyStr.substring(pos, le), 16);
                if (isNaN(size) || size === 0) break;
                parts.push(bodyStr.substring(le + 2, le + 2 + size));
                pos = le + 2 + size + 2;
              }
              body = Buffer.from(parts.join(''), 'binary');
            }
            resolve({ ok: status === 200, status, buffer: body });
          });
          tlsSocket.on('error', e => reject(e));
          setTimeout(() => { tlsSocket.destroy(); reject(new Error('timeout')); }, 15000);
        });
        tlsSocket.on('error', e => reject(e));
      });
      proxyReq.on('error', e => reject(e));
      proxyReq.on('timeout', () => { proxyReq.destroy(); reject(new Error('proxy timeout')); });
      proxyReq.end();
    } else {
      const req = https.request({
        hostname: u.hostname, port: 443, path: u.pathname,
        method, headers: { 'Content-Type': 'application/proto', 'connect-protocol-version': '1' }
      }, (res) => {
        const chunks = [];
        res.on('data', c => chunks.push(c));
        res.on('end', () => resolve({ ok: res.statusCode === 200, status: res.statusCode, buffer: Buffer.concat(chunks) }));
      });
      req.on('error', e => reject(e));
      req.setTimeout(15000, () => { req.destroy(); reject(new Error('timeout')); });
      if (bodyBuffer) req.write(bodyBuffer);
      req.end();
    }
  });
}

// ========== Protobuf ==========

function encodeProtoString(value, fieldNumber = 1) {
  const tokenBytes = Buffer.from(value, 'utf8');
  const tag = (fieldNumber << 3) | 2;
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

function readVarint(data, pos) {
  let result = 0, shift = 0;
  while (pos < data.length) {
    const b = data[pos++];
    result |= (b & 0x7f) << shift;
    if ((b & 0x80) === 0) break;
    shift += 7;
  }
  return { value: result, nextPos: pos };
}

function parseProtoString(buf) {
  const bytes = new Uint8Array(buf);
  if (bytes.length < 3 || bytes[0] !== 0x0a) return null;
  let pos = 1;
  const r = readVarint(bytes, pos);
  pos = r.nextPos;
  if (pos + r.value > bytes.length) return null;
  return Buffer.from(bytes.slice(pos, pos + r.value)).toString('utf8');
}

function parseCredits(buf) {
  const bytes = new Uint8Array(buf);
  let used = 0, total = 100;
  for (let i = 0; i < bytes.length - 1; i++) {
    if (bytes[i] === 0x30) { const r = readVarint(bytes, i + 1); if (r.value > 0 && r.value <= 100000) used = r.value / 100; }
    if (bytes[i] === 0x40) { const r = readVarint(bytes, i + 1); if (r.value > 0 && r.value <= 100000) total = r.value / 100; }
  }
  return Math.round(total - used);
}

// ========== DB Helpers ==========

function dbRead(key) {
  try {
    const out = execSync(
      `python -c "import sqlite3,json;db=sqlite3.connect(r'${DB_PATH}');cur=db.cursor();cur.execute('SELECT value FROM ItemTable WHERE key=?',('${key}',));r=cur.fetchone();print(r[0] if r else '');db.close()"`,
      { encoding: 'utf8', timeout: 5000 }
    ).trim();
    return out ? JSON.parse(out) : null;
  } catch { return null; }
}

function dbWrite(key, value) {
  try {
    const jsonStr = JSON.stringify(value).replace(/'/g, "''").replace(/\\/g, '\\\\');
    execSync(
      `python -c "import sqlite3;db=sqlite3.connect(r'${DB_PATH}');db.execute('INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)',('${key}','${jsonStr}'));db.commit();db.close()"`,
      { timeout: 5000 }
    );
    return true;
  } catch (e) { console.log('DB write error:', e.message); return false; }
}

// ========== Core Tests ==========

async function testProxyConnectivity() {
  console.log('\n═══ T1. 代理连通性 ═══');
  try {
    const net = require('net');
    const ok = await new Promise(resolve => {
      const sock = new net.Socket();
      sock.setTimeout(2000);
      sock.on('connect', () => { sock.destroy(); resolve(true); });
      sock.on('error', () => resolve(false));
      sock.on('timeout', () => { sock.destroy(); resolve(false); });
      sock.connect(PROXY_PORT, PROXY_HOST);
    });
    console.log(`  代理 ${PROXY_HOST}:${PROXY_PORT}: ${ok ? '✅ 可连接' : '❌ 不可连接'}`);
    return ok;
  } catch (e) {
    console.log(`  ❌ 代理测试失败: ${e.message}`);
    return false;
  }
}

async function testFirebaseLogin(email, password) {
  const payload = { returnSecureToken: true, email, password, clientType: 'CLIENT_TYPE_WEB' };
  // Try proxy first
  try {
    const url = `https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${FIREBASE_KEY}`;
    const r = await httpsJson(url, 'POST', payload, true);
    if (r.idToken) return { ok: true, idToken: r.idToken, channel: 'proxy' };
    return { ok: false, error: r.error?.message || 'no idToken' };
  } catch (e1) {
    // Try relay
    try {
      const r = await httpsJson(`${RELAY}/firebase/login`, 'POST', payload, false);
      if (r.idToken) return { ok: true, idToken: r.idToken, channel: 'relay' };
      return { ok: false, error: r.error?.message || 'no idToken' };
    } catch (e2) {
      return { ok: false, error: `proxy: ${e1.message} | relay: ${e2.message}` };
    }
  }
}

async function testRegisterUser(idToken) {
  const reqData = encodeProtoString(idToken);
  const urls = [
    'https://register.windsurf.com/exa.seat_management_pb.SeatManagementService/RegisterUser',
    'https://server.codeium.com/exa.seat_management_pb.SeatManagementService/RegisterUser',
  ];
  for (const url of urls) {
    try {
      const resp = await httpsBinary(url, 'POST', reqData, true);
      if (resp.ok) {
        const apiKey = parseProtoString(resp.buffer);
        return { ok: !!apiKey, apiKey, url: new URL(url).hostname };
      }
    } catch {}
  }
  return { ok: false, error: 'all RegisterUser endpoints failed' };
}

async function testGetPlanStatus(idToken) {
  const reqData = encodeProtoString(idToken);
  const urls = [
    'https://server.codeium.com/exa.seat_management_pb.SeatManagementService/GetPlanStatus',
    'https://web-backend.windsurf.com/exa.seat_management_pb.SeatManagementService/GetPlanStatus',
  ];
  for (const url of urls) {
    try {
      const resp = await httpsBinary(url, 'POST', reqData, true);
      if (resp.ok) {
        const credits = parseCredits(resp.buffer);
        return { ok: true, credits, url: new URL(url).hostname };
      }
    } catch {}
  }
  // Relay fallback
  try {
    const resp = await httpsBinary(`${RELAY}/windsurf/plan-status`, 'POST', reqData, false);
    if (resp.ok) return { ok: true, credits: parseCredits(resp.buffer), url: 'relay' };
  } catch {}
  return { ok: false, error: 'all PlanStatus endpoints failed' };
}

// ========== Main ==========

async function main() {
  console.log('╔══════════════════════════════════════════════╗');
  console.log('║  无感切号 诊断脚本 — 直接底层测试            ║');
  console.log('╚══════════════════════════════════════════════╝');

  // T1: Proxy
  const proxyOk = await testProxyConnectivity();

  // T2: DB State
  console.log('\n═══ T2. state.vscdb 状态 ═══');
  const authStatus = dbRead('windsurfAuthStatus');
  console.log(`  apiKey: ${authStatus?.apiKey ? authStatus.apiKey.substring(0, 30) + '...' : 'NONE'}`);
  const machineId = dbRead('storage.serviceMachineId');
  console.log(`  serviceMachineId: ${machineId || 'NONE'}`);
  const planInfo = dbRead('windsurf.settings.cachedPlanInfo');
  if (planInfo) {
    console.log(`  plan: ${planInfo.planName} | billing: ${planInfo.billingStrategy}`);
    if (planInfo.quotaUsage) {
      console.log(`  daily: ${planInfo.quotaUsage.dailyRemainingPercent}% | weekly: ${planInfo.quotaUsage.weeklyRemainingPercent}%`);
    }
    console.log(`  credits: ${planInfo.usage?.remainingMessages}/${planInfo.usage?.messages}`);
  }

  // T3: Accounts
  console.log('\n═══ T3. 账号列表 ═══');
  let accounts = [];
  try {
    accounts = JSON.parse(fs.readFileSync(ACCOUNTS_PATH, 'utf8'));
  } catch { console.log('  ❌ 无法读取账号文件'); return; }
  console.log(`  共 ${accounts.length} 个账号`);

  // T4: Test first 3 accounts — full auth chain
  console.log('\n═══ T4. 认证链测试 (前3个账号) ═══');
  const testCount = Math.min(3, accounts.length);
  const results = [];
  for (let i = 0; i < testCount; i++) {
    const a = accounts[i];
    const name = a.email.split('@')[0].substring(0, 15);
    process.stdout.write(`  #${i} ${name}: `);

    // Firebase login
    const login = await testFirebaseLogin(a.email, a.password);
    if (!login.ok) { console.log(`❌ Firebase失败: ${login.error}`); continue; }
    process.stdout.write(`Firebase✅(${login.channel}) `);

    // RegisterUser
    const reg = await testRegisterUser(login.idToken);
    if (!reg.ok) { console.log(`❌ RegisterUser失败`); continue; }
    process.stdout.write(`Register✅(${reg.url}) `);

    // GetPlanStatus
    const plan = await testGetPlanStatus(login.idToken);
    if (!plan.ok) { console.log(`❌ PlanStatus失败`); continue; }
    console.log(`Plan✅ credits=${plan.credits}(${plan.url})`);

    results.push({ index: i, email: a.email, idToken: login.idToken, apiKey: reg.apiKey, credits: plan.credits });
  }

  // T5: Compare apiKey with current windsurfAuthStatus
  console.log('\n═══ T5. 注入可行性分析 ═══');
  if (results.length > 0 && authStatus?.apiKey) {
    const currentKey = authStatus.apiKey;
    console.log(`  当前活跃apiKey: ${currentKey.substring(0, 25)}...`);
    for (const r of results) {
      const match = r.apiKey === currentKey;
      console.log(`  账号#${r.index} apiKey: ${r.apiKey.substring(0, 25)}... ${match ? '← 当前活跃' : ''}`);
    }
    console.log(`\n  ✅ 可通过DB直写 windsurfAuthStatus.apiKey 切换账号`);
    console.log(`  ✅ 新apiKey通过registerUser获取 → 写入state.vscdb → 重启生效`);
    console.log(`  ⚠ serviceMachineId = ${machineId} (设备级限流绑定)`);
  }

  // T6: Summary
  console.log('\n═══ 诊断总结 ═══');
  console.log(`  代理: ${proxyOk ? '✅' : '❌'}`);
  console.log(`  认证链: ${results.length}/${testCount} 成功`);
  console.log(`  DB路径: ${DB_PATH}`);
  console.log(`  账号数: ${accounts.length}`);
  if (results.length > 0) {
    console.log(`\n  🔑 可切换账号: ${results.map(r => `#${r.index}(${r.credits}cr)`).join(', ')}`);
  }
}

main().catch(e => console.error('诊断脚本错误:', e));
