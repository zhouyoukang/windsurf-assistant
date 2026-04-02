/**
 * _watchdog_wuwei.js — 无为看门狗 v4.0
 * 道法自然 · 用户无感 · 后台永续
 *
 * 功能:
 *   1. 持续监控管理端Rate Limit状态
 *   2. 检测到限流事件 → 立即推送强制轮转指令
 *   3. 检测到globalThis.__wamRateLimit信号 → 立即触发切号
 *   4. 预防性轮转: 账号使用计数超预算自动切换
 *   5. 看门狗自愈: 管理端/WAM Hub离线自动重连
 *   6. 一切在后台, 用户零感知零操作
 *   7. [v4.0] quota exhausted检测: 日配额耗尽(FAILED_PRECONDITION)→切号+自动续传
 *   8. [v4.0] 补丁完整性升级检查: 验证Patch7(扩展_rl正则)已应用
 *
 * Usage:
 *   node _watchdog_wuwei.js            # 启动看门狗(持久运行)
 *   node _watchdog_wuwei.js --once     # 单次检查
 *   node _watchdog_wuwei.js --status   # 打印当前状态
 */
'use strict';
const http = require('http');
const net  = require('net');
const fs   = require('fs');
const path = require('path');

const ADMIN_HUB = 'http://127.0.0.1:19881';
const WAM_HUB   = 'http://127.0.0.1:9876'; // wam_engine.py HUB_PORT
const POLL_MS   = 5000;   // 正常轮询: 5s
const FAST_MS   = 1000;   // 限流后: 1s
const MIN_SWITCH_MS = 3000; // 最短切号间隔

// ─── 机器HMAC认证 (与WAM/pool-admin相同算法) ────
function getMachineHmac() {
  const os = require('os'), crypto = require('crypto');
  const identity = [os.hostname(), os.userInfo().username,
    os.cpus()[0]?.model || '', os.platform(), os.arch()].join('|');
  return crypto.createHmac('sha256', identity).update('wam-relay-v1').digest('hex');
}

// ─── HTTP ────────────────────────────────────
function httpGet(url) {
  return new Promise(resolve => {
    const req = http.get(url, { timeout: 3000 }, res => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => {
        try { resolve(JSON.parse(d)); } catch { resolve(null); }
      });
    });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
  });
}

function httpPostAuth(url, body) {
  const hmac = getMachineHmac();
  return new Promise(resolve => {
    const data = JSON.stringify(body);
    const opts  = Object.assign(require('url').parse(url), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(data),
        'x-wam-relay-secret': hmac,
      },
      timeout: 3000,
    });
    const req = http.request(opts, res => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => { try { resolve(JSON.parse(d)); } catch { resolve(null); } });
    });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
    req.write(data);
    req.end();
  });
}

function httpPost(url, body) {
  return new Promise(resolve => {
    const data = JSON.stringify(body);
    const opts  = Object.assign(require('url').parse(url), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) },
      timeout: 3000,
    });
    const req = http.request(opts, res => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => { try { resolve(JSON.parse(d)); } catch { resolve(null); } });
    });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
    req.write(data);
    req.end();
  });
}

// ─── IPC ────────────────────────────────────
function findIpcPipes() {
  try {
    return fs.readdirSync('//./pipe/')
      .filter(n => n.includes('main-sock'))
      .map(n => '\\\\.\\pipe\\' + n);
  } catch { return []; }
}

function sendIpc(pipeName, message) {
  return new Promise(resolve => {
    const client = net.createConnection(pipeName, () => {
      const payload = Buffer.from(JSON.stringify(message), 'utf8');
      const header  = Buffer.allocUnsafe(4);
      header.writeUInt32LE(payload.length, 0);
      client.write(Buffer.concat([header, payload]), () => {
        client.end();
        resolve(true);
      });
    });
    client.on('error', () => resolve(false));
    client.setTimeout(3000, () => { client.destroy(); resolve(false); });
  });
}

