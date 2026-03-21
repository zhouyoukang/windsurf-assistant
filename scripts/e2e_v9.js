/**
 * E2E验证 Windsurf小助手 v1.0.0 — 全感知号池引擎+多窗口协调
 * 测试: 语法 + 结构 + 安全审计 + 核心功能 + 号池引擎特性
 */
const fs = require('fs');
const path = require('path');

// V:网络驱动器映射修复: __dirname可能解析为D:(远程机器盘符)导致ENOENT
// 降级策略: __dirname → process.cwd() → 硬编码路径
let BASE = require('path').resolve(__dirname, '..');
if (!fs.existsSync(path.join(BASE, 'src'))) {
  BASE = process.cwd();
  if (!fs.existsSync(path.join(BASE, 'src'))) {
    console.error('ERROR: 无法定位项目目录。请在无感切号/目录下运行此脚本。');
    process.exit(1);
  }
}
const SRC = path.join(BASE, 'src');
let pass = 0, fail = 0, total = 0;

function test(name, fn) {
  total++;
  try {
    const result = fn();
    if (result === true || result === undefined) { pass++; console.log(`  ✅ ${name}`); }
    else { fail++; console.log(`  ❌ ${name}: ${result}`); }
  } catch (e) { fail++; console.log(`  ❌ ${name}: ${e.message}`); }
}

