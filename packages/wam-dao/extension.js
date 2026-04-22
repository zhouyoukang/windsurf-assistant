// extension.js — 道Agent · 无感切号 v17.53 · 二核合一 · 五层锚定
//
// 道可道,非常道。名可名,非常名。
// 无,名天地之始;有,名万物之母。
// 反者道之动, 弱者道之用。
// 有无相生, 难易相成, 高下相倾, 音声相和。
//
// v17.53 — 五层锚定 · 万流归宗 · 一网打尽:
//   WAM 核心: vendor/wam/extension.js (v17.42.2 战斗源 · 原片不动)
//   Origin 覆层: 内联 cascade-hijack + state-bridge (纯 JS · 零 Python 依赖)
//   前端: 双按钮热切换 (道Agent ⇄ 官方Agent ⇄ 关) · 太上不知有之
//   观层: essence webview · dissectSP 分身份/块/末 · 跨模恒显
//   锚层: 调 锚.py anchor-all-globalstate · 五层全下
//         L1 secret blob (Electron safeStorage v10+AES-GCM)
//         L2 ItemTable.codeium.apiServerUrl (plain)
//         L3 codeium.windsurf globalState (native)
//         L4 dao-agi.windsurf-dao/cascade globalState (030 repack 等多 publisher)
//         L5 settings.json codeium.inferenceApiServerUrl
//   本文件: 手写薄壳 · 无需 TS 编译 · 圣人抱一
//
// v17.48 根路观察 · v17.50 抱一守中持盘 · v17.51 反向出发解剖 · v17.52 四层锚 · v17.53 五层一网 — 五里程碑
"use strict";

const vscode = require("vscode");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawn, execSync } = require("node:child_process");
const { EssenceProvider } = require("./essence");

// ═══════════════════════ 常量 · 道法自然 · 三级软适配 ═══════════════════════
// 其数一也: env > vscode config > default · 每一常量皆可软盖 · 适配一切环境
//
// 覆盖方式:
//   (a) 环境变量 (进程启前可设)  · DAO_PORT / DAO_HOT_DIRNAME / DAO_VENDOR_SUBPATH
//   (b) VS Code 设置 (用户可改)  · dao.origin.port / dao.hotDirname / dao.vendorSubpath
//   (c) 默认值 (兜底)            · 8889 / ".wam-hot" / "wam/bundled-origin"

const DEFAULT_PORT = (() => {
  const env = parseInt(process.env.DAO_PORT || "", 10);
  return Number.isFinite(env) && env > 0 && env < 65536 ? env : 8889;
})();
const HOT_DIRNAME = process.env.DAO_HOT_DIRNAME || ".wam-hot";
const VENDOR_SUBPATH = (process.env.DAO_VENDOR_SUBPATH || "wam/bundled-origin")
  .split(/[\\/]/)
  .filter(Boolean);
const IS_WIN = process.platform === "win32";

const DAO_QUOTES = [
  "道可道,非常道。名可名,非常名。",
  "天下万物生于有,有生于无。",
  "反者道之动,弱者道之用。",
  "道生一,一生二,二生三,三生万物。",
  "上善若水。水善利万物而不争。",
  "为无为,事无事,味无味。",
  "大方无隅,大器晚成,大音希声,大象无形。",
  "致虚极,守静笃。万物并作,吾以观复。",
  "知人者智,自知者明。胜人者有力,自胜者强。",
  "圣人无常心,以百姓心为心。",
  "千里之行,始于足下。",
  "祸兮福之所倚,福兮祸之所伏。",
  "大直若屈,大巧若拙,大辩若讷。",
  "信言不美,美言不信。善者不辩,辩者不善。",
  "天之道,利而不害。圣人之道,为而不争。",
  "大制不割。道法自然。",
];

function randomQuote() {
  return DAO_QUOTES[Math.floor(Math.random() * DAO_QUOTES.length)];
}

// ═══════════════════════ 日志 ═══════════════════════

