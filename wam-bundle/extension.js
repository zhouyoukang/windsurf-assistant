// WAM v10.0 — 道法自然: 多源竞速·官方直连·缓存降级·系统DNS·冷启动修复
// 载营魄抱一，能无离乎？专气致柔，能如婴儿乎？
// 五感原则: 切号绝不调用windsurf.logout, 绝不重启extension host, 绝不写state.vscdb
const vscode = require("vscode");
const crypto = require("crypto");
const https = require("https");
const http = require("http");
const net = require("net");
const tls = require("tls");
const fs = require("fs");
const path = require("path");
const os = require("os");
const dns = require("dns");

// ── 配置 ──
const FIREBASE_KEYS = [
  "AIzaSyDsOl-1XpT5err0Tcnx8FFod1H8gVGIycY",
  "AIzaSyDKm6GGxMJfCbNf-k0kPytiGLaqFJpeSac",
];
const FIREBASE_HOST = "identitytoolkit.googleapis.com";
const PROXY_HOST = "127.0.0.1";
const PROXY_PORTS = [7890, 7897, 7891, 10808, 1080];
const WAM_DIR = path.join(os.homedir(), ".wam-hot");
const TOKEN_FILE = path.join(WAM_DIR, "oneshot_token.json");
const RESULT_FILE = path.join(WAM_DIR, "inject_result.json");
const LOG_FILE = path.join(WAM_DIR, "wam.log");
const SNAPSHOT_FILE = path.join(WAM_DIR, "quota_snapshots.json");
const INUSE_FILE = path.join(WAM_DIR, "inuse_marks.json");
// TRIAL_MAX_DAYS已移除 — 官方Trial是14天(非90天), 且过期后仍有配额, 不再用时间猜测过期
const PURGE_INTERVAL_MS = 6 * 3600 * 1000; // 每6小时自动检查一次

let _store = null;
let _sidebarProvider = null;
let _editorPanel = null;
let _statusBarItem = null;
let _watcher = null;
let _switching = false;
let _switchingStartTime = 0; // v7.3: 切号锁开始时间, 用于超时释放+手动抢占
let _pollTimer = null;
let _purgeRunning = false;
let _lastPurgeTime = 0;
let _mode = "wam"; // 'wam' = 切号模式 | 'official' = 官方登录模式
const MODE_FILE = path.join(WAM_DIR, "wam_mode.json");

// ── 额度查询 ──
const RELAY_HOST = "168666okfa.xyz";
// v10: 官方API端点 — 直连Windsurf/Codeium, 不经中继, 根治429
const OFFICIAL_PLAN_STATUS_URLS = [
  "https://server.codeium.com/exa.seat_management_pb.SeatManagementService/GetPlanStatus",
  "https://web-backend.windsurf.com/exa.seat_management_pb.SeatManagementService/GetPlanStatus",
  "https://server.codeium.com/exa.api_server_pb.ApiServerService/GetPlanStatus",
];
// v10: 全局请求计数器 — 跨实例文件锁协调
const GLOBAL_RATE_FILE = path.join(WAM_DIR, "global_rate.json");
const GLOBAL_RATE_WINDOW = 60000; // 60秒窗口
const GLOBAL_RATE_MAX = 30; // 窗口内最大请求数
const MONITOR_FAST_MS = 3000; // 活跃账号监测: 3秒 (锚定: 尽快捕捉发消息后的额度波动)
const SCAN_SLOW_MS = 45000; // 全量后台扫描: 45秒
const SCAN_BATCH_SIZE = 10; // 每轮后台扫描账号数 (加大覆盖面)
const CHANGE_THRESHOLD = 0.01; // 额度变化检测阈值: 任意变动即标记 (近零阈值, 仅过滤浮点噪声)
const TOKEN_CACHE_TTL = 50 * 60000; // idToken缓存50分钟
const INUSE_COOLDOWN_MS = 120000; // 使用中标记冷却: 120秒无新波动才清除 (锚定: 快标记·慢清除·防误判)
const BURST_MS = 1500; // 突发模式: 1.5秒一轮 (锚定: 用户连续发消息时极速追踪)
const BURST_DURATION = 60000; // 突发模式持续60秒 (锚定: 覆盖用户一轮对话周期)
const AUTO_SWITCH_THRESHOLD = 5; // 自动切号阈值: min(D,W) < 5% 才触发切号
const PREDICTIVE_THRESHOLD = 25; // 预判切号阈值: < 25% 时预选候选账号
const DAILY_RESET_HOUR_UTC = 8; // 官方Daily重置时间 = 4:00 PM GMT+8 = 8:00 UTC
const WEEKLY_RESET_DAY = 0; // 官方Weekly重置日 = Sunday (JS: 0=Sun, 6=Sat) — 诊断实证: field 18指向Sunday
const WAIT_RESET_HOURS = 3; // 如果Daily将在此时间内重置，且Weekly充足，则等待重置而非切号
const INSTANCE_LOCK_FILE = path.join(WAM_DIR, "instance_claims.json");
const INSTANCE_HEARTBEAT_MS = 30000; // 实例心跳: 30秒
const INSTANCE_DEAD_MS = 60000; // 实例死亡判定: 60秒无心跳