// ═══ T1. 语法检查 (5文件) ═══
console.log('\n📋 T1. 语法检查');
const EXPECTED_FILES = ['extension.js', 'authService.js', 'accountManager.js', 'webviewProvider.js', 'fingerprintManager.js'];
EXPECTED_FILES.forEach(f => {
  test(`${f} 语法正确`, () => {
    const code = fs.readFileSync(path.join(SRC, f), 'utf8');
    new Function(code.replace(/require\(/g, '(() => ({})) || r('));
    return true;
  });
});

test('src/目录恰好5个js文件', () => {
  const files = fs.readdirSync(SRC).filter(f => f.endsWith('.js'));
  return files.length === 5 ? true : `${files.length}个: ${files.join(',')}`;
});

// ═══ T2. 已删文件不存在 ═══
console.log('\n📋 T2. 已删文件不存在');
['configManager.js', 'securityBridge.js', 'poolSync.js', 'wisdomManager.js', 'wisdomTemplates.js'].forEach(f => {
  test(`${f} 已删除`, () => !fs.existsSync(path.join(SRC, f)) ? true : '文件仍然存在!');
});

// ═══ T3. package.json ═══
console.log('\n📋 T3. package.json');
const pkg = JSON.parse(fs.readFileSync(path.join(BASE, 'package.json'), 'utf8'));
test('name=windsurf-assistant', () => pkg.name === 'windsurf-assistant' ? true : pkg.name);
test('version=1.0.0', () => pkg.version === '1.0.0' ? true : pkg.version);
test('命令数=12', () => {
  const cmds = pkg.contributes.commands.length;
  return cmds === 12 ? true : `${cmds}个命令`;
});
test('viewId=windsurf-assistant.assistantView', () => {
  const views = pkg.contributes.views?.['windsurf-assistant'];
  return views?.[0]?.id === 'windsurf-assistant.assistantView' ? true : views?.[0]?.id;
});
test('12个命令正确', () => {
  const expected = ['switchAccount', 'refreshCredits', 'openPanel', 'switchMode', 'reprobeProxy',
    'resetFingerprint', 'panicSwitch', 'batchAdd', 'refreshAllCredits', 'smartRotate', 'importAccounts', 'initWorkspace'];
  const actual = pkg.contributes.commands.map(c => c.command.replace('wam.', ''));
  const missing = expected.filter(e => !actual.includes(e));
  return missing.length === 0 ? true : `缺少: ${missing.join(',')}`;
});
test('无已删命令', () => {
  const deleted = ['configStatus', 'deployConfig', 'backupConfig', 'rollbackConfig',
    'securityStatus', 'mcpSync', 'mcpFix', 'syncPool', 'poolServer',
    'injectConfig', 'scanConfig', 'wisdomInspect', 'wisdomInject', 'wisdomRollback'];
  const actual = pkg.contributes.commands.map(c => c.command.replace('wam.', ''));
  const found = deleted.filter(d => actual.includes(d));
  return found.length === 0 ? true : `残留: ${found.join(',')}`;
});
test('配置项=2', () => {
  const props = Object.keys(pkg.contributes.configuration?.properties || {});
  return props.length === 2 ? true : `${props.length}个: ${props.join(',')}`;
});

// ═══ T4. 核心安全审计 (核心矛盾: 不能自动注入auth打断Cascade) ═══
console.log('\n📋 T4. 核心安全审计');
const extCode = fs.readFileSync(path.join(SRC, 'extension.js'), 'utf8');

test('v1.0.0版本标识', () => extCode.includes('v1.0.0') ? true : '缺少v1.0.0标识');
test('_doImport函数(extension)', () => {
  return extCode.includes('async function _doImport') ? true : '缺少_doImport';
});
test('_checkAccount函数(安全)', () => extCode.includes('async function _checkAccount'));
test('injectAuth函数(破坏性)', () => extCode.includes('async function injectAuth'));
test('_loginToAccount包含_checkAccount和injectAuth(v5.2.0+设计)', () => {
  const match = extCode.match(/async function _loginToAccount[\s\S]*?^}/m);
  if (!match) return '_loginToAccount not found';
  const body = match[0];
  if (!body.includes('_checkAccount')) return '_loginToAccount未调用_checkAccount';
  if (!body.includes('injectAuth')) return '_loginToAccount未调用injectAuth';
  return true;
});
test('_seamlessSwitch存在且委托_loginToAccount', () => {
  const match = extCode.match(/async function _seamlessSwitch[\s\S]*?^}/m);
  if (!match) return '_seamlessSwitch not found';
  return match[0].includes('_loginToAccount') ? true : '未委托_loginToAccount';
});
test('injectAuth仅在受控路径调用', () => {
  const lines = extCode.split('\n');
  const callLines = lines.filter(l =>
    l.includes('injectAuth(') && !l.includes('async function injectAuth') && !l.trim().startsWith('*') && !l.trim().startsWith('//'));
  const ok = callLines.every(l => l.includes('await injectAuth'));
  return ok ? true : `意外的injectAuth调用: ${callLines.map(l => l.trim()).join(' | ')}`;
});
test('号池引擎无直接auth注入', () => {
  const dangerous = ['_poolTick', '_startQuotaWatcher', '_doPoolRotate', '_doRefreshPool'];
  for (const fn of dangerous) {
    const match = extCode.match(new RegExp(`(async )?function ${fn}[\\s\\S]*?^}`, 'm'));
    if (match && match[0].includes('provideAuthToken')) return `${fn}包含provideAuthToken!`;
  }
  return true;
});

// ═══ T5. 残留引用检查 ═══
console.log('\n📋 T5. 残留引用检查');
const allSrc = EXPECTED_FILES.map(f => fs.readFileSync(path.join(SRC, f), 'utf8')).join('\n');
['configManager', 'securityBridge', 'poolSync', 'wisdomManager', 'wisdomTemplates'].forEach(mod => {
  test(`无${mod}引用`, () => {
    const refs = (allSrc.match(new RegExp(mod, 'gi')) || []).length;
    return refs === 0 ? true : `${refs}处引用`;
  });
});
test('无cfgMgr引用', () => !allSrc.includes('cfgMgr') ? true : '残留cfgMgr');
test('无secBridge引用', () => !allSrc.includes('secBridge') ? true : '残留secBridge');
test('无configStatusBar引用', () => !allSrc.includes('configStatusBar') ? true : '残留configStatusBar');
test('无securityStatusBar引用', () => !allSrc.includes('securityStatusBar') ? true : '残留securityStatusBar');

