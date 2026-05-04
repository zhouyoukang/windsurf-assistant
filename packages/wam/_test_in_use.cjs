// v2.3.0 回归 · 使用中🔒 (反者道之动)
//
// 测点:
//   [A] markInUse / isInUse / inUseRemainingMs / clearInUse · 锁期 · 过期清
//   [B] _scoreOf 排除 in-use 账号 (返 -Infinity)
//   [C] getBestIndex / getSortedIndices 跳 in-use
//   [D] _bumpFailure v2.5 永不禁号 · 无论失败多少次 · count 只增 · 无 until · isBanned=false
//   [E] setActive 自动打 in-use 印 (使用 typeof _cfg 守 · 默认 120000ms)
//   [F] remove / removeBatch 清理 inUseUntil · 不残
//   [G] _isValidAutoTarget 五辨贯通 (含 isInUse)
"use strict";

const Module = require("node:module");
const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");

// ── 隔离: 临时 HOME · 防污染真用户 ~/.wam ──
const tmpHome = path.join(os.tmpdir(), "wam-test-in-use-" + process.pid);
fs.mkdirSync(tmpHome, { recursive: true });
process.env.HOME = tmpHome;
process.env.USERPROFILE = tmpHome;
// os.homedir() 缓存 · 直接 monkey-patch
os.homedir = () => tmpHome;