let _quotaSnapshots = new Map(); // email -> {daily, weekly, ts}
let _tokenCache = new Map(); // email -> {idToken, expiresAt}
let _monitorTimer = null;
let _scanTimer = null;
let _scanRunning = false;
let _scanOffset = 0;
let _monitorActive = false; // 正在执行监测
let _totalMonitorCycles = 0;
let _lastMonitorSaveTs = 0; // 监测循环save节流时间戳
let _totalChangesDetected = 0;
let _burstUntil = 0; // 突发模式截止时间戳
let _consecutiveChanges = 0; // 连续变动计数 (锚定强度)
let _lastSwitchTime = 0; // 上次切号时间戳
let _lastSelfActivity = 0; // 上次本实例活动时间 (编辑器/终端/对话)
let _instanceId = crypto.randomBytes(4).toString("hex"); // 本实例唯一ID
let _heartbeatTimer = null;
let _predictiveCandidate = -1; // 预判候选账号索引 (-1=无)
let _prewarmedToken = null; // v8: 预热Token缓存 {email, idToken, ts} — 道法自然: 切号前已备好弹药
let _rateLimitWatcher = null; // v8: Rate-limit错误拦截器
let _droughtCache = { value: false, ts: 0 }; // Weekly干旱缓存 (10秒TTL)

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}\n`;
  try {
    fs.mkdirSync(WAM_DIR, { recursive: true });
  } catch {}
  try {
    fs.appendFileSync(LOG_FILE, line);
  } catch {}
  console.log("WAM:", msg);
}

// ── 持久化引擎 — 快照/使用中标记 落盘 (反者道之动: 不信内存, 只信磁盘) ──
let _snapshotDirty = false;
let _inUseDirty = false;
let _persistTimer = null;

function _saveSnapshots() {
  try {
    const obj = {};
    for (const [k, v] of _quotaSnapshots) obj[k] = v;
    fs.writeFileSync(SNAPSHOT_FILE, JSON.stringify(obj), "utf8");
  } catch (e) {
    log(`snapshot save err: ${e.message}`);
  }
  _snapshotDirty = false;
}

function _loadSnapshots() {
  try {
    if (fs.existsSync(SNAPSHOT_FILE)) {
      const data = JSON.parse(fs.readFileSync(SNAPSHOT_FILE, "utf8"));
      let loaded = 0;
      for (const [k, v] of Object.entries(data)) {
        if (v && typeof v.daily === "number" && typeof v.weekly === "number") {
          const existing = _quotaSnapshots.get(k);
          if (!existing || !existing.ts || (v.ts && v.ts > existing.ts)) {
            _quotaSnapshots.set(k, v);
            loaded++;
          }
        }
      }
      if (loaded > 0)
        log(
          `snapshots: merged ${loaded} from disk (total=${_quotaSnapshots.size})`,
        );
    }
  } catch (e) {
    log(`snapshot load err: ${e.message}`);
  }
}

function _saveInUse(store) {
  try {
    const obj = {};
    for (const [k, v] of store._inUse) obj[k] = v;
    fs.writeFileSync(INUSE_FILE, JSON.stringify(obj), "utf8");
  } catch (e) {
    log(`inUse save err: ${e.message}`);
  }
  _inUseDirty = false;
}

function _loadInUse(store) {
  try {
    if (fs.existsSync(INUSE_FILE)) {
      const data = JSON.parse(fs.readFileSync(INUSE_FILE, "utf8"));
      const now = Date.now();
      let loaded = 0;
      for (const [k, v] of Object.entries(data)) {
        if (v && v.lastChange && now - v.lastChange < INUSE_COOLDOWN_MS) {
          const existing = store._inUse.get(k);
          // 只合并更新的标记 (不覆盖本实例更新鲜的数据)
          if (!existing || v.lastChange > existing.lastChange) {
            store._inUse.set(k, v);
            loaded++;
          }
        }
      }
      if (loaded > 0)
        log(
          `inUse: merged ${loaded} marks from disk (total=${store._inUse.size})`,
        );
    }
  } catch (e) {
    log(`inUse load err: ${e.message}`);
  }
}

function _schedulePersist() {
  if (_persistTimer) return;
  _persistTimer = setTimeout(() => {
    _persistTimer = null;
    if (_snapshotDirty) _saveSnapshots();
    if (_inUseDirty && _store) _saveInUse(_store);
  }, 2000);
}

// ── 重置时间计算引擎 (锚定官方机制) ──
// 官方: Daily resets at 4:00 PM GMT+8 = 8:00 UTC every day
// 官方: Weekly resets at 4:00 PM GMT+8 on Sunday (诊断实证: API field 18 = Sunday 08:00 UTC)
function getNextDailyResetMs() {
  const now = new Date();
  const todayReset = new Date(
    Date.UTC(
      now.getUTCFullYear(),
      now.getUTCMonth(),
      now.getUTCDate(),
      DAILY_RESET_HOUR_UTC,
      0,
      0,
    ),
  );
  return todayReset.getTime() > now.getTime()
    ? todayReset.getTime()
    : todayReset.getTime() + 86400000;
}

function getNextWeeklyResetMs() {
  const now = new Date();
  let d = new Date(
    Date.UTC(
      now.getUTCFullYear(),
      now.getUTCMonth(),
      now.getUTCDate(),
      DAILY_RESET_HOUR_UTC,
      0,
      0,
    ),
  );
  // 找到下一个Sunday 4PM UTC+8 (诊断实证: Windsurf weekly reset = Sunday)
  while (d.getUTCDay() !== WEEKLY_RESET_DAY || d.getTime() <= now.getTime()) {
    d = new Date(d.getTime() + 86400000);
  }
  return d.getTime();
}

function hoursUntilDailyReset() {
  return Math.max(0, (getNextDailyResetMs() - Date.now()) / 3600000);
}

function hoursUntilWeeklyReset() {
  return Math.max(0, (getNextWeeklyResetMs() - Date.now()) / 3600000);
}

// ── Weekly干旱检测 ──
// 当>=80%已验证账号Weekly<=阈值时，整个池子进入干旱模式
// 干旱模式下: 不因W0触发切号，只看Daily，避免无效切号死循环
function isWeeklyDrought() {
  const now = Date.now();
  if (now - _droughtCache.ts < 10000) return _droughtCache.value;
  if (!_store) {
    _droughtCache = { value: false, ts: now };
    return false;
  }
  let checked = 0,
    wDry = 0;
  for (const a of _store.accounts) {
    if (!a.password) continue; // 干旱检测仅计有密码可登录的账号
    const h = _store.getHealth(a);
    if (!h.checked) continue;
    checked++;
    if (h.weekly <= AUTO_SWITCH_THRESHOLD) wDry++;
  }
  const result = checked > 0 && wDry / checked >= 0.8;
  _droughtCache = { value: result, ts: now };
  if (result)
    log(
      `🏜️ Weekly干旱: ${wDry}/${checked}号W耗尽(${Math.round((wDry / checked) * 100)}%), 周重置${hoursUntilWeeklyReset().toFixed(1)}h后`,
    );
  return result;
}

// ── Claude模型可用性判定 — 真正锚定底层 ──
// 道法自然: planEnd过期 ≠ 不可用! Windsurf有宽限期, 实际以D/W配额为准
// Free plan(D0/W0) → 唯一死刑 | 有配额(D>0或W>0) → 可用
function isTrialPlan(plan) {
  const p = (plan || "").toLowerCase();
  return !["pro", "enterprise", "team", "individual"].includes(p);
}

function isClaudeAvailable(health) {
  const plan = (health.plan || "").toLowerCase();
  // Free plan + 无配额: 唯一确定的死号
  if (
    plan === "free" &&
    (health.daily || 0) === 0 &&
    (health.weekly || 0) === 0
  )
    return false;
  // 付费计划: Claude始终可用
  if (["pro", "enterprise", "team", "individual"].includes(plan)) return true;
  // 有实际配额(D>0或W>0) → 可用(无论planEnd是否过期)
  if ((health.daily || 0) > 0 || (health.weekly || 0) > 0) return true;
  // 未检测账号: 不确定, 给予机会
  if (!health.checked) return true;
  // 兜底: 没有足够信息判定不可用时, 保留
  return true;
}

// 判断账号是否"有效可切" — Claude可用性 · 干旱感知 · 重置时间感知
// 反者道之动: D/W配额是表象, Claude可用性是本质
function isAccountSwitchable(health) {
  // Claude不可用(Free/试用过期) → 不可切
  if (!isClaudeAvailable(health)) return false;
  const eff = Math.min(health.daily, health.weekly);
  if (eff > AUTO_SWITCH_THRESHOLD) return true;
  // Weekly干旱模式: Daily充足即可用 (W0是全局问题，切号无法解决)
  if (isWeeklyDrought() && health.daily > AUTO_SWITCH_THRESHOLD) return true;
  // Daily耗尽但即将重置 + Weekly充足 → 仍可用(等重置)
  if (
    health.daily <= AUTO_SWITCH_THRESHOLD &&
    health.weekly > AUTO_SWITCH_THRESHOLD
  ) {
    if (hoursUntilDailyReset() <= WAIT_RESET_HOURS) return true;
  }
  // Daily耗尽但即将重置 + 干旱模式 → 等重置
  if (
    isWeeklyDrought() &&
    health.daily <= AUTO_SWITCH_THRESHOLD &&
    hoursUntilDailyReset() <= WAIT_RESET_HOURS
  )
    return true;
  return false;
}

// ── 模式管理 (WAM切号 / 官方登录) ──
function loadMode() {
  try {
    if (fs.existsSync(MODE_FILE)) {
      const data = JSON.parse(fs.readFileSync(MODE_FILE, "utf8"));
      if (data.mode === "official" || data.mode === "wam") _mode = data.mode;
    }
  } catch {}
}

function saveMode(mode) {
  _mode = mode;
  try {
    fs.mkdirSync(WAM_DIR, { recursive: true });
    fs.writeFileSync(MODE_FILE, JSON.stringify({ mode, ts: Date.now() }));
  } catch {}
  log(`mode → ${mode}`);
}

function isWamMode() {
  return _mode === "wam";
}

// ── 官方模式: 彻底隔离第三方套层, 回归本源 ──
// v7.4: 万法归宗 — 真正的零干扰隔离
//   1. windsurf.logout 登出WAM注入的会话
//   2. 停止所有引擎+心跳+文件监听
//   3. 清除activeIndex/instance claim
//   4. 清除内存+磁盘状态
//   5. 清除代理环境变量
async function cleanupThirdPartyState() {
  const appdata = process.env.APPDATA || "";
  const cleanFiles = [
    path.join(appdata, "Windsurf", "_fp_salt.txt"),
    path.join(appdata, "Windsurf", "_pool_apikey.txt"),
    path.join(WAM_DIR, "oneshot_token.json"),
    path.join(WAM_DIR, "inject_result.json"),
  ];
  let cleaned = 0;
  for (const f of cleanFiles) {
    try {
      if (fs.existsSync(f)) {
        fs.unlinkSync(f);
        cleaned++;
        log(`cleanup: deleted ${path.basename(f)}`);
      }
    } catch (e) {
      log(`cleanup: failed ${path.basename(f)}: ${e.message}`);
    }
  }
  // v7.4: 登出WAM注入的会话 — 回归本源, 让用户用自己的账号
  try {
    log("cleanup: windsurf.logout — 登出WAM会话");
    await Promise.race([
      vscode.commands.executeCommand("windsurf.logout"),
      new Promise((r) => setTimeout(r, 8000)),
    ]);
    cleaned++;
    log("cleanup: logout OK");
  } catch (e) {
    log(`cleanup: logout skipped: ${e.message}`);
  }
  // 停止所有引擎
  _stopEngines();
  if (_pollTimer) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
  // v7.4: 停止心跳定时器
  if (_heartbeatTimer) {
    clearInterval(_heartbeatTimer);
    _heartbeatTimer = null;
    log("cleanup: heartbeat stopped");
  }
  // v7.4: 停止文件监听
  if (_watcher) {
    _watcher.close();
    _watcher = null;
    log("cleanup: watcher stopped");
  }
  // v7.4: 清除activeIndex + instance claim
  if (_store) {
    _store.activeIndex = -1;
    log("cleanup: activeIndex cleared");
  }
  try {
    const claims = _readInstanceClaims();
    delete claims[_instanceId];
    fs.writeFileSync(
      INSTANCE_LOCK_FILE,
      JSON.stringify(claims, null, 2),
      "utf8",
    );
    log("cleanup: instance claim cleared");
  } catch {}
  // 清除active account marker
  try {
    const markerPath = path.join(WAM_DIR, "_active_account.txt");
    if (fs.existsSync(markerPath)) {
      fs.unlinkSync(markerPath);
      cleaned++;
    }
  } catch {}
  // 清除内存状态并落盘 (防止重启后恢复旧数据)
  _quotaSnapshots.clear();
  _tokenCache.clear();
  if (_store) _store._inUse.clear();
  try {
    _saveSnapshots();
  } catch {}
  try {
    if (_store) _saveInUse(_store);
  } catch {}
  _burstUntil = 0;
  _consecutiveChanges = 0;
  _predictiveCandidate = -1;
  _prewarmedToken = null; // v8: 清除预热Token
  // 清除旧版本可能设置的代理环境变量污染
  // 注: 仅清除WAM设置的值(127.0.0.1:7890), 不动用户自己设的代理
  if (process.env.HTTP_PROXY === "http://127.0.0.1:7890") {
    delete process.env.HTTP_PROXY;
    cleaned++;
    log("cleanup: removed HTTP_PROXY");
  }
  if (process.env.HTTPS_PROXY === "http://127.0.0.1:7890") {
    delete process.env.HTTPS_PROXY;
    cleaned++;
    log("cleanup: removed HTTPS_PROXY");
  }
  log(
    `cleanup: ${cleaned} items cleaned, engines+heartbeat+watcher stopped, session logged out — 回归本源`,
  );
  return cleaned;
}

// v7.4: 回切WAM时重启所有后台服务 (watcher + heartbeat)
function _restartBackgroundServices() {
  if (!_watcher) startFileWatcher();
  if (!_heartbeatTimer) {
    _heartbeatTimer = setInterval(() => {
      if (!isWamMode()) return;
      const activeAcc =
        _store && _store.activeIndex >= 0
          ? _store.get(_store.activeIndex)
          : null;
      _writeInstanceClaim(activeAcc?.email || "");
      _cleanDeadInstances();
    }, INSTANCE_HEARTBEAT_MS);
  }
  log("services restarted: watcher + heartbeat");
}

// ============================================================
// AccountStore — 账号池CRUD + 使用中标记 + 批量操作
// ============================================================
class AccountStore {
  constructor(globalStoragePath) {
    this._dir = globalStoragePath;
    this._path = path.join(globalStoragePath, "windsurf-login-accounts.json");
    // 共享路径: 让pool_engine等外部工具也能读到
    this._sharedPath = path.join(
      globalStoragePath,
      "..",
      "windsurf-login-accounts.json",
    );
    this.accounts = [];
    this.switchCount = 0;
    this.activeIndex = -1;
    this.lastRefresh = 0;
    this._inUse = new Map(); // email -> {since, lastChange} 消息锚定: 单次波动即标记, 冷却后清除
    this.load();
  }

  load() {
    const candidates = [
      this._path,
      path.join(this._dir, "..", "windsurf-login-accounts.json"),
    ];
    // 黑名单: 读取归档池中的死号,防止从其他路径被重新合并
    const blacklist = new Set();
    try {
      const archPath = path.join(path.dirname(this._path), "_wam_purged.json");
      if (fs.existsSync(archPath)) {
        const arch = JSON.parse(fs.readFileSync(archPath, "utf8"));
        if (Array.isArray(arch))
          arch.forEach((a) => {
            if (a.email) blacklist.add(a.email.toLowerCase());
          });
      }
    } catch {}
    const seen = new Set();
    const merged = [];
    let sources = 0,
      blocked = 0;
    for (const p of candidates) {
      try {
        if (fs.existsSync(p)) {
          const data = JSON.parse(fs.readFileSync(p, "utf8"));
          if (Array.isArray(data)) {
            let added = 0;
            for (const a of data) {
              // 清洗: 去掉email末尾分隔符残留 (修复----解析bug遗留)
              if (a.email) a.email = a.email.replace(/[-=|:,\s]+$/, "").trim();
              const e = (a.email || "").toLowerCase();
              if (!a.password) continue; // 道法自然: 无密码不入池，根除phantom D50/W50幻影号
              if (blacklist.has(e)) {
                blocked++;
                continue;
              } // 黑名单: 已归档死号不再入池
              if (a.usage && a.usage.mode) delete a.usage.mode; // 清除旧系统mode=quota残留
              // Claude可用性门控: cached plan=free → 不入池 (反者道之动: D100/W100是假象)
              const cachedPlan = (
                (a.usage && a.usage.plan) ||
                ""
              ).toLowerCase();
              if (cachedPlan === "free") {
                blocked++;
                continue;
              }
              // 试用过期门控: 仅当D=0且W=0时才阻止(planEnd过期但有配额仍可用)
              const cachedPlanEnd = (a.usage && a.usage.planEnd) || 0;
              // v7.2: 兼容两种格式 — number(82) 或 object({remaining:82})
              const _rd = (f) =>
                f == null
                  ? -1
                  : typeof f === "number"
                    ? f
                    : f && f.remaining != null
                      ? f.remaining
                      : -1;
              const cachedD = a.usage ? _rd(a.usage.daily) : -1;
              const cachedW = a.usage ? _rd(a.usage.weekly) : -1;
              if (
                cachedPlanEnd > 0 &&
                Date.now() > cachedPlanEnd &&
                isTrialPlan(cachedPlan) &&
                cachedD === 0 &&
                cachedW === 0
              ) {
                blocked++;
                continue;
              }
              // v7.2: 格式迁移 — 统一 usage.daily/weekly 为 {remaining: N} 对象格式
              if (a.usage && typeof a.usage.daily === "number") {
                a.usage.daily = { remaining: a.usage.daily };
                a._migrated = true;
              }
              if (a.usage && typeof a.usage.weekly === "number") {
                a.usage.weekly = { remaining: a.usage.weekly };
                a._migrated = true;
              }
              if (e && !seen.has(e)) {
                seen.add(e);
                merged.push(a);
                added++;
              }
            }
            if (added > 0) sources++;
          }
        }
      } catch {}
    }
    this.accounts = merged.filter((a) => a && a.email);
    log(
      `store: loaded ${this.accounts.length} accounts (${this.pwCount()} with pw) from ${sources} sources${blocked > 0 ? ` (${blocked} blacklisted)` : ""}`,
    );
    // v7.2.1: 格式迁移后立即持久化，避免file watcher反复读旧格式
    if (this.accounts.some((a) => a.usage && a._migrated)) {
      this.accounts.forEach((a) => {
        if (a._migrated) delete a._migrated;
      });
      this.save();
      log("store: format migration persisted");
    }
  }

  save() {
    const json = JSON.stringify(this.accounts, null, 2);
    // 自动备份: 保存前先备份现有文件 (保留最近3个备份)
    this._autoBackup();
    try {
      fs.mkdirSync(path.dirname(this._path), { recursive: true });
      fs.writeFileSync(this._path, json, "utf8");
    } catch (e) {
      log(`store save error: ${e.message}`);
    }
    // 同步写入共享位置 (让pool_engine等外部工具也能读到)
    try {
      if (this._sharedPath) fs.writeFileSync(this._sharedPath, json, "utf8");
    } catch {}
  }

  _autoBackup() {
    try {
      if (!fs.existsSync(this._path)) return;
      const backupDir = path.join(path.dirname(this._path), "_wam_backups");
      fs.mkdirSync(backupDir, { recursive: true });
      const ts = Date.now();
      fs.copyFileSync(this._path, path.join(backupDir, `accounts_${ts}.json`));
      // 只保留最近3个备份
      const files = fs
        .readdirSync(backupDir)
        .filter((f) => f.startsWith("accounts_"))
        .sort();
      while (files.length > 3) {
        fs.unlinkSync(path.join(backupDir, files.shift()));
      }
    } catch (e) {
      log(`backup error: ${e.message}`);
    }
  }

  get(i) {
    return this.accounts[i] || null;
  }
  count() {
    return this.accounts.length;
  }
  pwCount() {
    return this.accounts.filter((a) => a.password).length;
  }

  add(email, password) {
    // 清洗: 去掉email末尾分隔符残留, 去掉password首尾空格
    email = email.replace(/[-=|:,\s]+$/, "").trim();
    password = (password || "").trim();
    if (!email || !email.includes("@") || !password) return false;
    if (
      this.accounts.some(
        (a) => (a.email || "").toLowerCase() === email.toLowerCase(),
      )
    )
      return false;
    this.accounts.push({
      email,
      password,
      loginCount: 0,
      addedAt: Date.now(),
      usage: null,
      _unverified: true, // Claude可用性未验证标记
    });
    this.save();
    // 异步验证Claude可用性 — 不阻塞add()返回，后台验证后自动清理
    this._asyncVerifyAccount(email, password);
    return true;
  }

  // 异步验证新入池账号的Claude可用性 (反者道之动: 不信表象, 只信API)
  async _asyncVerifyAccount(email, password) {
    try {
      log(`verify-gate: ${email} — 异步验证Claude可用性...`);
      const quota = await fetchAccountQuota(email, password);
      const idx = this.accounts.findIndex(
        (a) => (a.email || "").toLowerCase() === email.toLowerCase(),
      );
      if (idx < 0) return; // 已被其他流程移除
      if (quota.ok) {
        const plan = (quota.planName || "").toLowerCase();
        const planEnd = quota.planEndUnix ? quota.planEndUnix * 1000 : 0;
        const isExpired = planEnd > 0 && Date.now() > planEnd;
        // Free plan(D0/W0) 或 试用过期且D0/W0 → 拒绝; 有配额的保留
        if (
          (plan === "free" && quota.daily === 0 && quota.weekly === 0) ||
          (isExpired &&
            isTrialPlan(plan) &&
            quota.daily === 0 &&
            quota.weekly === 0)
        ) {
          const reason =
            plan === "free"
              ? `verify_gate_free: plan=free, D${quota.daily}W${quota.weekly}仅限免费模型, Claude不可用`
              : `verify_gate_expired: plan=${plan}已过期, Claude不可用`;
          log(`verify-gate: ${email} → 拒绝 (${reason})`);
          this._archiveRemoved([this.accounts[idx]], reason);
          this.accounts.splice(idx, 1);
          if (this.activeIndex === idx) this.activeIndex = -1;
          else if (this.activeIndex > idx) this.activeIndex--;
          this.save();
          vscode.window.showWarningMessage(
            `WAM: 已拒绝 ${email} — ${plan === "free" ? "Free计划无Claude" : "试用已过期"}`,
          );
          refreshAll();
          return;
        }
        // 验证通过 → 清除未验证标记
        delete this.accounts[idx]._unverified;
        this.accounts[idx]._verifiedPlan = plan;
        this.save();
        log(
          `verify-gate: ${email} → 通过 (plan=${plan}, D${quota.daily}W${quota.weekly})`,
        );
      } else {
        log(
          `verify-gate: ${email} → 探测失败: ${quota.error} (保留, 等待下次purge)`,
        );
        // 登录永久失败 → 立即清除
        if (/INVALID|NOT_FOUND|DISABLED|WRONG/.test(quota.error || "")) {
          log(`verify-gate: ${email} → 登录死号, 归档移除`);
          this._archiveRemoved(
            [this.accounts[idx]],
            `verify_gate_dead: ${quota.error}`,
          );
          this.accounts.splice(idx, 1);
          if (this.activeIndex === idx) this.activeIndex = -1;
          else if (this.activeIndex > idx) this.activeIndex--;
          this.save();
          vscode.window.showWarningMessage(
            `WAM: 已拒绝 ${email} — 登录失败(${quota.error})`,
          );
          refreshAll();
        }
      }
    } catch (e) {
      log(`verify-gate: ${email} error: ${e.message}`);
    }
  }

  remove(index) {
    if (index < 0 || index >= this.accounts.length) return false;
    const removed = this.accounts[index];
    this._archiveRemoved([removed], "manual_remove");
    this.accounts.splice(index, 1);
    if (this.activeIndex === index) this.activeIndex = -1;
    else if (this.activeIndex > index) this.activeIndex--;
    this.save();
    return true;
  }

  removeBatch(indices) {
    const sorted = [...indices].sort((a, b) => b - a);
    const removed = [];
    let count = 0;
    for (const i of sorted) {
      if (i >= 0 && i < this.accounts.length) {
        removed.push(this.accounts[i]);
        this.accounts.splice(i, 1);
        if (this.activeIndex === i) this.activeIndex = -1;
        else if (this.activeIndex > i) this.activeIndex--;
        count++;
      }
    }
    if (count > 0) {
      this._archiveRemoved(removed, "batch_remove");
      this.save();
    }
    return count;
  }

  // 归档被删除的账号 (追加写入，永不丢失)
  _archiveRemoved(accounts, reason) {
    try {
      const archivePath = path.join(
        path.dirname(this._path),
        "_wam_purged.json",
      );
      let existing = [];
      try {
        existing = JSON.parse(fs.readFileSync(archivePath, "utf8"));
      } catch {}
      if (!Array.isArray(existing)) existing = [];
      for (const acc of accounts) {
        existing.push({ ...acc, _purgeReason: reason, _purgedAt: Date.now() });
      }
      fs.writeFileSync(archivePath, JSON.stringify(existing, null, 2), "utf8");
    } catch (e) {
      log(`archive error: ${e.message}`);
    }
  }

  // 智能解析: 支持任意格式 email:password / email password / email\tpassword
  // 也支持 "email----password" / "email|password" / CSV格式等
  addBatch(text) {
    const lines = text
      .split(/[\n\r;]+/)
      .map((l) => l.trim())
      .filter(Boolean);
    let added = 0,
      skipped = 0,
      duplicate = 0;
    for (const line of lines) {
      const parsed = this._parseLine(line);
      if (parsed) {
        const result = this.add(parsed.email, parsed.password);
        if (result) added++;
        else duplicate++;
      } else {
        skipped++;
        log(`parse skip: ${line.substring(0, 60)}`);
      }
    }
    return { added, skipped, duplicate, total: lines.length };
  }

  _parseLine(line) {
    line = line
      .replace(/^\uFEFF/, "")
      .replace(/^["']+|["']+$/g, "")
      .trim();
    if (!line || !line.includes("@")) return null;

    // 辅助: 是否像合法email (含@, @后有.tld, 无多余分隔符)
    const _ok = (s) => {
      const a = s.indexOf("@");
      return a > 0 && s.indexOf(".", a) > a && !/[\s:,|]/.test(s);
    };

    // ── P1: 破折号分隔 (2+连续破折号, indexOf+split最可靠) ──
    // 从最长的匹配开始尝试, 同时尝试首次和末次出现位置
    for (const sep of ["----", "---", "--"]) {
      for (const idx of [line.indexOf(sep), line.lastIndexOf(sep)]) {
        if (idx <= 0) continue;
        const L = line.substring(0, idx).trim();
        const R = line.substring(idx).replace(/^-+/, "").trim();
        if (_ok(L) && R) return { email: L, password: R };
        if (_ok(R) && L) return { email: R, password: L };
      }
    }

    // ── P2: 冒号/管道/逗号/等号分隔 (最常见: email:password) ──
    let m = line.match(/^([^\s:,|=]+@[^\s:,|=]+)[:\s,|=]+(.+)$/);
    if (m) return { email: m[1].trim(), password: m[2].trim() };

    // ── P3: 反向 password:email ──
    m = line.match(/^([^\s@:,|=]+)[:\s,|=]+([^\s:,|=]+@[^\s:,|=]+)$/);
    if (m) return { email: m[2].trim(), password: m[1].trim() };

    // ── P4: Tab分隔 ──
    const tabs = line.split("\t");
    if (tabs.length >= 2) {
      const eI = tabs.findIndex((t) => t.includes("@"));
      if (eI >= 0)
        return {
          email: tabs[eI].trim(),
          password: tabs[eI === 0 ? 1 : 0].trim(),
        };
    }

    // ── P5: 空格分隔 ──
    const sp = line.indexOf(" ");
    if (sp > 0) {
      const L = line.substring(0, sp).trim();
      const R = line.substring(sp + 1).trim();
      if (L.includes("@") && R) return { email: L, password: R };
      if (R.includes("@") && L) return { email: R, password: L };
    }

    // ── P6: 纯邮箱 (无密码) → 拒绝入池，无密码不可切号 ──

    return null;
  }

  getHealth(acc) {
    const u = acc.usage || {};
    const snap = _quotaSnapshots.get((acc.email || "").toLowerCase());
    const checked =
      !!(
        acc.usage &&
        (acc.usage.daily || acc.usage.lastChecked || acc.loginCount > 0)
      ) || !!snap;
    // v7.2: 兼容两种格式 — usage.daily 可能是数字(82)或对象({remaining:82})
    const _readQuota = (field) => {
      if (field == null) return undefined;
      if (typeof field === "number") return field; // 数字格式: 82
      if (typeof field === "object" && field.remaining != null)
        return field.remaining; // 对象格式: {remaining:82}
      return undefined;
    };
    const rawD = _readQuota(u.daily);
    const rawW = _readQuota(u.weekly);
    const storedD = rawD != null ? rawD : checked ? 0 : -1;
    const storedW = rawW != null ? rawW : checked ? 0 : -1;
    // 反者道之动: 快照是实时真相, acc.usage是历史兔底
    const dr = snap ? Math.max(0, Math.min(100, snap.daily)) : storedD;
    const wr = snap ? Math.max(0, Math.min(100, snap.weekly)) : storedW;
    const plan = u.plan || (checked ? "Trial" : "");
    const planEnd = u.planEnd || 0;
    const resetTime = u.resetTime || 0;
    const weeklyReset = u.weeklyReset || 0;
    const lastChecked = snap ? snap.ts : u.lastChecked || 0;
    const now = Date.now();
    // 道法自然: daysLeft允许负值, 负值=过期天数, UI据此区分宽限期(有配额)和真死(无配额)
    const daysLeft = planEnd ? (planEnd - now) / 86400000 : 0;
    const age = acc.addedAt ? Math.round((now - acc.addedAt) / 86400000) : 0;
    const staleMin = lastChecked ? Math.round((now - lastChecked) / 60000) : -1;
    const dailyResetIn =
      resetTime > now ? Math.round((resetTime - now) / 1000) : 0;
    const weeklyResetIn =
      weeklyReset > now ? Math.round((weeklyReset - now) / 1000) : 0;
    return {
      checked,
      daily: dr,
      weekly: wr,
      plan,
      daysLeft: Math.round(daysLeft * 10) / 10,
      age,
      staleMin,
      planEnd,
      resetTime,
      weeklyReset,
      lastChecked,
      dailyResetIn,
      weeklyResetIn,
      hasSnap: !!snap,
    };
  }

  getPoolStats() {
    let totalD = 0,
      totalW = 0,
      available = 0,
      exhausted = 0,
      waiting = 0,
      pwCount = 0,
      unchecked = 0;
    const drought = isWeeklyDrought();
    for (const a of this.accounts) {
      pwCount++;
      if (!a.password) continue;
      const h = this.getHealth(a);
      if (!h.checked) {
        unchecked++;
        continue;
      }
      totalD += h.daily;
      totalW += h.weekly;
      if (!isClaudeAvailable(h)) exhausted++;
      else if (isAccountSwitchable(h)) available++;
      else if (drought ? h.daily <= AUTO_SWITCH_THRESHOLD : h.weekly <= 2)
        exhausted++;
      else waiting++;
    }
    // v7.2: 优先用活跃账号的API重置时间, 仅在无API数据时用计算值兜底
    const now = Date.now();
    const activeAcc =
      this.activeIndex >= 0 ? this.accounts[this.activeIndex] : null;
    const activeUsage = activeAcc ? activeAcc.usage || {} : {};
    const apiDailyMs = activeUsage.resetTime || 0;
    const apiWeeklyMs = activeUsage.weeklyReset || 0;
    const hrsD =
      apiDailyMs > now ? (apiDailyMs - now) / 3600000 : hoursUntilDailyReset();
    const hrsW =
      apiWeeklyMs > now
        ? (apiWeeklyMs - now) / 3600000
        : hoursUntilWeeklyReset();
    return {
      totalD: Math.round(totalD),
      totalW: Math.round(totalW),
      count: this.accounts.length,
      pwCount,
      available,
      exhausted,
      waiting,
      unchecked,
      drought,
      switches: this.switchCount,
      lastRefresh: this.lastRefresh,
      hrsToDaily: hrsD,
      hrsToWeekly: hrsW,
    };
  }

  // 标记使用中 — 消息锚定: 单次波动即刻标记, 冷却INUSE_COOLDOWN_MS后清除 (持久化)
  markInUse(email) {
    const key = email.toLowerCase();
    const now = Date.now();
    const existing = this._inUse.get(key);
    if (existing) {
      existing.lastChange = now;
    } else {
      this._inUse.set(key, { since: now, lastChange: now });
    }
    _inUseDirty = true;
    _schedulePersist();
  }

  // 清除已冷却的使用中标记 (持久化)
  cleanInUse() {
    const now = Date.now();
    let cleaned = false;
    for (const [email, info] of this._inUse) {
      if (now - info.lastChange > INUSE_COOLDOWN_MS) {
        this._inUse.delete(email);
        cleaned = true;
      }
    }
    if (cleaned) {
      _inUseDirty = true;
      _schedulePersist();
    }
  }

  // 判断是否被占用 — 冷却期内即返回true (快标记·慢清除)
  isInUse(email) {
    this.cleanInUse();
    return this._inUse.has(email.toLowerCase());
  }

  // 获取剩余冷却秒数 (UI显示用)
  getInUseCooldown(email) {
    const info = this._inUse.get(email.toLowerCase());
    if (!info) return 0;
    const remaining = INUSE_COOLDOWN_MS - (Date.now() - info.lastChange);
    return remaining > 0 ? Math.ceil(remaining / 1000) : 0;
  }

  clearInUse(email) {
    this._inUse.delete(email.toLowerCase());
    _inUseDirty = true;
    _schedulePersist();
  }

  // 使用中置信度 (0=无, 1=低, 2=中, 3=高)
  getInUseConfidence(email) {
    const key = email.toLowerCase();
    const info = this._inUse.get(key);
    if (!info) return 0;
    const elapsed = Date.now() - info.lastChange;
    if (elapsed > INUSE_COOLDOWN_MS) return 0;
    if (elapsed < 10000) return 3;
    if (elapsed < 30000) return 2;
    return 1;
  }

  getBestIndex(excludeIndex = -1, skipInUse = true) {
    let bestI = -1,
      bestScore = -Infinity;
    const hrsToDaily = hoursUntilDailyReset();
    const hrsToWeekly = hoursUntilWeeklyReset();
    const drought = isWeeklyDrought();

    for (let i = 0; i < this.accounts.length; i++) {
      if (i === excludeIndex) continue;
      const a = this.accounts[i];
      if (!a.password) continue;
      if (a._unverified) continue; // Claude可用性未验证 → 不参与切号
      if (skipInUse && this.isInUse(a.email)) continue;
      if (_isClaimedByOther(a.email)) continue; // 跨实例协调: 跳过被其他存活实例占用的账号
      const h = this.getHealth(a);
      // Claude不可用(Free/试用过期) → 跳过
      if (!isClaudeAvailable(h)) continue;

      if (drought) {
        // ── 干旱模式: 只看Daily, 忽略Weekly(全池都是0) ──
        if (h.daily <= 0 && hrsToDaily > 4) continue;
        let score = 0;
        score += h.daily * 15;
        if (h.daily <= 5 && hrsToDaily <= 2) score += 300;
        else if (h.daily <= 5 && hrsToDaily <= 6) score += 120;
        if (h.daily > 50) score += 200;
        if (h.staleMin >= 0 && h.staleMin < 5) score += 30;
        else if (h.staleMin >= 0 && h.staleMin > 60) score += 60;
        if (score > bestScore) {
          bestScore = score;
          bestI = i;
        }
      } else {
        // ── 正常模式: D+W综合评分 ──
        const eff = Math.min(h.daily, h.weekly);
        if (h.daily <= 0 && h.weekly <= 0 && hrsToDaily > 4 && hrsToWeekly > 4)
          continue;
        if (h.weekly <= 0 && hrsToWeekly > 6) continue;
        let score = 0;
        score += eff * 10;
        score += h.weekly * 8;
        score += h.daily * 3;
        if (h.daily <= 5 && hrsToDaily <= 2) score += 250;
        else if (h.daily <= 5 && hrsToDaily <= 6) score += 100;
        if (h.weekly <= 5 && hrsToWeekly <= 4) score += 350;
        if (h.daily > 50 && h.weekly > 50) score += 200;
        if (h.staleMin >= 0 && h.staleMin < 5) score += 80;
        else if (h.staleMin >= 0 && h.staleMin < 30) score += 40;
        else if (h.staleMin < 0 || h.staleMin > 120) score -= 50;
        if (score > bestScore) {
          bestScore = score;
          bestI = i;
        }
      }
    }
    return bestI;
  }
}

// ============================================================
// 实例协调引擎 — 跨Windsurf实例的账号占用协调
// ============================================================
function _writeInstanceClaim(email) {
  try {
    fs.mkdirSync(WAM_DIR, { recursive: true });
    let claims = {};
    try {
      claims = JSON.parse(fs.readFileSync(INSTANCE_LOCK_FILE, "utf8"));
    } catch {}
    claims[_instanceId] = {
      email: (email || "").toLowerCase(),
      ts: Date.now(),
      pid: process.pid,
    };
    fs.writeFileSync(
      INSTANCE_LOCK_FILE,
      JSON.stringify(claims, null, 2),
      "utf8",
    );
  } catch (e) {
    log(`instance-claim write error: ${e.message}`);
  }
}

function _readInstanceClaims() {
  try {
    if (!fs.existsSync(INSTANCE_LOCK_FILE)) return {};
    return JSON.parse(fs.readFileSync(INSTANCE_LOCK_FILE, "utf8"));
  } catch {
    return {};
  }
}

function _isClaimedByOther(email) {
  const claims = _readInstanceClaims();
  const now = Date.now();
  const key = email.toLowerCase();
  for (const [instId, claim] of Object.entries(claims)) {
    if (instId === _instanceId) continue;
    if (now - claim.ts > INSTANCE_DEAD_MS) continue;
    if (claim.email === key) return true;
  }
  return false;
}

function _cleanDeadInstances() {
  try {
    const claims = _readInstanceClaims();
    const now = Date.now();
    let changed = false;
    for (const [instId, claim] of Object.entries(claims)) {
      if (now - claim.ts > INSTANCE_DEAD_MS) {
        delete claims[instId];
        changed = true;
        log(
          `instance-clean: removed dead ${instId} (${Math.round((now - claim.ts) / 1000)}s stale)`,
        );
      }
    }
    if (changed)
      fs.writeFileSync(
        INSTANCE_LOCK_FILE,
        JSON.stringify(claims, null, 2),
        "utf8",
      );
  } catch {}
}

// ============================================================
// 认证引擎 v4 — 纯Node.js · 多通道并行竞速 · 零外部依赖
// ============================================================

// ── 基础HTTPS请求 ──
function _httpsPost(url, body, opts = {}) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const reqOpts = {
      hostname: opts.hostname || parsed.hostname,
      port: opts.port || parsed.port || 443,
      path: parsed.pathname + parsed.search,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(body),
        Host: parsed.hostname,
        ...(opts.headers || {}),
      },
      timeout: opts.timeout || 12000,
      rejectUnauthorized:
        opts.rejectUnauthorized !== undefined ? opts.rejectUnauthorized : true,
      servername:
        opts.servername !== undefined ? opts.servername : parsed.hostname,
    };
    const req = https.request(reqOpts, (res) => {
      let data = "";
      res.on("data", (c) => (data += c));
      res.on("end", () => {
        try {
          resolve(JSON.parse(data));
        } catch {
          resolve({ _raw: data, _status: res.statusCode });
        }
      });
    });
    req.on("error", reject);
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("timeout"));
    });
    req.write(body);
    req.end();
  });
}

// ── 通过HTTP代理发送HTTPS请求 (CONNECT隧道 + https.request自动处理chunked) ──
function _httpsViaProxy(
  proxyHost,
  proxyPort,
  targetUrl,
  body,
  timeout = 12000,
) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(targetUrl);
    const timer = setTimeout(() => {
      reject(new Error("proxy_timeout"));
    }, timeout);
    const connReq = http.request({
      host: proxyHost,
      port: proxyPort,
      method: "CONNECT",
      path: `${parsed.hostname}:443`,
      timeout: 5000,
    });
    connReq.on("connect", (res, socket) => {
      if (res.statusCode !== 200) {
        clearTimeout(timer);
        socket.destroy();
        reject(new Error(`proxy_connect_${res.statusCode}`));
        return;
      }
      // 用https.request接管已建立的CONNECT隧道socket，自动处理chunked/gzip
      const req = https.request(
        {
          socket, // 复用CONNECT隧道
          hostname: parsed.hostname,
          path: parsed.pathname + parsed.search,
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Content-Length": Buffer.byteLength(body),
            Host: parsed.hostname,
          },
          servername: parsed.hostname,
          rejectUnauthorized: false,
          timeout: timeout - 2000,
        },
        (resp) => {
          let data = "";
          resp.on("data", (c) => (data += c));
          resp.on("end", () => {
            clearTimeout(timer);
            try {
              resolve(JSON.parse(data));
            } catch {
              resolve({ _raw: data, _status: resp.statusCode });
            }
          });
        },
      );
      req.on("error", (e) => {
        clearTimeout(timer);
        reject(e);
      });
      req.on("timeout", () => {
        clearTimeout(timer);
        req.destroy();
        reject(new Error("req_timeout"));
      });
      req.write(body);
      req.end();
    });
    connReq.on("error", (e) => {
      clearTimeout(timer);
      reject(e);
    });
    connReq.on("timeout", () => {
      clearTimeout(timer);
      connReq.destroy();
      reject(new Error("proxy_conn_timeout"));
    });
    connReq.end();
  });
}

// ── 探测本地代理端口 ──
let _proxyPortCache = null;
let _proxyPortCacheTs = 0;
const PROXY_CACHE_TTL = 300000; // 5分钟 TTL
function _detectProxy() {
  if (
    _proxyPortCache !== null &&
    Date.now() - _proxyPortCacheTs < PROXY_CACHE_TTL
  )
    return Promise.resolve(_proxyPortCache);
  _proxyPortCache = null;
  return new Promise((resolve) => {
    let found = false;
    let pending = PROXY_PORTS.length;
    for (const port of PROXY_PORTS) {
      const s = new net.Socket();
      s.setTimeout(800);
      s.connect(port, PROXY_HOST, () => {
        s.destroy();
        if (!found) {
          found = true;
          _proxyPortCache = port;
          _proxyPortCacheTs = Date.now();
          resolve(port);
        }
      });
      s.on("error", () => {
        s.destroy();
        if (--pending === 0 && !found) {
          _proxyPortCache = 0;
          _proxyPortCacheTs = Date.now();
          resolve(0);
        }
      });
      s.on("timeout", () => {
        s.destroy();
        if (--pending === 0 && !found) {
          _proxyPortCache = 0;
          _proxyPortCacheTs = Date.now();
          resolve(0);
        }
      });
    }
  });
}

// ── Raw HTTPS POST (返回Buffer, 用于protobuf二进制响应) ──
function _httpsPostRaw(url, body, opts = {}) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const reqOpts = {
      hostname: opts.hostname || parsed.hostname,
      port: opts.port || parsed.port || 443,
      path: parsed.pathname + parsed.search,
      method: "POST",
      headers: {
        "Content-Type": "application/proto",
        "Content-Length": Buffer.byteLength(body),
        Host: parsed.hostname,
        "connect-protocol-version": "1",
        ...(opts.headers || {}),
      },
      timeout: opts.timeout || 12000,
      rejectUnauthorized: false,
      servername: parsed.hostname,
    };
    const req = https.request(reqOpts, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () =>
        resolve({ buf: Buffer.concat(chunks), status: res.statusCode }),
      );
    });
    req.on("error", reject);
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("timeout"));
    });
    req.write(body);
    req.end();
  });
}

function _httpsPostRawViaProxy(
  proxyHost,
  proxyPort,
  targetUrl,
  body,
  timeout = 12000,
) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(targetUrl);
    const timer = setTimeout(() => {
      reject(new Error("proxy_raw_timeout"));
    }, timeout);
    const connReq = http.request({
      host: proxyHost,
      port: proxyPort,
      method: "CONNECT",
      path: `${parsed.hostname}:443`,
      timeout: 5000,
    });
    connReq.on("connect", (res, socket) => {
      if (res.statusCode !== 200) {
        clearTimeout(timer);
        socket.destroy();
        reject(new Error(`proxy_connect_${res.statusCode}`));
        return;
      }
      const req = https.request(
        {
          socket,
          hostname: parsed.hostname,
          path: parsed.pathname + parsed.search,
          method: "POST",
          headers: {
            "Content-Type": "application/proto",
            "Content-Length": Buffer.byteLength(body),
            Host: parsed.hostname,
            "connect-protocol-version": "1",
          },
          servername: parsed.hostname,
          rejectUnauthorized: false,
          timeout: timeout - 2000,
        },
        (resp) => {
          const chunks = [];
          resp.on("data", (c) => chunks.push(c));
          resp.on("end", () => {
            clearTimeout(timer);
            resolve({ buf: Buffer.concat(chunks), status: resp.statusCode });
          });
        },
      );
      req.on("error", (e) => {
        clearTimeout(timer);
        reject(e);
      });
      req.on("timeout", () => {
        clearTimeout(timer);
        req.destroy();
        reject(new Error("req_timeout"));
      });
      req.write(body);
      req.end();
    });
    connReq.on("error", (e) => {
      clearTimeout(timer);
      reject(e);
    });
    connReq.on("timeout", () => {
      clearTimeout(timer);
      connReq.destroy();
      reject(new Error("proxy_conn_timeout"));
    });
    connReq.end();
  });
}

// ── Protobuf 编解码 (Windsurf API使用Connect协议) ──
function encodeProtoString(str) {
  const b = Buffer.from(str, "utf8");
  const lenBytes = [];
  let l = b.length;
  while (l > 127) {
    lenBytes.push((l & 0x7f) | 0x80);
    l >>= 7;
  }
  lenBytes.push(l);
  return Buffer.concat([Buffer.from([0x0a, ...lenBytes]), b]);
}

function readVarint(buf, pos) {
  let v = 0,
    s = 0;
  while (pos < buf.length) {
    const x = buf[pos++];
    v |= (x & 0x7f) << s;
    if (!(x & 0x80)) return [v, pos];
    s += 7;
  }
  return [v, pos];
}

// ── Protobuf逐字段解析器 ──
// 返回 { varints: {fieldNum: value}, messages: {fieldNum: Buffer} }
// varints = 所有varint字段, messages = 所有length-delimited字段的原始字节
function parseProtoFields(buf) {
  const varints = {},
    messages = {};
  let pos = 0;
  while (pos < buf.length) {
    const [tag, tagEnd] = readVarint(buf, pos);
    if (tagEnd === pos || tag === 0) break;
    pos = tagEnd;
    const fieldNum = tag >>> 3;
    const wireType = tag & 0x07;
    if (fieldNum === 0 || fieldNum > 10000) break;
    switch (wireType) {
      case 0: {
        // varint
        const [val, nextPos] = readVarint(buf, pos);
        if (nextPos === pos) {
          pos = buf.length;
          break;
        }
        pos = nextPos;
        varints[fieldNum] = val;
        break;
      }
      case 1: // 64-bit fixed
        if (pos + 8 > buf.length) {
          pos = buf.length;
          break;
        }
        pos += 8;
        break;
      case 2: {
        // length-delimited (string/bytes/nested)
        const [len, nextPos] = readVarint(buf, pos);
        if (nextPos === pos || nextPos + len > buf.length) {
          pos = buf.length;
          break;
        }
        if (!messages[fieldNum])
          messages[fieldNum] = buf.slice(nextPos, nextPos + len);
        pos = nextPos + len;
        break;
      }
      case 5: // 32-bit fixed
        if (pos + 4 > buf.length) {
          pos = buf.length;
          break;
        }
        pos += 4;
        break;
      default:
        pos = buf.length; // unknown wire type → bail
    }
  }
  return { varints, messages };
}

// 从解析结果中提取D/W额度字段
// v7.1: proto3零值修复 — field 15(weekly)缺失时不再盲目默认0
// 诊断发现: API可能不返回field 15(weekly%), 且field 17===18(daily/weekly reset相同)
// 这表示API已统一D/W或weekly不再单独限制, 此时weekly应镜像daily
function _extractQuotaFields(v, msgs) {
  const dailyR = v[14],
    weeklyR = v[15],
    used = v[6],
    total = v[8],
    dReset = v[17],
    wReset = v[18];
  let valid = 0;
  if (dailyR !== undefined && dailyR >= 0 && dailyR <= 100) valid++;
  if (weeklyR !== undefined && weeklyR >= 0 && weeklyR <= 100) valid++;
  if (dReset !== undefined && dReset > 1700000000) valid++;
  if (wReset !== undefined && wReset > 1700000000) valid++;
  if (used !== undefined && used > 0 && used <= 10000) valid++;
  if (total !== undefined && total > 0 && total <= 10000) valid++;
  if (valid < 2) return null; // 至少2个有效字段才接受 (防relay单字段误读)

  // 尝试从protobuf string字段中提取plan名称
  let planName = null;
  if (msgs) {
    const knownPlans =
      /^(free|pro_trial|pro|trial|enterprise|team|individual)$/i;
    for (const fn of Object.keys(msgs)) {
      try {
        const str = msgs[fn].toString("utf8").trim();
        if (knownPlans.test(str)) {
          planName = str;
          break;
        }
      } catch {}
    }
  }

  const dailyVal =
    dailyR !== undefined && dailyR >= 0 && dailyR <= 100 ? dailyR : 0;

  // Weekly修复: proto3零值省略 + API统一D/W
  // 1. field 15存在且有效 → 直接使用
  // 2. field 15缺失 + field 17===18(reset相同) → API已统一D/W, weekly镜像daily
  // 3. field 15缺失 + daily>0 → weekly未知但账号活跃, 镜像daily(保守安全)
  // 4. field 15缺失 + daily===0 → 账号可能真的耗尽, weekly=0
  let weeklyVal;
  if (weeklyR !== undefined && weeklyR >= 0 && weeklyR <= 100) {
    weeklyVal = weeklyR;
  } else if (dReset && wReset && dReset === wReset) {
    // API返回相同的D/W重置时间 → D/W已统一, weekly不再独立限制
    weeklyVal = dailyVal;
  } else if (dailyVal > 0) {
    // daily有余量但weekly缺失 → 保守镜像daily
    weeklyVal = dailyVal;
  } else {
    weeklyVal = 0;
  }

  // 提取plan有效期时间戳: field 2 → planStart, field 3 → planEnd (嵌套message内field 1为unix秒)
  // 官方实证: Trial = 14天 (如 Apr 1 - Apr 15, 2026)
  let planStartUnix = 0,
    planEndUnix = 0;
  if (msgs) {
    try {
      if (msgs[2]) {
        const sf = parseProtoFields(msgs[2]);
        const ts = sf.varints[1];
        if (ts && ts > 1700000000 && ts < 2100000000) planStartUnix = ts;
      }
      if (msgs[3]) {
        const ef = parseProtoFields(msgs[3]);
        const ts = ef.varints[1];
        if (ts && ts > 1700000000 && ts < 2100000000) planEndUnix = ts;
      }
    } catch {}
    // 交叉验证: planStart和planEnd应构成合理区间(1-365天)
    if (planStartUnix && planEndUnix) {
      const durDays = (planEndUnix - planStartUnix) / 86400;
      if (planStartUnix >= planEndUnix || durDays > 365) {
        log(
          `planDate suspect: start=${new Date(planStartUnix * 1000).toISOString().slice(0, 10)} end=${new Date(planEndUnix * 1000).toISOString().slice(0, 10)} dur=${durDays.toFixed(1)}d → discard`,
        );
        planStartUnix = 0;
        planEndUnix = 0;
      }
    }
  }

  return {
    daily: dailyVal,
    weekly: weeklyVal,
    dailyResetUnix: dReset && dReset > 1700000000 ? dReset : 0,
    weeklyResetUnix: wReset && wReset > 1700000000 ? wReset : 0,
    creditsUsed: used && used > 0 && used <= 10000 ? used / 100 : 0,
    creditsTotal: total && total > 0 && total <= 10000 ? total / 100 : 100,
    planName,
    planStartUnix,
    planEndUnix,
  };
}

function parsePlanStatus(buf) {
  // 非protobuf响应快速拒绝 (JSON/HTML错误页)
  if (buf.length < 50 || buf[0] === 0x7b || buf[0] === 0x3c) return null; // '{' or '<'
  // ── 层1: 剥离gRPC 5字节envelope (flags[1]+length[4]) ──
  let pb = buf;
  let stripped = false;
  if (pb.length >= 5) {
    const flags = pb[0];
    const msgLen = pb.readUInt32BE(1);
    if (
      (flags === 0x00 || flags === 0x02) &&
      msgLen > 0 &&
      msgLen + 5 <= pb.length
    ) {
      pb = pb.slice(5, 5 + msgLen);
      stripped = true;
    }
  }

  const top = parseProtoFields(pb);

  // ── 关键策略: 深层优先 ──
  // relay可能在自己的wrapper消息中有field 14/15(非D/W), 导致L2误读
  // 所以: 有wrapper(field 1)时, 优先解析内层(L3/L4), L2仅做fallback

  // ── 层3/4: 优先解析wrapper内部 ──
  if (top.messages[1] && top.messages[1].length > 10) {
    const inner = parseProtoFields(top.messages[1]);
    let result = _extractQuotaFields(inner.varints, inner.messages);
    if (result) {
      log(
        `proto L3: D${result.daily} W${result.weekly}${result.planName ? " plan=" + result.planName : ""}${result.planEndUnix ? " end=" + new Date(result.planEndUnix * 1000).toISOString().slice(0, 10) : ""} env=${stripped} ${pb.length}B`,
      );
      return result;
    }
    // 层4: 再深一层
    if (inner.messages[1] && inner.messages[1].length > 10) {
      const deep = parseProtoFields(inner.messages[1]);
      result = _extractQuotaFields(deep.varints, deep.messages);
      if (result) {
        log(
          `proto L4: D${result.daily} W${result.weekly}${result.planName ? " plan=" + result.planName : ""}${result.planEndUnix ? " end=" + new Date(result.planEndUnix * 1000).toISOString().slice(0, 10) : ""} env=${stripped} ${pb.length}B`,
        );
        return result;
      }
    }
  }

  // ── 层2: fallback — 仅当没有wrapper时才用顶层字段 ──
  // (response经envelope剥离后直接是Codeium protobuf, 无relay wrapper)
  let result = _extractQuotaFields(top.varints, top.messages);
  if (result) {
    log(
      `proto L2: D${result.daily} W${result.weekly}${result.planEndUnix ? " end=" + new Date(result.planEndUnix * 1000).toISOString().slice(0, 10) : ""} env=${stripped} ${pb.length}B b0=0x${buf[0].toString(16)}`,
    );
    return result;
  }

  log(
    `parsePlanStatus: no quota in ${pb.length}B env=${stripped} b0=0x${buf[0].toString(16)} top=${Object.keys(top.varints).join(",")} hex=${pb.slice(0, 48).toString("hex")}`,
  );
  return null;
}

// ── 单通道Firebase登录 ──
async function _firebaseVia(channel, email, password, key) {
  const payload = JSON.stringify({ email, password, returnSecureToken: true });
  const url = `https://${FIREBASE_HOST}/v1/accounts:signInWithPassword?key=${key}`;

  switch (channel) {
    case "direct":
      return _httpsPost(url, payload, { timeout: 8000 });

    case "proxy":
      return _detectProxy().then((port) => {
        if (!port) throw new Error("no_proxy");
        return _httpsViaProxy(PROXY_HOST, port, url, payload, 10000);
      });

    default:
      throw new Error(`unknown_channel: ${channel}`);
  }
}

