// v2.1.3 回归: _parsePlanStatusJson · proto3 omit 语义 + 镜像谬绝
"use strict";
const fs = require("node:fs");
const path = require("node:path");

const EXT = path.join(__dirname, "extension.js");
const src = fs.readFileSync(EXT, "utf8");

// 抽出函数 (函数声明边界)
const startTok = "function _parsePlanStatusJson(j) {";
const endTok = "\nfunction ";
const start = src.indexOf(startTok);
if (start < 0) {
  console.error("× cannot locate _parsePlanStatusJson");
  process.exit(1);
}
const end = src.indexOf(endTok, start + startTok.length);
const body = src.substring(start, end);

// log 桩 + 函数封装
const harness = `
const _logs = [];
function log(s){ _logs.push(String(s)); }
${body}
return { fn: _parsePlanStatusJson, logs: _logs };
`;
const env = new Function(harness)();
const fn = env.fn;

let pass = 0, fail = 0;
function expect(name, input, predicate, desc) {
  const r = fn(input);
  if (predicate(r)) {
    console.log("  ✓", name, "→", desc);
    pass++;
  } else {
    console.log("  ✗", name);
    console.log("    got:", JSON.stringify(r));
    fail++;
  }
}

// 时戳: 哨兵存在
const NOW_S = Math.floor(Date.now() / 1000);
const D_RST = NOW_S + 8 * 3600;   // 8h 后 daily 重置
const W_RST = NOW_S + 3 * 86400;  // 3d 后 weekly 重置

console.log("\n[A] 完整字段 · 双值正常");
expect(
  "D85/W43 双present",
  {
    planStatus: {
      planInfo: { planName: "Trial", teamsTier: 9 },
      dailyQuotaRemainingPercent: 85,
      weeklyQuotaRemainingPercent: 43,
      dailyQuotaResetAtUnix: D_RST,
      weeklyQuotaResetAtUnix: W_RST,
    },
  },
  (r) => r.daily === 85 && r.weekly === 43,
  "保持 85/43"
);

console.log("\n[B] ★ 核心修复验证: daily 缺失 (耗尽) ★");
expect(
  "daily omit + dailyResetAt>0 → D=0 (不再镜像 weekly)",
  {
    planStatus: {
      planInfo: { planName: "Trial", teamsTier: 9 },
      // dailyQuotaRemainingPercent omit (proto3 default 0)
      weeklyQuotaRemainingPercent: 24,
      dailyQuotaResetAtUnix: D_RST,
      weeklyQuotaResetAtUnix: W_RST,
    },
  },
  (r) => r.daily === 0 && r.weekly === 24,
  "D=0 W=24 (历史 bug: D=24 W=24 现已绝)"
);
expect(
  "weekly omit → W=0 (一致)",
  {
    planStatus: {
      planInfo: { planName: "Trial", teamsTier: 9 },
      dailyQuotaRemainingPercent: 50,
      // weeklyQuotaRemainingPercent omit
      dailyQuotaResetAtUnix: D_RST,
      weeklyQuotaResetAtUnix: W_RST,
    },
  },
  (r) => r.daily === 50 && r.weekly === 0,
  "D=50 W=0"
);
expect(
  "双 omit → D=0 W=0 (双耗尽)",
  {
    planStatus: {
      planInfo: { planName: "Trial", teamsTier: 9 },
      dailyQuotaResetAtUnix: D_RST,
      weeklyQuotaResetAtUnix: W_RST,
    },
  },
  (r) => r.daily === 0 && r.weekly === 0,
  "D=0 W=0"
);

console.log("\n[C] 边界: 100% 满量");
expect(
  "D100/W100 全量",
  {
    planStatus: {
      planInfo: { planName: "Trial", teamsTier: 9 },
      dailyQuotaRemainingPercent: 100,
      weeklyQuotaRemainingPercent: 100,
      dailyQuotaResetAtUnix: D_RST,
      weeklyQuotaResetAtUnix: W_RST,
    },
  },
  (r) => r.daily === 100 && r.weekly === 100,
  "D=100 W=100"
);
expect(
  "D100 + W omit → D=100 W=0",
  {
    planStatus: {
      planInfo: { planName: "Trial", teamsTier: 9 },
      dailyQuotaRemainingPercent: 100,
      dailyQuotaResetAtUnix: D_RST,
      weeklyQuotaResetAtUnix: W_RST,
    },
  },
  (r) => r.daily === 100 && r.weekly === 0,
  "D=100 W=0"
);

console.log("\n[D] 退化兼容: dailyResetAt 缺失 (理论非追踪 plan)");
expect(
  "daily omit + drst==0 → 退化 mirror weekly (兼容)",
  {
    planStatus: {
      planInfo: { planName: "Trial", teamsTier: 9 },
      weeklyQuotaRemainingPercent: 32,
      // dailyResetAt omit + dailyPct omit
      weeklyQuotaResetAtUnix: W_RST,
    },
  },
  (r) => r.daily === 32 && r.weekly === 32,
  "保留对未来非追踪 plan 的兼容"
);

console.log("\n[E] usage% 字段反向解析");
expect(
  "weeklyQuotaUsagePercent=70 → W=30",
  {
    planStatus: {
      planInfo: { planName: "Pro", teamsTier: 2 },
      dailyQuotaRemainingPercent: 50,
      weeklyQuotaUsagePercent: 70,
      dailyQuotaResetAtUnix: D_RST,
      weeklyQuotaResetAtUnix: W_RST,
    },
  },
  (r) => r.daily === 50 && r.weekly === 30,
  "100-70=30"
);

console.log("\n[F] 实战镜像谬模拟 (复现 wam-state.json 历史污染)");
const mirrored = [
  ["d=11/w=11 → 修复后 d=0/w=11", 11],
  ["d=23/w=23 → 修复后 d=0/w=23", 23],
  ["d=42/w=42 → 修复后 d=0/w=42", 42],
  ["d=50/w=50 → 修复后 d=0/w=50", 50],
];
for (const [name, wval] of mirrored) {
  expect(
    name,
    {
      planStatus: {
        planInfo: { planName: "Trial", teamsTier: 9 },
        weeklyQuotaRemainingPercent: wval,
        dailyQuotaResetAtUnix: D_RST,
        weeklyQuotaResetAtUnix: W_RST,
      },
    },
    (r) => r.daily === 0 && r.weekly === wval,
    `D=0 W=${wval}`
  );
}

console.log("\n═══ 结果: " + pass + " 过 / " + fail + " 败 ═══");
process.exit(fail > 0 ? 1 : 0);
