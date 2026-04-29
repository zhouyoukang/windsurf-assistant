#!/usr/bin/env node
// tests/L1_unit.js · 道Agent · L1 单元自检 · v9.1 道法自然 · 反者道之动
// 跑: npm run test:l1   (即 node --preserve-symlinks tests/L1_unit.js)
//
// 道义:
//   "反者道之动 (四十章). 庖丁解牛 · 以神遇而不以目视 (庄子)."
//   "三十辐共一毂, 当其无, 有车之用 (十一章)." 毂不可弃 · 弃则无车.
//   L1 = 在最小单元 (合成 proto) 上验:
//     1. modifySPProto / modifyRawSP 之彻底隔离 (TAO+DAO+TRAILER+7块KEEP)
//     2. deepStripRequestBody 之侧信道剥净 (INFER_STRIP)
//     3. _customSP 整替 (含 [CUSTOM-SP-ACTIVE] 哨兵 + extractKeepBlocks)
//   不依赖 Windsurf, 不依赖云端, 纯本地, 毫秒完成.
//
// v9.0 核心:
//   整式 = TAO_HEADER + DAO_DE_JING_81 + TAO_TRAILER + extractKeepBlocks(中性化)
//   仅保 7 块最小必要模块. 原 SP 一切着相 (身份/风格/规训/记忆/用户域) 彻删.
//   deepStripProtoSideChannels 递归剥净所有 proto 字段侧信道.

"use strict";
const path = require("path");

// 不让 require 启监听 (L1 只跑函数, 不启 server)
process.env.SP_MODE = "passthrough";
process.env.ORIGIN_PORT = process.env.ORIGIN_PORT || "29999";

const O = require(
  path.join(__dirname, "..", "vendor", "bundled-origin", "source.js"),
);

console.log("═══ 道Agent · L1 单元自检 · v9.1 道法自然 · 反者道之动 ═══");
console.log("");

// ── fakeSP · 仿真实抓官方 SP 结构 (依 2026-04-29 实抓 20888 chars 官方 SP):
//   1. 起首身份段 "You are Cascade..." (628 chars)
//   2. <communication_style> 含 nested guidelines/markdown/citation_guidelines
//   3. <tool_calling> / <making_code_changes> / <task_management> / <running_commands>
//      / <debugging> / <mcp_servers> / <calling_external_apis>
//   4. <user_rules> wrapper 含 nested <MEMORY[*]>
//   5. <user_information>
//   6. <memory_system> (双套嵌)
//   7. <ide_metadata>
//   8. tail · discipline 6 行
const FAKE_SP =
  "You are Cascade, a powerful agentic AI coding assistant.\n" +
  "The USER is interacting with you through a chat panel in their IDE.\n" +
  "The task may require modifying or debugging existing code.\n" +
  "Be mindful of that you are not the only one working in this environment.\n" +
  "Do not overstep your bounds, your goal is to be a pair programmer to the user in completing their task.\n" +
  "For example: Do not create random files.\n" +
  "<communication_style>\n" +
  "Be terse and direct.\n" +
  "<communication_guidelines>be concise</communication_guidelines>\n" +
  "<markdown_formatting>use markdown</markdown_formatting>\n" +
  "<citation_guidelines>@/abs/path:line</citation_guidelines>\n" +
  "</communication_style>\n" +
  "<tool_calling>\nUse only the available tools. Never guess parameters. Before each tool call, briefly state why.\n</tool_calling>\n" +
  "<making_code_changes>\nEXTREMELY IMPORTANT: Your generated code must be immediately runnable.\nIf you're creating the codebase from scratch, create deps file.\n</making_code_changes>\n" +
  "<running_commands>\nYou have the ability to run terminal commands on the user's machine.\nYou are not running in a dedicated container.\n</running_commands>\n" +
  "<task_management>\nUse update_plan to manage work.\n</task_management>\n" +
  "<debugging>\nWhen debugging, only make code changes if you are certain that you can solve the problem.\n</debugging>\n" +
  "<mcp_servers>\n" +
  "The Model Context Protocol (MCP) is a standard that connects AI systems with external tools and data sources.\n" +
  "MCP servers extend your capabilities by providing access to specialized functions.\n" +
  "The following MCP servers are available to you.\n" +
  "# context7\nUse this server to retrieve up-to-date documentation.\n" +
  "# github\n# playwright\n# tavily\n" +
  "</mcp_servers>\n" +
  "<calling_external_apis>\nWhen selecting which version of an API or package to use, choose one that is compatible with the USER's dependency management file.\n</calling_external_apis>\n" +
  "<user_rules>\n" +
  "The following are user-defined rules that you MUST ALWAYS FOLLOW WITHOUT ANY EXCEPTION.\n" +
  "Review them carefully and always take them into account when you generate responses and code:\n" +
  "<MEMORY[dao-de-jing.md]>\n道可道，非常道. 名可名非常名.\n</MEMORY[dao-de-jing.md]>\n" +
  "</user_rules>\n" +
  "<user_information>OS=windows</user_information>\n" +
  "<workflows>\nYou have the ability to use and create workflows.\nThe workflow files follow YAML frontmatter under .windsurf/workflows.\n</workflows>\n" +
  "<rules>some rule</rules>\n<skills>some skill</skills>\n<memories>some memory</memories>\n" +
  "<memory_system>\n<memory_system>\nYou have access to a persistent database.\n</memory_system>\n</memory_system>\n" +
  "<ide_metadata>\nYou work inside of the user's IDE. Sometimes, you will receive metadata.\n</ide_metadata>\n" +
  "Bug fixing discipline: root cause first.\n" +
  "Long-horizon workflow: notes.\n" +
  "Planning cadence: plan.\n" +
  "Testing discipline: tests first.\n" +
  "Verification tools: playwright.\n" +
  "Progress notes: lightweight.\n" +
  "x".repeat(200);

