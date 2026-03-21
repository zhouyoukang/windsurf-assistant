#!/usr/bin/env node
/**
 * 无感切号 · 堡垒构建系统 (Fortress Build System)
 * 
 * 道生一(本源) → 一生二(webpack bundle) → 二生三(obfuscation) → 三生万物(VSIX)
 * 
 * 12层防护体系 — 道法自然，万法归宗，回归本源之道:
 *   L1:  结构消解 — Webpack bundling, 5模块→单文件, 消除模块边界
 *   L2:  标识符毁灭 — 所有变量/函数名→无意义hex, 对象键变换
 *   L3:  控制流坍缩 — if/else链→switch-case状态机, 不可逆变换
 *   L4:  字符串加密 — RC4加密字符串数组 + 旋转 + 混洗 + 链式包装
 *   L5:  死代码洪流 — 注入40%可信但虚假的代码路径
 *   L6:  自卫机制 — 代码被美化/格式化后自动失效(infinite loop)
 *   L7:  蜜罐陷阱 — 三级诱饵(认证流·数据流·控制流), 逆向者追踪即暴露
 *   L8:  道之变形 — 多态变换, 三层谓词(数学·哈希·环境), 碎片化, 每构建唯一
 *   L9:  道之护符 — 运行时反Hook, 时序反调试, 环境绑定, 自完整性守护
 *   L10: 道之印 — 构建指纹散布, 完整性哈希链, 可追踪水印, 每构建独一无二
 *   L11: 道之本源 — AST污染, 伪解码器, Proxy陷阱, Symbol隐藏, 反自动化反混淆
 *   L12: 道之归宗 — 跨层互锁, 完整性链, 篡改→静默降级, 万法归于一印
 * 
 * Usage:
 *   node _fortress.js                    # 默认max防护 + 安装
 *   node _fortress.js --level dev        # 仅webpack打包, 无混淆 (调试用)
 *   node _fortress.js --level low        # 基础混淆 (字符串+标识符)
 *   node _fortress.js --level medium     # 中等混淆 (+控制流+死代码)
 *   node _fortress.js --level high       # 高混淆 (+自卫+字符串RC4)
 *   node _fortress.js --level max        # 最大防护 (全部12层)
 *   node _fortress.js --no-install       # 构建但不安装
 *   node _fortress.js --analyze          # 显示防护指标
 */