// ── 多通道并行竞速 Firebase 登录 (v7.3: 快速失败 — 串行重试→并行重试, 60s→20s) ──
async function firebaseLogin(email, password) {
  const channels = ["proxy", "direct"];
  const errors = {};

  for (const key of FIREBASE_KEYS) {
    const keySuffix = key.slice(-4);
    const racePromises = channels.map((ch) =>
      _firebaseVia(ch, email, password, key)
        .then((result) => {
          if (result && result.idToken)
            return {
              ok: true,
              idToken: result.idToken,
              channel: `${ch}-${keySuffix}`,
            };
          const err = result?.error;
          const msg = (typeof err === "object" ? err?.message : err) || "";
          if (/INVALID|NOT_FOUND|DISABLED|WRONG/.test(msg)) {
            return { ok: false, permanent: true, error: msg };
          }
          throw new Error(msg || "no_token");
        })
        .catch((e) => {
          errors[`${ch}-${keySuffix}`] = e.message;
          throw e;
        }),
    );

    try {
      const result = await Promise.any(racePromises);
      if (result.ok) return result;
      if (result.permanent)
        return { ok: false, error: result.error, channel: "permanent" };
    } catch (aggErr) {
      const permanentErr = Object.values(errors).find((e) =>
        /INVALID|NOT_FOUND|DISABLED|WRONG/.test(e),
      );
      if (permanentErr)
        return { ok: false, error: permanentErr, channel: "permanent" };
    }
  }

  // v7.3: 快速重试 — 重置代理缓存后并行竞速一次(替代旧版的串行循环, 从40s→8s)
  _proxyPortCache = null;
  const retryKey = FIREBASE_KEYS[0];
  const retryKeySuffix = retryKey.slice(-4);
  const retryPromises = channels.map((ch) =>
    _firebaseVia(ch, email, password, retryKey)
      .then((r) => {
        if (r && r.idToken)
          return {
            ok: true,
            idToken: r.idToken,
            channel: `retry-${ch}-${retryKeySuffix}`,
          };
        throw new Error("no_token");
      })
      .catch((e) => {
        errors[`retry-${ch}`] = e.message;
        throw e;
      }),
  );
  try {
    const result = await Promise.any(retryPromises);
    if (result.ok) return result;
  } catch {}

  return { ok: false, error: "all_channels_failed", details: errors };
}

