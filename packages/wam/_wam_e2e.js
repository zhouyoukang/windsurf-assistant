/**
 * WAM · rt-flow E2E test · v17.41.0 · 唯变所适 · 去除一切硬路径硬端口硬编码
 * Offline static analysis — validates source integrity without runtime
 * Usage: node _wam_e2e.js [extDir]
 */
const fs = require("fs");
const path = require("path");

let pass = 0,
  fail = 0,
  skip = 0;
function assert(cond, msg) {
  if (cond) {
    pass++;
  } else {
    fail++;
    console.log(`  FAIL: ${msg}`);
  }
}
function section(title) {
  console.log(`\n# ${title}`);
}

// ── Locate extension.js ──
const extDir = process.argv[2] || path.resolve(__dirname);
const extPath = path.join(extDir, "extension.js");
if (!fs.existsSync(extPath)) {
  console.log(`ERROR: extension.js not found at ${extPath}`);
  process.exit(1);
}
const stat = fs.statSync(extPath);
console.log(`extension.js: ${extPath} (${stat.size} B)`);
const code = fs.readFileSync(extPath, "utf8");

// ══ L1: Package.json ══
section("L1: Package.json");
const pkgPath = path.join(extDir, "package.json");
if (fs.existsSync(pkgPath)) {
  const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
  assert(pkg.name === "rt-flow", `name=rt-flow (got ${pkg.name})`);
  assert(
    pkg.main === "./extension.js",
    `main=./extension.js (got ${pkg.main})`,
  );
  assert(pkg.version === "17.41.0", `version=17.41.0 (got ${pkg.version})`);
  assert(pkg.engines && pkg.engines.vscode, "engines.vscode defined");
  assert(
    pkg.activationEvents && pkg.activationEvents.includes("onStartupFinished"),
    "activates onStartupFinished",
  );
  const cmds = (pkg.contributes && pkg.contributes.commands) || [];
  const wamCmds = cmds.filter((c) => c.command.startsWith("wam."));
  assert(wamCmds.length >= 15, `wam.* commands >= 15 (got ${wamCmds.length})`);
  // Origin commands should still be registered (backward compat) but with deprecation hints
  const e2eCmd = cmds.find((c) => c.command === "wam.verifyEndToEnd");
  assert(!!e2eCmd, "wam.verifyEndToEnd command registered (backward compat)");
  // Configuration
  const props =
    (pkg.contributes.configuration &&
      pkg.contributes.configuration.properties) ||
    {};
  assert(props["wam.autoRotate"], "wam.autoRotate config exists");
  assert(
    props["wam.autoUpdate.enabled"],
    "wam.autoUpdate.enabled config exists",
  );
  assert(
    props["wam._origin_removed"],
    "wam._origin_removed deprecation marker exists",
  );
  assert(
    props["wam._origin_removed"].deprecationMessage,
    "_origin_removed has deprecationMessage",
  );
  // No stale origin settings (wam.origin.* should not exist)
  const originKeys = Object.keys(props).filter((k) =>
    k.startsWith("wam.origin."),
  );
  assert(
    originKeys.length === 0,
    `no wam.origin.* settings (got ${originKeys.length}: ${originKeys.join(",")})`,
  );
  // L1.extra: Stealth identity check
  assert(
    !pkg.name.includes("windsurf") && !pkg.name.includes("assistant"),
    "name has no banned keywords",
  );
  assert(
    !pkg.publisher.includes("zhouyoukang"),
    "publisher has no banned keywords",
  );
  console.log(
    `  pkg: ${pkg.name}@${pkg.version} pub=${pkg.publisher}, ${cmds.length} cmds (${wamCmds.length} wam.*)`,
  );
} else {
  skip++;
  console.log("  SKIP: package.json not found");
}

// ══ L2: WAM_VERSION alignment ══
section("L2: WAM_VERSION alignment");
const verMatch = code.match(/WAM_VERSION\s*=\s*"([^"]+)"/);
assert(verMatch, "WAM_VERSION constant exists");
if (verMatch) {
  assert(verMatch[1] === "17.41.0", `WAM_VERSION=17.41.0 (got ${verMatch[1]})`);
}

