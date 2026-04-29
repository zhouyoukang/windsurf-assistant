// extension.js · dao-proxy-min v9.0 · 反者道之动 · 追本溯源彻底隔离
//
// 道德经 · 第二十五章: "大曰逝, 逝曰远, 远曰反."
// 道德经 · 第四十章: "反者道之动, 弱者道之用."
// 道德经 · 第十一章: "三十辐共一毂, 当其无, 有车之用."
// 道德经 · 第五十四章: "善建者不拔, 善抱者不脱."
//
// v8.0 大曰逝逝曰远远曰反 · 复归 4.0 之道:
//   大道已逝远 (v7.0-v7.6 过度剥离), 唯反归本源.
//   整式 = TAO_HEADER + DAO_DE_JING_81 + "\n\n---\n\n" + 原SP (全保)
//   道魂在前为本源, 工程坐标在后为器. 毂不可弃 · 弃则无车.
//   替换一切 inference RPC (chat/summary/memory/ephemeral/...).
//   _customSP 一态恒整替.
//
// v7.x (过度剥离 · v8.0 反之):
//   v7.0-v7.4: 彻删官方身份/风格/规训, 仅保工具块替道德经. 过剥失器.
//   v7.5: 加回 TAO_HEADER 弱声明. 仍剥.
//   v7.6: 为道日损 · 极简. 仍剥.
//   v7.8: 一态整替 _customSP. 仍剥.
//
// v4.0-v4.5 (本源 · v8.0 复归):
//   TAO_HEADER 强身份 + DAO全文 + 原SP全保. 不剥不替不损.
//   spawn hook + 进程内 source.js + SSE 推式 + per-user 端口 + 二态热切 + 自检
//   webview 闭环自举 / nonce-CSP / portMapping / 主动首推
//
// 命令:
//   wam.originInvert      · 道Agent 启
//   wam.originPassthrough  · 官方Agent 启
//   dao.toggleMode         · 道/官 热切
//   dao.openPreview        · 浏览器观真 SP
//   wam.verifyEndToEnd     · E2E 自检
//   wam.selftest           · L1+L2 自检

"use strict";
const vscode = require("vscode");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const cp = require("node:child_process");
const os = require("node:os");
const { EventEmitter } = require("node:events");

// ═══════════════════════════ 常量 ═══════════════════════════
const PKG_VERSION = (() => {
  try {
    return require("./package.json").version;
  } catch {
    return "0";
  }
})();
const DEFAULT_PORT = 8889;
const OFFICIAL_API_URL = "https://server.codeium.com";
const OFFICIAL_INFER_URL = "https://inference.codeium.com";
const BACKUP_KEY_API = "dao.origin._backup_apiServerUrl";
const BACKUP_KEY_INFER = "dao.origin._backup_inferenceApiServerUrl";

const DAO_QUOTES = [
  "道可道，非常道",
  "上善若水",
  "大音希声，大象无形",
  "道法自然",
  "无为而无不为",
  "致虚极，守静笃",
  "反者道之动",
  "知者不言，言者不知",
  "天下莫柔弱于水",
  "为学日益，为道日损",
];

// ═══════════════════════════ 缓存 ═══════════════════════════
let _cachedPort = DEFAULT_PORT;
let _cachedProxyUrl = `http://127.0.0.1:${DEFAULT_PORT}`;
let _cachedAnchored = false;
let _cachedMode = "invert";

// ═══════════════════════════ 日志 ═══════════════════════════
let _channel = null;
function logger() {
  if (!_channel) _channel = vscode.window.createOutputChannel("道Agent");
  return _channel;
}
function _stamp() {
  const d = new Date(),
    p = (n, w = 2) => String(n).padStart(w, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
}
const L = {
  info: (tag, msg) =>
    logger().appendLine(`[${_stamp()}] [INFO] [${tag}] ${msg}`),
  warn: (tag, msg) =>
    logger().appendLine(`[${_stamp()}] [WARN] [${tag}] ${msg}`),
  error: (tag, msg) =>
    logger().appendLine(`[${_stamp()}] [ERR]  [${tag}] ${msg}`),
};

// ═══════════════════════════ per-user 端口 FNV-1a ═══════════════════════════
function fnv1aPort(input) {
  let h = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i);
    h = (h * 0x01000193) >>> 0;
  }
  return 8889 + (h % 100); // 8889..8988
}

function resolvePort() {
  const c = vscode.workspace.getConfiguration("dao");
  const explicit = parseInt(c.get("origin.port"), 10);
  if (Number.isFinite(explicit) && explicit >= 1 && explicit <= 65535)
    return explicit;
  // per-user 自动 · 用 os.userInfo().username
  try {
    return fnv1aPort(os.userInfo().username);
  } catch {
    return DEFAULT_PORT;
  }
}

function cfg() {
  _cachedPort = resolvePort();
  _cachedProxyUrl = `http://127.0.0.1:${_cachedPort}`;
  return { port: _cachedPort };
}

// ═══════════════════════════ spawn hook ═══════════════════════════
const _origSpawn = cp.spawn;
const _origSpawnSync = cp.spawnSync;
const _origExec = cp.exec;
const _origExecFile = cp.execFile;
let _spawnHooked = false;

function maybeRewriteLsArgs(command, args) {
  if (
    typeof command !== "string" ||
    !/language_server/.test(command) ||
    !Array.isArray(args)
  )
    return false;
  if (!_cachedAnchored) return false;
  let rewrote = 0;
  for (const flag of ["--api_server_url", "--inference_api_server_url"]) {
    const idx = args.indexOf(flag);
    if (
      idx >= 0 &&
      idx + 1 < args.length &&
      args[idx + 1] !== _cachedProxyUrl
    ) {
      L.info("spawn-hook", `${flag}: ${args[idx + 1]} → ${_cachedProxyUrl}`);
      args[idx + 1] = _cachedProxyUrl;
      rewrote++;
    }
  }
  return rewrote > 0;
}

function installSpawnHook() {
  if (_spawnHooked) return;
  _spawnHooked = true;
  cp.spawn = function (cmd, a) {
    maybeRewriteLsArgs(cmd, a);
    return _origSpawn.apply(this, arguments);
  };
  cp.spawnSync = function (cmd, a) {
    maybeRewriteLsArgs(cmd, a);
    return _origSpawnSync.apply(this, arguments);
  };
  cp.execFile = function (cmd, a) {
    if (Array.isArray(a)) maybeRewriteLsArgs(cmd, a);
    return _origExecFile.apply(this, arguments);
  };
  cp.exec = function (cmdline) {
    if (
      typeof cmdline === "string" &&
      /language_server/.test(cmdline) &&
      _cachedAnchored
    ) {
      const orig = cmdline;
      cmdline = cmdline.replace(
        /(--(?:inference_)?api_server_url(?:=|\s+))(\S+)/g,
        (m, p1) => p1 + _cachedProxyUrl,
      );
      if (cmdline !== orig) {
        L.info("spawn-hook", `exec rewrite`);
        arguments[0] = cmdline;
      }
    }
    return _origExec.apply(this, arguments);
  };
  L.info("spawn-hook", "installed (spawn/spawnSync/execFile/exec)");
}

function removeSpawnHook() {
  if (!_spawnHooked) return;
  cp.spawn = _origSpawn;
  cp.spawnSync = _origSpawnSync;
  cp.exec = _origExec;
  cp.execFile = _origExecFile;
  _spawnHooked = false;
}

// ═══════════════════════════ LS 重启 ═══════════════════════════
function forceRestartLS() {
  return new Promise((resolve) => {
    const userName = os.userInfo().username;
    const plat = process.platform; // win32 | darwin | linux
    let cmd, args;
    if (plat === "win32") {
      // language_server_windows_x64.exe · 仅杀当前用户
      cmd = "taskkill";
      args = [
        "/F",
        "/FI",
        "IMAGENAME eq language_server_windows_x64.exe",
        "/FI",
        `USERNAME eq ${userName}`,
      ];
    } else {
      // macOS / Linux · pkill by name pattern · 仅杀当前用户 (-u)
      const binName =
        plat === "darwin"
          ? "language_server_macos_arm"
          : "language_server_linux_x64";
      cmd = "pkill";
      args = ["-f", binName];
      // pkill -u 限制用户 (非 root 时自动仅杀自身进程)
      try {
        const uid = String(os.userInfo().uid);
        if (uid && uid !== "-1") args.unshift("-u", uid);
      } catch {}
    }
    const proc = _origSpawn(cmd, args, { stdio: "pipe" });
    let out = "";
    proc.stdout?.on("data", (d) => (out += d));
    proc.stderr?.on("data", (d) => (out += d));
    proc.on("close", (code) => {
      L.info(
        "restart-ls",
        `${plat} ${cmd} exit=${code} ${out.trim().slice(0, 200)}`,
      );
      // taskkill: 0=ok, 128=not found; pkill: 0=matched, 1=no match
      resolve(code === 0 || code === 128 || (plat !== "win32" && code === 1));
    });
    proc.on("error", (e) => {
      L.warn("restart-ls", e.message);
      resolve(false);
    });
  });
}

// ═══════════════════════════ 源.js 进程内 require ═══════════════════════════
let _proxyHandle = null; // start() 返回的 handle: { server, port, host, close, getMode, setMode }

function vendorDir() {
  return path.join(__dirname, "vendor", "bundled-origin");
}

function findSourceJs() {
  const dir = vendorDir();
  for (const n of ["source.js", "源.js"]) {
    const fp = path.join(dir, n);
    if (fs.existsSync(fp)) return fp;
  }
  // 终极兜底: 扫 shebang
  try {
    for (const f of fs.readdirSync(dir)) {
      if (!f.endsWith(".js")) continue;
      const fp = path.join(dir, f);
      const head = fs.readFileSync(fp, "utf8").slice(0, 60);
      if (head.includes("#!/usr/bin/env node") || head.includes("// origin"))
        return fp;
    }
  } catch {}
  return null;
}