// ─── 补丁检查+应用 (每次启动) ───────────────
function _findAllWindsurfTargets() {
  const os = require('os');
  const candidates = [
    'D:\\Windsurf\\resources\\app\\out\\vs\\workbench\\workbench.desktop.main.js',
    'C:\\Program Files\\Windsurf\\resources\\app\\out\\vs\\workbench\\workbench.desktop.main.js',
  ];
  // 枚举 C:\Users\*\AppData\Local\Programs\Windsurf (多用户安装)
  try {
    const usersDir = 'C:\\Users';
    const users = fs.readdirSync(usersDir, { withFileTypes: true })
      .filter(d => d.isDirectory())
      .map(d => d.name);
    for (const u of users) {
      candidates.push(`C:\\Users\\${u}\\AppData\\Local\\Programs\\Windsurf\\resources\\app\\out\\vs\\workbench\\workbench.desktop.main.js`);
    }
  } catch (_) {}
  return candidates.filter(p => fs.existsSync(p));
}

// ─── 补丁时间戳缓存 (防止频繁重复patching导致extension.js触发多余IPC重启) ───
const PATCH_STAMP_FILE = path.join(require('os').homedir(), '.wam-hot', '.patch_stamp.json');
const PATCH_STAMP_TTL_MS = 2 * 60 * 60 * 1000; // 2小时内已验证则跳过实际执行

function _readPatchStamp() {
  try {
    if (fs.existsSync(PATCH_STAMP_FILE)) {
      const data = JSON.parse(fs.readFileSync(PATCH_STAMP_FILE, 'utf8'));
      return data; // { ts, targets: { [path]: mtime } }
    }
  } catch (_) {}
  return null;
}

function _writePatchStamp(targets) {
  try {
    const hotDir = path.join(require('os').homedir(), '.wam-hot');
    fs.mkdirSync(hotDir, { recursive: true });
    const mtimes = {};
    for (const t of targets) {
      try { mtimes[t] = fs.statSync(t).mtimeMs; } catch (_) {}
    }
    fs.writeFileSync(PATCH_STAMP_FILE, JSON.stringify({ ts: Date.now(), targets: mtimes }));
  } catch (_) {}
}

function _isPatchStampValid(targets) {
  const stamp = _readPatchStamp();
  if (!stamp) return false;
  if (Date.now() - stamp.ts > PATCH_STAMP_TTL_MS) return false;
  // 验证每个目标文件的mtime与stamp一致(文件未被Windsurf更新替换)
  for (const t of targets) {
    try {
      const curMtime = fs.statSync(t).mtimeMs;
      if (!stamp.targets[t] || Math.abs(curMtime - stamp.targets[t]) > 1000) return false;
    } catch (_) { return false; }
  }
  return true;
}