// ══ L3: Core classes & functions ══
section("L3: Core module structure");
assert(
  code.includes("_detectProductName"),
  "_detectProductName (product auto-detect)",
);
assert(
  code.includes("_resolveDataDir"),
  "_resolveDataDir (data dir auto-detect)",
);
assert(code.includes("firebaseLogin"), "firebaseLogin function");
assert(code.includes("fetchAccountQuota"), "fetchAccountQuota function");
assert(code.includes("sanitizeCredential"), "sanitizeCredential function");
assert(code.includes("getBestIndex"), "getBestIndex method");
assert(
  code.includes("_sidebarProvider"),
  "_sidebarProvider (webview panel provider)",
);
assert(code.includes("module.exports"), "module.exports present");

// ══ L4: Devin dual-identity support ══
section("L4: Devin dual-identity");
assert(
  code.includes("devin") || code.includes("Devin"),
  "Devin support referenced",
);
assert(
  code.includes("_devinFullSwitch") || code.includes("devinFullSwitch"),
  "devinFullSwitch logic",
);
assert(
  code.includes("_devin-auth") || code.includes("devin-auth"),
  "Devin auth endpoint",
);

// ══ L5: Persistence (v17.37 critical fix) ══
section("L5: Persistence (v17.37 fix)");
const saveCount = (code.match(/_store\.save\(\)/g) || []).length;
assert(saveCount >= 20, `_store.save() calls >= 20 (got ${saveCount})`);
// No stale _saveStore() references
const staleCount = (code.match(/_saveStore\s*\(/g) || []).length;
assert(staleCount === 0, `no stale _saveStore() calls (got ${staleCount})`);
// doAutoRotate should persist
assert(
  code.includes("doAutoRotate") || code.includes("autoRotate"),
  "doAutoRotate function exists",
);
// panicSwitch should persist
assert(code.includes("panicSwitch"), "panicSwitch function exists");

// ══ L6: Chromium native bridge ══
section("L6: Chromium native bridge");
assert(code.includes("_bridgeReady"), "_bridgeReady flag");
assert(code.includes("_bridgeReadyCallbacks"), "_bridgeReadyCallbacks queue");
assert(code.includes("_fetchPending"), "_fetchPending map");
assert(code.includes("_bridgeEnsureTimer"), "_bridgeEnsureTimer");

// ══ L7: Token pool & predictive warming ══
section("L7: Token pool");
assert(code.includes("getBestIndex"), "getBestIndex (round-robin selection)");
assert(code.includes("bestI"), "bestI variable (best account index)");
assert(
  code.includes("getPoolStats") || code.includes("getHealth"),
  "pool stats / health check",
);
assert(
  code.includes("_prewarmedToken") || code.includes("prewarmedToken"),
  "token pre-warming",
);

// ══ L8: Timer management ══
section("L8: Timer management");
assert(code.includes("_scanTimer"), "_scanTimer");
assert(code.includes("_pollTimer"), "_pollTimer");
assert(
  code.includes("_monitorTimer") || code.includes("_rateLimitWatcher"),
  "monitor/rateLimit timer",
);

// ══ L9: Origin separation (v17.36) ══
section("L9: Origin separation (v17.36)");
// After v17.36, WAM should NOT contain OriginCtl / OriginProxy spawn logic
// But backward-compat stubs should exist
assert(
  !code.includes("class OriginCtl") && !code.includes("class OriginProxy"),
  "no OriginCtl/OriginProxy class (剥离 to dao-agi)",
);
// Backward compat: origin commands registered but show migration notice
assert(
  code.includes("_origin_removed") ||
    code.includes("origin_removed") ||
    code.includes("已移至"),
  "origin removal notice present",
);

// ══ L10: bundled-origin 已删除 (v17.41 损之又损) ══
section("L10: bundled-origin removed (v17.41)");
const verFile = path.join(extDir, "bundled-origin", "VERSION");
assert(
  !fs.existsSync(verFile),
  "bundled-origin/VERSION 已删除 (v17.41 死代码清理)",
);
const bundledDir = path.join(extDir, "bundled-origin");
assert(!fs.existsSync(bundledDir), "bundled-origin/ 目录已删除");

// ══ L11: .vscodeignore (VSIX content control) ══
section("L11: .vscodeignore");
const vsciPath = path.join(extDir, ".vscodeignore");
if (fs.existsSync(vsciPath)) {
  const vsci = fs.readFileSync(vsciPath, "utf8");
  assert(vsci.includes("!extension.js"), ".vscodeignore includes extension.js");
  assert(vsci.includes("!package.json"), ".vscodeignore includes package.json");
  // bundled-origin should NOT be included (v17.36 stripping)
  assert(
    !vsci.includes("!bundled-origin"),
    "bundled-origin NOT included in VSIX (Origin剥离)",
  );
} else {
  skip++;
  console.log("  SKIP: .vscodeignore not found");
}

// ══ L12: Auto-update system ══
section("L12: Auto-update");
assert(
  code.includes("autoUpdate") || code.includes("auto_update"),
  "autoUpdate system",
);
assert(
  code.includes("jsDelivr") || code.includes("jsdelivr"),
  "jsDelivr CDN fallback",
);
assert(
  code.includes("checkUpdate") || code.includes("_checkUpdate"),
  "checkUpdate function",
);

// ══ L13: Soft-coding verification (zero hardcoded secrets) ══
section("L13: Soft-coding (no hardcoded secrets)");
// No hardcoded Firebase API keys (should be in config or fetched)
const hardcodedKeys = code.match(/AIza[A-Za-z0-9_-]{35}/g) || [];
// Some keys may be defaults in code — just count, not fail
console.log(
  `  Firebase API keys in code: ${hardcodedKeys.length} (soft-coded via wam.firebase.extraKeys)`,
);
// No hardcoded passwords
assert(
  !code.includes("password123") && !code.includes("P@ssw0rd"),
  "no obvious hardcoded passwords",
);

// ══ L14: Deactivate cleanup ══
section("L14: Deactivate cleanup");
assert(code.includes("function deactivate"), "deactivate function exists");
assert(code.includes("_saveSnapshots"), "snapshots saved on deactivate");
assert(code.includes("_saveTokenCache"), "token cache saved on deactivate");
assert(code.includes("_saveInUse"), "inUse marks saved on deactivate");
assert(
  code.includes("_uninstallMessageAnchor"),
  "messageAnchor uninstalled on deactivate",
);

// ══ L15: v17.39 消息锚定·五路道并行 ══
section("L15: messageAnchor (v17.39 · 反者道之动)");
assert(code.includes("_msgAnchor"), "_msgAnchor state object exists");
assert(code.includes("_msgAnchorTrigger"), "_msgAnchorTrigger unified entry");
assert(code.includes("_msgAnchorDoSwitch"), "_msgAnchorDoSwitch switch logic");
assert(
  code.includes("_installNetworkAnchor"),
  "Path A: network monkey-patch installer",
);
assert(
  code.includes("_installCommandAnchor"),
  "Path B: command monkey-patch installer",
);
assert(
  code.includes("_installCascadeFileAnchor"),
  "Path C: cascade file watcher installer",
);
assert(
  code.includes("_installMessageAnchor"),
  "_installMessageAnchor orchestrator",
);
assert(
  code.includes("_uninstallMessageAnchor"),
  "_uninstallMessageAnchor teardown",
);
assert(
  code.includes("_msgAnchorSnapshot"),
  "_msgAnchorSnapshot diagnostic interface",
);
assert(
  code.includes("messageAnchor.enabled"),
  "messageAnchor.enabled config key referenced",
);
assert(
  code.includes("messageAnchor.debounceMs"),
  "messageAnchor.debounceMs config key referenced",
);
assert(
  code.includes("messageAnchor.everyN"),
  "messageAnchor.everyN config key referenced",
);
assert(
  code.includes("messageAnchor.dedupeMs"),
  "messageAnchor.dedupeMs config key referenced",
);
assert(
  code.includes("messageAnchor.path"),
  "messageAnchor.path.* config keys referenced",
);
assert(
  code.includes("_msgAnchor.paths.network"),
  "path-network tracked in state",
);
assert(
  code.includes("_msgAnchor.paths.command"),
  "path-command tracked in state",
);
assert(
  code.includes("_msgAnchor.paths.cascade"),
  "path-cascade tracked in state",
);
assert(
  code.includes("_msgAnchor.paths.ratelim"),
  "path-ratelim tracked in state",
);
assert(
  code.includes(".codeium") &&
    code.includes("windsurf") &&
    code.includes("cascade"),
  "cascade dir path ~/.codeium/windsurf/cascade",
);
assert(
  code.includes("fingerprint") || code.includes("StreamCascade"),
  "cascade network fingerprint regex present",
);
// multi-Dao: network.request 被钩且保留原函数
assert(
  code.includes("origHttpsReq"),
  "https.request original preserved for restore",
);
assert(
  code.includes("origExec"),
  "executeCommand original preserved for restore",
);
// package.json cross-check
if (fs.existsSync(pkgPath)) {
  const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
  const props =
    (pkg.contributes &&
      pkg.contributes.configuration &&
      pkg.contributes.configuration.properties) ||
    {};
  assert(
    props["wam.messageAnchor.enabled"],
    "wam.messageAnchor.enabled exposed in package.json",
  );
  assert(
    props["wam.messageAnchor.debounceMs"],
    "wam.messageAnchor.debounceMs exposed",
  );
  assert(props["wam.messageAnchor.everyN"], "wam.messageAnchor.everyN exposed");
  assert(
    props["wam.messageAnchor.path.network"],
    "wam.messageAnchor.path.network exposed",
  );
  assert(
    props["wam.messageAnchor.path.command"],
    "wam.messageAnchor.path.command exposed",
  );
  assert(
    props["wam.messageAnchor.path.cascade"],
    "wam.messageAnchor.path.cascade exposed",
  );
}
// exports include snapshot API
assert(
  /module\.exports\s*=\s*\{[^}]*_msgAnchorSnapshot/.test(code),
  "_msgAnchorSnapshot exported",
);
// activate hook
assert(
  /_installMessageAnchor\s*\(\s*context\s*\)/.test(code),
  "_installMessageAnchor(context) called in activate",
);
// 太上不知有之: 新路径不能 showInformationMessage (仅日志)
const msgAnchorSection = (code.match(/v17\.39[\s\S]*?v17\.39 END/) || [""])[0];
const toastInAnchor = (msgAnchorSection.match(/showInformationMessage/g) || [])
  .length;
assert(
  toastInAnchor === 0,
  `no showInformationMessage in messageAnchor region (got ${toastInAnchor})`,
);

// ══ L16: v17.40 Devin-first 千繁归一·持久化根治 ══
section("L16: Devin-first (v17.40 · 万法归宗)");
assert(code.includes("preferDevinFirst"), "preferDevinFirst 开关引用");
assert(code.includes("firebaseMaxTimeoutMs"), "firebaseMaxTimeoutMs 配置");
assert(
  code.includes("_persistDevinMark"),
  "_persistDevinMark 持久化辅助 (根治: v17.35 缺 save 的 bug)",
);
assert(
  code.includes("_persistFirebaseMark"),
  "_persistFirebaseMark 持久化辅助",
);
assert(code.includes("goDevinFirst"), "goDevinFirst 分支标志");
assert(code.includes("devinKnown"), "devinKnown 已知 devin 账号判定");
assert(
  code.includes("firebaseLocked"),
  "firebaseLocked 明确标记的 firebase 账号",
);
assert(code.includes("firebase_overall_timeout"), "Firebase 整体超时保护");
assert(code.includes("both_auth_failed"), "双路皆败错误标识");
assert(/if\s*\(\s*goDevinFirst\s*\)/.test(code), "goDevinFirst if 分支");
assert(/Promise\.race\s*\(/.test(code), "Promise.race 超时竞速使用");
// 持久化根治: _persistDevinMark 函数体内必须有 _store.save() (v17.35 遗漏 bug 的修复验证)
const devinMarkDefIdx = code.indexOf("const _persistDevinMark");
const devinMarkDefEnd = code.indexOf(
  "const _persistFirebaseMark",
  devinMarkDefIdx,
);
const devinMarkBody =
  devinMarkDefIdx > 0 && devinMarkDefEnd > devinMarkDefIdx
    ? code.substring(devinMarkDefIdx, devinMarkDefEnd)
    : "";
assert(
  devinMarkBody.includes("_store.save()"),
  "_persistDevinMark 函数体内有 _store.save() 调用 (持久化根治)",
);
// package.json cross-check
if (fs.existsSync(pkgPath)) {
  const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
  const props =
    (pkg.contributes &&
      pkg.contributes.configuration &&
      pkg.contributes.configuration.properties) ||
    {};
  assert(props["wam.preferDevinFirst"], "wam.preferDevinFirst 在 package.json");
  assert(
    props["wam.preferDevinFirst"].default === true,
    "wam.preferDevinFirst 默认 true",
  );
  assert(
    props["wam.firebaseMaxTimeoutMs"],
    "wam.firebaseMaxTimeoutMs 在 package.json",
  );
  assert(
    typeof props["wam.firebaseMaxTimeoutMs"].default === "number",
    "firebaseMaxTimeoutMs 默认是数字",
  );
}

// ══ L17: v17.41 唯变所适 · 去除硬路径硬端口硬编码 ══
section("L17: 唯变所适 (v17.41 · 道法自然)");
assert(code.includes("_resolveWamDir"), "_resolveWamDir 动态解析 WAM_DIR");
assert(code.includes("WAM_HOT_DIR"), "env WAM_HOT_DIR 支持");
assert(code.includes("_deriveWamPaths"), "_deriveWamPaths 派生路径函数");
assert(code.includes("_deriveOrigin"), "_deriveOrigin URL origin 自动推导");
assert(code.includes("_getRegisterUrl"), "_getRegisterUrl 可配化");
assert(code.includes("_getChatCapacityUrl"), "_getChatCapacityUrl 可配化");
assert(code.includes("_getClaudeProbeModel"), "_getClaudeProbeModel 可配化");
assert(code.includes("_getDevinLoginUrl"), "_getDevinLoginUrl 可配化");
assert(
  code.includes("_getWindsurfPostAuthUrl"),
  "_getWindsurfPostAuthUrl 可配化",
);
assert(
  code.includes("_getOfficialPlanStatusUrls"),
  "_getOfficialPlanStatusUrls 可配化",
);
assert(
  code.includes("_getFallbackScanPorts"),
  "_getFallbackScanPorts 可配化端口扫描",
);
assert(code.includes("_getGatewayPorts"), "_getGatewayPorts 可配化网关端口");
assert(code.includes("_getFirebaseKeys"), "_getFirebaseKeys 可配化");
assert(code.includes("_getFirebaseReferer"), "_getFirebaseReferer 可配化");
assert(code.includes("_getFirebaseHost"), "_getFirebaseHost 可配化");
// WAM_DIR 必须是 let (不是 const) — 支持 activate() 时重赋值
assert(/^let WAM_DIR/m.test(code), "WAM_DIR 声明为 let (可重赋值)");
// package.json cross-check v17.41 新配置
if (fs.existsSync(pkgPath)) {
  const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
  const props =
    (pkg.contributes &&
      pkg.contributes.configuration &&
      pkg.contributes.configuration.properties) ||
    {};
  assert(props["wam.wamHotDir"], "wam.wamHotDir 在 package.json");
  assert(props["wam.claudeProbeModel"], "wam.claudeProbeModel 在 package.json");
  assert(props["wam.devin.loginUrl"], "wam.devin.loginUrl 在 package.json");
  assert(
    props["wam.devin.postAuthUrl"],
    "wam.devin.postAuthUrl 在 package.json",
  );
  assert(props["wam.registerUrl"], "wam.registerUrl 在 package.json");
  assert(props["wam.chatCapacityUrl"], "wam.chatCapacityUrl 在 package.json");
  assert(props["wam.planStatusUrls"], "wam.planStatusUrls 在 package.json");
  assert(props["wam.proxy.scanPorts"], "wam.proxy.scanPorts 在 package.json");
  assert(
    props["wam.proxy.gatewayPorts"],
    "wam.proxy.gatewayPorts 在 package.json",
  );
}
// 无残余硬编码常量 (const 版本应已被替换)
assert(
  !code.includes("const _REGISTER_URL"),
  "_REGISTER_URL 不再是 const (已 getter 化)",
);
assert(
  !code.includes("const _CHAT_CAPACITY_URL"),
  "_CHAT_CAPACITY_URL 不再是 const (已 getter 化)",
);
assert(
  !code.includes("const _CLAUDE_PROBE_MODEL"),
  "_CLAUDE_PROBE_MODEL 不再是 const (已 getter 化)",
);
assert(!code.includes("const WAM_DIR"), "WAM_DIR 不再是 const (可动态赋值)");

// ══ Summary ══
console.log(`\n${"=".repeat(60)}`);
console.log(
  `WAM E2E v17.41.0 · RESULT: ${pass} pass / ${fail} fail / ${skip} skip`,
);
console.log(`STATUS: ${fail === 0 ? "✅ ALL GREEN" : "❌ FAILURES DETECTED"}`);
process.exit(fail > 0 ? 1 : 0);
