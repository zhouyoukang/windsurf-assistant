#!/usr/bin/env node
/**
 * Quick Switch — 一键切号 (Node.js版, 绕过Python urllib SSL超时)
 * 用法: node quick_switch.js [email]
 *       node quick_switch.js --list     列出所有账号
 *       node quick_switch.js --best     自动选积分最多的账号
 *       node quick_switch.js --all      批量检测所有账号积分
 */
const https = require("https");
const fs = require("fs");
const path = require("path");

const RELAY = "168666okfa.xyz";
const POOL_FILE = path.join(__dirname, "_archive", "_account_pool.json");

function httpsReq(url, opts, data) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const agent = new https.Agent({ keepAlive: false });
    const req = https.request({
      hostname: u.hostname, port: 443, path: u.pathname + u.search,
      method: opts.method || "GET", headers: opts.headers || {}, agent
    }, res => {
      const chunks = []; res.on("data", c => chunks.push(c));
      res.on("end", () => {
        agent.destroy();
        const buf = Buffer.concat(chunks);
        resolve({ ok: res.statusCode === 200, status: res.statusCode, buf,
          json: () => { try { return JSON.parse(buf.toString()); } catch { return {}; } } });
      });
    });
    req.on("error", e => { agent.destroy(); reject(e); });
    req.setTimeout(15000, () => { agent.destroy(); req.destroy(); reject(new Error("timeout")); });
    if (data) req.write(typeof data === "string" ? data : Buffer.from(data));
    req.end();
  });
}

function encodeProto(str) {
  const b = Buffer.from(str, "utf8"); const len = []; let l = b.length;
  while (l > 127) { len.push((l & 0x7f) | 0x80); l >>= 7; } len.push(l);
  return Buffer.concat([Buffer.from([0x0a, ...len]), b]);
}

async function fullChain(email, password) {
  // Step 1: Firebase Login
  const login = await httpsReq(`https://${RELAY}/firebase/login`, {
    method: "POST", headers: { "Content-Type": "application/json" }
  }, JSON.stringify({ returnSecureToken: true, email, password, clientType: "CLIENT_TYPE_WEB" }));
  const d = login.json();
  if (!d.idToken) return { ok: false, step: "firebase", error: d.error?.message || "no idToken" };

  // Step 2: AuthToken
  const proto = encodeProto(d.idToken);
  const auth = await httpsReq(`https://${RELAY}/windsurf/auth-token`, {
    method: "POST", headers: { "Content-Type": "application/proto", "connect-protocol-version": "1" }
  }, proto);
  let token = "";
  if (auth.buf.length > 2 && auth.buf[0] === 0x0a) token = auth.buf.slice(2, 2 + auth.buf[1]).toString("utf8");
  else { const m = auth.buf.toString().match(/[a-zA-Z0-9_-]{35,60}/); if (m) token = m[0]; }
  if (!token || token.length < 30) return { ok: false, step: "authToken", error: "invalid token" };

  // Step 3: Credits + QUOTA parsing
  const cr = await httpsReq(`https://${RELAY}/windsurf/plan-status`, {
    method: "POST", headers: { "Content-Type": "application/proto", "connect-protocol-version": "1" }
  }, proto);
  const b = cr.buf; let used = 0, total = 100;
  let dailyRemaining = -1, weeklyRemaining = -1, dailyResetUnix = 0, weeklyResetUnix = 0;
  // Helper: read varint at position
  function readVarint(buf, pos) {
    let v = 0, s = 0;
    while (pos < buf.length) { const x = buf[pos++]; v |= (x & 0x7f) << s; if (!(x & 0x80)) return [v, pos]; s += 7; }
    return [v, pos];
  }
  // Parse protobuf fields from PlanStatus
  for (let i = 0; i < b.length - 1; i++) {
    // Old credits: field 6 (0x30) = usedPromptCredits, field 8 (0x40) = availablePromptCredits
    if (b[i] === 0x30) { const [v] = readVarint(b, i + 1); if (v > 0 && v <= 10000) used = v / 100; }
    if (b[i] === 0x40) { const [v] = readVarint(b, i + 1); if (v > 0 && v <= 10000) total = v / 100; }
    // QUOTA fields: field 14 (0x70) = dailyRemainingPercent, field 15 (0x78) = weeklyRemainingPercent
    if (b[i] === 0x70) { const [v] = readVarint(b, i + 1); if (v >= 0 && v <= 100) dailyRemaining = v; }
    if (b[i] === 0x78) { const [v] = readVarint(b, i + 1); if (v >= 0 && v <= 100) weeklyRemaining = v; }
    // field 17 (0x88 0x01) = dailyResetAtUnix, field 18 (0x90 0x01) = weeklyResetAtUnix
    if (b[i] === 0x88 && i + 1 < b.length && b[i + 1] === 0x01) { const [v] = readVarint(b, i + 2); if (v > 1700000000) dailyResetUnix = v; }
    if (b[i] === 0x90 && i + 1 < b.length && b[i + 1] === 0x01) { const [v] = readVarint(b, i + 2); if (v > 1700000000) weeklyResetUnix = v; }
  }

  const quota = dailyRemaining >= 0 ? {
    dailyRemaining, weeklyRemaining,
    dailyUsed: Math.max(0, 100 - dailyRemaining),
    weeklyUsed: Math.max(0, 100 - weeklyRemaining),
    effective: Math.min(dailyRemaining, weeklyRemaining),
    dailyResetUnix, weeklyResetUnix,
  } : null;

  return { ok: true, email, token, credits: { used, total, remaining: Math.round(total - used) }, quota, displayName: d.displayName || email.split("@")[0] };
}