// ═══ T6. 核心功能存在 ═══
console.log('\n📋 T6. 核心功能检查');
test('_refreshOne helper', () => extCode.includes('async function _refreshOne'));
test('_refreshAll helper', () => extCode.includes('async function _refreshAll'));
test('checkAccount/injectAuth分离', () =>
  extCode.includes('SAFE') && extCode.includes('DISRUPTIVE') ? true : '缺少SAFE/DISRUPTIVE标记');
test('SWE-1.5降级建议', () => extCode.includes('SWE-1.5') ? true : '缺少SWE-1.5');
test('全感知限流检测', () => extCode.includes('_startQuotaWatcher') ? true : '缺少全感知限流检测');
test('号池引擎', () => extCode.includes('_startPoolEngine') ? true : '缺少号池引擎');

// ═══ T7. View ID一致性 ═══
console.log('\n📋 T7. View ID一致性');
test('extension.js注册windsurf-assistant.assistantView', () =>
  extCode.includes('windsurf-assistant.assistantView') ? true : '缺少windsurf-assistant.assistantView');
test('package.json viewId一致', () => {
  const extId = extCode.includes('windsurf-assistant.assistantView');
  const pkgId = pkg.contributes.views?.['windsurf-assistant']?.[0]?.id === 'windsurf-assistant.assistantView';
  return extId && pkgId ? true : `ext=${extId}, pkg=${pkgId}`;
});

// ═══ T8. VSIX文件 ═══
console.log('\n📋 T8. VSIX文件');
// Check for any recent VSIX
const vsixFiles = fs.readdirSync(BASE).filter(f => f.endsWith('.vsix'));
test('VSIX文件存在', () => vsixFiles.length > 0 ? true : '无VSIX文件');
test('VSIX大小合理(30-2000KB)', () => {
  if (vsixFiles.length === 0) return '无VSIX';
  const latest = vsixFiles.sort().pop();
  const size = fs.statSync(path.join(BASE, latest)).size;
  return size > 30000 && size < 2000000 ? true : `${latest}: ${(size/1024).toFixed(1)}KB`;
});

// ═══ T9. 源文件完整性 ═══
console.log('\n📋 T9. 源文件完整性');
test('必需文件存在', () => {
  const required = ['src/extension.js', 'src/authService.js', 'src/accountManager.js', 'src/webviewProvider.js', 'src/fingerprintManager.js', 'media/icon.svg', 'media/panel.js', 'package.json', 'LICENSE'];
  const missing = required.filter(f => !fs.existsSync(path.join(BASE, f)));
  return missing.length === 0 ? true : `缺少: ${missing.join(',')}`;
});
test('wisdom_bundle.json存在', () => fs.existsSync(path.join(SRC, 'wisdom_bundle.json')) ? true : '模板包不存在');

// ═══ T10. v6.2 全感知检测验证 ═══
console.log('\n📋 T10. v6.2全感知检测');
const wpCode = fs.readFileSync(path.join(SRC, 'webviewProvider.js'), 'utf8');
const amCode = fs.readFileSync(path.join(SRC, 'accountManager.js'), 'utf8');
test('_startQuotaWatcher存在', () => extCode.includes('function _startQuotaWatcher'));
test('8+context key检测', () => extCode.includes('chatQuotaExceeded') && extCode.includes('windsurf.messageRateLimited'));
test('cachedPlanInfo监控', () => extCode.includes('checkCachedQuota') && extCode.includes('cachedPlanInfo'));
test('RATE_LIMIT_PATTERNS文本模式', () => extCode.includes('RATE_LIMIT_PATTERNS'));
test('结构化日志(_logInfo/_logWarn/_logError)', () =>
  extCode.includes('function _logInfo') && extCode.includes('function _logWarn') && extCode.includes('function _logError'));
test('OutputChannel可见', () => extCode.includes('createOutputChannel') && extCode.includes('WAM 号池引擎'));
test('markRateLimited含model字段', () => amCode.includes('model: info.model'));