// ── 获取缓存的idToken或重新登录 ──
async function getCachedToken(email, password) {
  const key = email.toLowerCase();
  const cached = _tokenCache.get(key);
  if (cached && cached.expiresAt > Date.now())
    return { ok: true, idToken: cached.idToken };
  const loginResult = await firebaseLogin(email, password);
  if (!loginResult.ok) return loginResult;
  _tokenCache.set(key, {
    idToken: loginResult.idToken,
    expiresAt: Date.now() + TOKEN_CACHE_TTL,
  });
  return loginResult;
}

// ── 获取账号实时额度 (Firebase登录→Relay→PlanStatus) ──
// v7.2: 速率限制 — 每账号最少间隔10秒，429后退避60秒
const _quotaFetchCooldown = new Map(); // email → {nextAllowedTs}
const QUOTA_MIN_INTERVAL = 10000; // 正常最小间隔10秒
const QUOTA_429_BACKOFF = 60000; // 429后退避60秒

// v10: 通用DNS解析引擎 — 系统DNS优先, DoH兜底, 彻底消除proxy循环依赖
const _hostIPCache = new Map(); // hostname -> {ip, ts}
const HOST_IP_TTL = 600000; // IP缓存10分钟
// v7.2兼容保留
let _relayIPCache = { ip: null, ts: 0 };
const RELAY_IP_TTL = 600000;

async function _resolveHostIP(hostname) {
  const cached = _hostIPCache.get(hostname);
  if (cached && Date.now() - cached.ts < HOST_IP_TTL) return cached.ip;

  // 方法1: 系统DNS直接解析 (无需proxy, 最快最可靠)
  try {
    const ip = await new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new Error("sys_dns_timeout")),
        5000,
      );
      dns.resolve4(hostname, (err, addresses) => {
        clearTimeout(timer);
        if (err || !addresses || addresses.length === 0)
          reject(err || new Error("no_addr"));
        else resolve(addresses[0]);
      });
    });
    // 验证: 非回环/私网IP才接受 (Clash fake-ip返回198.18.x.x或127.0.0.1)
    if (
      ip &&
      /^\d+\.\d+\.\d+\.\d+$/.test(ip) &&
      !ip.startsWith("127.") &&
      !ip.startsWith("198.18.") &&
      !ip.startsWith("0.")
    ) {
      _hostIPCache.set(hostname, { ip, ts: Date.now() });
      log(`dns: ${hostname} → ${ip} (system)`);
      return ip;
    }
    log(`dns: ${hostname} → ${ip} (fake-ip detected, falling through)`);
  } catch (e) {
    log(`dns system: ${hostname} ${e.message}`);
  }

  // 方法2: DoH直连 (不经proxy, 直接访问Cloudflare/Google DNS)
  const dohProviders = [
    {
      host: "1.1.1.1",
      path: `/dns-query?name=${hostname}&type=A`,
      headers: { Accept: "application/dns-json" },
    },
    { host: "8.8.8.8", path: `/resolve?name=${hostname}&type=A`, headers: {} },
  ];
  for (const doh of dohProviders) {
    try {
      const ip = await new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error("doh_timeout")), 6000);
        const req = https.request(
          {
            hostname: doh.host,
            port: 443,
            path: doh.path,
            method: "GET",
            headers: { ...doh.headers, Host: doh.host },
            servername: doh.host,
            rejectUnauthorized: false,
            timeout: 5000,
          },
          (resp) => {
            let d = "";
            resp.on("data", (c) => (d += c));
            resp.on("end", () => {
              clearTimeout(timer);
              try {
                const j = JSON.parse(d);
                resolve(j.Answer ? j.Answer[0].data : null);
              } catch {
                resolve(null);
              }
            });
          },
        );
        req.on("error", (e) => {
          clearTimeout(timer);
          reject(e);
        });
        req.end();
      });
      if (
        ip &&
        /^\d+\.\d+\.\d+\.\d+$/.test(ip) &&
        !ip.startsWith("127.") &&
        !ip.startsWith("198.18.")
      ) {
        _hostIPCache.set(hostname, { ip, ts: Date.now() });
        log(`dns: ${hostname} → ${ip} (DoH-${doh.host})`);
        return ip;
      }
    } catch (e) {
      log(`dns DoH-${doh.host}: ${e.message}`);
    }
  }

  // 方法3: DoH via proxy (原始方案, 最后手段)
  try {
    const port = await _detectProxy();
    if (port) {
      const dohResult = await new Promise((resolve, reject) => {
        const timer = setTimeout(
          () => reject(new Error("doh_proxy_timeout")),
          8000,
        );
        const connReq = http.request({
          host: PROXY_HOST,
          port,
          method: "CONNECT",
          path: "dns.google:443",
          timeout: 5000,
        });
        connReq.on("connect", (res, socket) => {
          if (res.statusCode !== 200) {
            clearTimeout(timer);
            socket.destroy();
            reject(new Error("doh_proxy"));
            return;
          }
          const req = https.request(
            {
              socket,
              hostname: "dns.google",
              path: `/resolve?name=${hostname}&type=A`,
              method: "GET",
              headers: { Host: "dns.google" },
              servername: "dns.google",
              rejectUnauthorized: false,
              timeout: 6000,
            },
            (resp) => {
              let d = "";
              resp.on("data", (c) => (d += c));
              resp.on("end", () => {
                clearTimeout(timer);
                try {
                  const j = JSON.parse(d);
                  resolve(j.Answer ? j.Answer[0].data : null);
                } catch {
                  resolve(null);
                }
              });
            },
          );
          req.on("error", (e) => {
            clearTimeout(timer);
            reject(e);
          });
          req.end();
        });
        connReq.on("error", (e) => {
          clearTimeout(timer);
          reject(e);
        });
        connReq.end();
      });
      if (dohResult && /^\d+\.\d+\.\d+\.\d+$/.test(dohResult)) {
        _hostIPCache.set(hostname, { ip: dohResult, ts: Date.now() });
        log(`dns: ${hostname} → ${dohResult} (DoH-proxy)`);
        return dohResult;
      }
    }
  } catch (e) {
    log(`dns proxy: ${e.message}`);
  }

  // 返回过期缓存总比没有好
  const stale = _hostIPCache.get(hostname);
  return stale ? stale.ip : null;
}

async function _resolveRelayIP() {
  const ip = await _resolveHostIP(RELAY_HOST);
  if (ip) _relayIPCache = { ip, ts: Date.now() };
  return ip || _relayIPCache.ip;
}

// v10: 全局限流协调 — 跨实例文件锁, 防止多WAM实例轰炸API
function _globalRateCheck() {
  try {
    const now = Date.now();
    let data = { timestamps: [] };
    try {
      data = JSON.parse(fs.readFileSync(GLOBAL_RATE_FILE, "utf8"));
    } catch {}
    // 清除过期时间戳
    data.timestamps = (data.timestamps || []).filter(
      (ts) => now - ts < GLOBAL_RATE_WINDOW,
    );
    if (data.timestamps.length >= GLOBAL_RATE_MAX) return false; // 限流
    data.timestamps.push(now);
    fs.writeFileSync(GLOBAL_RATE_FILE, JSON.stringify(data), "utf8");
    return true;
  } catch {
    return true;
  } // 文件锁失败不阻塞
}

async function fetchAccountQuota(email, password) {
  const key = email.toLowerCase();
  const now = Date.now();
  const cd = _quotaFetchCooldown.get(key);
  if (cd && now < cd.nextAllowedTs) {
    // v10: 限流时返回缓存数据而非空
    const cached = _quotaSnapshots.get(key);
    if (cached)
      return {
        ok: true,
        email,
        channel: "cache",
        daily: cached.daily,
        weekly: cached.weekly,
        _cached: true,
      };
    return {
      ok: false,
      error: "rate_limited",
      retryAfter: cd.nextAllowedTs - now,
    };
  }
  _quotaFetchCooldown.set(key, { nextAllowedTs: now + QUOTA_MIN_INTERVAL });

  // v10: 全局限流检查
  if (!_globalRateCheck()) {
    const cached = _quotaSnapshots.get(key);
    if (cached)
      return {
        ok: true,
        email,
        channel: "cache_global",
        daily: cached.daily,
        weekly: cached.weekly,
        _cached: true,
      };
    return { ok: false, error: "global_rate_limited" };
  }

  const loginResult = await getCachedToken(email, password);
  if (!loginResult.ok) {
    _tokenCache.delete(key);
    return { ok: false, error: loginResult.error };
  }
  const proto = encodeProtoString(loginResult.idToken);
  const relayUrl = `https://${RELAY_HOST}/windsurf/plan-status`;

  // v10: 5通道竞速 — 官方直连优先, 中继兜底
  // 通道优先级: 官方直连(proxy) > 官方直连(direct) > Relay直连IP > Relay(proxy)
  const channels = [
    // 通道1: 官方API直连 via proxy (最可靠: 官方服务器不限流)
    {
      name: "official-proxy",
      fn: async () => {
        const port = await _detectProxy();
        if (!port) throw new Error("no_proxy");
        // 尝试所有官方端点
        for (const url of OFFICIAL_PLAN_STATUS_URLS) {
          try {
            const resp = await _httpsPostRawViaProxy(
              PROXY_HOST,
              port,
              url,
              proto,
              10000,
            );
            if (resp.status === 200 && resp.buf && resp.buf.length > 20)
              return resp;
          } catch {}
        }
        throw new Error("all_official_proxy_failed");
      },
    },
    // 通道2: 官方API直连 (无proxy, 适合无代理用户 — 需要能直连Google Cloud)
    {
      name: "official-direct",
      fn: async () => {
        for (const url of OFFICIAL_PLAN_STATUS_URLS) {
          try {
            const resp = await _httpsPostRaw(url, proto, { timeout: 10000 });
            if (resp.status === 200 && resp.buf && resp.buf.length > 20)
              return resp;
          } catch {}
        }
        throw new Error("all_official_direct_failed");
      },
    },
    // 通道3: Relay直连真实IP (DoH解析绕过fake-ip)
    {
      name: "relay-direct",
      fn: async () => {
        const ip = await _resolveRelayIP();
        if (!ip) throw new Error("no_relay_ip");
        return _httpsPostRaw(relayUrl, proto, { timeout: 12000, hostname: ip });
      },
    },
    // 通道4: Relay via proxy (最后手段)
    {
      name: "relay-proxy",
      fn: async () => {
        const port = await _detectProxy();
        if (!port) throw new Error("no_proxy");
        return _httpsPostRawViaProxy(PROXY_HOST, port, relayUrl, proto, 10000);
      },
    },
  ];

  log(`quota: ${channels.length}ch for ${email.substring(0, 15)}`);

  // v10: 并行竞速 — 同时启动所有通道, 第一个成功即返回
  const racePromises = channels.map((ch) =>
    ch
      .fn()
      .then((resp) => {
        if (resp.status === 429) throw new Error(`429_${ch.name}`);
        if (resp.status === 200 && resp.buf && resp.buf.length > 20) {
          const q = parsePlanStatus(resp.buf);
          if (q) return { channel: ch.name, quota: q };
        }
        throw new Error(`parse_fail_${ch.name}`);
      })
      .catch((e) => {
        throw e;
      }),
  );

  try {
    const result = await Promise.any(racePromises);
    _updateAccountUsage(email, result.quota);
    log(
      `${result.channel}: OK D${result.quota.daily} W${result.quota.weekly}${result.quota.planName ? " " + result.quota.planName : ""}`,
    );
    return { ok: true, email, channel: result.channel, ...result.quota };
  } catch (aggErr) {
    // v10: 所有通道失败 → 429退避 + 缓存降级
    const has429 = aggErr.errors?.some((e) => e.message?.startsWith("429_"));
    if (has429) {
      _quotaFetchCooldown.set(key, {
        nextAllowedTs: Date.now() + QUOTA_429_BACKOFF,
      });
      log(`quota: all 429 → backoff ${QUOTA_429_BACKOFF / 1000}s`);
    }
    // v10: 缓存降级 — 返回上次已知额度, 不让UI显示0
    const cached = _quotaSnapshots.get(key);
    if (cached && cached.daily !== undefined) {
      log(
        `quota: all channels failed → using cached D${cached.daily} W${cached.weekly}`,
      );
      return {
        ok: true,
        email,
        channel: "cache_degraded",
        daily: cached.daily,
        weekly: cached.weekly,
        _cached: true,
      };
    }
    // 从acc.usage恢复 (磁盘持久化数据)
    if (_store) {
      const acc = _store.accounts.find((a) => a.email.toLowerCase() === key);
      if (acc && acc.usage) {
        const rd = (f) =>
          f == null
            ? -1
            : typeof f === "number"
              ? f
              : f && f.remaining != null
                ? f.remaining
                : -1;
        const d = rd(acc.usage.daily),
          w = rd(acc.usage.weekly);
        if (d >= 0 && w >= 0) {
          log(`quota: all channels failed → using stored D${d} W${w}`);
          return {
            ok: true,
            email,
            channel: "stored_degraded",
            daily: d,
            weekly: w,
            _cached: true,
          };
        }
      }
    }
    log(`quota: all channels failed, no cache available`);
    return { ok: false, error: "quota_fetch_failed" };
  }
}

// 将API获取到的额度写回账号对象
function _updateAccountUsage(email, quota) {
  if (!_store) return;
  const acc = _store.accounts.find(
    (a) => a.email.toLowerCase() === email.toLowerCase(),
  );
  if (!acc) return;
  const prev = acc.usage || {};
  const now = Date.now();

  // API提供的重置时间优先, 否则用计算值
  const apiDailyReset = quota.dailyResetUnix ? quota.dailyResetUnix * 1000 : 0;
  const apiWeeklyReset = quota.weeklyResetUnix
    ? quota.weeklyResetUnix * 1000
    : 0;
  const calcDailyReset = getNextDailyResetMs();
  const calcWeeklyReset = getNextWeeklyResetMs();

  // v7.2: 始终信任API重置时间, 仅在API无值时用计算值兜底
  const effectiveWeeklyReset =
    apiWeeklyReset || calcWeeklyReset || prev.weeklyReset || 0;

  acc.usage = {
    daily: { remaining: quota.daily },
    weekly: { remaining: quota.weekly },
    plan: quota.planName || prev.plan || "Trial",
    // 道法自然: planEnd过期但仍有配额(D>0或W>0) → 不存储过期planEnd, 避免误标"已过期"
    planEnd: (() => {
      const pe = quota.planEndUnix ? quota.planEndUnix * 1000 : 0;
      if (pe > 0 && pe < Date.now() && (quota.daily > 0 || quota.weekly > 0))
        return 0; // 宽限期: 清除过期planEnd
      return pe || prev.planEnd || 0;
    })(),
    // 重置时间: API值 > 计算值 > 旧值
    resetTime: apiDailyReset || calcDailyReset || prev.resetTime || 0,
    weeklyReset: effectiveWeeklyReset,
    lastChecked: now,
    // 额外追踪: credits数据 + 有效配额
    creditsUsed: quota.creditsUsed || prev.creditsUsed || 0,
    creditsTotal: quota.creditsTotal || prev.creditsTotal || 100,
    effective: Math.min(quota.daily, quota.weekly),
  };
}

// ── Token注入 (v9.1 — 五感模式: 纯热替换·绝不logout·绝不中断对话·绝不杀agent) ──
// 根因修复: v8.0的Phase2 degraded path调用windsurf.logout是"切号退出登录+agent中断"的唯一根源
// 道法自然: provideAuthTokenToAuthProvider本身就是原子替换, 无需先登出
// 五感原则: 失败则优雅降级, 绝不破坏现有会话 — 保持当前号继续运行远比强行切号重要
async function injectAuth(idToken) {
  const cmd = "windsurf.provideAuthTokenToAuthProvider";
  const TIMEOUTS = [15000, 15000, 20000, 25000]; // 4次尝试, 逐步放宽超时
  const BACKOFFS = [0, 500, 1500, 3000]; // 退避递增: 0→0.5→1.5→3s

  for (let attempt = 1; attempt <= 4; attempt++) {
    try {
      if (BACKOFFS[attempt - 1] > 0) {
        log(
          `inject: backoff ${BACKOFFS[attempt - 1]}ms before attempt ${attempt}`,
        );
        await new Promise((r) => setTimeout(r, BACKOFFS[attempt - 1]));
      }
      log(`inject: hot-swap attempt ${attempt}/4 (no-logout·五感模式)`);
      const timeout = TIMEOUTS[attempt - 1];
      const result = await Promise.race([
        vscode.commands.executeCommand(cmd, idToken),
        new Promise((_, rej) =>
          setTimeout(
            () => rej(new Error(`注入超时${timeout / 1000}s`)),
            timeout,
          ),
        ),
      ]);
      const extracted = _extractInjectResult(result);
      if (extracted) {
        log(`inject: hot-swap OK on attempt ${attempt}`);
        _lastSwitchTime = Date.now();
        return extracted;
      }
      if (result && result.error) {
        log(
          `inject: attempt ${attempt} error: ${JSON.stringify(result.error)}`,
        );
      } else {
        log(
          `inject: attempt ${attempt} unexpected: ${JSON.stringify(result || null).substring(0, 200)}`,
        );
      }
    } catch (e) {
      log(`inject: attempt ${attempt} threw: ${e.message}`);
    }
  }
  // 五感模式: 4次全败也绝不logout — 保持现有会话不受干扰, agent继续运行
  log(
    "inject: all 4 hot-swap attempts failed — 五感模式: 保持现有会话, 不logout, 不中断agent",
  );
  return {
    ok: false,
    error: "all 4 inject attempts failed (五感模式: 已保留现有会话)",
  };
}

// 提取注入结果的通用辅助 (避免重复代码)
function _extractInjectResult(result) {
  if (!result) return null;
  if (result.session) {
    const s = result.session;
    return {
      ok: true,
      account: s.account?.label || "?",
      apiKey: s.accessToken || "",
      sessionId: s.id || "",
    };
  }
  if (result.account && !result.error) {
    return {
      ok: true,
      account: result.account?.label || result.account || "?",
      apiKey: result.accessToken || "",
      sessionId: result.id || "",
    };
  }
  return null;
}

// ── Firebase accounts:lookup — 获取账号创建时间 (官方API) ──
async function firebaseLookup(idToken) {
  const payload = JSON.stringify({ idToken });
  for (const key of FIREBASE_KEYS) {
    const url = `https://${FIREBASE_HOST}/v1/accounts:lookup?key=${key}`;
    try {
      const result = await _httpsPost(url, payload, { timeout: 8000 });
      if (result?.users?.[0]) return result.users[0];
    } catch {}
    // 也尝试代理通道
    try {
      const port = await _detectProxy();
      if (port) {
        const url2 = `https://${FIREBASE_HOST}/v1/accounts:lookup?key=${key}`;
        const result = await _httpsViaProxy(
          PROXY_HOST,
          port,
          url2,
          payload,
          10000,
        );
        if (result?.users?.[0]) return result.users[0];
      }
    } catch {}
  }
  return null;
}

// ── 判断账号是否真正过期(已被isClaudeAvailable取代用于清理决策) ──
// 反者道之动: planEnd过期→试用降级Free→Claude($$$)不可用
// 清理决策统一由isClaudeAvailable()判定, 此函数保留用于兼容
function isTrialExpired(createdAtMs, acc) {
  const planEnd = acc?.usage?.planEnd;
  if (planEnd && planEnd > 0) {
    return Date.now() > planEnd;
  }
  // 不再用createdAt猜测——官方Trial是14天而非90天, 且过期后仍可用
  return false;
}

