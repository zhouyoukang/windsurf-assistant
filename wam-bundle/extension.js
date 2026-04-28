// WAM · 万法归宗 v2.1 · 道德经体 · 用户无为·插件无不为 · 去芜存菁最终版
"use strict";
const vscode = require("vscode");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const https = require("node:https");
const { URL } = require("node:url");

// ═══ § 1 · 万法之资 ═══
const VERSION = "2.1.1";
const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36";
const WINDSURF = "https://windsurf.com";
const REGISTER_BASE = "https://register.windsurf.com";
const URL_DEVIN_LOGIN = WINDSURF + "/_devin-auth/password/login";
const URL_POSTAUTH =
  WINDSURF +
  "/_backend/exa.seat_management_pb.SeatManagementService/WindsurfPostAuth";
const URL_REGISTER_USER =
  REGISTER_BASE + "/exa.seat_management_pb.SeatManagementService/RegisterUser";
// GetPlanStatus 真路径: server.codeium.com (register.windsurf.com 是 404)
// 请求体: { authToken, includeTopUpStatus } JSON · Connect-Protocol-Version: 1
// 实测 4 个 endpoint 等价: server.codeium.com / web-backend.windsurf.com / server.self-serve.windsurf.com / windsurf.com/_backend
const URL_GET_PLAN_STATUS =
  "https://server.codeium.com/exa.seat_management_pb.SeatManagementService/GetPlanStatus";
const HTTP_TIMEOUT_MS = 12000;
const WAM_DIR = path.join(os.homedir(), ".wam");
const STATE_FILE = path.join(WAM_DIR, "wam-state.json");
const BACKUP_DIR = path.join(WAM_DIR, "backups");
const PENDING_TOKEN_FILE = path.join(WAM_DIR, "_pending_token.json");
const MAX_BACKUPS = 10;
const ACCOUNTS_DEFAULT_MD =
  "v:\\道\\道生一\\一生二\\Windsurf万法归宗\\070-插件_Plugins\\010-WAM本源_Origin\\账号库最新.md";

let _output = null,
  _ctx = null,
  _statusBar = null,
  _sidebarProvider = null,
  _editorPanel = null,
  _store = null,
  _engine = null,
  _verifyAllInProgress = false,
  _wamMode = "wam", // 'wam' | 'official' (本源同款) · 默认 wam · 用户自显式选官方时停引擎
  _switching = false, // 切号互斥锁 (本源 v17.42.7)
  _switchingStartTime = 0,
  _lastSwitchTime = 0, // 上次切号成功时间 (冷却用)
  _predictiveCandidate = -1, // 预判候选 idx (本源 v8 · 额度低时提前选好下一号)
  _lastInjectFail = 0, // 上次注入失败时间 (rate-limit 拦截冷却)
  _lastDocChangeAt = 0, // 最近文档变化时间 (Cascade 流式避让 · 对齐本源 v17.42.5)
  _lastSwitchMs = 0; // 上次切号耗时ms (对齐本源 switchToAccount.ms)
function log(m) {
  const t = new Date().toISOString().substring(11, 23);
  if (_output) _output.appendLine("[" + t + "] " + m);
  try {
    console.log("[wam] " + m);
  } catch {}
}
function _cfg(k, d) {
  return vscode.workspace.getConfiguration("wam").get(k, d);
}
function _notify(level, msg) {
  if (_cfg("invisible", false)) return;
  const lvl = _cfg("notifyLevel", "notify");
  if (lvl === "silent") return;
  if (lvl === "notify" && level === "verbose") return;
  if (level === "error") vscode.window.showErrorMessage(msg);
  else if (level === "warn") vscode.window.showWarningMessage(msg);
  else vscode.window.showInformationMessage(msg);
}
function ensureDir(p) {
  try {
    fs.mkdirSync(p, { recursive: true });
  } catch {}
}
function atomicWrite(filePath, content) {
  ensureDir(path.dirname(filePath));
  const tmp = filePath + "." + process.pid + "." + Date.now() + ".tmp";
  fs.writeFileSync(tmp, content);
  try {
    fs.renameSync(tmp, filePath);
  } catch (e) {
    try {
      fs.copyFileSync(tmp, filePath);
      fs.unlinkSync(tmp);
    } catch {}
    throw e;
  }
}
function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
function hoursUntilDailyReset() {
  // 兵无常势: API 提供 dailyResetAt 时用真值, 否则 fallback UTC 08:00
  if (_store && _store.activeEmail) {
    const h = _store.getHealth(_store.activeEmail);
    if (h && h.dailyResetAt > Date.now())
      return (h.dailyResetAt - Date.now()) / 3600000;
  }
  const n = new Date();
  const u = new Date(
    Date.UTC(n.getUTCFullYear(), n.getUTCMonth(), n.getUTCDate(), 8, 0, 0),
  );
  if (u.getTime() < n.getTime()) u.setUTCDate(u.getUTCDate() + 1);
  return (u.getTime() - n.getTime()) / 3600000;
}
function hoursUntilWeeklyReset() {
  // 兵无常势: API 提供 weeklyResetAt 时用真值, 否则 fallback UTC 周日 08:00
  if (_store && _store.activeEmail) {
    const h = _store.getHealth(_store.activeEmail);
    if (h && h.weeklyResetAt > Date.now())
      return (h.weeklyResetAt - Date.now()) / 3600000;
  }
  const n = new Date();
  const day = n.getUTCDay();
  const dts = (7 - day) % 7 || 7;
  const s = new Date(n.getTime());
  s.setUTCDate(s.getUTCDate() + dts);
  s.setUTCHours(8, 0, 0, 0);
  return (s.getTime() - n.getTime()) / 3600000;
}

// ── 本源 v17.42.7: 自动切号辅助 ──
function isWeeklyDrought() {
  if (!_store) return false;
  const s = _store.getStats();
  return s.drought;
}
function isTrialPlan(p) {
  return /trial|free/i.test(p || "");
}
function isClaudeAvailable(h) {
  if (!h || !h.checked) return false;
  const p = (h.plan || "").toLowerCase();
  // 兵无常势: 所有免费层 → Claude 死刑 (对齐本源 v17.42.4 _FREE_TIER_SET)
  if (/^free$|^devin.free$|^waitlist/i.test(p)) return false;
  // Trial 过期 + 额度耗尽 → 不可用
  if (
    isTrialPlan(p) &&
    h.planEnd > 0 &&
    Date.now() > h.planEnd &&
    h.daily <= 0 &&
    h.weekly <= 0
  )
    return false;
  return true;
}
// v17.42.7 锁🔒 全链路贯通 — 单一真相门 · 凡四辨一不齐即无效
function _isValidAutoTarget(i) {
  if (i < 0 || !_store) return false;
  const acc = _store.accounts[i];
  if (!acc || !acc.password) return false;
  if (acc.skipAutoSwitch) return false; // 用户手动锁 → 禁止自动切号
  if (_store.isBanned(acc.email)) return false;
  const h = _store.getHealth(acc.email);
  if (!isClaudeAvailable(h)) return false;
  return true;
}

function httpsReq(method, urlStr, headers, body, timeoutMs) {
  return new Promise((resolve, reject) => {
    let u;
    try {
      u = new URL(urlStr);
    } catch (e) {
      return reject(e);
    }
    const req = https.request(
      {
        method,
        hostname: u.hostname,
        port: u.port || 443,
        path: u.pathname + u.search,
        headers: Object.assign({ "User-Agent": UA }, headers || {}),
        timeout: timeoutMs || HTTP_TIMEOUT_MS,
      },
      (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () =>
          resolve({ status: res.statusCode, body: Buffer.concat(chunks) }),
        );
      },
    );
    req.on("error", reject);
    req.on("timeout", () => req.destroy(new Error("timeout")));
    if (body) req.write(body);
    req.end();
  });
}
async function jsonPost(url, headers, body, timeoutMs) {
  const r = await httpsReq(
    "POST",
    url,
    Object.assign({ "Content-Type": "application/json" }, headers || {}),
    JSON.stringify(body),
    timeoutMs,
  );
  let parsed = null;
  const text = r.body.toString("utf8");
  try {
    parsed = JSON.parse(text);
  } catch {}
  return { status: r.status, json: parsed, text };
}

function parseAccountText(content) {
  const lines = content.split(/\r?\n/);
  const accs = [];
  for (const raw of lines) {
    const ln = raw.trim();
    if (!ln || ln.startsWith("#") || ln.startsWith("//")) continue;
    let email, password;
    if (ln.includes("----")) {
      const p = ln.split(/----+/);
      email = (p[0] || "").trim();
      password = (p[1] || "").trim();
    } else if (ln.includes("\t")) {
      const p = ln.split(/\t+/);
      email = (p[0] || "").trim();
      password = (p[1] || "").trim();
    } else if (ln.includes(":") && !ln.match(/^https?:/)) {
      const idx = ln.indexOf(":");
      const a = ln.substring(0, idx).trim();
      const b = ln.substring(idx + 1).trim();
      if (a.includes("@")) {
        email = a;
        password = b;
      } else if (b.includes("@")) {
        email = b;
        password = a;
      }
    } else if (ln.includes("|")) {
      const p = ln.split(/\|+/);
      email = (p[0] || "").trim();
      password = (p[1] || "").trim();
    } else {
      const m = ln.match(/^(\S+@\S+)\s+(.+)$/);
      if (m) {
        email = m[1].trim();
        password = m[2].trim();
      }
    }
    if (email && password && email.includes("@"))
      accs.push({ email, password });
  }
  return accs;
}
function loadAccountsFromFs() {
  const cfgPath = _cfg("accountsFile", "");
  const cands = [
    cfgPath,
    ACCOUNTS_DEFAULT_MD,
    path.join(WAM_DIR, "accounts.md"),
    path.join(WAM_DIR, "accounts-backup.json"),
  ].filter(Boolean);
  for (const p of cands) {
    try {
      if (!fs.existsSync(p)) continue;
      let accs;
      if (p.endsWith(".json")) {
        const j = JSON.parse(fs.readFileSync(p, "utf8"));
        const arr = Array.isArray(j) ? j : j.accounts || [];
        accs = arr
          .filter((a) => a && a.email && a.password)
          .map((a) => ({ email: a.email, password: a.password }));
      } else {
        accs = parseAccountText(fs.readFileSync(p, "utf8"));
      }
      if (accs && accs.length) return { source: p, accounts: accs };
    } catch (e) {
      log("loadAccountsFromFs " + p + ": " + e.message);
    }
  }
  return { source: null, accounts: [] };
}