let _channel = null;
function initLogger() {
  if (!_channel)
    _channel = vscode.window.createOutputChannel("道·AGI 万法归宗");
  return _channel;
}
function _stamp() {
  const d = new Date();
  const p = (n, w = 2) => String(n).padStart(w, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
}
function _emit(level, tag, msg) {
  const ch = initLogger();
  ch.appendLine(`[${_stamp()}] [${level.toUpperCase()}] [${tag}] ${msg}`);
}
const log = {
  info: (tag, msg) => _emit("info", tag, msg),
  warn: (tag, msg) => _emit("warn", tag, msg),
  error: (tag, msg) => _emit("error", tag, msg),
  debug: (tag, msg) => _emit("debug", tag, msg),
  show: () => _channel && _channel.show(true),
  dispose: () => {
    if (_channel) {
      _channel.dispose();
      _channel = null;
    }
  },
};

// ═══════════════════════ 配置 ═══════════════════════

function cfg() {
  const c = vscode.workspace.getConfiguration();
  return {
    port: c.get("dao.origin.port", DEFAULT_PORT),
    defaultMode: c.get("dao.origin.defaultMode", "invert"),
    banner: c.get("dao-agi.dao.banner", true),
  };
}

// ═══════════════════════ Hijack · 反代进程管理 ═══════════════════════

let _proxyProc = null;

function extensionRoot() {
  return path.resolve(__dirname);
}
function vendorDir() {
  const p = path.join(extensionRoot(), "vendor", ...VENDOR_SUBPATH);
  return fs.existsSync(p) ? p : null;
}
function hotDir() {
  return path.join(os.homedir(), HOT_DIRNAME, "origin");
}

/** 首次激活 · 自解压 vendor/wam/bundled-origin → ~/.wam-hot/origin/ (size 幂等) */
function ensureHot() {
  const vdir = vendorDir();
  const hdir = hotDir();
  if (!vdir) {
    log.warn("hijack", "vendor/wam/bundled-origin 未找到");
    return { copied: 0, skipped: 0, dir: hdir };
  }
  fs.mkdirSync(hdir, { recursive: true });
  let copied = 0,
    skipped = 0;
  for (const name of fs.readdirSync(vdir)) {
    const src = path.join(vdir, name);
    const dst = path.join(hdir, name);
    try {
      const st = fs.statSync(src);
      if (!st.isFile()) continue;
      if (fs.existsSync(dst) && fs.statSync(dst).size === st.size) {
        skipped++;
        continue;
      }
      fs.copyFileSync(src, dst);
      copied++;
    } catch (e) {
      log.warn("hijack", `复制 ${name} 失败: ${e && e.message}`);
    }
  }
  log.info(
    "hijack",
    `hot ready: copied=${copied} skipped=${skipped} dir=${hdir}`,
  );
  return { copied, skipped, dir: hdir };
}

function isPortListening(port) {
  try {
    const cmd = IS_WIN
      ? `netstat -ano 2>nul | findstr ":${port} " | findstr "LISTENING"`
      : `lsof -iTCP:${port} -sTCP:LISTEN -t 2>/dev/null`;
    const out = execSync(cmd, {
      timeout: 2000,
      encoding: "utf8",
      windowsHide: true,
      stdio: ["ignore", "pipe", "ignore"],
      shell: true,
    });
    return String(out).trim().length > 0;
  } catch {
    return false;
  }
}

/** 启动 源.js 反代 */
async function hijackStart(port) {
  port = port || DEFAULT_PORT;
  if (_proxyProc && !_proxyProc.killed) return hijackStatus(port);
  if (isPortListening(port)) {
    log.info("hijack", `端口 :${port} 已被占用,复用 (Reload Window 后持续)`);
    return hijackStatus(port);
  }
  const hot = ensureHot();
  // 优先 源.js (中文名 · 原始) · 兜底 source.js (ASCII · VSIX 乱码防御)
  const candidates = ["源.js", "source.js"];
  let chosen = "";
  for (const n of candidates) {
    const fp = path.join(hot.dir, n);
    if (fs.existsSync(fp)) {
      chosen = fp;
      break;
    }
  }
  // 终极兜底: 扫描所有 .js 找 shebang
  if (!chosen) {
    for (const f of fs.readdirSync(hot.dir)) {
      if (!f.endsWith(".js")) continue;
      const fp = path.join(hot.dir, f);
      try {
        const head = fs.readFileSync(fp, "utf8").slice(0, 40);
        if (
          head.includes("#!/usr/bin/env node") ||
          head.includes("// origin")
        ) {
          chosen = fp;
          log.info("hijack", `乱码兜底: ${f} → 源.js`);
          break;
        }
      } catch {}
    }
  }
  if (!chosen) throw new Error(`源.js 未找到: ${hot.dir}`);

  log.info("hijack", `启动 源.js: ${chosen} on :${port}`);
  _proxyProc = spawn("node", [chosen], {
    cwd: hot.dir,
    env: {
      ...process.env,
      ORIGIN_PORT: String(port),
      ORIGIN_BIND_HOST: "127.0.0.1",
    },
    detached: true,
    shell: false,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  _proxyProc.unref();
  _proxyProc.stdout &&
    _proxyProc.stdout.on("data", (d) =>
      log.info("hijack.stdout", String(d).trimEnd()),
    );
  _proxyProc.stderr &&
    _proxyProc.stderr.on("data", (d) =>
      log.warn("hijack.stderr", String(d).trimEnd()),
    );
  _proxyProc.on("exit", (c) => {
    log.info("hijack", `源.js 退出 code=${c}`);
    _proxyProc = null;
  });
  await new Promise((r) => setTimeout(r, 900));
  return hijackStatus(port);
}

async function hijackStop() {
  if (!_proxyProc) return;
  log.info("hijack", `停止 源.js pid=${_proxyProc.pid}`);
  try {
    _proxyProc.kill("SIGTERM");
  } catch {}
  setTimeout(() => {
    try {
      _proxyProc && _proxyProc.kill("SIGKILL");
    } catch {}
    _proxyProc = null;
  }, 1200);
}

/** 切模式 · POST /origin/mode */
async function hijackSetMode(mode, port) {
  port = port || DEFAULT_PORT;
  try {
    const resp = await fetch(`http://127.0.0.1:${port}/origin/mode`, {
      method: "POST",
      headers: { "content-type": "application/json", connection: "close" },
      body: JSON.stringify({ mode }),
      signal: AbortSignal.timeout(8000),
    });
    return (await resp.text()).slice(0, 2000);
  } catch (e) {
    return `ERROR: ${e && e.message}`;
  }
}

/** ping 当前模式 */
async function hijackPingMode(port) {
  port = port || DEFAULT_PORT;
  try {
    const r = await fetch(`http://127.0.0.1:${port}/origin/mode`, {
      signal: AbortSignal.timeout(1500),
    });
    if (!r.ok) return "unknown";
    const t = (await r.text()).trim().toLowerCase();
    if (t.includes("invert")) return "invert";
    if (t.includes("passthrough")) return "passthrough";
    return "unknown";
  } catch {
    return "unknown";
  }
}

/** v17.44 · 取 /origin/ping 全信息 (含 self_size 用于版本漂移检测) */
async function hijackPingInfo(port) {
  port = port || DEFAULT_PORT;
  try {
    const r = await fetch(`http://127.0.0.1:${port}/origin/ping`, {
      signal: AbortSignal.timeout(1500),
    });
    if (!r.ok) return null;
    return JSON.parse(await r.text());
  } catch {
    return null;
  }
}

/** v17.44 · hot_dir 里 源.js 的实际大小 (用作版本指纹) */
function hotSourceSize() {
  const hot = hotDir();
  for (const n of ["源.js", "source.js"]) {
    const fp = path.join(hot, n);
    try {
      if (fs.existsSync(fp)) return fs.statSync(fp).size;
    } catch {}
  }
  return 0;
}

/** 强制重启 · ping 不通 → 杀进程 → 杀端口 → 重 spawn */
async function hijackForceRestart(port) {
  port = port || DEFAULT_PORT;
  log.info("hijack", "强制重启 源.js");
  try {
    _proxyProc && _proxyProc.kill("SIGKILL");
  } catch {}
  _proxyProc = null;
  try {
    if (IS_WIN) {
      const out = execSync(
        `netstat -ano 2>nul | findstr ":${port} " | findstr "LISTENING"`,
        {
          encoding: "utf8",
          timeout: 2000,
          windowsHide: true,
          stdio: ["ignore", "pipe", "ignore"],
          shell: true,
        },
      );
      const pids = [
        ...new Set(
          String(out)
            .split("\n")
            .map((l) => l.trim().split(/\s+/).pop())
            .filter(Boolean),
        ),
      ];
      for (const pid of pids) {
        try {
          execSync(`taskkill /PID ${pid} /F`, {
            timeout: 3000,
            windowsHide: true,
          });
        } catch {}
      }
    }
  } catch {}
  await new Promise((r) => setTimeout(r, 1500));
  return hijackStart(port);
}

function hijackStatus(port) {
  port = port || DEFAULT_PORT;
  const vdir = vendorDir();
  const hdir = hotDir();
  const portAlive = isPortListening(port);
  const procAlive = !!_proxyProc && !_proxyProc.killed;
  return {
    ready: !!vdir,
    hotDir: hdir,
    vendorDir: vdir,
    running: portAlive || procAlive,
    pid: _proxyProc ? _proxyProc.pid : undefined,
    port,
    endpoint: `http://127.0.0.1:${port}`,
  };
}

// ═══════════════════════ State · SQLite 锚定 ═══════════════════════

function _findStateDb() {
  const candidates = [
    path.join(
      os.homedir(),
      "AppData",
      "Roaming",
      "Windsurf",
      "User",
      "globalStorage",
      "state.vscdb",
    ),
    path.join(
      os.homedir(),
      ".config",
      "Windsurf",
      "User",
      "globalStorage",
      "state.vscdb",
    ),
    path.join(
      os.homedir(),
      "Library",
      "Application Support",
      "Windsurf",
      "User",
      "globalStorage",
      "state.vscdb",
    ),
  ];
  for (const p of candidates) if (fs.existsSync(p)) return p;
  return null;
}

function _hasPython() {
  try {
    execSync("python --version", {
      timeout: 2000,
      windowsHide: true,
      stdio: "ignore",
    });
    return true;
  } catch {
    try {
      execSync("python3 --version", {
        timeout: 2000,
        windowsHide: true,
        stdio: "ignore",
      });
      return true;
    } catch {
      return false;
    }
  }
}

function _pyCmd() {
  try {
    execSync("python --version", {
      timeout: 2000,
      windowsHide: true,
      stdio: "ignore",
    });
    return "python";
  } catch {
    return "python3";
  }
}

/** 读 apiServerUrl (纯 JS 二进制扫描 · 无依赖) */
function readApiServerUrl() {
  const db = _findStateDb();
  if (!db) return null;
  try {
    const buf = fs.readFileSync(db);
    const latin = buf.toString("latin1");
    if (!latin.startsWith("SQLite format 3")) return null;
    const key = "codeium.apiServerUrl";
    const idx = latin.indexOf(key);
    if (idx < 0) {
      // 全库扫描 127.0.0.1 存在性 (Python 改写后 B-tree 页可能分离)
      const m = latin.match(/https?:\/\/(127\.0\.0\.1|localhost):\d+/);
      return m ? m[0] : null;
    }
    const after = latin.slice(idx + key.length, idx + key.length + 200);
    const m = after.match(/(https?:\/\/[^\x00-\x1f\x7f-\xff]{5,120})/);
    if (m) return m[1].trim().replace(/[^A-Za-z0-9.:\-_/]+$/, "");
    return null;
  } catch (e) {
    log.warn("state", `读取失败: ${e && e.message}`);
    return null;
  }
}

/** v17.52 · 寻 锚.py (hot 优先 · vendor 回退) */
function _findAnchorPy() {
  const hot = path.join(hotDir(), "锚.py");
  if (fs.existsSync(hot)) return hot;
  const hotAlt = path.join(hotDir(), "anchor.py");
  if (fs.existsSync(hotAlt)) return hotAlt;
  const v = vendorDir();
  if (v) {
    const vp = path.join(v, "锚.py");
    if (fs.existsSync(vp)) return vp;
    const vpAlt = path.join(v, "anchor.py");
    if (fs.existsSync(vpAlt)) return vpAlt;
  }
  return null;
}

/** v17.52 · 验 cryptography 是否可用 (锚.py secret 层之需) */
function _hasCryptography() {
  if (!_hasPython()) return false;
  try {
    execSync(
      `${_pyCmd()} -c "import cryptography.hazmat.primitives.ciphers.aead"`,
      { timeout: 2500, windowsHide: true, stdio: "ignore", shell: true },
    );
    return true;
  } catch {
    return false;
  }
}

/** v17.52 · 调 锚.py 子命 · 返 {ok, output} */
function _runAnchorPy(anchorPy, subcmd, args) {
  try {
    const py = _pyCmd();
    const argStr = (args || [])
      .map((a) => `"${a.replace(/"/g, '\\"')}"`)
      .join(" ");
    const cmd = `${py} "${anchorPy}" ${subcmd} ${argStr}`;
    const out = execSync(cmd, {
      timeout: 15000,
      encoding: "utf8",
      windowsHide: true,
      shell: true,
    });
    return { ok: true, output: String(out || "").trim() };
  } catch (e) {
    return { ok: false, output: `[${subcmd}] ${e && e.message}` };
  }
}

/** 锚定 · v17.52 · 优先 锚.py 四层 · 回退简 SQL (仅 Layer 2) */
async function anchor(url) {
  const db = _findStateDb();
  if (!db) return { ok: false, output: "state.vscdb 未发现" };
  const current = readApiServerUrl() || "(未知)";

  const anchorPy = _findAnchorPy();
  const fullMode = anchorPy && _hasCryptography();

  if (fullMode) {
    // v17.53 · 五层完锚 · secret + ItemTable + native globalState + ALL globalState (030 等) + settings.json
    const lines = [`[锚.py 五层] ${current} → ${url}`];
    let anyFail = false;
    const r1 = _runAnchorPy(anchorPy, "anchor", [url]);
    lines.push(
      `  § secret+ItemTable:  ${r1.ok ? "✓" : "✗"} ${r1.output.split("\n").slice(-1)[0]}`,
    );
    if (!r1.ok) anyFail = true;
    // v17.53 · 一网打尽 · 含 codeium.windsurf / dao-agi.windsurf-dao / dao-agi.windsurf-cascade 皆锚
    const r2 = _runAnchorPy(anchorPy, "anchor-all-globalstate", [url, url]);
    lines.push(
      `  § all globalStates:  ${r2.ok ? "✓" : "✗"} ${r2.output.split("\n").slice(-1)[0]}`,
    );
    if (!r2.ok) {
      // 回退到单 native globalState (若老版 锚.py 不支持 anchor-all)
      const r2b = _runAnchorPy(anchorPy, "anchor-globalstate", [url, url]);
      lines.push(
        `  § native only:       ${r2b.ok ? "✓" : "✗"} ${r2b.output.split("\n").slice(-1)[0]}`,
      );
      if (!r2b.ok) anyFail = true;
    }
    const r3 = _runAnchorPy(anchorPy, "anchor-inference", [url]);
    lines.push(
      `  § settings.json:     ${r3.ok ? "✓" : "✗"} ${r3.output.split("\n").slice(-1)[0]}`,
    );
    if (!r3.ok) anyFail = true;
    // 关键层 (secret) 成功即视为 ok · 其他为 best-effort
    return { ok: r1.ok, output: lines.join("\n") };
  }

  // 回退: 简 SQL (仅 Layer 2 · 无 cryptography/或无 锚.py)
  if (!_hasPython()) {
    return {
      ok: false,
      output: [
        "无法自动写入 (缺 Python 环境)",
        "",
        "手动锚定:",
        `  UPDATE ItemTable SET value='${url}' WHERE key='codeium.apiServerUrl';`,
        `  DB: ${db}`,
        `  当前: ${current}`,
      ].join("\n"),
    };
  }
  try {
    const py = _pyCmd();
    const code = `import sqlite3; db=sqlite3.connect(r'${db.replace(/'/g, "\\'")}'); db.execute("INSERT OR REPLACE INTO ItemTable (key,value) VALUES ('codeium.apiServerUrl', ?)", ('${url}',)); db.commit(); db.close(); print('OK: written')`;
    const out = execSync(`${py} -c "${code.replace(/"/g, '\\"')}"`, {
      timeout: 10000,
      encoding: "utf8",
      windowsHide: true,
      shell: true,
    });
    const note = anchorPy
      ? "[仅 Layer 2 · 缺 cryptography · pip install cryptography 以全 4 层]"
      : "[仅 Layer 2 · 未找 锚.py]";
    return {
      ok: true,
      output: `[python-sqlite3] ${current} → ${url}\n${note}\n${out}`,
    };
  } catch (e) {
    return { ok: false, output: `Python 写入失败: ${e && e.message}` };
  }
}

/** 还原 · v17.53 · 优先 锚.py 五层还原 · 回退 anchor 官方默认 */
async function anchorRestore() {
  const anchorPy = _findAnchorPy();
  if (anchorPy && _hasCryptography()) {
    const lines = ["[锚.py 五层还原]"];
    const r1 = _runAnchorPy(anchorPy, "restore", []);
    lines.push(
      `  § secret:             ${r1.ok ? "✓" : "✗"} ${r1.output.split("\n").slice(-1)[0]}`,
    );
    const r2 = _runAnchorPy(anchorPy, "restore-all-globalstate", []);
    lines.push(
      `  § all globalStates:   ${r2.ok ? "✓" : "✗"} ${r2.output.split("\n").slice(-1)[0]}`,
    );
    if (!r2.ok) {
      const r2b = _runAnchorPy(anchorPy, "restore-globalstate", []);
      lines.push(
        `  § native only:        ${r2b.ok ? "✓" : "✗"} ${r2b.output.split("\n").slice(-1)[0]}`,
      );
    }
    const r3 = _runAnchorPy(anchorPy, "restore-inference", []);
    lines.push(
      `  § settings.json:      ${r3.ok ? "✓" : "✗"} ${r3.output.split("\n").slice(-1)[0]}`,
    );
    return { ok: r1.ok, output: lines.join("\n") };
  }
  // 回退: 简化 · 指向官方默认
  return anchor("https://server.codeium.com");
}

/** 锚定状态 */
async function anchorStatus() {
  const url = readApiServerUrl();
  if (!url)
    return { ok: false, output: "state.vscdb 不可读或未设置 apiServerUrl" };
  const isLocal = url.includes("127.0.0.1") || url.includes("localhost");
  return {
    ok: true,
    output: `${isLocal ? "已锚定本源反代" : "指向官方云"}: ${url}\n锚定: ${isLocal ? "是" : "否"}`,
  };
}

// ═══════════════════════ 道 Agent 模式同步 ═══════════════════════

/** 同步 agentMode 给 WAM 核心 (agent_mode.json) */
function syncAgentMode(mode) {
  try {
    const wamDir = path.join(os.homedir(), HOT_DIRNAME);
    fs.mkdirSync(wamDir, { recursive: true });
    fs.writeFileSync(
      path.join(wamDir, "agent_mode.json"),
      JSON.stringify({ agentMode: mode, ts: Date.now() }),
    );
  } catch {}
}

// ═══════════════════════ 双按钮 Webview · 太上不知有之 ═══════════════════════

function daoToggleHtml(nonce, cspSource) {
  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';">
<style>
  :root { color-scheme: light dark; }
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); background: transparent; margin: 0; padding: 10px 8px; font-size: 12px; }
  .banner { text-align: center; font-style: italic; font-size: 10px; opacity: 0.6; margin-bottom: 8px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr auto; gap: 4px; }
  .btn { padding: 8px 4px; border: 1px solid transparent; background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); cursor: pointer; font-size: 11px; border-radius: 2px; transition: background-color .12s, transform .08s; text-align: center; font-family: inherit; }
  .btn:hover { background: var(--vscode-button-secondaryHoverBackground, var(--vscode-button-hoverBackground)); }
  .btn:active { transform: scale(0.97); }
  .btn.active { background: var(--vscode-button-background); color: var(--vscode-button-foreground); font-weight: 600; box-shadow: 0 0 0 1px var(--vscode-focusBorder, transparent) inset; }
  .btn.off { font-size: 14px; padding: 8px 10px; opacity: 0.7; }
  .btn.off:hover { opacity: 1; }
  .status { text-align: center; margin-top: 8px; font-size: 10px; opacity: 0.65; min-height: 14px; line-height: 1.4; }
  .quote { text-align: center; margin-top: 4px; font-size: 10px; opacity: 0.4; font-style: italic; }
</style>
</head>
<body>
  <div class="banner">道法自然 · 无为而无不为</div>
  <div class="grid">
    <button class="btn dao" data-mode="dao" title="道Agent · 道德经 SP · 绝侧信道">🌊 道Agent</button>
    <button class="btn official" data-mode="official" title="官方 Agent · 原味透传">☁️ 官方</button>
    <button class="btn off" data-mode="off" title="关闭代理 · 还原锚">✕</button>
  </div>
  <div class="status" id="status">就绪</div>
  <div class="quote" id="quote"></div>
<script nonce="${nonce}">
(function(){
  const vscode = acquireVsCodeApi();
  const btns = document.querySelectorAll('.btn');
  const status = document.getElementById('status');
  const quote = document.getElementById('quote');
  function setActive(mode) {
    btns.forEach(function(b){
      const d = b.dataset.mode;
      const hit = (d === mode)
        || (mode === 'invert' && d === 'dao')
        || (mode === 'passthrough' && d === 'official');
      b.classList.toggle('active', hit);
    });
  }
  btns.forEach(function(b){
    b.addEventListener('click', function(){
      const m = b.dataset.mode;
      status.textContent = '切换中...';
      vscode.postMessage({ command: 'setMode', mode: m });
    });
  });
  window.addEventListener('message', function(e){
    const msg = e.data;
    if (msg.type === 'state') {
      setActive(msg.mode);
      status.textContent = msg.label || '';
      if (msg.quote) quote.textContent = msg.quote;
    }
  });
  vscode.postMessage({ command: 'requestState' });
})();
</script>
</body>
</html>`;
}

class DaoToggleProvider {
  constructor(ctx) {
    this._ctx = ctx;
    this._view = null;
  }
  resolveWebviewView(webviewView) {
    this._view = webviewView;
    webviewView.webview.options = { enableScripts: true };
    const nonce = crypto.randomBytes(16).toString("base64");
    const cspSource = webviewView.webview.cspSource;
    webviewView.webview.html = daoToggleHtml(nonce, cspSource);
    webviewView.webview.onDidReceiveMessage(async (msg) => {
      if (!msg) return;
      try {
        if (msg.command === "setMode") {
          const target =
            msg.mode === "dao"
              ? "wam.originInvert"
              : msg.mode === "official"
                ? "wam.originPassthrough"
                : "wam.originOff";
          await vscode.commands.executeCommand(target);
          setTimeout(() => this.refresh(), 500);
        } else if (msg.command === "requestState") {
          this.refresh();
        }
      } catch (e) {
        log.warn("dao-toggle", `msg err: ${e && e.message}`);
      }
    });
    this.refresh();
  }
  async refresh() {
    if (!this._view) return;
    const saved = this._ctx.globalState.get("wam.origin") || "off";
    const port = this._ctx.globalState.get("wam.originPort") || cfg().port;
    let label = "未启动";
    try {
      const st = hijackStatus(port);
      if (st.running) {
        const mode = await hijackPingMode(port);
        label =
          mode === "invert"
            ? `道Agent 运行中 :${port}`
            : mode === "passthrough"
              ? `官方 Agent 运行中 :${port}`
              : `代理运行中 :${port}`;
      } else {
        label = saved === "off" ? "代理已关闭" : `代理未运行 (保存=${saved})`;
      }
    } catch {}
    this._view.webview.postMessage({
      type: "state",
      mode: saved,
      label,
      quote: randomQuote(),
    });
  }
}

// ═══════════════════════ Origin 命令 ═══════════════════════

function registerOriginCommands(ctx, toggleProvider) {
  const refresh = () => toggleProvider && toggleProvider.refresh();

  ctx.subscriptions.push(
    vscode.commands.registerCommand("wam.originInvert", async () => {
      try {
        const port = ctx.globalState.get("wam.originPort") || cfg().port;
        const st = hijackStatus(port);
        if (!st.running) {
          const s = await hijackStart(port);
          if (!s.running) {
            vscode.window.showErrorMessage("道Agent: 源.js 启动失败");
            return;
          }
        }
        await hijackSetMode("invert", port);
        const ar = await anchor(`http://127.0.0.1:${port}`);
        await ctx.globalState.update("wam.origin", "invert");
        await ctx.globalState.update("wam.originPort", port);
        syncAgentMode("dao");
        log.info("origin", `invert: port=${port} anchor=${ar.ok}`);
        refresh();
        if (ar.ok) {
          const pick = await vscode.window.showInformationMessage(
            `道Agent: 已启动 (invert) · 请 Reload Window 生效 · ${randomQuote()}`,
            "Reload",
          );
          if (pick === "Reload")
            vscode.commands.executeCommand("workbench.action.reloadWindow");
        } else {
          vscode.window.showWarningMessage(
            `道Agent: 源.js 启动但锚定失败 — ${ar.output.slice(0, 200)}`,
          );
        }
      } catch (e) {
        vscode.window.showErrorMessage(`道Agent: ${e && e.message}`);
      }
    }),

    vscode.commands.registerCommand("wam.originPassthrough", async () => {
      try {
        const port = ctx.globalState.get("wam.originPort") || cfg().port;
        const st = hijackStatus(port);
        if (!st.running) {
          const s = await hijackStart(port);
          if (!s.running) {
            vscode.window.showErrorMessage("官方Agent: 源.js 启动失败");
            return;
          }
        }
        await hijackSetMode("passthrough", port);
        const ar = await anchor(`http://127.0.0.1:${port}`);
        await ctx.globalState.update("wam.origin", "passthrough");
        await ctx.globalState.update("wam.originPort", port);
        syncAgentMode("official");
        log.info("origin", `passthrough: port=${port} anchor=${ar.ok}`);
        refresh();
        vscode.window.showInformationMessage(
          `官方Agent: 已启动 · ${ar.ok ? "锚定成功" : "锚定失败"}`,
        );
      } catch (e) {
        vscode.window.showErrorMessage(`官方Agent: ${e && e.message}`);
      }
    }),

    vscode.commands.registerCommand("wam.originOff", async () => {
      try {
        await hijackStop();
        const ar = await anchorRestore();
        await ctx.globalState.update("wam.origin", "off");
        log.info("origin", `off: restore=${ar.ok}`);
        refresh();
        const pick = await vscode.window.showInformationMessage(
          `道Agent: 已关闭 · ${ar.ok ? "锚已还原" : "还原失败"} · 请 Reload Window 生效`,
          "Reload",
        );
        if (pick === "Reload")
          vscode.commands.executeCommand("workbench.action.reloadWindow");
      } catch (e) {
        vscode.window.showErrorMessage(`道Agent: ${e && e.message}`);
      }
    }),

    vscode.commands.registerCommand("dao.toggleMode", async () => {
      // 命令面板快捷: 道 ⇄ 官方 轮转 (off → dao → official → off)
      const current = ctx.globalState.get("wam.origin") || "off";
      const next =
        current === "off"
          ? "wam.originInvert"
          : current === "invert"
            ? "wam.originPassthrough"
            : "wam.originOff";
      await vscode.commands.executeCommand(next);
    }),

    vscode.commands.registerCommand("wam.verifyEndToEnd", async () => {
      const ch = vscode.window.createOutputChannel("道Agent · E2E 自检");
      ch.show(true);
      ch.appendLine(
        `═══ 道Agent v17.53 E2E · ${new Date().toISOString()} ═══\n`,
      );
      const port = ctx.globalState.get("wam.originPort") || cfg().port;
      const savedMode = ctx.globalState.get("wam.origin") || "off";
      const r = (ok, label, detail) =>
        ch.appendLine(`  ${ok ? "✓" : "✗"} ${label.padEnd(30)} ${detail}`);

      const vdir = vendorDir();
      r(!!vdir, "bundled-origin", vdir || "未找到");
      const hdir = hotDir();
      r(true, "hot dir", hdir);
      const st = hijackStatus(port);
      r(st.running, "源.js", st.running ? `:${port}` : "未运行");
      if (st.running) {
        const mode = await hijackPingMode(port);
        r(true, "模式", `${mode} (保存=${savedMode})`);
      } else {
        r(false, "模式", `未运行 (保存=${savedMode})`);
      }
      const anSt = await anchorStatus();
      r(anSt.ok, "锚定状态", anSt.output.slice(0, 200));
      ch.appendLine("\n═══ 完成 ═══");
    }),
  );
}