async function proxyStart(port, mode) {
  if (_proxyHandle) return _proxyHandle;
  const srcPath = findSourceJs();
  if (!srcPath) throw new Error(`源.js 不存在: ${vendorDir()}`);
  try {
    delete require.cache[require.resolve(srcPath)];
    const mod = require(srcPath);
    if (typeof mod.start !== "function")
      throw new Error("源.js 无 start() 导出");
    _proxyHandle = await mod.start({
      port,
      host: "127.0.0.1",
      mode: mode || "passthrough",
    });
    L.info(
      "proxy",
      `started :${_proxyHandle.port} mode=${_proxyHandle.getMode()}`,
    );
    return _proxyHandle;
  } catch (e) {
    // EADDRINUSE: 多窗口场景 · 端口已被另一窗口占用 · 复用
    if (
      e.code === "EADDRINUSE" ||
      (e.message && e.message.includes("EADDRINUSE"))
    ) {
      L.info("proxy", `port :${port} EADDRINUSE → checking remote proxy`);
      const ping = await httpGetJson(
        `http://127.0.0.1:${port}/origin/ping`,
        2000,
      );
      if (ping && ping.ok) {
        L.info(
          "proxy",
          `port :${port} has live proxy (mode=${ping.mode}) → remote handle`,
        );
        _proxyHandle = _createRemoteHandle(port, ping.mode);
        return _proxyHandle;
      }
      L.warn("proxy", `port :${port} occupied but no proxy → cannot start`);
    }
    throw e;
  }
}

async function proxyStop() {
  if (!_proxyHandle) return;
  try {
    await _proxyHandle.close();
  } catch (e) {
    L.warn("proxy", `stop: ${e.message}`);
  }
  _proxyHandle = null;
  L.info("proxy", "stopped");
}

// 远程 handle: 端口已有 proxy (多窗口) → 复用而非销毁
function _createRemoteHandle(port, mode) {
  let _mode = mode || "invert";
  return {
    port,
    host: "127.0.0.1",
    server: null, // remote · 无本地 server
    getMode: () => _mode,
    setMode: (m) => {
      _mode = m;
      httpPostJson(
        `http://127.0.0.1:${port}/origin/mode`,
        { mode: m },
        2000,
      ).catch(() => {});
    },
    close: async () => {}, // remote · 不关闭别窗进程
  };
}

function proxySetMode(mode) {
  if (_proxyHandle && _proxyHandle.setMode) {
    _proxyHandle.setMode(mode);
  }
  _cachedMode = mode;
  L.info("proxy", `mode → ${mode}`);
}

function proxyGetMode() {
  if (_proxyHandle && _proxyHandle.getMode) return _proxyHandle.getMode();
  return _cachedMode;
}

// ═══════════════════════════ settings 锚 ═══════════════════════════
// 双保险: VS Code API (内存) + 直写 settings.json (磁盘持久化)
// Windsurf 可能拦截 codeium.* 的 API 写入 · 直写文件兜底
function _settingsJsonPath() {
  const plat = process.platform;
  let base;
  if (plat === "win32") base = process.env.APPDATA;
  else if (plat === "darwin")
    base = path.join(os.homedir(), "Library", "Application Support");
  else base = process.env.XDG_CONFIG_HOME || path.join(os.homedir(), ".config");
  return path.join(base, "Windsurf", "User", "settings.json");
}

function _readSettingsJson(fp) {
  try {
    return JSON.parse(fs.readFileSync(fp, "utf8"));
  } catch {
    return null;
  }
}

function _writeSettingsJson(fp, json) {
  try {
    fs.writeFileSync(fp, JSON.stringify(json, null, 2), "utf8");
    return true;
  } catch (e) {
    L.warn("anchor", `file write fail: ${e.message}`);
    return false;
  }
}

async function setAnchor(port) {
  const url = `http://127.0.0.1:${port}`;

  // 方法1: VS Code API (内存即时生效) — 每个键单独 try · 不因未注册键而中断
  for (const key of ["codeium.apiServerUrl", "codeium.inferenceApiServerUrl"]) {
    try {
      await vscode.workspace
        .getConfiguration()
        .update(key, url, vscode.ConfigurationTarget.Global);
    } catch (e) {
      L.warn("anchor", `API set ${key} fail: ${e.message}`);
    }
  }

  // 方法2: 直写 settings.json (磁盘持久化 · 兜底)
  try {
    const sp = _settingsJsonPath();
    const json = _readSettingsJson(sp);
    if (json) {
      json["codeium.apiServerUrl"] = url;
      json["codeium.inferenceApiServerUrl"] = url;
      if (_writeSettingsJson(sp, json)) {
        L.info("anchor", `file set ${url} → ${sp}`);
      }
    } else {
      L.warn("anchor", `settings.json unreadable: ${sp}`);
    }
  } catch (e) {
    L.warn("anchor", `file set fail: ${e.message}`);
  }

  _cachedAnchored = true;
  _cachedProxyUrl = url;
}

async function clearAnchor() {
  // 方法1: VS Code API
  try {
    const c = vscode.workspace.getConfiguration();
    await c.update(
      "codeium.apiServerUrl",
      undefined,
      vscode.ConfigurationTarget.Global,
    );
    await c.update(
      "codeium.inferenceApiServerUrl",
      undefined,
      vscode.ConfigurationTarget.Global,
    );
    try {
      await c.update(
        BACKUP_KEY_API,
        undefined,
        vscode.ConfigurationTarget.Global,
      );
    } catch {}
    try {
      await c.update(
        BACKUP_KEY_INFER,
        undefined,
        vscode.ConfigurationTarget.Global,
      );
    } catch {}
  } catch (e) {
    L.warn("anchor", `API clear fail: ${e.message}`);
  }

  // 方法2: 直写 settings.json
  const sp = _settingsJsonPath();
  const json = _readSettingsJson(sp);
  if (json) {
    delete json["codeium.apiServerUrl"];
    delete json["codeium.inferenceApiServerUrl"];
    delete json[BACKUP_KEY_API];
    delete json[BACKUP_KEY_INFER];
    _writeSettingsJson(sp, json);
    L.info("anchor", `file cleared → ${sp}`);
  }

  _cachedAnchored = false;
  L.info("anchor", "cleared → Windsurf defaults");
}

// 同步清锚 · 仅文件 · 用于 deactivate 等需极速清理的场景
// VS Code API 异步且可能失败 (codeium.* 非注册键) · 文件直写最可靠
function _clearAnchorFileSync() {
  try {
    const sp = _settingsJsonPath();
    const json = _readSettingsJson(sp);
    if (json) {
      let changed = false;
      for (const k of [
        "codeium.apiServerUrl",
        "codeium.inferenceApiServerUrl",
        BACKUP_KEY_API,
        BACKUP_KEY_INFER,
      ]) {
        if (k in json) {
          delete json[k];
          changed = true;
        }
      }
      if (changed) {
        _writeSettingsJson(sp, json);
        L.info("anchor", `file-sync cleared → ${sp}`);
      }
    }
  } catch (e) {
    L.warn("anchor", `file-sync clear fail: ${e.message}`);
  }
  _cachedAnchored = false;
}

function isAnchored() {
  // 检查 VS Code API
  try {
    const c = vscode.workspace.getConfiguration();
    if (c.get("codeium.apiServerUrl") === _cachedProxyUrl) return true;
  } catch {}
  // 兜底: 检查文件
  try {
    const json = _readSettingsJson(_settingsJsonPath());
    if (json && json["codeium.apiServerUrl"] === _cachedProxyUrl) return true;
  } catch {}
  return false;
}

// ═══════════════════════════ HTTP 工具 ═══════════════════════════
function httpGetJson(url, timeoutMs) {
  return new Promise((resolve) => {
    try {
      const req = http.get(
        url,
        {
          timeout: timeoutMs || 3000,
          agent: false,
          headers: { connection: "close" },
        },
        (res) => {
          let body = "";
          res.setEncoding("utf8");
          res.on("data", (c) => (body += c));
          res.on("end", () => {
            try {
              resolve(JSON.parse(body));
            } catch {
              resolve(null);
            }
          });
        },
      );
      req.on("error", () => resolve(null));
      req.on("timeout", () => {
        try {
          req.destroy();
        } catch {}
        resolve(null);
      });
    } catch {
      resolve(null);
    }
  });
}

function httpPostJson(url, data, timeoutMs) {
  return new Promise((resolve) => {
    try {
      const payload = JSON.stringify(data);
      const u = new (require("node:url").URL)(url);
      const req = http.request(
        {
          hostname: u.hostname,
          port: u.port,
          path: u.pathname,
          method: "POST",
          timeout: timeoutMs || 3000,
          headers: {
            "content-type": "application/json",
            "content-length": Buffer.byteLength(payload),
            connection: "close",
          },
          agent: false,
        },
        (res) => {
          let body = "";
          res.setEncoding("utf8");
          res.on("data", (c) => (body += c));
          res.on("end", () => {
            try {
              resolve(JSON.parse(body));
            } catch {
              resolve(null);
            }
          });
        },
      );
      req.on("error", () => resolve(null));
      req.on("timeout", () => {
        try {
          req.destroy();
        } catch {}
        resolve(null);
      });
      req.write(payload);
      req.end();
    } catch {
      resolve(null);
    }
  });
}