function loadAccounts() {
  try { return JSON.parse(fs.readFileSync(POOL_FILE, "utf8")).accounts || []; } catch { return []; }
}

function saveAccountStatus(email, status, credits) {
  try {
    const data = JSON.parse(fs.readFileSync(POOL_FILE, "utf8"));
    const acc = data.accounts.find(a => a.email === email);
    if (acc) {
      acc.status = status;
      acc.last_tested = new Date().toISOString();
      if (credits) acc.messages_used = credits.used;
      if (credits) acc.notes = `remaining:${credits.remaining} ${new Date().toISOString().split("T")[0]}`;
    }
    fs.writeFileSync(POOL_FILE, JSON.stringify(data, null, 2), "utf8");
  } catch {}
}

(async () => {
  const arg = process.argv[2] || "--best";

  if (arg === "--list") {
    const accounts = loadAccounts();
    console.log(`\n  Accounts (${accounts.length}):`);
    accounts.forEach((a, i) => console.log(`  ${i + 1}. ${a.email.padEnd(40)} ${a.status.padEnd(20)} ${a.notes || ""}`));
    return;
  }

  if (arg === "--all") {
    const accounts = loadAccounts().filter(a => !["terminated", "invalid_credentials", "domain_rejected"].includes(a.status));
    console.log(`\n  Checking ${accounts.length} accounts...\n`);
    for (const a of accounts) {
      try {
        const r = await fullChain(a.email, a.password);
        if (r.ok) {
          const qInfo = r.quota ? `D${r.quota.dailyUsed}%·W${r.quota.weeklyUsed}% eff=${r.quota.effective}%` : `remaining: ${r.credits.remaining}`;
          console.log(`  OK  ${a.email.split("@")[0].padEnd(30)} ${qInfo}  token: ${r.token.substring(0, 12)}...`);
          saveAccountStatus(a.email, (r.quota ? r.quota.effective > 10 : r.credits.remaining > 10) ? "verified" : "low_credits", r.credits);
        } else {
          console.log(`  NO  ${a.email.split("@")[0].padEnd(30)} ${r.step}: ${r.error}`);
          saveAccountStatus(a.email, r.step === "firebase" ? "invalid_credentials" : "error");
        }
      } catch (e) { console.log(`  ERR ${a.email.split("@")[0].padEnd(30)} ${e.message}`); }
    }
    console.log("\n  Pool updated.");
    return;
  }

  // --best or specific email
  let email, password;
  if (arg === "--best") {
    const accounts = loadAccounts().filter(a => !["terminated", "invalid_credentials", "domain_rejected"].includes(a.status));
    // Sort by lowest messages_used (most credits remaining)
    accounts.sort((a, b) => (a.messages_used || 0) - (b.messages_used || 0));
    if (!accounts.length) { console.log("No available accounts"); return; }
    email = accounts[0].email;
    password = accounts[0].password;
    console.log(`  Best candidate: ${email.split("@")[0]}`);
  } else {
    const acc = loadAccounts().find(a => a.email === arg || a.email.startsWith(arg));
    if (!acc) { console.log(`Account not found: ${arg}`); return; }
    email = acc.email;
    password = acc.password;
  }

  console.log(`\n  Switching to ${email.split("@")[0]}...`);
  const r = await fullChain(email, password);
  if (r.ok) {
    console.log(`  Firebase:  OK`);
    console.log(`  AuthToken: ${r.token.substring(0, 15)}... (${r.token.length}ch)`);
    console.log(`  Credits:   ${r.credits.remaining}/${r.credits.total}`);
    if (r.quota) console.log(`  Quota:     D${r.quota.dailyUsed}%·W${r.quota.weeklyUsed}% (eff=${r.quota.effective}% remaining)`);
    console.log(`\n  === READY FOR HOT INJECT ===`);
    console.log(`  Token: ${r.token}`);
    console.log(`\n  In Windsurf Command Palette (Ctrl+Shift+P):`);
    console.log(`  → "WS Toolkit: 测试切号" (auto-switch)`);
    console.log(`  → Or paste token in "WS Toolkit: 诊断命令可用性"`);
    saveAccountStatus(email, r.credits.remaining > 10 ? "verified" : "low_credits", r.credits);

    // Write inject-ready file for VSIX to pick up
    const injectFile = path.join(require("os").tmpdir(), "ws-toolkit-inject.json");
    fs.writeFileSync(injectFile, JSON.stringify({ apiKey: r.token, name: r.displayName, email, credits: r.credits, ts: new Date().toISOString() }, null, 2));
    console.log(`  Inject file: ${injectFile}`);
  } else {
    console.log(`  FAILED at ${r.step}: ${r.error}`);
  }
})().catch(e => console.error("Error:", e.message));