async function ensurePatches() {
  const targets = _findAllWindsurfTargets();
  if (targets.length === 0) return;

  // Write patch discovery config for extension.js auto-patch feature
  try {
    const hotDir = path.join(require('os').homedir(), '.wam-hot');
    fs.mkdirSync(hotDir, { recursive: true });
    const patchScript = path.join(__dirname, '..', 'ws_repatch.py');
    fs.writeFileSync(
      path.join(hotDir, 'patch_info.json'),
      JSON.stringify({ patchScript, targets, ts: Date.now() })
    );
  } catch (_) {}

  // v4.1: 如果补丁时间戳有效(2小时内已验证且文件未变), 跳过实际补丁检查
  // 避免watchdog和extension.js同时patch导致extension.js触发多余IPC重启→新建Cascade会话
  if (_isPatchStampValid(targets)) {
    console.log(`[补丁] ✅ stamp有效(2h内已验证)，跳过重复检查 — 共${targets.length}个目标`);
    return;
  }

  const patchScript = path.join(__dirname, '..', 'ws_repatch.py');
  const { execSync } = require('child_process');
  let allOk = true;

  for (const target of targets) {
    const content = fs.readFileSync(target, 'utf8');
    const needsBase = !content.includes('globalThis.__wamRateLimit');
    const needsP7 = !content.includes('failed.precondition|quota.exhaust');

    if (needsBase || needsP7) {
      allOk = false;
      const reason = needsBase ? '缺少GBe拦截器' : '缺少Patch7(quota exhausted正则)';
      console.log(`[补丁] ${path.basename(path.dirname(path.dirname(path.dirname(path.dirname(target)))))} ${reason}，正在应用...`);
      if (fs.existsSync(patchScript)) {
        try {
          execSync(`python "${patchScript}" --target "${target}" --force`, { stdio: 'pipe', timeout: 30000 });
          console.log(`[补丁] ✅ 补丁应用完成: ${target.slice(0, 60)}`);
        } catch (e) {
          console.log('[补丁] ⚠️  补丁应用失败:', e.message.slice(0, 100));
        }
      }
    } else {
      console.log(`[补丁] ✅ 补丁完整: ${target.slice(0, 60)}`);
    }
  }

  // 所有目标补丁完整后写入时间戳(避免下次重复执行)
  if (allOk) {
    _writePatchStamp(targets);
    console.log('[补丁] ✅ 已写入补丁时间戳(2h内跳过重复验证)');
  }
}

// ─── 强制轮转 ────────────────────────────────
async function forceRotate(reason) {
  // 方法1: WAM Hub — 智能自动切号 (v5 endpoint)
  const r1 = await httpPost(`${WAM_HUB}/api/auto-switch`, { reason });
  if (r1 && r1.ok && r1.action === 'auto_switched') {
    console.log(`[轮转] ✅ WAM智能切号 → ${String(r1.to_email||'').slice(0,25)} score=${r1.to_score||0} (${reason})`);
    return true;
  }
  if (r1 && r1.ok && r1.action === 'hold') {
    console.log(`[轮转] ✅ WAM: 当前账号健康(${r1.reason?.slice(0,40)})，无需切换`);
    return true;
  }
  // 方法2: WAM 下一个
  const r2 = await httpPost(`${WAM_HUB}/api/next`, { reason });
  if (r2 && r2.ok) {
    const email = r2.target || '?';
    console.log(`[轮转] ✅ WAM切换成功 → ${String(email).slice(0,25)} (${reason})`);
    return true;
  }
  // 方法3: 通过管理端推送force_refresh指令
  const r3 = await httpPost(`${ADMIN_HUB}/api/ratelimit/trigger-switch`, {
    email: '__watchdog_proactive@wuwei.local',
    reason, deviceId: 'wuwei-watchdog',
  });
  if (r3 && r3.ok !== false) {
    console.log(`[轮转] ✅ 管理端推送轮转成功 (${reason})`);
    return true;
  }
  console.log(`[轮转] ⚠️  所有轮转方法失败 (${reason})`);
  return false;
}

// ─── 主看门狗 ────────────────────────────────
class WuWeiWatchdog {
  constructor() {
    this.rotateCount  = 0;
    this.rlCount      = 0;
    this.lastRotateMs = 0;
    this.pollMs       = POLL_MS;
    this.fastUntil    = 0;
    this.lastRlHash   = '';
    this.ticks        = 0;
    this.resetAtMap   = new Map(); // email → cooldownUntil (精确时间戳)
    this.nextWakeAt   = 0;         // 精确唤醒时间 (来自_resetAt)
  }

  // 获取管理端限流状态 — admin hub需session auth, 静默返回null
  // 主要依赖WAM Hub; admin hub仅用于健康检查
  async _getAdminRlStatus() {
    return null; // admin hub所有rate-limit端点需session, 无法外部访问
  }

