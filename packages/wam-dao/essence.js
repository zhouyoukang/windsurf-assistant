// essence.js — 道Agent · 本源一览 · 新小模块
//
// 圣人抱一为天下式 · 其数一也
// 此模块只观, 不改 · 视之不见名曰夷, 听之不闻名曰希, 搏之不得名曰微
// 汇聚"注入于 Windsurf 内 agent 本源之一切"九源于一屏:
//   一 · 道源锚定 (proxy + state.vscdb)
//   二 · 规则 (workspace .windsurf/rules + user-global)
//   三 · 工作流 (.windsurf/_workflows)
//   四 · 技能 (.windsurf/skills)
//   五 · 扩展 (~/.windsurf/extensions)
//   六 · 记忆 (~/.codeium/windsurf/memories)
//   七 · 热目录 (~/.wam-hot/origin)
//   八 · 自检 (proxy /origin/selftest 四路径)
//   九 · 道德经正文 (char count + preview)
"use strict";

const vscode = require("vscode");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const http = require("node:http");
const crypto = require("node:crypto");

// ═══════════════════════ 常 · 二十七侧信道 ═══════════════════════
// 与 source.js SIDE_CHANNEL_TAGS 同源 (L225-253) · 保持对齐
// 此列表于 invert 模式下皆剥于 SP + 用户消息 + 任意 proto 深层

const SIDE_CHANNEL_TAGS_LIST = [
  "user_rules",
  "user_information",
  "workspace_information",
  "ide_metadata",
  "ide_state",
  "skills",
  "workflows",
  "flows",
  "memories",
  "memory_system",
  "communication_style",
  "communication_guidelines",
  "markdown_formatting",
  "tool_calling",
  "making_code_changes",
  "running_commands",
  "task_management",
  "debugging",
  "mcp_servers",
  "calling_external_apis",
  "citation_guidelines",
  "custom_instructions",
  "system_prompt",
  "system_instructions",
  "open_files",
  "cursor_position",
  "additional_metadata",
];

// ═══════════════════════ 工具 · 皆柔弱 ═══════════════════════

