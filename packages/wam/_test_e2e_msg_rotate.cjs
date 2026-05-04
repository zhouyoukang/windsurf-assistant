// v2.3.0 E2E 模拟 · 用户每发一条消息切一次号 · 4 号循环
//
// 场景:
//   4 个 Pro 号 (alpha · beta · gamma · delta) · 全可用
//   连发 5 条消息 (每条间隔 5s · 模拟真用户)
//   inUseLockMs=120000 · perMessageDebounceMs=4000 · perMessageDelayMs=0(测略)
//
// 期望:
//   M1 (t=0)   · active=alpha (init) → 切→ best={beta|gamma|delta} (一最优)
//   M2 (t=5s)  · 4s 防抖过 · 切→ next best (排除 alpha+M1选中的 in-use 中)
//   M3 (t=10s) · 切→ third
//   M4 (t=15s) · 切→ fourth
//   M5 (t=20s) · 4 号都 in-use (各刚被切过 ≤ 20s) · 候选=null · 不切 (等 alpha 解锁)
//
// 此测拟全自家 Store + 模拟 _maybeTrigger + mock loginAccount → 不依赖 vscode
"use strict";
const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");
const Module = require("node:module");

// ── 隔离 HOME ──
const tmpHome = path.join(os.tmpdir(), "wam-e2e-" + process.pid);
fs.mkdirSync(tmpHome, { recursive: true });
process.env.HOME = tmpHome;
process.env.USERPROFILE = tmpHome;
os.homedir = () => tmpHome;

// ── 桩 vscode ──
const _cfgStore = {
  rotateOnEveryMessage: true,
  inUseLockMs: 120000,
  perMessageDebounceMs: 4000,
  perMessageDelayMs: 0,
  autoRotate: true,
  autoSwitchThreshold: 5,
  notifyLevel: "silent",
};
const vscodeStub = {
  workspace: {
    getConfiguration: () => ({
      get: (k, d) =>
        Object.prototype.hasOwnProperty.call(_cfgStore, k) ? _cfgStore[k] : d,
      update: () => Promise.resolve(),
    }),
    onDidChangeTextDocument: () => ({ dispose() {} }),
  },
  window: {
    createOutputChannel: () => ({ appendLine() {}, show() {}, dispose() {} }),
    createStatusBarItem: () => ({
      show() {},
      hide() {},
      dispose() {},
      text: "",
      tooltip: "",
      command: "",
    }),
    showInformationMessage: () => Promise.resolve(),
    showWarningMessage: () => Promise.resolve(),
    showErrorMessage: () => Promise.resolve(),
  },
  commands: {
    registerCommand: () => ({ dispose() {} }),
    executeCommand: () => Promise.resolve(),
  },
  env: { clipboard: { writeText: () => Promise.resolve() } },
  Uri: { file: (p) => ({ fsPath: p, toString: () => p }) },
  StatusBarAlignment: { Right: 2, Left: 1 },
  ViewColumn: { Active: -1, One: 1 },
  ConfigurationTarget: { Global: 1, Workspace: 2 },
  ThemeColor: class {},
  EventEmitter: class {
    event() {
      return () => {};
    }
  },
};
const origReq = Module.prototype.require;
Module.prototype.require = function (req) {
  if (req === "vscode") return vscodeStub;
  return origReq.call(this, req);
};

// ── 加载 ──
const ext = require(path.join(__dirname, "extension.js"));
const { Store } = ext._internals;

// ── 测试断言框架 ──
let pass = 0,
  fail = 0;
const log = [];
function expect(name, cond, detail) {
  const tag = cond ? "✓" : "✗";
  console.log("  " + tag + " " + name + (detail ? " · " + detail : ""));
  if (cond) pass++;
  else fail++;
}

// ── 装备: 4 个 Pro 号 + Store ──
function buildStore() {
  const s = new Store();
  s.accounts = [
    { email: "alpha@e.com", password: "p1" },
    { email: "beta@e.com", password: "p2" },
    { email: "gamma@e.com", password: "p3" },
    { email: "delta@e.com", password: "p4" },
  ];
  for (const a of s.accounts) {
    s.health[a.email.toLowerCase()] = {
      checked: true,
      daily: 80,
      weekly: 70,
      plan: "Pro",
      planEnd: 0,
      daysLeft: 30,
      lastChecked: Date.now(),
      hasSnap: true,
    };
  }
  // 初始 active = alpha
  s.activeIdx = 0;
  s.activeEmail = "alpha@e.com";
  return s;
}