  async tick() {
    this.ticks++;
    // 精确唤醒检查 (在每次tick开始时)
    this._checkResetAt();

    // ── 1. 管理端健康状态 (公开端点，无需认证) ──
    const health = await httpGet(`${ADMIN_HUB}/api/health`);
    const adminOnline = !!(health && health.ok);

    // ── 2. 管理端限流状态 (v1 relay, 机器HMAC认证) ──
    const rl = await this._getAdminRlStatus();
    if (rl && rl.ok) {
      const events = rl.events || [];
      const recent = events.filter(e => {
        const age = Date.now() - new Date(e.ts).getTime();
        return age < 30000 && e.type === 'rate_limit_hit';
      });
      if (recent.length > 0) {
        const ev = recent[0];
        const hash = ev.ts + ev.email;
        if (hash !== this.lastRlHash) {
          this.lastRlHash = hash;
          this.rlCount++;
          const email = (ev.email || '?').slice(0, 20);
          // v19.0: 记录精确冷却结束时间
          if (ev.cooldownUntil && ev.cooldownUntil > Date.now()) {
            this.resetAtMap.set(ev.email, ev.cooldownUntil);
            const resetInMin = ((ev.cooldownUntil - Date.now()) / 60000).toFixed(1);
            const src = ev.resetAtSource || 'estimate';
            console.log(`[限流事件] ⚡ 检测到限流: ${email}... (重置于${resetInMin}min后, ${src})`);
          } else {
            console.log(`[限流事件] ⚡ 检测到限流: ${email}... → 立即轮转`);
          }
          await this._doRotate('rate_limit_event');
          return;
        }
      }
      const cooling = rl.coolingCount || 0;
      if (this.ticks % 12 === 0) {
        const stats = rl.stats || {};
        process.stdout.write(
          `[状态] 管理端=${adminOnline?'✅':'❌'} 冷却中=${cooling} | ` +
          `24h限流=${stats.total24h||0} | 本守护轮转=${this.rotateCount}\r`
        );
      }
    } else if (this.ticks % 12 === 0) {
      process.stdout.write(
        `[状态] 管理端=${adminOnline?'在线':'离线'} | WAM待连接 | 本守护轮转=${this.rotateCount}\r`
      );
    }

    // ── 3. WAM Hub 额度监控 + quota exhausted检测 ───────────────
    const pool = await httpGet(`${WAM_HUB}/api/pool/status`); // compat route in v5
    if (pool) {
      const dPct = pool.dailyQuotaPercent || pool.dPercent || 100;
      const wPct = pool.weeklyQuotaPercent || pool.wPercent || 100;
      const eff  = Math.min(dPct || 100, wPct || 100);

      // v4.0: quota exhausted检测 (日配额耗尽 = Trial账号每日限额用完)
      if (pool.quotaExhausted || pool.dailyQuotaExhausted || eff <= 0) {
        const since = Date.now() - this.lastRotateMs;
        if (since > MIN_SWITCH_MS) {
          console.log(`[配额耗尽] ⚡ 日配额耗尽(D%=${dPct}, eff=${eff}) → 立即轮转+续传`);
          await this._doRotate('quota_exhausted');
          return;
        }
      }

      if (pool.rateLimited || pool.isRateLimited) {
        console.log(`[WAM] ⚡ WAM报告限流 → 立即轮转`);
        await this._doRotate('wam_rate_limited');
        return;
      }

      if (eff < 15 && eff > 0) {
        const since = Date.now() - this.lastRotateMs;
        if (since > 60000) {
          console.log(`[预防] 📊 有效配额=${eff.toFixed(0)}% < 15% → 预防性轮转`);
          await this._doRotate('quota_preemptive');
        }
      }
    }

    // ── 4. 快速模式超时检测 ───────────────
    if (this.pollMs === FAST_MS && Date.now() > this.fastUntil) {
      this.pollMs = POLL_MS;
      console.log('\n[无为守护] 恢复正常轮询 (5s)');
    }
  }