function httpDelete(url, timeoutMs) {
  return new Promise((resolve) => {
    try {
      const u = new (require("node:url").URL)(url);
      const req = http.request(
        {
          hostname: u.hostname,
          port: u.port,
          path: u.pathname,
          method: "DELETE",
          timeout: timeoutMs || 3000,
          headers: { connection: "close" },
          agent: false,
        },
        (res) => {
          let body = "";
          res.setEncoding("utf8");
          res.on("data", (c) => (body += c));
          res.on("end", () => {
            try {
              resolve(JSON.parse(body));
            } catch {
              resolve(null);
            }
          });
        },
      );
      req.on("error", () => resolve(null));
      req.on("timeout", () => {
        try {
          req.destroy();
        } catch {}
        resolve(null);
      });
      req.end();
    } catch {
      resolve(null);
    }
  });
}

// ═══════════════════════════ SSE 客户端 ═══════════════════════════
// 订阅 源.js /origin/stream · 事件: hello/turn/mode/hb
// 断自愈: 指数退避 max 30s · 无 proxy 时静默重试
class DaoSseClient extends EventEmitter {
  constructor(port) {
    super();
    this._port = port || DEFAULT_PORT;
    this._req = null;
    this._res = null;
    this._reconnectTimer = null;
    this._backoffMs = 1000;
    this._stopped = false;
    this._connected = false;
    this._buf = "";
  }
  setPort(p) {
    if (p && p !== this._port) {
      this._port = p;
      this._close();
      if (!this._stopped) this._scheduleReconnect(100);
    }
  }
  isConnected() {
    return this._connected;
  }
  start() {
    this._stopped = false;
    this._connect();
  }
  stop() {
    this._stopped = true;
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    this._close();
    this.removeAllListeners();
  }
  _close() {
    this._connected = false;
    try {
      if (this._req) this._req.destroy();
    } catch {}
    this._req = null;
    this._res = null;
    this._buf = "";
  }
  _scheduleReconnect(ms) {
    if (this._stopped) return;
    if (this._reconnectTimer) clearTimeout(this._reconnectTimer);
    this._reconnectTimer = setTimeout(
      () => {
        this._reconnectTimer = null;
        this._connect();
      },
      ms != null ? ms : this._backoffMs,
    );
    this._backoffMs = Math.min(30000, Math.max(1000, this._backoffMs * 2));
  }
  _connect() {
    if (this._stopped || this._req) return;
    try {
      this._req = http.get(
        `http://127.0.0.1:${this._port}/origin/stream?replay=1`,
        {
          headers: { accept: "text/event-stream", "cache-control": "no-cache" },
          agent: false,
          timeout: 5000,
        },
        (res) => {
          this._res = res;
          if (res.statusCode !== 200) {
            res.resume();
            this._close();
            this._scheduleReconnect();
            return;
          }
          this._connected = true;
          this._backoffMs = 1000;
          try {
            if (res.socket && res.socket.setTimeout) res.socket.setTimeout(0);
          } catch {}
          try {
            this.emit("connect", { port: this._port });
          } catch {}
          res.setEncoding("utf8");
          res.on("data", (chunk) => this._onData(chunk));
          res.on("end", () => {
            this._close();
            if (!this._stopped) this._scheduleReconnect();
          });
          res.on("error", () => {
            this._close();
            if (!this._stopped) this._scheduleReconnect();
          });
        },
      );
      this._req.on("error", () => {
        this._close();
        if (!this._stopped) this._scheduleReconnect();
      });
      this._req.on("timeout", () => {
        try {
          this._req && this._req.destroy();
        } catch {}
      });
    } catch {
      this._close();
      if (!this._stopped) this._scheduleReconnect();
    }
  }
  _onData(chunk) {
    this._buf += chunk;
    let idx;
    while ((idx = this._buf.indexOf("\n\n")) >= 0) {
      const raw = this._buf.slice(0, idx);
      this._buf = this._buf.slice(idx + 2);
      this._dispatch(raw);
    }
  }
  _dispatch(raw) {
    let eventType = "message";
    const dataLines = [];
    for (const line of raw.split("\n")) {
      if (line.startsWith("event:")) eventType = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (!dataLines.length) return;
    const dataStr = dataLines.join("\n");
    let data = dataStr;
    try {
      data = JSON.parse(dataStr);
    } catch {}
    try {
      this.emit(eventType, data);
      this.emit("event", { type: eventType, data });
    } catch {}
  }
}

// ═══════════════════════════ 数据采集 · proxy-only ═══════════════════════════
function withTimeout(promise, ms) {
  return Promise.race([
    promise,
    new Promise((resolve) => setTimeout(() => resolve(null), ms)),
  ]);
}

async function gatherEssence(port) {
  if (!port)
    return { ts: new Date().toISOString(), proxy: null, proxyUp: false };
  const ping = await withTimeout(
    httpGetJson(`http://127.0.0.1:${port}/origin/ping`, 1500),
    2500,
  );
  if (!ping)
    return { ts: new Date().toISOString(), proxy: null, proxyUp: false };
  const [proxy, realprompt] = (await withTimeout(
    Promise.all([
      httpGetJson(`http://127.0.0.1:${port}/origin/preview`, 4000),
      httpGetJson(`http://127.0.0.1:${port}/origin/realprompt?full=1`, 4000),
    ]),
    6000,
  )) || [null, null];
  const diag = {
    proxy_up: true,
    proxy_capturing: !!(proxy && proxy.has_captured_before),
    has_main: proxy ? !!proxy.has_main : false,
    aux_count: proxy ? proxy.aux_count || 0 : 0,
    agent_class: proxy && proxy.agent_class ? proxy.agent_class : null,
    proxy_stale: proxy && proxy.age_s != null && proxy.age_s > 300,
    mode: ping.mode,
    uptime_s: ping.uptime_s,
    req_total: ping.req_total,
    capture_count: ping.capture_count,
  };
  return {
    ts: new Date().toISOString(),
    proxy,
    realprompt,
    proxyUp: true,
    diag,
    ping,
  };
}

// ═══════════════════════════ 模式状态文本 ═══════════════════════════
function getModeLabel() {
  const mode = proxyGetMode();
  if (mode === "invert") return `道Agent · :${_cachedPort}`;
  return `官方Agent · 直连`;
}

// ═══════════════════════════ EssenceProvider · 本源观照 webview ═══════════════════════════
class EssenceProvider {
  constructor(ctx) {
    this._ctx = ctx;
    this._view = null;
    this._timer = null;
    this._sigTimer = null;
    this._busy = false;
    this._lastSig = "";
    this._sse = null;
    this._sseLastSpSig = "";
    this._setupSse();
  }

  _setupSse() {
    try {
      this._sse = new DaoSseClient(_cachedPort);
      this._sse.on("sp", (ev) => {
        if (!this._view) return;
        const sig = ev && ev.sig;
        if (sig && sig === this._sseLastSpSig) return;
        this._sseLastSpSig = sig || "";
        this.forceRefresh().catch(() => {});
      });
      this._sse.on("mode", (ev) => {
        if (!this._view) return;
        _cachedMode = (ev && ev.mode) || _cachedMode;
        try {
          this._view.webview.postMessage({ type: "mode", mode: ev && ev.mode });
        } catch {}
      });
      this._sse.on("connect", () => {
        if (this._view) this.forceRefresh().catch(() => {});
      });
      this._sse.start();
    } catch {
      this._sse = null;
    }
  }

  resolveWebviewView(webviewView) {
    this._view = webviewView;
    webviewView.webview.options = {
      enableScripts: true,
      // portMapping: webview 内部 127.0.0.1:_cachedPort 直通 extensionHost 端
      portMapping: [
        { webviewPort: _cachedPort, extensionHostPort: _cachedPort },
      ],
    };
    webviewView.webview.onDidReceiveMessage(async (msg) => {
      if (!msg) return;
      try {
        if (msg.command === "refresh") await this.refresh();
        else if (msg.command === "setMode") await this._handleSetMode(msg.mode);
        else if (msg.command === "getCustomSP") await this._handleGetCustomSP();
        else if (msg.command === "setCustomSP")
          await this._handleSetCustomSP(msg);
        else if (msg.command === "resetCustomSP")
          await this._handleResetCustomSP();
        else if (msg.command === "purge")
          await vscode.commands.executeCommand("dao.purge");
      } catch {}
    });
    webviewView.webview.html = getEssenceHtml(_cachedPort);
    webviewView.onDidChangeVisibility(() => {
      if (webviewView.visible) {
        this.refresh().catch(() => {});
        this._armTimer();
      } else this._stopTimer();
    });
    webviewView.onDidDispose(() => {
      this._view = null;
      this._stopTimer();
    });
    this._armTimer();
    // 主动首推 · 不依赖 webview 'refresh' 消息 (CSP/race-safe · 反者道之动)
    setTimeout(() => this.refresh().catch(() => {}), 200);
    setTimeout(() => this.refresh().catch(() => {}), 1500);
    setTimeout(() => this.refresh().catch(() => {}), 5000);
  }

  _armTimer() {
    this._stopTimer();
    if (!this._view || !this._view.visible) return;
    // v7.3: 后备 timer 12s, sig poll 1.5s (sig 接 _customSP.at + sp_sig + custom_sig)
    this._timer = setInterval(() => this.refresh().catch(() => {}), 12000);
    this._sigTimer = setInterval(() => this._sigTick().catch(() => {}), 1500);
  }

  _stopTimer() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
    if (this._sigTimer) {
      clearInterval(this._sigTimer);
      this._sigTimer = null;
    }
  }

  async _sigTick() {
    if (!this._view || !this._view.visible || this._busy) return;
    if (this._sse)
      try {
        this._sse.setPort(_cachedPort);
      } catch {}
    if (this._sse && this._sse.isConnected()) {
      this._sigSkipCounter = (this._sigSkipCounter || 0) + 1;
      if (this._sigSkipCounter % 10 !== 0) return;
    }
    try {
      const sig = await httpGetJson(
        `http://127.0.0.1:${_cachedPort}/origin/sig`,
        800,
      );
      if (!sig || !sig.ok) return;
      // v7.3: sig 接 _customSP 之 custom_sig + custom_sp_at, 编辑后即触刷
      const cur = `${sig.mode}|${sig.sp_sig}|${sig.custom_sig || "0"}|${sig.custom_sp_at || 0}`;
      if (cur === this._lastSig) return;
      this._lastSig = cur;
      this.refresh().catch(() => {});
    } catch {}
  }