// ═══ T11. 号池引擎核心机制 ═══
console.log('\n📋 T11. 号池引擎核心');
test('_poolTick存在', () => extCode.includes('async function _poolTick'));
test('_seamlessSwitch存在', () => extCode.includes('async function _seamlessSwitch'));
test('_doPoolRotate存在', () => extCode.includes('async function _doPoolRotate'));
test('_isBoost加速模式', () => extCode.includes('_isBoost') && extCode.includes('_activateBoost'));
test('PREEMPTIVE_THRESHOLD预防线', () => extCode.includes('PREEMPTIVE_THRESHOLD'));
test('_slopePredict斜率预测', () => extCode.includes('_slopePredict'));
test('_switching锁防重复', () => extCode.includes('let _switching = false'));
test('round-robin回退', () => extCode.includes('Round-robin') || extCode.includes('round-robin'));
test('deactivate清理_poolTimer', () => extCode.includes('clearTimeout(_poolTimer)'));
test('shouldSwitch判断引擎', () => amCode.includes('shouldSwitch'));
test('selectOptimal最优选号', () => amCode.includes('selectOptimal'));
test('effectiveRemaining统一指标', () => {
  return amCode.includes('effectiveRemaining') ? true : '缺少effectiveRemaining';
});
test('号池聚合统计(getPoolStats)', () => {
  return amCode.includes('getPoolStats') ? true : '缺少getPoolStats';
});

// ═══ T12. 认证链+注入策略 ═══
console.log('\n📋 T12. 认证链+注入策略');
const authCode = fs.readFileSync(path.join(SRC, 'authService.js'), 'utf8');
test('S0=idToken直传注入(PRIMARY策略)', () => {
  return extCode.includes('S0-provideAuth-idToken') && extCode.includes('getFreshIdToken') ? true : '缺少idToken直传策略';
});
test('S1=OneTimeAuthToken降级(FALLBACK策略)', () => {
  return extCode.includes('S1-provideAuth-otat') ? true : '缺少OTAT降级策略';
});
test('S2=registerUser apiKey(LAST RESORT策略)', () => {
  return extCode.includes('S2-') && extCode.includes('apiKey') ? true : '缺少apiKey最后策略';
});
test('S3=DB直写注入', () => {
  return extCode.includes('S3-db-inject') ? true : '缺少DB直写策略';
});
test('_postInjectionRefresh存在', () => extCode.includes('async function _postInjectionRefresh'));
test('_clearCachedPlanInfo存在', () => extCode.includes('function _clearCachedPlanInfo'));
test('_readAuthApiKeyPrefix存在', () => extCode.includes('function _readAuthApiKeyPrefix'));
test('_rotateFingerprintForSwitch存在', () => extCode.includes('function _rotateFingerprintForSwitch'));
test('getFreshIdToken(authService)', () => authCode.includes('getFreshIdToken'));
test('readCachedQuota(authService)', () => authCode.includes('readCachedQuota'));
test('智能代理探测(_detectSystemProxy)', () => authCode.includes('_detectSystemProxy'));
test('web-backend.windsurf.com端点', () => authCode.includes('web-backend.windsurf.com'));
test('setMode存在(代理模式切换)', () => {
  return extCode.includes("case 'setMode'") || wpCode.includes('setMode') ? true : '缺少setMode';
});
test('setProxyPort存在(端口设置)', () => {
  return extCode.includes("case 'setProxyPort'") || wpCode.includes('setProxyPort') ? true : '缺少setProxyPort';
});
test('代理探测(后台启动)', () => {
  return extCode.includes('reprobeProxy') ? true : '缺少代理探测';
});
test('指纹重置非破坏性(无reloadWindow)', () => {
  const match = extCode.match(/async function _doResetFingerprint[\s\S]*?^}/m);
  if (!match) return '_doResetFingerprint not found';
  return !match[0].includes('reloadWindow') ? true : '_doResetFingerprint仍含reloadWindow!';
});
test('_switching锁替代手动锁', () => {
  return extCode.includes('let _switching = false') ? true : '缺少_switching锁';
});
test('号池引擎自适应轮询(非固定间隔)', () => {
  return extCode.includes('POLL_NORMAL') && extCode.includes('POLL_BOOST') ? true : '缺少自适应轮询';
});