// ═══════════════════════ Origin 自动恢复 ═══════════════════════

function autoRestoreOrigin(ctx) {
  try {
    const saved = ctx.globalState.get("wam.origin");
    const savedPort = ctx.globalState.get("wam.originPort") || cfg().port;

    if (saved === "invert" || saved === "passthrough") {
      const st = hijackStatus(savedPort);
      if (st.running) {
        hijackPingMode(savedPort)
          .then(async (mode) => {
            // v17.44 · 版本漂移检测: hot_dir 源.js 大小 vs 代理进程 self_size
            // 不一致 → 代理在跑旧代码, 强制重启拉新码
            const hotSize = hotSourceSize();
            const info = await hijackPingInfo(savedPort);
            const runningSize = (info && info.self_size) || 0;
            const drift =
              hotSize > 0 && runningSize > 0 && hotSize !== runningSize;
            if (mode === "unknown") {
              log.warn("origin", "代理端口活但 ping 不通 — 强制重启");
              const ns = await hijackForceRestart(savedPort);
              if (ns.running && saved === "invert")
                await hijackSetMode("invert", savedPort);
            } else if (drift) {
              log.warn(
                "origin",
                `版本漂移: running=${runningSize}B hot=${hotSize}B — 强制重启拉新码`,
              );
              const ns = await hijackForceRestart(savedPort);
              if (ns.running && saved === "invert")
                await hijackSetMode("invert", savedPort);
            } else {
              log.info(
                "origin",
                `代理已运行: :${savedPort} mode=${mode} saved=${saved} size=${runningSize}B`,
              );
            }
            const ar = await anchor(`http://127.0.0.1:${savedPort}`);
            log.info("origin", `热重载锚验证: ok=${ar.ok}`);
          })
          .catch(() => {});
      } else {
        hijackStart(savedPort)
          .then(async (s) => {
            if (s.running) {
              if (saved === "invert") await hijackSetMode("invert", s.port);
              const ar = await anchor(`http://127.0.0.1:${s.port}`);
              log.info(
                "origin",
                `冷恢复: running=true port=${s.port} mode=${saved} anchor=${ar.ok}`,
              );
            } else {
              log.info("origin", `冷恢复: 启动失败 port=${s.port}`);
            }
          })
          .catch((e) => log.warn("origin", `冷恢复失败: ${e && e.message}`));
      }
    } else if (saved === undefined || saved === null) {
      // 首次激活 · 默认模式来自配置
      const def = cfg().defaultMode;
      log.info("origin", `首次激活 — 默认模式=${def}`);
      if (def === "off") return;
      hijackStart(cfg().port)
        .then(async (s) => {
          if (s.running) {
            await hijackSetMode(def, s.port);
            const ar = await anchor(`http://127.0.0.1:${s.port}`);
            await ctx.globalState.update("wam.origin", def);
            await ctx.globalState.update("wam.originPort", s.port);
            log.info(
              "origin",
              `默认启动: port=${s.port} mode=${def} anchor=${ar.ok}`,
            );
            if (ar.ok) {
              const pick = await vscode.window.showInformationMessage(
                `道Agent v17.53 已启 (${def}) · 请 Reload Window 生效 · ${randomQuote()}`,
                "Reload",
              );
              if (pick === "Reload")
                vscode.commands.executeCommand("workbench.action.reloadWindow");
            }
          }
        })
        .catch((e) => log.warn("origin", `默认启动失败: ${e && e.message}`));
    }

    // 延迟二次锚定 · 对抗 Windsurf 启动时覆写 apiServerUrl 的竞态
    setTimeout(async () => {
      try {
        const p = ctx.globalState.get("wam.originPort") || cfg().port;
        const ar = await anchor(`http://127.0.0.1:${p}`);
        log.info("origin", `延迟锚定(30s): ok=${ar.ok} port=${p}`);
      } catch {}
    }, 30000);
  } catch (e) {
    log.warn("origin", `自动恢复异常: ${e && e.message}`);
  }
}

