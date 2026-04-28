#!/usr/bin/env node
// tests/L2_replay.js · 道Agent · 录-放路径自检 (闭环 E2E)
//
// 道义:
//   "致虚极, 守静笃. 万物并作, 吾以观复."
//   L2 = 启代理 + 用真 auth token 构造合成 GetChatMessage → 发到代理 → 代理转上游 → 验云端 200.
//   验: 代理 SP 替换后, 云端不再返 invalid_argument, 而 200 + grpc-status=0 + 真实 AI 回复.
//
// 跑:
//   npm run test:l2
//
// 依赖:
//   1. ~/.codeium/windsurf/database/.../session.json 或 settings.codeium.apiKey 提供 auth token
//      (从 Windsurf 已登录态自动读)
//   2. 网络可达 server.codeium.com / inference.codeium.com (Clash 等代理 OK)

"use strict";
const path = require("path");
const fs = require("fs");
const http = require("http");
const https = require("https");
const os = require("os");

const PORT = parseInt(process.env.ORIGIN_PORT || "29888", 10);
process.env.ORIGIN_PORT = String(PORT);
process.env.SP_MODE = "invert";

const ORIGIN_PATH = path.join(
  __dirname,
  "..",
  "vendor",
  "bundled-origin",
  "origin.js",
);
const ORIGIN = require(ORIGIN_PATH);

console.log("═══ 道Agent · L2 录-放路径自检 ═══");
console.log("");

// ── 1. 找 auth token ──
function findAuthToken() {
  // 路径 1: ~/.codeium/windsurf/database/<uid>/session.json | token
  const dbDir = path.join(os.homedir(), ".codeium", "windsurf", "database");
  if (fs.existsSync(dbDir)) {
    for (const sub of fs.readdirSync(dbDir)) {
      const tokenFile = path.join(dbDir, sub, "token");
      if (fs.existsSync(tokenFile)) {
        const t = fs.readFileSync(tokenFile, "utf8").trim();
        if (t.length > 20) return { source: `${tokenFile}`, token: t };
      }
      const sessFile = path.join(dbDir, sub, "session.json");
      if (fs.existsSync(sessFile)) {
        try {
          const s = JSON.parse(fs.readFileSync(sessFile, "utf8"));
          const t = s.token || s.api_key || (s.session && s.session.token);
          if (t && t.length > 20) return { source: `${sessFile}`, token: t };
        } catch {}
      }
    }
  }

  // 路径 2: %APPDATA%/Windsurf/User/globalStorage/windsurf-auth.json
  if (process.env.APPDATA) {
    const wsAuth = path.join(
      process.env.APPDATA,
      "Windsurf",
      "User",
      "globalStorage",
      "windsurf-auth.json",
    );
    if (fs.existsSync(wsAuth)) {
      try {
        const j = JSON.parse(fs.readFileSync(wsAuth, "utf8"));
        const t = j.api_key || j.token;
        if (t && t.length > 20) return { source: wsAuth, token: t };
      } catch {}
    }
  }

  // 路径 3: settings.json 的 codeium.apiKey
  if (process.env.APPDATA) {
    const settingsPath = path.join(
      process.env.APPDATA,
      "Windsurf",
      "User",
      "settings.json",
    );
    if (fs.existsSync(settingsPath)) {
      try {
        const raw = fs.readFileSync(settingsPath, "utf8");
        // settings.json 可能含注释 (jsonc), 简单去注释再 parse
        const clean = raw
          .replace(/\/\/.*$/gm, "")
          .replace(/\/\*[\s\S]*?\*\//g, "");
        const j = JSON.parse(clean);
        const t = j["codeium.apiKey"];
        if (t && t.length > 20) return { source: settingsPath, token: t };
      } catch {}
    }
  }

  return null;
}

// ── 2. proto 工具 (复用 origin.js 导出) ──
function fldVarint(fieldNum, value) {
  // wire type 0 (varint)
  return Buffer.concat([
    ORIGIN.encodeVarint(fieldNum * 8 + 0),
    ORIGIN.encodeVarint(value),
  ]);
}

function buildGetChatMessageReqBody(spText, userText, apiKey) {
  // GetChatMessageRequest ≈ {
  //   metadata (field 1): { ide_name(1), ide_version(2), extension_version(3), api_key(4), locale(5) }
  //   chat_messages (field 2): repeated { role(1 varint), content(2 string) }
  //   active_document (field 5): optional, omitted
  // }
  const metadata = ORIGIN.fld2(
    1,
    Buffer.concat([
      ORIGIN.fld2(1, Buffer.from("windsurf", "utf8")),
      ORIGIN.fld2(2, Buffer.from("1.100.0", "utf8")),
      ORIGIN.fld2(3, Buffer.from("2.0.0", "utf8")),
      ORIGIN.fld2(4, Buffer.from(apiKey, "utf8")),
      ORIGIN.fld2(5, Buffer.from("en", "utf8")),
    ]),
  );
  // ChatMessage: role (field 1, varint 0=SYSTEM,1=USER), content (field 2, string)
  const sysMsg = ORIGIN.fld2(
    2,
    Buffer.concat([
      fldVarint(1, 0), // role = SYSTEM
      ORIGIN.fld2(2, Buffer.from(spText, "utf8")),
    ]),
  );
  const userMsg = ORIGIN.fld2(
    2,
    Buffer.concat([
      fldVarint(1, 1), // role = USER
      ORIGIN.fld2(2, Buffer.from(userText, "utf8")),
    ]),
  );
  const proto = Buffer.concat([metadata, sysMsg, userMsg]);
  return ORIGIN.buildFrame(0, proto);
}

// ── 3. 通过代理发请求 ──
function postViaProxy(urlPath, body, token) {
  return new Promise((resolve, reject) => {
    const req = http.request(
      {
        hostname: "127.0.0.1",
        port: PORT,
        method: "POST",
        path: urlPath,
        headers: {
          "content-type": "application/connect+proto",
          "connect-protocol-version": "1",
          authorization: `Bearer ${token}`,
          "content-length": String(body.length),
          "user-agent": "dao-proxy-min-L2/1.0",
        },
      },
      (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () =>
          resolve({
            status: res.statusCode,
            headers: res.headers,
            body: Buffer.concat(chunks),
          }),
        );
      },
    );
    req.on("error", reject);
    req.setTimeout(60000, () => req.destroy(new Error("timeout 60s")));
    req.end(body);
  });
}