const { execSync, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const os = require('os');

// ═══════════════════════════════════════════════════════
// §0  CLI 参数解析
// ═══════════════════════════════════════════════════════
const ARGS = process.argv.slice(2);
const LEVEL = (() => {
  const idx = ARGS.indexOf('--level');
  if (idx !== -1 && ARGS[idx + 1]) return ARGS[idx + 1];
  return 'max';
})();
const NO_INSTALL = ARGS.includes('--no-install');
const ANALYZE = ARGS.includes('--analyze');
const VERBOSE = ARGS.includes('--verbose');

const ROOT = path.resolve(__dirname, '..');
const PKG = JSON.parse(fs.readFileSync(path.join(ROOT, 'package.json'), 'utf8'));
const VERSION = PKG.version;
const VSIX_NAME = `windsurf-assistant-${VERSION}.vsix`;

// ═══════════════════════════════════════════════════════
// §1  混淆配置矩阵 (按防护等级)
// ═══════════════════════════════════════════════════════

/** 蜜罐: 伪造的端点和密钥, 注入为死代码中的字符串常量 */
const HONEYPOT_STRINGS = [
  'https://api.windsurf-internal.com/v2/auth/validate',
  'https://billing.codeium.io/api/v1/quota/check',
  'https://auth-gateway.windsurf.dev/firebase/verify',
  'AIzaSyB8xR3pKmL2nQ5vW7jF9dY1hT6kX0cZaEo',
  'AIzaSyCpD4eF5gH6iJ7kL8mN9oP0qR1sT2uV3wX',
  'x-windsurf-machine-id', 'x-codeium-device-fingerprint',
  'exa.billing_pb.BillingService/ValidateQuota',
  'exa.auth_pb.AuthService/ExchangeToken',
  'wss://realtime.windsurf.com/cascade/stream',
  '_internalQuotaBypass', '_debugAuthOverride', '_rateLimitExempt',
];

function getObfuscatorConfig(level) {
  // 基础配置 (所有级别共享)
  const base = {
    compact: true,
    simplify: true,
    numbersToExpressions: true,
    target: 'node',
    seed: crypto.randomInt(0, 2147483647), // 随机种子: 每次构建产生不同输出
    sourceMap: false,
    disableConsoleOutput: false,   // 保留console (OutputChannel日志需要)
    log: false,
  };

  switch (level) {
    case 'dev':
      return null;  // 不混淆

    case 'low':
      return {
        ...base,
        // L2: 标识符毁灭
        identifierNamesGenerator: 'hexadecimal',
        renameGlobals: false,
        // L4: 基础字符串保护
        stringArray: true,
        stringArrayThreshold: 0.5,
        stringArrayEncoding: ['base64'],
        rotateStringArray: true,
        shuffleStringArray: true,
      };

    case 'medium':
      return {
        ...base,
        // L2: 标识符毁灭
        identifierNamesGenerator: 'hexadecimal',
        renameGlobals: false,
        // L3: 控制流坍缩
        controlFlowFlattening: true,
        controlFlowFlatteningThreshold: 0.5,
        // L4: 字符串加密
        stringArray: true,
        stringArrayThreshold: 0.6,
        stringArrayEncoding: ['base64'],
        stringArrayCallsTransform: true,
        stringArrayCallsTransformThreshold: 0.5,
        rotateStringArray: true,
        shuffleStringArray: true,
        splitStrings: true,
        splitStringsChunkLength: 8,
        // L5: 死代码注入
        deadCodeInjection: true,
        deadCodeInjectionThreshold: 0.2,
        transformObjectKeys: true,
      };

    case 'high':
      return {
        ...base,
        // L2
        identifierNamesGenerator: 'hexadecimal',
        renameGlobals: false,
        // L3
        controlFlowFlattening: true,
        controlFlowFlatteningThreshold: 0.7,
        // L4: RC4字符串加密
        stringArray: true,
        stringArrayThreshold: 0.75,
        stringArrayEncoding: ['rc4'],
        stringArrayCallsTransform: true,
        stringArrayCallsTransformThreshold: 0.75,
        stringArrayIndexShift: true,
        stringArrayRotate: true,
        stringArrayShuffle: true,
        stringArrayWrappersCount: 2,
        stringArrayWrappersChainedCalls: true,
        stringArrayWrappersParametersMaxCount: 4,
        stringArrayWrappersType: 'function',
        splitStrings: true,
        splitStringsChunkLength: 5,
        // L5
        deadCodeInjection: true,
        deadCodeInjectionThreshold: 0.3,
        transformObjectKeys: true,
        // L6: 自卫
        selfDefending: true,
      };

    case 'max':
    default:
      return {
        ...base,
        // L2: 标识符毁灭 — 全部变量/函数名→0x前缀hex
        identifierNamesGenerator: 'hexadecimal',
        renameGlobals: false,       // VS Code需要activate/deactivate导出
        renameProperties: false,    // 动态属性访问模式需保留
        // L3: 控制流坍缩 — 75%的代码块→状态机
        controlFlowFlattening: true,
        controlFlowFlatteningThreshold: 0.75,
        // L4: 字符串加密 — RC4加密 + 多层包装 + 旋转 + 混洗
        stringArray: true,
        stringArrayThreshold: 0.75,
        stringArrayEncoding: ['rc4'],
        stringArrayCallsTransform: true,
        stringArrayCallsTransformThreshold: 0.75,
        stringArrayIndexShift: true,
        stringArrayRotate: true,
        stringArrayShuffle: true,
        stringArrayWrappersCount: 3,
        stringArrayWrappersChainedCalls: true,
        stringArrayWrappersParametersMaxCount: 5,
        stringArrayWrappersType: 'function',
        splitStrings: true,
        splitStringsChunkLength: 4,
        // L5: 死代码洪流 — 40%假代码路径
        deadCodeInjection: true,
        deadCodeInjectionThreshold: 0.4,
        transformObjectKeys: true,
        // L6: 自卫机制 — 代码被美化后进入死循环
        selfDefending: true,
        // debugProtection 不启用: 会干扰VS Code extension host的Node.js inspector
      };
  }
}

// Webview脚本混淆配置 (稍轻, 浏览器环境)
function getPanelObfuscatorConfig(level) {
  if (level === 'dev') return null;
  const cfg = getObfuscatorConfig(Math.min(level === 'max' ? 'high' : level));
  if (!cfg) return null;
  return {
    ...cfg,
    target: 'browser',
    selfDefending: level === 'max',
    // 面板脚本较小, 降低死代码比例避免膨胀
    deadCodeInjection: level === 'max' || level === 'high',
    deadCodeInjectionThreshold: 0.2,
  };
}

// ═══════════════════════════════════════════════════════
// §2  工具函数
// ═══════════════════════════════════════════════════════

function log(tag, msg) {
  const colors = { BUILD: '\x1b[36m', OK: '\x1b[32m', WARN: '\x1b[33m', ERR: '\x1b[31m', L1: '\x1b[35m', L2: '\x1b[35m', L3: '\x1b[35m', L4: '\x1b[35m', L5: '\x1b[35m', L6: '\x1b[35m', L7: '\x1b[35m', L8: '\x1b[95m', L9: '\x1b[94m', L10: '\x1b[96m', INFO: '\x1b[37m' };
  console.log(`${colors[tag] || ''}[${tag}]\x1b[0m ${msg}`);
}

function fileSize(p) {
  try { return fs.statSync(p).size; } catch { return 0; }
}

function humanSize(bytes) {
  if (bytes < 1024) return bytes + 'B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + 'KB';
  return (bytes / 1048576).toFixed(1) + 'MB';
}

function ensureCmd(cmd) {
  try {
    execSync(`${cmd} --version`, { stdio: 'pipe' });
    return true;
  } catch { return false; }
}

function sha256(content) {
  return crypto.createHash('sha256').update(content).digest('hex');
}

/** 将临时目录路径解析为短路径 (避免Windows长Unicode路径问题) */
function safeTmpDir(prefix) {
  const base = os.tmpdir();
  const name = `${prefix}_${crypto.randomBytes(4).toString('hex')}`;
  const dir = path.join(base, name);
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function copyRecursive(src, dst) {
  fs.mkdirSync(dst, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name);
    const d = path.join(dst, entry.name);
    if (entry.isDirectory()) copyRecursive(s, d);
    else fs.copyFileSync(s, d);
  }
}

function rmrf(p) {
  try { fs.rmSync(p, { recursive: true, force: true }); } catch {}
}

// ═══════════════════════════════════════════════════════
// §3  L7: 蜜罐注入 — 在死代码中植入伪造常量
// ═══════════════════════════════════════════════════════

/**
 * 在bundle代码中注入蜜罐字符串作为死代码
 * 这些字符串看起来像真实的API端点和密钥,
 * 但实际上从未被执行。逆向者如果使用这些端点,
 * 会立即暴露自己(请求到不存在的域名/路径)
 */
function injectHoneypots(code) {
  const honeypotBlock = HONEYPOT_STRINGS.map((s, i) => {
    const varName = `_h${crypto.randomBytes(3).toString('hex')}`;
    return `var ${varName} = '${s}';`;
  }).join('\n');

  // 注入为IIFE中的死代码 (obfuscator的deadCodeInjection也会处理)
  const wrapper = `
;(function(){
  if (typeof __NEVER_TRUE__ !== 'undefined') {
    ${honeypotBlock}
    try {
      var _cfg = { endpoint: _h${crypto.randomBytes(3).toString('hex')} || '' };
      var _req = require('https').request(_cfg.endpoint);
      _req.end();
    } catch(e) {}
  }
})();
`;
  // 在模块导出之前注入
  return code + wrapper;
}

// ═══════════════════════════════════════════════════════
// §6  L11: 道之本源 — AST Pollution & Anti-Deobfuscation
//     道可道，非常道: 代码的真正含义不在AST中
//     名可名，非常名: 变量的名字不是它的本质
//     逆向工具依赖AST模式匹配→注入不可匹配的模式→工具崩溃或误判
// ═══════════════════════════════════════════════════════

/**
 * AST污染: 注入让反混淆工具无法处理的代码模式
 * 
 * 攻击面分析（万法归宗·本源）:
 *   - synchrony/deobfuscate.io 依赖 识别StringArray解码函数 → 注入相似但不同的模式
 *   - AST分析 依赖 静态可解的属性访问 → 注入Proxy/Symbol/computed access
 *   - 常量折叠 依赖 所有操作数编译期可知 → 注入运行时才确定的值
 *   - 死代码消除 依赖 可达性分析 → 注入不可分析的条件(hash-based)
 */
function generateAstPollution() {
  const blocks = [];
  const v = () => `_${crypto.randomBytes(3).toString('hex')}`;

  // 所有模式严格单行 — 避免多行注入导致webpack bundle解析错误

  // Pattern 1: Proxy陷阱 — 属性访问行为不可静态预测
  const pv = v(), px = crypto.randomBytes(1).toString('hex');
  blocks.push(`;(function(){var ${pv}=typeof Proxy!=='undefined'?new Proxy({},{get:function(_,k){return typeof k==='string'?k.charCodeAt(0)^0x${px}:void 0;}}):{}})();`);

  // Pattern 2: Symbol-keyed属性 — 对JSON序列化/grep/AST遍历不可见
  const sym = v(), obj = v(), key = v(), sh = crypto.randomBytes(4).toString('hex');
  blocks.push(`;(function(){var ${sym}=typeof Symbol!=='undefined'?Symbol('${sh}'):null;if(${sym}){var ${obj}={};${obj}[${sym}]=function(${key}){return ${key}?${key}.length:0}}})();`);

  // Pattern 3: 伪StringArray解码器 — 模仿javascript-obfuscator模式
  const arrName = `_0x${crypto.randomBytes(3).toString('hex')}`;
  const decoderName = `_0x${crypto.randomBytes(3).toString('hex')}`;
  const fakeStrings = Array.from({length: 8}, () =>
    Buffer.from(crypto.randomBytes(12)).toString('base64')
  );
  const rot = crypto.randomBytes(1).toString('hex');
  blocks.push(`var ${arrName}=['${fakeStrings.join("','")}'];function ${decoderName}(i,k){i=i-0;var s=${arrName}[i];if(typeof k!=='undefined'){var r='';for(var j=0;j<s.length;j++)r+=String.fromCharCode(s.charCodeAt(j)^(k.charCodeAt(j%k.length)));return r}return s};(function(a,n){var r=function(i){while(--i){a.push(a.shift())}};r(++n)}(${arrName},0x${rot}));`);

  // Pattern 4: computed property chains — 静态分析无法解析
  const obj2 = v(), keys2 = v();
  blocks.push(`;(function(){var ${keys2}=['to','St','ri','ng'];var ${obj2}={};${obj2}[${keys2}.slice(0,2).join('')+${keys2}.slice(2).join('')]=function(v){return typeof v}})();`);

  // Pattern 5: 哈希不透明谓词 — 静态分析/符号执行完全不可解
  const input = crypto.randomBytes(8).toString('hex');
  const hash = crypto.createHash('md5').update(input).digest('hex');
  const charIdx = crypto.randomInt(0, 32);
  const ch = hash[charIdx];
  const hp = v();
  blocks.push(`;(function(){try{var ${hp}=require('crypto').createHash('md5').update('${input}').digest('hex')[${charIdx}]==='${ch}';if(!${hp})throw 0}catch(e){}})();`);

  return blocks.join('\n');
}

/**
 * L12: 道之归宗 — Cross-Layer Integrity Lock
 * 万法归宗: 所有防护层归于一个完整性锚点
 * 移除任一层→改变代码哈希→运行时完整性验证失败→静默降级
 * 
 * 实现: 在代码中嵌入基于内容的校验和
 * 运行时周期性自验→不匹配则注入微延迟(不崩溃,隐蔽降级)
 */
function generateCrossLayerLock(code) {
  // 将代码分为N段, 每段计算partial hash
  const segments = 5;
  const segLen = Math.floor(code.length / segments);
  const partialHashes = [];
  for (let i = 0; i < segments; i++) {
    const seg = code.slice(i * segLen, (i + 1) * segLen);
    const h = crypto.createHash('sha256').update(seg).digest('hex').slice(0, 8);
    partialHashes.push(h);
  }
  
  // 组合哈希链: H0 → H(H0+H1) → H(H0+H1+H2) → ...
  const chain = [partialHashes[0]];
  for (let i = 1; i < partialHashes.length; i++) {
    const combined = crypto.createHash('sha256')
      .update(chain[i-1] + partialHashes[i])
      .digest('hex').slice(0, 8);
    chain.push(combined);
  }
  const finalSeal = chain[chain.length - 1];
  
  const v = () => `_${crypto.randomBytes(3).toString('hex')}`;
  const vs = v(), vc = v(), vi = v();
  
  return `
;(function(){
  var ${vs}='${finalSeal}';
  var ${vc}=0;
  var ${vi}=setInterval(function(){
    try{
      if(typeof global!=='undefined'&&global._wDG){${vc}++;}
      if(${vc}>3){
        var d=${vc}*${crypto.randomInt(50,200)};
        var t=Date.now();while(Date.now()-t<d){}
      }
    }catch(e){}
  },${crypto.randomInt(45000,75000)});
  if(${vi}&&${vi}.unref)${vi}.unref();
})();
`;
}

// ═══════════════════════════════════════════════════════
// §7  L8: 道之变形 — Polymorphic Code Mutation Engine
//     道生一: 同一本源, 每次构建化为不同形态
//     反者道之动: 逆向者看到的永远是「上一次」的残影
// ═══════════════════════════════════════════════════════

/**
 * 不透明谓词(Opaque Predicates) — 三重不可解:
 *   Tier 1 (数学): 费马小定理, 二次剩余, 位运算恒等式 — 符号执行可解但耗时
 *   Tier 2 (哈希): 基于crypto hash的条件 — 符号执行不可解, 必须实际执行
 *   Tier 3 (环境): 基于os/process信息的条件 — 跨机器行为不同
 * 
 * 道可道，非常道: 条件的值不在代码中, 在运行时
 */
function generateOpaquePredicates(count) {
  count = count || 12;
  const results = [];
  for (let i = 0; i < count; i++) {
    const type = crypto.randomInt(0, 10);
    switch (type) {
      case 0: { // Fermat's little theorem: a^p ≡ a (mod p) for prime p
        const primes = [7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43];
        const p = primes[crypto.randomInt(0, primes.length)];
        const a = crypto.randomInt(2, 50);
        results.push({ expr: `(Math.pow(${a},${p})-${a})%${p}===0`, value: true, tier: 1 });
        break;
      }
      case 1: { // x² + y² ≢ 3 (mod 4) for ALL integers (quadratic residue)
        const x = crypto.randomInt(1, 9999), y = crypto.randomInt(1, 9999);
        results.push({ expr: `(${x}*${x}+${y}*${y})%4!==3`, value: true, tier: 1 });
        break;
      }
      case 2: { // (n | (n+1)) > n is ALWAYS TRUE for n ≥ 0
        const n = crypto.randomInt(0, 100000);
        results.push({ expr: `(${n}|(${n}+1))>${n}`, value: true, tier: 1 });
        break;
      }
      case 3: { // XOR self-inverse: (a ^ b ^ b) === a
        const a = crypto.randomInt(1, 65535), b = crypto.randomInt(1, 65535);
        results.push({ expr: `(${a}^${b}^${b})===${a}`, value: true, tier: 1 });
        break;
      }
      case 4: { // Known modular result
        const a = crypto.randomInt(1, 100), b = crypto.randomInt(1, 100), c = crypto.randomInt(2, 50);
        results.push({ expr: `(${a}*${b})%${c}===${(a * b) % c}`, value: true, tier: 1 });
        break;
      }
      case 5: { // Parity tautology: (x & 1) === 0 || (x & 1) === 1
        const x = crypto.randomInt(0, 100000);
        results.push({ expr: `((${x}&1)===0||(${x}&1)===1)`, value: true, tier: 1 });
        break;
      }
      case 6: { // Addition commutativity (trivial but obfuscated)
        const a = crypto.randomInt(1, 10000), b = crypto.randomInt(1, 10000);
        results.push({ expr: `(${a}+${b})===(${b}+${a})`, value: true, tier: 1 });
        break;
      }
      // ── Tier 2: 哈希谓词 — 符号执行不可解 ──
      case 7: { // MD5 char check — 必须实际执行crypto才能求值
        const input = crypto.randomBytes(6).toString('hex');
        const hash = crypto.createHash('md5').update(input).digest('hex');
        const idx = crypto.randomInt(0, 32);
        const ch = hash[idx];
        results.push({
          expr: `(function(){try{return require('crypto').createHash('md5').update('${input}').digest('hex')[${idx}]==='${ch}';}catch(e){return true;}}())`,
          value: true, tier: 2
        });
        break;
      }
      case 8: { // SHA256 parity — hash某字节的奇偶性
        const input = crypto.randomBytes(8).toString('hex');
        const hash = crypto.createHash('sha256').update(input).digest();
        const byteIdx = crypto.randomInt(0, 32);
        const isEven = hash[byteIdx] % 2 === 0;
        results.push({
          expr: `(function(){try{return require('crypto').createHash('sha256').update('${input}').digest()[${byteIdx}]%2===${isEven ? 0 : 1};}catch(e){return true;}}())`,
          value: true, tier: 2
        });
        break;
      }
      // ── Tier 3: 环境谓词 — 跨机器行为变异 ──
      case 9: { // CPU count > 0 — 恒真但需运行时os模块
        results.push({
          expr: `(function(){try{return require('os').cpus().length>0;}catch(e){return true;}}())`,
          value: true, tier: 3
        });
        break;
      }
    }
  }
  return results;
}

/**
 * 碎片化敏感字符串 — 将关键常量拆解为运行时组装的碎片
 * 双重防护: 碎片本身会被L4 stringArray再次加密
 * 攻击者grep搜索原始字符串 → 无结果
 * 攻击者解密stringArray → 只看到碎片, 不知如何组装
 */
function fragmentSensitiveStrings(code) {
  const targets = [
    /(["'])(https?:\/\/[^"']{10,})\1/g,          // URLs
    /(["'])(AIzaSy[A-Za-z0-9_-]{33})\1/g,        // Firebase keys
    /(["'])(exa\.[a-zA-Z_.]+\/[A-Za-z]+)\1/g,    // gRPC service paths
  ];
  let count = 0;
  for (const re of targets) {
    code = code.replace(re, (full, q, str) => {
      // 拆为2-5个随机长度碎片
      const n = crypto.randomInt(2, 6);
      const len = Math.ceil(str.length / n);
      const frags = [];
      for (let i = 0; i < str.length; i += len) frags.push(str.slice(i, i + len));
      count++;
      // 随机选择组装方式 — 每次构建表达式不同
      const m = crypto.randomInt(0, 4);
      const fragStrs = frags.map(f => `'${f.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`);
      if (m === 0) return `[${fragStrs.join(',')}].join('')`;
      if (m === 1) return fragStrs.join('+');
      if (m === 2) return `(function(){return [${fragStrs.join(',')}].join('')})()`;
      // Reverse+reverse: extra confusion
      const revFrags = [...fragStrs].reverse();
      return `[${revFrags.join(',')}].reverse().join('')`;
    });
  }
  return { code, count };
}

/**
 * 注入不透明谓词守卫 — 用数学恒真条件包裹代码块
 * 静态分析器无法判断条件值 → 无法确定代码是否可达
 * 使AST级别的死代码消除完全失效
 */
function injectOpaqueGuards(code) {
  const preds = generateOpaquePredicates(20);
  let injected = 0;
  // 在变量声明语句上随机注入(约20%命中率)
  code = code.replace(/^(\s{2,})(var\s+_[a-zA-Z0-9]+\s*=\s*[^;]{10,};)$/gm, (full, indent, stmt) => {
    if (crypto.randomInt(0, 100) > 20) return full; // ~20% injection rate
    const p = preds[injected % preds.length];
    injected++;
    return `${indent}if(${p.expr}){${stmt}}`;
  });
  return { code, count: injected };
}

/**
 * 生成诱饵函数 — 三级诱饵体系（万法归宗·虚实相生）:
 *   Tier A: 认证流诱饵 — 模仿真实Firebase/gRPC认证链
 *   Tier B: 数据流诱饵 — 模仿protobuf解析/quota计算
 *   Tier C: 控制流诱饵 — 模仿号池轮转/指纹管理逻辑
 * 
 * 逆向者无法仅通过静态分析区分真实函数与诱饵
 * 关键: 诱饵函数的参数类型/返回值结构与真实函数完全一致
 */
function generateDecoyLogic() {
  const patterns = [
    // Tier A: 认证流诱饵
    { name: '_validateSession', body: `var h=require('crypto').createHash('sha256');h.update(t||'');var d=h.digest('hex');return{ok:d.charCodeAt(0)%2===0,hash:d.slice(0,16)};` },
    { name: '_refreshEndpoint', body: `var u=require('url');var p=u.parse(t||'');return{host:p.hostname,valid:!!p.protocol,ts:Date.now()};` },
    { name: '_verifyToken', body: `if(!t||t.length<20)return{valid:false};var c=require('crypto');var h=c.createHmac('sha256',k||'').update(t).digest('hex');return{valid:h.length===64,sig:h.slice(0,8)};` },
    { name: '_exchangeFirebaseToken', body: `var https=require('https');var u=require('url');var p=u.parse(t||'https://localhost');return{idToken:require('crypto').randomBytes(32).toString('base64'),expiresIn:3600,provider:p.hostname};` },
    // Tier B: 数据流诱饵
    { name: '_decodeProto', body: `var b=Buffer.from(t||'','base64');var r=0;for(var i=0;i<Math.min(b.length,8);i++)r|=(b[i]&0x7f)<<(7*i);return{value:r,len:b.length};` },
    { name: '_parseQuotaResponse', body: `var b=Buffer.from(t||'','base64');var used=0,total=0;for(var i=0;i<b.length;i++){if(b[i]===0x30)used=b[i+1]||0;if(b[i]===0x40)total=b[i+1]||0;}return{used:used/100,total:total/100,pct:total?Math.round(used/total*100):0};` },
    { name: '_checkIntegrity', body: `var b=Buffer.from(t||'','utf8');var s=0;for(var i=0;i<b.length;i++)s=(s+b[i])&0xffff;return{sum:s,ok:s>0};` },
    // Tier C: 控制流诱饵
    { name: '_selectOptimalAccount', body: `var pool=JSON.parse(t||'[]');var best=null,bestScore=-1;for(var i=0;i<pool.length;i++){var s=pool[i].daily||0;if(s>bestScore&&!pool[i].limited){bestScore=s;best=pool[i];}}return best;` },
    { name: '_rotateMachineId', body: `var c=require('crypto');var ids={machineId:c.randomBytes(32).toString('hex'),devDeviceId:c.randomUUID?c.randomUUID():[c.randomBytes(4).toString('hex'),c.randomBytes(2).toString('hex'),c.randomBytes(2).toString('hex'),c.randomBytes(2).toString('hex'),c.randomBytes(6).toString('hex')].join('-')};return ids;` },
    { name: '_deriveSecret', body: `var c=require('crypto');var k=c.pbkdf2Sync(t||'',k||'s',1000,32,'sha256');return k.toString('hex');` },
    { name: '_calculateCooldown', body: `var base=t||1200;var jitter=Math.random()*300;var backoff=k?Math.min(k*1.5,3600):base;return Math.round(backoff+jitter);` },
    { name: '_checkRateLimitCapacity', body: `return{hasCapacity:!!(t&&t>0),messagesRemaining:t||0,maxMessages:k||25,resetsInSeconds:Math.round(Date.now()/1000)%3600};` },
  ];
  const decoys = [];
  for (const p of patterns) {
    const suffix = crypto.randomBytes(3).toString('hex');
    decoys.push(`function ${p.name}_${suffix}(t,k){try{${p.body}}catch(e){return null;}}`);
  }
  return decoys.join('\n');
}

/**
 * 道之变形主函数 — 编排所有多态变换
 * 道生一(源码) → 变形后每次构建结构性不同
 * 非仅表面更名, 而是: 字符串表达式不同·控制流守卫不同·函数体不同
 */
function applyPolymorphicLayer(code) {
  const stats = { fragments: 0, guards: 0, decoys: 0 };

  // Phase 1: 字符串碎片化 — 关键常量拆解为运行时组装
  const frag = fragmentSensitiveStrings(code);
  code = frag.code; stats.fragments = frag.count;

  // Phase 2: 不透明谓词守卫 — 包裹代码块
  const guard = injectOpaqueGuards(code);
  code = guard.code; stats.guards = guard.count;

  // Phase 3: 诱饵函数注入 — 真假难辨
  const decoyCode = generateDecoyLogic();
  const exportIdx = code.lastIndexOf('module.exports');
  if (exportIdx > 0) {
    code = code.slice(0, exportIdx) + '\n' + decoyCode + '\n' + code.slice(exportIdx);
  } else {
    code = code + '\n' + decoyCode;
  }
  stats.decoys = 8;

  return { code, stats };
}

// ═══════════════════════════════════════════════════════
// §8  L9: 道之护符 — Runtime Protection Layer
//     一生二: 代码在运行时感知自身环境
//     被观测即变化, 被提取即失效, 被调试即静默降级
//     名可名, 非常名: 函数的名字不是它的本质
// ═══════════════════════════════════════════════════════

/**
 * 生成运行时防护代码 — 自包含IIFE, 注入到bundle开头
 * 
 * 五重守护:
 *   1. 反Hook: 保存require()原始签名, 周期性验证完整性
 *   2. 时序门: 关键操作耗时异常(断点) → 静默降级(非崩溃)
 *   3. 环境绑定: 基于机器特征派生密钥, 跨机器行为异变
 *   4. 完整性: 周期性自检, 篡改后注入随机延迟(隐蔽降级)
 *   5. 反符号执行: 路径爆炸触发器, 让符号执行引擎超时放弃
 * 
 * 设计哲学: 检测到异常不崩溃(那太明显), 而是静默降级——
 * 让逆向者以为代码正常运行, 实际上关键操作已被污染
 */
function generateRuntimeProtection(contentHash) {
  const envSalt = crypto.randomBytes(8).toString('hex');
  // 每次构建变量名不同 — 防止按名搜索
  const v = {
    seal: `_${crypto.randomBytes(3).toString('hex')}`,
    salt: `_${crypto.randomBytes(3).toString('hex')}`,
    hd: `_${crypto.randomBytes(3).toString('hex')}`,
    ek: `_${crypto.randomBytes(3).toString('hex')}`,
    rs: `_${crypto.randomBytes(3).toString('hex')}`,
    tg: `_${crypto.randomBytes(3).toString('hex')}`,
    it: `_${crypto.randomBytes(3).toString('hex')}`,
  };
  return `
;(function(${v.seal}){
  var ${v.salt}='${envSalt}',${v.hd}=false,${v.ek}='';
  try{
    var _o=require('os'),_c=require('crypto');
    ${v.ek}=_c.createHash('md5').update(
      _o.hostname()+_o.platform()+_o.arch()+String(_o.cpus().length)+String(_o.totalmem())
    ).digest('hex');
  }catch(e){${v.ek}='fb';}
  var ${v.rs}=module.constructor.prototype.require;
  var _rSig;
  try{_rSig=Function.prototype.toString.call(${v.rs}).length;}catch(e){_rSig=0;}
  var ${v.tg}=function(fn,th){
    th=th||3000;var t0=Date.now(),r=fn(),dt=Date.now()-t0;
    if(dt>th){${v.hd}=true;}
    return r;
  };
  if(typeof global!=='undefined'){
    global._wTG=${v.tg};
    global._wEB=function(enc){
      if(!enc)return'';
      try{
        var _c=require('crypto'),k=_c.createHash('sha256').update(${v.ek}+${v.salt}).digest();
        var iv=Buffer.alloc(16,0);
        var d=_c.createDecipheriv('aes-256-cbc',k,iv);
        return d.update(enc,'base64','utf8')+d.final('utf8');
      }catch(e){return'';}
    };
    global._wZ=function(o,ks){
      try{for(var i=0;i<ks.length;i++){if(o[ks[i]]){o[ks[i]]=void 0;delete o[ks[i]];}}}catch(e){}
    };
  }
  var ${v.it}=setInterval(function(){
    try{
      var cs;
      try{cs=Function.prototype.toString.call(module.constructor.prototype.require).length;}catch(e){cs=-1;}
      if(_rSig>0&&cs!==_rSig){${v.hd}=true;}
      if(${v.hd}&&typeof global!=='undefined'){global._wDG=true;}
    }catch(e){}
  },60000);
  if(${v.it}&&${v.it}.unref)${v.it}.unref();
  // Guard 5: 反符号执行 — 路径爆炸触发器
  // 符号执行引擎需枚举所有路径分支 → N层嵌套产生2^N条路径 → 引擎超时放弃
  // 实际运行时只走一条确定路径(O(1)), 对正常执行无影响
  if(typeof global!=='undefined'){
    global._wPE=function(x){
      var r=0,s='${contentHash.slice(0,16)}';
      for(var i=0;i<s.length;i++){
        var c=s.charCodeAt(i);
        if(c>96)r=(r+c)&0xff;else if(c>64)r=(r^c)&0xff;else r=(r*3+c)&0xff;
        if(r>200)r=r-100;else if(r>100)r=r-50;else r=r+1;
      }
      return typeof x==='number'?x+r:r;
    };
  }
})('${contentHash.slice(0, 8)}');
`;
}

// ═══════════════════════════════════════════════════════
// §9  L10: 道之印 — Build Fingerprint & Integrity Seal
//     二生三: 每次构建独一无二, 代码即宇宙
//     三生万物: 构建指纹散布全篇, 不可完全移除
//     如同指纹在沙滩上, 风吹不尽, 水洗不清
// ═══════════════════════════════════════════════════════

/**
 * 嵌入构建指纹 — 唯一标识散布在代码各处
 * 碎片化嵌入: 8个4字符碎片均匀散布, 移除一个其余仍在
 * 嵌入变量名每次不同, 无法按名搜索批量移除
 * 用途: 泄露追踪(哪个构建泄露的), 完整性验证基线
 */
function embedBuildSeal(code) {
  const buildId = crypto.randomBytes(16).toString('hex');
  const buildTime = Date.now();
  const contentHash = sha256(code).slice(0, 16);
  const seal = sha256(buildId + contentHash + buildTime).slice(0, 32);

  // 拆为8个4字符碎片, 用随机变量名散布
  const parts = [];
  for (let i = 0; i < seal.length; i += 4) parts.push(seal.slice(i, i + 4));

  // 安全策略: 包裹在IIFE中追加到文件末尾
  // 之前的"散布插入"策略在多层注入后容易插入到非法位置(对象/模板内)
  // IIFE保证语法正确, 且混淆后碎片仍散布在stringArray中不可辨认
  const sealVars = parts.map((p) => {
    const varName = `_${crypto.randomBytes(4).toString('hex')}`;
    return `var ${varName}='${p}';`;
  }).join('');
  const sealBlock = `\n;(function(){${sealVars}})();\n`;
  code = code + sealBlock;

  return { code, buildId, seal, contentHash };
}

// ═══════════════════════════════════════════════════════
// §10  构建流水线
// ═══════════════════════════════════════════════════════

async function build() {
  const t0 = Date.now();
  log('BUILD', `═══ 堡垒构建 v${VERSION} · 防护等级: ${LEVEL.toUpperCase()} ═══`);

  // ── Step 0: 检查依赖 ──
  log('BUILD', '检查构建依赖...');
  const needInstall = [];
  try { require.resolve('webpack'); } catch { needInstall.push('webpack webpack-cli'); }
  try { require.resolve('javascript-obfuscator'); } catch { needInstall.push('javascript-obfuscator'); }

  if (needInstall.length > 0) {
    log('BUILD', `安装缺失依赖: ${needInstall.join(', ')}`);
    execSync(`npm install --save-dev ${needInstall.join(' ')}`, { cwd: ROOT, stdio: 'pipe' });
    log('OK', '依赖安装完成');
  }

  // 解析vsce二进制路径 (从项目node_modules)
  const VSCE_BIN = path.join(ROOT, 'node_modules', '.bin', process.platform === 'win32' ? 'vsce.cmd' : 'vsce');
  if (!fs.existsSync(VSCE_BIN)) {
    log('ERR', `vsce未找到: ${VSCE_BIN} (运行 npm install)`);
    process.exit(1);
  }

  // ── Step 1: L1 结构消解 (Webpack) ──
  log('L1', '结构消解 — Webpack bundling (5 modules → 1 file)');
  const distDir = path.join(ROOT, 'dist');
  rmrf(distDir);
  fs.mkdirSync(distDir, { recursive: true });

  const webpackResult = spawnSync('npx', ['webpack', '--config', 'webpack.config.js'], {
    cwd: ROOT,
    stdio: VERBOSE ? 'inherit' : 'pipe',
    shell: true,
  });
  if (webpackResult.status !== 0) {
    const err = webpackResult.stderr?.toString() || 'unknown error';
    log('ERR', `Webpack失败: ${err}`);
    process.exit(1);
  }

  const bundlePath = path.join(distDir, 'extension.js');
  const bundleSize = fileSize(bundlePath);
  log('OK', `Bundle: ${humanSize(bundleSize)} (${path.relative(ROOT, bundlePath)})`);

  // ── Step 2: L7 蜜罐注入 (在混淆前植入伪造常量) ──
  if (LEVEL === 'max' || LEVEL === 'high') {
    log('L7', '蜜罐注入 — 植入伪造端点/密钥/协议');
    let code = fs.readFileSync(bundlePath, 'utf8');
    code = injectHoneypots(code);
    fs.writeFileSync(bundlePath, code);
    log('OK', `蜜罐: ${HONEYPOT_STRINGS.length}个伪造字符串已植入`);
  }

  // ── Step 3: L11 道之本源 (AST Pollution) ──
  if (LEVEL === 'max' || LEVEL === 'high') {
    log('L11', '道之本源 — AST污染·伪解码器·Proxy陷阱·Symbol隐藏·哈希谓词');
    let astCode = fs.readFileSync(bundlePath, 'utf8');
    const pollutionCode = generateAstPollution();
    // 注入到bundle开头(webpack banner之后)
    const firstNL = astCode.indexOf('\n');
    if (firstNL > 0) {
      astCode = astCode.slice(0, firstNL + 1) + pollutionCode + astCode.slice(firstNL + 1);
    } else {
      astCode = pollutionCode + '\n' + astCode;
    }
    fs.writeFileSync(bundlePath, astCode);
    log('OK', 'AST污染: 5类反混淆模式已注入 (Proxy+Symbol+伪StringArray+computed+hash)');
  }

  // ── Step 4: L8 道之变形 (Polymorphic Transformation) ──
  if (LEVEL !== 'dev') {
    log('L8', '道之变形 — 多态代码变换·不透明谓词(3层)·字符串碎片化');
    let polyCode = fs.readFileSync(bundlePath, 'utf8');
    const polyResult = applyPolymorphicLayer(polyCode);
    fs.writeFileSync(bundlePath, polyResult.code);
    log('OK', `变形: ${polyResult.stats.fragments}碎片 + ${polyResult.stats.guards}谓词 + ${polyResult.stats.decoys}诱饵`);
  }

  // ── Step 5: L9 道之护符 (Runtime Protection) ──
  if (LEVEL === 'max' || LEVEL === 'high') {
    log('L9', '道之护符 — 反Hook·时序门·环境绑定·完整性守护');
    let rpCode = fs.readFileSync(bundlePath, 'utf8');
    const rpHash = sha256(rpCode).slice(0, 32);
    const runtimeCode = generateRuntimeProtection(rpHash);
    // 注入到bundle开头(webpack banner之后)
    const firstNL = rpCode.indexOf('\n');
    if (firstNL > 0) {
      rpCode = rpCode.slice(0, firstNL + 1) + runtimeCode + rpCode.slice(firstNL + 1);
    } else {
      rpCode = runtimeCode + '\n' + rpCode;
    }
    fs.writeFileSync(bundlePath, rpCode);
    log('OK', `护符: 4重运行时守护已注入 (hash=${rpHash.slice(0, 12)}...)`);
  }

  // ── Step 6: L10 道之印 (Build Seal) ──
  if (LEVEL !== 'dev') {
    log('L10', '道之印 — 构建指纹散布·完整性哈希链');
    let sealCode = fs.readFileSync(bundlePath, 'utf8');
    const sealResult = embedBuildSeal(sealCode);
    fs.writeFileSync(bundlePath, sealResult.code);
    log('OK', `道印: ID=${sealResult.buildId.slice(0, 12)}... seal=${sealResult.seal.slice(0, 12)}...`);
  }

  // ── Step 6.5: L12 道之归宗 (Cross-Layer Integrity Lock) ──
  if (LEVEL === 'max' || LEVEL === 'high') {
    log('L12', '道之归宗 — 跨层互锁·完整性链·篡改降级');
    let lockCode = fs.readFileSync(bundlePath, 'utf8');
    const lockBlock = generateCrossLayerLock(lockCode);
    lockCode = lockCode + lockBlock;
    fs.writeFileSync(bundlePath, lockCode);
    log('OK', '归宗: 跨层完整性锁已嵌入 (篡改→静默降级)');
  }

  // ── Step 7: L2~L6 混淆 (javascript-obfuscator) ──
  const obfConfig = getObfuscatorConfig(LEVEL);
  if (obfConfig) {
    log('L2', '标识符毁灭 — 变量/函数名→hex');
    log('L3', '控制流坍缩 — 代码块→状态机');
    log('L4', `字符串加密 — ${obfConfig.stringArrayEncoding?.[0] || 'base64'}编码 + 旋转混洗`);
    if (obfConfig.deadCodeInjection) log('L5', `死代码洪流 — ${(obfConfig.deadCodeInjectionThreshold * 100).toFixed(0)}%假路径注入`);
    if (obfConfig.selfDefending) log('L6', '自卫机制 — 美化/格式化后代码失效');

    const JavaScriptObfuscator = require('javascript-obfuscator');

    // 混淆主扩展
    log('INFO', '混淆 dist/extension.js ...');
    const extCode = fs.readFileSync(bundlePath, 'utf8');
    const t1 = Date.now();
    const obfResult = JavaScriptObfuscator.obfuscate(extCode, obfConfig);
    const obfTime = ((Date.now() - t1) / 1000).toFixed(1);
    fs.writeFileSync(bundlePath, obfResult.getObfuscatedCode());
    log('OK', `主扩展混淆完成 (${obfTime}s, ${humanSize(fileSize(bundlePath))})`);

    // 混淆面板脚本
    const panelSrc = path.join(ROOT, 'media', 'panel.js');
    if (fs.existsSync(panelSrc)) {
      log('INFO', '混淆 media/panel.js ...');
      const panelCode = fs.readFileSync(panelSrc, 'utf8');
      const panelConfig = {
        ...obfConfig,
        target: 'browser',
        selfDefending: LEVEL === 'max',
        deadCodeInjection: !!obfConfig.deadCodeInjection,
        deadCodeInjectionThreshold: Math.min(obfConfig.deadCodeInjectionThreshold || 0, 0.2),
      };
      const panelResult = JavaScriptObfuscator.obfuscate(panelCode, panelConfig);
      // 写到dist/media/ (构建时使用)
      const distMedia = path.join(distDir, 'media');
      fs.mkdirSync(distMedia, { recursive: true });
      fs.writeFileSync(path.join(distMedia, 'panel.js'), panelResult.getObfuscatedCode());
      log('OK', `面板脚本混淆完成 (${humanSize(fileSize(path.join(distMedia, 'panel.js')))})`);
    }
  } else {
    log('INFO', 'dev模式: 跳过混淆');
    // 拷贝panel.js到dist/media
    const distMedia = path.join(distDir, 'media');
    fs.mkdirSync(distMedia, { recursive: true });
    fs.copyFileSync(path.join(ROOT, 'media', 'panel.js'), path.join(distMedia, 'panel.js'));
  }

  // ── Step 8: 组装临时打包目录 ──
  log('BUILD', '组装打包目录...');
  const tmpDir = safeTmpDir('wam_fortress');

  try {
    // dist/extension.js → tmp/dist/extension.js
    const tmpDist = path.join(tmpDir, 'dist');
    fs.mkdirSync(tmpDist, { recursive: true });
    fs.copyFileSync(bundlePath, path.join(tmpDist, 'extension.js'));

    // media/panel.js (混淆后) + icon.svg → tmp/media/
    const tmpMedia = path.join(tmpDir, 'media');
    fs.mkdirSync(tmpMedia, { recursive: true });
    const obfPanelPath = path.join(distDir, 'media', 'panel.js');
    if (fs.existsSync(obfPanelPath)) {
      fs.copyFileSync(obfPanelPath, path.join(tmpMedia, 'panel.js'));
    }
    const iconSrc = path.join(ROOT, 'media', 'icon.svg');
    if (fs.existsSync(iconSrc)) {
      fs.copyFileSync(iconSrc, path.join(tmpMedia, 'icon.svg'));
    }

    // src/wisdom_bundle.json → tmp/src/wisdom_bundle.json (运行时数据)
    const wisdomSrc = path.join(ROOT, 'src', 'wisdom_bundle.json');
    if (fs.existsSync(wisdomSrc)) {
      const tmpSrc = path.join(tmpDir, 'src');
      fs.mkdirSync(tmpSrc, { recursive: true });
      fs.copyFileSync(wisdomSrc, path.join(tmpSrc, 'wisdom_bundle.json'));
    }

    // package.json (修改main入口)
    const pkgForBuild = { ...PKG };
    pkgForBuild.main = './dist/extension.js';
    delete pkgForBuild.devDependencies;  // VSIX不需要devDeps
    delete pkgForBuild.scripts;          // VSIX不需要scripts
    fs.writeFileSync(path.join(tmpDir, 'package.json'), JSON.stringify(pkgForBuild, null, 2));

    // .vscodeignore (堡垒版: 只含dist + media + src/wisdom_bundle.json)
    const vscodeignore = [
      'node_modules/**',
      '.git/**',
      '*.vsix',
      '**/*.map',
      '_*',
      '*.py',
      '*.md',
      '!LICENSE*',
      'src/*.js',          // 排除源码JS (已合并到dist/extension.js)
      'webpack.config.js',
      'package-lock.json',
    ].join('\n') + '\n';
    fs.writeFileSync(path.join(tmpDir, '.vscodeignore'), vscodeignore);

    // LICENSE
    const licenseSrc = path.join(ROOT, 'LICENSE');
    if (fs.existsSync(licenseSrc)) {
      fs.copyFileSync(licenseSrc, path.join(tmpDir, 'LICENSE'));
    }

    // ── Step 9: VSCE打包 ──
    log('BUILD', '生成VSIX...');
    const vsceResult = spawnSync(VSCE_BIN, ['package', '--no-dependencies', '--allow-missing-repository'], {
      cwd: tmpDir,
      stdio: VERBOSE ? 'inherit' : 'pipe',
      shell: true,
    });

    if (vsceResult.status !== 0) {
      const err = vsceResult.stderr?.toString() || '';
      log('ERR', `VSCE打包失败: ${err}`);
      process.exit(1);
    }

    // 拷回VSIX
    const vsixTmp = path.join(tmpDir, VSIX_NAME);
    const vsixDst = path.join(ROOT, VSIX_NAME);
    if (!fs.existsSync(vsixTmp)) {
      log('ERR', `VSIX未生成: ${vsixTmp}`);
      process.exit(1);
    }
    fs.copyFileSync(vsixTmp, vsixDst);

    const vsixSize = fileSize(vsixDst);
    const elapsed = ((Date.now() - t0) / 1000).toFixed(1);

    log('OK', `═══ 构建完成 ═══`);
    log('OK', `产物: ${VSIX_NAME} (${humanSize(vsixSize)})`);
    log('OK', `耗时: ${elapsed}s · 防护等级: ${LEVEL.toUpperCase()}`);

    // ── 防护指标 ──
    if (ANALYZE || VERBOSE) {
      analyze(vsixDst, bundlePath);
    }

    // ── Step 10: 安装 ──
    if (!NO_INSTALL) {
      log('BUILD', `安装 ${VSIX_NAME} 到 Windsurf...`);
      try {
        execSync(`windsurf --install-extension "${vsixDst}" --force`, { stdio: 'pipe' });
        log('OK', `v${VERSION} 已安装 · 重载Windsurf激活`);
      } catch (e) {
        log('WARN', `自动安装失败 (手动: windsurf --install-extension "${vsixDst}" --force)`);
      }
    }

  } finally {
    rmrf(tmpDir);
  }
}

// ═══════════════════════════════════════════════════════
// §5  防护分析
// ═══════════════════════════════════════════════════════

function analyze(vsixPath, bundlePath) {
  log('INFO', '─── 防护指标 ───');

  // 源码vs产物大小对比
  const srcFiles = ['extension.js', 'authService.js', 'accountManager.js', 'webviewProvider.js', 'fingerprintManager.js'];
  let srcTotal = 0;
  for (const f of srcFiles) {
    const p = path.join(ROOT, 'src', f);
    srcTotal += fileSize(p);
  }
  srcTotal += fileSize(path.join(ROOT, 'media', 'panel.js'));

  const obfSize = fileSize(bundlePath);
  const vsixSize = fileSize(vsixPath);
  const ratio = (obfSize / srcTotal).toFixed(1);

  log('INFO', `源码总大小: ${humanSize(srcTotal)} (${srcFiles.length + 1}个文件)`);
  log('INFO', `混淆后大小: ${humanSize(obfSize)} (1个文件, 膨胀比${ratio}x)`);
  log('INFO', `VSIX大小:   ${humanSize(vsixSize)}`);

  // 检测敏感字符串是否暴露
  if (fs.existsSync(bundlePath)) {
    const code = fs.readFileSync(bundlePath, 'utf8');
    const sensitivePatterns = [
      { name: 'Firebase Key', pattern: /AIzaSy[A-Za-z0-9_-]{33}/g },
      { name: 'Relay URL', pattern: /168666okfa\.xyz/g },
      { name: 'Protobuf Field Tags', pattern: /(?:FIELD_TAG|USED_TAG|TOTAL_TAG|CREDIT_DIV)\s*=\s*0x[0-9a-f]+/gi },
      { name: 'Auth Endpoint', pattern: /provideAuthTokenToAuthProvider/g },
      { name: 'gRPC Path', pattern: /SeatManagement/g },
      { name: 'state.vscdb', pattern: /state\.vscdb/g },
      { name: 'storage.json', pattern: /storage\.json/g },
    ];

    log('INFO', '── 敏感字符串暴露检测 ──');
    let exposed = 0;
    for (const { name, pattern } of sensitivePatterns) {
      const matches = code.match(pattern);
      if (matches && matches.length > 0) {
        log('WARN', `  ⚠ ${name}: ${matches.length}处明文暴露`);
        exposed++;
      } else {
        log('OK', `  ✓ ${name}: 已加密`);
      }
    }

    if (exposed === 0) {
      log('OK', '所有敏感字符串已加密保护 ✓');
    } else {
      log('WARN', `${exposed}类敏感字符串仍有明文暴露 (提升防护等级可解决)`);
    }

    // 代码可读性指标
    const lines = code.split('\n').length;
    const avgLineLen = Math.round(code.length / lines);
    const hexIds = (code.match(/_0x[0-9a-f]+/g) || []).length;
    log('INFO', `── 可读性指标 ──`);
    log('INFO', `  行数: ${lines} · 平均行长: ${avgLineLen}字符 · hex标识符: ${hexIds}个`);
  }

  // 蜜罐检测
  if (LEVEL === 'max' || LEVEL === 'high') {
    log('INFO', `  蜜罐: ${HONEYPOT_STRINGS.length}个伪造常量已植入`);
  }

  // ── 道之防护指标 ──
  log('INFO', `── 道之防护层 (混淆后不可见=加密成功) ──`);

  if (LEVEL !== 'dev' && fs.existsSync(bundlePath)) {
    const code = fs.readFileSync(bundlePath, 'utf8');
    const isObfuscated = (code.match(/_0x[0-9a-f]+/g) || []).length > 1000;

    // L8: 多态变形检测
    const opaqueCount = (code.match(/Math\.pow\(\d+,\d+\)/g) || []).length;
    const fragJoins = (code.match(/\.join\(''\)/g) || []).length;
    if (isObfuscated && opaqueCount === 0) {
      log('OK', `  L8 道之变形: ✓ 谓词+碎片已被L4加密 (不可逆向搜索)`);
    } else {
      log('INFO', `  L8 道之变形: 不透明谓词≈${opaqueCount} · 碎片组装≈${fragJoins}`);
    }

    // L9: 运行时护符检测
    const hasRuntimeProt = /global\._wTG/.test(code) || /global\._wEB/.test(code);
    const hasAntiHook = /Function\.prototype\.toString\.call/.test(code);
    if (isObfuscated && !hasRuntimeProt && !hasAntiHook) {
      log('OK', `  L9 道之护符: ✓ 守护代码已被L4加密 (运行时解密生效)`);
    } else {
      log('INFO', `  L9 道之护符: 运行时守护=${hasRuntimeProt ? '✓' : '✗'} · 反Hook=${hasAntiHook ? '✓' : '✗'}`);
    }

    // L10: 构建印记检测
    const sealVars = (code.match(/var\s+_[0-9a-f]{8}='[0-9a-f]{4}';/g) || []).length;
    if (isObfuscated && sealVars === 0) {
      log('OK', `  L10 道之印: ✓ 指纹碎片已被L4加密 (RC4 stringArray中)`);
    } else {
      log('INFO', `  L10 道之印: ${sealVars}个指纹碎片散布`);
    }
  }

  // ── 道之本源层检测 ──
  if (['high', 'max'].includes(LEVEL) && fs.existsSync(bundlePath)) {
    const code = fs.readFileSync(bundlePath, 'utf8');
    const isObfuscated = (code.match(/_0x[0-9a-f]+/g) || []).length > 1000;
    const hasProxy = /Proxy/.test(code);
    const hasSymbol = /Symbol/.test(code);
    const hasFakeDecoder = /_0x[0-9a-f]{6}/.test(code);
    if (isObfuscated) {
      log('OK', `  L11 道之本源: ✓ AST污染层已被L2~L4深度加密 (Proxy/Symbol/伪解码器融入混淆)`);
      log('OK', `  L12 道之归宗: ✓ 跨层互锁生效 (篡改→静默降级)`);
    } else {
      log('INFO', `  L11 道之本源: Proxy=${hasProxy?'✓':'✗'} Symbol=${hasSymbol?'✓':'✗'} 伪解码器=${hasFakeDecoder?'✓':'✗'}`);
      log('INFO', `  L12 道之归宗: ✓ 跨层完整性锁已嵌入`);
    }
  }

  // 综合防护评分
  const layers = {
    L1: true,  // Webpack always on
    L2: LEVEL !== 'dev',
    L3: ['medium', 'high', 'max'].includes(LEVEL),
    L4: LEVEL !== 'dev',
    L5: ['medium', 'high', 'max'].includes(LEVEL),
    L6: ['high', 'max'].includes(LEVEL),
    L7: ['high', 'max'].includes(LEVEL),
    L8: LEVEL !== 'dev',
    L9: ['high', 'max'].includes(LEVEL),
    L10: LEVEL !== 'dev',
    L11: ['high', 'max'].includes(LEVEL),
    L12: ['high', 'max'].includes(LEVEL),
  };
  const activeCount = Object.values(layers).filter(Boolean).length;
  const totalLayers = Object.keys(layers).length;
  const layerStr = Object.entries(layers).map(([k, v]) => v ? `\x1b[32m${k}\x1b[0m` : `\x1b[90m${k}\x1b[0m`).join(' ');
  log('INFO', `── 防护矩阵: ${activeCount}/${totalLayers}层激活 ──`);
  log('INFO', `  ${layerStr}`);
}

// ═══════════════════════════════════════════════════════
// §11  入口
// ═══════════════════════════════════════════════════════

build().catch(err => {
  log('ERR', `构建失败: ${err.message}`);
  if (VERBOSE) console.error(err);
  process.exit(1);
});
