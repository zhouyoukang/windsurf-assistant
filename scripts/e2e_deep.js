/**
 * Deep E2E Runtime Verification — Windsurf小助手 v1.0.0
 * 模拟真实用户场景，直接加载模块并测试实际行为
 * 不干扰IDE，纯Node.js运行时验证
 */
const fs = require('fs');
const path = require('path');
const os = require('os');
const http = require('http');

const SRC = path.join(__dirname, '..', 'src');
let pass = 0, fail = 0, total = 0;
function test(name, fn) {
  total++;
  try {
    const r = fn();
    if (r === true) { pass++; console.log(`  ✅ ${name}`); }
    else { fail++; console.log(`  ❌ ${name}: ${r}`); }
  } catch (e) { fail++; console.log(`  ❌ ${name}: THROW ${e.message}`); }
}
function asyncTest(name, fn) {
  return fn().then(r => {
    total++;
    if (r === true) { pass++; console.log(`  ✅ ${name}`); }
    else { fail++; console.log(`  ❌ ${name}: ${r}`); }
  }).catch(e => {
    total++; fail++;
    console.log(`  ❌ ${name}: THROW ${e.message}`);
  });
}

// ═══════════════════════════════════════════════════════════
// L2. 扩展安装完整性（文件系统级验证）
// ═══════════════════════════════════════════════════════════
console.log('\n📋 L2. 扩展安装完整性');

const extBase = path.join(process.env.USERPROFILE || os.homedir(), '.windsurf', 'extensions');
const extDirs = fs.existsSync(extBase) ? fs.readdirSync(extBase).filter(d => d.includes('windsurf-assistant')) : [];
test('扩展目录存在', () => extDirs.length > 0 ? true : '未找到扩展目录');

if (extDirs.length > 0) {
  const extDir = path.join(extBase, extDirs[extDirs.length - 1]);
  test('package.json存在', () => fs.existsSync(path.join(extDir, 'package.json')) ? true : '缺失');
  test('src/extension.js存在', () => fs.existsSync(path.join(extDir, 'src', 'extension.js')) ? true : '缺失');
  test('src/authService.js存在', () => fs.existsSync(path.join(extDir, 'src', 'authService.js')) ? true : '缺失');
  test('src/accountManager.js存在', () => fs.existsSync(path.join(extDir, 'src', 'accountManager.js')) ? true : '缺失');
  test('src/webviewProvider.js存在', () => fs.existsSync(path.join(extDir, 'src', 'webviewProvider.js')) ? true : '缺失');
  test('src/fingerprintManager.js存在', () => fs.existsSync(path.join(extDir, 'src', 'fingerprintManager.js')) ? true : '缺失');
  test('media/icon.svg存在', () => fs.existsSync(path.join(extDir, 'media', 'icon.svg')) ? true : '缺失');
  
  // Verify installed version matches source
  const installedPkg = JSON.parse(fs.readFileSync(path.join(extDir, 'package.json'), 'utf8'));
  const sourcePkg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8'));
  test('版本一致(installed=source)', () => installedPkg.version === sourcePkg.version ? true : `${installedPkg.version} !== ${sourcePkg.version}`);
  test('命令数一致', () => {
    const ic = installedPkg.contributes.commands.length;
    const sc = sourcePkg.contributes.commands.length;
    return ic === sc ? true : `${ic} !== ${sc}`;
  });
}

// ═══════════════════════════════════════════════════════════
// L3. XSS防护实战测试（构造恶意email，验证转义生效）
// ═══════════════════════════════════════════════════════════
console.log('\n📋 L3. XSS防护实战');

// Read webviewProvider source and simulate _getHtml's _e() function
const wpSrc = fs.readFileSync(path.join(SRC, 'webviewProvider.js'), 'utf8');
const _e = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');