// ── 模拟 mock loginAccount: 直接调 store.setActive (绕过真实网络) ──
function mockLogin(store, idx) {
  const acc = store.accounts[idx];
  if (!acc) return { ok: false, error: "idx_oob" };
  store.setActive(idx, acc.email, "tk-" + idx, null, null, "MOCK");
  return { ok: true };
}

// ── 模拟一条消息触发: 走 _isValidAutoTarget → getBestIndex → loginAccount ──
function simulateMessage(store, msgIdx) {
  console.log("  --- M" + msgIdx + " (t=" + (msgIdx - 1) * 5 + "s) ---");
  // _maybeTrigger 主流: getBestIndex 排除 in-use → 选号 → loginAccount
  const bestI = store.getBestIndex(store.activeIdx);
  if (bestI < 0) {
    console.log("    · 无候选 (全 in-use) · 不切");
    return { switched: false, to: null };
  }
  const targetEmail = store.accounts[bestI].email;
  const r = mockLogin(store, bestI);
  if (!r.ok) {
    console.log("    · 切号失败: " + r.error);
    return { switched: false, to: null };
  }
  console.log(
    "    · 切→ " +
      targetEmail.split("@")[0] +
      " (idx=" +
      bestI +
      ") · 锁 " +
      Math.round(store.inUseRemainingMs(targetEmail) / 1000) +
      "s",
  );
  return { switched: true, to: targetEmail, idx: bestI };
}

// ════ 测试主体 ════
const _origNow = Date.now;
let _fakeT = 1700000000000;
Date.now = () => _fakeT;

// ──────────────────────────────────────────────
// 场景 A · 简易启动 (初始 active 未经 setActive 锁) · 跳号验证全循环可达
// 此场景模拟: 用户首启时插件未走 activate→loginAccount, 仅 state load 设 activeIdx
// ──────────────────────────────────────────────
console.log(
  "\n[E2E·A] 简易启动 (初始 alpha 未锁) · 5 消息 · 期前 4 条切号·第 5 条无候选\n",
);
const store = buildStore();
expect("A 初: alpha 是 active", store.activeEmail === "alpha@e.com");
expect("A 初: 无 in-use 锁", Object.keys(store.inUseUntil).length === 0);

// M1 (t=0): active=alpha · 锁=∅ · 选 best ≠ alpha
const m1 = simulateMessage(store, 1);
expect("A·M1 切号成功", m1.switched);
expect("A·M1 切到非 alpha", m1.to !== "alpha@e.com", "→ " + m1.to);
expect("A·M1 该号 in-use 锁", store.isInUse(m1.to));
// active 现在转 m1.to · alpha 仍未锁 (跳过了 setActive)

// M2 (t=5s): active=m1.to · 锁={m1.to} · alpha 仍可选 (未锁)
_fakeT += 5000;
const m2 = simulateMessage(store, 2);
expect("A·M2 切号成功", m2.switched);
expect("A·M2 切号 ≠ M1.to (排除 in-use)", m2.to !== m1.to, "→ " + m2.to);
// 注: M2 可能切回 alpha — 因为 alpha 未锁 (init 旁路) · getBestIndex 排除 currentI=m1.to + isInUse=m1.to
// 候选 = {alpha} ∪ {未在 m1 选中的两号} · 全相同分数 · 选 idx 最低 = alpha(0)
expect("A·M2 该号 in-use 锁", store.isInUse(m2.to), "isInUse(" + m2.to + ")");

// M3 (t=10s): 锁={m1.to, m2.to}
_fakeT += 5000;
const m3 = simulateMessage(store, 3);
expect("A·M3 切号成功", m3.switched);
expect(
  "A·M3 切号 ≠ M1.to 也 ≠ M2.to",
  m3.to !== m1.to && m3.to !== m2.to,
  "→ " + m3.to,
);

// M4 (t=15s): 锁={m1, m2, m3}
_fakeT += 5000;
const m4 = simulateMessage(store, 4);
expect("A·M4 切号成功", m4.switched);
expect(
  "A·M4 切号 ≠ M1/M2/M3",
  m4.to !== m1.to && m4.to !== m2.to && m4.to !== m3.to,
  "→ " + m4.to,
);

// 此时 4 号全部锁 (M1+M2+M3+M4 各一)
const all4 = new Set([m1.to, m2.to, m3.to, m4.to]);
expect(
  "A 状态: 4 切号涵盖 4 个不同号 (alpha+beta+gamma+delta)",
  all4.size === 4,
);

// M5 (t=20s): 全锁 · 无候选
_fakeT += 5000;
const m5 = simulateMessage(store, 5);
expect("A·M5 全锁 · 不切 (柔弱避而不绝)", m5.switched === false);
expect("A·M5 总切号 = 4", store.switches === 4);

