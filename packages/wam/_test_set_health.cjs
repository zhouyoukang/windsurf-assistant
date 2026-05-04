// _test_set_health.cjs · v2.4.4 · setHealth 防御 + pruneOrphanHealth 回归
"use strict";
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

// mock vscode
const vscodeMock = {
  workspace: { getConfiguration: () => ({ get: (k, d) => d, update: () => Promise.resolve() }), onDidChangeConfiguration: () => ({ dispose() {} }), onDidChangeTextDocument: () => ({ dispose() {} }), onDidSaveTextDocument: () => ({ dispose() {} }), onDidChangeActiveTextEditor: () => ({ dispose() {} }) },
  window: { createOutputChannel: () => ({ appendLine: () => {}, append: () => {}, show: () => {}, dispose: () => {} }), createStatusBarItem: () => ({ show: () => {}, hide: () => {}, dispose: () => {}, tooltip: "", text: "", command: "" }), showInformationMessage: () => Promise.resolve(), showWarningMessage: () => Promise.resolve(), showErrorMessage: () => Promise.resolve(), showInputBox: () => Promise.resolve(""), registerWebviewViewProvider: () => ({ dispose() {} }), createWebviewPanel: () => ({ webview: { onDidReceiveMessage: () => {}, html: "" }, onDidDispose: () => {}, dispose: () => {}, reveal: () => {} }), onDidChangeWindowState: () => ({ dispose() {} }) },
  commands: { registerCommand: () => ({ dispose() {} }), executeCommand: () => Promise.resolve(), getCommands: () => Promise.resolve([]) },
  StatusBarAlignment: { Left: 1, Right: 2 },
  ViewColumn: { Active: -1, Beside: -2, One: 1 },
  ConfigurationTarget: { Global: 1, Workspace: 2 },
  Uri: { file: (p) => ({ fsPath: p }), parse: (s) => ({ toString: () => s }) },
  EventEmitter: class { fire() {} dispose() {} get event() { return () => ({ dispose() {} }); } },
  ThemeColor: class { constructor(c) { this.id = c; } },
  TreeItemCollapsibleState: { None: 0, Collapsed: 1, Expanded: 2 },
};
const Module = require("node:module");
const origLoad = Module._load;
Module._load = function (req, ...args) { if (req === "vscode") return vscodeMock; return origLoad.call(this, req, ...args); };

// 隔离 state 到临时目录
const tmpHome = path.join(os.tmpdir(), "_wam_test_" + Date.now());
const tmpWam = path.join(tmpHome, ".wam");
fs.mkdirSync(tmpWam, { recursive: true });
process.env.USERPROFILE = tmpHome;
process.env.HOME = tmpHome;

delete require.cache[require.resolve("./extension.js")];
const ext = require("./extension.js");

// 取 Store class (internals)
const Store = ext._internals && ext._internals.Store;
if (!Store) {
  console.error("✗ ext._internals.Store 不存在 · 请确认 extension.js 已导出");
  process.exit(1);
}

let pass = 0, fail = 0;
function expect(desc, cond, detail) {
  if (cond) {
    pass++;
    console.log("  ✓ " + desc);
  } else {
    fail++;
    console.log("  ✗ " + desc + (detail ? " · " + detail : ""));
  }
}

console.log("══ v2.4.4 setHealth 防御 + pruneOrphanHealth 回归 ══\n");

// Test A · setHealth: 0 值不覆盖 prev 非 0 (核心 bug 修复验证)
console.log("[A] setHealth: 0 值不覆盖 prev 非 0");
{
  const s = new Store();
  s.accounts = [{ email: "test@example.com", password: "x" }];
  // 初次写入完整 health
  const pe1 = Date.parse("2026-05-09T20:56:09Z");
  s.setHealth("test@example.com", {
    daily: 100,
    weekly: 100,
    plan: "Trial",
    planEnd: pe1,
    planStart: Date.parse("2026-04-25T20:56:09Z"),
    daysLeft: 6,
    promptCredits: 10000,
    flowCredits: 20000,
    dailyResetAt: 1777881600000,
    weeklyResetAt: 1778400000000,
  });
  const h1 = s.health["test@example.com"];
  expect("初次 planEnd 正", h1.planEnd === pe1);
  expect("初次 promptCredits=10000", h1.promptCredits === 10000);

  // 模拟老 ext host 进程返回 planEnd=0 的坏值
  s.setHealth("test@example.com", {
    daily: 95,
    weekly: 87,
    plan: "Trial",
    planEnd: 0, // ← 坏值
    planStart: 0,
    daysLeft: 0,
    promptCredits: 0,
    flowCredits: 0,
    dailyResetAt: 0,
    weeklyResetAt: 0,
  });
  const h2 = s.health["test@example.com"];
  expect("二次 daily 更新 95", h2.daily === 95);
  expect("二次 weekly 更新 87", h2.weekly === 87);
  expect("★ planEnd 0 不覆盖 · 保留 prev", h2.planEnd === pe1, "got " + h2.planEnd);
  expect("★ promptCredits 0 不覆盖", h2.promptCredits === 10000);
  expect("★ dailyResetAt 0 不覆盖", h2.dailyResetAt === 1777881600000);
  expect("daysLeft 基于保留的 planEnd 重算 > 0", h2.daysLeft >= 0);
}