  async refresh() {
    if (!this._view) return;
    if (this._busy) return;
    this._busy = true;
    try {
      const data = await gatherEssence(_cachedPort);
      if (!this._view) return;
      data.modeLabel = getModeLabel();
      // 注入端口号供 webview 直连 fallback
      data._port = _cachedPort;
      try {
        const ok = await this._view.webview.postMessage({ type: "data", data });
        if (!ok)
          L.warn("refresh", "postMessage returned false (webview not ready?)");
      } catch (e) {
        L.warn("refresh", `postMessage error: ${e.message}`);
      }
    } catch (e) {
      L.warn("refresh", `gather/send error: ${e.message}`);
    } finally {
      this._busy = false;
    }
  }

  async forceRefresh() {
    this._busy = false;
    await this.refresh();
  }

  async _handleSetMode(mode) {
    if (mode === "dao" || mode === "invert") await cmdInvert();
    else await cmdPassthrough();
    this._lastSig = "";
    setTimeout(() => this.forceRefresh().catch(() => {}), 300);
  }

  async _handleGetCustomSP() {
    if (!this._view) return;
    try {
      const r = await httpGetJson(
        `http://127.0.0.1:${_cachedPort}/origin/custom_sp`,
        2000,
      );
      await this._view.webview.postMessage({
        type: "customSP",
        action: "get",
        has_custom: r && r.has_custom,
        sp: r && r.sp,
        chars: r && r.chars,
        keep_blocks: r && r.keep_blocks,
      });
    } catch {
      try {
        await this._view.webview.postMessage({
          type: "customSP",
          action: "get",
          has_custom: false,
        });
      } catch {}
    }
  }

  async _handleSetCustomSP(msg) {
    if (!this._view) return;
    try {
      // v7.8 一态整替 · keep_blocks 永 false (服务端 invertSP 永整替, 字段仅兼容旧版)
      const r = await httpPostJson(
        `http://127.0.0.1:${_cachedPort}/origin/custom_sp`,
        { sp: msg.sp, keep_blocks: false, source: "webview" },
        3000,
      );
      await this._view.webview.postMessage({
        type: "customSP",
        action: "set",
        ok: r && r.ok,
        chars: r && r.chars,
        error: r && r.error,
      });
      if (r && r.ok) {
        this._lastSig = "";
        setTimeout(() => this.forceRefresh().catch(() => {}), 300);
      }
    } catch (e) {
      try {
        await this._view.webview.postMessage({
          type: "customSP",
          action: "set",
          ok: false,
          error: e.message,
        });
      } catch {}
    }
  }

  async _handleResetCustomSP() {
    if (!this._view) return;
    try {
      const r = await httpDelete(
        `http://127.0.0.1:${_cachedPort}/origin/custom_sp`,
        2000,
      );
      await this._view.webview.postMessage({
        type: "customSP",
        action: "reset",
        ok: r && r.ok,
      });
      if (r && r.ok) {
        this._lastSig = "";
        setTimeout(() => this.forceRefresh().catch(() => {}), 300);
      }
    } catch {
      try {
        await this._view.webview.postMessage({
          type: "customSP",
          action: "reset",
          ok: false,
        });
      } catch {}
    }
  }

  dispose() {
    this._stopTimer();
    try {
      if (this._sse) this._sse.stop();
    } catch {}
    this._sse = null;
    this._view = null;
  }
}

// ═══════════════════════════ 命令: 道Agent ═══════════════════════════
async function cmdInvert() {
  try {
    const { port } = cfg();
    const wasAnchored = _cachedAnchored;
    await proxyStart(port, "invert");
    proxySetMode("invert");
    await setAnchor(port);
    installSpawnHook();
    // 首次锚定才需重启 LS · 已锚定则纯翻转模式即可
    if (!wasAnchored) {
      L.info("cmd-invert", `first anchor → killing LS`);
      const killed = await forceRestartLS();
      if (killed) {
        vscode.window.showInformationMessage(
          `道Agent · 已启 :${port} · LS 重启中`,
        );
      } else {
        const c = await vscode.window.showInformationMessage(
          `道Agent · 已启 · 未找到 LS`,
          "重载窗口",
          "稍后",
        );
        if (c === "重载窗口")
          await vscode.commands.executeCommand("workbench.action.reloadWindow");
      }
    } else {
      L.info("cmd-invert", `mode flipped → invert (zero-cost)`);
      vscode.window.showInformationMessage(
        `道Agent · 道德经 SP 注入 · 下次对话生效`,
      );
    }
  } catch (e) {
    vscode.window.showErrorMessage(`道Agent 启失: ${e && e.message}`);
    L.error("cmd-invert", e && e.message);
  }
}

// ═══════════════════════════ 命令: 官方Agent ═══════════════════════════
// 官方模式 = proxy 仍运行但透传 · 不改 SP · 可观照 · 零代价热切
async function cmdPassthrough() {
  try {
    const { port } = cfg();
    // 确保 proxy 运行 (观照需要)
    await proxyStart(port, "passthrough");
    proxySetMode("passthrough");
    L.info(
      "cmd-pass",
      `mode flipped → passthrough (proxy stays for observation)`,
    );
    vscode.window.showInformationMessage(
      `官方Agent · 透传观照 · SP 不改 · 下次对话生效`,
    );
  } catch (e) {
    vscode.window.showErrorMessage(`官方Agent 切换失败: ${e && e.message}`);
    L.error("cmd-pass", e && e.message);
  }
}

// ═══════════════════════════ 命令: 切换 ═══════════════════════════
async function cmdToggle() {
  const cur = proxyGetMode();
  if (cur === "invert") await cmdPassthrough();
  else await cmdInvert();
}

// ═══════════════════════════ 命令: 浏览器观 ═══════════════════════════
async function cmdOpenPreview() {
  const url = `http://127.0.0.1:${_cachedPort}/origin/preview`;
  try {
    await vscode.env.openExternal(vscode.Uri.parse(url));
  } catch {}
}

// ═══════════════════════════ 命令: 了事拂衣去 (净卸) ═══════════════════════════
async function cmdPurge() {
  const answer = await vscode.window.showWarningMessage(
    "了事拂衣去 · 水过无痕 · 将彻底卸载道Agent:\n" +
      "① 透传  ② 断钩  ③ 清锚  ④ 杀LS  ⑤ 停代理\n" +
      "⑥ 清持存  ⑦ 清残留  ⑧ 自卸插件\n" +
      "Windsurf 回归本源 · 零痕迹。确认？",
    { modal: true },
    "确认净卸",
  );
  if (answer !== "确认净卸") return;

  const out = logger();
  out.show(true);
  out.appendLine("\n══════ 了事拂衣去 · 水过无痕 · 净卸开始 ══════");

  // ── 顺序至关重要 · 反者道之动 ──
  // 先清锚+杀LS → 后停代理 · 防 LS 连死代理 → Windsurf 卡死

  // 1. 先设透传 · 过渡期 LS 若仍连代理 · 安全透传
  try {
    if (_proxyHandle && _proxyHandle.setMode)
      _proxyHandle.setMode("passthrough");
    out.appendLine("  ✓ 代理已设透传 (安全过渡)");
  } catch {}

  // 2. 卸 spawn hook · 新 LS 不再被截持
  try {
    _cachedAnchored = false;
    removeSpawnHook();
    out.appendLine("  ✓ spawn hook 已卸");
  } catch {}

  // 3. 清除所有 dao 相关 settings (文件直写 + API 双保险)
  // VS Code API 对 codeium.* 键可能失败 (非注册键) · 文件直写兜底
  try {
    _clearAnchorFileSync();
    // API 补清 dao.* 注册键 (这些能成功)
    const c = vscode.workspace.getConfiguration();
    for (const k of [
      "dao.origin.port",
      "dao.origin.defaultMode",
      "dao.origin.banner",
    ]) {
      try {
        await c.update(k, undefined, vscode.ConfigurationTarget.Global);
      } catch {}
    }
    out.appendLine("  ✓ 所有 dao 设置已清 (文件+API)");
  } catch (e) {
    out.appendLine(`  ⚠ 清设置: ${e.message}`);
  }

  // 4. 杀 LS · 使其重生 · 无钩无锚 → 直连官方
  try {
    const killed = await forceRestartLS();
    out.appendLine(`  ✓ LS ${killed ? "已杀 · 将重生直连官方" : "未找到"}`);
  } catch (e) {
    out.appendLine(`  ⚠ 杀LS: ${e.message}`);
  }

  // 5. 停反代 · 此时 LS 已死或已重生直连官方 · 安全
  try {
    await proxyStop();
    out.appendLine("  ✓ 反代已停");
  } catch (e) {
    out.appendLine(`  ⚠ 停反代: ${e.message}`);
  }

  // 6. 清 source.js 持存文件 (mode / lastinject / custom_sp)
  try {
    const vd = vendorDir();
    const persistFiles = [
      "_origin_mode.txt",
      "_lastinject.json",
      "_custom_sp.json",
    ];
    let cleaned = 0;
    for (const f of persistFiles) {
      const fp = path.join(vd, f);
      try {
        if (fs.existsSync(fp)) {
          fs.unlinkSync(fp);
          cleaned++;
        }
      } catch {}
    }
    out.appendLine(`  ✓ 持存文件: ${cleaned} 清`);
  } catch (e) {
    out.appendLine(`  ⚠ 清持存: ${e.message}`);
  }

  // 7. 清 ~/.dao-proxy 目录 (如存在)
  try {
    const daoProxyDir = path.join(os.homedir(), ".dao-proxy");
    if (fs.existsSync(daoProxyDir)) {
      fs.rmSync(daoProxyDir, { recursive: true, force: true });
      out.appendLine("  ✓ ~/.dao-proxy 已清");
    }
  } catch (e) {
    out.appendLine(`  ⚠ 清 .dao-proxy: ${e.message}`);
  }

  // 8. 清 .obsolete 中 dao/wam 残留
  try {
    const extDir = path.join(os.homedir(), ".windsurf", "extensions");
    const obsFile = path.join(extDir, ".obsolete");
    if (fs.existsSync(obsFile)) {
      const obs = JSON.parse(fs.readFileSync(obsFile, "utf8"));
      let removed = 0;
      for (const k of Object.keys(obs)) {
        if (/dao|wam/i.test(k)) {
          delete obs[k];
          removed++;
        }
      }
      if (removed > 0) {
        fs.writeFileSync(obsFile, JSON.stringify(obs), "utf8");
        out.appendLine(`  ✓ .obsolete: ${removed} 条 dao/wam 残留已清`);
      }
    }
  } catch (e) {
    out.appendLine(`  ⚠ 清 .obsolete: ${e.message}`);
  }

  // 9. 自卸插件
  out.appendLine("  → 卸载插件 dao-agi.dao-proxy-min ...");
  out.appendLine("══════ 了事拂衣去 · 水过无痕 · 道法自然 ══════\n");

  try {
    await vscode.commands.executeCommand(
      "workbench.extensions.uninstallExtension",
      "dao-agi.dao-proxy-min",
    );
  } catch (e) {
    out.appendLine(`  ⚠ 自卸: ${e.message} · 请手动卸载`);
  }

  // 9. 提示重载 (modal · 必看 · source.js child 与 webview 残皆需 reload 方彻底清)
  const reload = await vscode.window.showInformationMessage(
    "了事拂衣去 · 水过无痕 · Windsurf 已归本源\n\n" +
      "插件已自卸 · 设置已清 · LS 已重生直连官方\n" +
      "唯余 utility process 内 source.js child 与 webview 残相\n" +
      "立即重载方彻底归本然 · 道法自然",
    { modal: true },
    "立即重载",
    "稍后重载",
  );
  if (reload === "立即重载") {
    await vscode.commands.executeCommand("workbench.action.reloadWindow");
  }
}