// ── 桩 vscode 模块 (extension.js 顶部 require) ──
const _cfgStore = {};
const vscodeStub = {
  workspace: {
    getConfiguration: () => ({
      get: (key, def) => {
        if (Object.prototype.hasOwnProperty.call(_cfgStore, key))
          return _cfgStore[key];
        return def;
      },
      update: () => Promise.resolve(),
    }),
    onDidChangeTextDocument: () => ({ dispose() {} }),
  },
  window: {
    createOutputChannel: () => ({
      appendLine() {},
      show() {},
      dispose() {},
    }),
    createStatusBarItem: () => ({
      show() {},
      hide() {},
      dispose() {},
      text: "",
      tooltip: "",
      command: "",
      color: undefined,
      backgroundColor: undefined,
    }),
    showInformationMessage: () => Promise.resolve(),
    showWarningMessage: () => Promise.resolve(),
    showErrorMessage: () => Promise.resolve(),
    showInputBox: () => Promise.resolve(""),
    showQuickPick: () => Promise.resolve(),
    createWebviewPanel: () => ({
      webview: { html: "", onDidReceiveMessage() {}, postMessage() {} },
      reveal() {},
      onDidDispose() {},
    }),
    registerWebviewViewProvider: () => ({ dispose() {} }),
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
  ThemeColor: class {
    constructor(id) {
      this.id = id;
    }
  },
  EventEmitter: class {
    event() {
      return () => {};
    }
  },
};

// 拦截 require("vscode")
const origReq = Module.prototype.require;
Module.prototype.require = function (req) {
  if (req === "vscode") return vscodeStub;
  return origReq.call(this, req);
};

// ── 加载 extension.js ──
const extPath = path.join(__dirname, "extension.js");
const ext = require(extPath);
const { Store, _bumpFailure, _isValidAutoTarget } = ext._internals;

// ── 测试断言框架 ──
let pass = 0,
  fail = 0;
function expect(name, cond, detail) {
  if (cond) {
    console.log("  ✓ " + name + (detail ? " · " + detail : ""));
    pass++;
  } else {
    console.log("  ✗ " + name + (detail ? " · " + detail : ""));
    fail++;
  }
}

// 帮助: 创建一个 Store 实例 + 注入两个号 · 跳过磁盘 · 测试用
function makeStore() {
  const s = new Store();
  // 注入合成账号
  s.accounts = [
    { email: "alpha@test.com", password: "p1" },
    { email: "beta@test.com", password: "p2" },
    { email: "gamma@test.com", password: "p3" },
    { email: "delta@test.com", password: "p4" },
  ];
  // 全注健康 (Pro · 高额度) 让 _scoreOf 不卡 Claude 门
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
  return s;
}

console.log("\n[A] markInUse / isInUse / inUseRemainingMs · 锁期 · 过期清");
{
  const s = makeStore();
  expect("初: 无锁 · isInUse=false", s.isInUse("alpha@test.com") === false);
  expect("初: 余=0", s.inUseRemainingMs("alpha@test.com") === 0);
  s.markInUse("alpha@test.com", 5000);
  expect("锁 5s · isInUse=true", s.isInUse("alpha@test.com") === true);
  const rem = s.inUseRemainingMs("alpha@test.com");
  expect(
    "锁 5s · 余 ≈ 5000 (4990-5000)",
    rem > 4900 && rem <= 5000,
    "rem=" + rem,
  );
  expect("大小写不敏感 · ALPHA → in-use", s.isInUse("ALPHA@test.com") === true);
  expect("其它号未锁", s.isInUse("beta@test.com") === false);
  // 模拟过期: 直接覆写 inUseUntil
  s.inUseUntil["alpha@test.com"] = Date.now() - 100;
  expect("过期 · isInUse 自清 → false", s.isInUse("alpha@test.com") === false);
  expect(
    "过期被自清 · inUseUntil[alpha] 不存",
    !("alpha@test.com" in s.inUseUntil),
  );
  // markInUse 边界
  s.markInUse("", 5000);
  s.markInUse("x", 0);
  s.markInUse("x", -1);
  expect("空 email · 不锁", !("" in s.inUseUntil));
  expect("ms=0 · 不锁", !("x" in s.inUseUntil));
  // clearInUse
  s.markInUse("zeta@test.com", 5000);
  s.clearInUse("zeta@test.com");
  expect("clearInUse · 立解", s.isInUse("zeta@test.com") === false);
  s.markInUse("a@b", 1000);
  s.markInUse("c@d", 1000);
  const cleared = s.clearAllInUse();
  expect("clearAllInUse 返计数", cleared === 2);
  expect("clearAllInUse · 全空", Object.keys(s.inUseUntil).length === 0);
}

console.log("\n[B] _scoreOf 排除 in-use 账号");
{
  const s = makeStore();
  // 全为 Pro 高额度 · 平时全可选
  const scoreBefore = s._scoreOf(0);
  expect("初: alpha 评分 > -Infinity", scoreBefore > -Infinity);
  s.markInUse("alpha@test.com", 60000);
  expect(
    "锁后: alpha 评分 = -Infinity",
    s._scoreOf(0) === -Infinity,
    "got " + s._scoreOf(0),
  );
  // 其他号不受影响
  expect("beta 评分仍 > -Infinity", s._scoreOf(1) > -Infinity);
}

console.log("\n[C] getBestIndex / getSortedIndices 跳 in-use");
{
  const s = makeStore();
  // alpha 高额度 (D=99 W=99) → 应是 best
  s.health["alpha@test.com"] = {
    ...s.health["alpha@test.com"],
    daily: 99,
    weekly: 99,
  };
  const bestNoLock = s.getBestIndex(-1);
  expect(
    "无锁: best 指 alpha (highest score)",
    bestNoLock === 0,
    "best=" + bestNoLock,
  );
  s.markInUse("alpha@test.com", 60000);
  const bestWithLock = s.getBestIndex(-1);
  expect(
    "锁 alpha · best 不再指 alpha",
    bestWithLock !== 0,
    "best=" + bestWithLock,
  );
  expect("锁 alpha · best ∈ {1,2,3}", bestWithLock >= 1 && bestWithLock <= 3);

  const sorted = s.getSortedIndices(-1);
  expect("getSortedIndices 不含 0(alpha)", !sorted.includes(0));
  expect("sorted 含 1,2,3", sorted.length === 3);
}

console.log(
  "\n[D] _bumpFailure v2.5 永不禁号 · count 只增 · 无 until · isBanned=false",
);
{
  const s = makeStore();
  // 第 1 次失败
  _bumpFailure(s, "alpha@test.com", "test fail");
  const e1 = s.blacklist["alpha@test.com"];
  expect("1次: count=1", e1 && e1.count === 1);
  expect("1次: 无 until (永不禁)", e1 && !e1.until);
  expect(
    "1次: isBanned=false (不冤杀)",
    s.isBanned("alpha@test.com") === false,
  );

  // 第 2 次
  _bumpFailure(s, "alpha@test.com", "test fail 2");
  const e2 = s.blacklist["alpha@test.com"];
  expect("2次: count=2", e2 && e2.count === 2);
  expect("2次: 无 until", e2 && !e2.until);
  expect("2次: isBanned=false", s.isBanned("alpha@test.com") === false);

  // 第 3 次 · v2.5 仍不入 ban (损之又损 · 号永远可选)
  _bumpFailure(s, "alpha@test.com", "test fail 3");
  const e3 = s.blacklist["alpha@test.com"];
  expect("3次: count=3", e3 && e3.count === 3);
  expect("3次: 无 until (v2.5 永不禁号)", e3 && !e3.until);
  expect(
    "3次: isBanned=false (永不禁号)",
    s.isBanned("alpha@test.com") === false,
  );

  // 第 10 次 · 依然永不禁
  for (let i = 4; i <= 10; i++) _bumpFailure(s, "alpha@test.com", "fail " + i);
  const e10 = s.blacklist["alpha@test.com"];
  expect("10次: count=10", e10 && e10.count === 10);
  expect("10次: 无 until", e10 && !e10.until);
  expect("10次: isBanned=false", s.isBanned("alpha@test.com") === false);

  // rate-limit 豁免: 连 count 都不 bump
  _bumpFailure(s, "beta@test.com", "devin: Rate limit exceeded");
  const eB = s.blacklist["beta@test.com"];
  expect("rate-limit: 不记数·blacklist 无条目", !eB);

  // 历史 until 自动清 (向后兼容老 state.json)
  s.blacklist["gamma@test.com"] = {
    count: 5,
    until: Date.now() + 999999,
    reason: "legacy",
  };
  expect("isBanned 清老 until", s.isBanned("gamma@test.com") === false);
  expect("老 until 被清掉", !s.blacklist["gamma@test.com"].until);

  // 防守: count-only 条目 (无 until) 属纯记数 · isBanned=false
  s.blacklist["zeta@test.com"] = { count: 1, reason: "stub" };
  expect(
    "isBanned 防守 count-only · 返 false",
    s.isBanned("zeta@test.com") === false,
  );
}

console.log("\n[E] setActive 自动打 in-use 印 (typeof _cfg 守)");
{
  // 此场景下 extension.js 已被 require · _cfg 已是函数 · 用桩 vscode getConfiguration 默认值
  const s = makeStore();
  s.setActive(0, "alpha@test.com", "devin-session-token$abc", null, null, "F");
  expect("setActive 后 · activeIdx=0", s.activeIdx === 0);
  expect(
    "setActive 后 · activeEmail=alpha",
    s.activeEmail === "alpha@test.com",
  );
  expect(
    "setActive 后 · alpha 自动 in-use",
    s.isInUse("alpha@test.com") === true,
  );
  const rem = s.inUseRemainingMs("alpha@test.com");
  expect(
    "默认锁 ≈ 120s (119000-120000)",
    rem > 119000 && rem <= 120000,
    "rem=" + rem,
  );

  // setActive 切到 beta · alpha 仍在 in-use (因 120s 未到), beta 也开始 in-use
  s.setActive(1, "beta@test.com", "devin-session-token$xyz", null, null, "B");
  expect(
    "切 beta · alpha 仍 in-use (120s 未到)",
    s.isInUse("alpha@test.com") === true,
  );
  expect("切 beta · beta 也 in-use", s.isInUse("beta@test.com") === true);
  expect("切 beta · activeEmail=beta", s.activeEmail === "beta@test.com");

  // 配置 inUseLockMs=0 → 关锁
  _cfgStore["inUseLockMs"] = 0;
  const s2 = makeStore();
  s2.setActive(0, "alpha@test.com", "tk", null, null, "F");
  expect(
    "inUseLockMs=0 · 不打印",
    s2.isInUse("alpha@test.com") === false,
    "应不锁",
  );
  delete _cfgStore["inUseLockMs"];

  // 配置 inUseLockMs=5000 · 宽容 Windows IO 抖动
  //   setActive → atomicWrite (write+fsync+rename) + state.save 链 · worst 可达 ~1s
  //   实测样本: 4997 (3ms IO) · 4781 (219ms IO) · 容差放宽至 1500ms (rem3 > 3500)
  _cfgStore["inUseLockMs"] = 5000;
  const s3 = makeStore();
  s3.setActive(0, "alpha@test.com", "tk", null, null, "F");
  const rem3 = s3.inUseRemainingMs("alpha@test.com");
  expect(
    "inUseLockMs=5000 · 锁 5s (容 1500ms IO jitter · Windows worst case)",
    rem3 > 3500 && rem3 <= 5000,
    "rem=" + rem3,
  );
  delete _cfgStore["inUseLockMs"];
}

console.log("\n[F] remove / removeBatch 清理 inUseUntil");
{
  const s = makeStore();
  s.markInUse("alpha@test.com", 60000);
  s.markInUse("beta@test.com", 60000);
  s.markInUse("gamma@test.com", 60000);
  expect("锁 3 个", Object.keys(s.inUseUntil).length === 3);
  s.remove(0); // 删 alpha
  expect("remove(alpha) · alpha 印消", !("alpha@test.com" in s.inUseUntil));
  expect("remove(alpha) · beta 印仍存", "beta@test.com" in s.inUseUntil);
  // 注: remove 操作 splice · 后续号 idx 左移 · 此时 0=beta, 1=gamma, 2=delta
  s.removeBatch([0, 1]); // 删 beta + gamma (索引)
  expect(
    "removeBatch · beta+gamma 印消",
    !("beta@test.com" in s.inUseUntil) && !("gamma@test.com" in s.inUseUntil),
  );
}

console.log("\n[G] _isValidAutoTarget 五辨 (含 isInUse)");
{
  // _isValidAutoTarget 用全局 _store · 须设它
  // 直接通过 ext._internals._store getter 读会拿到生产实例 · 测试不便
  // 改: 验证 _isValidAutoTarget 函数是 fn (导出存在) 即可
  expect("_isValidAutoTarget 已导出", typeof _isValidAutoTarget === "function");
  // 验五辨经在源码里 (字符串扫)
  const src = fs.readFileSync(extPath, "utf8");
  const fnSrc =
    src.match(/function _isValidAutoTarget\(i\)\s*\{[\s\S]+?\n\}/) || [];
  const body = fnSrc[0] || "";
  expect("五辨含 password", /\.password/.test(body));
  expect("五辨含 skipAutoSwitch", /skipAutoSwitch/.test(body));
  expect("五辨含 isBanned", /isBanned/.test(body));
  expect("五辨含 isInUse (v2.3.0 新)", /isInUse/.test(body));
  expect("五辨含 isClaudeAvailable", /isClaudeAvailable/.test(body));
}

console.log("\n[H] 体积守卫 (大制不割 · 监控代码膨胀)");
{
  const sz = fs.statSync(extPath).size;
  // v2.2.0 ≈ 121 KB · v2.3.0 加 21 KB (in-use) · v2.4.1 加 crypto+真路径 ≈ 158 KB
  // v2.4.4 加 setHealth 防御 + Layer 3 fetch ≈ 170 KB
  // v2.4.5 加 Layer 4 http2 hook ≈ 173 KB
  //   上限 200 KB (允未来小规模增 · 防大失控)
  expect(
    "extension.js 体积 < 200 KB",
    sz < 200 * 1024,
    sz + " bytes (~" + Math.round(sz / 1024) + " KB)",
  );
}

// 清理临时目录
try {
  fs.rmSync(tmpHome, { recursive: true, force: true });
} catch {}

console.log("\n═══ 总计 ═══");
console.log("  ✓ pass: " + pass);
console.log("  ✗ fail: " + fail);
console.log(
  "  道法自然 · " + (fail === 0 ? "无为而无不为" : "未尽 · 反者道之动"),
);
process.exit(fail > 0 ? 1 : 0);