function safeStat(p) {
  try {
    return fs.statSync(p);
  } catch {
    return null;
  }
}
function safeRead(p, enc) {
  try {
    return fs.readFileSync(p, enc || "utf8");
  } catch {
    return null;
  }
}
function safeReadDir(p) {
  try {
    return fs.readdirSync(p);
  } catch {
    return [];
  }
}
function fmtBytes(n) {
  if (!n || n < 0) return "0 B";
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
  return (n / 1048576).toFixed(2) + " MB";
}
function esc(s) {
  return String(s == null ? "" : s).replace(
    /[&<>"']/g,
    (c) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[c],
  );
}
function fileSha16(p) {
  try {
    const h = crypto.createHash("sha256");
    h.update(fs.readFileSync(p));
    return h.digest("hex").slice(0, 16).toUpperCase();
  } catch {
    return null;
  }
}

function getNonce() {
  const buf = crypto.randomBytes(16);
  return buf.toString("base64");
}

function httpGetJson(url, timeoutMs) {
  return new Promise((resolve) => {
    try {
      const req = http.get(
        url,
        { timeout: timeoutMs || 1500, headers: { connection: "close" } },
        (res) => {
          if (res.statusCode !== 200) {
            res.resume();
            return resolve(null);
          }
          let body = "";
          res.setEncoding("utf8");
          res.on("data", (c) => {
            body += c;
          });
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

// ═══════════════════════ 源 · 九处 ═══════════════════════

function findStateDb() {
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

function readApiServerUrl() {
  const db = findStateDb();
  if (!db) return null;
  try {
    const buf = fs.readFileSync(db);
    const latin = buf.toString("latin1");
    if (!latin.startsWith("SQLite format 3")) return null;
    const key = "codeium.apiServerUrl";
    const idx = latin.indexOf(key);
    if (idx < 0) {
      const m = latin.match(/https?:\/\/(127\.0\.0\.1|localhost):\d+/);
      return m ? { url: m[0], source: "scan", db } : null;
    }
    const after = latin.slice(idx + key.length, idx + key.length + 300);
    const m = after.match(/(https?:\/\/[^\x00-\x1f\x7f-\xff]{5,120})/);
    if (m)
      return {
        url: m[1].trim().replace(/[^A-Za-z0-9.:\-_/]+$/, ""),
        source: "direct",
        db,
      };
    return { url: null, source: "key-found-no-value", db };
  } catch {
    return null;
  }
}

function scanRulesFolder(dir) {
  const out = [];
  if (!fs.existsSync(dir)) return out;
  for (const name of safeReadDir(dir)) {
    if (!name.toLowerCase().endsWith(".md")) continue;
    const fp = path.join(dir, name);
    const st = safeStat(fp);
    if (!st || !st.isFile()) continue;
    const raw = safeRead(fp);
    if (!raw) continue;
    const m = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
    const frontmatter = m ? m[1] : "";
    const body = m ? m[2] : raw;
    const trigger = (frontmatter.match(/^trigger:\s*(.+)$/m) || [, ""])[1]
      .trim()
      .replace(/^["']|["']$/g, "");
    out.push({
      name,
      path: fp,
      size: st.size,
      bodyChars: body.length,
      trigger,
      preview: body.slice(0, 100).replace(/\s+/g, " ").trim(),
      sha16: fileSha16(fp),
    });
  }
  return out;
}

function scanSimpleDir(dir, extFilter) {
  const out = [];
  if (!fs.existsSync(dir)) return out;
  for (const name of safeReadDir(dir)) {
    if (extFilter && !name.toLowerCase().endsWith(extFilter)) continue;
    const fp = path.join(dir, name);
    const st = safeStat(fp);
    if (!st || !st.isFile()) continue;
    out.push({
      name,
      size: st.size,
      mtime: st.mtime.toISOString().slice(0, 16).replace("T", " "),
      path: fp,
    });
  }
  return out;
}

function listExtensions() {
  const extDir = path.join(os.homedir(), ".windsurf", "extensions");
  const out = [];
  if (!fs.existsSync(extDir)) return out;
  for (const name of safeReadDir(extDir)) {
    if (/\.bak\.\d+$/i.test(name)) continue; // skip backups
    const pj = path.join(extDir, name, "package.json");
    const raw = safeRead(pj);
    if (!raw) continue;
    try {
      const p = JSON.parse(raw);
      out.push({
        dir: name,
        id: (p.publisher ? p.publisher + "." : "") + (p.name || ""),
        version: p.version || "?",
        displayName: p.displayName || p.name || name,
        main: p.main || "",
        isDao: /dao|wam/i.test(name),
      });
    } catch {}
  }
  out.sort((a, b) => {
    if (a.isDao !== b.isDao) return a.isDao ? -1 : 1;
    return a.id.localeCompare(b.id);
  });
  return out;
}

// v17.50 · 抱一守中 · 万法归于一字段
// /origin/preview 已究竟: invert=内存合成 / passthrough=持盘回显
// 无论任何模式 · 任何用户规则变化 · preview.after 即 LLM 所收之最终注入全文
// 不离其中 · 多言数穷 · 唯四键 {ts, port, ping, preview}
async function gatherEssence(ctx, port) {
  const ping = await httpGetJson(`http://127.0.0.1:${port}/origin/ping`, 1500);
  const preview = ping
    ? await httpGetJson(`http://127.0.0.1:${port}/origin/preview`, 2000)
    : null;
  return {
    ts: new Date().toISOString(),
    port,
    ping,
    preview,
  };
}

// ═══════════════════════ HTML · 静水流深 ═══════════════════════

function htmlTemplate(nonce, cspSource) {
  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}'; connect-src http://127.0.0.1:*;">
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body {
    font-family: var(--vscode-font-family); color: var(--vscode-foreground);
    background: var(--vscode-sideBar-background, transparent);
    margin: 0; padding: 8px 10px; font-size: 12px; line-height: 1.45;
  }
  .head {
    text-align: center; font-style: italic; font-size: 10px;
    opacity: 0.55; margin: 0 0 8px; letter-spacing: 0.5px;
  }
  .bar {
    display: flex; gap: 4px; margin-bottom: 8px; align-items: center;
  }
  .btn {
    padding: 4px 8px; font-size: 10px; border: 1px solid transparent;
    background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground);
    cursor: pointer; border-radius: 2px; font-family: inherit;
    transition: background-color .12s;
  }
  .btn:hover { background: var(--vscode-button-secondaryHoverBackground, var(--vscode-button-hoverBackground)); }
  .btn.on { background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
  .pulse { margin-left: auto; font-size: 10px; opacity: 0.5; }
  section {
    margin: 0 0 10px; padding: 6px 8px;
    border-left: 2px solid var(--vscode-textSeparator-foreground, rgba(128,128,128,0.25));
    background: rgba(128,128,128,0.04);
    border-radius: 0 3px 3px 0;
  }
  .s-hd {
    display: flex; align-items: center; gap: 6px;
    font-size: 11px; font-weight: 600; margin: 0 0 4px;
    color: var(--vscode-symbolIcon-functionForeground, var(--vscode-foreground));
  }
  .s-hd .num { font-family: monospace; opacity: 0.65; font-weight: normal; }
  .s-hd .tag { margin-left: auto; font-size: 9px; font-weight: normal; padding: 1px 4px; border-radius: 2px; }
  .ok   { background: rgba(35, 134, 54, 0.18); color: var(--vscode-testing-iconPassed, #4ec94e); }
  .warn { background: rgba(200, 140, 0, 0.18); color: var(--vscode-charts-yellow, #d9a200); }
  .fail { background: rgba(200, 40, 40, 0.18); color: var(--vscode-errorForeground, #e57373); }
  .na   { background: rgba(128,128,128,0.12); color: var(--vscode-descriptionForeground); }
  .row { display: flex; gap: 6px; align-items: baseline; padding: 1px 0; }
  .row .k { min-width: 84px; opacity: 0.6; font-size: 10px; flex: 0 0 auto; }
  .row .v { font-family: var(--vscode-editor-font-family, monospace); font-size: 11px; word-break: break-all; flex: 1 1 auto; }
  .row .v.dim { opacity: 0.55; }
  .list { padding: 0; margin: 2px 0 0; list-style: none; }
  .list li {
    padding: 2px 4px; font-size: 11px; font-family: var(--vscode-editor-font-family, monospace);
    border-radius: 2px;
  }
  .list li:hover { background: var(--vscode-list-hoverBackground); cursor: pointer; }
  .list li .hi { color: var(--vscode-symbolIcon-classForeground, var(--vscode-foreground)); font-weight: 500; }
  .list li .sub { opacity: 0.55; font-size: 10px; margin-left: 4px; }
  .path { font-family: monospace; font-size: 10px; opacity: 0.55; word-break: break-all; }
  .preview {
    padding: 6px; background: rgba(0,0,0,0.12); border-radius: 3px;
    font-family: var(--vscode-editor-font-family, monospace); font-size: 10.5px;
    max-height: 120px; overflow: auto; line-height: 1.55; opacity: 0.85;
    white-space: pre-wrap; word-break: break-all;
  }
  .tao {
    font-family: "Noto Serif CJK SC", "Microsoft YaHei", serif;
    font-size: 11.5px; line-height: 1.7; font-style: normal;
  }
  .grid3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 4px; }
  .chip {
    text-align: center; padding: 6px 2px; font-size: 10px; border-radius: 2px;
    background: rgba(128,128,128,0.08);
  }
  .chip b { display: block; font-size: 14px; font-family: monospace; line-height: 1.4; }
  .footer { margin-top: 10px; text-align: center; font-size: 10px; opacity: 0.4; font-style: italic; }
  code { font-family: monospace; font-size: 11px; padding: 0 3px; background: rgba(128,128,128,0.14); border-radius: 2px; }
  .hr { height: 1px; background: rgba(128,128,128,0.15); margin: 4px -8px; }
  details { margin-top: 3px; }
  summary { cursor: pointer; font-size: 10px; opacity: 0.6; outline: none; user-select: none; }
  summary:hover { opacity: 1; }
  /* v17.51 · 反向出发 · 分段解剖样式 */
  .banner {
    padding: 5px 8px; border-radius: 3px; margin-bottom: 8px;
    font-size: 10.5px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
    background: rgba(128,128,128,0.08);
  }
  .banner.dao { background: rgba(100, 180, 100, 0.14); }
  .banner.off { background: rgba(180, 140, 80, 0.14); }
  .banner .ml { font-weight: 600; }
  .banner .stat { font-family: monospace; opacity: 0.75; font-size: 10px; }
  .banner .stat.dim { opacity: 0.45; }
  .blk {
    margin: 0 0 3px; border: 1px solid rgba(128,128,128,0.18);
    border-radius: 3px; background: rgba(128,128,128,0.04);
  }
  .blk > summary {
    padding: 4px 8px; cursor: pointer;
    display: flex; align-items: center; gap: 6px;
    font-size: 10.5px; list-style: none; outline: none;
  }
  .blk > summary::-webkit-details-marker { display: none; }
  .blk > summary::before { content: '▶'; font-size: 9px; opacity: 0.5; width: 8px; flex: 0 0 8px; }
  .blk[open] > summary::before { content: '▼'; }
  .blk:hover > summary { background: var(--vscode-list-hoverBackground); }
  .btag {
    font-family: monospace; font-size: 10.5px;
    color: var(--vscode-symbolIcon-classForeground, var(--vscode-foreground));
  }
  .bcnt { margin-left: auto; font-size: 9.5px; opacity: 0.55; font-family: monospace; }
  .blk .body {
    padding: 6px 10px; margin: 0; border-top: 1px dashed rgba(128,128,128,0.15);
    font-family: var(--vscode-editor-font-family, monospace); font-size: 10.5px;
    line-height: 1.55; white-space: pre-wrap; word-break: break-word;
    max-height: 320px; overflow: auto;
    background: rgba(0,0,0,0.04);
  }
  .blk-after .body {
    font-family: "Noto Serif CJK SC", "Microsoft YaHei", serif;
    font-size: 11.5px; line-height: 1.75;
    max-height: 420px;
    background: rgba(0,0,0,0.08);
  }
  .blk-after > summary .btag {
    font-family: inherit; font-weight: 600;
  }
  .diss-hdr {
    font-size: 10px; opacity: 0.55; letter-spacing: 0.4px;
    margin: 10px 0 4px; padding-left: 2px;
  }
  .quiet {
    opacity: 0.3; text-align: center; font-size: 10.5px; padding: 24px 0;
    font-style: italic; letter-spacing: 1px;
  }
  .trunc-note {
    display: block; font-size: 9.5px; opacity: 0.5; font-style: italic;
    margin: 6px 0; text-align: center;
  }
</style>
</head>
<body>
  <div class="head">反者道之动 · 以神遇而不以目视 · 一屏观本源</div>
  <div class="bar">
    <button class="btn" id="refresh">◉ 刷新</button>
    <button class="btn on" id="auto">⟲ 自动</button>
    <button class="btn" id="copy">⧉ 复制</button>
    <span class="pulse" id="pulse">—</span>
  </div>
  <div id="root">
    <section><div class="s-hd">正在观照本源…</div></section>
  </div>
  <noscript><div style="color:red;padding:12px;text-align:center">脚本被阻 · CSP nonce 未生效 · 请 Reload Window</div></noscript>
  <div class="footer">大曰逝 · 逝曰远 · 远曰反</div>
<script nonce="${nonce}">
(function() {
  const vscode = acquireVsCodeApi();
  const $root = document.getElementById('root');
  const $pulse = document.getElementById('pulse');
  const $auto = document.getElementById('auto');
  let lastData = null;
  let autoOn = true;

  document.getElementById('refresh').addEventListener('click', () => {
    $pulse.textContent = '刷…';
    vscode.postMessage({ command: 'refresh' });
  });
  $auto.addEventListener('click', () => {
    autoOn = !autoOn;
    $auto.classList.toggle('on', autoOn);
    vscode.postMessage({ command: 'setAuto', value: autoOn });
    $pulse.textContent = autoOn ? '自动' : '静';
  });
  document.getElementById('copy').addEventListener('click', () => {
    if (!lastData) return;
    const pv = lastData.preview;
    const txt = (pv && pv.after) ? pv.after : JSON.stringify(lastData, null, 2);
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(txt).then(() => { $pulse.textContent = '已复制'; });
    } else {
      const ta = document.createElement('textarea');
      ta.value = txt; document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); $pulse.textContent = '已复制 JSON'; } catch {}
      document.body.removeChild(ta);
    }
  });

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }
  function fmtBytes(n) {
    if (!n || n < 0) return '0 B';
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (n/1024).toFixed(1) + ' KB';
    return (n/1048576).toFixed(2) + ' MB';
  }
  function reveal(p) {
    if (!p) return;
    vscode.postMessage({ command: 'reveal', path: p });
  }
  window.revealPath = reveal;

  function chip(n, label, ok) {
    const cls = ok === true ? 'ok' : ok === false ? 'fail' : 'na';
    return '<div class="chip"><b>' + esc(n) + '</b><span class="' + cls + '" style="padding:0 2px;border-radius:2px">' + esc(label) + '</span></div>';
  }

  function rowKV(k, v, dim) {
    return '<div class="row"><span class="k">' + esc(k) + '</span><span class="v' + (dim?' dim':'') + '">' + esc(v) + '</span></div>';
  }

  function tag(ok, label) {
    const cls = ok === true ? 'ok' : ok === false ? 'fail' : ok === 'warn' ? 'warn' : 'na';
    return '<span class="tag ' + cls + '">' + esc(label) + '</span>';
  }

  function sec(num, title, tagHtml, body) {
    return '<section><div class="s-hd"><span class="num">'+num+'</span><span>'+esc(title)+'</span>'+(tagHtml||'')+'</div>'+body+'</section>';
  }

  function ageStr(s) {
    if (s == null) return '';
    if (s < 60) return s + '秒';
    if (s < 3600) return Math.round(s/60) + '分';
    if (s < 86400) return Math.round(s/3600) + '时';
    return Math.round(s/86400) + '日';
  }

  function renderBlock(b) {
    // 依 depth 缩进 · 深嵌 MEMORY[] 亦现 · 不一叶障泰山
    const depth = b.depth || 0;
    const ml = depth > 0 ? (' style="margin-left:' + (depth * 12) + 'px"') : '';
    let body = esc(b.content_head || '');
    if (b.truncated) {
      body += '\n\n<span class="trunc-note">... (中段省略 · 见"实注全文" ...) ...</span>\n\n' + esc(b.content_tail || '');
    }
    return '<details class="blk blk-tag"' + ml + '>' +
      '<summary><span class="btag">&lt;' + esc(b.tag) + '&gt;</span>' +
      '<span class="bcnt">' + (b.content_chars || 0) + ' 字</span></summary>' +
      '<div class="body">' + body + '</div>' +
      '</details>';
  }

  function renderDissect(diss, sourceLabel) {
    if (!diss) return '';
    let html = '<div class="diss-hdr">' + esc(sourceLabel) + ' · 共 ' + (diss.total_chars || 0) + ' 字 · ' + (diss.block_count || 0) + ' 块</div>';
    // § 身份首言
    if (diss.identity_chars > 0) {
      html += '<details class="blk">' +
        '<summary><span class="btag">◉ 身份首言</span>' +
        '<span class="bcnt">' + diss.identity_chars + ' 字</span></summary>' +
        '<div class="body">' + esc(diss.identity_head || '') + '</div>' +
        '</details>';
    }
    // § 各 tag 块 (依 start 排序 · 深嵌亦出)
    const blocks = (diss.blocks || []).slice().sort((a,b) => (a.start||0) - (b.start||0));
    for (const b of blocks) html += renderBlock(b);
    // § 末尾倾向
    if (diss.tail_chars > 0) {
      html += '<details class="blk">' +
        '<summary><span class="btag">◈ 末尾倾向</span>' +
        '<span class="bcnt">' + diss.tail_chars + ' 字</span></summary>' +
        '<div class="body">' + esc(diss.tail_head || '') + '</div>' +
        '</details>';
    }
    return html;
  }

  function render(d) {
    if (!d) { $root.innerHTML = ''; return; }
    lastData = d;
    // v17.51 · 反向出发 · 解剖观本源 · 不一叶障泰山
    // preview 返: {after, after_dissect, before, before_dissect, mode, ...}
    //   invert      → after = TAO+道德经 (实注) · before = 原 Windsurf SP (已持盘) · 二者并显
    //   passthrough → after = before = 原 Windsurf SP · 解剖即示所有组件
    const pv = d.preview;

    // 境一 · 未通 / 首启 / 无数据
    if (!pv || (!pv.after && !pv.before)) {
      const msg = d.ping
        ? (pv && pv.mode === 'passthrough'
            ? '首启 passthrough · 发一问即持 · 跨重启恒显'
            : '等 proxy 响应 ...')
        : '· proxy 未通 ·';
      $root.innerHTML = '<div class="quiet">' + esc(msg) + '</div>';
      $pulse.textContent = new Date(d.ts).toLocaleTimeString();
      return;
    }

    let html = '';

    // 头信 · 模式 + 字数 + 捕期
    const isDao = pv.mode === 'invert';
    const modeCls = isDao ? 'dao' : 'off';
    const modeLabel = isDao ? '道模 (invert · TAO+道德经)' : '官模 (passthrough · Windsurf 原)';
    html += '<div class="banner ' + modeCls + '">';
    html += '<span class="ml">' + esc(modeLabel) + '</span>';
    html += '<span class="stat">实注 ' + (pv.after_chars || 0) + ' 字</span>';
    if (pv.has_captured_before && pv.before_chars) {
      html += '<span class="stat dim">原 SP ' + pv.before_chars + ' 字</span>';
    }
    if (pv.age_s != null) {
      html += '<span class="stat dim">' + esc(ageStr(pv.age_s)) + '前</span>';
    }
    html += '</div>';

    // § 实注之文 · LLM 所收 (首段 · 开态)
    if (pv.after) {
      const aLabel = isDao ? '实注之文 · TAO_HEADER + 道德经' : '实注之文 · LLM 所收 (即原 SP)';
      html += '<details class="blk blk-after" open>' +
        '<summary><span class="btag">' + esc(aLabel) + '</span>' +
        '<span class="bcnt">' + (pv.after_chars || 0) + ' 字</span></summary>' +
        '<div class="body">' + esc(pv.after) + '</div>' +
        '</details>';
    }

    // § 解剖: 原 SP 结构 (泰山)
    // invert 模: 示 before_dissect (所舍之全貌 · 用户诸规皆在其中)
    // passthrough 模: before === after · 解剖示同物 (所留之全貌)
    const diss = pv.before_dissect || pv.after_dissect;
    if (diss) {
      const label = isDao
        ? '原 SP 结构 · Windsurf 拟发 · 道模已替 (示所舍)'
        : '实注结构 · 官模所留全貌 (sp + 规则 + 记忆 + 工具 + 末倾向)';
      html += renderDissect(diss, label);
    } else if (isDao) {
      html += '<div class="quiet" style="padding:12px 0;font-size:10px">原 SP 待首次请求捕 · 道模下发一问即存 · 之后跨重启恒显</div>';
    }

    $root.innerHTML = html;
    $pulse.textContent = new Date(d.ts).toLocaleTimeString();
  }


  window.addEventListener('message', (e) => {
    const msg = e.data;
    if (!msg) return;
    if (msg.type === 'data') render(msg.data);
  });

  vscode.postMessage({ command: 'refresh' });
})();
</script>
</body>
</html>`;
}

// ═══════════════════════ Provider · 玄之又玄 ═══════════════════════

class EssenceProvider {
  constructor(ctx, opts) {
    this._ctx = ctx;
    this._view = null;
    this._timer = null;
    this._auto = true;
    this._pollMs = (opts && opts.pollMs) || 8000;
    this._getPort =
      (opts && opts.getPort) ||
      (() =>
        ctx.globalState.get("wam.originPort") ||
        vscode.workspace.getConfiguration().get("dao.origin.port", 8889));
  }

  async resolveWebviewView(webviewView) {
    this._view = webviewView;
    webviewView.webview.options = { enableScripts: true };
    const nonce = getNonce();
    const cspSource = webviewView.webview.cspSource;
    webviewView.webview.html = htmlTemplate(nonce, cspSource);

    webviewView.webview.onDidReceiveMessage(async (msg) => {
      if (!msg) return;
      try {
        if (msg.command === "refresh") {
          await this.refresh();
        } else if (msg.command === "setAuto") {
          this._auto = !!msg.value;
          this._armTimer();
        } else if (msg.command === "reveal") {
          const p = msg.path;
          if (p && fs.existsSync(p)) {
            const doc = await vscode.workspace.openTextDocument(p);
            await vscode.window.showTextDocument(doc, { preview: true });
          }
        }
      } catch {
        /* swallow */
      }
    });

    webviewView.onDidChangeVisibility(() => {
      if (webviewView.visible) {
        this.refresh().catch(() => {});
        this._armTimer();
      } else {
        this._stopTimer();
      }
    });

    webviewView.onDidDispose(() => {
      this._view = null;
      this._stopTimer();
    });

    this._armTimer();
    this.refresh().catch(() => {});
  }

  _armTimer() {
    this._stopTimer();
    if (!this._auto || !this._view || !this._view.visible) return;
    this._timer = setInterval(
      () => this.refresh().catch(() => {}),
      this._pollMs,
    );
  }
  _stopTimer() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  }

  async refresh() {
    if (!this._view) return;
    const port = this._getPort();
    const data = await gatherEssence(this._ctx, port);
    if (!this._view) return;
    try {
      this._view.webview.postMessage({ type: "data", data });
    } catch {
      /* view may have been disposed mid-flight */
    }
  }

  reveal() {
    if (this._view && this._view.show) {
      try {
        this._view.show(true);
      } catch {}
    }
  }
}

module.exports = { EssenceProvider, gatherEssence };