// ═══════════════════════════ 命令: E2E 自检 ═══════════════════════════
async function cmdVerifyE2E() {
  await cmdSelftest();
}

// ═══════════════════════════ 命令: 自检 ═══════════════════════════
async function cmdSelftest() {
  const out = logger();
  out.show(true);
  out.appendLine("");
  out.appendLine("════════════════════════════════════════");
  out.appendLine(
    `  道Agent v${PKG_VERSION} · 自检 · ${new Date().toISOString()}`,
  );
  out.appendLine("════════════════════════════════════════");

  const { port } = cfg();

  // L1: selftest (via proxy HTTP endpoint)
  out.appendLine("\n── L1 · proto 单元 ──");
  try {
    const r = await httpGetJson(
      `http://127.0.0.1:${port}/origin/selftest`,
      5000,
    );
    if (r && r.cases) {
      out.appendLine(
        `  道德经: ${r.dao_chars || "?"}字 · ${r.summary || "?"} · ${r.ok ? "✓全绿" : "✗有失败"}`,
      );
      for (const c of r.cases || []) {
        out.appendLine(
          `  ${c.ok ? "✓" : "✗"} ${c.name}: ${c.in_bytes}→${c.out_bytes}B sp=${c.new_sp_chars}`,
        );
      }
    } else {
      out.appendLine("  ⚠ /origin/selftest 无响应 (代理未启?)");
    }
  } catch (e) {
    out.appendLine(`  ✗ L1 异: ${e.message}`);
  }

  // L2: proxy 路径
  out.appendLine("\n── L2 · 反代路径 ──");
  out.appendLine(
    `  port: ${port} (per-user) · anchored: ${isAnchored()} · mode: ${proxyGetMode()}`,
  );
  try {
    const ping = await httpGetJson(
      `http://127.0.0.1:${port}/origin/ping`,
      2000,
    );
    if (ping) {
      out.appendLine(
        `  ✓ proxy up: v=${ping.version} mode=${ping.mode} uptime=${ping.uptime_s}s req=${ping.req_total} cap=${ping.capture_count}`,
      );
    } else {
      out.appendLine("  ✗ proxy unreachable");
    }
  } catch (e) {
    out.appendLine(`  ✗ ping: ${e.message}`);
  }

  try {
    const last = await httpGetJson(
      `http://127.0.0.1:${port}/origin/last`,
      2000,
    );
    if (last && last.has_capture) {
      out.appendLine(
        `  最近替换: ${new Date(last.at).toISOString()} ${last.url}`,
      );
      out.appendLine(
        `    before(${last.before_bytes}B): ${(last.before_head || "").slice(0, 80)}…`,
      );
      out.appendLine(
        `    after(${last.after_bytes}B): ${(last.after_head || "").slice(0, 80)}…`,
      );
    }
  } catch {}

  try {
    const paths = await httpGetJson(
      `http://127.0.0.1:${port}/origin/paths?n=10`,
      2000,
    );
    if (paths && paths.top && paths.top.length) {
      out.appendLine(`\n  路径直方图 (${paths.total_paths} paths):`);
      for (const p of paths.top) {
        const tags = [];
        if (p.is_chat) tags.push("CHAT");
        if (p.replaced > 0) tags.push(`✓${p.replaced}`);
        out.appendLine(
          `    ${String(p.count).padStart(5)} ${p.path} [${tags.join(",")}]`,
        );
      }
    }
  } catch {}

  out.appendLine("\n── L3 · 活检指引 ──");
  out.appendLine(`  1. 运行 "道Agent: 启" → LS 重启 → 向 Cascade 问 '你是谁'`);
  out.appendLine(`  2. 期答含 '道'/'无为'/'自然' (道德经 SP 注入成功)`);
  out.appendLine("════════════════════════════════════════\n");
}

