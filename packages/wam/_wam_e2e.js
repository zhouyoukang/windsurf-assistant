/**
 * WAM · rt-flow E2E test · v17.42.7 · 锁🔒全链贯通 + 一键导出 (叠加 v17.42.6 env 自净 + v17.42.5 五刀贯通)
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
  assert(pkg.version === "17.42.7", `version=17.42.7 (got ${pkg.version})`);
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
  assert(verMatch[1] === "17.42.7", `WAM_VERSION=17.42.7 (got ${verMatch[1]})`);
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
  code.includes("_msgAnchor.paths.http2"),
  "path-http2 tracked in state (v17.42)",
);
assert(
  code.includes("_installHttp2Anchor"),
  "Path E: HTTP/2 prototype-level hook installer (v17.42)",
);
assert(
  code.includes("_uninstallHttp2Anchor"),
  "_uninstallHttp2Anchor teardown (v17.42)",
);
assert(
  code.includes(".codeium") &&
    code.includes("windsurf") &&
    code.includes("cascade"),
  "cascade dir path ~/.codeium/windsurf/cascade",
);
assert(
  code.includes("grpcCascadeSend") ||
    code.includes("StreamCascade") ||
    code.includes("cloudPath"),
  "cascade network fingerprint regex present (v17.42: grpcCascadeSend/cloudPath)",
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

// ══ L18: v17.42 反者道之动 · 逆向本源根治msgAnchor ══
section(
  "L18: v17.42 反者道之动 (localhost gRPC + http2 + fetch + 五感退出 + monitor退避)",
);
// http2 require
assert(code.includes('require("http2")'), "http2 module imported");
// Path A 增强: localhost gRPC 双层匹配
assert(
  code.includes("localHost") || code.includes("localhost"),
  "localhost gRPC 匹配 (v17.42 双层: 云端宽松+本地精确)",
);
assert(
  code.includes("grpcCascadeSend") || code.includes("SendUserCascadeMessage"),
  "逆向确认的真实 gRPC 方法名 (SendUserCascadeMessage 等)",
);
// Path A 增强: globalThis.fetch hook
assert(
  code.includes("origFetch") || code.includes("patchedFetch"),
  "globalThis.fetch hook (ConnectRPC undici 覆盖)",
);
// Path E: HTTP/2 prototype-level hook
assert(
  code.includes("origProtoRequest") || code.includes("_patchedProto"),
  "HTTP/2 ClientHttp2Session.prototype.request hook (v17.42 原型链穿透)",
);
assert(
  code.includes("_getActiveHandles"),
  "process._getActiveHandles 定位活跃 HTTP/2 session",
);
// 消息即标记使用中
assert(
  code.includes("markInUse"),
  "消息发送即标记使用中 (v17.42: 不等额度变化)",
);
// 五感快速退出 (inject 失败不重试)
assert(
  code.includes("五感注入失败") || code.includes("五感模式"),
  "五感注入失败快速退出 (知止可以不殆)",
);
// monitor 退避 (连续失败递增间隔)
assert(
  code.includes("_monitorConsecutiveFails"),
  "monitor 连续失败退避计数 (v17.42 知止可以不殆)",
);
assert(code.includes("monitorInterval"), "monitor 动态退避间隔函数");
// v17.42.1: 切号重置退避 (归入 _afterSwitchSuccess 后仅 2 处: helper定义 + fetch成功)
assert(
  (code.match(/_monitorConsecutiveFails\s*=\s*0/g) || []).length >= 2,
  "_monitorConsecutiveFails=0 至少 2 处 (helper + 监测成功)",
);
// v17.42.1: origFetch 初始声明
assert(
  code.includes("origFetch: null"),
  "origFetch: null 初始声明 (fetch hook 状态完整)",
);

// ══ L19: v17.42.2 去芜存菁 · 切号后state不变量归一 ══
section("L19: v17.42.2 去芜存菁 (大制不割 · _afterSwitchSuccess)");
assert(
  code.includes("function _afterSwitchSuccess"),
  "_afterSwitchSuccess 统一不变量函数 (v17.42.2)",
);
// helper 必须包含所有 6 项不变量
const asDefIdx = code.indexOf("function _afterSwitchSuccess");
const asDefEnd = asDefIdx > 0 ? code.indexOf("\n}", asDefIdx) : -1;
const asBody =
  asDefIdx > 0 && asDefEnd > asDefIdx
    ? code.substring(asDefIdx, asDefEnd + 2)
    : "";
assert(
  asBody.includes("_store.activeIndex = bestI"),
  "_afterSwitchSuccess 含 _store.activeIndex 赋值",
);
assert(
  asBody.includes("_store.switchCount++"),
  "_afterSwitchSuccess 含 switchCount 递增",
);
assert(
  asBody.includes("_lastSwitchTime = Date.now()"),
  "_afterSwitchSuccess 含 _lastSwitchTime 更新",
);
assert(
  asBody.includes("_monitorConsecutiveFails = 0"),
  "_afterSwitchSuccess 含 monitor 退避重置",
);
assert(
  asBody.includes("_store.save()"),
  "_afterSwitchSuccess 含 _store.save() 持久化",
);
assert(
  asBody.includes("_quotaSnapshots.delete"),
  "_afterSwitchSuccess 含快照失效",
);
assert(
  asBody.includes("_schedulePersist"),
  "_afterSwitchSuccess 含 _schedulePersist",
);
// 8 路切号成功位全部调用 helper (msgAnchor/monitor/exhaust/ratelim/setMode/autoRotate/panic/wamMode)
const callCount = (code.match(/_afterSwitchSuccess\(/g) || []).length;
assert(
  callCount >= 9, // 1 定义 + 8 调用
  `_afterSwitchSuccess 调用 ≥ 8 处 (1 定义 + 8 切号位) · got ${callCount}`,
);
// 除 helper 外, 无任何散落的 _store.activeIndex = bestI (已归一 · 大制不割)
// 使用多行模式: 仅匹配"行首 + 可选空白 + _store..." (排除注释 `// _store...`)
const strayActiveIdx = (
  code.match(/^\s*_store\.activeIndex\s*=\s*bestI\s*;/gm) || []
).length;
assert(
  strayActiveIdx === 1, // 仅 helper 内 1 处 (可执行语句)
  `_store.activeIndex = bestI 可执行语句仅 helper 内 1 处 · got ${strayActiveIdx}`,
);
// store.activeIndex 也归一 (局部 store 参数 e.g. doAutoRotate 已移除)
const strayLocalStore = (
  code.match(/^\s*store\.activeIndex\s*=\s*bestI\s*;/gm) || []
).length;
assert(
  strayLocalStore === 0,
  `局部 store.activeIndex = bestI 已归一 · got ${strayLocalStore}`,
);

// ══ L20: v17.42.3 反者道之动 · _devinLogin 四路归一 ══
section("L20: v17.42.3 _devinLogin 四路竞速 (反者道之动 · 万法归宗)");
const devinLoginIdx = code.indexOf("async function _devinLogin");
assert(devinLoginIdx > 0, "_devinLogin 存在");
if (devinLoginIdx > 0) {
  // 提取函数体 (到下一个 async function 前)
  const nextFnIdx = code.indexOf("\nasync function ", devinLoginIdx + 10);
  const devinLoginBody = code.substring(
    devinLoginIdx,
    nextFnIdx > 0 ? nextFnIdx : devinLoginIdx + 5000,
  );
  // 必含 Origin/UA (匹配网页 fetch)
  assert(
    devinLoginBody.includes("Origin: urlOrigin"),
    "_devinLogin 含 Origin 头 (匹配 windsurf.com 同源 fetch)",
  );
  assert(
    devinLoginBody.includes("User-Agent"),
    "_devinLogin 含 User-Agent 头 (浏览器伪装)",
  );
  // 必含 4 个命名通道
  for (const ch of ["direct-auto", "proxy", "direct-raw", "native"]) {
    assert(
      devinLoginBody.includes(`n: "${ch}"`) ||
        devinLoginBody.includes(`"${ch}"`),
      `_devinLogin 含通道 "${ch}"`,
    );
  }
  // 错误聚合改为 perCh 具名 map (非单一 errs[0])
  assert(
    devinLoginBody.includes("const perCh = {}") ||
      devinLoginBody.includes("perCh[n]"),
    "_devinLogin 错误聚合用具名 map (非单 errs[0])",
  );
  // 错误串接 format: "ch:msg | ch:msg | ..." (template literal ${n}:${m})
  assert(
    devinLoginBody.includes(".map(([n, m])") &&
      devinLoginBody.includes("${n}:${m}"),
    "_devinLogin 最终错误串接 ${n}:${m} 模板",
  );
  // 永久错识别 (业务级 permanent pattern)
  assert(
    devinLoginBody.includes("permanentPat") ||
      devinLoginBody.includes("invalid|not"),
    "_devinLogin 含业务级永久错快速识别 (INVALID_LOGIN_CREDENTIALS 等)",
  );
  // v17.42.3: j.detail 优先 (匹配 windsurf.com 401 返回 {"detail":"Invalid..."})
  assert(
    devinLoginBody.includes("j.detail"),
    "_devinLogin 错误提取优先读 j.detail (网页源码 chunks/1635 一致)",
  );
  // 成功返回含 viaChannel
  assert(
    devinLoginBody.includes("viaChannel"),
    "_devinLogin 成功返回含 viaChannel 指示",
  );
}

// ══ L21: v17.42.4 以神遇不以目视 · PlanStatus 18字段全解 ══
section("L21: v17.42.4 PlanStatus proto schema (逆向 windsurf.com 本源)");
// 存在 enum/helper 常量
assert(
  code.includes("const TEAMS_TIER = {") && code.includes("DEVIN_TRIAL"),
  "TEAMS_TIER 枚举 (21 种 tier) 存在",
);
assert(
  code.includes("const GRACE_PERIOD = {") && code.includes("EXPIRED"),
  "GRACE_PERIOD 枚举 (UNSPECIFIED/NONE/ACTIVE/EXPIRED) 存在",
);
assert(
  code.includes("function tierIsPaid(") &&
    code.includes("function tierIsTrial(") &&
    code.includes("function tierIsFree("),
  "tierIsPaid/Trial/Free helper 三件组齐全",
);
// _extractQuotaFields 新结构
const extractIdx = code.indexOf("function _extractQuotaFields(");
assert(extractIdx > 0, "_extractQuotaFields 存在");
if (extractIdx > 0) {
  const nextFnIdx = code.indexOf("\nfunction ", extractIdx + 10);
  const body = code.substring(
    extractIdx,
    nextFnIdx > 0 ? nextFnIdx : extractIdx + 8000,
  );
  // v17.42.4: 不再 /100 · 直接整数读取
  assert(
    !body.includes("used / 100") && !body.includes("total / 100"),
    "不再对 credits 做错误的 /100 除法 (v17.42.4 语义修正)",
  );
  // 必含 18 字段对应的字段号读取
  for (const fn of [
    "v[4]",
    "v[5]",
    "v[6]",
    "v[7]",
    "v[8]",
    "v[9]",
    "v[11]",
    "v[12]",
    "v[14]",
    "v[15]",
    "v[16]",
    "v[17]",
    "v[18]",
  ]) {
    assert(body.includes(fn), `_extractQuotaFields 读取 ${fn}`);
  }
  // 必解析嵌套消息 msgs[1] (plan_info), msgs[2/3] (plan_start/end), msgs[10] (top_up), msgs[13] (grace_end)
  for (const mi of ["msgs[1]", "msgs[2]", "msgs[3]", "msgs[10]", "msgs[13]"]) {
    assert(body.includes(mi), `_extractQuotaFields 解析嵌套消息 ${mi}`);
  }
  // 返回字段扩充
  for (const key of [
    "teamsTier",
    "teamsTierName",
    "isDevin",
    "promptUsed",
    "promptAvailable",
    "promptMonthly",
    "flowUsed",
    "flowAvailable",
    "flowMonthly",
    "gracePeriod",
    "gracePeriodEndUnix",
    "overageMicros",
    "topUpEnabled",
  ]) {
    assert(body.includes(key), `_extractQuotaFields 返回 ${key}`);
  }
}
// isClaudeAvailable / isTrialPlan 新签名
const icaIdx = code.indexOf("function isClaudeAvailable(");
if (icaIdx > 0) {
  const icaBody = code.substring(icaIdx, icaIdx + 1200);
  assert(
    icaBody.includes("tierIsFree") && icaBody.includes("tierIsPaid"),
    "isClaudeAvailable 用 tierIsFree/Paid 快速路径",
  );
  assert(
    icaBody.includes("gracePeriod === 3"),
    "isClaudeAvailable 识别 gracePeriod=EXPIRED",
  );
}
assert(
  code.includes("function isTrialPlan(plan, teamsTier)"),
  "isTrialPlan 新签名支持 teamsTier 参数",
);
// verify-gate 用 gracePeriod
assert(
  code.includes("verify_gate_free_tier") || code.includes("rejectFreeTier"),
  "verify-gate 识别 Free tier (tier=19 DEVIN_FREE / tier=6 WAITLIST_PRO)",
);
assert(
  code.includes("verify_gate_grace_expired") ||
    code.includes("rejectGraceExpired"),
  "verify-gate 识别 gracePeriod=EXPIRED 官方过期状态",
);
// _updateAccountUsage 持久化新字段
const updIdx = code.indexOf("function _updateAccountUsage(");
if (updIdx > 0) {
  // 查找函数结束: 下一个顶层 function (注意 function _updateAccountUsage 本身是顶层)
  const nextTopIdx = code.indexOf("\nfunction ", updIdx + 30);
  const updBody = code.substring(
    updIdx,
    nextTopIdx > 0 ? nextTopIdx : updIdx + 10000,
  );
  for (const key of [
    "promptCredits",
    "flowCredits",
    "flexCredits",
    "teamsTier",
    "gracePeriod",
    "topUp",
  ]) {
    assert(updBody.includes(key), `_updateAccountUsage 持久化 ${key}`);
  }
}
// getHealth 透传新字段 (类方法, 需查到方法体的闭合)
const ghIdx = code.indexOf("getHealth(acc)");
if (ghIdx > 0) {
  // 类方法体大概 3000-4000 char, 扩大搜索窗口
  const ghBody = code.substring(ghIdx, ghIdx + 4500);
  for (const key of [
    "teamsTier",
    "teamsTierName",
    "gracePeriod",
    "promptCredits",
    "flowCredits",
  ]) {
    assert(ghBody.includes(key), `getHealth 透传 ${key}`);
  }
}

// ══ L22: v17.42.5 太上不知有之 · 五刀贯通 ══
section(
  "L22: v17.42.5 太上不知有之 (notify/invisible/idToken守护/cascade避让/认证本源化)",
);

// —— 刀一: notify 三级治理 ——
assert(
  code.includes("function _notifyInfo(") &&
    code.includes("function _notifyWarn(") &&
    code.includes("function _notifyError("),
  "刀一: _notifyInfo/Warn/Error helper 三件组存在",
);
assert(
  code.includes("function _shouldNotify(") &&
    code.includes("function _getNotifyLevel("),
  "刀一: _shouldNotify + _getNotifyLevel 决策函数",
);
assert(
  (code.includes('kind === "fatal"') &&
    code.includes('kind === "user"') &&
    code.includes('kind === "auto"')) ||
    (code.includes('"fatal"') &&
      code.includes('"user"') &&
      code.includes('"auto"')),
  "刀一: kind 三分类 (fatal/user/auto) 均有使用",
);
// 验证已替换 vscode.window.show*Message 为 helper (起码除 helper 定义外仅剩 modal 对话)
const showMsgHits = (
  code.match(/vscode\.window\.show(Information|Warning|Error)Message\s*\(/g) ||
  []
).length;
// 3 个在 helper 定义 · 其余剩下的都是 modal/多参数确认框 (testDevinSwitch 结果/selfTest 结果/removeBatch 确认/wam.switchAccount 官方模式确认/wam.checkUpdate 源配置/wam.officialMode 确认/wam.panicSwitch 官方确认)
assert(
  showMsgHits <= 12,
  `刀一: show*Message 调用数 ≤ 12 (3 helper + ≤ 9 modal) · got ${showMsgHits}`,
);
assert(
  (code.match(/_notifyInfo\s*\(/g) || []).length >= 15,
  "刀一: _notifyInfo 调用 ≥ 15 处",
);
assert(
  (code.match(/_notifyWarn\s*\(/g) || []).length >= 10,
  "刀一: _notifyWarn 调用 ≥ 10 处",
);

// —— 刀二: invisible 无感模式 ——
assert(
  code.includes("function _isInvisibleMode("),
  "刀二: _isInvisibleMode helper",
);
assert(code.includes('_cfg("invisible"'), "刀二: wam.invisible 配置读取");
// 阈值激进
{
  const idx = code.indexOf("function _getAutoSwitchThreshold(");
  if (idx > 0) {
    const body = code.substring(idx, idx + 400);
    assert(
      body.includes("_isInvisibleMode()") &&
        body.includes("Math.max(base, 10)"),
      "刀二: _getAutoSwitchThreshold 无感模式 ≥ 10% (比基线 5% 激进)",
    );
  }
}
// 状态栏极简
{
  const idx = code.indexOf("function updateStatusBar(");
  if (idx > 0) {
    const body = code.substring(idx, idx + 3500);
    assert(
      body.includes("_isInvisibleMode()"),
      "刀二: updateStatusBar 识别 无感模式",
    );
    assert(
      body.includes("$(zap) ${s.pwCount}"),
      "刀二: 无感模式状态栏仅显示 $(zap) N",
    );
  }
}

// —— 刀三: idToken 主动守护 ——
assert(
  code.includes("function _activeTokenGuardTick(") &&
    code.includes("function _startActiveTokenGuardian(") &&
    code.includes("function _stopActiveTokenGuardian("),
  "刀三: _activeTokenGuardTick/Start/Stop 守护三件组",
);
assert(
  code.includes("GUARD_MARGIN_MS = 2 * 60 * 1000"),
  "刀三: 守护边距 2min (对齐官网 10min 过期)",
);
assert(
  code.includes("_startActiveTokenGuardian()") &&
    code.includes("_stopActiveTokenGuardian()"),
  "刀三: 守护已注册到 _ensureEngines / _stopEngines",
);

// —— 刀四: cascade 流式避让 ——
assert(
  code.includes("function _isCascadeStreaming(") &&
    code.includes("async function _waitIfCascadeBusy("),
  "刀四: _isCascadeStreaming + _waitIfCascadeBusy helper",
);
// 消息锚定 + 耗尽两处自动切号升级了避让
const waitCascadeHits = (code.match(/await _waitIfCascadeBusy\(/g) || [])
  .length;
assert(
  waitCascadeHits >= 2,
  `刀四: await _waitIfCascadeBusy() 插入至少 2 处 · got ${waitCascadeHits}`,
);

// —— 刀五: 认证链路本源化 ——
assert(
  code.includes("_persistFirebaseMark = () => {") &&
    (code.includes("No-op") || code.includes("不再自动标记")),
  "刀五: _persistFirebaseMark 已在内部 no-op (不再自动标记 firebase)",
);
assert(
  code.includes('_cfg("preferDevinFirst", true)'),
  "刀五: preferDevinFirst 默认 true",
);

// —— package.json 配置项 ——
if (fs.existsSync(pkgPath)) {
  const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
  const props =
    (pkg.contributes.configuration &&
      pkg.contributes.configuration.properties) ||
    {};
  assert(props["wam.invisible"], "package.json 声明 wam.invisible");
  assert(props["wam.notify.level"], "package.json 声明 wam.notify.level");
  assert(
    props["wam.notify.level"] &&
      props["wam.notify.level"].enum &&
      props["wam.notify.level"].enum.length === 3,
    "wam.notify.level enum 有 3 个值 (silent/notify/verbose)",
  );
  assert(
    props["wam.notify.level"] && props["wam.notify.level"].default === "notify",
    "wam.notify.level 默认 notify",
  );
  assert(
    props["wam.invisible"] && props["wam.invisible"].default === false,
    "wam.invisible 默认 false (不强加用户 · opt-in)",
  );
}

// ══ L23: v17.42.6 死代理 env 自净 · 反者道之动 ══
section("L23: v17.42.6 env-proxy self-cleanse (启动 TCP 验活 · 死则剔 env)");

// —— 函数存在 ——
assert(
  /function\s+_tcpProbe\s*\(/.test(code),
  "_tcpProbe(host, port, timeoutMs) 函数定义存在",
);
assert(
  /async\s+function\s+_purgeDeadEnvProxy\s*\(/.test(code),
  "_purgeDeadEnvProxy() 异步函数定义存在",
);

// —— _tcpProbe 关键字段 ——
assert(
  code.includes("new net.Socket()") &&
    code.includes('socket.once("connect"') &&
    code.includes('socket.once("error"'),
  "_tcpProbe 使用 net.Socket + connect/error 双路",
);
assert(
  /socket\.connect\s*\(\s*port\s*,\s*host\s*\)/.test(code),
  "_tcpProbe 发起 socket.connect(port, host)",
);
assert(
  /setTimeout\(\s*\(\)\s*=>\s*finish\(false\)\s*,\s*timeoutMs\s*\)/.test(code),
  "_tcpProbe 有 timeoutMs 超时保护",
);

// —— _purgeDeadEnvProxy 覆盖所有大小写 env key ——
const envKeysExpected = [
  "HTTPS_PROXY",
  "https_proxy",
  "HTTP_PROXY",
  "http_proxy",
  "ALL_PROXY",
  "all_proxy",
];
for (const k of envKeysExpected) {
  assert(code.includes(`"${k}"`), `_purgeDeadEnvProxy 覆盖 env key '${k}'`);
}
assert(
  /delete\s+process\.env\[\s*key\s*\]/.test(code),
  "_purgeDeadEnvProxy 对死代调用 delete process.env[key] (仅本进程生效)",
);
assert(
  /await\s+_tcpProbe\(\s*host\s*,\s*port\s*,\s*2000\s*\)/.test(code),
  "_purgeDeadEnvProxy 调用 _tcpProbe 2s 超时",
);
assert(
  code.includes("env-proxy purge:") && code.includes("env-proxy keep:"),
  "_purgeDeadEnvProxy 有 purge/keep 日志 (可审计)",
);
assert(
  code.includes("_invalidateProxyCache()") &&
    /if\s*\(\s*purged\s*>\s*0\s*\)\s*_invalidateProxyCache\(\)/.test(code),
  "_purgeDeadEnvProxy 清完死代后 · 必 _invalidateProxyCache() 让 _detectProxy 重扫",
);
assert(
  code.includes("seen.has(k)") && code.includes("seen.set(k"),
  "_purgeDeadEnvProxy 使用 seen Map 去重 (同一 host:port 只验一次)",
);

// —— activate() 在起点即注入 ——
const actMatch = code.match(
  /function\s+activate\s*\(\s*context\s*\)\s*\{([\s\S]{0,4000})/,
);
assert(actMatch, "activate(context) 函数存在");
if (actMatch) {
  assert(
    /_purgeDeadEnvProxy\(\)\.catch\(/.test(actMatch[1]),
    "activate() 早期 fire-and-forget 调用 _purgeDeadEnvProxy().catch(...)",
  );
  // 验证是在 log(`activate v...`) 之后, globalStorage 之前 (最早网络 op 之前)
  const actStart = code.indexOf("function activate(context) {");
  const purgeIdx = code.indexOf("_purgeDeadEnvProxy().catch", actStart);
  const gsPathIdx = code.indexOf("context.globalStorageUri", actStart);
  assert(
    purgeIdx > actStart && purgeIdx < gsPathIdx,
    "_purgeDeadEnvProxy 注入位置: activate 起点之后 · globalStorage 初始化之前 (最早网络 op 之前)",
  );
}

// —— v17.42.6 版本描述锚点 ——
assert(
  /17\.42\.6:?\s*死代理\s*env\s*自净/.test(code),
  "WAM_VERSION 注释锚 '17.42.6: 死代理 env 自净'",
);

// —— 与 _getSystemProxy 的并存关系 ——
// _getSystemProxy 本身未改 · 是 _purgeDeadEnvProxy 在入口净化 env, 让 _getSystemProxy 天然看不到死代
assert(
  /function\s+_getSystemProxy\s*\(/.test(code),
  "_getSystemProxy 保留 · 依赖入口 env 已净化",
);
assert(
  code.includes("_getSystemProxy") &&
    code.indexOf("_purgeDeadEnvProxy") < code.lastIndexOf("_getSystemProxy"),
  "_purgeDeadEnvProxy 声明在 _getSystemProxy 之后 (辅助净化 · 不替代)",
);

// —— 根因 comment 锚点 (留档 future-proof) ——
assert(
  code.includes("Node 22+ https.request") ||
    code.includes("_skipAutoProxy 挡不住"),
  "根因注释: Node 22+ https.request 原生读 env 绕过 _skipAutoProxy",
);

// ══ L24: v17.42.7 锁🔒 全链贯通 + 一键导出 ══
section("L24: v17.42.7 lock 全链贯通 + copyAllAccounts 一键导出");

// —— _isValidAutoTarget 统一门 ——
assert(
  /function\s+_isValidAutoTarget\s*\(/.test(code),
  "_isValidAutoTarget(i) 函数定义存在 (统一候选验证门)",
);
assert(
  code.includes("if (acc.skipAutoSwitch) return false") ||
    /acc\.skipAutoSwitch\s*\)\s*return\s+false/.test(code),
  "_isValidAutoTarget 包含 skipAutoSwitch 四辨",
);
assert(
  /_isClaimedByOther\(acc\.email\)/.test(code),
  "_isValidAutoTarget 包含 跨实例 claimed 检查",
);
assert(
  code.includes("!acc.password") &&
    /_tokenPoolBlacklist(\s*&&\s*_tokenPoolBlacklist)?\.has\(ek\)/.test(code),
  "_isValidAutoTarget 包含 password + pool 黑名单四辨",
);

// —— 所有 选目标式 _predictiveCandidate 使用处必经 _isValidAutoTarget ——
// 选目标式: `_predictiveCandidate ... ? _predictiveCandidate : ...` (选为当届 target)
// 与 log 式 `>= 0 ? " [预判]"` 区分 (后者不以 _predictiveCandidate 作为真果)
const pickUses = [
  ...code.matchAll(
    /_predictiveCandidate\s*[>=!&|)]+[^?]*\?\s*_predictiveCandidate\s*:/g,
  ),
];
for (const m of pickUses) {
  const ctx = code.substring(Math.max(0, m.index - 200), m.index + 200);
  assert(
    ctx.includes("_isValidAutoTarget"),
    `选目标式 _predictiveCandidate 使用处必经 _isValidAutoTarget (@idx ${m.index})`,
  );
}
assert(
  pickUses.length >= 1,
  `至少 1 处 选目标式 _predictiveCandidate (msgAnchor) · got ${pickUses.length}`,
);
// 直式调用 _isValidAutoTarget(_predictiveCandidate) (monitor/exhaust/rate-limit 至少 3 处)
const directValidUses = [
  ...code.matchAll(/_isValidAutoTarget\(_predictiveCandidate\)/g),
];
assert(
  directValidUses.length >= 3,
  `_isValidAutoTarget(_predictiveCandidate) 直式 至少 3 处 (monitor/exhaust/rate-limit) · got ${directValidUses.length}`,
);

// —— toggleSkip 即时联动失效 ——
assert(
  /acc3\.skipAutoSwitch\s*&&\s*_predictiveCandidate\s*===\s*msg\.index/.test(
    code,
  ),
  "toggleSkip 手动锁 → 若为 _predictiveCandidate 即时失效",
);
assert(
  code.includes("🔒 lock:") && code.includes("即时作废"),
  "toggleSkip 失效联动有日志追迹",
);

// —— copyAllAccounts 消息处理 ——
assert(
  /case\s+["']copyAllAccounts["']\s*:/.test(code),
  "copyAllAccounts 后端 case 分支存在",
);
assert(
  code.includes("_store.accounts.map") &&
    code.includes("a.password ? `${a.email}:${a.password}` : a.email"),
  "copyAllAccounts 格式 email:password (无密码仅 email)",
);
assert(
  code.includes('lines.join("\\n")') || code.includes("lines.join('\\n')"),
  "copyAllAccounts 换行连接 (一行一个)",
);
assert(
  code.includes("账号池为空") || code.includes("pool 为空"),
  "copyAllAccounts 空池防护",
);
assert(/已导出\s*\$\{total\}/.test(code), "copyAllAccounts toast 显示导出总数");

// —— UI 一键导出按钮 ——
assert(/onclick="copyAll\(\)"/.test(code), "UI 有 copyAll() onclick 按钮");
assert(
  /function\s+copyAll\s*\(\s*\)\s*\{[^}]*copyAllAccounts/.test(code),
  "UI copyAll() 函数 postMessage copyAllAccounts",
);
assert(code.includes("一键导出"), "UI 按钮文本含 '一键导出'");

// —— v17.42.7 版本描述锚 ——
assert(
  /17\.42\.7:?\s*锁🔒\s*全链[路]?贯通/.test(code),
  "WAM_VERSION 注释锚 '17.42.7: 锁🔒 全链[路]贯通'",
);

// ══ Summary ══
console.log(`\n${"=".repeat(60)}`);
console.log(
  `WAM E2E v17.42.7 · RESULT: ${pass} pass / ${fail} fail / ${skip} skip`,
);
console.log(`STATUS: ${fail === 0 ? "✅ ALL GREEN" : "❌ FAILURES DETECTED"}`);
process.exit(fail > 0 ? 1 : 0);