// ── 批量验证 + 自动剔除 (官方Firebase机制) ──
async function verifyAndPurgeExpired(store, opts = {}) {
  if (_purgeRunning) {
    log("purge: already running");
    return { purged: 0 };
  }
  _purgeRunning = true;
  const silent = opts.silent || false;
  const toRemoveIndices = [];
  const reasons = {}; // index -> reason string
  const pwAccounts = [];

  for (let i = 0; i < store.accounts.length; i++) {
    if (store.accounts[i].password) pwAccounts.push(i);
  }

  log(`purge: verifying ${pwAccounts.length} accounts...`);
  if (!silent)
    broadcastMessage({
      type: "toast",
      text: `正在验证 ${pwAccounts.length} 个账号...`,
    });

  for (const i of pwAccounts) {
    const acc = store.accounts[i];
    if (!acc) continue;

    // Step 1: Firebase登录验证
    const loginResult = await firebaseLogin(acc.email, acc.password);

    if (!loginResult.ok) {
      const err = loginResult.error || "";
      // 永久性错误 → 标记移除
      if (/INVALID|NOT_FOUND|DISABLED|WRONG/.test(err)) {
        toRemoveIndices.push(i);
        reasons[i] = `login_dead: ${err}`;
        log(`purge: ${acc.email} → DEAD (${err})`);
        continue;
      }
      // 网络/临时错误 → 跳过 (不冤枉)
      log(`purge: ${acc.email} → skip (${err})`);
      continue;
    }

    // Step 2: 用idToken查询账号元信息 (官方Firebase lookup)
    const userInfo = await firebaseLookup(loginResult.idToken);
    if (userInfo) {
      const createdAt = Number(userInfo.createdAt || 0);
      const ageDays = createdAt ? (Date.now() - createdAt) / 86400000 : 0;

      // 写回信息到账号对象
      acc._firebaseCreatedAt = createdAt;
      acc._firebaseDisplayName = userInfo.displayName || "";
      acc._lastVerified = Date.now();

      if (userInfo.disabled) {
        toRemoveIndices.push(i);
        reasons[i] = "account_disabled";
        log(`purge: ${acc.email} → DISABLED`);
        continue;
      }

      log(`purge: ${acc.email} → login OK (${ageDays.toFixed(1)}d)`);
    }

    // Step 2.5: 深度探测 — 获取实时Plan状态, 不信缓存只信API
    // 反者道之动: D100/W100是假象, plan才是Claude可用性的ground truth
    if (!toRemoveIndices.includes(i)) {
      try {
        const quota = await fetchAccountQuota(acc.email, acc.password);
        if (quota.ok) {
          const freshPlan = (quota.planName || "").toLowerCase();
          const freshPlanEnd = quota.planEndUnix ? quota.planEndUnix * 1000 : 0;
          const isExpired = freshPlanEnd > 0 && Date.now() > freshPlanEnd;
          const daysExpired = isExpired
            ? (Date.now() - freshPlanEnd) / 86400000
            : 0;

          // Case 1: 实时plan是free → 无Claude($$$)权限 → 清理
          if (freshPlan === "free") {
            toRemoveIndices.push(i);
            reasons[i] =
              `probe_free: plan=free, D${quota.daily}W${quota.weekly}仅限免费模型, Claude不可用`;
            log(
              `purge: ${acc.email} → FREE (实时探测: plan=${freshPlan}, D${quota.daily}W${quota.weekly})`,
            );
          }
          // Case 2: 试用过期 — 仅当D=0且W=0时才清理(planEnd过期但有配额仍可用)
          else if (
            isExpired &&
            isTrialPlan(freshPlan) &&
            quota.daily === 0 &&
            quota.weekly === 0
          ) {
            toRemoveIndices.push(i);
            reasons[i] =
              `expired_trial_no_quota: plan=${freshPlan}过期${daysExpired.toFixed(1)}天且D0/W0, Claude不可用`;
            log(
              `purge: ${acc.email} → EXPIRED+D0W0 ${daysExpired.toFixed(1)}d (plan=${freshPlan}, end=${new Date(freshPlanEnd).toISOString().slice(0, 10)})`,
            );
          }
          // Case 2b: 试用过期但仍有配额 → 保留(Windsurf宽限期)
          else if (isExpired && isTrialPlan(freshPlan)) {
            log(
              `purge: ${acc.email} → EXPIRED_BUT_USABLE (plan=${freshPlan} expired ${daysExpired.toFixed(1)}d, but D${quota.daily}W${quota.weekly}>0, 保留)`,
            );
          }
          // Case 3: Claude可用
          else {
            log(
              `purge: ${acc.email} → CLAUDE✓ (plan=${freshPlan}${isExpired ? " expired!" : ""} D${quota.daily}W${quota.weekly})`,
            );
          }
        } else {
          log(
            `purge: ${acc.email} → probe failed: ${quota.error} (保留, 不冤枉)`,
          );
        }
      } catch (e) {
        log(`purge: ${acc.email} → probe error: ${e.message} (保留, 不冤枉)`);
      }
    }

    // 限速保护
    await new Promise((r) => setTimeout(r, 300));
  }

  // Step 3: 缓存兜底 — 深度探测可能遗漏的(网络失败等), 用缓存数据补刀
  for (let i = 0; i < store.accounts.length; i++) {
    if (toRemoveIndices.includes(i)) continue;
    const acc = store.accounts[i];
    if (!acc.password) continue;
    const h = store.getHealth(acc);

    // 缓存plan是free → 清理
    if ((h.plan || "").toLowerCase() === "free") {
      toRemoveIndices.push(i);
      reasons[i] = "cached_free: 缓存plan=free, Claude不可用";
      log(`purge: ${acc.email} → FREE (缓存兜底)`);
      continue;
    }

    // 缓存planEnd已过期 + 试用计划 + D=0且W=0 → 清理(有配额的保留)
    if (
      h.planEnd > 0 &&
      h.daysLeft <= 0 &&
      isTrialPlan(h.plan) &&
      (h.daily || 0) === 0 &&
      (h.weekly || 0) === 0
    ) {
      toRemoveIndices.push(i);
      reasons[i] =
        `cached_expired_no_quota: plan=${h.plan}过期${Math.abs(h.daysLeft).toFixed(1)}天且D0/W0, Claude不可用`;
      log(
        `purge: ${acc.email} → EXPIRED+D0W0 (缓存兜底: plan=${h.plan}, daysLeft=${h.daysLeft})`,
      );
    }
  }

  // 执行移除 — 归档而非永久删除，保障可恢复
  let purgedCount = 0;
  if (toRemoveIndices.length > 0) {
    const archived = [];
    const sorted = [...toRemoveIndices].sort((a, b) => b - a);
    for (const idx of sorted) {
      const acc = store.accounts[idx];
      if (!acc) continue;
      log(`purge: archiving [${idx}] ${acc.email} — ${reasons[idx]}`);
      archived.push({
        ...acc,
        _purgeReason: reasons[idx],
        _purgedAt: Date.now(),
      });
      store.accounts.splice(idx, 1);
      if (store.activeIndex === idx) store.activeIndex = -1;
      else if (store.activeIndex > idx) store.activeIndex--;
      purgedCount++;
    }
    // 写入归档文件 (追加模式，永不丢失)
    _archivePurged(store, archived);
    store.save();
  }

  _purgeRunning = false;
  _lastPurgeTime = Date.now();

  const rv = Object.values(reasons);
  const loginDead = rv.filter((r) => r.startsWith("login_dead")).length;
  const disabled = rv.filter((r) => r === "account_disabled").length;
  const probeFree = rv.filter(
    (r) => r.startsWith("probe_free") || r.startsWith("cached_free"),
  ).length;
  const expiredTrial = rv.filter(
    (r) => r.startsWith("expired_trial") || r.startsWith("cached_expired"),
  ).length;
  const msg = `验证完成: ${pwAccounts.length}个账号, 剔除${purgedCount}个 (${loginDead}登录失败, ${disabled}禁用, ${probeFree}Free无Claude, ${expiredTrial}试用过期)`;
  log(`purge: ${msg}`);
  if (!silent) {
    vscode.window.showInformationMessage(`WAM: ${msg}`);
    refreshAll();
  }

  return { purged: purgedCount, total: pwAccounts.length, reasons };
}

// ── 归档被清理的账号 (追加写入，可恢复) ──
function _archivePurged(store, archived) {
  try {
    const archivePath = path.join(
      path.dirname(store._path),
      "_wam_purged.json",
    );
    let existing = [];
    try {
      existing = JSON.parse(fs.readFileSync(archivePath, "utf8"));
    } catch {}
    if (!Array.isArray(existing)) existing = [];
    existing.push(...archived);
    fs.writeFileSync(archivePath, JSON.stringify(existing, null, 2), "utf8");
    log(`purge: archived ${archived.length} accounts to ${archivePath}`);
  } catch (e) {
    log(`purge archive error: ${e.message}`);
  }
}

// _syncToAllUsers removed — 不再跨用户写入文件

// ── 完整切号流程 (v8.0 — 道法自然: 预热快速路径 + 无感热替换) ──
// 切号分两条路径:
//   快速路径: 预热Token命中 → 跳过Firebase登录 → 直接注入 (目标<3s)
//   标准路径: Firebase登录 → 注入 (目标<10s, 替代旧版26s)
async function switchToAccount(email, password) {
  log(`switch: ${email}`);
  const t0 = Date.now();

  // ── 快速路径: 检查预热Token缓存 (道法自然: 弹药已备好, 一触即发) ──
  let idToken = null;
  const emailKey = email.toLowerCase();
  if (
    _prewarmedToken &&
    _prewarmedToken.email === emailKey &&
    Date.now() - _prewarmedToken.ts < TOKEN_CACHE_TTL
  ) {
    idToken = _prewarmedToken.idToken;
    log(
      `switch: ⚡ pre-warmed token HIT (${Math.round((Date.now() - _prewarmedToken.ts) / 1000)}s old) [${Date.now() - t0}ms]`,
    );
    _prewarmedToken = null; // 一次性消费
  }

  // ── 标准路径: 检查通用Token缓存 ──
  if (!idToken) {
    const cached = _tokenCache.get(emailKey);
    if (cached && cached.expiresAt > Date.now()) {
      idToken = cached.idToken;
      log(`switch: token cache HIT [${Date.now() - t0}ms]`);
    }
  }

  // ── 兜底路径: Firebase登录 ──
  if (!idToken) {
    const loginResult = await firebaseLogin(email, password);
    if (!loginResult.ok) {
      const err = loginResult.error || "";
      log(`switch FAIL login: ${err} [${Date.now() - t0}ms]`);
      if (/INVALID|NOT_FOUND|DISABLED|WRONG/.test(err)) {
        const idx = _store?.accounts.findIndex(
          (a) => a.email.toLowerCase() === emailKey,
        );
        if (idx >= 0) {
          const deadAcc = _store.accounts[idx];
          log(`switch: archiving dead account [${idx}] ${email} (${err})`);
          _archivePurged(_store, [
            {
              ...deadAcc,
              _purgeReason: `switch_dead: ${err}`,
              _purgedAt: Date.now(),
            },
          ]);
          _store.remove(idx);
          vscode.window.showWarningMessage(
            `WAM: 已归档无效账号 ${email} (${err})，可从_wam_purged.json恢复`,
          );
        }
      }
      return {
        ok: false,
        error: `登录失败: ${err}`,
        ms: Date.now() - t0,
        permanent: /INVALID|NOT_FOUND|DISABLED|WRONG/.test(err),
      };
    }
    idToken = loginResult.idToken;
    _tokenCache.set(emailKey, {
      idToken,
      expiresAt: Date.now() + TOKEN_CACHE_TTL,
    });
    log(
      `switch: login OK via ${loginResult.channel} (${idToken.length}ch) [${Date.now() - t0}ms]`,
    );
  }

  // ── 注入 (v8: 无感热替换, 不中断对话) ──
  const injectResult = await injectAuth(idToken);
  const ms = Date.now() - t0;
  if (!injectResult.ok) {
    log(`switch FAIL inject: ${JSON.stringify(injectResult.error)} [${ms}ms]`);
    // 注入失败可能是token过期, 清除缓存让下次重新登录
    _tokenCache.delete(emailKey);
    return {
      ok: false,
      error: `注入失败: ${JSON.stringify(injectResult.error)}`,
      ms,
    };
  }
  log(
    `switch OK: ${injectResult.account} apiKey=${(injectResult.apiKey || "").substring(0, 20)}... ${ms}ms`,
  );
  _lastSwitchTime = Date.now();
  _writeInstanceClaim(email);
  try {
    fs.mkdirSync(WAM_DIR, { recursive: true });
    fs.writeFileSync(
      RESULT_FILE,
      JSON.stringify({
        ok: true,
        ts: Date.now(),
        email,
        account: injectResult.account,
        apiKey: (injectResult.apiKey || "").substring(0, 25) + "...",
        sessionId: injectResult.sessionId,
      }),
    );
  } catch {}
  return {
    ok: true,
    account: injectResult.account,
    apiKey: injectResult.apiKey,
    ms,
  };
}

// ── v8: Token预热引擎 — 道法自然: 不等耗尽再行动, 提前备好弹药 ──
// 当预判候选被选中时, 立即在后台获取其Firebase idToken并缓存
// 切号时直接使用, 跳过~10s的Firebase登录, 实现<3s无感切换
async function _prewarmCandidateToken(candidateIndex) {
  if (candidateIndex < 0 || !_store) return;
  const acc = _store.get(candidateIndex);
  if (!acc || !acc.password) return;
  const emailKey = acc.email.toLowerCase();

  // 如果已有有效缓存, 不重复预热
  const cached = _tokenCache.get(emailKey);
  if (cached && cached.expiresAt > Date.now() + 300000) {
    // 至少还有5分钟有效期
    _prewarmedToken = {
      email: emailKey,
      idToken: cached.idToken,
      ts: cached.expiresAt - TOKEN_CACHE_TTL,
    };
    log(`🔥 prewarm: ${acc.email.substring(0, 20)} already cached`);
    return;
  }

  // 后台异步获取 (不阻塞主流程)
  try {
    log(`🔥 prewarm: firing for ${acc.email.substring(0, 20)}...`);
    const loginResult = await firebaseLogin(acc.email, acc.password);
    if (loginResult.ok) {
      _prewarmedToken = {
        email: emailKey,
        idToken: loginResult.idToken,
        ts: Date.now(),
      };
      _tokenCache.set(emailKey, {
        idToken: loginResult.idToken,
        expiresAt: Date.now() + TOKEN_CACHE_TTL,
      });
      log(
        `🔥 prewarm: OK for ${acc.email.substring(0, 20)} (${loginResult.idToken.length}ch)`,
      );
    } else {
      log(
        `🔥 prewarm: FAIL for ${acc.email.substring(0, 20)}: ${loginResult.error}`,
      );
    }
  } catch (e) {
    log(`🔥 prewarm: error ${acc.email.substring(0, 20)}: ${e.message}`);
  }
}

// ============================================================
// 实时额度监测引擎 — 反者道之动
// 活跃账号快速监测(3s) + 全量后台扫描(45s)
// 额度变动 → 标记使用中 → 自动切号 → 变动停止 → 标记消失
// 引擎生命周期: _ensureEngines() 按需启动 / _stopEngines() 安全停止
// monitor 与 scan 各自独立, 互不干扰:
//   - monitor 只管活跃账号, scan 只管非活跃账号 (disjoint sets)
//   - 两者共享 _quotaFetchCooldown (per-account rate limit) 避免重复请求
//   - _switching flag 是唯一互斥点: 切号时两者都暂停
// ============================================================

function _ensureEngines() {
  if (!_store || !isWamMode()) return;
  // monitor: setTimeout 链式循环 (非 setInterval, 避免堆积)
  if (!_monitorTimer) {
    const monitorInterval = () =>
      Date.now() < _burstUntil ? BURST_MS : MONITOR_FAST_MS;
    const scheduleMonitor = () => {
      _monitorTimer = setTimeout(async () => {
        await monitorActiveQuota();
        if (_monitorTimer) scheduleMonitor(); // 仍活跃则继续
      }, monitorInterval());
    };
    scheduleMonitor();
    log("engine: monitor started");
  }
  // scan: setInterval 定时触发 (scanBackgroundQuota 自带 _scanRunning 防重入)
  if (!_scanTimer) {
    _scanTimer = setInterval(() => scanBackgroundQuota(), SCAN_SLOW_MS);
    // 首次立即触发一轮
    setTimeout(() => scanBackgroundQuota(), 2000);
    log("engine: scan started");
  }
}

function _stopEngines() {
  if (_monitorTimer) {
    clearTimeout(_monitorTimer);
    _monitorTimer = null;
    log("engine: monitor stopped");
  }
  if (_scanTimer) {
    clearInterval(_scanTimer);
    _scanTimer = null;
    log("engine: scan stopped");
  }
}

// 活跃账号实时监测 (快速循环, 每MONITOR_FAST_MS)
async function monitorActiveQuota() {
  if (!_store || _switching || _monitorActive || !isWamMode()) return;
  _monitorActive = true;
  _totalMonitorCycles++;

  try {
    const activeI = _store.activeIndex;
    if (activeI < 0) {
      _monitorActive = false;
      return;
    }
    const acc = _store.get(activeI);
    if (!acc || !acc.password) {
      _monitorActive = false;
      return;
    }

    const result = await fetchAccountQuota(acc.email, acc.password);
    if (!result.ok) {
      log(`monitor: ${acc.email.substring(0, 20)} fetch fail: ${result.error}`);
      _monitorActive = false;
      return;
    }

    const emailKey = acc.email.toLowerCase();
    const prev = _quotaSnapshots.get(emailKey);
    const now = Date.now();
    _quotaSnapshots.set(emailKey, {
      daily: result.daily,
      weekly: result.weekly,
      ts: now,
    });
    _snapshotDirty = true;
    _schedulePersist();

    // ── 额度变化检测 v7.1 — 消息锚定: 任意波动→立即切号 ──
    if (prev) {
      const dDelta = prev.daily - result.daily;
      const wDelta = prev.weekly - result.weekly;
      const hasFluctuation =
        dDelta > CHANGE_THRESHOLD || wDelta > CHANGE_THRESHOLD;
      const autoRotate = vscode.workspace
        .getConfiguration("wam")
        .get("autoRotate", true);
      const drought = isWeeklyDrought();

      if (hasFluctuation) {
        _totalChangesDetected++;
        _consecutiveChanges++;
        _burstUntil = Date.now() + BURST_DURATION;
        _store.markInUse(acc.email); // 消息锚定: 波动即标记, 不等累积
        log(
          `📊 D${prev.daily}→${result.daily}(Δ${dDelta.toFixed(1)}) W${prev.weekly}→${result.weekly}(Δ${wDelta.toFixed(1)}) ${acc.email.substring(0, 25)} [×${_consecutiveChanges}]`,
        );
        broadcastMessage({
          type: "quotaChange",
          email: acc.email,
          prevD: prev.daily,
          curD: result.daily,
          prevW: prev.weekly,
          curW: result.weekly,
        });

        // ── 消息锚定核心: 波动=有人发消息→立即切到新账号, 确保下条消息用新号 ──
        // v7.3: 自动切号冷却 — 上次切号15s内不再触发, 避免连续切号风暴
        const switchCooldown = Date.now() - _lastSwitchTime < 15000;
        if (autoRotate && !_switching && !switchCooldown) {
          let bestI = _predictiveCandidate >= 0 ? _predictiveCandidate : -1;
          if (bestI >= 0) {
            const candAcc = _store.get(bestI);
            if (
              !candAcc ||
              !candAcc.password ||
              _isClaimedByOther(candAcc.email)
            )
              bestI = -1;
          }
          if (bestI < 0) bestI = _store.getBestIndex(activeI, true);

          if (bestI >= 0) {
            const bestAcc = _store.get(bestI);
            log(
              `⚡ 消息锚定切号: D${result.daily}%·W${result.weekly}% → ${bestAcc.email.substring(0, 20)}${_predictiveCandidate >= 0 ? " [预判]" : ""}`,
            );
            _switching = true;
            _switchingStartTime = Date.now();
            try {
              const switchResult = await switchToAccount(
                bestAcc.email,
                bestAcc.password,
              );
              if (switchResult.ok) {
                _store.activeIndex = bestI;
                _store.switchCount++;
                _lastSwitchTime = Date.now();
                _store.save();
                _quotaSnapshots.delete(bestAcc.email.toLowerCase());
                _snapshotDirty = true;
                _schedulePersist();
                _burstUntil = Date.now() + BURST_DURATION;
                _consecutiveChanges = 0;
                // 切号后立即预选下一个候选 (零延迟准备) + v8: 立即预热Token
                _predictiveCandidate = _store.getBestIndex(bestI, true);
                if (_predictiveCandidate >= 0) {
                  log(
                    `🔮 预选下一个: → ${_store.get(_predictiveCandidate).email.substring(0, 20)}`,
                  );
                  _prewarmCandidateToken(_predictiveCandidate); // v8: 后台预热, 不阻塞
                }
                setTimeout(() => monitorActiveQuota(), 1500);
                vscode.window.showInformationMessage(
                  `WAM: 消息锚定 → 已切换到 ${switchResult.account}`,
                );
                refreshAll();
              } else {
                log(`auto-switch FAIL: ${switchResult.error}`);
                vscode.window.showWarningMessage(
                  `WAM: 切换失败 — ${switchResult.error}`,
                );
                _predictiveCandidate = -1;
              }
            } finally {
              _switching = false;
            }
          } else {
            log(`消息锚定: 波动检测但无可用账号, 继续使用当前号`);
          }
        }
      } else {
        _consecutiveChanges = 0;
      }

      // ── 预判候选: 额度<25%时提前预选, 波动时零延迟切入 ──
      const effQuota = drought
        ? result.daily
        : Math.min(result.daily, result.weekly);
      if (
        effQuota < PREDICTIVE_THRESHOLD &&
        _predictiveCandidate < 0 &&
        autoRotate
      ) {
        _predictiveCandidate = _store.getBestIndex(activeI, true);
        if (_predictiveCandidate >= 0) {
          log(
            `🔮 预判: 额度${effQuota.toFixed(0)}%<${PREDICTIVE_THRESHOLD}%, 预选→${_store.get(_predictiveCandidate).email.substring(0, 20)}`,
          );
          _prewarmCandidateToken(_predictiveCandidate); // v8: 立即预热Token, 切号时零延迟
        }
      }
      if (effQuota >= PREDICTIVE_THRESHOLD) _predictiveCandidate = -1;

      // ── 耗尽保护: 额度极低时强制切号 (即使无波动, 防止卡死) ──
      const isExhausted = drought
        ? result.daily < AUTO_SWITCH_THRESHOLD
        : Math.min(result.daily, result.weekly) < AUTO_SWITCH_THRESHOLD;

      const exhaustCooldown = Date.now() - _lastSwitchTime < 15000;
      if (isExhausted && autoRotate && !_switching && !exhaustCooldown) {
        const hrsToReset = hoursUntilDailyReset();

        if (
          result.daily < AUTO_SWITCH_THRESHOLD &&
          hrsToReset <= WAIT_RESET_HOURS
        ) {
          log(
            `⏳ Daily耗尽(${result.daily}%) 但${hrsToReset.toFixed(1)}h后重置 → 等待`,
          );
        } else if (
          !drought &&
          result.daily >= AUTO_SWITCH_THRESHOLD &&
          result.weekly < AUTO_SWITCH_THRESHOLD &&
          hoursUntilWeeklyReset() <= WAIT_RESET_HOURS
        ) {
          log(
            `⏳ Weekly耗尽(${result.weekly}%) 但${hoursUntilWeeklyReset().toFixed(1)}h后重置 → 等待`,
          );
        } else {
          const reason = drought
            ? `Daily耗尽(${result.daily}%)`
            : result.weekly < AUTO_SWITCH_THRESHOLD
              ? `Weekly耗尽(${result.weekly}%)`
              : `Daily耗尽(${result.daily}%)`;
          let bestI =
            _predictiveCandidate >= 0
              ? _predictiveCandidate
              : _store.getBestIndex(activeI, true);
          if (bestI >= 0) {
            const bestAcc = _store.get(bestI);
            log(`⚡ 耗尽保护: ${reason} → ${bestAcc.email.substring(0, 20)}`);
            _switching = true;
            _switchingStartTime = Date.now();
            try {
              const sr = await switchToAccount(bestAcc.email, bestAcc.password);
              if (sr.ok) {
                _store.activeIndex = bestI;
                _store.switchCount++;
                _lastSwitchTime = Date.now();
                _predictiveCandidate = _store.getBestIndex(bestI, true);
                if (_predictiveCandidate >= 0)
                  _prewarmCandidateToken(_predictiveCandidate); // v8: 预热下一个
                _store.save();
                _quotaSnapshots.delete(bestAcc.email.toLowerCase());
                _snapshotDirty = true;
                _schedulePersist();
                _burstUntil = Date.now() + BURST_DURATION;
                setTimeout(() => monitorActiveQuota(), 1500);
                vscode.window.showInformationMessage(
                  `WAM: ${reason} → 切换到 ${sr.account}`,
                );
                refreshAll();
              } else {
                log(`exhaust-switch FAIL: ${sr.error}`);
                _predictiveCandidate = -1;
              }
            } finally {
              _switching = false;
            }
          } else {
            log(`耗尽保护: ${reason}, 无可用账号`);
            vscode.window.showWarningMessage(`WAM: ${reason}，无空闲账号`);
          }
        }
      }
    }

    // 节流落盘: 每30秒最多保存一次 (监测循环3-5s但磁盘写入无需那么频繁)
    if (!_lastMonitorSaveTs || Date.now() - _lastMonitorSaveTs > 30000) {
      _store.save();
      _lastMonitorSaveTs = Date.now();
    }
    updateStatusBar();
  } catch (e) {
    log(`monitor error: ${e.message}`);
  } finally {
    _monitorActive = false;
  }
}