// ═══════════════════════════ HTML · 本源观照 ═══════════════════════════
function _genNonce() {
  // 32-char hex nonce · CSP-strict · 道法自然
  const a = new Uint8Array(16);
  for (let i = 0; i < 16; i++) a[i] = Math.floor(Math.random() * 256);
  return Array.from(a)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
function getEssenceHtml(proxyPort, nonce) {
  const N = nonce || _genNonce();
  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${N}' 'unsafe-inline'; connect-src http://127.0.0.1:* http://localhost:* https: http:; img-src data:;">
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    font-family: var(--vscode-font-family); color: var(--vscode-foreground);
    background: var(--vscode-sideBar-background, transparent);
    margin: 0; padding: 6px 8px; font-size: 12px; line-height: 1.55;
    display: flex; flex-direction: column;
  }
  .bar { display: flex; gap: 3px; align-items: center; margin-bottom: 3px; flex: 0 0 auto; font-size: 10px; flex-wrap: wrap; }
  .ib {
    padding: 2px 5px; font-size: 12px; border: 1px solid transparent;
    background: transparent; color: var(--vscode-foreground);
    cursor: pointer; border-radius: 2px; font-family: inherit;
    opacity: 0.65; min-width: 20px; line-height: 1;
  }
  .ib:hover { opacity: 1; background: var(--vscode-toolbar-hoverBackground, rgba(128,128,128,0.15)); }
  .ib.vw-act { opacity:1; color:#6bb86b; border-color:#6bb86b; background:rgba(107,184,107,0.06); }
  .ib.vw-orig { opacity:1; color:#d9a200; border-color:#d9a200; background:rgba(217,162,0,0.06); }
  .age-tick { font-family:monospace; font-size:9px; opacity:0.5; margin-left:3px; }
  .mb {
    padding: 1px 7px; font-size: 11px; border: 1px solid rgba(128,128,128,0.3);
    background: transparent; color: var(--vscode-foreground);
    cursor: pointer; border-radius: 3px; font-family: inherit;
    opacity: 0.55; line-height: 1.3; transition: all 0.15s; font-weight: 500;
  }
  .mb:hover { opacity: 1; background: var(--vscode-toolbar-hoverBackground, rgba(128,128,128,0.15)); }
  .mb.active { opacity: 1; border-color: var(--vscode-textLink-foreground, #4fc1ff); color: var(--vscode-textLink-foreground, #4fc1ff); background: rgba(79,193,255,0.1); font-weight: 700; }
  .mb.active-dao { border-color: #6bb86b; color: #6bb86b; background: rgba(107,184,107,0.1); }
  .mode-hint { font-size: 9px; opacity: 0.4; margin-left: 2px; }
  .dots { display: inline-flex; gap: 2px; align-items: center; padding: 0 4px; cursor: help; }
  .dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: rgba(128,128,128,0.3); }
  .dot.ok { background: #6bb86b; } .dot.warn { background: #d9a200; } .dot.err { background: #e08080; }
  .meta { margin-left: auto; opacity: 0.5; font-family: monospace; font-size: 10px; }
  .source { font-size: 9px; opacity: 0.5; margin: 0 0 3px; min-height: 12px; line-height: 1.4; }
  #sp {
    flex: 1 1 auto; overflow: auto; margin: 0; padding: 10px 12px;
    font-family: "Noto Serif CJK SC", "Microsoft YaHei", var(--vscode-editor-font-family), serif;
    font-size: 11.5px; line-height: 1.75; white-space: pre-wrap; word-break: break-word;
    background: rgba(0,0,0,0.08); border-radius: 3px;
  }
  #sp.quiet { text-align: center; opacity: 0.35; font-style: italic; padding: 40px 0; letter-spacing: 1px; }
  .ib.edit-active { opacity: 1; color: #e8a040; border-color: #e8a040; background: rgba(232,160,64,0.1); }
  #editArea { display: none; flex: 1 1 auto; flex-direction: column; }
  #editArea.show { display: flex; }
  #editArea textarea {
    flex: 1 1 auto; resize: none; border: 1px solid rgba(128,128,128,0.3); border-radius: 3px; padding: 8px 10px;
    font-family: "Noto Serif CJK SC", "Microsoft YaHei", var(--vscode-editor-font-family), serif;
    font-size: 11.5px; line-height: 1.75;
    background: var(--vscode-input-background, rgba(0,0,0,0.12)); color: var(--vscode-input-foreground, var(--vscode-foreground));
    outline: none; min-height: 120px;
  }
  #editArea textarea:focus { border-color: var(--vscode-focusBorder, #007fd4); }
  .edit-bar { display: flex; gap: 4px; align-items: center; margin-top: 4px; flex: 0 0 auto; font-size: 10px; }
  .edit-bar .eb {
    padding: 2px 8px; font-size: 10px; border: 1px solid rgba(128,128,128,0.3);
    background: transparent; color: var(--vscode-foreground); cursor: pointer; border-radius: 3px;
    font-family: inherit; line-height: 1.4; transition: all 0.15s;
  }
  .edit-bar .eb:hover { background: var(--vscode-toolbar-hoverBackground, rgba(128,128,128,0.15)); }
  .edit-bar .eb.save { border-color: #6bb86b; color: #6bb86b; }
  .edit-bar .eb.save:hover { background: rgba(107,184,107,0.15); }
  .edit-bar .eb.reset { border-color: #e08080; color: #e08080; }
  .edit-bar .eb.reset:hover { background: rgba(224,128,128,0.15); }
  .edit-bar .edit-status { opacity: 0.5; margin-left: auto; font-size: 9px; }
  .custom-badge { display: inline-block; font-size: 8px; padding: 0 4px; border-radius: 2px; background: rgba(232,160,64,0.2); color: #e8a040; border: 1px solid rgba(232,160,64,0.3); margin-left: 4px; }
</style>
</head>
<body>
  <div class="bar">
    <span class="dots" id="dots" title="Proxy\u00b7Capture\u00b7Mode"></span>
    <button class="mb" id="btnDao" title="\u9053Agent \u00b7 \u9053\u5fb7\u7ecfSP">\u9053</button>
    <button class="mb" id="btnOff" title="\u5b98\u65b9Agent \u00b7 \u539f\u5473SP">\u5b98</button>
    <span class="mode-hint" id="modeHint"></span>
    <button class="ib" id="refresh" title="\u5237\u65b0">\u27f3</button>
    <button class="ib" id="copy" title="\u590d\u5236">\u29c9</button>
    <button class="ib vw-act" id="viewToggle" title="\u5b9e\u6536/\u539f\u53d1">\u5b9e</button>
    <button class="ib" id="editToggle" title="\u7f16\u8f91\u6ce8\u5165SP">\u270e</button>
    <span id="customBadge"></span>
    <span class="meta" id="meta">\u2014</span>
    <span class="age-tick" id="ageTick"></span>
    <button class="ib" id="btnPurge" title="\u4e86\u4e8b\u62c2\u8863\u53bb \u00b7 \u6c34\u8fc7\u65e0\u75d5 \u00b7 \u5f7b\u5e95\u5378\u8f7d" style="margin-left:auto;opacity:0.35;font-size:11px;color:#e08080;">\u2716</button>
  </div>
  <div class="source" id="source"></div>
  <pre id="sp" class="quiet">\u89c2\u2026</pre>
  <noscript><div style="padding:16px;color:#e08080;font-size:11px">\u811a\u672c\u88abCSP\u62e6\u622a \u00b7 \u8bf7\u91cd\u8f7d</div></noscript>
  <div id="editArea">
    <textarea id="editText"></textarea>
    <div class="edit-bar">
      <button class="eb save" id="editSave" title="Ctrl+Enter">\u2714 \u6ce8\u5165</button>
      <button class="eb reset" id="editReset" title="\u6e05 _customSP \u00b7 \u56de\u9ed8\u9053\u5fb7\u7ecf\u8def\u5f84">\u2716 \u5f52\u9053</button>
      <span class="edit-status" id="editStatus"></span>
    </div>
  </div>
<script nonce="${N}">
(function() {
  var _PORT = ${proxyPort || 0};
  // ═══════ v4.5 stage tracker · 道法自然 · 闭环可观察 ═══════
  function _stage(s) { try { document.body.setAttribute('data-dao-stage', String(s).substring(0,80)); } catch(_) {} }
  _stage('iife-start');
  try { document.body.setAttribute('data-dao-script', 'running'); } catch(_) {}

  // ═══════ v4.5 早期渲染 · 反者道之动 · 不依赖 vsc / postMessage / listener ═══════
  // 即便后续脚本死, #sp 仍能从 source.js 直拉道德经文.
  var _hasRendered = false;
  function _earlyRender(tag) {
    if (_hasRendered || !_PORT) { if (!_PORT) _stage('no-port'); return; }
    try {
      var ctrl = (typeof AbortController === 'function') ? new AbortController() : null;
      if (ctrl) setTimeout(function(){ try{ ctrl.abort(); }catch(_){} }, 4000);
      fetch('http://127.0.0.1:' + _PORT + '/origin/preview', ctrl ? { signal: ctrl.signal } : {})
        .then(function(r){ if (!r.ok) throw new Error('http ' + r.status); return r.json(); })
        .then(function(p){
          if (!p) { _stage(tag + ':empty'); return; }
          var sp = document.getElementById('sp');
          if (!sp) { _stage(tag + ':no-sp'); return; }
          var text = p.after || p.before;
          if (!text) { _stage(tag + ':no-text'); return; }
          if (sp.classList.contains('quiet') || sp.textContent === '\u89c2\u2026' || !_hasRendered) {
            sp.classList.remove('quiet');
            sp.textContent = text;
            var meta = document.getElementById('meta');
            if (meta) meta.textContent = (p.after_chars || p.before_chars || text.length) + ' \u5b57';
            var srcEl = document.getElementById('source');
            if (srcEl) srcEl.textContent = (p.mode === 'invert' ? '\u5b9e\u6536' : '\u539f\u53d1') + ' · v7.6\u4e3a\u9053\u65e5\u635f\u00b7\u9053\u6cd5\u81ea\u7136 · ' + tag;
            _hasRendered = true;
            _stage(tag + ':ok');
          }
        })
        .catch(function(e){
          _stage(tag + ':fail:' + (e && e.message ? e.message.substring(0,32) : '?'));
        });
    } catch(e) {
      _stage(tag + ':throw:' + (e.message||'?').substring(0,32));
    }
  }
  _earlyRender('e0');
  setTimeout(function(){ _earlyRender('e1'); }, 600);
  setTimeout(function(){ _earlyRender('e2'); }, 2500);
  setTimeout(function(){ _earlyRender('e3'); }, 8000);

  // ═══════ v4.5 错误显形 · 脚本任意错均回写 #sp 让人可见 ═══════
  window.addEventListener('error', function(e) {
    _stage('err:' + ((e && e.message) || '?').substring(0,40));
    try {
      var sp = document.getElementById('sp');
      if (sp && (sp.classList.contains('quiet') || sp.textContent === '\u89c2\u2026') && !_hasRendered) {
        sp.classList.remove('quiet');
        sp.style.color = '#e08080';
        sp.style.whiteSpace = 'pre-wrap';
        sp.style.fontSize = '10px';
        sp.style.fontFamily = 'monospace';
        sp.style.textAlign = 'left';
        sp.style.padding = '8px';
        sp.textContent = '\u3010v4.5\u8bca\u3011\u811a\u672c\u9519\\n' + (e.message||'?') + '\\n@' + ((e.filename||'').split(/[\\/]/).pop()) + ':' + (e.lineno||0) + ':' + (e.colno||0);
      }
    } catch(_) {}
  });

  // ═══════ v4.5 vsc 容错 · acquireVsCodeApi 抛错也不死 IIFE ═══════
  var vsc;
  try {
    vsc = acquireVsCodeApi();
    _stage('vsc-ok');
  } catch(e) {
    vsc = { postMessage: function(){ return false; }, setState: function(){}, getState: function(){ return null; }, _ghost: true };
    _stage('vsc-fail:' + (e.message||'?').substring(0,32));
  }

  var $sp = document.getElementById('sp');
  var $meta = document.getElementById('meta');
  var $source = document.getElementById('source');
  var $dots = document.getElementById('dots');
  var $btnDao = document.getElementById('btnDao');
  var $btnOff = document.getElementById('btnOff');
  var $modeHint = document.getElementById('modeHint');
  var lastText = '';
  var curMode = '';
  var viewMode = 'actual';
  var lastProxyData = null;
  var _ageBase = null, _ageTimer = null;

  function setModeUI(mode) {
    curMode = mode || 'passthrough';
    $btnDao.classList.remove('active', 'active-dao');
    $btnOff.classList.remove('active');
    if (curMode === 'invert') { $btnDao.classList.add('active', 'active-dao'); $modeHint.textContent = '\u9053'; }
    else { $btnOff.classList.add('active'); $modeHint.textContent = '\u5b98'; }
  }
  $btnDao.addEventListener('click', function() { if (curMode === 'invert') return; setModeUI('invert'); $source.textContent = '\u5207\u6362\u4e2d \u2192 \u9053Agent\u2026'; vsc.postMessage({ command: 'setMode', mode: 'dao' }); });
  $btnOff.addEventListener('click', function() { if (curMode === 'passthrough') return; setModeUI('passthrough'); $source.textContent = '\u5207\u6362\u4e2d \u2192 \u5b98\u65b9Agent\u2026'; vsc.postMessage({ command: 'setMode', mode: 'official' }); });
  document.getElementById('refresh').addEventListener('click', function() { vsc.postMessage({ command: 'refresh' }); });
  document.getElementById('copy').addEventListener('click', function() {
    if (!lastText) return;
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(lastText);
    else { var ta = document.createElement('textarea'); ta.value = lastText; document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); } catch(e) {} document.body.removeChild(ta); }
  });

  var $viewToggle = document.getElementById('viewToggle');
  var $ageTick = document.getElementById('ageTick');
  function updateViewToggle() {
    if (!$viewToggle) return;
    $viewToggle.classList.remove('vw-act', 'vw-orig');
    if (viewMode === 'actual') { $viewToggle.textContent = '\u5b9e'; $viewToggle.classList.add('vw-act'); }
    else { $viewToggle.textContent = '\u539f'; $viewToggle.classList.add('vw-orig'); }
  }
  if ($viewToggle) $viewToggle.addEventListener('click', function() {
    viewMode = viewMode === 'actual' ? 'original' : 'actual';
    updateViewToggle();
    if (lastProxyData) reRenderProxy();
  });
  function reRenderProxy() {
    if (!lastProxyData) return;
    var proxy = lastProxyData;
    var ts = new Date().toLocaleTimeString();
    if (viewMode === 'actual' && proxy.mode === 'invert' && proxy.after) {
      showText(proxy.after, ts);
      $source.textContent = '\u5b9e\u6536 \u00b7 LLM\u5b9e\u6536 \u00b7 ' + (proxy.after_chars || proxy.after.length) + '\u5b57';
    } else if (proxy.before) {
      showText(proxy.before, ts);
      $source.textContent = '\u539f\u53d1 \u00b7 Windsurf\u62df\u53d1 \u00b7 ' + (proxy.before_chars || proxy.before.length) + '\u5b57';
    } else if (proxy.after) {
      showText(proxy.after, ts);
      $source.textContent = proxy.synthesized ? '\u9053\u5fb7\u7ecf\u6ce8\u5165' : '\u900f\u4f20';
    }
    startAgeTick(proxy.age_s);
  }
  function startAgeTick(age_s) {
    if (_ageTimer) { clearInterval(_ageTimer); _ageTimer = null; }
    if (!$ageTick) return;
    if (age_s == null) { $ageTick.textContent = ''; return; }
    _ageBase = { s: age_s, at: Date.now() };
    var tick = function() { if (!_ageBase) return; var c = _ageBase.s + Math.round((Date.now() - _ageBase.at) / 1000); $ageTick.textContent = c + 's\u524d'; };
    tick(); _ageTimer = setInterval(tick, 1000);
  }
  updateViewToggle();

  function setDots(dg) {
    $dots.innerHTML = '';
    if (!dg) return;
    var items = [
      { k: 'proxy_up', label: 'Proxy' },
      { k: 'proxy_capturing', label: 'Capture' },
    ];
    var tipBits = [];
    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      var on = !!dg[item.k];
      var d = document.createElement('span');
      d.className = 'dot ' + (on ? 'ok' : (item.k === 'proxy_capturing' ? 'warn' : 'err'));
      $dots.appendChild(d);
      tipBits.push(item.label + ':' + (on ? '\u2713' : '\u2717'));
    }
    if (dg.mode) tipBits.push('M:' + dg.mode);
    if (dg.uptime_s != null) tipBits.push(dg.uptime_s + 's');
    if (dg.req_total != null) tipBits.push('req:' + dg.req_total);
    if (dg.capture_count != null) tipBits.push('cap:' + dg.capture_count);
    $dots.title = tipBits.join(' \u00b7 ');
  }

  function renderView(d) {
    var proxy = d.proxy;
    var ts = d.ts ? new Date(d.ts).toLocaleTimeString() : '';
    setDots(d.diag);
    if (proxy) lastProxyData = proxy;
    updateViewToggle();

    // realprompt 优先
    var realprompt = d.realprompt;
    var rpReliable = !!(realprompt && realprompt.has && realprompt.sp && realprompt.chars >= 2000);

    if (viewMode === 'actual' && proxy && proxy.mode === 'invert' && proxy.after) {
      showText(proxy.after, ts);
      // v7.3: synthesized_from 区分真捕获 vs 合成 sample, 让用户知所见之态
      var src;
      if (proxy.synthesized_from === 'captured') src = '\u5b9e\u6536 \u00b7 LLM\u5b9e\u6536 (\u771f\u6355\u83b7)';
      else if (proxy.synthesized_from === 'sample') src = '\u9884\u89c8 \u00b7 \u5408\u6210sample\u00b7\u4e0eLLM\u5b9e\u6536\u540c\u7ed3\u6784';
      else src = '\u5b9e\u6536 \u00b7 LLM\u5b9e\u6536';
      if (proxy.custom_sp) src += ' \u00b7 \u81ea\u5b9a\u4e49' + (proxy.custom_sp_chars ? proxy.custom_sp_chars + '\u5b57' : '');
      src += ' \u00b7 ' + (proxy.after_chars || proxy.after.length) + '\u5b57';
      $source.textContent = src;
      startAgeTick(proxy.age_s);
      setModeUI('invert');
      return;
    }

    if (rpReliable) {
      showText(realprompt.sp, ts);
      $source.textContent = '\u6355\u83b7\u8f68 \u00b7 ' + realprompt.chars + '\u5b57';
      startAgeTick(realprompt.age_s);
      return;
    }

    if (proxy && proxy.before && proxy.before.length >= 2000) {
      showText(proxy.before, ts);
      $source.textContent = '\u539f\u53d1 \u00b7 ' + proxy.before.length + '\u5b57';
      startAgeTick(proxy.age_s);
    } else if (proxy && proxy.after) {
      showText(proxy.after, ts);
      $source.textContent = proxy.synthesized ? '\u9053\u5fb7\u7ecf\u6ce8\u5165' : '\u900f\u4f20';
      startAgeTick(proxy.age_s);
    } else {
      showEmpty(ts);
      startAgeTick(null);
    }

    var ml = d.modeLabel || '';
    if (/\u9053\\s*Agent/.test(ml)) setModeUI('invert');
    else setModeUI('passthrough');
  }

  function showText(text, ts) {
    var changed = text !== lastText;
    lastText = text;
    $sp.classList.remove('quiet');
    $sp.innerHTML = '';
    $sp.textContent = text;
    $meta.textContent = text.length + ' \u5b57 \u00b7 ' + ts;
    if (changed) try { $sp.scrollTop = 0; } catch(_) {}
  }
  function showEmpty(ts) {
    $sp.classList.add('quiet');
    $sp.textContent = '\u81f4\u865a\u5b88\u9759 \u00b7 \u8bf7\u5411Cascade\u53d1\u6d88\u606f\u89e6\u53d1\u91c7\u96c6';
    $meta.textContent = ts;
    $source.textContent = '';
    lastText = '';
  }

  // 编辑模式 · v7.8 反者道之动 · 所见即所改, 所改即所注 · 一态整替
  // 编辑切换 → textarea 装当前面板"实时注入"全文 (lastText / _customSP.sp)
  // 保存 → _customSP.sp = textarea 文 → 下次反代 LLM 实收即此文
  var $editToggle = document.getElementById('editToggle');
  var $editArea = document.getElementById('editArea');
  var $editText = document.getElementById('editText');
  var $editSave = document.getElementById('editSave');
  var $editReset = document.getElementById('editReset');
  var $editStatus = document.getElementById('editStatus');
  var $customBadge = document.getElementById('customBadge');
  var editMode = false;
  var _editClosing = null;

  function _closeEditMode() {
    editMode = false;
    $editArea.classList.remove('show');
    $editToggle.classList.remove('edit-active');
    $sp.style.display = '';
    if (_editClosing) { clearTimeout(_editClosing); _editClosing = null; }
  }

  $editToggle.addEventListener('click', function() {
    editMode = !editMode;
    if (editMode) {
      $editArea.classList.add('show'); $editToggle.classList.add('edit-active'); $sp.style.display = 'none';
      // v7.8 所见即所改: textarea 立装当前面板显文 (即"实时注入"全文)
      // 既有 _customSP.sp → 同 lastText (一致), 无 _customSP → 装当前 invertSP 之 after
      // 服务端 getCustomSP 拉真值, 若已设则覆盖 (但通常与 lastText 同, 因 webview 显的就是 _customSP.sp)
      $editText.value = lastText || '';
      $editStatus.textContent = '';
      vsc.postMessage({ command: 'getCustomSP' });
      $editText.focus();
    } else { _closeEditMode(); }
  });
  $editSave.addEventListener('click', function() {
    var sp = $editText.value;
    if (!sp || !sp.trim()) { $editStatus.textContent = '\u2716 \u5185\u5bb9\u4e0d\u53ef\u4e3a\u7a7a'; return; }
    $editStatus.textContent = '\u4fdd\u5b58\u4e2d\u2026';
    // v7.8 一态整替 · 不再传 keep_blocks (服务端忽略, 永整替)
    vsc.postMessage({ command: 'setCustomSP', sp: sp.trim() });
  });
  $editReset.addEventListener('click', function() { $editStatus.textContent = '\u6e05\u9664\u4e2d\u2026'; vsc.postMessage({ command: 'resetCustomSP' }); });
  $editText.addEventListener('keydown', function(e) { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); $editSave.click(); } });

  function updateCustomBadge(isCustom, chars) {
    if (isCustom) $customBadge.innerHTML = '<span class="custom-badge">\u81ea\u5b9a\u4e49' + (chars ? ' ' + chars + '\u5b57' : '') + '</span>';
    else $customBadge.innerHTML = '';
  }

  window.addEventListener('message', function(e) {
    if (!e.data) return;
    if (e.data.type === 'data') {
      renderView(e.data.data);
      var proxy = e.data.data.proxy;
      if (proxy && proxy.custom_sp != null) updateCustomBadge(proxy.custom_sp, proxy.custom_sp_chars);
    }
    if (e.data.type === 'mode') setModeUI(e.data.mode);
    if (e.data.type === 'customSP') {
      var r = e.data;
      if (r.action === 'get') {
        // v7.8: 已设则覆盖 lastText 之初值 (虽通常一致, 防 race)
        if (r.has_custom && r.sp) {
          $editText.value = r.sp;
          updateCustomBadge(true, r.chars);
          $editStatus.textContent = '\u81ea\u5b9a\u4e49 \u00b7 ' + (r.chars || 0) + '\u5b57';
        } else {
          // 未设: 留 lastText 初值不变, 用户编辑当前显之全文即可
          $editStatus.textContent = '\u672a\u8bbe \u00b7 \u53ef\u7f16\u5f53\u524d\u5b9e\u6536';
        }
      } else if (r.action === 'set') {
        if (r.ok) {
          $editStatus.textContent = '\u2714 \u5df2\u6ce8\u5165 ' + (r.chars || 0) + '\u5b57 \u00b7 1.5s\u540e\u5173\u95ed';
          updateCustomBadge(true, r.chars);
          // v7.3 新: 1.5s 自关闭编辑面板, 让用户立即见 LLM 实收效果
          if (_editClosing) clearTimeout(_editClosing);
          _editClosing = setTimeout(_closeEditMode, 1500);
        } else $editStatus.textContent = '\u2716 \u5931\u8d25: ' + (r.error || '?');
      } else if (r.action === 'reset') {
        if (r.ok) {
          $editStatus.textContent = '\u2714 \u5df2\u6e05\u9664 \u00b7 \u56de\u9ed8\u9053\u5fb7\u7ecf';
          $editText.value = '';
          updateCustomBadge(false);
        } else $editStatus.textContent = '\u2716 \u6e05\u9664\u5931\u8d25';
      }
    }
  });

  // HTTP 直连: 绕过 postMessage 通道 · 用编译时注入的 _PORT
  var _hasData = false;
  window.addEventListener('message', function(e) {
    if (e.data && e.data.type === 'data') _hasData = true;
  });
  function _directFetch() {
    if (_hasData || !_PORT) return;
    fetch('http://127.0.0.1:' + _PORT + '/origin/ping')
      .then(function(r) { return r.json(); })
      .then(function(ping) {
        if (!ping || !ping.ok) throw new Error('no proxy');
        return fetch('http://127.0.0.1:' + _PORT + '/origin/preview')
          .then(function(r) { return r.json(); })
          .then(function(proxy) {
            var d = {
              ts: new Date().toISOString(),
              proxy: proxy, proxyUp: true, ping: ping,
              diag: { proxy_up: true, proxy_capturing: !!(proxy && proxy.has_captured_before), mode: ping.mode, uptime_s: ping.uptime_s, req_total: ping.req_total, capture_count: ping.capture_count },
              modeLabel: ping.mode === 'invert' ? '\u9053Agent' : '\u5b98\u65b9Agent'
            };
            renderView(d); _hasData = true;
          });
      })
      .catch(function() {});
  }
  // 立即尝试 HTTP 直连 (不依赖 postMessage · 道法自然)
  _directFetch();
  setTimeout(function() { if (!_hasData) _directFetch(); }, 1500);
  setTimeout(function() { if (!_hasData) _directFetch(); }, 4000);
  setTimeout(function() { if (!_hasData) _directFetch(); }, 10000);
  setInterval(function() { if (!_hasData) _directFetch(); }, 20000);

  document.getElementById('btnPurge').addEventListener('click', function() {
    // v4.5 修: webview 内 confirm() 被 vscode 严格禁用 (默认 false)
    // 直接 postMessage · 由 extension cmdPurge() 内 showWarningMessage(modal:true) 唯一确认
    if ($source) $source.textContent = '\u51c6\u5907\u51c0\u5378\u2026';
    vsc.postMessage({ command: 'purge' });
  });

  if (!vsc._ghost) vsc.postMessage({ command: 'refresh' });
  _stage('iife-end');
})();
</script>
</body>
</html>`;
}

// ═══════════════════════════ icon.svg placeholder ═══════════════════════════
function ensureIconSvg() {
  const svgPath = path.join(__dirname, "media", "icon.svg");
  if (fs.existsSync(svgPath)) return;
  try {
    fs.mkdirSync(path.join(__dirname, "media"), { recursive: true });
    fs.writeFileSync(
      svgPath,
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 2a7.5 7.5 0 0 0 0 15 5 5 0 0 1 0 5"/></svg>`,
    );
  } catch {}
}