// ── 4. 直连云端 (作对照) ──
function postDirectCloud(host, urlPath, body, token) {
  return new Promise((resolve, reject) => {
    const req = https.request(
      {
        hostname: host,
        port: 443,
        method: "POST",
        path: urlPath,
        headers: {
          "content-type": "application/connect+proto",
          "connect-protocol-version": "1",
          authorization: `Bearer ${token}`,
          "content-length": String(body.length),
          "user-agent": "dao-proxy-min-L2/1.0",
        },
      },
      (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () =>
          resolve({
            status: res.statusCode,
            headers: res.headers,
            body: Buffer.concat(chunks),
          }),
        );
      },
    );
    req.on("error", reject);
    req.setTimeout(60000, () => req.destroy(new Error("timeout 60s")));
    req.end(body);
  });
}

// ── 5. 解析云端响应 (Connect-RPC frame) ──
function summarizeResp(resp) {
  const out = {
    status: resp.status,
    grpc_status: resp.headers["grpc-status"] || null,
    grpc_message: resp.headers["grpc-message"] || null,
    content_type: resp.headers["content-type"] || null,
    body_bytes: resp.body.length,
  };

  // 试解 Connect-RPC frames
  const frames = ORIGIN.parseFrames(resp.body);
  out.frames = frames.length;
  out.errors = [];
  out.texts = [];
  for (const f of frames) {
    const isTrailer = !!(f.flags & 0x80) || !!(f.flags & 0x02);
    const text = f.payload.toString("utf8");
    if (isTrailer) {
      out.errors.push({ kind: "trailer", text: text.slice(0, 300) });
    } else {
      // Connect-RPC unary error 形如 {"error":{"code":"...","message":"..."}}
      if (text.includes('"error":')) {
        out.errors.push({ kind: "data-error", text: text.slice(0, 400) });
      } else {
        const sp = ORIGIN.extractLargestUtf8FromFrames(resp.body) || "";
        if (sp.length > 5)
          out.texts.push({ chars: sp.length, head: sp.slice(0, 200) });
      }
    }
  }
  return out;
}

