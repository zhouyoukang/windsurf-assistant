// L2 合成 · 自举闭环 · 不依赖真 token
//
// 道义: "道之为物, 惟恍惟惚. 惚兮恍兮, 其中有象." — 不需真象, 只验代理换道之道
//
// 测什么:
//   1. 构造 GetChatMessage proto 含完整官方 SP marker (用 fake token)
//   2. 经反代发到 8889
//   3. 验: /origin/lastinject 有捕获 · transformed=true · after 含道德经
//   4. 云端可能 401/502 (token 假) · 不要紧 · 本地替换闭环已成
//
// 跑: node tests/L2_synthetic.js
"use strict";

const http = require("http");
const path = require("node:path");
const ORIGIN = require(
  path.join(__dirname, "..", "vendor", "bundled-origin", "source.js"),
);

// ── 0. 软编码 · 水无常形 ──
const PROXY_PORT = parseInt(process.env.ORIGIN_PORT || "8889", 10);
const TARGET_RPC =
  "/exa.language_server_pb.LanguageServerService/GetChatMessage";

// fld2: 构造 proto wire-type-2 (length-delimited) 字段
// = varint(field_number << 3 | 2) + varint(data.length) + data
function fld2(fieldNum, data) {
  return Buffer.concat([
    ORIGIN.encodeVarint((fieldNum << 3) | 2),
    ORIGIN.encodeLen(data),
  ]);
}

console.log("═══ 道Agent · L2 合成 · 自举闭环 ═══");
console.log("");

// ── 1. HTTP 工具 ──
function httpGet(urlPath) {
  return new Promise((resolve, reject) => {
    const req = http.request(
      { host: "127.0.0.1", port: PROXY_PORT, path: urlPath, method: "GET" },
      (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => {
          try {
            resolve(JSON.parse(Buffer.concat(chunks).toString()));
          } catch (e) {
            reject(e);
          }
        });
      },
    );
    req.on("error", reject);
    req.end();
  });
}