// 后台全量扫描 (慢速, 每轮扫描SCAN_BATCH_SIZE个账号)
async function scanBackgroundQuota() {
  if (!_store || _scanRunning || _switching || !isWamMode()) return;
  _scanRunning = true;

  try {
    const pwAccounts = _store.accounts.filter((a) => a.password);
    if (pwAccounts.length === 0) {
      _scanRunning = false;
      return;
    }

    // 优先扫描未检查账号 (planEnd=0 或 lastChecked=0)
    const uncheckedAccs = pwAccounts.filter((a) => {
      const u = a.usage || {};
      return !u.planEnd || !u.lastChecked;
    });
    let batch;
    if (uncheckedAccs.length > 0) {
      batch = uncheckedAccs.slice(0, SCAN_BATCH_SIZE);
      log(`scan: prioritizing ${uncheckedAccs.length} unchecked accounts`);
    } else {
      // 常规轮询偏移
      if (_scanOffset >= pwAccounts.length) _scanOffset = 0;
      batch = pwAccounts.slice(_scanOffset, _scanOffset + SCAN_BATCH_SIZE);
      _scanOffset += SCAN_BATCH_SIZE;
    }

    let scanned = 0,
      changed = 0;
    for (const acc of batch) {
      if (_switching) break;
      // 跳过当前活跃账号(已由快速监测覆盖)
      const activeAcc =
        _store.activeIndex >= 0 ? _store.get(_store.activeIndex) : null;
      if (
        activeAcc &&
        acc.email.toLowerCase() === activeAcc.email.toLowerCase()
      )
        continue;

      // 反者道之动: 先读存储基线, 再fetch(fetch会更新acc.usage)
      const emailKey = acc.email.toLowerCase();
      const prev = _quotaSnapshots.get(emailKey);
      const storedD = acc.usage?.daily?.remaining;
      const storedW = acc.usage?.weekly?.remaining;

      try {
        const result = await fetchAccountQuota(acc.email, acc.password);
        if (result.ok) {
          _quotaSnapshots.set(emailKey, {
            daily: result.daily,
            weekly: result.weekly,
            ts: Date.now(),
          });
          _snapshotDirty = true;

          // 基线: 优先用快照(精确), 其次用存储值(首次扫描兜底)
          const baseD = prev ? prev.daily : storedD != null ? storedD : -1;
          const baseW = prev ? prev.weekly : storedW != null ? storedW : -1;

          if (baseD >= 0 && baseW >= 0) {
            const dDelta = baseD - result.daily;
            const wDelta = baseW - result.weekly;
            if (
              Math.abs(dDelta) > CHANGE_THRESHOLD ||
              Math.abs(wDelta) > CHANGE_THRESHOLD
            ) {
              _store.markInUse(acc.email);
              changed++;
              const src = prev ? "" : "(baseline)";
              log(
                `scan: ${acc.email.substring(0, 25)} CHANGED${src} D${baseD}→${result.daily}(Δ${dDelta.toFixed(1)}) W${baseW}→${result.weekly}(Δ${wDelta.toFixed(1)}) → 标记使用中`,
              );
            }
          }
          scanned++;
        }
      } catch {}

      await new Promise((r) => setTimeout(r, 400));
    }
    _schedulePersist();

    // 合并其他实例写入的in-use标记 (反者道之动: 不独占, 共享感知)
    _loadInUse(_store);

    // 清理已冷却的使用中标记
    const now = Date.now();
    let expiredCount = 0;
    for (const [email, info] of _store._inUse) {
      if (now - info.lastChange > INUSE_COOLDOWN_MS) {
        _store._inUse.delete(email);
        expiredCount++;
        log(
          `inUse expired: ${email.substring(0, 25)} (${Math.round((now - info.lastChange) / 1000)}s idle)`,
        );
      }
    }
    if (expiredCount > 0) {
      _inUseDirty = true;
      _schedulePersist();
    }

    if (scanned > 0 || changed > 0) {
      log(
        `scan: batch[${_scanOffset - SCAN_BATCH_SIZE}+${batch.length}] ${scanned}ok ${changed}changed inUse=${_store._inUse.size}`,
      );
    }
    _store.save();
    refreshAll();
  } catch (e) {
    log(`scan error: ${e.message}`);
  } finally {
    _scanRunning = false;
  }
}

// ── 批量刷新缺失有效期的账号 (强制扫描所有planEnd=0或从未检查的账号) ──
let _expiryScanning = false;
async function scanMissingExpiry() {
  if (!_store || _expiryScanning) {
    log("scanExpiry: already running");
    return { scanned: 0, fetched: 0, failed: 0 };
  }
  _expiryScanning = true;
  const targets = [];
  for (let i = 0; i < _store.accounts.length; i++) {
    const a = _store.accounts[i];
    if (!a.password) continue;
    const u = a.usage || {};
    const pe = u.planEnd || 0;
    const lc = u.lastChecked || 0;
    // 目标: planEnd缺失 或 从未检查过
    if (pe === 0 || lc === 0) targets.push(i);
  }
  log(`scanExpiry: ${targets.length} accounts missing planEnd/never checked`);
  if (targets.length === 0) {
    _expiryScanning = false;
    return { scanned: 0, fetched: 0, failed: 0 };
  }
  broadcastMessage({
    type: "toast",
    text: `正在刷新 ${targets.length} 个账号有效期...`,
  });

  let fetched = 0,
    failed = 0;
  for (const idx of targets) {
    if (_switching) break;
    const acc = _store.accounts[idx];
    if (!acc) continue;
    try {
      const result = await fetchAccountQuota(acc.email, acc.password);
      if (result.ok) {
        fetched++;
        const pe2 = acc.usage?.planEnd || 0;
        log(
          `scanExpiry: ${acc.email.substring(0, 25)} OK D${result.daily} W${result.weekly} planEnd=${pe2 > 0 ? new Date(pe2).toISOString().slice(0, 10) : "NONE"}`,
        );
      } else {
        failed++;
        log(`scanExpiry: ${acc.email.substring(0, 25)} FAIL ${result.error}`);
      }
    } catch (e) {
      failed++;
      log(`scanExpiry: ${acc.email.substring(0, 25)} ERR ${e.message}`);
    }
    // 进度广播 (每5个更新一次)
    if ((fetched + failed) % 5 === 0) {
      broadcastMessage({
        type: "toast",
        text: `有效期刷新: ${fetched + failed}/${targets.length} (${fetched}成功 ${failed}失败)`,
      });
      _store.save();
      refreshAll();
    }
    await new Promise((r) => setTimeout(r, 400));
  }

  _store.save();
  _expiryScanning = false;
  const msg = `有效期刷新完成: ${targets.length}个目标, ${fetched}成功, ${failed}失败`;
  log(`scanExpiry: ${msg}`);
  vscode.window.showInformationMessage(`WAM: ${msg}`);
  refreshAll();
  return { scanned: targets.length, fetched, failed };
}

function updateStatusBar() {
  if (!_statusBarItem || !_store) return;
  // v7.4: 官方模式下最小化显示 — 不泄露账号/额度/池子信息
  if (_mode === "official") {
    _statusBarItem.text = "$(key) 官方模式";
    _statusBarItem.tooltip =
      "WAM v10.0 [官方模式] — 所有切号功能已停止\n点击打开管理面板，可切回WAM模式";
    return;
  }
  const s = _store.getPoolStats();
  const activeAcc =
    _store.activeIndex >= 0 ? _store.get(_store.activeIndex) : null;
  const inUseCount = _store._inUse.size;
  const droughtTag = s.drought ? "[旱]" : "";
  if (activeAcc) {
    const h = _store.getHealth(activeAcc);
    const liveD = Math.round(h.daily);
    const liveW = Math.round(h.weekly);
    const inUseTag = inUseCount > 0 ? ` [${inUseCount}占]` : "";
    const waitTag = s.waiting > 0 ? ` ${s.waiting}待` : "";
    const monTag = _monitorActive ? "$(sync~spin)" : "$(zap)";
    _statusBarItem.text = `${monTag}${droughtTag} D${liveD}%·W${liveW}% ${s.available}/${s.pwCount}号${inUseTag}${waitTag}`;
    _statusBarItem.tooltip =
      `WAM v10.0 [WAM切号]${s.drought ? " [🏜️Weekly干旱模式·只看D]" : ""}\n` +
      `活跃: ${activeAcc.email}\n${h.plan}\n` +
      `号池: ${s.available}可用 · ${s.exhausted}耗尽 · ${s.waiting}等重置\n` +
      (s.drought
        ? `⚠️ Weekly全面耗尽 — 自动切号仅看Daily，避免无效轮转\n`
        : "") +
      `日重置: ${s.hrsToDaily.toFixed(1)}h后 · 周重置: ${s.hrsToWeekly.toFixed(1)}h后\n` +
      `使用中: ${inUseCount}个 · 切换: ${s.switches}次\n` +
      `监测: ${_totalMonitorCycles}轮 · ${_totalChangesDetected}次变动`;
  } else {
    _statusBarItem.text = `$(zap) ${s.pwCount}号`;
    _statusBarItem.tooltip = `WAM v10.0 [WAM切号] · 未选择活跃账号\n日重置: ${s.hrsToDaily.toFixed(1)}h后 · 周重置: ${s.hrsToWeekly.toFixed(1)}h后`;
  }
}

function refreshAll() {
  if (_sidebarProvider) _sidebarProvider.refresh();
  if (_editorPanel) _editorPanel.webview.html = buildHtml(_store);
  updateStatusBar();
}

// ============================================================
// 消息处理 (sidebar + editor panel 共用)
// ============================================================
async function handleWebviewMessage(msg) {
  switch (msg.type) {
    case "switch": {
      // 手动切号: 无任何限制 (不检查in-use)
      // v7.4: 官方模式下不自动翻转
      if (_mode === "official") {
        vscode.window.showWarningMessage(
          "WAM: 官方模式下无法切号，请先切回WAM模式",
        );
        return;
      }
      const acc = _store.get(msg.index);
      if (!acc || !acc.password) return;
      // v7.3: 手动抢占机制 — 如果_switching已超过30s, 强制释放锁允许手动切号
      if (_switching) {
        const lockAge = Date.now() - _switchingStartTime;
        if (lockAge < 30000) {
          vscode.window.showWarningMessage(
            `WAM: 正在切换中(${Math.round(lockAge / 1000)}s)...请稍候`,
          );
          return;
        }
        log(
          `switch: 手动抢占 — 强制释放超时锁(${Math.round(lockAge / 1000)}s)`,
        );
        _switching = false;
      }
      _switching = true;
      _switchingStartTime = Date.now();
      broadcastMessage({ type: "switching", index: msg.index });
      try {
        const result = await switchToAccount(acc.email, acc.password);
        if (result.ok) {
          _store.activeIndex = msg.index;
          _store.switchCount++;
          _store.clearInUse(acc.email);
          _writeInstanceClaim(acc.email);
          _quotaSnapshots.delete(acc.email.toLowerCase()); // 重置快照基准
          _snapshotDirty = true;
          _schedulePersist();
          _store.save();
          vscode.window.showInformationMessage(
            `WAM: 已手动切换到 ${result.account} (${result.ms}ms)`,
          );
          _ensureEngines();
        } else {
          vscode.window.showErrorMessage(`WAM: 切换失败 — ${result.error}`);
        }
      } finally {
        _switching = false;
        refreshAll();
      }
      break;
    }
    case "remove": {
      const acc = _store.get(msg.index);
      if (!acc) return;
      const pick = await vscode.window.showWarningMessage(
        `删除 ${acc.email}?`,
        { modal: true },
        "确认删除",
      );
      if (pick === "确认删除") {
        _store.remove(msg.index);
        refreshAll();
      }
      break;
    }
    case "removeBatch": {
      if (!msg.indices || !msg.indices.length) return;
      const pick = await vscode.window.showWarningMessage(
        `批量删除 ${msg.indices.length} 个账号?`,
        { modal: true },
        "确认删除",
      );
      if (pick === "确认删除") {
        const n = _store.removeBatch(msg.indices);
        vscode.window.showInformationMessage(`WAM: 已删除 ${n} 个账号`);
        refreshAll();
      }
      break;
    }
    case "addBatch": {
      const r = _store.addBatch(msg.text);
      let info = `WAM: 添加了 ${r.added} 个账号`;
      if (r.duplicate > 0) info += ` (${r.duplicate}个重复)`;
      if (r.skipped > 0) info += ` (${r.skipped}个无法识别)`;
      if (r.added > 0) vscode.window.showInformationMessage(info);
      else if (r.duplicate > 0)
        vscode.window.showWarningMessage(
          `WAM: ${r.duplicate}个账号已存在，无新增`,
        );
      else
        vscode.window.showWarningMessage(
          `WAM: 无法识别格式，请检查输入 (${r.total}行)`,
        );
      refreshAll();
      break;
    }
    case "refresh": {
      _store.load();
      _store.lastRefresh = Date.now();
      refreshAll();
      break;
    }
    case "autoRotate": {
      // v7.4: 官方模式下智能轮转被禁用(UI按钮也已disabled)
      if (!isWamMode()) {
        vscode.window.showWarningMessage(
          "WAM: 官方模式下智能轮转已禁用，请先切回WAM模式",
        );
        break;
      }
      await doAutoRotate(_store);
      refreshAll();
      break;
    }
    case "copyAccount": {
      const acc2 = _store.get(msg.index);
      if (acc2) {
        const text = acc2.password
          ? `${acc2.email}:${acc2.password}`
          : acc2.email;
        await vscode.env.clipboard.writeText(text);
        broadcastMessage({ type: "toast", text: "已复制账号密码" });
      }
      break;
    }
    case "openEditor": {
      openEditorPanel();
      break;
    }
    case "verifyAll": {
      verifyAndPurgeExpired(_store).then(() => refreshAll());
      break;
    }
    case "scanExpiry": {
      scanMissingExpiry().then(() => refreshAll());
      break;
    }
    case "setMode": {
      const newMode = msg.mode === "official" ? "official" : "wam";
      saveMode(newMode);
      if (newMode === "wam") {
        // v7.4: 回切WAM时重启所有后台设施
        _restartBackgroundServices();
        if (_store.activeIndex < 0 && _store.pwCount() > 0) {
          const bestI = _store.getBestIndex(-1, false);
          if (bestI >= 0) {
            const acc = _store.get(bestI);
            if (_switching) {
              log(
                `setMode: 强制释放锁(${Math.round((Date.now() - _switchingStartTime) / 1000)}s)`,
              );
              _switching = false;
            }
            _switching = true;
            _switchingStartTime = Date.now();
            try {
              const result = await switchToAccount(acc.email, acc.password);
              if (result.ok) {
                _store.activeIndex = bestI;
                _store.switchCount++;
                _store.save();
                vscode.window.showInformationMessage(
                  `WAM: WAM模式启动，自动登录 ${result.account}`,
                );
                _ensureEngines();
              }
            } finally {
              _switching = false;
            }
          }
        }
      }
      if (newMode === "official") {
        // v7.4: cleanupThirdPartyState is now async (includes windsurf.logout)
        const cleaned = await cleanupThirdPartyState();
        vscode.window.showInformationMessage(
          `WAM: 官方模式 — WAM会话已登出，${cleaned}项清理完成。请用Windsurf原生登录您自己的账号`,
        );
      }
      refreshAll();
      break;
    }
  }
}

function broadcastMessage(msg) {
  if (_sidebarProvider && _sidebarProvider._view)
    _sidebarProvider._view.webview.postMessage(msg);
  if (_editorPanel) _editorPanel.webview.postMessage(msg);
}

// ============================================================
// WebviewViewProvider — 侧边栏面板
// ============================================================
class WamViewProvider {
  constructor(store) {
    this._store = store;
    this._view = null;
  }
  resolveWebviewView(webviewView) {
    this._view = webviewView;
    webviewView.webview.options = { enableScripts: true };
    webviewView.webview.html = buildHtml(this._store);
    webviewView.webview.onDidReceiveMessage(handleWebviewMessage);
  }
  refresh() {
    if (this._view) this._view.webview.html = buildHtml(this._store);
  }
}

// ============================================================
// 编辑器面板 (中间栏) — 点击状态栏打开
// ============================================================
function openEditorPanel() {
  if (_editorPanel) {
    _editorPanel.reveal();
    return;
  }
  _editorPanel = vscode.window.createWebviewPanel(
    "wam.editor",
    "无感切号 · 账号管理",
    vscode.ViewColumn.One,
    { enableScripts: true, retainContextWhenHidden: true },
  );
  _editorPanel.webview.html = buildHtml(_store);
  _editorPanel.webview.onDidReceiveMessage(handleWebviewMessage);
  _editorPanel.onDidDispose(() => {
    _editorPanel = null;
  });
}