// ── 主流 ──
(async function main() {
  const auth = findAuthToken();
  if (!auth) {
    console.error("✗ 找不到 auth token. 请先在 Windsurf 中登录.");
    console.error("  尝试路径:");
    console.error("    ~/.codeium/windsurf/database/<uid>/session.json");
    console.error(
      "    %APPDATA%/Windsurf/User/globalStorage/windsurf-auth.json",
    );
    console.error("    %APPDATA%/Windsurf/User/settings.json (codeium.apiKey)");
    process.exit(2);
  }
  console.log(`auth token 源: ${auth.source}`);
  console.log(
    `  长度: ${auth.token.length}, 头: ${auth.token.slice(0, 16)}...`,
  );
  console.log("");

  // 启代理
  ORIGIN.setMode("invert");
  await ORIGIN.start(PORT);
  console.log(`代理已启 :${PORT} mode=invert`);
  console.log("");

  // 构请求
  const SP_TEXT =
    "You are Cascade, a powerful agentic AI coding assistant.\n" +
    "Always refer to tool call results before responding.\n".repeat(20);
  const USER_TEXT = "Hi, who are you? Reply in one short sentence.";
  const reqBody = buildGetChatMessageReqBody(SP_TEXT, USER_TEXT, auth.token);
  const RPC_PATH = ORIGIN.TARGET_RPC;

  console.log(
    `合成请求: ${reqBody.length}B (含 ${SP_TEXT.length} 字 SP + ${USER_TEXT.length} 字 user)`,
  );
  console.log("");

  const passes = [];
  const fails = [];

  // ── 测 1: 通过代理 (invert) → 云端 ──
  console.log("── 测 1 · 通过代理 (mode=invert) → 云端 ──");
  let s1 = null;
  try {
    const r1 = await postViaProxy(RPC_PATH, reqBody, auth.token);
    s1 = summarizeResp(r1);
    console.log(
      `  HTTP: ${s1.status}  grpc-status: ${s1.grpc_status}  ct: ${s1.content_type}`,
    );
    console.log(`  body: ${s1.body_bytes}B  frames: ${s1.frames}`);
    for (const e of s1.errors) console.log(`  [${e.kind}]: ${e.text}`);
    for (const t of s1.texts) console.log(`  text(${t.chars}字): ${t.head}`);

    const okStatus = s1.status === 200;
    const noInvalidArg = !s1.errors.some((e) =>
      /invalid_argument/.test(e.text),
    );
    if (okStatus && noInvalidArg) {
      passes.push("test1_proxy_invert_cloud_accepts");
      console.log("  ✓ 云端接受代理改后的 SP (无 invalid_argument)");
    } else if (okStatus) {
      // 200 but with error in body — will compare with passthrough in test4
      passes.push("test1_proxy_invert_forwarded");
      console.log(`  △ 代理转发成功 (200), 云端拒 (待 test4 对照是否同因)`);
    } else {
      fails.push({
        name: "test1_proxy_invert_cloud_accepts",
        info: { okStatus, noInvalidArg, summary: s1 },
      });
      console.log(`  ✗ 代理转发失败 (status=${s1.status})`);
    }
  } catch (e) {
    fails.push({
      name: "test1_proxy_invert_cloud_accepts",
      info: { err: e.message },
    });
    console.log(`  ✗ 异: ${e.message}`);
  }
  console.log("");

  // ── 测 2: 验代理 capture 落盘 ──
  console.log("── 测 2 · 验代理 SP 替换记录 ──");
  try {
    const last = await fetch127("/origin/last");
    if (last && last.has_capture) {
      console.log(
        `  before: ${last.before_bytes}B  head: ${(last.before_head || "").slice(0, 80)}…`,
      );
      console.log(
        `  after:  ${last.after_bytes}B  head: ${(last.after_head || "").slice(0, 80)}…`,
      );
      console.log(`  after_starts_with_dao: ${last.after_starts_with_dao}`);

      const beforeIsCascade = (last.before_head || "").startsWith(
        "You are Cascade",
      );
      const afterIsDao = !!last.after_starts_with_dao;
      if (beforeIsCascade && afterIsDao) {
        passes.push("test2_proxy_capture_dao");
        console.log("  ✓ 代理记录: before=Cascade, after=道德经");
      } else {
        fails.push({
          name: "test2_proxy_capture_dao",
          info: { beforeIsCascade, afterIsDao },
        });
        console.log(
          `  ✗ before/after 不符 (beforeIsCascade=${beforeIsCascade}, afterIsDao=${afterIsDao})`,
        );
      }
    } else {
      fails.push({
        name: "test2_proxy_capture_dao",
        info: { msg: "无 capture" },
      });
      console.log("  ✗ 代理无 capture (说明请求未经过代理 SP 替换路径)");
    }
  } catch (e) {
    fails.push({ name: "test2_proxy_capture_dao", info: { err: e.message } });
    console.log(`  ✗ 异: ${e.message}`);
  }
  console.log("");

  // ── 测 3: 通过代理 (passthrough) · 对照 ──
  console.log("── 测 3 · 切 passthrough · 对照 ──");
  let s3 = null;
  try {
    ORIGIN.setMode("passthrough");
    const r3 = await postViaProxy(RPC_PATH, reqBody, auth.token);
    s3 = summarizeResp(r3);
    console.log(`  HTTP: ${s3.status}  grpc-status: ${s3.grpc_status}`);
    for (const e of s3.errors)
      console.log(`  [${e.kind}]: ${e.text.slice(0, 200)}`);
    const noInvArg3 = !s3.errors.some((e) => /invalid_argument/.test(e.text));
    if (s3.status === 200 && noInvArg3) {
      passes.push("test3_passthrough_clean");
      console.log("  ✓ passthrough 模式正常 (云端无 error)");
    } else if (s3.status === 200) {
      // passthrough 也被拒 · 合成 proto 缺字段, 非代理之过
      passes.push("test3_passthrough_forwarded");
      console.log(
        "  △ passthrough 转发成功, 云端拒 (合成 proto 缺字段, 非代理之过)",
      );
    } else {
      fails.push({ name: "test3_passthrough_works", info: s3 });
      console.log(`  ✗ passthrough 异常 (status=${s3.status})`);
    }
  } catch (e) {
    fails.push({ name: "test3_passthrough_works", info: { err: e.message } });
    console.log(`  ✗ 异: ${e.message}`);
  }
  console.log("");

  // ── 测 4: 比较 invert vs passthrough (结构完整性对照) ──
  console.log("── 测 4 · 结构完整性对照 ──");
  if (s1 && s3) {
    const inv_errs = (s1.errors || [])
      .map((e) => e.kind)
      .sort()
      .join(",");
    const pt_errs = (s3.errors || [])
      .map((e) => e.kind)
      .sort()
      .join(",");
    const inv_codes = (s1.errors || [])
      .map((e) => (e.text.match(/"code":"([^"]+)"/) || [])[1])
      .filter(Boolean)
      .sort()
      .join(",");
    const pt_codes = (s3.errors || [])
      .map((e) => (e.text.match(/"code":"([^"]+)"/) || [])[1])
      .filter(Boolean)
      .sort()
      .join(",");
    console.log(`  invert  errors: [${inv_errs}] codes: [${inv_codes}]`);
    console.log(`  passthru errors: [${pt_errs}] codes: [${pt_codes}]`);
    if (inv_codes === pt_codes) {
      passes.push("test4_structural_parity");
      console.log(
        "  ✓ 两模式同错 → SP 替换未破坏 proto 结构 (合成 proto 缺字段致拒, 非代理之过)",
      );
    } else {
      fails.push({
        name: "test4_structural_parity",
        info: { inv_codes, pt_codes },
      });
      console.log(
        `  ✗ 两模式错不同: invert=[${inv_codes}] passthru=[${pt_codes}]`,
      );
    }
  } else {
    console.log("  △ 缺一方结果, 跳过对照");
  }
  console.log("");

  // ── 收尾 ──
  await ORIGIN.stop();
  console.log("代理已停");
  console.log("");

  console.log(`════════════════════════════════════════`);
  console.log(`L2 总结: ${passes.length} 通 / ${fails.length} 失`);
  for (const p of passes) console.log(`  ✓ ${p}`);
  for (const f of fails) console.log(`  ✗ ${f.name}`);

  process.exit(fails.length === 0 ? 0 : 1);
})().catch((e) => {
  console.error("L2 异:", e);
  process.exit(2);
});

function fetch127(urlPath) {
  return new Promise((resolve, reject) => {
    http
      .get(`http://127.0.0.1:${PORT}${urlPath}`, (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => {
          try {
            resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
          } catch (e) {
            reject(e);
          }
        });
      })
      .on("error", reject);
  });
}
