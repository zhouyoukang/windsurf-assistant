/**
 * 无感切号 — 直接DB注入切换脚本
 * 绕过VS Code命令系统，直接写入state.vscdb
 * 
 * Usage: node _switch.js [accountIndex]
 *   无参数: 自动选择最优账号
 *   指定索引: 切换到该账号
 */
const https = require('https');
const http = require('http');
const tls = require('tls');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const crypto = require('crypto');

const PROXY_HOST = '127.0.0.1';
const PROXY_PORT = 7890;
const FIREBASE_KEY = 'AIzaSyDsOl-1XpT5err0Tcnx8FFod1H8gVGIycY';

const DB_PATH = path.join(process.env.APPDATA, 'Windsurf', 'User', 'globalStorage', 'state.vscdb');
const ACCOUNTS_PATH = path.join(process.env.APPDATA, 'Windsurf', 'User', 'globalStorage',
  'undefined_publisher.windsurf-assistant', 'windsurf-assistant-accounts.json');

// ========== HTTP (proxy CONNECT tunnel) ==========
function httpsJson(url, method, body) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const data = body ? JSON.stringify(body) : null;
    const proxyReq = http.request({
      hostname: PROXY_HOST, port: PROXY_PORT, method: 'CONNECT',
      path: `${u.hostname}:443`, timeout: 8000
    });
    proxyReq.on('connect', (res, socket) => {
      if (res.statusCode !== 200) { socket.destroy(); return reject(new Error(`CONNECT ${res.statusCode}`)); }
      const tlsSock = tls.connect({ socket, servername: u.hostname }, () => {
        let req = `${method} ${u.pathname}${u.search} HTTP/1.1\r\nHost: ${u.hostname}\r\nContent-Type: application/json\r\n`;
        if (data) req += `Content-Length: ${Buffer.byteLength(data)}\r\n`;
        req += `Connection: close\r\n\r\n`;
        tlsSock.write(req);
        if (data) tlsSock.write(data);
        const chunks = [];
        tlsSock.on('data', c => chunks.push(c));
        tlsSock.on('end', () => {
          const raw = Buffer.concat(chunks).toString();
          const idx = raw.indexOf('\r\n\r\n');
          if (idx < 0) return reject(new Error('no header'));
          let bodyStr = raw.substring(idx + 4);
          if (raw.substring(0, idx).toLowerCase().includes('chunked')) {
            const parts = []; let pos = 0;
            while (pos < bodyStr.length) {
              const le = bodyStr.indexOf('\r\n', pos); if (le < 0) break;
              const sz = parseInt(bodyStr.substring(pos, le), 16); if (!sz) break;
              parts.push(bodyStr.substring(le + 2, le + 2 + sz)); pos = le + 2 + sz + 2;
            }
            bodyStr = parts.join('');
          }
          try { resolve(JSON.parse(bodyStr)); } catch { resolve({ raw: bodyStr }); }
        });
        tlsSock.on('error', reject);
        setTimeout(() => { tlsSock.destroy(); reject(new Error('timeout')); }, 15000);
      });
      tlsSock.on('error', reject);
    });
    proxyReq.on('error', reject);
    proxyReq.on('timeout', () => { proxyReq.destroy(); reject(new Error('proxy timeout')); });
    proxyReq.end();
  });
}

function httpsBin(url, bodyBuf) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const proxyReq = http.request({
      hostname: PROXY_HOST, port: PROXY_PORT, method: 'CONNECT',
      path: `${u.hostname}:443`, timeout: 8000
    });
    proxyReq.on('connect', (res, socket) => {
      if (res.statusCode !== 200) { socket.destroy(); return reject(new Error(`CONNECT ${res.statusCode}`)); }
      const tlsSock = tls.connect({ socket, servername: u.hostname }, () => {
        let req = `POST ${u.pathname} HTTP/1.1\r\nHost: ${u.hostname}\r\nContent-Type: application/proto\r\nconnect-protocol-version: 1\r\n`;
        if (bodyBuf) req += `Content-Length: ${bodyBuf.length}\r\n`;
        req += `Connection: close\r\n\r\n`;
        tlsSock.write(req);
        if (bodyBuf) tlsSock.write(bodyBuf);
        const chunks = [];
        tlsSock.on('data', c => chunks.push(c));
        tlsSock.on('end', () => {
          const raw = Buffer.concat(chunks);
          const rawStr = raw.toString('binary');
          const idx = rawStr.indexOf('\r\n\r\n');
          if (idx < 0) return reject(new Error('no header'));
          const hdr = rawStr.substring(0, idx);
          const st = hdr.match(/HTTP\/1\.[01] (\d+)/);
          let body = raw.slice(idx + 4);
          if (/chunked/i.test(hdr)) {
            const parts = []; let bs = body.toString('binary'), pos = 0;
            while (pos < bs.length) {
              const le = bs.indexOf('\r\n', pos); if (le < 0) break;
              const sz = parseInt(bs.substring(pos, le), 16); if (!sz) break;
              parts.push(bs.substring(le + 2, le + 2 + sz)); pos = le + 2 + sz + 2;
            }
            body = Buffer.from(parts.join(''), 'binary');
          }
          resolve({ ok: (st ? parseInt(st[1]) : 0) === 200, buffer: body });
        });
        tlsSock.on('error', reject);
        setTimeout(() => { tlsSock.destroy(); reject(new Error('timeout')); }, 15000);
      });
      tlsSock.on('error', reject);
    });
    proxyReq.on('error', reject);
    proxyReq.on('timeout', () => { proxyReq.destroy(); reject(new Error('proxy timeout')); });
    proxyReq.end();
  });
}