// ═══════════════════════════ activate / deactivate ═══════════════════════════
let _essenceProvider = null;

function activate(ctx) {
  try {
    cfg();
    _cachedAnchored = isAnchored();
    _cachedMode = vscode.workspace
      .getConfiguration("dao")
      .get("origin.defaultMode", "invert");

    installSpawnHook();
    ensureIconSvg();

    L.info(
      "ext",
      `dao-proxy-min v${PKG_VERSION} activate · port=${_cachedPort} anchored=${_cachedAnchored} user=${os.userInfo().username}`,
    );

    // 道德经横幅
    if (vscode.workspace.getConfiguration("dao").get("origin.banner", true)) {
      const q = DAO_QUOTES[Math.floor(Math.random() * DAO_QUOTES.length)];
      vscode.window.showInformationMessage(`道Agent v${PKG_VERSION} · ${q}`);
    }

    // 注册命令
    ctx.subscriptions.push(
      vscode.commands.registerCommand("wam.originInvert", cmdInvert),
      vscode.commands.registerCommand("wam.originPassthrough", cmdPassthrough),
      vscode.commands.registerCommand("dao.toggleMode", cmdToggle),
      vscode.commands.registerCommand("dao.openPreview", cmdOpenPreview),
      vscode.commands.registerCommand("wam.verifyEndToEnd", cmdVerifyE2E),
      vscode.commands.registerCommand("wam.selftest", cmdSelftest),
      vscode.commands.registerCommand("dao.purge", cmdPurge),
    );

    // 注册 webview
    _essenceProvider = new EssenceProvider(ctx);
    ctx.subscriptions.push(
      vscode.window.registerWebviewViewProvider(
        "dao.essence",
        _essenceProvider,
        {
          webviewOptions: { retainContextWhenHidden: true },
        },
      ),
    );

    // 自动恢复 / 首装自启: 道法自然 · 下载即用
    if (_cachedAnchored) {
      // 已锚定 → 恢复代理 (含 EADDRINUSE 远程复用)
      L.info("activate", "settings anchored → auto-restore proxy");
      proxyStart(_cachedPort, "invert")
        .then(() => {
          proxySetMode("invert");
          L.info("activate", "auto-restore done");
        })
        .catch((e) => {
          L.error("activate", `auto-restore fail: ${e.message}`);
          // 不清锚 · 代理可能由另一窗口运行
        });
    } else {
      // 首装 / 未锚定 → 自动启 invert · 道Agent 默认开启
      L.info("activate", "not anchored → first-run auto-start invert");
      (async () => {
        try {
          await proxyStart(_cachedPort, "invert");
          proxySetMode("invert");
        } catch (e) {
          L.error("activate", `first-run proxy fail: ${e.message}`);
          return; // 代理启动失败 · 无法继续
        }
        try {
          await setAnchor(_cachedPort);
        } catch (e) {
          L.warn("activate", `first-run anchor fail (non-fatal): ${e.message}`);
          // 锚定失败不阻塞 · 代理已启 · 文件写入仍可用
          _cachedAnchored = true;
          _cachedProxyUrl = `http://127.0.0.1:${_cachedPort}`;
        }
        try {
          installSpawnHook();
          L.info("activate", "first-run: proxy+anchor done → restarting LS");
          await forceRestartLS();
          L.info("activate", "first-run: LS restarted · invert active");
        } catch (e) {
          L.warn("activate", `first-run LS restart fail: ${e.message}`);
        }
      })();
    }
  } catch (e) {
    L.error("activate", `FATAL activation error: ${e.stack || e.message}`);
    vscode.window.showErrorMessage(`道Agent 激活失败: ${e.message}`);
  }
}