// ============================================================
// 构建HTML (sidebar + editor共用)
// ============================================================
function buildHtml(store) {
  const stats = store.getPoolStats();
  const accounts = store.accounts;
  const activeI = store.activeIndex;

  const allIndices = [];
  for (let i = 0; i < accounts.length; i++) allIndices.push(i);

  const domainCounts = {};
  for (let i = 0; i < accounts.length; i++) {
    const d = accounts[i].email.split("@")[1] || "?";
    domainCounts[d] = (domainCounts[d] || 0) + 1;
  }
  const domainSummary = Object.entries(domainCounts)
    .map(([d, c]) => `${d}(${c})`)
    .join(" ");

  const inUseCount = store._inUse.size;

  let rows = "";
  for (const i of allIndices) {
    const a = accounts[i];
    const h = store.getHealth(a);
    const isActive = i === activeI;
    const inUse = store.isInUse(a.email);
    const domain = a.email.split("@")[1] || "";
    const domainBadge = domain.endsWith(".shop")
      ? "shop"
      : domain.includes("yahoo")
        ? "yh"
        : "o";
    const localPart = a.email.replace(/@.*/, "");
    const emailShort =
      localPart.substring(0, 12) + (localPart.length > 12 ? ".." : "");
    // getHealth() 已融合快照, 是唯一数据源
    const isUnchecked = !h.checked;
    const dPct = isUnchecked
      ? 0
      : Math.max(0, Math.min(100, Math.round(h.daily)));
    const wPct = isUnchecked
      ? 0
      : Math.max(0, Math.min(100, Math.round(h.weekly)));
    const dColor = isUnchecked
      ? "#555"
      : dPct <= 5
        ? "#f44"
        : dPct <= 30
          ? "#ce9178"
          : "#4ec9b0";
    const wColor = isUnchecked
      ? "#555"
      : wPct <= 5
        ? "#f44"
        : wPct <= 30
          ? "#ce9178"
          : "#4ec9b0";
    const liveTag = h.hasSnap
      ? '<span class="live-dot" title="实时数据"></span>'
      : "";
    const cooldownSec = store.getInUseCooldown(a.email);
    const inUseTag = inUse
      ? `<span class="iu">使用中(${cooldownSec}s)</span>`
      : "";
    const uncheckedTag = isUnchecked ? '<span class="uc">未验</span>' : "";
    const planTag =
      h.plan && h.plan !== "Trial"
        ? `<span class="plan-tag">${h.plan}</span>`
        : "";
    // 过期判定: Claude可用性是ground truth, 不再被D/W数字迷惑
    const claudeOk = isClaudeAvailable(h);
    let expiryTag = "";
    if (h.daysLeft > 0) {
      const ec =
        h.daysLeft <= 2 ? "#f44" : h.daysLeft <= 5 ? "#ce9178" : "#4ec9b0";
      expiryTag = `<span class="days" style="color:${ec}" title="Plan到期: ${h.planEnd ? new Date(h.planEnd).toLocaleDateString() : ""}">${h.daysLeft}天</span>`;
    } else if (h.daysLeft < 0) {
      expiryTag =
        '<span class="days" style="color:#ce9178" title="宽限期仍可用">已过期</span>';
    } else if (h.planEnd > 0) {
      expiryTag =
        '<span class="days" style="color:#f44" title="试用已过期·Claude不可用">已过期</span>';
    }
    const claudeTag =
      !claudeOk && h.checked
        ? '<span class="days" style="color:#f44;font-weight:700" title="Claude($$$)模型不可用·仅免费模型">⊘Claude</span>'
        : "";
    const freshTag =
      h.staleMin >= 0 && h.staleMin <= 3
        ? '<span class="fresh">&#8226;</span>'
        : "";

    rows += `
    <div class="row${isActive ? " act" : ""}${inUse ? " in-use" : ""}${!claudeOk && h.checked ? " expired-row" : ""}" data-i="${i}" data-email="${a.email.toLowerCase()}">
      <input type="checkbox" class="chk" data-i="${i}" />
      <span class="dm ${domainBadge}">${domainBadge}</span>
      <span class="em" title="${a.email}">${emailShort}</span>
      ${expiryTag}${planTag}${claudeTag}
      ${freshTag}${liveTag}${inUseTag}${uncheckedTag}
      <span class="qt">
        <span class="mb"><span class="mf" style="width:${dPct}%;background:${dColor}"></span></span>
        <span class="ql" style="color:${dColor}">${isUnchecked ? "D?" : "D" + dPct}</span>
        <span class="mb"><span class="mf" style="width:${isUnchecked ? 0 : wPct}%;background:${wColor}"></span></span>
        <span class="ql" style="color:${wColor}">${isUnchecked ? "W?" : "W" + wPct}</span>
      </span>
      <span class="acts">
        <button class="b sw" onclick="sw(${i})" title="手动切换(无限制)"${_mode === "official" ? ' disabled style="opacity:.3;cursor:not-allowed"' : ""}>&#9889;</button>
        <button class="b cp" onclick="cp(${i})" title="复制账号密码">&#128203;</button>
        <button class="b rm" onclick="rm(${i})" title="删除">&times;</button>
      </span>
    </div>`;
  }

  const checkedCount = stats.pwCount - (stats.unchecked || 0);
  // 干旱模式下用Daily计算池子健康度 (Weekly全是0无意义)
  const poolPct =
    checkedCount > 0
      ? Math.round((stats.drought ? stats.totalD : stats.totalW) / checkedCount)
      : 0;
  const poolColor =
    poolPct >= 60 ? "#4ec9b0" : poolPct >= 30 ? "#ce9178" : "#f44";

  // 监测状态 + 重置倒计时
  const burstActive = Date.now() < _burstUntil;
  const burstSec = burstActive
    ? Math.ceil((_burstUntil - Date.now()) / 1000)
    : 0;
  const monitorStatus = `<div class="monitor-bar${burstActive ? " burst" : ""}">
    <span class="mon-dot${burstActive ? " burst-dot" : ""}"></span>
    <span>消息锚定${burstActive ? "(突发" + burstSec + "s)" : ""}</span>
    <span class="mon-stat">D重置${stats.hrsToDaily.toFixed(1)}h</span>
    <span class="mon-stat">W重置${stats.hrsToWeekly.toFixed(1)}h</span>
    <span class="mon-stat">${inUseCount}占</span>
    <span class="mon-stat">${stats.switches}切</span>
    <span class="mon-stat">${_totalChangesDetected}变</span>
  </div>`;

  // 活跃账号信息
  let activeHtml =
    '<div class="act-info" style="border-color:#555;color:#666">未选择活跃账号</div>';
  if (activeI >= 0 && accounts[activeI]) {
    const aa = accounts[activeI];
    const ah = store.getHealth(aa);
    const liveD = Math.round(ah.daily);
    const liveW = Math.round(ah.weekly);
    const hrsD = stats.hrsToDaily;
    const hrsW = stats.hrsToWeekly;
    const snapAge = ah.hasSnap
      ? `${Math.round((Date.now() - ah.lastChecked) / 1000)}秒前`
      : "无数据";
    // 干旱模式: 有效配额只看Daily (W0是全局问题)
    const effQuota = stats.drought ? liveD : Math.min(liveD, liveW);
    const effColor =
      effQuota < 5
        ? "var(--red)"
        : effQuota < 30
          ? "var(--orange)"
          : "var(--green)";
    const switchHint =
      effQuota < 5
        ? stats.drought
          ? ' · <b style="color:var(--orange)">干旱·D耗尽即切</b>'
          : ' · <b style="color:var(--red)">即将切号</b>'
        : stats.drought
          ? ' · <span style="color:#d29922;font-size:9px">[干旱·只看D]</span>'
          : "";
    const activeClaudeOk = isClaudeAvailable(ah);
    const planExpiryTag =
      ah.daysLeft > 0
        ? ` <span style="color:${ah.daysLeft <= 2 ? "var(--red)" : ah.daysLeft <= 5 ? "var(--orange)" : "var(--green)"}">${ah.daysLeft}天</span>`
        : ah.daysLeft < 0
          ? ' <span style="color:var(--orange)" title="宽限期仍可用">已过期</span>'
          : ah.planEnd > 0
            ? ' <span style="color:var(--red)">已过期</span>'
            : "";
    const activeClaudeTag = !activeClaudeOk
      ? ' <span style="color:var(--red);font-weight:700">⊘Claude不可用</span>'
      : "";
    activeHtml = `<div class="act-info">
      <b>活跃:</b> ${aa.email.substring(0, 28)}
      <span class="tag">${ah.plan}</span>${planExpiryTag}${activeClaudeTag}
      <span style="color:${effColor}">D${liveD}%·W${liveW}%</span>
      <br><small>采样${snapAge} · 日重置${hrsD.toFixed(1)}h · 周重置${hrsW.toFixed(1)}h${switchHint}</small>
    </div>`;
  }

  return `<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
:root{--bg:var(--vscode-editor-background);--fg:var(--vscode-editor-foreground);--border:var(--vscode-panel-border,#2d2d2d);--input-bg:var(--vscode-input-background,#1e1e1e);--input-border:var(--vscode-input-border,#3c3c3c);--btn:var(--vscode-button-background,#0e639c);--btn-h:var(--vscode-button-hoverBackground,#1177bb);--btn2:#264f78;--green:#4ec9b0;--orange:#ce9178;--red:#f44;--blue:#9cdcfe}
*{margin:0;padding:0;box-sizing:border-box}
body{font:12px/1.5 -apple-system,'Segoe UI',sans-serif;background:var(--bg);color:var(--fg);padding:6px 8px;overflow-x:hidden}

.hd{margin-bottom:8px}
.stats-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin:4px 0}
.stat-card{background:#1e1e1e;border:1px solid var(--border);border-radius:6px;padding:8px 10px}
.stat-val{font-size:20px;font-weight:700;letter-spacing:-0.5px}
.stat-label{font-size:10px;color:#888;margin-top:1px}
.pool-bar{height:5px;background:#252525;border-radius:3px;margin:6px 0;overflow:hidden}
.pool-fill{height:100%;border-radius:3px;background:linear-gradient(90deg,${poolColor}88,${poolColor});transition:width .4s}
.st{display:flex;flex-wrap:wrap;gap:8px;font-size:11px;color:#777;margin:4px 0}
.st b{color:#ccc}
.st .ex{color:var(--red)}
.act-info{background:#264f7833;border-left:3px solid var(--blue);padding:4px 8px;border-radius:0 4px 4px 0;margin:6px 0;font-size:11px;color:var(--blue)}
.act-info b{color:var(--blue)}
.act-info .tag{background:#264f78;color:var(--blue);padding:1px 6px;border-radius:3px;font-size:10px;margin-left:4px}

.tb{display:flex;gap:4px;margin:6px 0;flex-wrap:wrap}
.tb button{background:var(--btn2);color:#ccc;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px;transition:background .15s}
.tb button:hover{background:#37669d}
.tb button.primary{background:var(--btn);color:#fff}
.tb button.primary:hover{background:var(--btn-h)}
.tb button.danger{background:#5a1d1d;color:#f88}
.tb button.danger:hover{background:#7a2d2d}


.add-section{margin:6px 0;border:1px solid var(--border);border-radius:6px;overflow:hidden}
.add-header{background:#1a1a1a;padding:4px 8px;font-size:11px;color:#888;cursor:pointer;display:flex;justify-content:space-between}
.add-header:hover{color:#ccc}
.add-body{padding:6px 8px;display:none}
.add-body.open{display:block}
.add-body textarea{width:100%;min-height:60px;background:var(--input-bg);border:1px solid var(--input-border);color:#ccc;padding:6px 8px;border-radius:4px;font-size:11px;outline:none;resize:vertical;font-family:monospace}
.add-body textarea:focus{border-color:var(--btn)}
.add-body textarea::placeholder{color:#555}
.add-body .add-actions{display:flex;gap:4px;margin-top:4px}
.add-body .add-actions button{background:var(--btn);color:#fff;border:none;padding:4px 12px;border-radius:4px;cursor:pointer;font-size:11px}
.add-body .add-actions button:hover{background:var(--btn-h)}
.add-body .add-hint{font-size:10px;color:#555;margin-top:4px}

.sec{display:flex;justify-content:space-between;align-items:center;color:#777;font-size:11px;margin:8px 0 3px;padding-bottom:3px;border-bottom:1px solid var(--border)}
.sec .dm-info{font-size:10px;color:#555}

.row{display:flex;align-items:center;padding:3px 2px;border-bottom:1px solid #1a1a1a;gap:4px;transition:background .1s}
.row:hover{background:#2a2d2e}
.row.act{background:#264f7844;border-left:2px solid var(--blue);padding-left:0}
.row.in-use{background:#3a2a1a44;border-left:2px solid var(--orange)}
.row.switching{opacity:.4;pointer-events:none}
.row.expired-row{opacity:.45;background:#1a0a0a}
.chk{width:14px;height:14px;accent-color:var(--btn);cursor:pointer;flex-shrink:0}
.dm{width:22px;height:16px;border-radius:3px;font-size:9px;font-weight:700;text-align:center;line-height:16px;flex-shrink:0}
.dm.shop{background:#553399;color:#c8a2ff}
.dm.yh{background:#4a1564;color:#d19cff}
.dm.o{background:#333;color:#aaa}
.em{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:11px;cursor:default}
.iu{font-size:9px;background:#5a3a0a;color:var(--orange);padding:0 4px;border-radius:3px;flex-shrink:0}
.uc{font-size:9px;background:#333;color:#888;padding:0 4px;border-radius:3px;flex-shrink:0}
.plan-tag{font-size:9px;background:#1a3a1a;color:#6c6;padding:0 4px;border-radius:3px;flex-shrink:0}
.days{font-size:9px;color:#666;flex-shrink:0}
.qt{display:flex;align-items:center;gap:2px;flex-shrink:0;min-width:100px}
.mb{width:18px;height:4px;background:#252525;border-radius:2px;overflow:hidden;flex-shrink:0}
.mf{display:block;height:100%;border-radius:2px;transition:width .3s}
.ql{font-size:10px;font-weight:600;width:26px;text-align:right}
.acts{display:flex;gap:2px;flex-shrink:0}
.b{width:20px;height:20px;border:none;border-radius:3px;cursor:pointer;font-size:11px;display:flex;align-items:center;justify-content:center;padding:0;transition:all .1s}
.b.sw{background:var(--btn);color:#fff}
.b.sw:hover{background:var(--btn-h);transform:scale(1.1)}
.b.cp{background:#333;color:#aaa}
.b.cp:hover{background:#444;color:#fff}
.b.rm{background:transparent;color:#555;font-size:14px}
.b.rm:hover{color:var(--red)}
.toast{position:fixed;bottom:8px;left:8px;right:8px;background:#264f78;color:#fff;padding:6px 10px;border-radius:4px;font-size:11px;opacity:0;transition:opacity .3s;pointer-events:none;z-index:99}
.toast.show{opacity:1}
.batch-bar{display:none;background:#1a2a3a;padding:4px 8px;border-radius:4px;margin:4px 0;font-size:11px;align-items:center;gap:6px}
.batch-bar.visible{display:flex}
.batch-bar span{color:#9cdcfe}
.batch-bar button{background:#5a1d1d;color:#f88;border:none;padding:2px 10px;border-radius:3px;cursor:pointer;font-size:11px}
.batch-bar button:hover{background:#7a2d2d}
.monitor-bar{display:flex;align-items:center;gap:6px;background:#1a2a1a;border:1px solid #2a3a2a;border-radius:4px;padding:3px 8px;margin:4px 0;font-size:10px;color:#6c6}
.mon-dot{width:6px;height:6px;border-radius:50%;background:#4ec9b0;animation:pulse 2s infinite}
.mon-stat{color:#888;padding:0 3px}
.mode-bar{display:flex;align-items:center;gap:6px;margin:6px 0;padding:5px 8px;background:#1a1a2a;border:1px solid #2a2a3a;border-radius:4px}
.mode-label{font-size:10px;color:#888}
.mode-btn{background:#252525;color:#888;border:1px solid #333;padding:3px 10px;border-radius:4px;cursor:pointer;font-size:11px;transition:all .15s}
.mode-btn:hover{background:#333;color:#ccc}
.mode-btn.wam-on{background:#1a2a1a;color:var(--green);border-color:#2a4a2a}
.mode-btn.off-on{background:#2a1a1a;color:#f88;border-color:#4a2a2a}
.official-banner{background:#2a1a1a;border:1px solid #4a2a2a;border-radius:4px;padding:6px 10px;margin:6px 0;font-size:11px;color:#f88;display:flex;align-items:center;gap:6px}
.official-banner b{color:#faa}
.drought-banner{background:#2a2a1a;border:1px solid #4a4a2a;border-radius:4px;padding:6px 10px;margin:6px 0;font-size:11px;color:#d29922;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.drought-banner b{color:#e8a830}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
.mon-dot.grace{background:#d29922;animation:pulse 1s infinite}
.mon-dot.burst-dot{background:#f44;animation:pulse .5s infinite}
.monitor-bar.burst{background:#2a1a1a;border-color:#4a2a2a;color:#f88}
.live-dot{display:inline-block;width:5px;height:5px;border-radius:50%;background:#4ec9b0;margin:0 2px;flex-shrink:0;animation:pulse 2s infinite}
.fresh{color:#4ec9b0;font-size:14px;line-height:1;flex-shrink:0;margin:0 1px}
.row.quota-flash{animation:qflash .6s}
@keyframes qflash{0%{background:#5a3a0a}100%{background:transparent}}
</style></head><body>

<div class="hd">
  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-val" style="color:${poolColor}">${stats.totalD}D</div>
      <div class="stat-label">日额度总计</div>
    </div>
    <div class="stat-card">
      <div class="stat-val" style="color:${poolColor}">${stats.totalW}W</div>
      <div class="stat-label">周额度总计</div>
    </div>
  </div>
  <div class="pool-bar"><div class="pool-fill" style="width:${poolPct}%"></div></div>
  <div class="st">
    <span><b>${stats.available}</b> 可用</span>
    <span class="${stats.exhausted > 0 ? "ex" : ""}"><b>${stats.exhausted}</b> 耗尽</span>
    ${stats.waiting > 0 ? `<span style="color:#d29922"><b>${stats.waiting}</b> 等重置</span>` : ""}
    <span>切<b>${stats.switches}</b></span>
    <span><b>${stats.pwCount}</b>号</span>
    ${stats.unchecked > 0 ? `<span style="color:#888"><b>${stats.unchecked}</b>未验</span>` : ""}
  </div>
  ${activeHtml}
  ${monitorStatus}
  <div class="mode-bar">
    <span class="mode-label">模式:</span>
    <button class="mode-btn${_mode === "wam" ? " wam-on" : ""}" onclick="setWamMode('wam')">⚡ WAM切号</button>
    <button class="mode-btn${_mode === "official" ? " off-on" : ""}" onclick="setWamMode('official')">&#128273; 官方登录</button>
  </div>
  ${_mode === "official" ? '<div class="official-banner"><b>&#128274; 官方模式 · 万法归宗</b><br>WAM会话已登出 · 切号/监测/心跳/文件监听 — 全部已停止<br>请使用 Windsurf 原生登录 · 点击 WAM切号 恢复</div>' : ""}
  ${stats.drought ? `<div class="drought-banner">&#127964;&#65039; <b>Weekly干旱模式</b> 全池W耗尽·仅靠Daily轮换·周重置${stats.hrsToWeekly.toFixed(1)}h后 · <span style="color:#4ec9b0">不再因W0无效切号</span></div>` : ""}
</div>

<div class="tb">
  <button class="primary" onclick="send('autoRotate')"${_mode === "official" ? ' disabled style="opacity:.4"' : ""}>⚡ 智能轮转</button>
  <button onclick="send('refresh')">&#8635; 刷新</button>
  <button class="danger" onclick="send('verifyAll')">&#128269; 验证清理</button>
  <button onclick="send('scanExpiry')" style="background:#1a3a1a;color:#4ec9b0">&#128197; 刷新有效期</button>
  <button onclick="send('openEditor')">&#9634; 管理面板</button>
</div>

<div class="batch-bar" id="batchBar">
  <span>已选 <b id="batchCount">0</b> 个</span>
  <button onclick="batchDelete()">批量删除</button>
  <button onclick="clearSelection()" style="background:#333;color:#ccc">取消</button>
</div>

<div class="add-section">
  <div class="add-header" onclick="toggleAdd()">
    <span>&#43; 添加账号</span>
    <span id="addArrow">&#9660;</span>
  </div>
  <div class="add-body" id="addBody">
    <textarea id="addInput" placeholder="支持多种格式，每行一个：\nemail:password\nemail password\nemail\tpassword\nemail----password\nemail|password\n密码:邮箱（反向也行）"></textarea>
    <div class="add-actions">
      <button onclick="doAdd()">添加</button>
    </div>
    <div class="add-hint">支持批量粘贴，自动识别各种分隔符格式</div>
  </div>
</div>

<div class="sec">
  <span>&#9660; 账号列表</span>
  <span class="dm-info">${domainSummary}</span>
</div>
<div id="list">${rows}</div>

<div class="toast" id="toast"></div>

<script>
const vscode = acquireVsCodeApi();

function send(type, index) { vscode.postMessage({type, index}); }
function setWamMode(mode) { vscode.postMessage({type:'setMode', mode}); }
function sw(i) { send('switch', i); }
function cp(i) { vscode.postMessage({type:'copyAccount', index:i}); }
function rm(i) { send('remove', i); }

function toggleAdd() {
  const body = document.getElementById('addBody');
  body.classList.toggle('open');
  document.getElementById('addArrow').textContent = body.classList.contains('open') ? '\\u25B2' : '\\u25BC';
}

function doAdd() {
  const ta = document.getElementById('addInput');
  const text = ta.value.trim();
  if (!text) return;
  vscode.postMessage({type:'addBatch', text});
  ta.value = '';
}

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 1500);
}

// 批量选择
function updateBatchBar() {
  const checked = document.querySelectorAll('.chk:checked');
  const bar = document.getElementById('batchBar');
  const cnt = document.getElementById('batchCount');
  cnt.textContent = checked.length;
  bar.classList.toggle('visible', checked.length > 0);
}

function batchDelete() {
  const indices = [...document.querySelectorAll('.chk:checked')].map(c => parseInt(c.dataset.i));
  if (indices.length === 0) return;
  vscode.postMessage({type:'removeBatch', indices});
}

function clearSelection() {
  document.querySelectorAll('.chk:checked').forEach(c => c.checked = false);
  updateBatchBar();
}

document.addEventListener('change', e => {
  if (e.target.classList.contains('chk')) updateBatchBar();
});