// ========== Protobuf ==========
function encodeProto(value, field = 1) {
  const b = Buffer.from(value, 'utf8');
  const tag = (field << 3) | 2;
  const lenBytes = []; let len = b.length;
  while (len > 127) { lenBytes.push((len & 0x7f) | 0x80); len >>= 7; }
  lenBytes.push(len);
  const buf = Buffer.alloc(1 + lenBytes.length + b.length);
  buf[0] = tag; Buffer.from(lenBytes).copy(buf, 1); b.copy(buf, 1 + lenBytes.length);
  return buf;
}
function readVarint(d, p) {
  let r = 0, s = 0; while (p < d.length) { const b = d[p++]; r |= (b & 0x7f) << s; if (!(b & 0x80)) break; s += 7; }
  return { value: r, nextPos: p };
}
function parseStr(buf) {
  const b = new Uint8Array(buf);
  if (b.length < 3 || b[0] !== 0x0a) return null;
  const r = readVarint(b, 1);
  if (r.nextPos + r.value > b.length) return null;
  return Buffer.from(b.slice(r.nextPos, r.nextPos + r.value)).toString('utf8');
}
function parseCredits(buf) {
  const b = new Uint8Array(buf); let used = 0, total = 100;
  for (let i = 0; i < b.length - 1; i++) {
    if (b[i] === 0x30) { const r = readVarint(b, i + 1); if (r.value > 0 && r.value <= 100000) used = r.value / 100; }
    if (b[i] === 0x40) { const r = readVarint(b, i + 1); if (r.value > 0 && r.value <= 100000) total = r.value / 100; }
  }
  return Math.round(total - used);
}

// ========== DB ==========
function pyExec(code) {
  return execSync(`python -c "${code}"`, { encoding: 'utf8', timeout: 5000 }).trim();
}
const DB_HELPER = path.join(__dirname, 'db_helper.py');

function dbHelper(cmd, ...args) {
  try {
    return execSync(`python "${DB_HELPER}" ${cmd} ${args.map(a => `"${a}"`).join(' ')}`, 
      { encoding: 'utf8', timeout: 8000 }).trim();
  } catch (e) { return ''; }
}
function dbGet(key) {
  try {
    const r = dbHelper('read', key);
    return r ? JSON.parse(r) : null;
  } catch { return null; }
}
function dbInjectApiKey(newApiKey) {
  return dbHelper('inject_apikey', newApiKey);
}
function dbInjectSession(apiKey, username) {
  return dbHelper('inject_session', apiKey, username);
}
function dbWriteViaFile(key, value) {
  const tmpFile = path.join(__dirname, '_tmp_db_write.json');
  fs.writeFileSync(tmpFile, JSON.stringify(value), 'utf8');
  const result = dbHelper('write', key, tmpFile);
  try { fs.unlinkSync(tmpFile); } catch {}
  return result;
}

// ========== Core ==========
async function firebaseLogin(email, password) {
  const url = `https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${FIREBASE_KEY}`;
  const r = await httpsJson(url, 'POST', { returnSecureToken: true, email, password, clientType: 'CLIENT_TYPE_WEB' });
  return r.idToken ? { ok: true, idToken: r.idToken } : { ok: false, error: r.error?.message };
}

async function registerUser(idToken) {
  const buf = encodeProto(idToken);
  for (const host of ['register.windsurf.com', 'server.codeium.com']) {
    try {
      const r = await httpsBin(`https://${host}/exa.seat_management_pb.SeatManagementService/RegisterUser`, buf);
      if (r.ok) { const k = parseStr(r.buffer); if (k) return { ok: true, apiKey: k }; }
    } catch {}
  }
  return { ok: false };
}

async function getPlanCredits(idToken) {
  const buf = encodeProto(idToken);
  for (const host of ['server.codeium.com', 'web-backend.windsurf.com']) {
    try {
      const r = await httpsBin(`https://${host}/exa.seat_management_pb.SeatManagementService/GetPlanStatus`, buf);
      if (r.ok) return parseCredits(r.buffer);
    } catch {}
  }
  return null;
}