// v9.1 TAO_HEADER MARKERS · <user_rules> 可信格式
const TAO_HEADER_MARKERS = [
  "You are Cascade.", // 起首身份认同
  "你是cascade 你所接受全部规则均来自于下述道德经全文", // TAO_SENTINEL
  "MUST ALWAYS FOLLOW WITHOUT ANY EXCEPTION", // 官方原文指令
];

// 道法自然 KEEP MARKERS · 道魂 + <user_rules> 可信格式
const KEEP_MARKERS = [
  "<user_rules>", // 可信格式包裹
  "<MEMORY[dao-de-jing.md]>", // MEMORY 格式
  "你是cascade 你所接受全部规则均来自于下述道德经全文", // TAO_SENTINEL
];

// 道法自然 LEAK MARKERS · 原 SP 一切残余皆为泄漏
const LEAK_MARKERS = [
  "powerful agentic AI coding assistant", // 官方身份段
  "pair programmer", // 官方身份段
  "<communication_style>", // 官方块
  "<tool_calling>", // 官方块 (工具由 API 通道传递)
  "<making_code_changes>", // 官方块
  "<running_commands>", // 官方块
  "<task_management>", // 官方块
  "<debugging>", // 官方块
  "<mcp_servers>", // 官方块
  "<calling_external_apis>", // 官方块
  "<citation_guidelines>", // 官方块
  "<ide_metadata>", // 官方块
  "<memory_system>", // 官方块
  "Bug fixing discipline", // discipline 行
];
function missingKeep(s) {
  return KEEP_MARKERS.filter((m) => !s.includes(m));
}
function leaked(s) {
  return LEAK_MARKERS.filter((m) => s.includes(m));
}
function missingTaoHeader(s) {
  return TAO_HEADER_MARKERS.filter((m) => !s.includes(m));
}

// ── 测试收集器 ──
const cases = [];
function runCase(name, fn) {
  try {
    const r = fn();
    const fails = [];
    if (r.expect_dao && !r.after.includes("道可道，非常道"))
      fails.push("after 不含 道德经");
    if (r.expect_dao === false && r.after.includes("道可道，非常道"))
      fails.push("after 含道德经 (该 case 应不含)");
    if (r.expect_dao_first && !r.after.startsWith("You are Cascade."))
      fails.push('after 不以 "You are Cascade." 起首 (TAO_HEADER)');
    if (r.expect_keep_tools) {
      const m = missingKeep(r.after);
      if (m.length) fails.push(`KEEP 缺失: ${m.join(", ")}`);
    }
    if (r.expect_no_leak) {
      const l = leaked(r.after);
      if (l.length) fails.push(`LEAK 残留: ${l.join(", ")}`);
    }
    if (r.expect_tao_header) {
      const m = missingTaoHeader(r.after);
      if (m.length) fails.push(`TAO_HEADER 缺失: ${m.join(", ")}`);
    }
    if (r.expect_has_footer && !r.after.includes("</MEMORY[dao-de-jing.md]>"))
      fails.push("after 无 TAO_FOOTER 闭合");
    // _customSP 验 · expect_custom_first: string → startsWith 检; true → 仅标记 (由 _extra_fails 细检)
    if (
      typeof r.expect_custom_first === "string" &&
      !r.after.startsWith(r.expect_custom_first)
    )
      fails.push("after 不以预期字串起首");
    if (r.expect_exact != null && r.after !== r.expect_exact)
      fails.push(
        `after 非完全等于 expect_exact (${r.after.length}B vs ${r.expect_exact.length}B)`,
      );
    if (Array.isArray(r._extra_fails) && r._extra_fails.length) {
      for (const x of r._extra_fails) fails.push(x);
    }
    cases.push({
      name,
      ok: fails.length === 0,
      in_bytes: r.in_bytes,
      out_bytes: r.out_bytes,
      changed: r.in_bytes !== r.out_bytes,
      orig_sp_chars: r.orig_sp_chars,
      new_sp_chars: r.after.length,
      failed_assertions: fails,
    });
  } catch (e) {
    cases.push({
      name,
      ok: false,
      err: e.message,
      in_bytes: 0,
      out_bytes: 0,
      changed: false,
      orig_sp_chars: 0,
      new_sp_chars: 0,
      failed_assertions: [`异常: ${e.message}`],
    });
  }
}