// t=145s: 锁始 t=0 (m1) 已过 120s
_fakeT += 125 * 1000; // 总 t=145s
expect("A t=145s · m1.to 解锁 (锁 120s)", store.isInUse(m1.to) === false);
// m4.to 锁始 t=15s · 锁到 t=135s · t=145s 已过
expect("A t=145s · m4.to 解锁", store.isInUse(m4.to) === false);

// ──────────────────────────────────────────────
// 场景 B · 真实启动 (initial setActive 也打 in-use 印) · 验 4 号 3 切+1 等
// 此场景模拟: 插件 activate → loginAccount(0) → setActive(alpha) → markInUse(alpha)
// 之后用户连发 5 条消息
// ──────────────────────────────────────────────
console.log(
  "\n[E2E·B] 真实启动 (alpha 已被 setActive 锁) · 期 3 切 + M4/M5 全锁\n",
);
_fakeT += 1000; // 推进 1s 避结果残留
const storeB = buildStore();
storeB.activeIdx = -1; // 重置 active · 让 mockLogin 真打
storeB.activeEmail = null;
mockLogin(storeB, 0); // 启动 setActive(alpha) · alpha 锁
expect("B 初: alpha 是 active", storeB.activeEmail === "alpha@e.com");
expect("B 初: alpha 已锁 (启动 setActive)", storeB.isInUse("alpha@e.com"));

// M1: active=alpha (锁) · 候选 = {beta, gamma, delta}
const bm1 = simulateMessage(storeB, 1);
expect("B·M1 切号成功", bm1.switched);
expect("B·M1 ≠ alpha", bm1.to !== "alpha@e.com");

// M2 (5s): 锁={alpha, bm1} · 候选 ⊂ {beta,gamma,delta}\{bm1.to}
_fakeT += 5000;
const bm2 = simulateMessage(storeB, 2);
expect("B·M2 切号成功", bm2.switched);
expect(
  "B·M2 ≠ alpha 也 ≠ bm1.to",
  bm2.to !== "alpha@e.com" && bm2.to !== bm1.to,
);

// M3 (10s): 锁={alpha, bm1, bm2}
_fakeT += 5000;
const bm3 = simulateMessage(storeB, 3);
expect("B·M3 切号成功", bm3.switched);

// M4 (15s): 4 号全锁 (alpha 锁始 t=0+1, bm1 锁始 t=1, bm2 锁始 t=6, bm3 锁始 t=11) · 全锁
_fakeT += 5000;
const bm4 = simulateMessage(storeB, 4);
expect("B·M4 全锁 · 不切 (alpha 已被 init 锁)", bm4.switched === false);

// M5 (20s): 仍全锁 (最早锁 alpha t=0+1, 锁到 t=120+1=121, 现 t=20 远远未到)
_fakeT += 5000;
const bm5 = simulateMessage(storeB, 5);
expect("B·M5 仍全锁", bm5.switched === false);
// 注: 启动 mockLogin(0) 也算 1 次切号 (init→alpha) · 加 M1+M2+M3 = 4
expect("B 状态: 总切号 4 次 (init+M1+M2+M3)", storeB.switches === 4);

// 时间推进至 alpha 解锁 (锁 120s · 锁始 t≈1s · 解锁 t≈121s)
_fakeT = 1700000000000 + 145 * 1000 + 1000 + 122 * 1000;
expect("B t≈268s · alpha 已解锁", storeB.isInUse("alpha@e.com") === false);

Date.now = _origNow;

// ── 第二轮: clearAllInUse 命令验 ──
console.log("\n[CLEAR] wam.clearAllInUse 手清验");
{
  const s2 = buildStore();
  s2.markInUse("alpha@e.com", 60000);
  s2.markInUse("beta@e.com", 60000);
  s2.markInUse("gamma@e.com", 60000);
  expect("锁 3 个", Object.keys(s2.inUseUntil).length === 3);
  const cleared = s2.clearAllInUse();
  expect("clearAllInUse 返计数 3", cleared === 3);
  expect("清后锁 0 个", Object.keys(s2.inUseUntil).length === 0);
  expect("清后 alpha 可选", s2.isInUse("alpha@e.com") === false);
  expect("清后 _scoreOf > -Infinity", s2._scoreOf(0) > -Infinity);
}

// 清理
try {
  fs.rmSync(tmpHome, { recursive: true, force: true });
} catch {}

console.log("\n═══ E2E 总计 ═══");
console.log("  ✓ pass: " + pass);
console.log("  ✗ fail: " + fail);
console.log(
  "  道法自然 · " + (fail === 0 ? "无为而无不为" : "未尽 · 反者道之动"),
);
process.exit(fail > 0 ? 1 : 0);