window.addEventListener('message', e => {
  const msg = e.data;
  if (msg.type === 'switching') {
    const row = document.querySelector('.row[data-i="' + msg.index + '"]');
    if (row) { row.classList.add('switching'); showToast('正在切换...'); }
  }
  if (msg.type === 'toast') showToast(msg.text);
  if (msg.type === 'quotaChange') {
    // 额度变动: 闪烁对应行, 显示变动信息
    const email = (msg.email || '').toLowerCase();
    const row = document.querySelector('.row[data-email="' + email + '"]');
    if (row) {
      row.classList.add('quota-flash', 'in-use');
      setTimeout(() => row.classList.remove('quota-flash'), 700);
    }
    showToast('D' + msg.prevD + '\\u2192' + msg.curD + ' W' + msg.prevW + '\\u2192' + msg.curW + ' \\u26A1\\u81EA\\u52A8\\u5207\\u53F7');
  }
});
</script>
</body></html>`;
}

// ============================================================
// Auto-rotate
// ============================================================
async function doAutoRotate(store) {
  const current = store.activeIndex;
  const drought = isWeeklyDrought();
  if (current >= 0) {
    const h = store.getHealth(store.get(current));
    if (isAccountSwitchable(h)) {
      const hrsD = hoursUntilDailyReset();
      const hrsW = hoursUntilWeeklyReset();
      const droughtTag = drought ? " [🏜️干旱模式·只看D]" : "";
      vscode.window.showInformationMessage(
        `WAM: 当前账号可用 D${Math.round(h.daily)}%·W${Math.round(h.weekly)}% | 日重置${hrsD.toFixed(1)}h·周重置${hrsW.toFixed(1)}h${droughtTag}`,
      );
      return;
    }
  }
  const bestI = store.getBestIndex(current);
  if (bestI < 0) {
    const hrsD = hoursUntilDailyReset();
    const hrsW = hoursUntilWeeklyReset();
    const msg = drought
      ? `WAM: 🏜️干旱模式·D+W全面耗尽 (日重置${hrsD.toFixed(1)}h后·周重置${hrsW.toFixed(1)}h后)`
      : `WAM: 无可用账号 (日重置在${hrsD.toFixed(1)}h后)`;
    vscode.window.showWarningMessage(msg);
    return;
  }
  const acc = store.get(bestI);
  // v7.3.1: 智能轮转也需要抢占检查
  if (_switching) {
    const lockAge = Date.now() - _switchingStartTime;
    if (lockAge < 30000) {
      vscode.window.showWarningMessage(
        `WAM: 正在切换中(${Math.round(lockAge / 1000)}s)...请稍候`,
      );
      return;
    }
    log(
      `autoRotate: 手动抢占 — 强制释放超时锁(${Math.round(lockAge / 1000)}s)`,
    );
    _switching = false;
  }
  _switching = true;
  _switchingStartTime = Date.now();
  try {
    const result = await switchToAccount(acc.email, acc.password);
    if (result.ok) {
      store.activeIndex = bestI;
      store.switchCount++;
      const droughtTag = drought ? " [干旱·D轮换]" : "";
      vscode.window.showInformationMessage(
        `WAM: 智能轮转到 ${result.account} (${result.ms}ms)${droughtTag}`,
      );
      _ensureEngines();
    } else {
      vscode.window.showErrorMessage(`WAM: 轮转失败 — ${result.error}`);
    }
  } finally {
    _switching = false;
  }
}

// ============================================================
// 文件监听 — 外部bridge兼容
// ============================================================
function startFileWatcher() {
  try {
    fs.mkdirSync(WAM_DIR, { recursive: true });
  } catch {}
  _watcher = fs.watch(WAM_DIR, (eventType, filename) => {
    if (filename === "oneshot_token.json" && eventType === "rename") {
      setTimeout(async () => {
        // v7.3.1: 真原子性 — renameSync是文件系统级原子操作, 只有一个实例能成功rename
        const claimFile = path.join(WAM_DIR, `_claimed_${_instanceId}.json`);
        let rawData;
        try {
          fs.renameSync(TOKEN_FILE, claimFile); // 原子rename: 仅第一个成功, 其余ENOENT
          rawData = fs.readFileSync(claimFile, "utf8");
          try {
            fs.unlinkSync(claimFile);
          } catch {}
        } catch {
          return;
        } // rename失败 = 其他实例已抢走
        if (!isWamMode()) {
          log("watcher: skip injection (official mode)");
          return;
        }
        try {
          const data = JSON.parse(rawData);
          if (!data.idToken) return;
          log(`watcher: external token for ${data.email || "?"}`);
          const result = await injectAuth(data.idToken);
          fs.writeFileSync(
            RESULT_FILE,
            JSON.stringify({
              ok: result.ok,
              ts: Date.now(),
              email: data.email || "",
              account: result.account || "",
              apiKey: result.ok
                ? (result.apiKey || "").substring(0, 25) + "..."
                : "",
              error: result.error || undefined,
              sessionId: result.sessionId || "",
            }),
          );
          log(
            `watcher: inject ${result.ok ? "OK" : "FAIL"}: ${result.account || result.error}`,
          );
          refreshAll();
        } catch (e) {
          log(`watcher error: ${e.message}`);
        }
      }, 500);
    }
  });
  _watcher.on("error", () => {
    _watcher = null;
    setTimeout(startFileWatcher, 5000);
  });
  log("watcher: started");
}

// ============================================================
// 激活 — v6.0 · 实时额度监测 · 重置感知 · 反者道之动
// ============================================================
function activate(context) {
  log(
    `activate v9.1.0-五感模式 — inst=${_instanceId} 纯热替换·绝不logout·绝不杀agent·Token预热·Rate-limit拦截`,
  );

  const gsPath =
    context.globalStorageUri?.fsPath ||
    path.join(
      os.homedir(),
      "AppData",
      "Roaming",
      "Windsurf",
      "User",
      "globalStorage",
    );
  _store = new AccountStore(gsPath);
  _loadSnapshots(); // 恢复上次快照 (首次扫描就能检测变化)
  _loadInUse(_store); // 恢复使用中标记 (重启不丢失)
  loadMode();
  log(
    `startup mode: ${_mode} | snapshots: ${_quotaSnapshots.size} | inUse: ${_store._inUse.size}`,
  );

  // 检测活跃账号 (从marker文件)
  const markerPaths = [path.join(WAM_DIR, "_active_account.txt")];
  for (const mp of markerPaths) {
    try {
      if (fs.existsSync(mp)) {
        const ae = fs.readFileSync(mp, "utf8").trim();
        for (let i = 0; i < _store.accounts.length; i++) {
          if (_store.accounts[i].email === ae) {
            _store.activeIndex = i;
            break;
          }
        }
        if (_store.activeIndex >= 0) break;
      }
    } catch {}
  }

  // ── 侧边栏面板 ──
  _sidebarProvider = new WamViewProvider(_store);
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider("wam.panel", _sidebarProvider),
  );

  // ── 状态栏小标 (右下角) ──
  _statusBarItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100,
  );
  _statusBarItem.command = "wam.openEditor";
  updateStatusBar();
  _statusBarItem.show();
  context.subscriptions.push(_statusBarItem);

  // ── 注册命令 ──
  context.subscriptions.push(
    vscode.commands.registerCommand("wam.openEditor", () => {
      openEditorPanel();
    }),
    // 手动切号: 无任何限制 (不检查in-use, 不跳过任何账号)
    vscode.commands.registerCommand("wam.switchAccount", async () => {
      // v7.4: 官方模式下不自动翻转, 明确提示用户
      if (_mode === "official") {
        const choice = await vscode.window.showWarningMessage(
          "WAM: 当前为官方模式，切号将切回WAM模式。确认？",
          "切回WAM模式",
          "取消",
        );
        if (choice !== "切回WAM模式") return;
        saveMode("wam");
        _restartBackgroundServices();
        log("switchAccount: user confirmed → wam mode");
      }
      const items = _store.accounts.map((a, idx) => {
        const i = idx;
        const h = _store.getHealth(a);
        const inUse = _store.isInUse(a.email) ? " [使用中]" : "";
        const liveTag = h.hasSnap ? "●" : "";
        return {
          label: `${idx + 1}. ${a.email}${inUse}`,
          description: `${liveTag}D${Math.round(h.daily)}%·W${Math.round(h.weekly)}% ${h.plan}`,
          index: i,
        };
      });
      const pick = await vscode.window.showQuickPick(items, {
        placeHolder: "手动选择账号 (无任何限制)",
      });
      if (pick) {
        const acc = _store.get(pick.index);
        if (!acc || !acc.password) return;
        // v7.3.1: 手动抢占机制 — 超过30s强制释放锁
        if (_switching) {
          const lockAge = Date.now() - _switchingStartTime;
          if (lockAge < 30000) {
            vscode.window.showWarningMessage(
              `WAM: 正在切换中(${Math.round(lockAge / 1000)}s)...请稍候`,
            );
            return;
          }
          log(
            `switchAccount: 手动抢占 — 强制释放超时锁(${Math.round(lockAge / 1000)}s)`,
          );
          _switching = false;
        }
        _switching = true;
        _switchingStartTime = Date.now();
        try {
          const result = await switchToAccount(acc.email, acc.password);
          if (result.ok) {
            _store.activeIndex = pick.index;
            _store.switchCount++;
            _store.clearInUse(acc.email);
            _writeInstanceClaim(acc.email);
            _quotaSnapshots.delete(acc.email.toLowerCase()); // 重置快照基准
            _snapshotDirty = true;
            _schedulePersist();
            vscode.window.showInformationMessage(
              `WAM: 已手动切换到 ${result.account}`,
            );
            _ensureEngines();
          } else {
            vscode.window.showErrorMessage(`WAM: ${result.error}`);
          }
        } finally {
          _switching = false;
          refreshAll();
        }
      }
    }),
    vscode.commands.registerCommand("wam.refreshAll", () => {
      _store.load();
      _store.lastRefresh = Date.now();
      refreshAll();
      vscode.window.showInformationMessage(
        `WAM: 已刷新 ${_store.pwCount()} 个账号`,
      );
    }),
    vscode.commands.registerCommand("wam.addAccount", async () => {
      const input = await vscode.window.showInputBox({
        prompt: "粘贴账号 (支持多种格式)",
        placeHolder: "email:password 或 email password 或批量粘贴",
      });
      if (input) {
        const r = _store.addBatch(input);
        refreshAll();
        if (r.added > 0)
          vscode.window.showInformationMessage(`WAM: 添加了 ${r.added} 个账号`);
        else vscode.window.showWarningMessage(`WAM: 无法识别格式或账号已存在`);
      }
    }),
    vscode.commands.registerCommand("wam.autoRotate", async () => {
      // v7.4: 官方模式下智能轮转被禁用
      if (!isWamMode()) {
        vscode.window.showWarningMessage(
          "WAM: 官方模式下智能轮转已禁用，请先切回WAM模式",
        );
        return;
      }
      await doAutoRotate(_store);
      refreshAll();
    }),
    vscode.commands.registerCommand("wam.panicSwitch", async () => {
      // v7.4: 官方模式下紧急切换也需确认
      if (_mode === "official") {
        const choice = await vscode.window.showWarningMessage(
          "WAM: 官方模式下紧急切换将切回WAM模式",
          "确认紧急切换",
          "取消",
        );
        if (choice !== "确认紧急切换") return;
        saveMode("wam");
        _restartBackgroundServices();
      }
      const bestI = _store.getBestIndex(_store.activeIndex, false); // 紧急切换不跳过使用中
      if (bestI < 0) {
        vscode.window.showErrorMessage("WAM: 无可用账号");
        return;
      }
      const acc = _store.get(bestI);
      // v7.3.1: 紧急切换无条件抢占 — 不等待30s, 直接强制释放
      if (_switching) {
        log(
          `panicSwitch: 强制释放锁(${Math.round((Date.now() - _switchingStartTime) / 1000)}s)`,
        );
        _switching = false;
      }
      _switching = true;
      _switchingStartTime = Date.now();
      try {
        const result = await switchToAccount(acc.email, acc.password);
        if (result.ok) {
          _store.activeIndex = bestI;
          _store.switchCount++;
          _writeInstanceClaim(acc.email);
          _quotaSnapshots.delete(acc.email.toLowerCase());
          _snapshotDirty = true;
          _schedulePersist();
          vscode.window.showInformationMessage(
            `WAM: 紧急切换到 ${result.account} (${result.ms}ms)`,
          );
          _ensureEngines();
        }
      } finally {
        _switching = false;
        refreshAll();
      }
    }),
    vscode.commands.registerCommand("wam.injectToken", async () => {
      if (!fs.existsSync(TOKEN_FILE)) {
        vscode.window.showWarningMessage("WAM: 无待注入token");
        return;
      }
      const data = JSON.parse(fs.readFileSync(TOKEN_FILE, "utf8"));
      const result = await injectAuth(data.idToken);
      if (result.ok) {
        try {
          fs.unlinkSync(TOKEN_FILE);
        } catch {}
        vscode.window.showInformationMessage(
          `WAM: 注入成功 — ${result.account}`,
        );
      } else {
        vscode.window.showErrorMessage(
          `WAM: 注入失败 — ${JSON.stringify(result.error)}`,
        );
      }
      refreshAll();
    }),
    vscode.commands.registerCommand("wam.verifyAll", async () => {
      const result = await verifyAndPurgeExpired(_store);
      refreshAll();
    }),
    vscode.commands.registerCommand("wam.scanExpiry", async () => {
      await scanMissingExpiry();
      refreshAll();
    }),
    vscode.commands.registerCommand("wam.officialMode", async () => {
      const choice = await vscode.window.showWarningMessage(
        "WAM: 切换到官方模式？\n将登出WAM会话、清除所有第三方套层，回归Windsurf原生登录。",
        { modal: true },
        "确认回归本源",
      );
      if (choice !== "确认回归本源") return;
      saveMode("official");
      const cleaned = await cleanupThirdPartyState();
      vscode.window.showInformationMessage(
        `WAM: 官方模式已激活 — WAM会话已登出，${cleaned}项清理完成。请使用Windsurf原生登录您自己的账号`,
      );
      refreshAll();
    }),
    vscode.commands.registerCommand("wam.wamMode", async () => {
      saveMode("wam");
      // v7.4: 回切WAM时重启后台设施
      _restartBackgroundServices();
      if (_store.activeIndex < 0 && _store.pwCount() > 0) {
        const bestI = _store.getBestIndex(-1, false);
        if (bestI >= 0) {
          const acc = _store.get(bestI);
          if (_switching) {
            log(
              `wamMode: 强制释放锁(${Math.round((Date.now() - _switchingStartTime) / 1000)}s)`,
            );
            _switching = false;
          }
          _switching = true;
          _switchingStartTime = Date.now();
          try {
            const result = await switchToAccount(acc.email, acc.password);
            if (result.ok) {
              _store.activeIndex = bestI;
              _store.switchCount++;
              _store.save();
              vscode.window.showInformationMessage(
                `WAM: WAM模式启动，自动登录 ${result.account}`,
              );
              _ensureEngines();
            }
          } finally {
            _switching = false;
            refreshAll();
          }
          return;
        }
      }
      vscode.window.showInformationMessage("WAM: WAM切号模式已启动");
      refreshAll();
    }),
    vscode.commands.registerCommand("wam.status", () => {
      const stats = _store.getPoolStats();
      const activeAcc =
        _store.activeIndex >= 0 ? _store.get(_store.activeIndex) : null;
      const inUseEmails = [..._store._inUse.keys()]
        .map((e) => e.substring(0, 15))
        .join(", ");
      let msg = `WAM v10.0.0 | ${stats.pwCount}号 D${stats.totalD}·W${stats.totalW} | mode=${_mode} | 监测${_totalMonitorCycles}轮·${_totalChangesDetected}次变动·${_store.switchCount}次切号 | inst=${_instanceId}`;
      if (activeAcc) msg += ` | 活跃: ${activeAcc.email.substring(0, 20)}`;
      if (_store._inUse.size > 0) msg += ` | 使用中: ${inUseEmails}`;
      vscode.window.showInformationMessage(msg);
    }),
  );

  // ── v8: Rate-limit错误拦截器 — 道法自然: 不等用户报错, 主动感知并切号 ──
  // 拦截Windsurf的"Rate limit exceeded"错误, 自动触发无感切号
  _rateLimitWatcher = vscode.window.onDidChangeActiveTextEditor(() => {}); // placeholder for dispose
  try {
    // 监听所有信息/警告消息 (vscode.window的showInformationMessage无法拦截, 但可以监听output channel)
    const _rlInterceptor = vscode.workspace.onDidChangeTextDocument(
      async (e) => {
        if (!isWamMode() || _switching || !_store || _store.activeIndex < 0)
          return;
        // 检测Windsurf AI输出中的rate limit错误
        const text = e.document.getText();
        if (!text) return;
        // 仅检查最近写入的内容 (性能优化: 不扫描整个文档)
        const lastChange = e.contentChanges[e.contentChanges.length - 1];
        if (!lastChange) return;
        const newText = lastChange.text;
        if (!newText || newText.length < 20 || newText.length > 500) return;
        if (/rate.?limit.?exceeded|Rate limit error/i.test(newText)) {
          const cooldown = Date.now() - _lastSwitchTime < 10000;
          if (cooldown) return; // 刚切过, 不重复
          log(
            `🚨 rate-limit intercepted in document! Triggering proactive switch...`,
          );
          const autoRotate = vscode.workspace
            .getConfiguration("wam")
            .get("autoRotate", true);
          if (!autoRotate) return;
          const bestI =
            _predictiveCandidate >= 0
              ? _predictiveCandidate
              : _store.getBestIndex(_store.activeIndex, true);
          if (bestI < 0) {
            log("rate-limit: no available account");
            return;
          }
          const bestAcc = _store.get(bestI);
          _switching = true;
          _switchingStartTime = Date.now();
          try {
            const sr = await switchToAccount(bestAcc.email, bestAcc.password);
            if (sr.ok) {
              _store.activeIndex = bestI;
              _store.switchCount++;
              _lastSwitchTime = Date.now();
              _predictiveCandidate = _store.getBestIndex(bestI, true);
              if (_predictiveCandidate >= 0)
                _prewarmCandidateToken(_predictiveCandidate);
              _store.save();
              _quotaSnapshots.delete(bestAcc.email.toLowerCase());
              _snapshotDirty = true;
              _schedulePersist();
              vscode.window.showInformationMessage(
                `WAM: 🚨 Rate-limit拦截 → 已无感切换到 ${sr.account} (${sr.ms}ms)`,
              );
              refreshAll();
            }
          } finally {
            _switching = false;
          }
        }
      },
    );
    context.subscriptions.push(_rlInterceptor);
    log("v8: rate-limit interceptor registered");
  } catch (e) {
    log(`v8: rate-limit interceptor failed: ${e.message}`);
  }

  // ── 活动感知: 追踪本实例的编辑器/终端活动 (根治: 区分自使用vs外部使用) ──
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor(() => {
      _lastSelfActivity = Date.now();
    }),
    vscode.workspace.onDidChangeTextDocument(() => {
      _lastSelfActivity = Date.now();
    }),
    vscode.window.onDidOpenTerminal(() => {
      _lastSelfActivity = Date.now();
    }),
  );
  _lastSelfActivity = Date.now(); // 启动即视为活跃

  // ── 实例协调: 心跳 + 声明 (根治: 多实例抢号) ──
  // v7.4: 官方模式下不启动心跳, 不写入instance claim
  if (isWamMode()) {
    _writeInstanceClaim(
      _store.activeIndex >= 0 ? _store.get(_store.activeIndex)?.email : "",
    );
    _heartbeatTimer = setInterval(() => {
      if (!isWamMode()) return; // v7.4: 官方模式下静默
      const activeAcc =
        _store.activeIndex >= 0 ? _store.get(_store.activeIndex) : null;
      _writeInstanceClaim(activeAcc?.email || "");
      _cleanDeadInstances();
    }, INSTANCE_HEARTBEAT_MS);
  }
  context.subscriptions.push({
    dispose() {
      if (_heartbeatTimer) clearInterval(_heartbeatTimer);
    },
  });
  log(`instance: ${_instanceId} registered (pid=${process.pid})`);

  // ── 延迟启动 ──
  setTimeout(() => {
    // v7.4: 官方模式下不启动文件监听, 不处理待注入token
    if (isWamMode()) {
      startFileWatcher();
      if (fs.existsSync(TOKEN_FILE)) {
        log("startup: pending token found");
        vscode.commands.executeCommand("wam.injectToken");
      }
      // v10: 冷启动修复 — 立即启动扫描引擎, 不等首次切号
      // 根治: 新安装用户所有账号显示"未验"0D/0W的问题
      _ensureEngines();
      log("startup: WAM模式 — v10: 引擎已立即启动, 后台扫描开始获取额度");
    } else {
      log("startup: 官方模式 — 零干扰·无监听/心跳/引擎");
    }
    updateStatusBar();
  }, 3000);
}

function deactivate() {
  if (_watcher) {
    _watcher.close();
    _watcher = null;
  }
  if (_pollTimer) {
    clearInterval(_pollTimer);
    _pollTimer = null;
  }
  _stopEngines();
  if (_heartbeatTimer) {
    clearInterval(_heartbeatTimer);
    _heartbeatTimer = null;
  }
  if (_persistTimer) {
    clearTimeout(_persistTimer);
    _persistTimer = null;
  }
  if (_rateLimitWatcher) {
    _rateLimitWatcher.dispose();
    _rateLimitWatcher = null;
  }
  _prewarmedToken = null;
  if (_editorPanel) {
    _editorPanel.dispose();
    _editorPanel = null;
  }
  // 关闭前落盘: 确保快照和使用中标记不丢失
  try {
    _saveSnapshots();
  } catch {}
  try {
    if (_store) _saveInUse(_store);
  } catch {}
  // 清除实例声明
  try {
    const claims = _readInstanceClaims();
    delete claims[_instanceId];
    fs.writeFileSync(
      INSTANCE_LOCK_FILE,
      JSON.stringify(claims, null, 2),
      "utf8",
    );
  } catch {}
  log(
    `deactivate — inst=${_instanceId} 监测${_totalMonitorCycles}轮·${_totalChangesDetected}次变动·${_store?.switchCount || 0}次切换 snap=${_quotaSnapshots.size} inUse=${_store?._inUse?.size || 0}`,
  );
}

module.exports = { activate, deactivate };