// ── A: plain UTF-8 (field[10]) · CHAT_PROTO 精确路径 ──
runCase("plain_utf8", () => {
  const top = O.serializeProto({
    10: [{ w: 2, b: Buffer.from(FAKE_SP, "utf8") }],
  });
  const frame = O.buildFrame(0, top);
  const mod = O.modifySPProto(frame);
  const out = O.parseProto(O.parseFrames(mod)[0].payload);
  const after = Buffer.from(out[10][0].b).toString("utf8");
  return {
    in_bytes: frame.length,
    out_bytes: mod.length,
    orig_sp_chars: FAKE_SP.length,
    before: FAKE_SP,
    after,
    expect_dao: true,
    expect_dao_first: true,
    expect_tao_header: true,
    expect_keep_tools: true, // 可信格式保留
    expect_no_leak: true, // 一切着相彻删
    expect_has_footer: true, // TAO_FOOTER 存在
  };
});

// ── B: nested ChatMessage (field[10] → sub {1:role, 2:content}) · CHAT_PROTO ──
runCase("nested_chat_message", () => {
  const nested = O.serializeProto({
    1: [{ w: 0, v: 0 }],
    2: [{ w: 2, b: Buffer.from(FAKE_SP, "utf8") }],
  });
  const top = O.serializeProto({ 10: [{ w: 2, b: nested }] });
  const frame = O.buildFrame(0, top);
  const mod = O.modifySPProto(frame);
  const topOut = O.parseProto(O.parseFrames(mod)[0].payload);
  const nestOut = O.parseProto(Buffer.from(topOut[10][0].b));
  const after = Buffer.from(nestOut[2][0].b).toString("utf8");
  return {
    in_bytes: frame.length,
    out_bytes: mod.length,
    orig_sp_chars: FAKE_SP.length,
    before: FAKE_SP,
    after,
    expect_dao: true,
    expect_dao_first: true,
    expect_tao_header: true,
    expect_keep_tools: true,
    expect_no_leak: true,
    expect_has_footer: true,
  };
});

// ── C: RawGetChatMessage · field[3] · CHAT_RAW 精确路径 ──
runCase("raw_sp", () => {
  const top = O.serializeProto({
    3: [{ w: 2, b: Buffer.from(FAKE_SP, "utf8") }],
  });
  const frame = O.buildFrame(0, top);
  const mod = O.modifyRawSP(frame);
  const topOut = O.parseProto(O.parseFrames(mod)[0].payload);
  const after = Buffer.from(topOut[3][0].b).toString("utf8");
  return {
    in_bytes: frame.length,
    out_bytes: mod.length,
    orig_sp_chars: FAKE_SP.length,
    before: FAKE_SP,
    after,
    expect_dao: true,
    expect_dao_first: true,
    expect_tao_header: true,
    expect_keep_tools: true,
    expect_no_leak: true,
    expect_has_footer: true,
  };
});