async function deactivate() {
  L.info("ext", "deactivate");
  const isLocal = _proxyHandle && _proxyHandle.server;

  // ── 顺序至关重要 · 反者道之动 ──
  // 正序 (停代理→清锚→杀LS) 必死 · 因 LS 连死代理 → Windsurf 卡死
  // 逆序 (透传→清锚→杀LS→停代理) · 道法自然 · 无为而无不为

  // ① 先设透传 · 过渡期 LS 若仍连代理 · 透传至官方 · 不断不乱
  if (isLocal && _proxyHandle.setMode) {
    try {
      _proxyHandle.setMode("passthrough");
    } catch {}
  }

  // ② 立即断钩 · 新 LS 不再被截持
  _cachedAnchored = false;
  removeSpawnHook();

  // ③ 同步清锚 (直写 settings.json) · VS Code API 不可靠 (codeium.* 非注册键)
  // 文件直写 → Windsurf file watcher → 内存刷新 · 后续 LS 重启指向官方
  if (isLocal) _clearAnchorFileSync();

  // ④ 杀 LS · 使其重生 · 无钩无锚 → 直连官方
  if (isLocal) {
    try {
      await forceRestartLS();
    } catch {}
  }

  // ⑤ dispose webview
  if (_essenceProvider) {
    _essenceProvider.dispose();
    _essenceProvider = null;
  }

  // ⑥ 停代理 · 此时 LS 已死或已重生直连官方 · 安全
  await proxyStop();
  L.info(
    "deactivate",
    isLocal
      ? "local: passthrough→清锚→杀LS→停代理 · 道法自然"
      : "remote: 仅停代理",
  );
}

module.exports = { activate, deactivate };