// ═══ § 2 · 万物之母 (Store) ═══
class Store {
  constructor() {
    this.accountsSource = null;
    this.accounts = [];
    this.health = {};
    this.blacklist = {};
    this.activeIdx = -1;
    this.activeEmail = null;
    this.activeTokenShort = null;
    this.activeApiKey = null;
    this.activeApiServerUrl = null;
    this.lastInjectPath = null;
    this.lastRotateAt = 0;
    this.switches = 0;
    this.changesDetected = 0;
  }
  load() {
    try {
      if (!fs.existsSync(STATE_FILE)) return false;
      const j = JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
      if (j.health) this.health = j.health;
      if (j.blacklist) this.blacklist = j.blacklist;
      if (typeof j.switches === "number") this.switches = j.switches;
      if (typeof j.changesDetected === "number")
        this.changesDetected = j.changesDetected;
      if (typeof j.activeEmail === "string") this.activeEmail = j.activeEmail;
      if (typeof j.lastInjectPath === "string")
        this.lastInjectPath = j.lastInjectPath;
      log("store.load ok · health=" + Object.keys(this.health).length);
      return true;
    } catch (e) {
      log("store.load fail: " + e.message);
      return false;
    }
  }
  save() {
    try {
      const data = {
        version: VERSION,
        savedAt: Date.now(),
        health: this.health,
        blacklist: this.blacklist,
        switches: this.switches,
        changesDetected: this.changesDetected,
        activeEmail: this.activeEmail,
        lastInjectPath: this.lastInjectPath,
      };
      atomicWrite(STATE_FILE, JSON.stringify(data, null, 2));
      this._rotateBackups();
    } catch (e) {
      log("store.save fail: " + e.message);
    }
  }
  _rotateBackups() {
    try {
      ensureDir(BACKUP_DIR);
      const today = new Date().toISOString().substring(0, 10);
      const tf = path.join(BACKUP_DIR, "wam-state-" + today + ".json");
      if (!fs.existsSync(tf) && fs.existsSync(STATE_FILE))
        fs.copyFileSync(STATE_FILE, tf);
      const files = fs
        .readdirSync(BACKUP_DIR)
        .filter((f) => f.startsWith("wam-state-") && f.endsWith(".json"))
        .map((f) => ({
          name: f,
          full: path.join(BACKUP_DIR, f),
          stat: fs.statSync(path.join(BACKUP_DIR, f)),
        }))
        .sort((a, b) => b.stat.mtimeMs - a.stat.mtimeMs);
      const max = Math.max(3, MAX_BACKUPS);
      for (let i = max; i < files.length; i++) {
        try {
          fs.unlinkSync(files[i].full);
        } catch {}
      }
    } catch (e) {
      log("rotateBackups: " + e.message);
    }
  }
  reloadAccounts() {
    const r = loadAccountsFromFs();
    this.accountsSource = r.source;
    this.accounts = r.accounts;
    if (this.activeEmail) {
      const idx = this.accounts.findIndex(
        (a) => a.email.toLowerCase() === this.activeEmail.toLowerCase(),
      );
      this.activeIdx = idx;
    } else {
      this.activeIdx = -1;
    }
    return r;
  }
  addBatch(text) {
    const newOnes = parseAccountText(text);
    let added = 0,
      duplicate = 0;
    for (const a of newOnes) {
      const exists = this.accounts.find(
        (x) => x.email.toLowerCase() === a.email.toLowerCase(),
      );
      if (exists) {
        duplicate++;
        continue;
      }
      this.accounts.push({
        email: a.email,
        password: a.password,
        addedAt: Date.now(),
      });
      added++;
    }
    if (added > 0) this._persistAccountsToMd();
    return { added, duplicate };
  }
  remove(idx) {
    if (idx < 0 || idx >= this.accounts.length) return false;
    const r = this.accounts.splice(idx, 1)[0];
    if (r) {
      delete this.health[r.email.toLowerCase()];
      delete this.blacklist[r.email.toLowerCase()];
      this._persistAccountsToMd();
      if (this.activeEmail === r.email) {
        this.activeIdx = -1;
        this.activeEmail = null;
      } else if (this.activeIdx > idx) this.activeIdx--;
      this.save();
    }
    return true;
  }
  removeBatch(indices) {
    const sorted = [...indices].sort((a, b) => b - a);
    let n = 0;
    for (const i of sorted) if (this.remove(i)) n++;
    return n;
  }
  _persistAccountsToMd() {
    let target = this.accountsSource;
    if (!target || !target.endsWith(".md"))
      target = path.join(WAM_DIR, "accounts.md");
    try {
      const lines = this.accounts.map((a) => a.email + " " + a.password);
      atomicWrite(target, lines.join("\n") + "\n");
      log("persistAccountsToMd: " + this.accounts.length + " → " + target);
    } catch (e) {
      log("persistAccountsToMd: " + e.message);
    }
  }
  setHealth(email, h) {
    const k = email.toLowerCase();
    const prev = this.health[k] || {};
    this.health[k] = Object.assign({}, prev, h, {
      lastChecked: Date.now(),
      hasSnap: true,
      checked: true,
    });
    if (
      typeof prev.daily === "number" &&
      typeof h.daily === "number" &&
      Math.abs(prev.daily - h.daily) > 0.01
    )
      this.changesDetected++;
    this.save();
  }
  getHealth(email) {
    const k = (email || "").toLowerCase();
    const h = this.health[k];
    if (!h)
      return {
        checked: false,
        daily: 0,
        weekly: 0,
        plan: "",
        planEnd: 0,
        daysLeft: 0,
        lastChecked: 0,
        hasSnap: false,
        staleMin: -1,
      };
    return Object.assign({}, h, {
      staleMin: h.lastChecked
        ? Math.round((Date.now() - h.lastChecked) / 60000)
        : -1,
    });
  }
  banFor(email, ms, reason) {
    const k = email.toLowerCase();
    const cur = this.blacklist[k] || { count: 0 };
    this.blacklist[k] = {
      until: Date.now() + ms,
      reason: reason || "?",
      count: (cur.count || 0) + 1,
    };
    log("ban " + email + " " + Math.round(ms / 1000) + "s · " + reason);
    this.save();
  }
  isBanned(email) {
    const k = email.toLowerCase();
    const b = this.blacklist[k];
    if (!b) return false;
    if (Date.now() > b.until) {
      delete this.blacklist[k];
      this.save();
      return false;
    }
    return true;
  }
  clearBlacklist() {
    const n = Object.keys(this.blacklist).length;
    this.blacklist = {};
    this.save();
    return n;
  }
  // ── 本源 v17.42.20 评分 — 道法自然 · D/W 综合 + 干旱/重置倒计时/锁/Claude门控 ──
  _scoreOf(idx) {
    const a = this.accounts[idx];
    if (!a || !a.password) return -Infinity;
    if (a.skipAutoSwitch) return -Infinity; // 🔒 锁号不参与自动切号
    if (this.isBanned(a.email)) return -Infinity;
    const h = this.getHealth(a.email);
    if (!h.checked) return 50; // 未验号给基础分 (好过跳过)
    if (!isClaudeAvailable(h)) return -Infinity; // Free/过期耗尽不选
    const hrsToDaily = hoursUntilDailyReset();
    const hrsToWeekly = hoursUntilWeeklyReset();
    const drought = isWeeklyDrought();
    if (drought) {
      // ── 干旱模式: 只看 Daily ──
      if (h.daily <= 0 && hrsToDaily > 4) return -Infinity;
      let s = h.daily * 15;
      if (h.daily <= 5 && hrsToDaily <= 2)
        s += 300; // 即将重置 · 低额度也值得
      else if (h.daily <= 5 && hrsToDaily <= 6) s += 120;
      if (h.daily > 50) s += 200;
      if (h.staleMin >= 0 && h.staleMin < 5) s += 30;
      else if (h.staleMin >= 0 && h.staleMin > 60) s += 60;
      return s;
    }
    // ── 正常模式: D+W 综合评分 ──
    const eff = Math.min(h.daily, h.weekly);
    if (h.daily <= 0 && h.weekly <= 0 && hrsToDaily > 4 && hrsToWeekly > 4)
      return -Infinity;
    if (h.weekly <= 0 && hrsToWeekly > 6) return -Infinity;
    let s = eff * 10 + h.weekly * 8 + h.daily * 3;
    if (h.daily <= 5 && hrsToDaily <= 2) s += 250;
    else if (h.daily <= 5 && hrsToDaily <= 6) s += 100;
    if (h.weekly <= 5 && hrsToWeekly <= 4) s += 350;
    if (h.daily > 50 && h.weekly > 50) s += 200;
    if (h.staleMin >= 0 && h.staleMin < 5) s += 80;
    else if (h.staleMin >= 0 && h.staleMin < 30) s += 40;
    else if (h.staleMin < 0 || h.staleMin > 120) s -= 50;
    return s;
  }
  getBestIndex(excludeIdx) {
    let best = -1,
      bestScore = -Infinity;
    for (let i = 0; i < this.accounts.length; i++) {
      if (i === excludeIdx) continue;
      const s = this._scoreOf(i);
      if (s > bestScore) {
        bestScore = s;
        best = i;
      }
    }
    return best;
  }
  // 按 score 降序返回所有 idx (黑名单已排除) · rotateNext 阈值切号用
  getSortedIndices(excludeIdx) {
    const arr = [];
    for (let i = 0; i < this.accounts.length; i++) {
      if (i === excludeIdx) continue;
      const s = this._scoreOf(i);
      if (s > -Infinity) arr.push({ i, s });
    }
    arr.sort((a, b) => b.s - a.s);
    return arr.map((x) => x.i);
  }
  getStats() {
    let totalD = 0,
      totalW = 0,
      checkedCount = 0,
      unchecked = 0,
      available = 0,
      exhausted = 0;
    for (const a of this.accounts) {
      const h = this.getHealth(a.email);
      if (!h.checked) {
        unchecked++;
        continue;
      }
      checkedCount++;
      totalD += h.daily;
      totalW += h.weekly;
      const eff = Math.min(h.daily, h.weekly);
      if (eff < 1) exhausted++;
      else available++;
    }
    const banned = Object.keys(this.blacklist).filter((k) =>
      this.isBanned(k),
    ).length;
    return {
      pwCount: this.accounts.length,
      checkedCount,
      unchecked,
      available,
      exhausted,
      banned,
      totalD: Math.round(totalD),
      totalW: Math.round(totalW),
      switches: this.switches,
      changesDetected: this.changesDetected,
      hrsToDaily: hoursUntilDailyReset(),
      hrsToWeekly: hoursUntilWeeklyReset(),
      drought: checkedCount > 0 && totalW / checkedCount < 1,
    };
  }
  setActive(idx, email, sessionToken, apiKey, apiServerUrl, injectPath) {
    // 大制不割: 仅真正换号才计数 · 同号 re-auth (启动恢复) 不虚增
    const isRealSwitch = email !== this.activeEmail || idx !== this.activeIdx;
    this.activeIdx = idx;
    this.activeEmail = email;
    this.activeTokenShort = sessionToken
      ? sessionToken.substring(0, 14) + "..."
      : null;
    this.activeApiKey = apiKey || sessionToken;
    this.activeApiServerUrl = apiServerUrl || null;
    this.lastInjectPath = injectPath || null;
    this.lastRotateAt = Date.now();
    if (isRealSwitch) this.switches++;
    this.save();
  }
}