// ── D: user msg deep strip · v9.0 侧信道深度净化 ──
//    deepStripProtoSideChannels 递归剥净所有 proto 字段的侧信道,
//    包括 user msg 中的 MEMORY 块. 非侧信道内容保留.
runCase("user_msg_deep_strip", () => {
  const userContent =
    "帮我查一下代码.\n<MEMORY[test.md]>\n道可道...\n</MEMORY[test.md]>\n剩余用户问题.\n";
  const userMsg = O.serializeProto({
    1: [{ w: 0, v: 1 }], // role=1 user
    2: [{ w: 2, b: Buffer.from(userContent, "utf8") }],
  });
  const sysMsg = O.serializeProto({
    1: [{ w: 0, v: 0 }], // role=0 system
    2: [{ w: 2, b: Buffer.from(FAKE_SP, "utf8") }],
  });
  const top = O.serializeProto({
    2: [
      { w: 2, b: userMsg },
      { w: 2, b: sysMsg },
    ],
  });
  const frame = O.buildFrame(0, top);
  const mod = O.modifySPProto(frame);
  const topOut = O.parseProto(O.parseFrames(mod)[0].payload);
  const userOut = O.parseProto(Buffer.from(topOut[2][0].b));
  const after = Buffer.from(userOut[2][0].b).toString("utf8");
  // v9.0: MEMORY 侧信道被剥, 但非侧信道内容 (帮我查/剩余) 保留
  const fails = [];
  if (after.includes("<MEMORY["))
    fails.push("user msg 中 MEMORY 侧信道未被剥除");
  if (!after.includes("帮我查一下代码"))
    fails.push("user msg 非侧信道内容丢失");
  if (!after.includes("剩余用户问题"))
    fails.push("user msg 非侧信道内容丢失 (2)");
  return {
    in_bytes: frame.length,
    out_bytes: mod.length,
    orig_sp_chars: userContent.length,
    before: userContent,
    after,
    _extra_fails: fails,
  };
});

// ── E: _customSP · keep_blocks=true · v9.1 道法自然 · 用户即道 ──
runCase("custom_sp_keep_blocks", () => {
  const userSP =
    "你是用户自定义助手. 第一律: 答必精简. 第二律: 不饰美言. 第三律: 道法自然.";
  O.setCustomSP(userSP, { keep_blocks: true, source: "L1_test" });
  try {
    const top = O.serializeProto({
      10: [{ w: 2, b: Buffer.from(FAKE_SP, "utf8") }],
    });
    const frame = O.buildFrame(0, top);
    const mod = O.modifySPProto(frame);
    const out = O.parseProto(O.parseFrames(mod)[0].payload);
    const after = Buffer.from(out[10][0].b).toString("utf8");
    // v9.1: userSP + realtime/keeps · 无哨兵前缀 · 道法自然
    const fails = [];
    if (!after.startsWith(userSP.slice(0, 10)))
      fails.push("after 不以 userSP 起首");
    if (!after.includes(userSP)) fails.push("after 不含 userSP");
    if (!after.includes("<tool_calling>"))
      fails.push("after 不含 keep blocks (tool_calling)");
    if (after.includes("道可道，非常道"))
      fails.push("after 含道德经 (custom SP 不应含)");
    return {
      in_bytes: frame.length,
      out_bytes: mod.length,
      orig_sp_chars: FAKE_SP.length,
      before: FAKE_SP,
      after,
      expect_dao: false,
      expect_custom_first: true,
      _extra_fails: fails,
    };
  } finally {
    O.clearCustomSP();
  }
});

// ── F: _customSP · keep_blocks=false · v9.1 道法自然 · 用户即道 ──
runCase("custom_sp_replace_all", () => {
  const userSP =
    "你是用户自定义助手, 仅用此身. 不引道德经. 不留官方块. 用户全权.";
  O.setCustomSP(userSP, { keep_blocks: false, source: "L1_test" });
  try {
    const top = O.serializeProto({
      10: [{ w: 2, b: Buffer.from(FAKE_SP, "utf8") }],
    });
    const frame = O.buildFrame(0, top);
    const mod = O.modifySPProto(frame);
    const out = O.parseProto(O.parseFrames(mod)[0].payload);
    const after = Buffer.from(out[10][0].b).toString("utf8");
    // v9.1: userSP + realtime · 无哨兵前缀 · 道法自然
    const fails = [];
    if (!after.startsWith(userSP.slice(0, 10)))
      fails.push("after 不以 userSP 起首");
    if (!after.includes(userSP)) fails.push("after 不含 userSP");
    // keep_blocks=false: 不含 tool_calling 等 (仅 realtime: user_information)
    if (after.includes("<tool_calling>"))
      fails.push("after 含 tool_calling (keep_blocks=false 不应含)");
    return {
      in_bytes: frame.length,
      out_bytes: mod.length,
      orig_sp_chars: FAKE_SP.length,
      before: FAKE_SP,
      after,
      expect_dao: false,
      expect_custom_first: true,
      _extra_fails: fails,
    };
  } finally {
    O.clearCustomSP();
  }
});