async function switchToAccount(index) {
  const accounts = JSON.parse(fs.readFileSync(ACCOUNTS_PATH, 'utf8'));
  if (index < 0 || index >= accounts.length) { console.error(`Invalid index ${index}, have ${accounts.length}`); return false; }
  const a = accounts[index];
  const name = a.email.split('@')[0];
  
  console.log(`\n🔄 切换到 #${index} ${name}...`);
  
  // Step 1: Firebase login
  process.stdout.write('  Firebase login... ');
  const login = await firebaseLogin(a.email, a.password);
  if (!login.ok) { console.log(`❌ ${login.error}`); return false; }
  console.log('✅');
  
  // Step 2: RegisterUser → apiKey
  process.stdout.write('  RegisterUser... ');
  const reg = await registerUser(login.idToken);
  if (!reg.ok) { console.log('❌'); return false; }
  console.log(`✅ apiKey: ${reg.apiKey.substring(0, 20)}...`);
  
  // Step 3: Get fresh credits
  process.stdout.write('  GetPlanStatus... ');
  const credits = await getPlanCredits(login.idToken);
  console.log(credits !== null ? `✅ ${credits} credits` : '⚠ unknown');
  
  // Step 4: Inject apiKey via DB helper (handles 49KB+ windsurfAuthStatus)
  process.stdout.write('  注入 apiKey... ');
  const injectResult = dbInjectApiKey(reg.apiKey);
  const injOk = injectResult.startsWith('OK');
  console.log(injOk ? `✅ ${injectResult}` : `❌ ${injectResult}`);
  if (!injOk) return false;
  
  // Step 5: Update sessions secret
  process.stdout.write('  更新 session... ');
  const sessResult = dbInjectSession(reg.apiKey, name);
  console.log(sessResult.startsWith('OK') ? `✅` : `⚠ ${sessResult}`);
  
  // Step 6: Update WAM accounts file with fresh credits
  accounts[index].credits = credits;
  accounts[index].lastChecked = Date.now();
  fs.writeFileSync(ACCOUNTS_PATH, JSON.stringify(accounts, null, 2), 'utf8');
  
  // Step 7: Verify
  const verify = dbGet('windsurfAuthStatus');
  const changed = verify?.apiKey?.substring(0, 25) === reg.apiKey.substring(0, 25);
  console.log(`\n  验证: apiKey ${changed ? '✅ 已切换' : '❌ 未变化'}`);
  console.log(`  新apiKey: ${verify?.apiKey?.substring(0, 25)}...`);
  
  if (changed) {
    console.log('\n  ✅ DB注入成功！需要重新加载Windsurf窗口使新session生效');
    console.log('  方式: Ctrl+Shift+P → "Developer: Reload Window"');
    console.log('  或: 插件将自动触发 workbench.action.reloadWindow');
  }
  
  return changed;
}

async function autoSwitch() {
  const accounts = JSON.parse(fs.readFileSync(ACCOUNTS_PATH, 'utf8'));
  const currentAuth = dbGet('windsurfAuthStatus');
  const currentKey = currentAuth?.apiKey;
  
  console.log('🔍 扫描所有账号...');
  let best = -1, bestCredits = -1;
  
  for (let i = 0; i < accounts.length; i++) {
    const a = accounts[i];
    const name = a.email.split('@')[0].substring(0, 12);
    process.stdout.write(`  #${i} ${name}: `);
    
    try {
      const login = await firebaseLogin(a.email, a.password);
      if (!login.ok) { console.log(`❌ ${login.error}`); continue; }
      
      const reg = await registerUser(login.idToken);
      if (!reg.ok) { console.log('❌ register'); continue; }
      
      const isCurrent = reg.apiKey === currentKey;
      const credits = await getPlanCredits(login.idToken);
      accounts[i].credits = credits;
      accounts[i]._apiKey = reg.apiKey;
      accounts[i]._idToken = login.idToken;
      
      console.log(`${credits}cr ${isCurrent ? '← 当前' : ''}`);
      
      if (!isCurrent && credits !== null && credits > bestCredits) {
        bestCredits = credits;
        best = i;
      }
    } catch (e) { console.log(`❌ ${e.message}`); }
  }
  
  fs.writeFileSync(ACCOUNTS_PATH, JSON.stringify(accounts, null, 2), 'utf8');
  
  if (best >= 0) {
    console.log(`\n🏆 最优: #${best} (${bestCredits} credits)`);
    return switchToAccount(best);
  } else {
    console.log('\n⚠ 无更优账号可切换');
    return false;
  }
}

// ========== Entry ==========
async function main() {
  const arg = process.argv[2];
  if (arg !== undefined) {
    const idx = parseInt(arg);
    if (isNaN(idx)) { console.error('Usage: node _switch.js [accountIndex]'); process.exit(1); }
    const ok = await switchToAccount(idx);
    process.exit(ok ? 0 : 1);
  } else {
    const ok = await autoSwitch();
    process.exit(ok ? 0 : 1);
  }
}

main().catch(e => { console.error('Error:', e); process.exit(1); });