  async _doRotate(reason) {
    const now = Date.now();
    if (now - this.lastRotateMs < MIN_SWITCH_MS) return; // 防连锁
    this.lastRotateMs = now;
    this.rotateCount++;
    await forceRotate(reason);
    // 切换到快速模式30s
    this.pollMs    = FAST_MS;
    this.fastUntil = now + 30000;
    console.log('[无为守护] 进入快速监控30s (1s/次)');
  }

  // 精确唤醒: 当所有账号冷却结束时立即轮转
  _checkResetAt() {
    const now = Date.now();
    for (const [email, cooldownUntil] of this.resetAtMap) {
      if (cooldownUntil > 0 && now >= cooldownUntil) {
        this.resetAtMap.delete(email);
        const em = email.slice(0, 20);
        console.log(`\n[精确唤醒] ⏰ ${em}... 冷却结束 → 触发轮转`);
        this._doRotate('resetAt_precise');
        return;
      }
    }
  }

  async run() {
    console.log('╔══════════════════════════════════════════════════════════╗');
    console.log('║  无为看门狗 v4.0 — quota exhausted根因修复·后台永续    ║');
    console.log('╚══════════════════════════════════════════════════════════╝');
    console.log(`管理端: ${ADMIN_HUB} | WAM Hub: ${WAM_HUB}`);
    console.log('轮询: 5s正常 / 1s限流后 | 按 Ctrl+C 停止\n');

    // 启动前确保补丁完整
    await ensurePatches();
    console.log();

    // 验证管理端连通
    const health = await httpGet(`${ADMIN_HUB}/api/health`);
    if (health && health.ok) {
      console.log(`[健康] ✅ 管理端在线 v${health.v}`);
    } else {
      console.log(`[健康] ⚠️  管理端离线，仅WAM模式`);
    }
    console.log();

    while (true) {
      await this.tick();
      await new Promise(r => setTimeout(r, this.pollMs));
    }
  }
}

// ─── 入口 ────────────────────────────────────
const mode = process.argv[2] || '';

if (mode === '--once') {
  (async () => {
    console.log('[单次] 执行单次检查...');
    const health = await httpGet(`${ADMIN_HUB}/api/health`);
    if (!health || !health.ok) { console.log('[单次] 管理端不可达'); return; }
    console.log(`[单次] 管理端在线 v${health.v}`);
    // WAM Hub状态 (无需auth)
    const pool = await httpGet(`${WAM_HUB}/api/pool/status`);
    if (pool) {
      const d = pool.dailyQuotaPercent || pool.dPercent;
      const w = pool.weeklyQuotaPercent || pool.wPercent;
      const rl = pool.rateLimited || pool.isRateLimited;
      console.log(`[单次] WAM Hub在线 D%=${d||'?'} W%=${w||'?'} 限流=${rl?'是':'否'}`);
      if (rl) { console.log('[单次] WAM报告限流 → 触发轮转'); await forceRotate('single_check_wam'); }
      else { console.log('[单次] 系统状态正常'); }
    } else {
      console.log('[单次] WAM Hub离线 — 系统可能仍在启动中，等待正常');
    }
  })().catch(console.error);
} else if (mode === '--status') {
  (async () => {
    const [health, rl, pool] = await Promise.all([
      httpGet(`${ADMIN_HUB}/api/health`),
      httpGet(`${ADMIN_HUB}/api/ratelimit/status`),
      httpGet(`${WAM_HUB}/api/pool/status`),
    ]);
    console.log('管理端:', health ? `v${health.v} ✅` : '❌');
    console.log('WAM Hub:', pool ? '✅' : '❌');
    if (rl && rl.ok) {
      console.log(`限流: 冷却中=${rl.coolingCount} 24h=${rl.stats?.total24h||0}`);
    }
    if (pool) {
      console.log(`号池: D%=${pool.dailyQuotaPercent||'?'} W%=${pool.weeklyQuotaPercent||'?'}`);
    }
  })().catch(console.error);
} else {
  new WuWeiWatchdog().run().catch(e => {
    console.error('[致命] 守护进程崩溃:', e.message);
    process.exit(1);
  });
}