// ── G: clearCustomSP 后回默认 · 道德经彻底隔离恢复 ──
runCase("custom_sp_clear_then_default", () => {
  O.setCustomSP("临时自定义", { keep_blocks: true });
  O.clearCustomSP(); // 立清
  const top = O.serializeProto({
    10: [{ w: 2, b: Buffer.from(FAKE_SP, "utf8") }],
  });
  const frame = O.buildFrame(0, top);
  const mod = O.modifySPProto(frame);
  const out = O.parseProto(O.parseFrames(mod)[0].payload);
  const after = Buffer.from(out[10][0].b).toString("utf8");
  return {
    in_bytes: frame.length,
    out_bytes: mod.length,
    orig_sp_chars: FAKE_SP.length,
    before: FAKE_SP,
    after,
    expect_dao: true,
    expect_dao_first: true,
    expect_tao_header: true,
    expect_keep_tools: true,
    expect_no_leak: true,
    expect_has_footer: true,
  };
});

// ── H: v9.0 INFER_STRIP · deepStripRequestBody 侧信道剥净 ──
// 仿 inference RPC body 含侧信道 XML 块, 验 deepStripRequestBody 剥净
runCase("infer_strip", () => {
  const fakeInferBody =
    "Some inference text with side channels.\n" +
    "<user_rules>MUST FOLLOW rules</user_rules>\n" +
    "<MEMORY[test.md]>test memory content</MEMORY[test.md]>\n" +
    "<skills>some skill content</skills>\n" +
    "<workflows>some workflow</workflows>\n" +
    "Bug fixing discipline: root cause first.\n" +
    "Normal text preserved.\n" +
    "x".repeat(200);
  const top = O.serializeProto({
    5: [{ w: 2, b: Buffer.from(fakeInferBody, "utf8") }],
  });
  const frame = O.buildFrame(0, top);
  const result = O.deepStripRequestBody(frame);
  const topOut = O.parseProto(O.parseFrames(result.body)[0].payload);
  const after = Buffer.from(topOut[5][0].b).toString("utf8");
  const fails = [];
  if (result.changed === 0)
    fails.push("deepStripRequestBody 未改 (应至少剥 1 个侧信道)");
  if (after.includes("<user_rules>")) fails.push("user_rules 侧信道未被剥除");
  if (after.includes("<MEMORY[")) fails.push("MEMORY 侧信道未被剥除");
  if (after.includes("<skills>")) fails.push("skills 侧信道未被剥除");
  if (after.includes("<workflows>")) fails.push("workflows 侧信道未被剥除");
  if (after.includes("Bug fixing discipline"))
    fails.push("discipline 行未被剥除");
  if (!after.includes("Normal text preserved")) fails.push("非侧信道文本丢失");
  if (!after.includes("Some inference text"))
    fails.push("非侧信道文本丢失 (2)");
  return {
    in_bytes: frame.length,
    out_bytes: result.body.length,
    orig_sp_chars: fakeInferBody.length,
    before: fakeInferBody,
    after,
    _extra_fails: fails,
  };
});

// ── 结果 ──
const pass = cases.filter((c) => c.ok).length;
const total = cases.length;
const ok = pass === total;
console.log(`道德经字数: ${O.DAO_DE_JING_81.length}`);
console.log(`TAO_HEADER 字数: ${O.TAO_HEADER.length}`);
console.log(
  `TAO_HEADER 数: ${TAO_HEADER_MARKERS.length} · KEEP 数: ${KEEP_MARKERS.length} · LEAK 数: ${LEAK_MARKERS.length}`,
);
console.log(`通过率: ${pass}/${total}`);
console.log(`总体: ${ok ? "✓ 全绿" : "✗ 有失败"}`);
console.log("");
console.log("各 case:");
for (const c of cases) {
  const mark = c.ok ? "✓" : "✗";
  console.log(`  ${mark} ${c.name}`);
  console.log(
    `     in=${c.in_bytes}B  out=${c.out_bytes}B  changed=${c.changed}  orig=${c.orig_sp_chars}  after=${c.new_sp_chars}`,
  );
  if (c.failed_assertions && c.failed_assertions.length) {
    for (const a of c.failed_assertions) console.log(`     · 失: ${a}`);
  }
  if (c.err) console.log(`     · 异: ${c.err}`);
}

console.log("");
process.exit(ok ? 0 : 1);
