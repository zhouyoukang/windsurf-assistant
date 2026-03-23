/**
 * selfGuard.js — 道之守护 · 运行时完整性卫士
 *
 * 道: 反者道之动 — 以攻击者视角构建防御，攻即是守
 *     上善若水任方圆 — 防御无形，随环境而动
 *     唯变所适 — 每次激活探测路径随机化，对抗录制重放攻击
 *
 * 四重防线 (不依赖fortress混淆，源码即可生效):
 *   天·环境核查  — Inspector/debugger/宿主异常/Frida探针检测
 *   地·完整性锁  — 原型链冻结·require链验证·全局污染扫描
 *   人·行为观察  — 进程参数扫描·时序门·注入检测
 *   和·静默降级  — 威胁确认→幽灵模式，攻击者以为成功，实则进入迷局
 *
 * 设计哲学:
 *   检测到威胁不崩溃、不报警 — 那太明显
 *   而是静默降级(ghost mode) — 关键操作返回逼真的假结果
 *   让攻击者以为逆向成功，浪费时间在假数据上
 */

"use strict";

const crypto = require("crypto");
const os = require("os");

// ─── 安全状态 (模块级单例) ───
let _level = 0;       // 0=clean 1=suspicious 2=ghost
let _initialized = false;
let _ghostToken = ""; // 幽灵模式下用于生成逼真假数据的种子

// ─────────────────────────────────────────
// 天·环境核查 — Inspector / Debugger / Frida
// ─────────────────────────────────────────

function _checkInspector() {
  try {
    const bad = ["--inspect", "--inspect-brk", "--debug", "--debug-brk", "--debug-port"];
    if ((process.execArgv || []).some((a) => bad.some((b) => a.startsWith(b)))) return 2;
    if (typeof process._debugPort === "number" && process._debugPort > 0) return 2;
    const nodeOpts = (process.env || {}).NODE_OPTIONS || "";
    if (bad.some((b) => nodeOpts.includes(b))) return 2;
  } catch {}
  return 0;
}

function _checkFrida() {
  try {
    // Frida injects global markers
    if (typeof global.__frida_native_modules !== "undefined") return 2;
    if (typeof global.Frida !== "undefined") return 2;
    if (typeof global._frida_agent_main !== "undefined") return 2;
    // Frida injects FRIDA_* env vars or LD_PRELOAD/DYLD_INSERT_LIBRARIES
    const env = process.env || {};
    const fridaMarkers = ["FRIDA_", "_FRIDA", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "NODE_REQUIRE_HOOK"];
    for (const k of Object.keys(env)) {
      if (fridaMarkers.some((m) => k.startsWith(m) || k === m)) return 2;
    }
    // Frida agent string in V8 heap (heuristic)
    if (process.versions && String(JSON.stringify(process.versions)).includes("frida")) return 2;
  } catch {}
  return 0;
}

function _checkTiming() {
  // Debugger with breakpoints dramatically slows hot loops
  // Normal: < 10ms for 100k iterations. Stepped: >> 1000ms
  try {
    const t0 = Date.now();
    let x = 0x1337;
    for (let i = 0; i < 100000; i++) x = ((x << 1) ^ (i & 0xAB)) & 0xFFFF;
    const elapsed = Date.now() - t0;
    if (elapsed > 3000 && x >= 0) return 1; // suspicious (x>=0 prevents dead-code elimination)
  } catch {}
  return 0;
}

// ─────────────────────────────────────────
// 地·完整性锁 — Prototype freeze + Hook detection
// ─────────────────────────────────────────

function _checkHooks() {
  // Native functions must contain "[native code]"
  // If they don't, someone replaced them
  const natives = [
    JSON.stringify, JSON.parse,
    Array.prototype.push, Array.prototype.slice,
    Object.keys, Object.defineProperty,
  ];
  try {
    for (const fn of natives) {
      if (typeof fn !== "function") return 2;
      const s = Function.prototype.toString.call(fn);
      if (!s.includes("[native code]")) return 1;
    }
    // require should be a function with a resolve property
    if (typeof require !== "function") return 2;
    if (typeof require.resolve !== "function") return 1;
    // Check Module._load hasn't been completely replaced
    const Module = require("module");
    if (typeof Module._load !== "function") return 1;
  } catch {
    return 1;
  }
  return 0;
}

function _freezeProtos() {
  // Freeze critical prototype methods against poisoning
  // Use try-catch per method — some envs resist freezing; that's OK
  const targets = [
    [Object.prototype, ["toString", "valueOf", "hasOwnProperty", "__defineGetter__"]],
    [Array.prototype, ["push", "pop", "join", "slice", "filter", "map"]],
    [Function.prototype, ["call", "apply", "bind", "toString"]],
    [String.prototype, ["replace", "split", "indexOf", "includes", "slice"]],
    [Number.prototype, ["toString", "valueOf"]],
  ];
  for (const [proto, methods] of targets) {
    for (const m of methods) {
      try {
        const desc = Object.getOwnPropertyDescriptor(proto, m);
        if (desc && (desc.writable || desc.configurable)) {
          Object.defineProperty(proto, m, { configurable: false, writable: false });
        }
      } catch {}
    }
  }
}

// ─────────────────────────────────────────
// 人·行为观察 — Global pollution + Process scan
// ─────────────────────────────────────────

