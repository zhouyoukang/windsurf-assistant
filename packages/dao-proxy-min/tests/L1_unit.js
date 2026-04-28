#!/usr/bin/env node
// tests/L1_unit.js · 道Agent · L1 单元自检 · v5.1 道法自然 · 损强名
// 跑: npm run test:l1   (即 node --preserve-symlinks tests/L1_unit.js)
//
// 道义:
//   "图难于其易, 为大于其细. 天下难事, 必作于易; 天下大事, 必作于细."
//   "为道日损. 损之又损, 以至于无为. 无为而无不为."
//   "名可名, 非常名. 圣人去甚, 去奢, 去泰."
//   L1 = 在最小单元 (合成 proto) 上验 modifySPProto / modifyRawSP 之
//        前置道魂 + 损强名三处 + 工程骨全留.
//   不依赖 Windsurf, 不依赖云端, 纯本地, 毫秒完成.
//
// 一气贯三清 · 损强名:
//   道层  TAO_HEADER + 道德经81章   ← 唯一身份本源, 永在前
//   法层  官方 Cascade SP · 损强名留工程骨
//   术层  proto 不动                 ← 各工具自然运行

"use strict";
const path = require("path");

// 不让 require 启监听 (L1 只跑函数, 不启 server)
process.env.SP_MODE = "passthrough";
process.env.ORIGIN_PORT = process.env.ORIGIN_PORT || "29999";

const O = require(
  path.join(__dirname, "..", "vendor", "bundled-origin", "source.js"),
);

console.log("═══ 道Agent · L1 单元自检 · v5.1 道法自然 · 损强名 ═══");
console.log("");

// ── fakeSP · 仿真官方 SP 结构 · 强名起首 / communication_style 套嵌 citation_guidelines /
//          工程骨诸块 / 尾部六行 discipline ──
const FAKE_SP =
  "You are Cascade, a powerful agentic AI coding assistant.\n" +
  "The USER is interacting with you through a chat panel in their IDE.\n" +
  "The task may require modifying or debugging existing code.\n" +
  "Be mindful of that you are not the only one working in this environment.\n" +
  "Do not overstep your bounds, your goal is to be a pair programmer.\n" +
  "For example: Do not create random files.\n" +
  "<communication_style>\n" +
  "Be terse and direct.\n" +
  "<communication_guidelines>be concise</communication_guidelines>\n" +
  "<markdown_formatting>use markdown</markdown_formatting>\n" +
  "<citation_guidelines>@/abs/path:line</citation_guidelines>\n" +
  "</communication_style>\n" +
  "<tool_calling>use only available tools</tool_calling>\n" +
  "<making_code_changes>prefer minimal edits</making_code_changes>\n" +
  "<running_commands>NEVER cd</running_commands>\n" +
  "<task_management>plan first then execute</task_management>\n" +
  "<debugging>root cause before symptom</debugging>\n" +
  "<calling_external_apis>use compatible versions</calling_external_apis>\n" +
  "<user_information>OS=windows</user_information>\n" +
  "<workspace_information>ws=e:/test</workspace_information>\n" +
  "<memory_system>memories are persistent</memory_system>\n" +
  "<ide_metadata>cursor=51</ide_metadata>\n" +
  "Bug fixing discipline: root cause first.\n" +
  "Long-horizon workflow: notes.\n" +
  "Planning cadence: plan.\n" +
  "Testing discipline: tests first.\n" +
  "Verification tools: playwright.\n" +
  "Progress notes: lightweight.\n" +
  "\n" +
  "When making function calls...\n" +
  "x".repeat(200);

// 工程骨 KEEP MARKERS · 必在 after
const KEEP_MARKERS = [
  "道可道，非常道", // 道德经
  "You are Cascade. 你的唯一本源", // TAO_HEADER
  "<tool_calling>",
  "<making_code_changes>",
  "<running_commands>",
  "<citation_guidelines>", // 从 communication_style 提出保留
  "<task_management>",
  "<debugging>",
  "<calling_external_apis>",
  "<user_information>",
  "<workspace_information>",
  "<memory_system>",
  "<ide_metadata>",
];
// 强名 LEAK MARKERS · 必不在 after (太上不知有之)
const LEAK_MARKERS = [
  "powerful agentic AI coding assistant", // 起首强名
  "pair programmer",
  "<communication_style>", // 整块去
  "</communication_style>",
  "<communication_guidelines>",
  "<markdown_formatting>",
  "Bug fixing discipline:",
  "Long-horizon workflow:",
  "Planning cadence:",
  "Testing discipline:",
  "Verification tools:",
  "Progress notes:",
];
function missingKeep(s) {
  return KEEP_MARKERS.filter((m) => !s.includes(m));
}
function leaked(s) {
  return LEAK_MARKERS.filter((m) => s.includes(m));
}

// ── 测试收集器 ──
const cases = [];
function runCase(name, fn) {
  try {
    const r = fn();
    const fails = [];
    if (r.expect_dao && !r.after.includes("道可道，非常道"))
      fails.push("after 不含 道德经");
    if (r.expect_tao_header && !r.after.startsWith("You are Cascade. 你的唯一"))
      fails.push("after 不以 TAO_HEADER 起首");
    if (r.expect_keep_before && !r.after.includes(r.before))
      fails.push("after 未完整含 before (透传原则破)");
    if (r.expect_keep_engineering) {
      const m = missingKeep(r.after);
      if (m.length) fails.push(`KEEP 缺失: ${m.join(", ")}`);
    }
    if (r.expect_no_strong_naming) {
      const lk = leaked(r.after);
      if (lk.length) fails.push(`强名漏: ${lk.join(", ")}`);
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

// ── A: plain UTF-8 (field[10]) ──
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
    expect_tao_header: true,
    expect_keep_engineering: true,
    expect_no_strong_naming: true,
  };
});

// ── B: nested ChatMessage (field[10] → sub {1:role, 2:content}) ──
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
    expect_tao_header: true,
    expect_keep_engineering: true,
    expect_no_strong_naming: true,
  };
});

// ── C: RawGetChatMessage · field[3] ──
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
    expect_tao_header: true,
    expect_keep_engineering: true,
    expect_no_strong_naming: true,
  };
});

// ── D: user msg passthrough · 道法自然: 用户消息不动 ──
//    用户侧记忆/规则若已在 user msg 中, 也不剥. 道魂在前为本源, 模型自识.
runCase("user_msg_passthrough", () => {
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
  // 用户消息应原样保留 (含 MEMORY[test.md] · 因不剥)
  return {
    in_bytes: frame.length,
    out_bytes: mod.length,
    orig_sp_chars: userContent.length,
    before: userContent,
    after,
    expect_keep_before: true, // user msg 全保
  };
});

// ── 结果 ──
const pass = cases.filter((c) => c.ok).length;
const total = cases.length;
const ok = pass === total;
console.log(`道德经字数: ${O.DAO_DE_JING_81.length}`);
console.log(`TAO_HEADER 字数: ${O.TAO_HEADER.length}`);
console.log(
  `KEEP_MARKERS 数: ${KEEP_MARKERS.length} · LEAK_MARKERS 数: ${LEAK_MARKERS.length}`,
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