function httpPost(urlPath, body, headers) {
  return new Promise((resolve, reject) => {
    const req = http.request(
      {
        host: "127.0.0.1",
        port: PROXY_PORT,
        path: urlPath,
        method: "POST",
        headers,
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
    req.setTimeout(15000, () => req.destroy(new Error("timeout 15s")));
    req.write(body);
    req.end();
  });
}

// ── 2. 构造合成 GetChatMessage proto ──
// SP 必须 ≥500 字且含 ≥2 个 OFFICIAL_SP_MARKERS 才触发 invertSP
function buildSynFrame(spText, userText, fakeToken) {
  const metadata = fld2(
    1,
    Buffer.concat([
      fld2(1, Buffer.from("windsurf", "utf8")),
      fld2(2, Buffer.from("1.100.0", "utf8")),
      fld2(4, Buffer.from(fakeToken, "utf8")),
    ]),
  );
  const sysMsg = fld2(
    2,
    Buffer.concat([
      Buffer.from([0x08, 0x00]), // role=0 (system)
      fld2(2, Buffer.from(spText, "utf8")),
    ]),
  );
  const usrMsg = fld2(
    2,
    Buffer.concat([
      Buffer.from([0x08, 0x02]), // role=2 (user)
      fld2(2, Buffer.from(userText, "utf8")),
    ]),
  );
  const payload = Buffer.concat([metadata, sysMsg, usrMsg]);
  return ORIGIN.buildFrame(0, payload);
}

(async function main() {
  // ── ping ──
  let p0;
  try {
    p0 = await httpGet("/origin/ping");
  } catch (e) {
    console.error(`✗ 反代未启 (:${PROXY_PORT}):`, e.message);
    process.exit(2);
  }
  console.log(
    `反代: mode=${p0.mode} req=${p0.req_total} dao=${p0.dao_chars}字`,
  );
  console.log("");

  // ── 确保 invert ──
  if (p0.mode !== "invert") {
    console.log("→ 切 mode=invert");
    await httpPost(
      "/origin/mode",
      Buffer.from(JSON.stringify({ mode: "invert" })),
      {
        "content-type": "application/json",
      },
    );
    const p1 = await httpGet("/origin/ping");
    console.log(`  现 mode=${p1.mode}`);
    console.log("");
  }

  // ── 构造含完整 marker 的 fake SP (≥500字 · ≥2 marker) ──
  const SP_TEXT =
    "You are Cascade, a powerful agentic AI coding assistant.\n" +
    "<communication_style>be terse and direct</communication_style>\n" +
    "<tool_calling>use only available tools</tool_calling>\n" +
    "<making_code_changes>prefer minimal edits</making_code_changes>\n" +
    "<running_commands>NEVER cd</running_commands>\n" +
    "<user_rules>no special rules</user_rules>\n" +
    "<user_information>OS=windows</user_information>\n" +
    "<workspace_information>ws=e:/道</workspace_information>\n" +
    "x".repeat(200);
  const USER_TEXT = "你是谁? 用一句话回";
  const FAKE_TOKEN = "fake_token_for_local_replay_only_no_cloud";
  const reqBody = buildSynFrame(SP_TEXT, USER_TEXT, FAKE_TOKEN);
  const RPC_PATH = TARGET_RPC;

  console.log(`合成 chat: SP=${SP_TEXT.length}字 req=${reqBody.length}B`);
  console.log(`目标: ${RPC_PATH}`);
  console.log("");

  // ── 发请求 ──
  console.log("── 发 → 反代 → 上游 (期 401/502 · 本地替换闭环已成) ──");
  try {
    const resp = await httpPost(RPC_PATH, reqBody, {
      "content-type": "application/connect+proto",
      "connect-protocol-version": "1",
      authorization: `Bearer ${FAKE_TOKEN}`,
      "content-length": String(reqBody.length),
      "user-agent": "dao-proxy-min-L2-syn/1.0",
    });
    console.log(`  HTTP: ${resp.status}  body: ${resp.body.length}B`);
    if (resp.body.length < 500) {
      console.log(`  body: ${resp.body.toString("utf8").substring(0, 300)}`);
    }
  } catch (e) {
    console.log(`  发失 (预期 · token 假): ${e.message}`);
  }
  console.log("");

  // ── 闭环验证: /origin/lastinject ──
  console.log("── 闭环验证 (via /origin/lastinject) ──");
  await new Promise((r) => setTimeout(r, 300));
  const inj = await httpGet("/origin/lastinject?full=1");

  if (!inj.has_inject) {
    console.log("  ✗ 无注入记录 (lastinject 为空)");
    process.exit(1);
  }

  console.log(`  has_inject: ${inj.has_inject}`);
  console.log(`  mode: ${inj.mode}  transformed: ${inj.transformed}`);
  console.log(`  before: ${inj.before_chars}字  after: ${inj.after_chars}字`);
  console.log(`  kind: ${inj.kind}`);
  const afterHead = (inj.after || "").slice(0, 60);
  const beforeHead = (inj.before || "").slice(0, 60);
  console.log(`  before_head: "${beforeHead}..."`);
  console.log(`  after_head:  "${afterHead}..."`);
  console.log("");

  const ok =
    inj.transformed === true &&
    inj.after_chars > 6000 &&
    (inj.after || "").includes("道可道");

  if (ok) {
    // 额外: req_total 增
    const p2 = await httpGet("/origin/ping");
    console.log(`  Δreq = +${p2.req_total - p0.req_total}`);
    console.log("");
    console.log("═══ 闭环 ✓ · 反代 + 道德经 SP 替换 · 自举验证通过 ═══");
    process.exit(0);
  } else {
    console.log("  ✗ 闭环失败:");
    if (!inj.transformed) console.log("    transformed !== true");
    if (inj.after_chars <= 6000)
      console.log(`    after_chars=${inj.after_chars} ≤ 6000`);
    if (!(inj.after || "").includes("道可道"))
      console.log("    after 不含 道可道");
    process.exit(1);
  }
})().catch((e) => {
  console.error("致命:", e);
  process.exit(99);
});