// ═══════════════════════ WAM 核心加载 · 以神遇而不以目视 ═══════════════════════
//
// WAM v17.36 起为切号纯本位, 但源码中仍留 origin 占位 stub (wam.originInvert/
// Passthrough/verifyEndToEnd), 其 handler 仅提示 "已移至 020-道VSIX_DaoAgi"。
// 我们要接管这些命令注入真实实现, 必须让 WAM 的占位 stub 不注册 (否则 VS Code
// 抛 "command already exists")。方法: 临时 hook vscode.commands.registerCommand,
// WAM 注册此三命令时静默放行 (返回 no-op disposable)。
// 不改 WAM 原片 (利而不害) · 不碰其他命令 (为而不争) · 不露痕迹 (太上不知有之)

const WAM_STUB_COMMANDS = new Set([
  "wam.originInvert",
  "wam.originPassthrough",
  "wam.originOff",
  "wam.verifyEndToEnd",
]);

let _wam = null;
function loadWamCore(ctx) {
  const wamPath = path.join(ctx.extensionPath, "vendor", "wam", "extension.js");
  if (!fs.existsSync(wamPath)) throw new Error(`WAM 核心未找到: ${wamPath}`);

  const origRegister = vscode.commands.registerCommand;
  let skipped = 0;
  vscode.commands.registerCommand = function (cmd, callback, thisArg) {
    if (WAM_STUB_COMMANDS.has(cmd)) {
      skipped++;
      log.info(
        "wam-hook",
        `skip WAM stub: ${cmd} (override with dao-agi v17.53)`,
      );
      return { dispose: function () {} };
    }
    return origRegister.apply(vscode.commands, arguments);
  };
  try {
    _wam = require(wamPath);
    _wam.activate(ctx);
  } finally {
    vscode.commands.registerCommand = origRegister;
  }
  log.info(
    "boot",
    `本源 WAM v17.42 激活完成 · 道生一 · skipped=${skipped} stubs`,
  );
}