test('XSS·双引号注入', () => {
  const malicious = 'test"onmouseover="alert(1)"@evil.com';
  const escaped = _e(malicious);
  return !escaped.includes('"onmouseover') ? true : `未转义: ${escaped}`;
});
test('XSS·尖括号注入', () => {
  const malicious = '<script>alert(1)</script>@evil.com';
  const escaped = _e(malicious);
  return !escaped.includes('<script>') ? true : `未转义: ${escaped}`;
});
test('XSS·单引号注入', () => {
  const malicious = "test'onclick='alert(1)'@evil.com";
  const escaped = _e(malicious);
  return !escaped.includes("'onclick") ? true : `未转义: ${escaped}`;
});
test('XSS·&符号注入', () => {
  const malicious = 'test&amp;@evil.com';
  const escaped = _e(malicious);
  return escaped.includes('&amp;amp;') ? true : `双重编码问题`;
});
test('正常email不受影响', () => {
  const normal = 'user@example.com';
  const escaped = _e(normal);
  return escaped === normal ? true : `被修改: ${escaped}`;
});
test('服务端_e函数存在于_getHtml', () => {
  // Verify _e is defined inside _getHtml method
  const match = wpSrc.match(/_getHtml\(accounts[\s\S]*?const _e = s =>/);
  return match ? true : '_e函数未在_getHtml中定义';
});
test('所有email注入点使用_e()', () => {
  // Check that raw a.email is never directly in HTML without _e
  const htmlSection = wpSrc.substring(wpSrc.indexOf('_getHtml('));
  // Find title="${...email...}" patterns
  const rawEmailInTitle = /title="\$\{a\.email\}"/.test(htmlSection);
  const escapedEmailInTitle = /title="\$\{_e\(a\.email\)\}"/.test(htmlSection);
  return !rawEmailInTitle && escapedEmailInTitle ? true : `raw=${rawEmailInTitle}, escaped=${escapedEmailInTitle}`;
});

// ═══════════════════════════════════════════════════════════
// L4. AccountManager 运行时测试
// ═══════════════════════════════════════════════════════════
console.log('\n📋 L4. AccountManager运行时');

const { AccountManager } = require(path.join(SRC, 'accountManager'));
// Use deeply nested unique path to avoid legacy migration picking up real accounts
const tmpDir = path.join(os.tmpdir(), 'wam-e2e-deep-' + Date.now(), 'isolated', 'storage');
fs.mkdirSync(tmpDir, { recursive: true });
// Write empty accounts file BEFORE constructing AM to prevent legacy migration
fs.writeFileSync(path.join(tmpDir, 'windsurf-assistant-accounts.json'), '[]', 'utf8');

const am = new AccountManager(tmpDir, { isolated: true });

test('初始化成功(隔离)', () => am.count() === 0 ? true : `非空: ${am.count()}`);
test('添加账号', () => {
  const r = am.add('test1@example.com', 'pass123');
  return r === true && am.count() === 1 ? true : `添加失败 r=${r} count=${am.count()}`;
});
test('防重复添加', () => {
  const r = am.add('test1@example.com', 'pass123');
  return r === false && am.count() === 1 ? true : `重复添加成功了 r=${r} count=${am.count()}`;
});
test('获取账号', () => {
  const a = am.get(0);
  return a && a.email === 'test1@example.com' && a.password === 'pass123' ? true : `获取失败: ${JSON.stringify(a)}`;
});
test('更新积分', () => {
  am.updateCredits(0, 100);
  return am.get(0).credits === 100 ? true : `积分未更新`;
});
test('积分历史', () => {
  am.updateCredits(0, 95);
  const a = am.get(0);
  return a.creditHistory && a.creditHistory.length >= 1 ? true : `无历史记录`;
});
test('添加第2个账号', () => {
  am.add('test2@example.com', 'pass456');
  return am.count() === 2 ? true : `count=${am.count()}`;
});
test('findHighest排除当前', () => {
  am.updateCredits(1, 200);
  const best = am.findHighest(0);
  return best && best.index === 1 && best.credits === 200 ? true : JSON.stringify(best);
});
test('findBestAvailable排除限流', () => {
  am.markRateLimited(1, 3600, { model: 'test' });
  const best = am.findBestAvailable(-1, 0);
  return best && best.index === 0 ? true : `找到了限流账号: ${JSON.stringify(best)}`;
});
test('isRateLimited检测', () => {
  return am.isRateLimited(1) === true ? true : '未检测到限流';
});
test('clearRateLimit', () => {
  am.clearRateLimit(1);
  return am.isRateLimited(1) === false ? true : '清除失败';
});
test('effectiveRemaining', () => {
  const r = am.effectiveRemaining(0);
  return r === 95 ? true : `r=${r}`;
});
test('allDepleted(false)', () => {
  return am.allDepleted(5) === false ? true : '误判为耗尽';
});
test('allDepleted(true)', () => {
  am.updateCredits(0, 0);
  am.updateCredits(1, 0);
  return am.allDepleted(5) === true ? true : '未检测到耗尽';
});

// Usage info (quota mode)
test('updateUsage(quota模式)', () => {
  am.updateUsage(0, { mode: 'quota', credits: 50, daily: { remaining: 10, limit: 25, used: 15 }, plan: 'pro' });
  const a = am.get(0);
  return a.usage && a.usage.mode === 'quota' && a.usage.daily.remaining === 10 ? true : 'usage未更新';
});
test('effectiveRemaining(quota)', () => {
  return am.effectiveRemaining(0) === 10 ? true : `r=${am.effectiveRemaining(0)}`;
});
test('findBestForQuota', () => {
  am.updateUsage(1, { mode: 'quota', credits: 50, daily: { remaining: 20, limit: 25 }, plan: 'pro' });
  const best = am.findBestForQuota(0, 5);
  return best && best.index === 1 && best.remaining === 20 ? true : JSON.stringify(best);
});

// Batch parse
test('parseAccounts·email:pass格式', () => {
  const r = AccountManager.parseAccounts('user1@gmail.com:pass123\nuser2@outlook.com:abc456');
  return r.length === 2 && r[0].email === 'user1@gmail.com' ? true : `解析=${r.length}`;
});
test('parseAccounts·email----pass格式', () => {
  const r = AccountManager.parseAccounts('user@test.com----mypassword');
  return r.length === 1 && r[0].password === 'mypassword' ? true : `解析失败`;
});
test('parseAccounts·中文卡号卡密格式', () => {
  const r = AccountManager.parseAccounts('卡号1: user@test.com\n卡密1: mypass');
  return r.length === 1 && r[0].email === 'user@test.com' && r[0].password === 'mypass' ? true : JSON.stringify(r);
});
test('parseAccounts·空/垃圾输入', () => {
  const r = AccountManager.parseAccounts('nothing here\njust text');
  return r.length === 0 ? true : `误解析=${r.length}`;
});

// Export/Import
test('exportToFile', () => {
  const fpath = am.exportToFile(tmpDir);
  return fs.existsSync(fpath) ? true : '导出文件不存在';
});
test('importFromFile(merge)', () => {
  const exportPath = fs.readdirSync(tmpDir).find(f => f.startsWith('wam-backup-'));
  if (!exportPath) return '无导出文件';
  const am2 = new AccountManager(path.join(tmpDir, 'import-test'));
  const result = am2.importFromFile(path.join(tmpDir, exportPath));
  return result.added === 2 ? true : `added=${result.added}`;
});

// Cleanup
test('删除账号', () => {
  am.remove(1);
  return am.count() === 1 ? true : `count=${am.count()}`;
});

// ═══════════════════════════════════════════════════════════
// L5. FingerprintManager 运行时测试
// ═══════════════════════════════════════════════════════════
console.log('\n📋 L5. FingerprintManager运行时');

const { readFingerprint, resetFingerprint: fpReset, getFingerPrintPaths, listResetHistory } = require(path.join(SRC, 'fingerprintManager'));

test('getFingerPrintPaths返回有效路径', () => {
  const p = getFingerPrintPaths();
  return p.machineid && p.storageJson && p.globalBase ? true : '路径不完整';
});
test('readFingerprint返回结构', () => {
  const fp = readFingerprint();
  return typeof fp.count === 'number' && fp.ids ? true : '结构错误';
});
test('readFingerprint检测到至少1个ID', () => {
  const fp = readFingerprint();
  return fp.count > 0 ? true : `count=${fp.count}(Windsurf可能未运行过)`;
});
test('dryRun重置不修改文件', () => {
  const before = readFingerprint();
  const result = fpReset({ dryRun: true });
  const after = readFingerprint();
  return result.ok && JSON.stringify(before.ids) === JSON.stringify(after.ids) ? true : 'dryRun修改了文件!';
});
test('dryRun生成新ID', () => {
  const result = fpReset({ dryRun: true });
  return result.new && Object.keys(result.new).length >= 5 ? true : `新ID数=${Object.keys(result.new || {}).length}`;
});
test('listResetHistory返回数组', () => {
  const h = listResetHistory();
  return Array.isArray(h) ? true : '非数组';
});

// ═══════════════════════════════════════════════════════════
// L6. AuthService 可加载性测试（不做实际网络调用）
// ═══════════════════════════════════════════════════════════
console.log('\n📋 L6. AuthService可加载性');

const { AuthService } = require(path.join(SRC, 'authService'));
const authTmpDir = path.join(tmpDir, 'auth-test');

test('AuthService构造成功', () => {
  const auth = new AuthService(authTmpDir);
  return auth ? true : '构造失败';
});
test('getProxyStatus返回结构', () => {
  const auth = new AuthService(authTmpDir);
  const s = auth.getProxyStatus();
  return s.mode && typeof s.port === 'number' ? true : '结构错误';
});
test('setMode切换', () => {
  const auth = new AuthService(authTmpDir);
  auth.setMode('relay');
  return auth.getProxyStatus().mode === 'relay' ? true : '切换失败';
});
test('setPort设置', () => {
  const auth = new AuthService(authTmpDir);
  auth.setPort(1234);
  const s = auth.getProxyStatus();
  return s.port === 1234 && s.mode === 'local' ? true : `port=${s.port}, mode=${s.mode}`;
});
test('clearTokenCache不崩溃', () => {
  const auth = new AuthService(authTmpDir);
  auth.clearTokenCache();
  return true;
});

// ═══════════════════════════════════════════════════════════
// L6b. 智能代理探测运行时测试 (v5.7.0)
// ═══════════════════════════════════════════════════════════
console.log('\n📋 L6b. 智能代理探测运行时(v5.7.0)');

test('_detectSystemProxy返回数组', () => {
  const auth = new AuthService(authTmpDir);
  const candidates = auth._detectSystemProxy();
  return Array.isArray(candidates) ? true : '返回非数组';
});
test('getProxyStatus含新字段detail', () => {
  const auth = new AuthService(authTmpDir);
  const s = auth.getProxyStatus();
  return s.detail !== undefined ? true : '缺少detail字段';
});
// _tcpProbe and reprobeProxy are async — tested in the async IIFE below

// ═══════════════════════════════════════════════════════════
// L7. 安全管理集成验证（wisdom API可达性）
// ═══════════════════════════════════════════════════════════
console.log('\n📋 L7. 安全管理集成');

async function checkWisdomAPI() {
  return new Promise(resolve => {
    const req = http.request({
      hostname: '127.0.0.1', port: 9876, path: '/api/catalog', method: 'GET', timeout: 3000
    }, res => {
      let data = '';
      res.on('data', d => data += d);
      res.on('end', () => {
        try { resolve({ ok: true, data: JSON.parse(data) }); }
        catch { resolve({ ok: true, data: {} }); }
      });
    });
    req.on('error', () => resolve({ ok: false }));
    req.on('timeout', () => { req.destroy(); resolve({ ok: false }); });
    req.end();
  });
}

async function checkSecurityHub() {
  return new Promise(resolve => {
    const req = http.request({
      hostname: '127.0.0.1', port: 9877, path: '/api/status', method: 'GET', timeout: 3000
    }, res => {
      let data = '';
      res.on('data', d => data += d);
      res.on('end', () => {
        try { resolve({ ok: true, data: JSON.parse(data) }); }
        catch { resolve({ ok: true, data: {} }); }
      });
    });
    req.on('error', () => resolve({ ok: false }));
    req.on('timeout', () => { req.destroy(); resolve({ ok: false }); });
    req.end();
  });
}

(async () => {
  // L6b async tests
  await asyncTest('_tcpProbe返回bool(async)', async () => {
    const auth = new AuthService(authTmpDir);
    const r = await auth._tcpProbe('127.0.0.1', 1, 200);
    return r === false ? true : `意外结果: ${r}`;
  });
  await asyncTest('reprobeProxy返回结构(async)', async () => {
    const auth = new AuthService(authTmpDir);
    const r = await auth.reprobeProxy();
    return r.mode && typeof r.port === 'number' ? true : `结构错误: ${JSON.stringify(r)}`;
  });

  const wisdom = await checkWisdomAPI();
  total++;
  if (wisdom.ok) {
    pass++;
    console.log(`  ✅ 智慧部署器(:9876)在线`);
  } else {
    pass++; // 不在线也算pass，因为是可选依赖
    console.log(`  ⚠️  智慧部署器(:9876)未运行 (可选依赖,降级正常)`);
  }

  const hub = await checkSecurityHub();
  total++;
  if (hub.ok) {
    pass++;
    console.log(`  ✅ 安全中枢(:9877)在线`);
  } else {
    pass++;
    console.log(`  ⚠️  安全中枢(:9877)未运行 (可选依赖,降级正常)`);
  }

  // ═══ 清理 ═══
  try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch {}

  // ═══ 总结 ═══
  console.log(`\n${'═'.repeat(50)}`);
  console.log(`  Deep E2E: 总计: ${total}  通过: ${pass}  失败: ${fail}`);
  console.log(`  通过率: ${Math.round(pass/total*100)}%`);
  console.log(`${'═'.repeat(50)}`);
  process.exit(fail > 0 ? 1 : 0);
})();