// ═══ T13. 内嵌智慧注入系统 ═══
console.log('\n📋 T13. 内嵌智慧注入系统');
test('wisdom_bundle可解析', () => {
  try {
    const bundle = JSON.parse(fs.readFileSync(path.join(SRC, 'wisdom_bundle.json'), 'utf8'));
    return bundle.templates && Object.keys(bundle.templates).length > 0 ? true : '模板为空';
  } catch (e) { return 'JSON解析失败: ' + e.message; }
});
test('_doEmbeddedWisdom存在', () => extCode.includes('_doEmbeddedWisdom'));
test('_loadWisdomBundle存在', () => extCode.includes('_loadWisdomBundle'));
test('服务器不可用降级', () => extCode.includes('切换到内置模板模式') || extCode.includes('_doEmbeddedWisdom'));
test('智慧部署器降级提示', () => {
  return extCode.includes('切换到内置模板模式') || extCode.includes('_doEmbeddedWisdom(context, targ') ? true : '缺少降级提示';
});

// ═══ T14. WebView + XSS防护 ═══
console.log('\n📋 T14. WebView+XSS防护');
const panelJsPath = path.join(BASE, 'media', 'panel.js');
const panelCode = fs.existsSync(panelJsPath) ? fs.readFileSync(panelJsPath, 'utf8') : '';
test('webview无prompt()', () => !wpCode.includes('prompt(') ? true : '仍含prompt()');
test('XSS服务端_e转义', () => wpCode.includes("const _e = s => String(s).replace") ? true : '缺少服务端转义');
test('XSS客户端_esc(panel.js)', () => panelCode.includes('function _esc(') ? true : '缺少客户端转义');
test('密码不内嵌HTML', () => !wpCode.includes('const _PWD=') ? true : '密码嵌入HTML');
test('copyPwd功能(server+client)', () => wpCode.includes('copyPwd') && panelCode.includes('navigator.clipboard'));
test('exportAccounts按钮', () => wpCode.includes('exportAccounts'));
test('importAccounts按钮', () => wpCode.includes('importAccounts'));
test('creditHistory趋势(accountManager)', () => amCode.includes('creditHistory') && amCode.includes('_pushCreditHistory'));
test('CSP安全(panel.js外部脚本)', () => {
  return fs.existsSync(path.join(BASE, 'media', 'panel.js')) && wpCode.includes('cspSource') ? true : '缺少CSP安全';
});
test('CSP安全(外部脚本)', () => {
  return wpCode.includes('cspSource') || wpCode.includes('panel.js') ? true : '缺少CSP外部脚本';
});
test('无内联script(安全)', () => {
  return !wpCode.includes('<script>') || wpCode.includes('panel.js') ? true : '存在内联script';
});

// ═══ T15. 账号管理器核心功能 ═══
console.log('\n📋 T15. 账号管理器');
test('addBatch智能解析', () => amCode.includes('addBatch') && amCode.includes('parseAccounts'));
test('merge合并策略', () => amCode.includes('merge(externalAccounts)'));
test('markRateLimited', () => amCode.includes('markRateLimited'));
test('isRateLimited', () => amCode.includes('isRateLimited'));
test('clearRateLimit', () => amCode.includes('clearRateLimit'));
test('findBestAvailable', () => amCode.includes('findBestAvailable'));
test('allDepleted无indexOf(O(n))', () => {
  const match = amCode.match(/allDepleted[\s\S]*?^  }/m);
  if (!match) return 'allDepleted not found';
  return !match[0].includes('indexOf');
});
test('maxPremiumMessages存储', () => amCode.includes('maxPremiumMessages'));
test('fs.watch多窗口同步', () => amCode.includes('fs.watch') && amCode.includes('startWatching'));

// ═══ 总结 ═══
console.log(`\n${'═'.repeat(50)}`);
console.log(`  总计: ${total}  通过: ${pass}  失败: ${fail}`);
console.log(`  通过率: ${Math.round(pass/total*100)}%`);
console.log(`${'═'.repeat(50)}`);
process.exit(fail > 0 ? 1 : 0);