// ═══ § 3 · 万法之本 (Devin auth · inject · 切号主流水) ═══
async function devinLogin(email, password) {
  try {
    const r = await jsonPost(
      URL_DEVIN_LOGIN,
      {
        Origin: WINDSURF,
        Referer: WINDSURF + "/account/login",
        Accept: "application/json, text/plain, */*",
      },
      { email, password },
    );
    if (r.json && r.json.token && r.json.user_id)
      return { ok: true, auth1: r.json.token, userId: r.json.user_id };
    const err =
      (r.json && (r.json.detail || r.json.error || r.json.message)) ||
      "no_token";
    return { ok: false, status: r.status, error: err };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}
async function windsurfPostAuth(auth1, orgId) {
  try {
    const body = { auth1_token: auth1 };
    if (orgId) body.org_id = orgId;
    const r = await jsonPost(
      URL_POSTAUTH,
      {
        Origin: WINDSURF,
        Referer: WINDSURF + "/profile",
        "Connect-Protocol-Version": "1",
      },
      body,
    );
    if (
      r.json &&
      typeof r.json.sessionToken === "string" &&
      r.json.sessionToken.startsWith("devin-session-token$")
    )
      return {
        ok: true,
        sessionToken: r.json.sessionToken,
        accountId: r.json.accountId || "",
        primaryOrgId: r.json.primaryOrgId || "",
      };
    const err =
      (r.json && (r.json.error || r.json.code || r.json.message)) ||
      "no_session";
    return { ok: false, status: r.status, error: err };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}
async function registerUserViaSession(sessionToken) {
  try {
    const r = await jsonPost(
      URL_REGISTER_USER,
      { "Connect-Protocol-Version": "1" },
      { firebase_id_token: sessionToken },
    );
    if (r.json && (r.json.api_key || r.json.apiKey))
      return {
        ok: true,
        apiKey: r.json.api_key || r.json.apiKey,
        name: r.json.name || "",
        apiServerUrl: r.json.api_server_url || r.json.apiServerUrl || "",
      };
    return {
      ok: false,
      status: r.status,
      error: (r.json && (r.json.code || r.json.message)) || "no_api_key",
    };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}
async function tryFetchPlanStatus(sessionToken) {
  try {
    const r = await jsonPost(
      URL_GET_PLAN_STATUS,
      { "Connect-Protocol-Version": "1" },
      { authToken: sessionToken, includeTopUpStatus: true },
      8000,
    );
    if (r.status >= 200 && r.status < 300 && r.json)
      return _parsePlanStatusJson(r.json);
    log(
      "planStatus status=" +
        r.status +
        " · body=" +
        (r.text || "").substring(0, 120),
    );
  } catch (e) {
    log("planStatus err: " + e.message);
  }
  return null;
}
// Devin Trial 真返回示例 (2026-04-28 实测):
//   planInfo.planName = "Trial"
//   planInfo.teamsTier = "TEAMS_TIER_DEVIN_TRIAL"
//   planStart = "2026-04-25T20:56:09Z" (ISO string)
//   planEnd = "2026-05-09T20:56:09Z" (ISO string)
//   weeklyQuotaRemainingPercent = 32   ← weekly 真值 (REMAINING, 非 USAGE)
//   availablePromptCredits = 10000     ← 独立资源池, 与 quota% 无关!
//   availableFlowCredits = 20000
//   ⚠ Devin Trial 没有 dailyQuotaRemainingPercent · daily 镜像 weekly
//
// ★★★ proto3 语义 (本源 v17.42.4 对齐 · 2026-04-28 修正) ★★★
//   - 新号满量 W100 D100 → JSON 字段 PRESENT (100 ≠ default 0, 不被 omit)
//   - 用过的 W32        → JSON 显式带字段
//   - 耗尽 W0 D0       → JSON 字段 omit (proto3: default 0 suppressed)
//   ∴ 字段缺失 = 值为 0 = 耗尽. 不用 credits 启发 (credits ≠ quota%)
//   官方 UI 显示 "usage" = 100 - remaining (0%用量=满,100%用量=耗尽)
function _parsePlanStatusJson(j) {
  const ps = j.planStatus || j.plan_status || j;
  const planInfo = ps.planInfo || ps.plan_info || {};
  // ── plan name ──
  let plan =
    planInfo.planName ||
    planInfo.plan_name ||
    planInfo.tier ||
    planInfo.teamsTier ||
    planInfo.teams_tier ||
    ps.tier ||
    "Trial";
  if (typeof plan === "string" && /^TEAMS_TIER_/i.test(plan)) {
    const raw = plan.replace(/^TEAMS_TIER_/i, "").replace(/_/g, " ");
    // 兵无常势: 完整 tier 映射 (对齐本源 v17.42.4 TEAMS_TIER enum)
    if (/DEVIN.TRIAL/i.test(raw)) plan = "Trial";
    else if (/DEVIN.PRO/i.test(raw)) plan = "Pro";
    else if (/DEVIN.MAX/i.test(raw)) plan = "Max";
    else if (/DEVIN.FREE/i.test(raw)) plan = "Free";
    else if (/DEVIN.ENTERPRISE/i.test(raw)) plan = "Enterprise";
    else if (/DEVIN.TEAMS/i.test(raw)) plan = "Teams";
    else if (/PRO.ULTIMATE/i.test(raw)) plan = "Pro Ultimate";
    else if (/TEAMS.ULTIMATE/i.test(raw)) plan = "Teams Ultimate";
    else if (/^PRO$/i.test(raw)) plan = "Pro";
    else if (/^MAX$/i.test(raw)) plan = "Max";
    else if (/^TRIAL$/i.test(raw)) plan = "Trial";
    else if (/FREE|WAITLIST/i.test(raw)) plan = "Free";
    else if (/ENTERPRISE/i.test(raw)) plan = "Enterprise";
    else plan = raw; // 未知 tier → 原样保留
  }
  // ── credits (启发推算锚点) ──
  const promptUsed = Number(ps.usedPromptCredits || ps.promptUsed || 0);
  const promptAvail = Number(
    ps.availablePromptCredits || ps.promptAvailable || 0,
  );
  const promptMonth = Number(
    planInfo.monthlyPromptCredits || planInfo.monthly_prompt_credits || 0,
  );
  const flowUsed = Number(ps.usedFlowCredits || ps.flowUsed || 0);
  const flowAvail = Number(ps.availableFlowCredits || ps.flowAvailable || 0);
  const flowMonth = Number(
    planInfo.monthlyFlowCredits || planInfo.monthly_flow_credits || 0,
  );
  // ── weekly% 解析: 多字段名 · 兵无常势 · 唯变所适 ──
  // 核心语义: API 返回 REMAINING 百分比 (0=耗尽 100=满)
  //   官方 UI 显示 USAGE = 100 - remaining
  //   proto field 15 = weekly_quota_remaining_percent (本源 v17.42.4 逆向)
  let weeklyPct = null;
  if (ps.weeklyQuotaRemainingPercent != null)
    weeklyPct = Number(ps.weeklyQuotaRemainingPercent);
  else if (ps.weeklyPercentRemaining != null)
    weeklyPct = Number(ps.weeklyPercentRemaining);
  else if (ps.weekly_percent_remaining != null)
    weeklyPct = Number(ps.weekly_percent_remaining);
  else if (ps.weeklyQuotaUsagePercent != null)
    weeklyPct = 100 - Number(ps.weeklyQuotaUsagePercent);
  else if (ps.weeklyPercentUsed != null)
    weeklyPct = 100 - Number(ps.weeklyPercentUsed);
  else if (ps.weekly_percent_used != null)
    weeklyPct = 100 - Number(ps.weekly_percent_used);
  // ── daily% 解析 (Devin Trial 一般 omit · 镜像 weekly) ──
  let dailyPct = null;
  if (ps.dailyQuotaRemainingPercent != null)
    dailyPct = Number(ps.dailyQuotaRemainingPercent);
  else if (ps.dailyPercentRemaining != null)
    dailyPct = Number(ps.dailyPercentRemaining);
  else if (ps.daily_percent_remaining != null)
    dailyPct = Number(ps.daily_percent_remaining);
  else if (ps.dailyQuotaUsagePercent != null)
    dailyPct = 100 - Number(ps.dailyQuotaUsagePercent);
  else if (ps.dailyPercentUsed != null)
    dailyPct = 100 - Number(ps.dailyPercentUsed);
  else if (ps.daily_percent_used != null)
    dailyPct = 100 - Number(ps.daily_percent_used);
  // ── ★★★ proto3 语义修正 (本源 v17.42.4 对齐) ★★★ ──
  // proto3 JSON: 值=0 → 字段 omit (default suppression)
  //              值=100 → 字段 present (100 ≠ default 0)
  //              值=32 → 字段 present
  // ∴ 字段缺失 = 值为 0 = 耗尽 (不是 "未知"!)
  // ★ 旧版 credits 启发有误: promptCredits 与 quota% 是独立资源池 ★
  //   实证: 账号 Weekly Usage 100%(官方UI) 但 promptAvail=10000 → 旧版误判 W100
  if (weeklyPct == null) {
    weeklyPct = 0; // proto3: absent = 0 = exhausted
    log("  parsePlan: weekly% omit → 0 (proto3 default · 耗尽)");
  }
  if (dailyPct == null) {
    // Devin Trial: API 不填 daily → 镜像 weekly (保守代理)
    // min(daily, weekly) 中 weekly 为瓶颈 · daily 误差不影响耗尽判定
    dailyPct = weeklyPct;
    log("  parsePlan: daily% omit → mirror weekly=" + weeklyPct);
  }
  // ── planEnd: ISO/proto-Timestamp/unix ms 兼容 ──
  let pe = 0;
  const peRaw = ps.planEnd || ps.plan_end || planInfo.endTimestamp || 0;
  if (typeof peRaw === "string") {
    const t = Date.parse(peRaw);
    if (!isNaN(t)) pe = t;
  } else if (peRaw && typeof peRaw === "object" && peRaw.seconds != null) {
    pe = Number(peRaw.seconds) * 1000;
  } else {
    pe = Number(peRaw) || 0;
  }
  const daysLeft =
    pe > 0 ? Math.max(0, Math.round((pe - Date.now()) / 86400000)) : 0;
  // ── 防御 NaN/Infinity → 0 (不再用 `|| 0` 误吞 0) ──
  const safeDaily = Math.max(
    0,
    Math.min(100, Math.round(isFinite(dailyPct) ? dailyPct : 0)),
  );
  const safeWeekly = Math.max(
    0,
    Math.min(100, Math.round(isFinite(weeklyPct) ? weeklyPct : 0)),
  );
  // ── 重置时间 (proto field 17/18 · 兵无常势: API 提供时用 API 值) ──
  const _parseUnixTs = (v) => {
    if (!v) return 0;
    if (typeof v === "object" && v.seconds != null)
      return Number(v.seconds) * 1000;
    const n = Number(v);
    // unix 秒 vs unix 毫秒 智能判断
    if (n > 1e12) return n; // 已是 ms
    if (n > 1e9) return n * 1000; // 秒 → ms
    return 0;
  };
  const dailyResetAt = _parseUnixTs(
    ps.dailyQuotaResetAtUnix ||
      ps.daily_quota_reset_at_unix ||
      ps.dailyResetAt ||
      0,
  );
  const weeklyResetAt = _parseUnixTs(
    ps.weeklyQuotaResetAtUnix ||
      ps.weekly_quota_reset_at_unix ||
      ps.weeklyResetAt ||
      0,
  );
  // ── planStart ──
  let ps2 = 0;
  const psRaw = ps.planStart || ps.plan_start || 0;
  if (typeof psRaw === "string") {
    const t2 = Date.parse(psRaw);
    if (!isNaN(t2)) ps2 = t2;
  } else if (psRaw && typeof psRaw === "object" && psRaw.seconds != null) {
    ps2 = Number(psRaw.seconds) * 1000;
  } else {
    ps2 = _parseUnixTs(psRaw);
  }
  // ── teamsTier (软编码: 适配所有 plan 类型) ──
  const tierRaw = planInfo.teamsTier || planInfo.teams_tier || 0;
  let teamsTier = 0;
  if (typeof tierRaw === "number") teamsTier = tierRaw;
  else if (typeof tierRaw === "string") {
    const m = tierRaw.match(/\d+/);
    if (m) teamsTier = Number(m[0]);
  }
  return {
    daily: safeDaily,
    weekly: safeWeekly,
    plan: typeof plan === "string" ? plan : "Trial",
    planEnd: pe,
    planStart: ps2,
    daysLeft,
    promptCredits: promptAvail,
    flowCredits: flowAvail,
    promptUsed,
    promptMonth,
    dailyResetAt,
    weeklyResetAt,
    teamsTier,
  };
}

// ═══ § 3b · 批量验证 (verifyOne / verifyAll) · 不切号 · 仅探测 quota ═══
// 取之尽锱铢: 用 devinLogin → postAuth → tryFetchPlanStatus 三步链条 · 不调 inject
// 用之如泥沙: 并行 + 间隔抖动 + 限速回退 · 防 Devin 整批拉黑
async function verifyOneAccount(account) {
  if (!account || !account.email || !account.password)
    return { ok: false, stage: "init", error: "no creds" };
  const dl = await devinLogin(account.email, account.password);
  if (!dl.ok) return { ok: false, stage: "devinLogin", error: dl.error };
  const pa = await windsurfPostAuth(dl.auth1);
  if (!pa.ok) return { ok: false, stage: "postAuth", error: pa.error };
  const q = await tryFetchPlanStatus(pa.sessionToken);
  if (!q) return { ok: false, stage: "planStatus", error: "fetch null" };
  return { ok: true, q, sessionToken: pa.sessionToken };
}

// 批量验证 · onlyStale=true 时跳过最近验过的 (默认 staleMin <= 30)
// v2.1.1 根治: 全局限速协调 + 指数退避 + 失败自动重试 · 新用户首次全池验证不再卡死
// parallel: 默认 3 (保守 · 防 Devin 限速 · 用户可改 wam.verify.parallel)
// gapMs: 每个 verify 完成后的间隔 (默认 250ms 抖动)
async function verifyAllAccounts(opts) {
  if (_verifyAllInProgress) return { ok: false, busy: true };
  _verifyAllInProgress = true;
  const o = opts || {};
  const onlyStale = !!o.onlyStale;
  const userParallel = Math.max(
    1,
    Math.min(8, _cfg("verify.parallel", 3) | 0 || 3),
  );
  const gapMs = Math.max(0, _cfg("verify.gapMs", 250) | 0);
  const staleThresholdMin = Math.max(1, _cfg("verify.staleMin", 30) | 0);
  const total = _store.accounts.length;
  // 构建队列 (排除黑名单 + onlyStale 时排除最近验过的)
  const queue = [];
  let uncheckedCount = 0;
  for (let i = 0; i < total; i++) {
    const a = _store.accounts[i];
    if (_store.isBanned(a.email)) continue;
    const h = _store.getHealth(a.email);
    if (!h.checked) uncheckedCount++;
    if (onlyStale) {
      if (h.checked && h.staleMin >= 0 && h.staleMin < staleThresholdMin)
        continue;
    }
    queue.push(i);
  }
  // 道法自然 · 首次验证 (>50% 未验) → 降低并行度 · 加大间隔 · 防 Devin 整批拉黑
  const isFirstTime = uncheckedCount > total * 0.5;
  const parallel = isFirstTime ? Math.min(userParallel, 2) : userParallel;
  const effectiveGapMs = isFirstTime ? Math.max(gapMs, 1500) : gapMs;
  log(
    "verifyAll: 启动 · 候选 " +
      queue.length +
      "/" +
      total +
      " · 未验 " +
      uncheckedCount +
      " · 并行 " +
      parallel +
      (isFirstTime ? "(首次降速)" : "") +
      " · gap " +
      effectiveGapMs +
      "ms" +
      (onlyStale ? " · onlyStale" : ""),
  );
  let ok = 0,
    fail = 0,
    done = 0;
  const t0 = Date.now();
  // v2.1.1 全局限速协调: 所有 worker 共享暂停状态 · 一人中招全队等
  let _globalPauseUntil = 0;
  let _rateLimitHits = 0;
  const _failedIndices = []; // 收集失败的 idx · 后续重试
  async function _waitGlobalPause() {
    while (Date.now() < _globalPauseUntil) {
      const wait = Math.min(_globalPauseUntil - Date.now(), 2000);
      if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    }
  }
  async function worker() {
    while (queue.length > 0) {
      await _waitGlobalPause(); // 尊重全局暂停
      const idx = queue.shift();
      const a = _store.accounts[idx];
      if (!a) continue;
      const tag = a.email.split("@")[0].substring(0, 14);
      try {
        const r = await verifyOneAccount(a);
        if (r.ok) {
          _store.setHealth(a.email, r.q);
          ok++;
          // 连续成功 → 逐步恢复退避
          if (_rateLimitHits > 0)
            _rateLimitHits = Math.max(0, _rateLimitHits - 1);
          log(
            "verify [" +
              idx +
              "] " +
              tag +
              " ✓ D" +
              r.q.daily +
              "% W" +
              r.q.weekly +
              "% " +
              r.q.plan +
              " " +
              r.q.daysLeft +
              "d",
          );
        } else {
          fail++;
          _failedIndices.push(idx);
          log("verify [" + idx + "] " + tag + " ✗ " + r.stage + ": " + r.error);
          // v2.1.1 全局限速: 指数退避 5s → 15s → 30s → 60s · 全 worker 共享
          if (r.error && /rate.?limit|too.many|429/i.test(String(r.error))) {
            _rateLimitHits++;
            const backoff = Math.min(
              60000,
              5000 * Math.pow(2, _rateLimitHits - 1),
            );
            _globalPauseUntil = Date.now() + backoff;
            log(
              "verifyAll: 限速#" +
                _rateLimitHits +
                " · 全局暂停 " +
                Math.round(backoff / 1000) +
                "s",
            );
          }
        }
      } catch (e) {
        fail++;
        _failedIndices.push(idx);
        log("verify [" + idx + "] " + tag + " 异常 " + e.message);
      }
      done++;
      // 每 3 个 broadcast 一次 (首次验证时用户需要更频繁的反馈)
      if (done % (isFirstTime ? 3 : 5) === 0 || queue.length === 0)
        _broadcastUI();
      if (effectiveGapMs > 0 && queue.length > 0) {
        // 抖动: gapMs ± 30%
        const jitter = Math.round(effectiveGapMs * (0.7 + Math.random() * 0.6));
        await new Promise((r) => setTimeout(r, jitter));
      }
    }
  }
  const workers = [];
  for (let i = 0; i < parallel; i++) workers.push(worker());
  try {
    await Promise.all(workers);
  } catch {}
  // v2.1.1 自动重试: 首轮失败的账号 · 串行 + 长间隔 · 水善利万物而不争
  if (_failedIndices.length > 0 && _failedIndices.length <= total * 0.8) {
    const retryCount = _failedIndices.length;
    log("verifyAll: 重试 " + retryCount + " 个失败账号 · 串行 · gap 3s");
    let retryOk = 0;
    for (const idx of _failedIndices) {
      const a = _store.accounts[idx];
      if (!a) continue;
      await new Promise((r) => setTimeout(r, 3000 + Math.random() * 2000));
      try {
        const r = await verifyOneAccount(a);
        if (r.ok) {
          _store.setHealth(a.email, r.q);
          retryOk++;
          fail--;
          ok++;
          if (retryOk % 3 === 0) _broadcastUI();
        }
      } catch {}
    }
    log("verifyAll: 重试完成 · " + retryOk + "/" + retryCount + " 恢复");
  }
  _verifyAllInProgress = false;
  _broadcastUI();
  const dur = Math.round((Date.now() - t0) / 1000);
  log("verifyAll: 完成 · " + ok + " ✓ / " + fail + " ✗ · " + dur + "s");
  return { ok: true, total: ok + fail, ok, fail, durSec: dur };
}

async function injectViaJia(token) {
  const orig_show = vscode.window.showInputBox;
  const orig_open = vscode.env.openExternal;
  let showCalls = 0,
    openCalls = 0;
  const probeShow = async () => {
    showCalls++;
    return token;
  };
  const probeOpen = async () => {
    openCalls++;
    return false;
  };
  let installed = false;
  try {
    Object.defineProperty(vscode.window, "showInputBox", {
      value: probeShow,
      configurable: true,
      writable: true,
    });
    Object.defineProperty(vscode.env, "openExternal", {
      value: probeOpen,
      configurable: true,
      writable: true,
    });
    installed =
      vscode.window.showInputBox === probeShow &&
      vscode.env.openExternal === probeOpen;
  } catch (e) {
    return { ok: false, reason: "defineProperty: " + e.message };
  }
  if (!installed) return { ok: false, reason: "not-sticky" };
  let cmdErr = null;
  try {
    await vscode.commands.executeCommand("windsurf.loginWithAuthToken");
  } catch (e) {
    cmdErr = e && e.message ? e.message : String(e);
  } finally {
    try {
      Object.defineProperty(vscode.window, "showInputBox", {
        value: orig_show,
        configurable: true,
        writable: true,
      });
    } catch {}
    try {
      Object.defineProperty(vscode.env, "openExternal", {
        value: orig_open,
        configurable: true,
        writable: true,
      });
    } catch {}
  }
  if (showCalls === 0)
    return { ok: false, reason: "showInputBox-never-called", cmdErr };
  if (cmdErr) return { ok: false, reason: "handleAuthToken-error", cmdErr };
  return { ok: true, showCalls, openCalls };
}
async function injectViaYi(token) {
  await vscode.env.clipboard.writeText(token);
  const promise = vscode.commands
    .executeCommand("windsurf.loginWithAuthToken")
    .then(
      () => ({ ok: true }),
      (e) => ({ ok: false, error: (e && e.message) || String(e) }),
    );
  vscode.window.showInformationMessage(
    "WAM: token 已复制 · 请在 inputBox 按 Ctrl+V 然后 Enter",
    "Got it",
  );
  const r = await promise;
  return { ok: r.ok, reason: r.error || "" };
}
// 路丙: IDE 内部 authProvider 命令 · 真无为 · 不弹 UI · 不重启
// 来源: workbench.desktop.main.js · $bG.PROVIDE_AUTH_TOKEN_TO_AUTH_PROVIDER.id = "windsurf.provideAuthTokenToAuthProvider"
// 调用语义: vscode.commands.executeCommand(id, token) · 返回 { type: "success"/"failure", error?: { code, description } }
async function injectViaBing(token) {
  try {
    const c = await Promise.race([
      vscode.commands.executeCommand(
        "windsurf.provideAuthTokenToAuthProvider",
        token,
      ),
      new Promise((r) => setTimeout(() => r({ type: "_wam_timeout" }), 8000)),
    ]);
    if (c == null) return { ok: true, path: "丙", detail: "void" }; // IDE 命令成功无返回值视作 ok
    if (c.type === "_wam_timeout")
      return { ok: false, path: "丙", reason: "timeout" };
    if (c.type === "failure") {
      const err = c.error
        ? c.error.code || c.error.description || JSON.stringify(c.error)
        : "?";
      return { ok: false, path: "丙", reason: err };
    }
    return {
      ok: true,
      path: "丙",
      detail: c.type || JSON.stringify(c).substring(0, 80),
    };
  } catch (e) {
    return { ok: false, path: "丙", reason: e.message };
  }
}

async function injectToken(token) {
  // preferYi 强走旧路 (debug)
  if (_cfg("preferYi", false)) {
    const r = await injectViaYi(token);
    return { ok: r.ok, path: "乙", note: r.reason || "" };
  }
  // 路丙: IDE 内部 API (主路径 · 真无为)
  log("inject 路丙 provideAuthTokenToAuthProvider");
  const c = await injectViaBing(token);
  if (c.ok) {
    log("路丙 ✓ " + (c.detail || ""));
    return { ok: true, path: "丙" };
  }
  log("路丙 ✗ " + c.reason);
  // 路甲兜底: hijack
  log("降路甲 hijack");
  const a = await injectViaJia(token);
  if (a.ok) {
    log("路甲 ✓ showCalls=" + a.showCalls);
    return { ok: true, path: "甲" };
  }
  log("路甲 ✗ " + a.reason + (a.cmdErr ? " err: " + a.cmdErr : ""));
  // 路乙兜底: clipboard
  log("降路乙 clipboard");
  const b = await injectViaYi(token);
  return { ok: b.ok, path: "乙", note: b.reason || "" };
}

function tryLoadPendingToken() {
  try {
    if (!fs.existsSync(PENDING_TOKEN_FILE)) return null;
    const j = JSON.parse(fs.readFileSync(PENDING_TOKEN_FILE, "utf8"));
    if (!j || !j.sessionToken || !j.email) return null;
    const ageMs = Date.now() - (j.timestamp || 0);
    if (ageMs > 5 * 60 * 1000) {
      log("pending expired");
      return null;
    }
    log("pending hit · age=" + Math.round(ageMs / 1000) + "s");
    return j;
  } catch (e) {
    log("loadPending: " + e.message);
    return null;
  }
}
function consumePendingToken() {
  try {
    if (fs.existsSync(PENDING_TOKEN_FILE)) fs.unlinkSync(PENDING_TOKEN_FILE);
  } catch {}
}
function _bumpFailure(store, email, reason) {
  const k = email.toLowerCase();
  const prev = store.blacklist[k] || { count: 0 };
  const cnt = (prev.count || 0) + 1;
  if (cnt >= 3) store.banFor(email, 15 * 60 * 1000, reason);
  else {
    store.blacklist[k] = { until: Date.now() + 30 * 1000, reason, count: cnt };
    store.save();
  }
}

async function loginAccount(store, idx) {
  if (idx < 0 || idx >= store.accounts.length)
    return { ok: false, error: "idx_out_of_range" };
  const acc = store.accounts[idx];
  if (store.isBanned(acc.email))
    return { ok: false, error: "banned", stage: "preCheck" };
  const t0 = Date.now();
  const tag = acc.email.split("@")[0].substring(0, 18);
  log("login: 试 [" + idx + "] " + tag);
  const dl = await devinLogin(acc.email, acc.password);
  if (!dl.ok) {
    log("  devinLogin ✗ " + (dl.error || "?"));
    _bumpFailure(store, acc.email, "devin: " + (dl.error || "?"));
    return { ok: false, stage: "devinLogin", error: dl.error };
  }
  const pa = await windsurfPostAuth(dl.auth1);
  if (!pa.ok) {
    log("  postAuth ✗ " + (pa.error || "?"));
    _bumpFailure(store, acc.email, "postAuth: " + (pa.error || "?"));
    return { ok: false, stage: "windsurfPostAuth", error: pa.error };
  }
  tryFetchPlanStatus(pa.sessionToken)
    .then((q) => {
      if (q) {
        store.setHealth(acc.email, q);
        log(
          "  planStatus: D" +
            q.daily +
            "% W" +
            q.weekly +
            "% " +
            q.plan +
            " " +
            q.daysLeft +
            "d",
        );
        _broadcastUI();
      }
    })
    .catch(() => {});
  const inj = await injectToken(pa.sessionToken);
  if (!inj.ok) {
    log("  inject ✗ 路" + inj.path + " " + inj.note);
    _bumpFailure(store, acc.email, "inject: " + (inj.note || ""));
    return { ok: false, stage: "inject", error: inj.note };
  }
  store.setActive(idx, acc.email, pa.sessionToken, null, null, inj.path);
  registerUserViaSession(pa.sessionToken)
    .then((r) => {
      if (r.ok) {
        store.activeApiKey = r.apiKey;
        store.activeApiServerUrl = r.apiServerUrl;
        store.save();
        log("  registerUser ✓ apiServerUrl=" + r.apiServerUrl);
      }
    })
    .catch(() => {});
  const ms = Date.now() - t0;
  _lastSwitchMs = ms;
  log("login: ✓ " + tag + " · 路" + inj.path + " · " + ms + "ms");
  return { ok: true, path: inj.path, ms };
}

// ═══ § 4 · 万法之眼 (StatusBar + Webview) ═══
function updateStatusBar() {
  if (!_statusBar || !_store) return;
  const inv = _cfg("invisible", false);
  const stats = _store.getStats();
  const h = _store.activeEmail ? _store.getHealth(_store.activeEmail) : null;
  // ── 官方模式 · 最小化显示 (对齐本源 v17.42.20) ──
  if (_wamMode === "official") {
    _statusBar.text = "$(key) 官方模式";
    _statusBar.tooltip =
      "WAM v" +
      VERSION +
      " [官方模式] — 所有切号功能已停止\n点击打开管理面板，可切回WAM模式";
    _statusBar.color = undefined;
    _statusBar.backgroundColor = undefined;
    return;
  }
  const droughtTag = stats.drought ? "[旱]" : "";
  if (_engine && _engine.rotating) {
    _statusBar.text = "$(sync~spin)" + droughtTag + " 切换中…";
    _statusBar.color = new vscode.ThemeColor("statusBarItem.warningForeground");
    _statusBar.backgroundColor = new vscode.ThemeColor(
      "statusBarItem.warningBackground",
    );
  } else if (_store.activeEmail && h) {
    const liveD = Math.round(h.daily || 0);
    const liveW = Math.round(h.weekly || 0);
    if (inv) {
      _statusBar.text = "$(zap) " + stats.pwCount;
    } else {
      _statusBar.text =
        "$(zap)" +
        droughtTag +
        " D" +
        liveD +
        "%·W" +
        liveW +
        "% " +
        stats.available +
        "/" +
        stats.pwCount +
        "号";
    }
    _statusBar.color = undefined;
    _statusBar.backgroundColor = undefined;
  } else if (_store.activeEmail) {
    _statusBar.text =
      "$(zap)" +
      droughtTag +
      " " +
      stats.available +
      "/" +
      stats.pwCount +
      "号";
    _statusBar.color = undefined;
    _statusBar.backgroundColor = undefined;
  } else {
    _statusBar.text = "$(zap) " + stats.pwCount + "号";
    _statusBar.color = new vscode.ThemeColor("statusBarItem.errorForeground");
    _statusBar.backgroundColor = new vscode.ThemeColor(
      "statusBarItem.errorBackground",
    );
  }
  // ── tooltip · 对齐本源丰富信息 ──
  const ttLines = [
    "WAM v" +
      VERSION +
      (_wamMode === "wam" ? " [WAM切号]" : "") +
      (stats.drought ? " [🏜️干旱]" : ""),
  ];
  if (_store.activeEmail) ttLines.push("活跃: " + _store.activeEmail);
  if (h && h.checked)
    ttLines.push(
      h.plan +
        " · D" +
        Math.round(h.daily) +
        "% · W" +
        Math.round(h.weekly) +
        "%",
    );
  ttLines.push(
    "号池: " +
      stats.available +
      "可用 · " +
      stats.exhausted +
      "耗尽" +
      (stats.banned ? " · " + stats.banned + "黑" : ""),
  );
  ttLines.push(
    "日重置: " +
      stats.hrsToDaily.toFixed(1) +
      "h · 周重置: " +
      stats.hrsToWeekly.toFixed(1) +
      "h",
  );
  ttLines.push(
    "切换: " +
      stats.switches +
      "次" +
      (stats.changesDetected ? " · " + stats.changesDetected + "变动" : ""),
  );
  ttLines.push("点击 → 打开管理面板");
  _statusBar.tooltip = ttLines.join("\n");
}
function _broadcastUI() {
  if (_sidebarProvider) _sidebarProvider.refresh();
  if (_editorPanel) {
    try {
      _editorPanel.webview.html = buildHtml();
    } catch {}
  }
  updateStatusBar();
}

// ═══ Cascade 流式避让 (对齐本源 v17.42.5 · 道法自然: 让流完成再切 · 用户对话永不断裂) ═══
// 原理: onDidChangeTextDocument 持续追踪最近文档变化时间
// 2s 内有更新即视为"流式进行中" · 切号推迟 1s 重试 · 总等待上限 15s
// 披褐怀玉: 15s 极限后强切 (避免无限卡住 · 保护后台进度)
function _isCascadeBusy() {
  return Date.now() - _lastDocChangeAt < 2000;
}
async function _waitIfCascadeBusy(maxWaitMs) {
  if (!_isCascadeBusy()) return 0;
  const start = Date.now();
  let waited = 0;
  while (_isCascadeBusy() && Date.now() - start < (maxWaitMs || 15000)) {
    await new Promise((r) => setTimeout(r, 1000));
    waited += 1000;
  }
  if (waited > 0)
    log(
      "⏸️ cascade-avoid: waited " +
        waited +
        "ms · streaming " +
        (_isCascadeBusy() ? "still ongoing (forced)" : "completed"),
    );
  return waited;
}

// 大窗口面板 (本源 wam.openEditor 同款 · createWebviewPanel)
function openEditorPanel() {
  if (_editorPanel) {
    try {
      _editorPanel.reveal(vscode.ViewColumn.Active, false);
    } catch {}
    return _editorPanel;
  }
  _editorPanel = vscode.window.createWebviewPanel(
    "wam.editor",
    "WAM 切号管理",
    vscode.ViewColumn.Active,
    { enableScripts: true, retainContextWhenHidden: true },
  );
  _editorPanel.webview.html = buildHtml();
  _editorPanel.webview.onDidReceiveMessage((msg) => handleWebviewMessage(msg));
  _editorPanel.onDidDispose(() => {
    _editorPanel = null;
  });
  return _editorPanel;
}

class WamViewProvider {
  constructor() {
    this._view = null;
  }
  resolveWebviewView(webviewView) {
    this._view = webviewView;
    webviewView.webview.options = { enableScripts: true };
    webviewView.webview.html = buildHtml();
    webviewView.webview.onDidReceiveMessage((msg) => handleWebviewMessage(msg));
    webviewView.onDidChangeVisibility(() => {
      if (webviewView.visible) this.refresh();
    });
  }
  refresh() {
    if (this._view && this._view.visible) this._view.webview.html = buildHtml();
  }
}

function buildHtml() {
  const store = _store,
    stats = store.getStats(),
    accounts = store.accounts,
    activeI = store.activeIdx;
  const autoOn = _cfg("autoRotate", true);
  let rows = "";
  for (let i = 0; i < accounts.length; i++) {
    const a = accounts[i],
      h = store.getHealth(a.email);
    const isActive = i === activeI;
    const isBanned = store.isBanned(a.email);
    const banInfo = isBanned ? store.blacklist[a.email.toLowerCase()] : null;
    const banSec = banInfo
      ? Math.max(0, Math.round((banInfo.until - Date.now()) / 1000))
      : 0;
    const localPart = a.email.replace(/@.*/, "");
    const domain = a.email.split("@")[1] || "";
    const domainBadge = domain.endsWith(".shop")
      ? "shop"
      : /yahoo/i.test(domain)
        ? "yh"
        : /gmail/i.test(domain)
          ? "gm"
          : /outlook|hotmail|live/i.test(domain)
            ? "ms"
            : "o";
    const emailShort =
      localPart.substring(0, 14) + (localPart.length > 14 ? ".." : "");
    const isU = !h.checked;
    const dPct = isU ? 0 : Math.max(0, Math.min(100, Math.round(h.daily)));
    const wPct = isU ? 0 : Math.max(0, Math.min(100, Math.round(h.weekly)));
    const dC = isU
      ? "#555"
      : dPct <= 5
        ? "#f44"
        : dPct <= 30
          ? "#ce9178"
          : "#4ec9b0";
    const wC = isU
      ? "#555"
      : wPct <= 5
        ? "#f44"
        : wPct <= 30
          ? "#ce9178"
          : "#4ec9b0";
    const liveTag = h.hasSnap
      ? '<span class="live-dot" title="实时"></span>'
      : "";
    const ucTag = isU ? '<span class="uc">未验</span>' : "";
    const bnTag = isBanned
      ? `<span class="bn" title="${_esc(banInfo.reason || "")}">黑${banSec}s</span>`
      : "";
    const planTag =
      h.plan && h.plan !== "Trial"
        ? `<span class="plan-tag">${_esc(h.plan)}</span>`
        : "";
    const claudeOk = isClaudeAvailable(h);
    let expTag = "";
    if (h.daysLeft > 0) {
      const ec =
        h.daysLeft <= 2 ? "#f44" : h.daysLeft <= 5 ? "#ce9178" : "#4ec9b0";
      expTag = `<span class="days" style="color:${ec}" title="Plan到期: ${h.planEnd ? new Date(h.planEnd).toLocaleDateString() : ""}">${h.daysLeft}天</span>`;
    } else if (h.daysLeft < 0)
      expTag =
        '<span class="days" style="color:#ce9178" title="宽限期仍可用">已过期</span>';
    else if (h.planEnd > 0)
      expTag =
        '<span class="days" style="color:#f44" title="试用已过期">已过期</span>';
    const claudeTag =
      !claudeOk && h.checked
        ? '<span class="days" style="color:#f44;font-weight:700" title="Claude($$$)模型不可用·仅免费模型">⊘Claude</span>'
        : "";
    const freshTag =
      h.staleMin >= 0 && h.staleMin <= 3
        ? '<span class="fresh">&#8226;</span>'
        : "";
    rows += `
    <div class="row${isActive ? " act" : ""}${isBanned ? " banned" : ""}${!claudeOk && h.checked ? " expired-row" : ""}" data-i="${i}" data-email="${_esc(a.email.toLowerCase())}">
      <input type="checkbox" class="chk" data-i="${i}" />
      <span class="dm ${domainBadge}" title="${_esc(domain)}">${domainBadge}</span>
      <span class="em" title="${_esc(a.email)}">${_esc(emailShort)}</span>
      ${expTag}${planTag}${claudeTag}${bnTag}${freshTag}${liveTag}${ucTag}
      <span class="qt">
        <span class="mb"><span class="mf" style="width:${dPct}%;background:${dC}"></span></span>
        <span class="ql" style="color:${dC}">${isU ? "D?" : "D" + dPct}</span>
        <span class="mb"><span class="mf" style="width:${isU ? 0 : wPct}%;background:${wC}"></span></span>
        <span class="ql" style="color:${wC}">${isU ? "W?" : "W" + wPct}</span>
      </span>
      <span class="acts">
        <button class="b sk" onclick="sk(${i})" title="${a.skipAutoSwitch ? "已锁定·自动切号跳过此号(点击解锁)" : "锁定·防止自动切号选到此号"}" style="opacity:${a.skipAutoSwitch ? "1;color:#f0c674" : ".4"}">${a.skipAutoSwitch ? "&#128274;" : "&#128275;"}</button>
        <button class="b sw" onclick="sw(${i})" title="手动切换(无限制)"${isBanned ? " disabled" : ""}${_wamMode === "official" ? ' disabled style="opacity:.3;cursor:not-allowed"' : ""}>&#9889;</button>
        <button class="b vf" onclick="vf(${i})" title="验证">&#128270;</button>
        <button class="b cp" onclick="cp(${i})" title="复制">&#128203;</button>
        <button class="b rm" onclick="rm(${i})" title="删除">&times;</button>
      </span>
    </div>`;
  }
  const cc = stats.checkedCount;
  const poolPct =
    cc > 0 ? Math.round((stats.drought ? stats.totalD : stats.totalW) / cc) : 0;
  const poolColor =
    poolPct >= 60 ? "#4ec9b0" : poolPct >= 30 ? "#ce9178" : "#f44";
  const monitorBar = `<div class="monitor-bar"><span class="mon-dot${autoOn ? "" : " off"}"></span><span class="mon-stat">D重置${stats.hrsToDaily.toFixed(1)}h</span><span class="mon-stat">W重置${stats.hrsToWeekly.toFixed(1)}h</span></div>`;
  let activeHtml =
    '<div class="act-info empty">未选择活跃账号 · 点击下方任意 ⚡ 即可登录</div>';
  if (activeI >= 0 && accounts[activeI]) {
    const aa = accounts[activeI],
      ah = store.getHealth(aa.email);
    const liveD = Math.round(ah.daily),
      liveW = Math.round(ah.weekly);
    const isDrought = stats.drought;
    const effQuota = isDrought ? liveD : Math.min(liveD, liveW);
    const ec =
      ah.checked && effQuota < 5
        ? "var(--red)"
        : ah.checked && effQuota < 30
          ? "var(--orange)"
          : "var(--green)";
    const switchHint =
      ah.checked && effQuota < 5
        ? isDrought
          ? ' · <b style="color:var(--orange)">干旱·D耗尽即切</b>'
          : ' · <b style="color:var(--red)">即将切号</b>'
        : isDrought
          ? ' · <span style="color:#d29922;font-size:9px">[干旱·只看D]</span>'
          : "";
    const activeClaudeOk = isClaudeAvailable(ah);
    const activeClaudeTag = !activeClaudeOk
      ? ' <span style="color:var(--red);font-weight:700">⊘Claude不可用</span>'
      : "";
    const planExpiryTag =
      ah.daysLeft > 0
        ? ` <span style="color:${ah.daysLeft <= 2 ? "var(--red)" : ah.daysLeft <= 5 ? "var(--orange)" : "var(--green)"}">${ah.daysLeft}天</span>`
        : ah.planEnd > 0
          ? ' <span style="color:var(--red)">已过期</span>'
          : "";
    const switchInfo = _lastSwitchMs > 0 ? " · " + _lastSwitchMs + "ms" : "";
    const switchAge =
      store.lastRotateAt > 0
        ? Math.round((Date.now() - store.lastRotateAt) / 60000)
        : 0;
    const switchAgeStr = switchAge > 0 ? switchAge + "min前切" : "";
    activeHtml = `<div class="act-info"><b>当前:</b> ${_esc(aa.email)}${ah.plan ? `<span class="tag">${_esc(ah.plan)}</span>` : ""}${planExpiryTag}${activeClaudeTag}<span style="color:${ec}">D${liveD}%·W${liveW}%</span>${switchHint}<br><small>token: ${_esc(store.activeTokenShort || "-")} · 路${_esc(store.lastInjectPath || "-")}${switchInfo} · ${ah.staleMin >= 0 ? ah.staleMin + "min前采样" : "无快照"}${switchAgeStr ? " · " + switchAgeStr : ""}</small></div>`;
  }
  return `<!DOCTYPE html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';">
<style>
:root{--bg:var(--vscode-editor-background);--fg:var(--vscode-editor-foreground);--border:var(--vscode-panel-border,#2d2d2d);--input-bg:var(--vscode-input-background,#1e1e1e);--input-border:var(--vscode-input-border,#3c3c3c);--btn:var(--vscode-button-background,#0e639c);--btn-h:var(--vscode-button-hoverBackground,#1177bb);--green:#4ec9b0;--orange:#ce9178;--red:#f44;--blue:#9cdcfe}
*{margin:0;padding:0;box-sizing:border-box}
body{font:12px/1.5 -apple-system,'Segoe UI',sans-serif;background:var(--bg);color:var(--fg);padding:6px 8px;overflow-x:hidden}
.hd{margin-bottom:8px}
.pool-bar{height:5px;background:#252525;border-radius:3px;margin:6px 0;overflow:hidden}
.pool-fill{height:100%;border-radius:3px;background:linear-gradient(90deg,${poolColor}88,${poolColor});transition:width .4s}
.st{display:flex;flex-wrap:wrap;gap:8px;font-size:11px;color:#777;margin:4px 0}
.st b{color:#ccc}.st .ex{color:var(--red)}
.act-info{background:#264f7833;border-left:3px solid var(--blue);padding:4px 8px;margin:6px 0;font-size:11px;color:var(--blue);border-radius:0 4px 4px 0}
.act-info.empty{color:#777;border-left-color:#555;background:#1a1a1a}
.act-info b{color:var(--blue)}
.act-info .tag{background:#264f78;color:var(--blue);padding:1px 6px;border-radius:3px;font-size:10px;margin-left:4px}
.add-section{margin:6px 0;border:1px solid var(--border);border-radius:6px;overflow:hidden}
.add-header{background:#1a1a1a;padding:4px 8px;font-size:11px;color:#888;cursor:pointer;display:flex;justify-content:space-between}
.add-body{padding:6px 8px;display:none}.add-body.open{display:block}
.add-body textarea{width:100%;min-height:80px;background:var(--input-bg);border:1px solid var(--input-border);color:#ccc;padding:6px 8px;border-radius:4px;font-size:11px;outline:none;resize:vertical;font-family:monospace}
.add-body .add-actions{display:flex;gap:4px;margin-top:4px}
.add-body .add-actions button{background:var(--btn);color:#fff;border:none;padding:4px 12px;border-radius:4px;cursor:pointer;font-size:11px}
.add-body .add-hint{font-size:10px;color:#555;margin-top:4px}
.sec{display:flex;justify-content:space-between;align-items:center;color:#777;font-size:11px;margin:8px 0 3px;padding-bottom:3px;border-bottom:1px solid var(--border)}
.row{display:flex;align-items:center;padding:3px 2px;border-bottom:1px solid #1a1a1a;gap:4px}
.row:hover{background:#2a2d2e}
.row.act{background:#264f7844;border-left:2px solid var(--blue)}
.row.banned{opacity:.5;background:#2a1a1a}
.row.expired-row{opacity:.55;background:#1a1515}
.row.switching{opacity:.6;pointer-events:none;position:relative}
.row.switching::after{content:'⏳';position:absolute;right:6px;animation:pulse 1s infinite}
.row.verifying{opacity:.7}
.row.verifying .b.vf{animation:spin .8s linear infinite}
@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
.b.clicked{transform:scale(0.85);transition:transform .1s}
.toast.ok{background:#1a3a1a;color:var(--green);border:1px solid #2a5a2a}
.toast.fail{background:#3a1a1a;color:var(--red);border:1px solid #5a2a2a}
.chk{width:14px;height:14px;cursor:pointer;flex-shrink:0}
.dm{width:24px;height:14px;border-radius:2px;font-size:9px;font-weight:700;text-align:center;line-height:14px;flex-shrink:0;color:#aaa}
.dm.shop{background:#553399;color:#cdb}
.dm.yh{background:#4a1564;color:#cce}
.dm.gm{background:#3a3a3a;color:#9cdcfe}
.dm.ms{background:#1a3a5a;color:#9cf}
.dm.o{background:#333;color:#999}
.em{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:11px}
.uc{font-size:9px;background:#333;color:#888;padding:0 4px;border-radius:3px}
.bn{font-size:9px;background:#5a1d1d;color:#f88;padding:0 4px;border-radius:3px}
.plan-tag{font-size:9px;background:#1a3a1a;color:var(--blue);padding:0 4px;border-radius:3px}
.days{font-size:9px;color:#666}
.qt{display:flex;align-items:center;gap:2px;flex-shrink:0;min-width:100px}
.mb{width:18px;height:4px;background:#252525;border-radius:2px;overflow:hidden}
.mf{display:block;height:100%}
.ql{font-size:10px;font-weight:600;width:26px;text-align:right}
.acts{display:flex;gap:2px}
.b{width:20px;height:20px;border:none;border-radius:3px;cursor:pointer;font-size:11px;display:flex;align-items:center;justify-content:center;padding:0}
.b.sw{background:var(--btn);color:#fff}.b.sw:hover{background:var(--btn-h)}
.b.sw:disabled{opacity:.3;cursor:not-allowed}
.b.sk{background:transparent;color:#666;font-size:12px}.b.sk:hover{color:#f0c674}
.b.vf,.b.cp{background:#333;color:var(--blue)}.b.vf:hover,.b.cp:hover{background:#444}
.b.rm{background:transparent;color:#555;font-size:14px}.b.rm:hover{color:var(--red)}
.toast{position:fixed;bottom:8px;left:8px;right:8px;background:#264f78;color:var(--blue);padding:6px 10px;border-radius:4px;font-size:11px;opacity:0;transition:opacity .3s;pointer-events:none;z-index:99}
.toast.show{opacity:1}
.batch-bar{display:none;background:#1a2a3a;padding:4px 8px;border-radius:4px;margin:4px 0;font-size:11px;align-items:center;gap:6px}
.batch-bar.visible{display:flex}
.batch-bar button{background:#5a1d1d;color:var(--red);border:none;padding:2px 10px;border-radius:3px;cursor:pointer;font-size:11px}
.monitor-bar{display:flex;align-items:center;gap:6px;background:#1a2a1a;border:1px solid #2a3a2a;border-radius:4px;padding:3px 8px;margin:4px 0;font-size:10px;color:var(--blue);flex-wrap:wrap}
.mon-dot{width:6px;height:6px;border-radius:50%;background:var(--green);animation:pulse 2s infinite}
.mon-dot.off{background:#666;animation:none}
.mon-stat{padding:0 3px}
.mode-sw{display:inline-flex;align-items:center;gap:3px;font-size:10px;color:#666;float:right}
.mode-sw button{background:transparent;color:#555;border:1px solid #333;padding:1px 6px;border-radius:3px;cursor:pointer;font-size:10px;transition:all .15s}
.mode-sw button:hover{color:var(--blue);border-color:#555}
.mode-sw button.on{color:var(--green);border-color:#2a4a2a}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.live-dot{display:inline-block;width:5px;height:5px;border-radius:50%;background:var(--green);margin:0 2px;animation:pulse 2s infinite}
.fresh{color:var(--green);font-size:14px}
.row.quota-flash{animation:qflash .6s}
@keyframes qflash{0%{background:#5a3a0a}100%{background:transparent}}
.footer{margin-top:8px;padding-top:6px;border-top:1px solid var(--border);font-size:10px;color:#555;text-align:center;word-break:break-all}
.footer .v{color:var(--blue)}
</style></head><body>
<div class="hd">
<div class="st"><span style="color:${poolColor};font-weight:700">D${stats.totalD} W${stats.totalW}</span><span><b>${stats.available}</b>可用</span>${stats.exhausted > 0 ? `<span class="ex"><b>${stats.exhausted}</b>耗尽</span>` : ""}<span><b>${stats.pwCount}</b>号</span>${stats.unchecked > 0 ? `<span style="color:var(--blue)"><b>${stats.unchecked}</b>未验</span>` : ""}${stats.banned > 0 ? `<span style="color:var(--red)"><b>${stats.banned}</b>黑</span>` : ""}<span class="mode-sw"><button class="${_wamMode === "wam" ? "on" : ""}" onclick="setMode('wam')" title="WAM 自动切号">WAM</button><button class="${_wamMode === "official" ? "on" : ""}" onclick="setMode('official')" title="官方登录·停引擎">官方</button></span></div>
<div class="pool-bar"><div class="pool-fill" style="width:${poolPct}%"></div></div>
${activeHtml}${monitorBar}
${_wamMode === "official" ? '<div style="background:#2a1a1a;border:1px solid #4a2a2a;border-radius:4px;padding:6px 10px;margin:4px 0;font-size:11px;color:#f87171"><b>&#128274; 官方登录模式</b><br>WAM 引擎已停 (扫描/切号/心跳)<br>切回 WAM 模式可恢复自动轮转</div>' : ""}
${stats.drought ? '<div style="background:#2a2a1a;border:1px solid #4a4a2a;border-radius:4px;padding:4px 10px;margin:4px 0;font-size:11px;color:#eab308">&#127964;&#65039; <b>Weekly 干旱</b> 全池W耗尽·D重置 ' + stats.hrsToDaily.toFixed(1) + "h后 · 自动换号仅看D</div>" : ""}
${_verifyAllInProgress ? '<div style="background:#1a2a3a;border:1px solid #2a3a5a;border-radius:4px;padding:4px 10px;margin:4px 0;font-size:11px;color:#9cdcfe">&#9203; <b>正在批量验证</b> · 见 Output 实时进度</div>' : ""}
</div>
<div class="batch-bar" id="batchBar"><span>已选 <b id="batchCount">0</b> 个</span><button onclick="batchDelete()">批量删除</button><button onclick="clearSelection()" style="background:#333;color:var(--blue)">取消</button></div>
<div class="add-section">
<div class="add-header" onclick="toggleAdd()"><span>&#43; 添加账号</span><span id="addArrow">&#9660;</span></div>
<div class="add-body" id="addBody">
<textarea id="addInput" placeholder="支持多种格式，每行一个：&#10;email password&#10;email:password&#10;email----password&#10;email|password"></textarea>
<div class="add-actions"><button onclick="doAdd()">添加</button><button onclick="copyAll()" style="background:#333;color:var(--blue);margin-left:auto">&#128203; 一键导出</button></div>
<div class="add-hint">支持批量粘贴 · 自动识别各种分隔符 · 重复跳过</div>
</div></div>
<div class="sec"><span>&#9660; 账号列表 (${stats.pwCount})</span></div>
<div id="list">${rows}</div>
<div class="footer">WAM <span class="v">v${VERSION}</span><br>${_esc(store.accountsSource || "")}</div>
<div class="toast" id="toast"></div>
<script>
const vscode = acquireVsCodeApi();
function send(t,i){vscode.postMessage({type:t,index:i});}
function _clickFb(e){if(!e||!e.target)return;const b=e.target.closest('.b');if(b){b.classList.add('clicked');setTimeout(()=>b.classList.remove('clicked'),150);}}
function sw(i){_clickFb(event);send('switch',i);}
function sk(i){_clickFb(event);send('toggleSkip',i);}
function vf(i){_clickFb(event);send('verify',i);}
function cp(i){_clickFb(event);vscode.postMessage({type:'copyAccount',index:i});}
function rm(i){_clickFb(event);send('remove',i);}
function copyAll(){vscode.postMessage({type:'copyAllAccounts'});}
function setMode(m){vscode.postMessage({type:'setMode',mode:m});}
function toggleAdd(){const b=document.getElementById('addBody');b.classList.toggle('open');document.getElementById('addArrow').textContent=b.classList.contains('open')?'\\u25B2':'\\u25BC';}
function doAdd(){const ta=document.getElementById('addInput');const t=ta.value.trim();if(!t)return;vscode.postMessage({type:'addBatch',text:t});ta.value='';}
function showToast(m,cls){const t=document.getElementById('toast');t.textContent=m;t.className='toast show'+(cls?' '+cls:'');setTimeout(()=>{t.className='toast';},2200);}
function updateBatchBar(){const c=document.querySelectorAll('.chk:checked');document.getElementById('batchCount').textContent=c.length;document.getElementById('batchBar').classList.toggle('visible',c.length>0);}
function batchDelete(){const ix=[...document.querySelectorAll('.chk:checked')].map(c=>parseInt(c.dataset.i));if(ix.length===0)return;vscode.postMessage({type:'removeBatch',indices:ix});}
function clearSelection(){document.querySelectorAll('.chk:checked').forEach(c=>c.checked=false);updateBatchBar();}
document.addEventListener('change',e=>{if(e.target.classList.contains('chk'))updateBatchBar();});
window.addEventListener('message',e=>{const m=e.data;
if(m.type==='toast'){const cls=m.text&&m.text.startsWith('\\u2713')?'ok':m.text&&m.text.startsWith('\\u2717')?'fail':'';showToast(m.text,cls);}
if(m.type==='switching'){const r=document.querySelector('.row[data-i=\"'+m.index+'\"]');if(r){r.classList.add('switching');showToast('\\u26A1 \\u5207\\u6362\\u4E2D...');}}
if(m.type==='verifying'){const r=document.querySelector('.row[data-i=\"'+m.index+'\"]');if(r){r.classList.add('verifying');}}
if(m.type==='quotaChange'){const r=document.querySelector('.row[data-email=\"'+(m.email||'').toLowerCase()+'\"]');if(r){r.classList.add('quota-flash');setTimeout(()=>r.classList.remove('quota-flash'),700);}}
});
</script></body></html>`;
}

function _toast(text) {
  if (_sidebarProvider && _sidebarProvider._view) {
    try {
      _sidebarProvider._view.webview.postMessage({ type: "toast", text });
    } catch {}
  }
  if (_editorPanel) {
    try {
      _editorPanel.webview.postMessage({ type: "toast", text });
    } catch {}
  }
}

function _broadcastMsg(msg) {
  if (_sidebarProvider && _sidebarProvider._view) {
    try {
      _sidebarProvider._view.webview.postMessage(msg);
    } catch {}
  }
  if (_editorPanel) {
    try {
      _editorPanel.webview.postMessage(msg);
    } catch {}
  }
}

async function handleWebviewMessage(msg) {
  try {
    switch (msg.type) {
      case "switch": {
        // v17.42.20 手动抢占: _switching 超 30s 强制释放
        if (_switching) {
          const lockAge = Date.now() - _switchingStartTime;
          if (lockAge < 30000) {
            _toast("正在切换中(" + Math.round(lockAge / 1000) + "s)...");
            return;
          }
          log(
            "switch: 手动抢占 — 强制释放超时锁(" +
              Math.round(lockAge / 1000) +
              "s)",
          );
          _switching = false;
        }
        if (_engine.rotating && !_switching) {
          _toast("引擎正在轮转中...");
          return;
        }
        _switching = true;
        _switchingStartTime = Date.now();
        _engine.rotating = true;
        _broadcastMsg({ type: "switching", index: msg.index });
        _broadcastUI();
        try {
          const r = await loginAccount(_store, msg.index);
          if (r.ok) {
            _toast(
              "✓ " +
                (_store.activeEmail || "?").split("@")[0] +
                " · 路" +
                r.path +
                " · " +
                (r.ms || 0) +
                "ms",
            );
          } else {
            _toast("✗ " + r.stage + ": " + r.error);
          }
        } finally {
          _switching = false;
          _engine.rotating = false;
          _broadcastUI();
        }
        break;
      }
      case "verify": {
        const i = msg.index;
        if (i < 0 || i >= _store.accounts.length) return;
        const a = _store.accounts[i];
        const vt0 = Date.now();
        _broadcastMsg({ type: "verifying", index: i });
        _toast("🔍 验证中: " + a.email.split("@")[0]);
        const dl = await devinLogin(a.email, a.password);
        if (!dl.ok) {
          _bumpFailure(_store, a.email, "verify-devin: " + dl.error);
          _toast("✗ devin: " + dl.error + " · " + (Date.now() - vt0) + "ms");
          _broadcastUI();
          return;
        }
        const pa = await windsurfPostAuth(dl.auth1);
        if (!pa.ok) {
          _bumpFailure(_store, a.email, "verify-postAuth: " + pa.error);
          _toast("✗ postAuth: " + pa.error + " · " + (Date.now() - vt0) + "ms");
          _broadcastUI();
          return;
        }
        const q = await tryFetchPlanStatus(pa.sessionToken);
        const vms = Date.now() - vt0;
        if (q) {
          _store.setHealth(a.email, q);
          _toast(
            "✓ " +
              a.email.split("@")[0] +
              " D" +
              q.daily +
              "% W" +
              q.weekly +
              "% " +
              (q.plan || "") +
              " · " +
              vms +
              "ms",
          );
        } else {
          _store.setHealth(a.email, { plan: "?", daily: 0, weekly: 0 });
          _toast("✓ 登录通 · PlanStatus 未取到 · " + vms + "ms");
        }
        const k = a.email.toLowerCase();
        if (_store.blacklist[k]) {
          delete _store.blacklist[k];
          _store.save();
        }
        _broadcastUI();
        break;
      }
      case "remove":
        _store.remove(msg.index);
        _toast("已删除");
        _broadcastUI();
        break;
      case "removeBatch": {
        const n = _store.removeBatch(msg.indices || []);
        _toast("批量删除 " + n + " 个");
        _broadcastUI();
        break;
      }
      case "addBatch": {
        const r = _store.addBatch(msg.text || "");
        let info = "添加 " + r.added + " 个";
        if (r.duplicate > 0) info += " · 跳重 " + r.duplicate;
        _toast(info);
        _store.reloadAccounts();
        _broadcastUI();
        break;
      }
      case "copyAccount": {
        const a = _store.accounts[msg.index];
        if (a) {
          await vscode.env.clipboard.writeText(a.email + ":" + a.password);
          _toast("\u2713 已复制 " + a.email.split("@")[0]);
        }
        break;
      }
      case "copyAllAccounts": {
        const lines = _store.accounts.map((a) => a.email + ":" + a.password);
        await vscode.env.clipboard.writeText(lines.join("\n"));
        _toast("\u2713 已导出 " + lines.length + " 个账号到剪贴板");
        break;
      }
      // ── 本源 v17.42.7 锁🔒 toggleSkip ──
      case "toggleSkip": {
        const acc3 = _store.accounts[msg.index];
        if (acc3) {
          acc3.skipAutoSwitch = !acc3.skipAutoSwitch;
          // v17.42.7 锁🔒贯通: 即时联动 — 若刚锁的正是 _predictiveCandidate, 立刻失效
          if (acc3.skipAutoSwitch && _predictiveCandidate === msg.index) {
            _predictiveCandidate = -1;
            log(
              "🔒 lock: " +
                acc3.email.substring(0, 20) +
                " 是 _predictiveCandidate → 即时作废",
            );
          }
          log(
            "🔒 " +
              (acc3.skipAutoSwitch ? "锁" : "解锁") +
              ": " +
              acc3.email.substring(0, 20),
          );
          _toast(
            (acc3.skipAutoSwitch ? "🔒 已锁定 " : "🔓 已解锁 ") +
              acc3.email.split("@")[0],
          );
          _store.save();
          _broadcastUI();
        }
        break;
      }
      case "setMode": {
        const m = msg.mode === "official" ? "official" : "wam";
        if (m === _wamMode) {
          _toast(
            "当前已是 " + (m === "wam" ? "WAM切号" : "官方登录") + " 模式",
          );
          break;
        }
        _wamMode = m;
        if (m === "official") {
          if (_engine) _engine.stopMonitor();
          _toast("已切官方登录模式 · WAM 引擎停");
          log("setMode: official · 引擎停");
        } else {
          if (_engine) _engine.startMonitor();
          _toast("已切 WAM 切号模式 · 引擎启");
          log("setMode: wam · 引擎启");
        }
        if (_ctx) _ctx.globalState && _ctx.globalState.update("wam.mode", m);
        _broadcastUI();
        break;
      }
      // ── 对齐本源: refresh (刷新视图) ──
      case "refresh": {
        _store.reloadAccounts();
        _broadcastUI();
        break;
      }
      // ── 对齐本源: autoRotate (智能轮转) ──
      case "autoRotate": {
        if (_wamMode === "official") {
          _toast("官方模式下不可自动切号");
          break;
        }
        _toast("⚡ 智能轮转中…");
        try {
          await _engine.rotateNext();
        } catch (e2) {
          log("autoRotate err: " + (e2.message || e2));
        }
        _broadcastUI();
        break;
      }
      // ── 对齐本源: verifyAll (全量验证) ──
      case "verifyAll": {
        if (_verifyAllInProgress) {
          _toast("验证已在运行中");
          break;
        }
        _toast("🔍 全量验证 " + _store.accounts.length + " 个号中…");
        verifyAllAccounts({ onlyStale: false })
          .then((r2) => {
            if (r2)
              _toast(
                "✓ 验证完成: " +
                  r2.ok +
                  " ✓ / " +
                  r2.fail +
                  " ✗ · " +
                  r2.durSec +
                  "s",
              );
            _broadcastUI();
          })
          .catch((e2) => log("verifyAll err: " + (e2.message || e2)));
        break;
      }
      // ── 对齐本源: scanExpiry (刷新缺失有效期) ──
      case "scanExpiry": {
        _toast("🔍 扫描缺失有效期…");
        let fetched2 = 0,
          failed2 = 0;
        for (const a of _store.accounts) {
          const hh = _store.getHealth(a.email);
          if (hh.checked && hh.planEnd > 0) continue;
          try {
            const vr = await verifyOneAccount(a);
            if (vr.ok && vr.q) {
              _store.setHealth(a.email, vr.q);
              fetched2++;
            } else failed2++;
          } catch {
            failed2++;
          }
          if ((fetched2 + failed2) % 5 === 0) _broadcastUI();
        }
        _toast("有效期扫描: " + fetched2 + " ✓ / " + failed2 + " ✗");
        _broadcastUI();
        break;
      }
      // ── 对齐本源: openEditor (从侧栏打开大窗口) ──
      case "openEditor": {
        openEditorPanel();
        break;
      }
    }
  } catch (e) {
    log("handleMsg err: " + (e.stack || e.message || e));
  }
}

// ═══ § 5 · 万法之运 (auto-rotate · 健康检查 · activate) ═══
class Engine {
  constructor(store) {
    this.store = store;
    this.rotating = false;
    this.scanTimer = null;
    this.lastScanAt = 0;
    this.bootRotateDone = false;
  }

  async rotateNext(opts) {
    if (this.rotating) {
      log("rotate: in-progress");
      return { ok: false, busy: true };
    }
    this.rotating = true;
    _broadcastUI();
    try {
      if (opts && opts.tryPending) {
        const j = tryLoadPendingToken();
        if (j) {
          const inj = await injectToken(j.sessionToken);
          if (inj.ok) {
            consumePendingToken();
            let idx = this.store.accounts.findIndex(
              (a) => a.email.toLowerCase() === j.email.toLowerCase(),
            );
            if (idx < 0 && j.sourceIdx != null) idx = j.sourceIdx;
            if (idx >= 0)
              this.store.setActive(
                idx,
                j.email,
                j.sessionToken,
                null,
                null,
                inj.path,
              );
            log("pending inject ✓ 路" + inj.path);
            return { ok: true, path: inj.path };
          }
        }
      }
      if (this.store.accounts.length === 0) {
        _notify("warn", "WAM: 无账号可切");
        return { ok: false };
      }
      // 始终按健康分降序排 (黑名单已排除) · 高配额账号优先
      // boot 首次切: 排除当前 active idx · 后续切: 也排除当前 active 避免回切自己
      const order = this.store.getSortedIndices(this.store.activeIdx);
      if (!this.bootRotateDone) this.bootRotateDone = true;
      log("rotate: 候选 " + order.length + " 个 (按 score 降序)");
      for (const idx of order) {
        const r = await loginAccount(this.store, idx);
        if (r.ok) return r;
      }
      _notify("error", "WAM: 所有账号都失败 · 见 Output: WAM");
      return { ok: false };
    } finally {
      this.rotating = false;
      _broadcastUI();
    }
  }

  async panicSwitch() {
    log("panic: 紧急切下一号");
    return this.rotateNext();
  }

  async refreshAll() {
    log("refreshAll → verifyAllAccounts(onlyStale)");
    return verifyAllAccounts({ onlyStale: true });
  }

  async healthCheck() {
    log("healthCheck: 自诊断 + 自愈");
    let activeOk = false;
    if (
      this.store.activeApiKey &&
      typeof this.store.activeApiKey === "string" &&
      this.store.activeApiKey.startsWith("devin-session-token$")
    ) {
      const q = await tryFetchPlanStatus(this.store.activeApiKey);
      activeOk = !!q;
      if (q && this.store.activeEmail)
        this.store.setHealth(this.store.activeEmail, q);
    }
    log("healthCheck: active-token=" + (activeOk ? "✓" : "✗"));
    if (!activeOk && this.store.activeEmail) {
      log("自愈: rotateNext");
      await this.rotateNext();
    }
    _notify("info", "WAM 健康: " + (activeOk ? "✓ active有效" : "✗ 已自愈"));
    _broadcastUI();
    return { ok: activeOk };
  }

  startMonitor() {
    if (this.scanTimer) return;
    const ms = Math.max(30000, _cfg("scanIntervalMs", 60000) | 0);
    log("monitor start · period=" + ms + "ms");
    this.scanTimer = setInterval(() => {
      this._tick().catch((e) => log("tick err: " + (e.message || e)));
    }, ms);
  }

  stopMonitor() {
    if (this.scanTimer) {
      clearInterval(this.scanTimer);
      this.scanTimer = null;
    }
  }

  // ── v2.1 _tick: 耗尽保护 · 预判候选 · 切号冷却 · 重试3次 · 重置等待 ──
  async _tick() {
    this.lastScanAt = Date.now();
    if (!_cfg("autoRotate", true)) return;
    // 切号锁超时保护 — 必须在 _switching 守卫之前 (v2.1 根治死代码)
    if (
      _switching &&
      _switchingStartTime > 0 &&
      Date.now() - _switchingStartTime > 120000
    ) {
      log("⚠️ switching lock timeout (>120s) — force release");
      _switching = false;
      _switchingStartTime = 0;
    }
    if (_switching || this.rotating) return;
    if (!this.store.activeEmail || !this.store.activeApiKey) return;

    const q = await tryFetchPlanStatus(this.store.activeApiKey);
    if (!q) {
      log("tick: planStatus 拉空 · 跳过");
      return;
    }
    this.store.setHealth(this.store.activeEmail, q);
    _broadcastUI();

    const activeI = this.store.activeIdx;
    const acc = activeI >= 0 ? this.store.accounts[activeI] : null;
    if (!acc) return;
    const threshold = _cfg("autoSwitchThreshold", 5);
    const predictiveThreshold = _cfg("predictiveThreshold", 25);
    const switchCooldownMs = _cfg("switchCooldownMs", 15000);
    const waitResetHours = _cfg("waitResetHours", 3);
    const drought = isWeeklyDrought();
    const effQuota = drought ? q.daily : Math.min(q.daily, q.weekly);
    const hrsToDaily = hoursUntilDailyReset();
    const hrsToWeekly = hoursUntilWeeklyReset();

    // ── 预判候选: 额度 < predictiveThreshold% 时提前预选 ──
    if (effQuota < predictiveThreshold && _predictiveCandidate < 0) {
      _predictiveCandidate = this.store.getBestIndex(activeI);
      if (_predictiveCandidate >= 0)
        log(
          "🔮 预判: 额度" +
            effQuota.toFixed(0) +
            "%<" +
            predictiveThreshold +
            "%, 预选→" +
            this.store.accounts[_predictiveCandidate].email.substring(0, 20),
        );
    }
    if (effQuota >= predictiveThreshold) _predictiveCandidate = -1;

    // ── 耗尽保护: 额度极低时强制切号 ──
    const isExhausted = effQuota < threshold;
    const switchCooldown = Date.now() - _lastSwitchTime < switchCooldownMs;
    if (isExhausted && !_switching && !switchCooldown && !acc.skipAutoSwitch) {
      // 重置等待: Daily/Weekly 即将重置 → 不切号
      if (q.daily < threshold && hrsToDaily <= waitResetHours) {
        log(
          "⏳ Daily耗尽(" +
            q.daily +
            "%) 但" +
            hrsToDaily.toFixed(1) +
            "h后重置 → 等待",
        );
        return;
      }
      if (
        !drought &&
        q.daily >= threshold &&
        q.weekly < threshold &&
        hrsToWeekly <= waitResetHours
      ) {
        log(
          "⏳ Weekly耗尽(" +
            q.weekly +
            "%) 但" +
            hrsToWeekly.toFixed(1) +
            "h后重置 → 等待",
        );
        return;
      }
      const reason = drought
        ? "Daily耗尽(" + q.daily + "%)"
        : q.weekly < threshold
          ? "Weekly耗尽(" + q.weekly + "%)"
          : "Daily耗尽(" + q.daily + "%)";
      // v17.42.7 锁🔒贯通: 统一由 _isValidAutoTarget 四辨
      let bestI = _isValidAutoTarget(_predictiveCandidate)
        ? _predictiveCandidate
        : this.store.getBestIndex(activeI);
      if (bestI >= 0) {
        log(
          "⚡ 耗尽保护: " +
            reason +
            " → " +
            this.store.accounts[bestI].email.substring(0, 20),
        );
        await this._doAutoSwitch(bestI, activeI, "exhaust");
      } else {
        log("耗尽保护: " + reason + ", 无可用账号");
        _notify("warn", "WAM: " + reason + "，无空闲账号");
      }
    } else if (!isExhausted) {
      // ── 时间轮转: rotatePeriodMs > 0 时 · 定期换号防检测 (兵无常势) ──
      const rotatePeriodMs = Math.max(0, _cfg("rotatePeriodMs", 0) | 0);
      if (
        rotatePeriodMs > 0 &&
        _lastSwitchTime > 0 &&
        Date.now() - _lastSwitchTime > rotatePeriodMs &&
        !acc.skipAutoSwitch
      ) {
        const bestI2 = this.store.getBestIndex(activeI);
        if (bestI2 >= 0) {
          log(
            "⏰ 时间轮转: " +
              Math.round((Date.now() - _lastSwitchTime) / 60000) +
              "min已过 · 换→ " +
              this.store.accounts[bestI2].email.substring(0, 20),
          );
          await this._doAutoSwitch(bestI2, activeI, "time-rotate");
        }
      } else if (this.lastScanAt % 5 === 0) {
        log("tick: D" + q.daily + "% W" + q.weekly + "% ok");
      }
    }
  }

  // ── 自动切号核心 (含 3 次重试 · 流式避让 · 对齐本源 v17.42.20) ──
  async _doAutoSwitch(bestI, excludeI, tag) {
    _switching = true;
    _switchingStartTime = Date.now();
    this.rotating = true;
    _broadcastUI();
    try {
      // v17.42.5 太上不知有之: cascade 流式避让 · 对话永不被打断
      await _waitIfCascadeBusy(15000);
      let switchOk = false;
      for (let _retry = 0; _retry < 3 && !switchOk; _retry++) {
        if (_retry > 0) {
          bestI = this.store.getBestIndex(excludeI);
          if (bestI < 0) break;
          log(
            tag +
              "-retry#" +
              _retry +
              ": → " +
              this.store.accounts[bestI].email.substring(0, 20),
          );
        }
        const sr = await loginAccount(this.store, bestI);
        if (sr.ok) {
          _lastSwitchTime = Date.now();
          _predictiveCandidate = this.store.getBestIndex(bestI);
          if (_predictiveCandidate >= 0)
            log(
              "🔮 预选下一个: → " +
                this.store.accounts[_predictiveCandidate].email.substring(
                  0,
                  20,
                ),
            );
          const autoMs = Date.now() - _switchingStartTime;
          _notify(
            "verbose",
            "WAM: " +
              tag +
              " → " +
              (this.store.activeEmail || "?") +
              " · " +
              autoMs +
              "ms",
          );
          switchOk = true;
        } else if (sr.error && /登录失败/.test(sr.error)) {
          log(tag + " FAIL#" + _retry + ": " + sr.error + " — 尝试下一个");
          continue;
        } else {
          // 注入失败 → 短暂等待后重试
          if (_retry < 2) {
            log(
              tag +
                " FAIL#" +
                _retry +
                ": " +
                (sr.error || "?") +
                " — 3s后重试",
            );
            await new Promise((r) => setTimeout(r, 3000));
            continue;
          }
          log(tag + " FAIL: " + (sr.error || "?"));
          _predictiveCandidate = -1;
          break;
        }
      }
      if (!switchOk) _predictiveCandidate = -1;
    } finally {
      _switching = false;
      this.rotating = false;
      _broadcastUI();
    }
  }
}

// ═══ activate / deactivate ═══
async function activate(context) {
  _ctx = context;
  _output = vscode.window.createOutputChannel("WAM");
  context.subscriptions.push(_output);
  log("WAM v" + VERSION + " activate · pid=" + process.pid);
  ensureDir(WAM_DIR);
  _store = new Store();
  _store.load();
  _store.reloadAccounts();
  _store.save();
  log(
    "accounts loaded: " +
      _store.accounts.length +
      " from " +
      (_store.accountsSource || "<none>"),
  );
  _engine = new Engine(_store);

  _statusBar = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100,
  );
  _statusBar.command = "wam.openEditor";
  context.subscriptions.push(_statusBar);
  updateStatusBar();
  _statusBar.show();

  _sidebarProvider = new WamViewProvider();
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("wam.panel", _sidebarProvider),
  );

  const cmds = [
    ["wam.openEditor", () => openEditorPanel()],
    [
      "wam.status",
      async () => {
        const stats = _store.getStats();
        const h = _store.activeEmail
          ? _store.getHealth(_store.activeEmail)
          : null;
        const lines = [
          "WAM v" + VERSION,
          "current: " + (_store.activeEmail || "-"),
          "token:   " + (_store.activeTokenShort || "-"),
          "path:    " + (_store.lastInjectPath || "-"),
          "accounts:" +
            stats.pwCount +
            " · 可用" +
            stats.available +
            " · 切" +
            stats.switches,
          h && h.checked
            ? "quota:   D" +
              Math.round(h.daily) +
              "% W" +
              Math.round(h.weekly) +
              "% " +
              (h.plan || "")
            : "quota:   (未验)",
          "auto:    " +
            (_cfg("autoRotate", true) ? "on" : "off") +
            " · 阈值=" +
            _cfg("autoSwitchThreshold", 5) +
            "%",
          "source:  " + (_store.accountsSource || "-"),
        ];
        const c = await vscode.window.showInformationMessage(
          lines.join(" | "),
          "Open Log",
          "Open Panel",
        );
        if (c === "Open Log") _output.show();
        else if (c === "Open Panel")
          vscode.commands.executeCommand("wam.panel.focus");
      },
    ],
    [
      "wam.switchAccount",
      async () => {
        if (_store.accounts.length === 0) {
          vscode.window.showWarningMessage(
            "WAM: 无账号 (从 " + (_store.accountsSource || "?") + ")",
          );
          return;
        }
        const items = _store.accounts.map((a, i) => {
          const h = _store.getHealth(a.email);
          const banned = _store.isBanned(a.email);
          return {
            label: (i === _store.activeIdx ? "$(check) " : "  ") + a.email,
            description: banned
              ? "✗ 黑名单"
              : h.checked
                ? "D" +
                  Math.round(h.daily) +
                  "% W" +
                  Math.round(h.weekly) +
                  "% " +
                  (h.plan || "")
                : "未验",
            idx: i,
          };
        });
        const pick = await vscode.window.showQuickPick(items, {
          placeHolder: "选择账号 · 当前: " + (_store.activeEmail || "无"),
          matchOnDescription: true,
        });
        if (!pick || pick.idx === _store.activeIdx) return;
        _engine.rotating = true;
        _broadcastUI();
        try {
          const r = await loginAccount(_store, pick.idx);
          if (r.ok) _notify("info", "WAM: ✓ " + _store.activeEmail);
          else _notify("error", "WAM: ✗ " + r.stage + ": " + r.error);
        } finally {
          _engine.rotating = false;
          _broadcastUI();
        }
      },
    ],
    ["wam.panicSwitch", () => _engine.rotateNext()],
    [
      "wam.refreshAll",
      async () => {
        if (_verifyAllInProgress) {
          _notify("warn", "WAM: 验证已在运行");
          return;
        }
        _notify("info", "WAM: 开始验证 stale 账号·仅未验+老快照");
        const r = await verifyAllAccounts({ onlyStale: true });
        if (r.ok)
          _notify(
            "info",
            "WAM refreshAll: " +
              r.ok +
              " ✓ / " +
              r.fail +
              " ✗ · " +
              r.durSec +
              "s",
          );
      },
    ],
    [
      "wam.addAccount",
      async () => {
        const text = await vscode.window.showInputBox({
          prompt: "输入新账号 (邮箱 密码)·支持空格/Tab/----/|分隔",
          placeHolder: "foo@bar.com mypassword",
        });
        if (!text) return;
        const r = _store.addBatch(text);
        _notify("info", "WAM: 添加 " + r.added + " 个 · 跳重 " + r.duplicate);
        _store.reloadAccounts();
        _broadcastUI();
      },
    ],
    [
      "wam.injectToken",
      async () => {
        const t = await vscode.window.showInputBox({
          prompt: "输入 sessionToken (devin-session-token$...)",
          password: true,
        });
        if (!t) return;
        const inj = await injectToken(t);
        if (inj.ok) {
          _notify("info", "WAM: 注入 ✓ 路" + inj.path);
          _store.lastInjectPath = inj.path;
          _store.save();
          _broadcastUI();
        } else _notify("error", "WAM: 注入 ✗ 路" + inj.path + ": " + inj.note);
      },
    ],
    [
      "wam.verifyAll",
      async () => {
        if (_verifyAllInProgress) {
          _notify("warn", "WAM: 验证已在运行");
          return;
        }
        _notify(
          "info",
          "WAM: 全量验证 " +
            _store.accounts.length +
            " 个号 · 并行 " +
            (_cfg("verify.parallel", 3) | 0 || 3) +
            " · 预计 " +
            Math.ceil(_store.accounts.length / 3) * 3 +
            "s",
        );
        const r = await verifyAllAccounts({ onlyStale: false });
        if (r.ok) {
          // 验后统计过期号 (仅提示·不自动删)
          let expired = 0;
          for (const a of _store.accounts) {
            const h = _store.getHealth(a.email);
            if (h.checked && h.daysLeft === 0 && h.planEnd > 0) expired++;
          }
          _notify(
            "info",
            "WAM verifyAll: " +
              r.ok +
              " ✓ / " +
              r.fail +
              " ✗ · " +
              r.durSec +
              "s" +
              (expired > 0 ? " · " + expired + " 过期" : ""),
          );
        }
      },
    ],
    [
      "wam.scanExpiry",
      async () => {
        let warn = [];
        for (const a of _store.accounts) {
          const h = _store.getHealth(a.email);
          if (h.daysLeft > 0 && h.daysLeft <= 3)
            warn.push(a.email + " " + h.daysLeft + "天");
        }
        _notify(
          "info",
          "WAM 有效期: 危急 " +
            warn.length +
            " 个 · " +
            warn.slice(0, 3).join(" / ") +
            (warn.length > 3 ? " ..." : ""),
        );
      },
    ],
    ["wam.healthCheck", () => _engine.healthCheck()],
    [
      "wam.clearBlacklist",
      () => {
        const n = _store.clearBlacklist();
        _notify("info", "WAM: 清空黑名单 (" + n + " 个)");
        _broadcastUI();
      },
    ],
    [
      "wam.toggleAutoRotate",
      async () => {
        const cur = _cfg("autoRotate", true);
        await vscode.workspace
          .getConfiguration("wam")
          .update("autoRotate", !cur, vscode.ConfigurationTarget.Global);
        _notify("info", "WAM auto-rotate: " + (!cur ? "on" : "off"));
        _broadcastUI();
      },
    ],
    ["wam.show", () => _output.show()],
    [
      "wam.selfTest",
      async () => {
        log("=== selfTest ===");
        const r = {
          version: VERSION,
          accounts: _store.accounts.length,
          source: _store.accountsSource,
          active: _store.activeEmail,
          token: _store.activeTokenShort,
          path: _store.lastInjectPath,
          autoRotate: _cfg("autoRotate", true),
          threshold: _cfg("autoSwitchThreshold", 5),
          scanIntervalMs: _cfg("scanIntervalMs", 60000),
          invisible: _cfg("invisible", false),
          notifyLevel: _cfg("notifyLevel", "notify"),
          blacklistSize: Object.keys(_store.blacklist).length,
          switches: _store.switches,
          changesDetected: _store.changesDetected,
        };
        log(JSON.stringify(r, null, 2));
        _output.show();
        _notify("info", "WAM selfTest 完成 · 见 Output");
      },
    ],
    [
      "wam.setModeWam",
      async () => {
        if (_wamMode === "wam") {
          _notify("info", "WAM: 已是 WAM 模式");
          return;
        }
        _wamMode = "wam";
        if (_engine) _engine.startMonitor();
        if (context.globalState) context.globalState.update("wam.mode", "wam");
        _notify("info", "WAM: 切 WAM 切号模式 · 引擎启");
        _broadcastUI();
      },
    ],
    [
      "wam.setModeOfficial",
      async () => {
        if (_wamMode === "official") {
          _notify("info", "WAM: 已是官方登录模式");
          return;
        }
        _wamMode = "official";
        if (_engine) _engine.stopMonitor();
        if (context.globalState)
          context.globalState.update("wam.mode", "official");
        _notify("info", "WAM: 切官方登录模式 · 引擎停 · 用户可用官方登录");
        _broadcastUI();
      },
    ],
    [
      "wam.testDevinSwitch",
      async () => {
        if (_store.accounts.length === 0) {
          _notify("warn", "无账号");
          return;
        }
        const idx = _store.activeIdx >= 0 ? _store.activeIdx : 0;
        const a = _store.accounts[idx];
        _notify("info", "WAM: 测试 Devin 链路 · " + a.email.split("@")[0]);
        const dl = await devinLogin(a.email, a.password);
        if (!dl.ok) {
          _notify("error", "Devin login ✗ " + dl.error);
          return;
        }
        const pa = await windsurfPostAuth(dl.auth1);
        if (!pa.ok) {
          _notify("error", "postAuth ✗ " + pa.error);
          return;
        }
        _notify(
          "info",
          "WAM Devin 链路 ✓ sessionToken=" +
            pa.sessionToken.substring(0, 30) +
            "...",
        );
        log(
          "testDevinSwitch ✓ " +
            a.email +
            " " +
            pa.sessionToken.substring(0, 30) +
            "...",
        );
      },
    ],
  ];
  for (const [name, fn] of cmds) {
    context.subscriptions.push(vscode.commands.registerCommand(name, fn));
  }

  // ── wamMode 加载 (持久化) · 默认 wam ──
  try {
    const savedMode =
      (context.globalState && context.globalState.get("wam.mode")) || "wam";
    _wamMode = savedMode === "official" ? "official" : "wam";
    log("wamMode: " + _wamMode + " (loaded)");
  } catch {}

  if (_store.accounts.length > 0 && _wamMode === "wam") {
    const delay = Math.max(1000, _cfg("startupDelayMs", 3500) | 0);
    log("scheduling first rotate in " + delay + "ms");
    const t = setTimeout(async () => {
      try {
        // v2.1 启动恢复: 如有持久化活跃号 → 尝试复用而非新轮转
        if (_store.activeIdx >= 0 && _store.accounts[_store.activeIdx]) {
          const acc = _store.accounts[_store.activeIdx];
          const ah = _store.getHealth(acc.email);
          if (ah.checked && Math.min(ah.daily, ah.weekly) >= 5) {
            log(
              "startup: 尝试恢复 " +
                acc.email.substring(0, 20) +
                " (D" +
                Math.round(ah.daily) +
                "% W" +
                Math.round(ah.weekly) +
                "%)",
            );
            const r = await loginAccount(_store, _store.activeIdx);
            if (r.ok) {
              log("startup: 恢复 ✓ 路" + r.path);
              _broadcastUI();
              return; // 跳过 rotateNext
            }
            log("startup: 恢复失败 → rotateNext");
          }
        }
        await _engine.rotateNext({ tryPending: true });
      } catch (e) {
        log("first rotate err: " + (e.stack || e.message || e));
      }
    }, delay);
    context.subscriptions.push({ dispose: () => clearTimeout(t) });

    // ── 内化原 "refresh" 按钮: 启动后自动 verifyAll(stale) ──
    // 太上不知有之 · 用户启动后看到所有号自动验完 · 不需手动点
    // v2.1.1: 首次使用 (>50% 未验) → 10s 即开始验证 · 用户更快看到额度
    const uncheckedPct =
      _store.accounts.filter((a) => !_store.getHealth(a.email).checked).length /
      Math.max(1, _store.accounts.length);
    const baseVerifyDelay = _cfg("autoVerifyOnStartupMs", 30000) | 0;
    const verifyDelay = Math.max(
      5000,
      uncheckedPct > 0.5 ? Math.min(baseVerifyDelay, 10000) : baseVerifyDelay,
    );
    if (verifyDelay > 0) {
      log(
        "scheduling auto verify(stale) in " +
          verifyDelay +
          "ms" +
          (uncheckedPct > 0.5
            ? " (首次加速 · " + Math.round(uncheckedPct * 100) + "% 未验)"
            : ""),
      );
      const tv = setTimeout(() => {
        if (_wamMode !== "wam") return;
        if (_verifyAllInProgress) return;
        log("auto-verify(stale): 启动 · 内化 refresh 按钮");
        verifyAllAccounts({ onlyStale: true }).catch((e) =>
          log("auto-verify err: " + (e.message || e)),
        );
      }, verifyDelay);
      context.subscriptions.push({ dispose: () => clearTimeout(tv) });
    }

    // ── 内化原 "verify" 按钮: 周期重验 (每 N 分钟) · 默认 30min ──
    const periodicVerifyMs = Math.max(
      0,
      _cfg("autoVerifyPeriodMs", 30 * 60 * 1000) | 0,
    );
    if (periodicVerifyMs > 0) {
      log("scheduling periodic verify(stale) every " + periodicVerifyMs + "ms");
      const ti = setInterval(() => {
        if (_wamMode !== "wam") return;
        if (_verifyAllInProgress) return;
        log("auto-verify(stale): 周期触发");
        verifyAllAccounts({ onlyStale: true }).catch((e) =>
          log("periodic-verify err: " + (e.message || e)),
        );
      }, periodicVerifyMs);
      context.subscriptions.push({ dispose: () => clearInterval(ti) });
    }
  } else if (_store.accounts.length === 0) {
    vscode.window.showWarningMessage(
      "WAM-min: 无账号 · 配 wam.accountsFile 或确保账号库文件存在",
    );
  } else if (_wamMode === "official") {
    log("activate: 官方登录模式 · 跳过启动切号 + 引擎不启");
  }

  if (_wamMode === "wam") {
    _engine.startMonitor();
    context.subscriptions.push({ dispose: () => _engine.stopMonitor() });

    // ── 文档变化追踪 + Rate-limit 拦截器 (对齐本源 v17.42.5 / v17.42.20) ──
    // 双重职责:
    //   1. 所有文档变化 → 更新 _lastDocChangeAt → 供 _isCascadeBusy 流式避让
    //   2. rate-limit 关键字 → 主动无感切号 (不言之教 · 无为之益)
    try {
      const _docDisp = vscode.workspace.onDidChangeTextDocument((e) => {
        // 职责1: 追踪文档变化 (流式检测)
        _lastDocChangeAt = Date.now();
        // 职责2: rate-limit 拦截 (异步 · 不阻塞编辑器)
        if (_wamMode !== "wam" || _switching || !_store || _store.activeIdx < 0)
          return;
        if (!e.contentChanges.length) return;
        const lastChange = e.contentChanges[e.contentChanges.length - 1];
        if (!lastChange) return;
        const t = lastChange.text;
        if (!t || t.length < 20 || t.length > 500) return;
        if (!/rate.?limit.?exceeded|Rate limit error/i.test(t)) return;
        const cooldown =
          Date.now() - _lastSwitchTime < _cfg("switchCooldownMs", 15000);
        const injCd = Date.now() - _lastInjectFail < 30000;
        if (cooldown || injCd || !_cfg("autoRotate", true)) return;
        log("\uD83D\uDEA8 rate-limit intercepted! Proactive switch...");
        (async () => {
          let bestI = _isValidAutoTarget(_predictiveCandidate)
            ? _predictiveCandidate
            : _store.getBestIndex(_store.activeIdx);
          if (bestI < 0) {
            log("rate-limit: no available account");
            return;
          }
          // 流式避让: 让当前对话完成再切
          await _waitIfCascadeBusy(15000);
          _switching = true;
          _switchingStartTime = Date.now();
          _engine.rotating = true;
          _broadcastUI();
          try {
            const sr = await loginAccount(_store, bestI);
            if (sr.ok) {
              _lastSwitchTime = Date.now();
              _predictiveCandidate = _store.getBestIndex(bestI);
              _notify(
                "verbose",
                "WAM: \uD83D\uDEA8 Rate-limit \u2192 " +
                  (_store.activeEmail || "?"),
              );
            } else {
              _lastInjectFail = Date.now();
            }
          } finally {
            _switching = false;
            _engine.rotating = false;
            _broadcastUI();
          }
        })();
      });
      context.subscriptions.push(_docDisp);
      log("doc-tracker + rate-limit interceptor registered");
    } catch (e) {
      log("doc-tracker/rate-limit setup failed: " + (e.message || e));
    }

    // ── 活跃号 token 守护线程 (对齐本源 v17.42.5 _startActiveTokenGuardian) ──
    // 太上不知有之: 每 20min 静默验证活跃 token · 失效则自愈 (重新登录当前号)
    // 用户对话永不因 token 过期而卡顿 · 近零开销
    const _guardianMs = 20 * 60 * 1000;
    const _guardDelay = 25000; // 延迟 25s 启动 (避免与启动切号 / verify 叠加)
    const _guardTimer = setTimeout(() => {
      const _gInterval = setInterval(async () => {
        if (_wamMode !== "wam" || _switching || !_store) return;
        if (!_store.activeEmail || !_store.activeApiKey) return;
        try {
          const q = await tryFetchPlanStatus(_store.activeApiKey);
          if (q) {
            _store.setHealth(_store.activeEmail, q);
            _broadcastUI();
            return; // token 有效 · 无事
          }
          // token 无效 → 自愈: 重新登录当前号
          log(
            "🛡️ guardian: token invalid → re-login " +
              _store.activeEmail.substring(0, 20),
          );
          if (_store.activeIdx >= 0) {
            const r = await loginAccount(_store, _store.activeIdx);
            if (r.ok) {
              log("🛡️ guardian: re-login ✓ 路" + r.path);
              _broadcastUI();
            } else {
              log("🛡️ guardian: re-login ✗ → rotateNext");
              await _engine.rotateNext();
            }
          }
        } catch (e) {
          log("guardian: " + (e.message || e));
        }
      }, _guardianMs);
      context.subscriptions.push({ dispose: () => clearInterval(_gInterval) });
      log("active-token guardian started (20min cycle · 25s delay)");
    }, _guardDelay);
    context.subscriptions.push({ dispose: () => clearTimeout(_guardTimer) });
  }

  log(
    "WAM v" +
      VERSION +
      " activated · 道法自然 · 去芜存菁 · 用户无为·插件无不为",
  );
}

function deactivate() {
  if (_engine) _engine.stopMonitor();
  if (_store) _store.save();
  log("WAM deactivate");
}

module.exports = {
  activate,
  deactivate,
  // 暴露给 harness · 用于真打验证 (生产代码不依赖)
  _internals: {
    devinLogin,
    windsurfPostAuth,
    tryFetchPlanStatus,
    _parsePlanStatusJson,
    verifyOneAccount,
    verifyAllAccounts,
    injectViaBing,
    _isValidAutoTarget,
    isClaudeAvailable,
    isWeeklyDrought,
    buildHtml,
    openEditorPanel,
    parseAccountText,
    Store,
    get _store() {
      return _store;
    },
    get _predictiveCandidate() {
      return _predictiveCandidate;
    },
    set _predictiveCandidate(v) {
      _predictiveCandidate = v;
    },
  },
};