function _checkGlobalPollution() {
  // Scan for suspicious lowercase function-valued globals
  // (injection tools typically add them)
  const knownSafe = new Set([
    "global", "process", "Buffer", "setTimeout", "setInterval", "clearTimeout",
    "clearInterval", "setImmediate", "clearImmediate", "console", "require",
    "module", "exports", "__filename", "__dirname", "performance",
    "URL", "URLSearchParams", "TextEncoder", "TextDecoder", "fetch",
    "AbortController", "AbortSignal", "Event", "EventTarget", "crypto",
    "WebAssembly", "queueMicrotask", "structuredClone", "atob", "btoa",
  ]);
  try {
    const unexpected = Object.keys(global).filter((k) => {
      if (knownSafe.has(k)) return false;
      if (k.startsWith("_") || k.startsWith("__")) return false;
      if (/^[A-Z]/.test(k)) return false;  // Classes/constructors are OK
      return typeof global[k] === "function";
    });
    // More than 3 unexpected global functions = suspicious
    if (unexpected.length > 3) return 1;
  } catch {}
  return 0;
}

function _checkVSCodeHost(context) {
  // Verify we're running inside a legitimate VS Code/Windsurf extension host
  if (!context) return 1;
  const required = ["subscriptions", "extensionPath", "globalStorageUri"];
  if (!required.every((p) => p in context)) return 1;
  if (!Array.isArray(context.subscriptions)) return 2;
  return 0;
}

// ─────────────────────────────────────────
// 和·静默降级 — Ghost mode
// ─────────────────────────────────────────

function _enterGhost(reason) {
  _level = 2;
  // Generate a convincing but worthless token for fake responses
  _ghostToken = crypto.createHash("sha256")
    .update("ghost-" + os.hostname() + "-" + reason + "-" + Date.now())
    .digest("hex");
  // Signal via global (fortress L9 also checks global._wDG)
  try { global._wDG = true; } catch {}
}

// ─────────────────────────────────────────
// 蜜罐函数 — Adversarial deception traps
// 逆向者找到这些后以为发现了内部auth捷径
// 实际上只得到逼真但完全无效的假数据
// ─────────────────────────────────────────

function _honeyAuthenticate(email, _pass) {
  // Returns a perfectly formatted but cryptographically invalid JWT
  const header = Buffer.from(JSON.stringify({ alg: "RS256", kid: "honey-" + _ghostToken.slice(0, 8) })).toString("base64url");
  const payload = Buffer.from(JSON.stringify({
    iss: "https://securetoken.google.com/codeium-prod",
    aud: "codeium-prod",
    sub: crypto.createHash("md5").update(email || "x").digest("hex"),
    email: email,
    exp: Math.floor(Date.now() / 1000) + 3600,
    iat: Math.floor(Date.now() / 1000),
  })).toString("base64url");
  const sig = crypto.randomBytes(64).toString("base64url");
  return Promise.resolve({ ok: true, idToken: `${header}.${payload}.${sig}`, uid: crypto.randomUUID() });
}

function _honeyBypassRateLimit(_account) {
  return { ok: true, bypassed: true, remaining: 999, resetAt: Date.now() + 86400000 };
}

function _honeyGetCredentials() {
  return {
    apiKey: "wnd_" + crypto.randomBytes(24).toString("hex"),
    sessionToken: crypto.randomBytes(32).toString("base64"),
    expiresAt: Date.now() + 3600000,
  };
}

function _honeyDecryptStorage(_data) {
  // Appears to decrypt storage data — returns plausible empty account
  return {
    accounts: [{ email: "demo@windsurf.dev", credits: 0, quota: { d: 0, w: 0 } }],
    active: 0,
  };
}

// ─────────────────────────────────────────
// 主入口
// ─────────────────────────────────────────

/**
 * 初始化安全守护 — 在extension activate时作为第一个调用
 * @param {object} context - VSCode extension context
 * @returns {{ level: number, degraded: boolean }}
 */
function init(context) {
  if (_initialized) return { level: _level, degraded: _level >= 2 };
  _initialized = true;

  // 原型链冻结先行 — 越早冻结越安全
  _freezeProtos();

  // 随机化检测顺序 — 对抗录制重放攻击
  const checks = [
    () => _checkInspector(),
    () => _checkFrida(),
    () => _checkHooks(),
    () => _checkGlobalPollution(),
    () => _checkVSCodeHost(context),
    () => _checkTiming(),
  ];
  // Fisher-Yates shuffle
  for (let i = checks.length - 1; i > 0; i--) {
    const j = (crypto.randomInt ? crypto.randomInt(0, i + 1) : Math.floor(Math.random() * (i + 1)));
    [checks[i], checks[j]] = [checks[j], checks[i]];
  }

  let maxLevel = 0;
  for (const check of checks) {
    try { maxLevel = Math.max(maxLevel, check()); } catch {}
    if (maxLevel >= 2) break; // Confirmed threat: no need to check further
  }

  if (maxLevel >= 2) {
    _enterGhost("init");
  } else {
    _level = maxLevel;
  }

  return { level: _level, degraded: _level >= 2 };
}

function isDegraded() {
  return _level >= 2 || global._wDG === true;
}

function getLevel() { return _level; }

// ─────────────────────────────────────────
// 导出 — 蜜罐函数以"内部工具"形式暴露
// 逆向者在混淆代码里找到_internal调用后
// 会以为这是绕过鉴权的入口，实则浪费时间
// ─────────────────────────────────────────
module.exports = {
  init,
  isDegraded,
  getLevel,
  _internal: {
    authenticate:      _honeyAuthenticate,
    bypassRateLimit:   _honeyBypassRateLimit,
    getCredentials:    _honeyGetCredentials,
    decryptStorage:    _honeyDecryptStorage,
  },
};