// ═══════════════════════ activate / deactivate ═══════════════════════

exports.activate = async function (ctx) {
  initLogger();
  log.info(
    "boot",
    `道Agent v17.53 · 二核合一 · 万法归宗 · 五层一网 · 道法自然`,
  );
  log.info(
    "boot",
    `extensionPath=${ctx.extensionPath} vscode=${vscode.version}`,
  );

  // 一、本源 WAM 激活 (道生一)
  try {
    loadWamCore(ctx);
  } catch (e) {
    log.error("boot", `WAM 激活失败: ${e && e.message}`);
    if (e && e.stack)
      log.error("boot", String(e.stack).split("\n").slice(0, 5).join("\n"));
    vscode.window.showErrorMessage(`WAM 本源激活失败: ${e && e.message}`);
    return;
  }

  // 二、Origin 自解压 (一生二)
  try {
    const h = ensureHot();
    log.info(
      "boot",
      `origin hot: copied=${h.copied} skipped=${h.skipped} @ ${h.dir}`,
    );
  } catch (e) {
    log.warn("boot", `ensureHot: ${e && e.message}`);
  }

  // 三、双按钮 WebView (二生三 · 前端双按钮热切换)
  const toggleProvider = new DaoToggleProvider(ctx);
  ctx.subscriptions.push(
    vscode.window.registerWebviewViewProvider("dao.toggle", toggleProvider, {
      webviewOptions: { retainContextWhenHidden: true },
    }),
  );

  // 三.一、本源一览 WebView (以神遇而不以目视 · 一屏观九源)
  const essenceProvider = new EssenceProvider(ctx, {
    getPort: () => ctx.globalState.get("wam.originPort") || cfg().port,
    pollMs: 8000,
  });
  ctx.subscriptions.push(
    vscode.window.registerWebviewViewProvider("dao.essence", essenceProvider, {
      webviewOptions: { retainContextWhenHidden: true },
    }),
    vscode.commands.registerCommand("wam.showEssence", async () => {
      try {
        await vscode.commands.executeCommand(
          "workbench.view.extension.wam-container",
        );
        await vscode.commands.executeCommand("dao.essence.focus");
        essenceProvider.reveal();
      } catch (e) {
        log.warn("essence", `showEssence: ${e && e.message}`);
      }
    }),
  );

  // 四、Origin 命令 (三生万物)
  registerOriginCommands(ctx, toggleProvider);

  // 五、Origin 自动恢复
  autoRestoreOrigin(ctx);

  // 启动横幅 (太上不知有之 · 可配置隐藏)
  if (cfg().banner) {
    vscode.window.showInformationMessage(`道Agent v17.53 · ${randomQuote()}`);
  }
  log.info(
    "boot",
    "激活完成 · v17.53 · 五层锚 · secret+ItemTable+native+多publisher+settings · 道法自然",
  );
};

exports.deactivate = function () {
  try {
    _wam && _wam.deactivate && _wam.deactivate();
  } catch (e) {
    log.warn("deactivate", `WAM deactivate: ${e && e.message}`);
  }
  try {
    hijackStop();
  } catch {}
  log.dispose();
};