// Test B · setHealth: 正常覆盖 (新值非 0 时完全覆盖 prev)
console.log("\n[B] setHealth: 非 0 新值正常覆盖 prev");
{
  const s = new Store();
  s.accounts = [{ email: "b@e.com", password: "x" }];
  const pe1 = Date.parse("2026-05-01T00:00:00Z");
  s.setHealth("b@e.com", { daily: 50, weekly: 50, plan: "Trial", planEnd: pe1, planStart: 0, daysLeft: 3, promptCredits: 5000, flowCredits: 5000 });
  const pe2 = Date.parse("2026-05-15T00:00:00Z");
  s.setHealth("b@e.com", { daily: 70, weekly: 70, plan: "Pro", planEnd: pe2, planStart: 0, daysLeft: 13, promptCredits: 20000, flowCredits: 20000 });
  const h = s.health["b@e.com"];
  expect("plan 更新 Pro", h.plan === "Pro");
  expect("planEnd 新值覆盖", h.planEnd === pe2);
  expect("promptCredits 20000", h.promptCredits === 20000);
}

// Test C · pruneOrphanHealth: 只清 accounts 无 + >24h
console.log("\n[C] pruneOrphanHealth: 清 orphan · 保活号");
{
  const s = new Store();
  s.accounts = [
    { email: "alive1@e.com", password: "x" },
    { email: "alive2@e.com", password: "x" },
  ];
  const now = Date.now();
  const DAY = 24 * 3600 * 1000;
  // 活号
  s.health["alive1@e.com"] = { daily: 50, weekly: 50, checked: true, lastChecked: now, planEnd: now + DAY };
  s.health["alive2@e.com"] = { daily: 70, weekly: 70, checked: true, lastChecked: now - 2 * DAY, planEnd: now + DAY };
  // 陈旧 orphan
  s.health["orphan_old@e.com"] = { daily: 0, weekly: 0, checked: true, lastChecked: now - 30 * DAY };
  s.health["orphan_old2@e.com"] = { daily: 0, weekly: 0, checked: true, lastChecked: now - 2 * DAY };
  // 新 orphan (<24h · 暂保)
  s.health["orphan_fresh@e.com"] = { daily: 10, weekly: 10, checked: true, lastChecked: now - 3600 * 1000 };
  const before = Object.keys(s.health).length;
  const removed = s.pruneOrphanHealth();
  const after = Object.keys(s.health).length;
  expect("before = 5", before === 5);
  expect("清 2 个陈旧 orphan", removed === 2);
  expect("after = 3", after === 3);
  expect("alive1 保留", !!s.health["alive1@e.com"]);
  expect("alive2 保留 (即使 stale)", !!s.health["alive2@e.com"]);
  expect("orphan_fresh 保留 (<24h)", !!s.health["orphan_fresh@e.com"]);
  expect("orphan_old 删除", !s.health["orphan_old@e.com"]);
  expect("orphan_old2 删除", !s.health["orphan_old2@e.com"]);
}

// Test D · 场景重现: ext host 老代码在 setHealth 前后 (fresh=true · planEnd=0)
console.log("\n[D] 实战场景: fresh=true 但 planEnd=0 → 保留 prev");
{
  const s = new Store();
  s.accounts = [{ email: "s@e.com", password: "x" }];
  const goodPe = Date.parse("2026-05-09T20:56:09Z");
  // step 1: 老 state.json 有好 planEnd
  s.health["s@e.com"] = {
    daily: 100, weekly: 100, plan: "Trial",
    planEnd: goodPe, planStart: Date.parse("2026-04-25T20:56:09Z"),
    daysLeft: 6, checked: true, lastChecked: Date.now() - 7200 * 1000,
    promptCredits: 10000,
  };
  // step 2: ext host 老代码 verifyAll 写 planEnd=0
  s.setHealth("s@e.com", {
    daily: 100, weekly: 100, plan: "Trial",
    planEnd: 0, planStart: 0, daysLeft: 0, promptCredits: 0,
  });
  const h = s.health["s@e.com"];
  expect("daily 新", h.daily === 100);
  expect("★ planEnd 保留 prev 好值", h.planEnd === goodPe, "got " + h.planEnd);
  expect("★ planStart 保留", h.planStart === Date.parse("2026-04-25T20:56:09Z"));
  expect("promptCredits 保留 10000", h.promptCredits === 10000);
  expect("daysLeft 重算 >= 0", h.daysLeft >= 0);
}

console.log("\n═══ 结果: " + pass + " 过 / " + fail + " 败 ═══");
process.exit(fail ? 1 : 0);
