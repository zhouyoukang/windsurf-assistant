/**
 * 无感号池引擎 v1.0.0
 *
 * 道: 用户是号池，不是单个账号。切换必须在rate limit之前发生。
 *
 * 架构:
 *   认证: Firebase → idToken → provideAuthTokenToAuthProvider → session
 *   额度: QUOTA(daily%+weekly%) | CREDITS(固定积分) → effective=min(D,W)
 *   指纹: 6个ID轮转(切号前写入→LS重启读取=热重置)
 *   注入: S0=idToken → S1=OTAT → S2=apiKey → S3=DB直写
 *   预防: L5 gRPC容量探测(CheckUserMessageRateLimit)为本，辅以阈值/斜率/限流检测
 *
 * 详细版本演进见 FIRST_PRINCIPLES.md
 */
const vscode = require("vscode");
const { AccountManager } = require("./accountManager");
const { AuthService } = require("./authService");
const { openAccountPanel, AccountViewProvider } = require("./webviewProvider");
const {
  readFingerprint,
  resetFingerprint,
  ensureComplete: ensureFingerprintComplete,
  hotVerify,
} = require("./fingerprintManager");
const fs = require("fs");
const path = require("path");
const os = require("os");
const http = require("http");
const { execSync } = require("child_process");
const { runClean: _diskClean, setLogger: _diskSetLogger } = require("./diskCleaner");

// ═══ 号池状态 ═══
let statusBar, am, auth, _panelProvider, _panel;
let _activeIndex = -1; // 当前活跃账号
let _switching = false; // 切换锁
let _poolTimer = null; // 号池引擎定时器
let _lastQuota = null; // 上次活跃账号额度(变化检测)
let _lastCheckTs = 0; // 上次检查时间戳
let _boostUntil = 0; // 加速模式截止
let _switchCount = 0; // 本会话切换次数
let _discoveredAuthCmd = null; // 缓存发现的注入命令
let _outputChannel = null; // 结构化日志输出通道
let _eventLog = []; // 事件日志缓冲 [{ts, level, msg}]
const MAX_EVENT_LOG = 200; // 最大日志条数
let _urgentSwitch = false; // v7.4: 紧急切换模式(rate limit触发时最小延迟切换)

// ═══ v7.5 Gate 4: Account-Tier Rate Limit Detection ═══
// 根因: Trial/Free账号有独立于Quota和Per-Model的硬性小时消息上限
// 证据: "Permission denied: Rate limit exceeded...no credits were used...upgrade to Pro...try again in about an hour"
// 关键区分: "no credits were used" + "upgrade to Pro" = 层级硬限, 非配额/非模型级
// 对策: 跳过模型轮转(无效), 直接账号切换 + 3600s冷却
const TIER_RL_RE = /rate\s*limit\s*exceeded[\s\S]*?no\s*credits\s*were\s*used/i;
const UPGRADE_PRO_RE = /upgrade\s*to\s*a?\s*pro/i;
const ABOUT_HOUR_RE = /try\s*again\s*in\s*about\s*an?\s*hour/i;
const MODEL_UNREACHABLE_RE = /model\s*provider\s*unreachable/i;
const PROVIDER_ERROR_RE = /provider.*(?:error|unavailable|unreachable)|(?:error|unavailable|unreachable).*provider/i;
const HOUR_WINDOW = 3600000; // 1小时滑动窗口
const TIER_MSG_CAP_ESTIMATE = 25; // Trial账号预估小时消息上限(保守)
const TIER_CAP_WARN_RATIO = 0.7; // 达到上限70%即预防
let _hourlyMsgLog = []; // [{ts}] 每小时消息追踪(用于Gate 4预测)
let _tierRateLimitCount = 0; // 本会话Gate 4触发次数

// ═══ Watchdog: 最后防线 — 所有检测层失效时的兜底切换 ═══
// 根因: L1(死代码)+L2(无法hook)+L3(仅quota)+L4(可能不写)+L5(可能失败) = 全盲窗口
// 看门狗: 追踪最后一次成功容量确认时间,超过阈值→预防性切号
const WATCHDOG_TIMEOUT = 90000; // 90s无成功探测→触发看门狗
const WATCHDOG_CHECK_INTERVAL = 20000; // 20s检查
let _lastSuccessfulProbe = Date.now(); // 上次成功容量确认时间
let _watchdogSwitchCount = 0; // 看门狗触发切号次数

// ═══ 多窗口协调 (v6.3 P0) ═══
const WINDOW_STATE_FILE = "wam-window-state.json";
const WINDOW_HEARTBEAT_MS = 30000; // 30s心跳
const WINDOW_DEAD_MS = 90000; // 90s无心跳=死亡
let _windowId = null; // 本窗口唯一ID
let _windowTimer = null; // 心跳定时器

const POLL_NORMAL = 45000; // 正常轮询 45s
const POLL_BOOST = 8000; // 加速轮询 8s (v6.2: 从12s降至8s)
const POLL_BURST = 3000; // 并发burst轮询 3s (v6.4: 多Tab场景)
const BOOST_DURATION = 300000; // 加速持续 5min (v6.2: 从3min延至5min)
const PREEMPTIVE_THRESHOLD = 15; // 预防性切换底线: daily%≤15即切(硬编码，不受用户配置影响)
const SLOPE_WINDOW = 5; // 斜率预测窗口(样本数)
const SLOPE_HORIZON = 300000; // 预测视野5min(ms)
let _quotaHistory = []; // [{ts, remaining}] 用于斜率预测

// ═══ 并发Tab感知 (v6.4 P0: 解决单窗口多Tab并发消息速率限流的核心矛盾) ═══
// 根因: 5个Cascade Tab共享1个账号session，并发请求形成burst → 触发消息速率限制(非配额耗尽)
// 截图证据: "Permission denied: Rate limit exceeded. no credits were used" = 请求被拦截在计费前
// 解法: 感知Tab数+追踪消息速率+动态调整轮询/冷却+主动轮转
const CONCURRENT_TAB_SAFE = 2; // 安全并发Tab数(超过即进入burst防护)
const MSG_RATE_WINDOW = 60000; // 消息速率统计窗口 60s
const MSG_RATE_LIMIT = 12; // 预估消息速率上限(条/分钟, 保守估计)
const BURST_DETECT_THRESHOLD = 0.7; // 速率达到上限的70%即触发预防
let _cascadeTabCount = 0; // 当前检测到的Cascade Tab数
let _msgRateLog = []; // [{ts}] 消息速率追踪(每次quota变化≈1次消息)
let _lastTabCheck = 0; // 上次Tab检测时间
const TAB_CHECK_INTERVAL = 10000; // Tab检测间隔 10s
let _burstMode = false; // 是否处于burst防护模式

// ═══ 全池实时监控 (v6.7 P0: 检测所有账号额度变化 + 活跃账号变动即切) ═══
let _allQuotaSnapshot = new Map(); // index → {remaining, checkedAt} 全池额度快照
let _lastFullScanTs = 0; // 上次全池扫描时间戳
let _lastReactiveSwitchTs = 0; // 上次响应式切换时间戳
const FULL_SCAN_INTERVAL = 300000; // 全池扫描间隔 300s (v6.8: 从90s放宽，减少API压力)
const REACTIVE_SWITCH_CD = 10000; // 响应式切换冷却 10s (v7.4: 从30s收紧，加速响应)
const REACTIVE_DROP_MIN = 5; // 响应式切换最小降幅阈值 (额度降>5%才触发，避免微波动)

// ═══ v7.0 热重置引擎 (Hot Reset Engine) ═══
// 核心洞察: provideAuthTokenToAuthProvider → LS重启 → LS在启动时读取机器码
// 如果在注入BEFORE轮转指纹, LS重启自然拿到新ID = 热重置, 无需重启Windsurf
// 旧流程(v6.9): 注入 → LS重启(读旧ID) → 轮转指纹(写新ID到磁盘, 但LS已用旧ID)
// 新流程(v7.0): 轮转指纹(写新ID) → 注入 → LS重启(读新ID!) → 验证 = 热重置完成
let _lastRotatedIds = null; // 最近一次轮转生成的新ID (用于热验证)
let _hotResetCount = 0; // 本会话热重置成功次数
let _hotResetVerified = 0; // 本会话热重置已验证次数
// 积分速度追踪器 (v7.0: 检测高速消耗 → 主动触发热重置+切号)
const VELOCITY_WINDOW = 120000; // 速度计算窗口 120s
const VELOCITY_THRESHOLD = 10; // 速度阈值: 120s内降>10% = 高速消耗
let _velocityLog = []; // [{ts, remaining}] 速度追踪样本

// ═══ Per-Model Rate Limit Breakthrough Engine (Opus Guard) ═══
// 根因: 服务端对每个(apiKey, modelUid)维护独立滑动窗口消息速率桶
// Thinking模型分级预算 — 根据模型tier动态调整budget
//   - Thinking 1M: ACU=10x, 服务端桶≈3条/20min → Budget=1(每条即切!)
//   - Thinking:    ACU=8x,  服务端桶≈4条/20min → Budget=2
//   - Regular:     ACU=6x,  服务端桶≈5条/20min → Budget=3
// 核心洞察: L5探测返回-1/-1(Trial盲探) → 唯一可靠防线=自主计数+分级预算
//          Opus 6变体共享同一服务端桶(同底层API) → 变体轮转=浪费时间
const OPUS_VARIANTS = [
  'claude-opus-4-6-thinking-1m',
  'claude-opus-4-6-thinking',
  'claude-opus-4-6-1m',
  'claude-opus-4-6',
  'claude-opus-4-6-thinking-fast',
  'claude-opus-4-6-fast',
];
const SONNET_FALLBACK = 'claude-sonnet-4-6-thinking-1m';
let _currentModelUid = null; // 当前活跃模型UID (从windsurfConfigurations读取)
let _modelRateLimitCount = 0; // 本会话per-model rate limit触发次数
let _lastModelSwitch = 0; // 上次模型切换时间戳

// ═══ Layer 8: Opus消息预算守卫 (Thinking-Tier-Aware Prevention) ═══
// 实测: Opus Thinking 1M桶容量≈3条/20min → Resets in: 20m3s (1203s)
//       Opus Thinking桶容量≈4条/20min → Resets in: ~20min
//       Opus Regular桶容量≈5条/20min → Resets in: ~22min
// 分级预算 — Thinking 1M=1条即切, Thinking=2条, Regular=3条
const OPUS_THINKING_1M_BUDGET = 1; // Thinking 1M: 每条消息后立即切号!
const OPUS_THINKING_BUDGET = 2;    // Thinking: 2条后切号
const OPUS_REGULAR_BUDGET = 3;     // Regular Opus: 3条后切号
const OPUS_MSG_BUDGET = 3;         // 默认预算(兼容旧代码路径)
const OPUS_BUDGET_WINDOW = 1200000; // 20分钟滑动窗口(ms) — 匹配实测Opus Thinking 1M 20m3s
const OPUS_PREEMPT_RATIO = 1.0;    // 达到预算100%即切(分级预算已足够保守)
const OPUS_COOLDOWN_DEFAULT = 1500; // Opus per-model默认冷却1500s(25min) — 匹配实测
const CAPACITY_CHECK_THINKING = 3000; // Thinking模型L5探测间隔3s(更快检测hasCapacity=false)
let _opusMsgLog = new Map(); // accountIndex → [{ts}] per-account Opus消息记录
let _opusGuardSwitchCount = 0; // 本会话Opus守卫主动切号次数

/** 读取当前活跃模型UID (从state.vscdb windsurfConfigurations/codeium.windsurf) */
function _readCurrentModelUid() {
  try {
    if (!auth) return _currentModelUid;
    const cw = auth.readCachedValue && auth.readCachedValue('codeium.windsurf');
    if (cw) {
      const d = JSON.parse(cw);
      const uids = d['windsurf.state.lastSelectedCascadeModelUids'];
      if (Array.isArray(uids) && uids.length > 0) {
        _currentModelUid = uids[0];
        return _currentModelUid;
      }
    }
  } catch {}
  // v8.0 fallback: 如果state.vscdb读取失败但有缓存值则返回缓存
  // 防止_currentModelUid为null导致Gate 3 handler被跳过
  return _currentModelUid || 'claude-opus-4-6-thinking-1m'; // 默认假设Opus(保守策略)
}

/** 检测modelUid是否属于Opus家族 */
function _isOpusModel(uid) {
  return uid && uid.toLowerCase().includes('opus');
}

/** 检测是否为Thinking模型(更高token成本, 更低rate limit) */
function _isThinkingModel(uid) {
  return uid && uid.toLowerCase().includes('thinking');
}

/** 检测是否为Thinking 1M模型(最高成本, 最低rate limit) */
function _isThinking1MModel(uid) {
  if (!uid) return false;
  const u = uid.toLowerCase();
  return u.includes('thinking') && u.includes('1m');
}

/** 根据模型tier获取动态预算 — 道法自然, 因材施教 */
function _getModelBudget(uid) {
  if (!uid || !_isOpusModel(uid)) return OPUS_REGULAR_BUDGET;
  if (_isThinking1MModel(uid)) return OPUS_THINKING_1M_BUDGET; // 1条即切!
  if (_isThinkingModel(uid)) return OPUS_THINKING_BUDGET;       // 2条后切
  return OPUS_REGULAR_BUDGET;                                   // 3条后切
}

/** v8.0: 追踪Opus消息 — 在quota%下降且当前模型=Opus时调用 */
function _trackOpusMsg(accountIndex) {
  if (accountIndex < 0) return;
  if (!_opusMsgLog.has(accountIndex)) _opusMsgLog.set(accountIndex, []);
  _opusMsgLog.get(accountIndex).push({ ts: Date.now() });
  // 清理过期记录
  const cutoff = Date.now() - OPUS_BUDGET_WINDOW;
  _opusMsgLog.set(accountIndex, _opusMsgLog.get(accountIndex).filter(m => m.ts > cutoff));
}

/** v8.0: 获取当前账号在窗口内的Opus消息数 */
function _getOpusMsgCount(accountIndex) {
  if (accountIndex < 0 || !_opusMsgLog.has(accountIndex)) return 0;
  const cutoff = Date.now() - OPUS_BUDGET_WINDOW;
  const valid = _opusMsgLog.get(accountIndex).filter(m => m.ts > cutoff);
  return valid.length;
}

/** 判断是否达到Opus消息预算 — 分级预算, Thinking 1M=1条即切 */
function _isNearOpusBudget(accountIndex) {
  const modelUid = _currentModelUid || _readCurrentModelUid();
  const budget = _getModelBudget(modelUid);
  const count = _getOpusMsgCount(accountIndex);
  return count >= budget; // budget=1时, 1条消息后即返回true → 立即切号
}

/** v8.0: 切号后重置该账号的Opus消息计数 */
function _resetOpusMsgLog(accountIndex) {
  _opusMsgLog.delete(accountIndex);
}

// ═══ Layer 5: Active Rate Limit Capacity Probe ═══
// 根因突破: Windsurf workbench的rate limit分类器是死代码(GZt=Z=>!1)
//          → 不设置任何context key → WAM的4层检测全部盲区
// 解法: 主动调用CheckUserMessageRateLimit gRPC端点 → 获取精确容量数据 → 在用户消息失败前切号
// 逆向自 @exa/chat-client: 此端点是Cascade发送每条消息前的预检
// 返回: { hasCapacity, messagesRemaining, maxMessages, resetsInSeconds }
const CAPACITY_CHECK_INTERVAL = 45000; // 正常容量检查间隔 45s
const CAPACITY_CHECK_FAST = 15000; // 活跃使用时快速检查 15s
const CAPACITY_PREEMPT_REMAINING = 2; // 剩余≤2条消息时提前切号
let _cachedApiKey = null; // 缓存当前session apiKey
let _cachedApiKeyTs = 0; // apiKey缓存时间戳
const APIKEY_CACHE_TTL = 120000; // apiKey缓存2min(注入后刷新)
let _lastCapacityCheck = 0; // 上次容量检查时间戳
let _lastCapacityResult = null; // 上次容量检查结果
let _capacityProbeCount = 0; // 本会话容量探测次数
let _capacityProbeFailCount = 0; // 连续失败次数(用于backoff)
let _capacitySwitchCount = 0; // 本会话因容量不足触发的切号次数
let _realMaxMessages = -1; // 服务端返回的真实消息上限(替代TIER_MSG_CAP_ESTIMATE)

// ═══ v7.5 Gate 4: Account-Tier Rate Limit Engine ═══

/** 分类限流类型 — 四重闸门路由
 *  Gate 1/2: quota (D%/W%耗尽) → 账号切换 + 等日/周重置
 *  Gate 3: per_model (单模型桶满) → 模型变体轮转 → 账号切换 → 降级
 *  Gate 4: tier_cap (层级硬限) → 跳过模型轮转, 直接账号切换 + 3600s
 */
function _classifyRateLimit(errorText, contextKey) {
  if (!errorText && !contextKey) return 'unknown';
  const text = (errorText || '') + ' ' + (contextKey || '');
  // "Model provider unreachable" → 立即切号(可能是账号被封或模型访问受限)
  if (MODEL_UNREACHABLE_RE.test(text) || PROVIDER_ERROR_RE.test(text)) {
    return 'tier_cap'; // 当作tier_cap处理：直接换号
  }
  // Gate 4 特征: "no credits were used" + "upgrade to Pro" 或 "about an hour"
  if (TIER_RL_RE.test(text) || (UPGRADE_PRO_RE.test(text) && /rate\s*limit/i.test(text))) {
    return 'tier_cap';
  }
  if (ABOUT_HOUR_RE.test(text)) return 'tier_cap';
  // Gate 3 特征: "for this model" 或 模型级context key
  if (/for\s*this\s*model/i.test(text) || /model.*rate.*limit/i.test(text)) {
    return 'per_model';
  }
  if (contextKey && (contextKey.includes('modelRateLimited') || contextKey.includes('messageRateLimited'))) {
    return 'per_model';
  }
  // Gate 1/2 特征: "quota" 相关
  if (/quota/i.test(text) && /exhaust|exceed/i.test(text)) return 'quota';
  if (contextKey && contextKey.includes('quota')) return 'quota';
  // v8.0: 当context key是通用限流(permissionDenied/rateLimited)且当前模型=Opus时
  // 高概率为per-model rate limit(Opus桶容量最小,最容易触发)
  // 防止这些通用key落入'unknown'导致Gate 3 handler被跳过
  if (contextKey && (contextKey.includes('permissionDenied') || contextKey.includes('rateLimited'))) {
    const model = _currentModelUid || _readCurrentModelUid();
    if (_isOpusModel(model)) return 'per_model';
  }
  return 'unknown';
}

/** 追踪每小时消息数(用于Gate 4预测) */
function _trackHourlyMsg() {
  _hourlyMsgLog.push({ ts: Date.now() });
  const cutoff = Date.now() - HOUR_WINDOW;
  _hourlyMsgLog = _hourlyMsgLog.filter(m => m.ts > cutoff);
}

/** 获取当前小时消息数 */
function _getHourlyMsgCount() {
  const cutoff = Date.now() - HOUR_WINDOW;
  return _hourlyMsgLog.filter(m => m.ts > cutoff).length;
}

/** 判断是否接近Gate 4层级上限 */
function _isNearTierCap() {
  return _getHourlyMsgCount() >= TIER_MSG_CAP_ESTIMATE * TIER_CAP_WARN_RATIO;
}

/** v7.5 Gate 4: 账号层级硬限处理 — 跳过模型轮转, 直接账号切换
 *  与_handlePerModelRateLimit的关键区别: Gate 4是账号级, 换模型无效 */
async function _handleTierRateLimit(context, resetSeconds) {
  _tierRateLimitCount++;
  const logPrefix = `[TIER_RL #${_tierRateLimitCount}]`;
  _logWarn('TIER_RL', `${logPrefix} Gate 4 账号层级硬限! hourly=${_getHourlyMsgCount()}, reset=${resetSeconds}s`);
  // 标记当前账号 — 3600s冷却("about an hour")
  const cooldown = resetSeconds || 3600;
  am.markRateLimited(_activeIndex, cooldown, {
    model: 'all',
    trigger: 'tier_rate_limit',
    type: 'tier_cap',
  });
  _pushRateLimitEvent({ type: 'tier_cap', trigger: 'tier_rate_limit', cooldown, hourlyMsgs: _getHourlyMsgCount() });
  // 直接账号轮转(跳过模型变体轮转 — 对Gate 4无效)
  _activateBoost();
  await _doPoolRotate(context, true);
  // 重置小时计数器(新账号从0开始)
  _hourlyMsgLog = [];
  return { action: 'tier_account_switch', cooldown };
}

/** v8.0 核心: Per-model rate limit 三级突破 (Opus优化版)
 *  Opus路径(v8.0): 跳过L1变体轮转(同桶无效) → 直接L2账号切换 → L3降级Sonnet
 *  非Opus路径: L1变体轮转 → L2账号切换 → L3降级
 *  核心洞察: Opus 6变体共享同一服务端rate limit桶(同底层API) → L1变体轮转=浪费5+秒
 */
async function _handlePerModelRateLimit(context, modelUid, resetSeconds) {
  _modelRateLimitCount++;
  const logPrefix = `[MODEL_RL #${_modelRateLimitCount}]`;
  // v8.0: Opus使用专用冷却时间(1500s/25min)，匹配实测22m50s
  const effectiveCooldown = _isOpusModel(modelUid) ? Math.max(resetSeconds || 0, OPUS_COOLDOWN_DEFAULT) : (resetSeconds || 1200);
  _logWarn('MODEL_RL', `${logPrefix} 检测到per-model rate limit: model=${modelUid}, resets=${resetSeconds}s, effectiveCooldown=${effectiveCooldown}s`);

  // 标记当前(account, model)为limited — Opus时标记所有变体(共享桶)
  if (_isOpusModel(modelUid)) {
    for (const variant of OPUS_VARIANTS) {
      am.markModelRateLimited(_activeIndex, variant, effectiveCooldown, { trigger: 'per_model_rate_limit' });
    }
    // v8.0: 重置该账号的Opus消息计数(已触发限流,计数器已失效)
    _resetOpusMsgLog(_activeIndex);
  } else {
    am.markModelRateLimited(_activeIndex, modelUid, effectiveCooldown, { trigger: 'per_model_rate_limit' });
  }

  // v8.0: Opus跳过L1变体轮转 — 6变体共享同一服务端桶，轮转浪费时间
  // 直接进入L2账号切换(不同apiKey = 不同桶 = 立即可用)
  if (_isOpusModel(modelUid)) {
    _logInfo('MODEL_RL', `${logPrefix} [OPUS_FAST] 跳过L1变体轮转(共享桶) → 直接L2账号切换`);
  } else {
    // === L1: 非Opus模型变体轮转(可能有效) ===
    const availableVariant = am.findAvailableModelVariant(_activeIndex, OPUS_VARIANTS);
    if (availableVariant && availableVariant !== modelUid) {
      _logInfo('MODEL_RL', `${logPrefix} L1: 同账号切换变体 ${modelUid} → ${availableVariant}`);
      await _switchModelUid(availableVariant);
      return { action: 'variant_switch', from: modelUid, to: availableVariant };
    }
  }

  // === L2: 换账号继续用同模型 (核心: 不同apiKey = 不同rate limit桶) ===
  const bestForModel = am.findBestForModel(modelUid, _activeIndex, PREEMPTIVE_THRESHOLD);
  if (bestForModel) {
    _logInfo('MODEL_RL', `${logPrefix} L2: 切换到账号#${bestForModel.index + 1}继续用${modelUid} (rem=${bestForModel.remaining})`);
    await _seamlessSwitch(context, bestForModel.index);
    _pushRateLimitEvent({ type: 'per_model', trigger: 'opus_guard_reactive', model: modelUid, cooldown: effectiveCooldown, switchTo: bestForModel.index + 1 });
    return { action: 'account_switch', to: bestForModel.index, model: modelUid };
  }
  _logInfo('MODEL_RL', `${logPrefix} L2: 所有账号的${modelUid}都已限流,尝试L3`);

  // === L3: 智能降级到Sonnet ===
  if (_isOpusModel(modelUid)) {
    _logWarn('MODEL_RL', `${logPrefix} L3: 所有账号Opus均已限流 → 降级到${SONNET_FALLBACK}`);
    await _switchModelUid(SONNET_FALLBACK);
    await _doPoolRotate(context, true);
    return { action: 'fallback', from: modelUid, to: SONNET_FALLBACK };
  }

  // 非Opus模型: 直接账号轮转
  await _doPoolRotate(context, true);
  return { action: 'account_rotate', model: modelUid };
}

/** 切换Windsurf当前模型UID (写入state.vscdb windsurfConfigurations) */
async function _switchModelUid(targetUid) {
  if (!targetUid || Date.now() - _lastModelSwitch < 5000) return false;
  _lastModelSwitch = Date.now();
  try {
    // 通过VS Code命令切换模型
    await vscode.commands.executeCommand('windsurf.cascadeSetModel', targetUid);
    _currentModelUid = targetUid;
    _logInfo('MODEL_RL', `模型已切换到: ${targetUid}`);
    return true;
  } catch (e1) {
    // 备用: 直接写state.vscdb
    try {
      if (auth && auth.writeModelSelection) {
        auth.writeModelSelection(targetUid);
        _currentModelUid = targetUid;
        _logInfo('MODEL_RL', `模型已切换(DB直写): ${targetUid}`);
        return true;
      }
    } catch {}
    _logWarn('MODEL_RL', `模型切换失败: ${targetUid}`, e1.message);
    return false;
  }
}

// ═══ 内嵌Hub Server (v7.2: VSIX内HTTP API + Token成本分析) ═══
const HUB_PORT = 9870;
let _hubServer = null;
const _ANTHROPIC = {
  "Claude Opus 4.6": { i: 5, o: 25 },
  "Claude Opus 4.6 1M": { i: 10, o: 37.5 },
  "Claude Opus 4.6 Thinking": { i: 5, o: 25 },
  "Claude Opus 4.6 Fast": { i: 5, o: 25 },
  "Claude Sonnet 4.6": { i: 3, o: 15 },
  "Claude Sonnet 4.6 1M": { i: 6, o: 22.5 },
  "Claude Sonnet 4.6 Thinking": { i: 3, o: 15 },
  "Claude Opus 4.5": { i: 5, o: 25 },
  "Claude Sonnet 4.5": { i: 3, o: 15 },
  "Claude Sonnet 4": { i: 3, o: 15 },
  "Claude Haiku 4.5": { i: 1, o: 5 },
  "Claude Opus 4.1": { i: 15, o: 75 },
};
const _ACU = {
  "Claude Opus 4.6": 6,
  "Claude Opus 4.6 1M": 10,
  "Claude Opus 4.6 Thinking": 8,
  "Claude Opus 4.6 Fast": 24,
  "Claude Sonnet 4.6": 4,
  "Claude Sonnet 4.6 1M": 12,
  "Claude Sonnet 4.6 Thinking": 6,
  "Claude Opus 4.5": 4,
  "Claude Sonnet 4.5": 2,
  "Claude Sonnet 4": 2,
  "Claude Haiku 4.5": 1,
  "SWE-1.5": 0,
  "SWE-1.5 Fast": 0.5,
};
const _CNY = 7.25,
  _XIANYU = 4.5;

function _tokenCost(model, inTok, outTok) {
  const p = _ANTHROPIC[model] || _ANTHROPIC["Claude Sonnet 4.6"];
  const ic = (inTok / 1e6) * p.i,
    oc = (outTok / 1e6) * p.o;
  return {
    model,
    input_cost: +ic.toFixed(4),
    output_cost: +oc.toFixed(4),
    total_usd: +(ic + oc).toFixed(4),
    total_cny: +((ic + oc) * _CNY).toFixed(2),
  };
}

function _startHubServer() {
  try {
    _hubServer = http.createServer((req, res) => {
      const url = new URL(req.url, `http://127.0.0.1:${HUB_PORT}`);
      const p = url.pathname.replace(/\/$/, "") || "/";
      const qs = Object.fromEntries(url.searchParams);
      const cors = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      };
      const json = (data, code = 200) => {
        const b = JSON.stringify(data);
        res.writeHead(code, { "Content-Type": "application/json", ...cors });
        res.end(b);
      };

      if (req.method === "OPTIONS") {
        res.writeHead(204, cors);
        return res.end();
      }

      if (p === "/health")
        return json({
          status: "ok",
          version: "1.0.0",
          port: HUB_PORT,
          accounts: am ? am.getAll().length : 0,
          activeIndex: _activeIndex,
        });

      if (p === "/api/pool/status") {
        const pool = am ? am.getPoolStats(PREEMPTIVE_THRESHOLD) : {};
        pool.activeIndex = _activeIndex;
        pool.switchCount = _switchCount;
        const _hubModel = _currentModelUid || _readCurrentModelUid();
        const _hubBudget = _getModelBudget(_hubModel);
        pool.opusGuard = {
          switchCount: _opusGuardSwitchCount,
          currentModel: _hubModel,
          isOpus: _isOpusModel(_hubModel),
          isThinking: _isThinkingModel(_hubModel),
          isThinking1M: _isThinking1MModel(_hubModel),
          opusMsgsInWindow: _activeIndex >= 0 ? _getOpusMsgCount(_activeIndex) : 0,
          budget: _hubBudget,
          budgetTier: _isThinking1MModel(_hubModel) ? 'T1M' : _isThinkingModel(_hubModel) ? 'T' : 'R',
          windowMs: OPUS_BUDGET_WINDOW,
          cooldownDefault: OPUS_COOLDOWN_DEFAULT,
          modelRateLimits: am ? am.getModelRateLimits() : [],
          perModelGuard: true,
        };
        if (am && _activeIndex >= 0) {
          const a = am.get(_activeIndex);
          pool.activeEmail = a?.email;
          pool.activeRemaining = am.effectiveRemaining(_activeIndex);
          pool.activePlanDays = am.getPlanDaysRemaining(_activeIndex);
          pool.activeUrgency = am.getExpiryUrgency(_activeIndex);
        }
        // Window-account binding map
        const winState = _readWindowState();
        const windowMap = {};
        const now = Date.now();
        for (const [id, w] of Object.entries(winState.windows || {})) {
          if (now - w.lastHeartbeat <= WINDOW_DEAD_MS) {
            windowMap[id] = { accountIndex: w.accountIndex, email: w.accountEmail, pid: w.pid, isSelf: id === _windowId };
          }
        }
        pool.windows = windowMap;
        pool.windowCount = Object.keys(windowMap).length;
        // Effective pool metrics (本源推万法)
        pool.effectiveMetrics = {
          sumEffective: pool.sumEffective,
          avgEffective: pool.avgEffective,
          weeklyBottleneckCount: pool.weeklyBottleneckCount,
          weeklyBottleneckRatio: pool.weeklyBottleneckRatio,
          preResetWasteCount: pool.preResetWasteCount,
          preResetWasteTotal: pool.preResetWasteTotal,
        };
        // Layer 5 容量探测数据
        pool.capacityProbe = {
          lastResult: _lastCapacityResult,
          probeCount: _capacityProbeCount,
          failCount: _capacityProbeFailCount,
          switchCount: _capacitySwitchCount,
          realMaxMessages: _realMaxMessages,
          lastCheckTs: _lastCapacityCheck,
          intervalMs: (_isBoost() || _burstMode) ? CAPACITY_CHECK_FAST : CAPACITY_CHECK_INTERVAL,
        };
        // Watchdog stats
        pool.watchdog = {
          lastSuccessfulProbe: _lastSuccessfulProbe,
          timeSinceProbe: Math.round((Date.now() - _lastSuccessfulProbe) / 1000),
          timeout: WATCHDOG_TIMEOUT / 1000,
          switchCount: _watchdogSwitchCount,
          isArmed: (Date.now() - _lastSuccessfulProbe) > WATCHDOG_TIMEOUT && _capacityProbeFailCount >= 3,
        };
        return json(pool);
      }

      if (p === "/api/pool/accounts") {
        const all = am ? am.getAll() : [];
        const safe = all.map((a, i) => ({
          index: i,
          email: a.email,
          credits: a.credits,
          usage: a.usage,
          effective: am.effectiveRemaining(i),
          rateLimited: am.isRateLimited(i),
          expired: am.isExpired(i),
          planDays: am.getPlanDaysRemaining(i),
          urgency: am.getExpiryUrgency(i),
        }));
        return json({
          accounts: safe,
          total: safe.length,
          activeIndex: _activeIndex,
        });
      }

      if (p === "/api/quota/cached") {
        try {
          const c = auth?.readCachedQuota();
          return json(c || { error: "no cached quota" });
        } catch {
          return json({ error: "read failed" });
        }
      }

      if (p === "/api/token/cost") {
        const model = qs.model || "Claude Sonnet 4.6";
        const msgs = parseInt(qs.msgs || "30");
        const avgIn = parseInt(qs.input || "4000"),
          avgOut = parseInt(qs.output || "2000");
        const daily = _tokenCost(model, msgs * avgIn, msgs * avgOut);
        const mo = +(daily.total_usd * 30).toFixed(2);
        const xCny = +(mo * _CNY).toFixed(2);
        const ratio = +(xCny / _XIANYU).toFixed(1);
        return json({
          model,
          acu: _ACU[model] || 1,
          msgs_per_day: msgs,
          avg_input: avgIn,
          avg_output: avgOut,
          daily,
          monthly_usd: mo,
          monthly_cny: xCny,
          per_msg: +(daily.total_usd / msgs).toFixed(4),
          xianyu: {
            api_cny: xCny,
            xianyu_cny: _XIANYU,
            ratio,
            savings_pct:
              xCny > 0 ? +((1 - _XIANYU / xCny) * 100).toFixed(1) : 0,
          },
        });
      }

      if (p === "/api/token/pricing")
        return json({ pricing: _ANTHROPIC, acu: _ACU });
      if (p === "/api/token/xianyu") {
        const mo = parseFloat(qs.monthly_usd || "37.80"),
          xy = parseFloat(qs.xianyu_cny || String(_XIANYU));
        const ac = +(mo * _CNY).toFixed(2),
          r = +(ac / xy).toFixed(1);
        return json({
          api_usd: mo,
          api_cny: ac,
          xianyu_cny: xy,
          ratio: r,
          savings_cny: +(ac - xy).toFixed(2),
          savings_pct: ac > 0 ? +((1 - xy / ac) * 100).toFixed(1) : 0,
        });
      }

      if (p === "/api/logs") {
        const limit = parseInt(qs.limit || "50");
        return json({ logs: _eventLog.slice(-limit), total: _eventLog.length });
      }

      // ═══ Complete CRUD API (用尽每一寸资源 — Hub feature-complete) ═══
      const _pb = () => new Promise(r => { let b=''; req.on('data',c=>b+=c); req.on('end',()=>{ try{r(JSON.parse(b||'{}'))}catch{r({})} }); });

      if (p === "/api/pool/active") {
        if (_activeIndex < 0 || !am) return json({ error: "no active" }, 404);
        const a = am.get(_activeIndex); const q = am.getActiveQuota ? am.getActiveQuota(_activeIndex) : null;
        return json({ ok: true, index: _activeIndex, email: a?.email, quota: q, plan: am.getPlanSummary ? am.getPlanSummary(_activeIndex) : null });
      }
      if (p === "/api/proxy/status") return json(auth ? { ok: true, ...auth.getProxyStatus() } : { ok: false, mode: "unknown" });
      if (p === "/api/fingerprint") { try { return json({ ok: true, ids: readFingerprint() }); } catch (e) { return json({ ok: false, ids: {}, error: e.message }); } }
      if (p === "/api/window/state") return json({ ok: true, windowId: _windowId, ..._readWindowState() });
      if (p === "/api/account/export") return json({ version: 1, exportedAt: new Date().toISOString(), count: am ? am.count() : 0, accounts: am ? am.exportAll() : [] });

      if (req.method === "POST" && p === "/api/account/add") { _pb().then(d => {
        if (!d.email || !d.password) return json({ error: "email and password required" }, 400);
        if (am && am.findByEmail(d.email)) return json({ error: "duplicate", email: d.email }, 409);
        const ok = am ? am.add(d.email, d.password) : false;
        json({ ok, email: d.email });
      }); return; }

      if (req.method === "POST" && p === "/api/account/batch") { _pb().then(d => {
        if (!d.text) return json({ error: "text required" }, 400);
        const r = am ? am.addBatch(d.text) : { added: 0, skipped: 0, total: 0 };
        json({ ok: true, ...r });
      }); return; }

      if (req.method === "POST" && p === "/api/pool/set_active") { _pb().then(d => {
        if (d.index === undefined || d.index < 0) return json({ error: "index required" }, 400);
        _activeIndex = d.index;
        json({ ok: true, activeIndex: _activeIndex });
      }); return; }

      if (req.method === "POST" && p === "/api/proxy/reprobe") {
        if (!auth) return json({ error: "no auth" }, 500);
        auth.reprobeProxy().then(r => json({ ok: true, ...r })).catch(e => json({ error: e.message }, 500));
        return;
      }

      if (req.method === "POST" && p === "/api/proxy/mode") { _pb().then(d => {
        if (!d.mode || !['local','relay'].includes(d.mode)) return json({ error: "invalid mode, use 'local' or 'relay'" }, 400);
        if (auth) auth.setMode(d.mode);
        json({ ok: true, mode: d.mode });
      }); return; }

      if (req.method === "POST" && p === "/api/account/mark_rate_limited") { _pb().then(d => {
        const idx = d.index ?? _activeIndex;
        if (am) am.markRateLimited(idx, d.seconds || 3600, { trigger: 'hub_api' });
        json({ ok: true, index: idx });
      }); return; }

      if (req.method === "POST" && p === "/api/account/clear_rate_limit") { _pb().then(d => {
        const idx = d.index ?? _activeIndex;
        if (am) am.clearRateLimit(idx);
        json({ ok: true, index: idx });
      }); return; }

      if (req.method === "POST" && p === "/api/pool/refresh") { _pb().then(async d => {
        try {
          const limit = d.limit || 0;
          if (limit > 0) { for (let i = 0; i < Math.min(limit, am ? am.count() : 0); i++) { try { await _refreshOne(i); } catch {} } }
          else { await _refreshAll(); }
          json({ ok: true, stats: am ? am.getPoolStats(PREEMPTIVE_THRESHOLD) : {} });
        } catch (e) { json({ ok: false, error: e.message }, 500); }
      }); return; }

      if (req.method === "POST" && p === "/api/pool/rotate") { _pb().then(async () => {
        if (!am) return json({ ok: false, error: "no account manager" });
        const best = am.selectOptimal(_activeIndex, PREEMPTIVE_THRESHOLD, _getOtherWindowAccounts());
        if (best) {
          // Full seamless switch
          const prev = _activeIndex;
          try {
            await _seamlessSwitch(context, best.index);
            json({ ok: true, from: prev, to: best.index, remaining: best.remaining, method: 'seamless' });
          } catch (e) {
            // Fallback to index-only if seamless fails
            _activeIndex = best.index;
            json({ ok: true, from: prev, to: best.index, remaining: best.remaining, method: 'index_only', warning: 'seamless failed: ' + e.message });
          }
        }
        else json({ ok: false, error: "no better account" });
      }); return; }

      // Dashboard
      if (p === "/" || p === "/dashboard") {
        const html = _hubDashboardHtml();
        res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        return res.end(html);
      }

      json({ error: "not found" }, 404);
    });

    _hubServer.on("error", (e) => {
      if (e.code === "EADDRINUSE") {
        _logWarn("HUB", `port ${HUB_PORT} in use, hub disabled`);
        _hubServer = null;
      } else _logError("HUB", "server error", e.message);
    });
    _hubServer.listen(HUB_PORT, "127.0.0.1", () => {
      _logInfo("HUB", `Hub API ready — http://127.0.0.1:${HUB_PORT}/`);
    });
  } catch (e) {
    _logWarn("HUB", "start failed", e.message);
  }
}

function _hubDashboardHtml() {
  return `<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WAM Hub</title><style>
*{margin:0;padding:0;box-sizing:border-box}body{font-family:system-ui,sans-serif;background:#0a0a1a;color:#e0e0e0;min-height:100vh}
.hd{background:linear-gradient(135deg,#1a1a3e,#2d1b69);padding:16px 24px;border-bottom:1px solid #333}
.hd h1{font-size:1.3em;background:linear-gradient(90deg,#00d4ff,#7b68ee);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hd .s{color:#888;font-size:.8em;margin-top:2px}
.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;padding:16px 24px}
.c{background:#12122a;border:1px solid #2a2a4a;border-radius:10px;padding:14px}
.c h3{color:#7b68ee;font-size:.8em;margin-bottom:8px;text-transform:uppercase;letter-spacing:1px}
.m{font-size:1.8em;font-weight:700;color:#00d4ff}.m.ok{color:#00ff88}.m.w{color:#ffa500}.m.d{color:#ff4444}
.sm{color:#888;font-size:.78em;margin-top:3px}
.bar{background:#1a1a3e;border-radius:4px;height:6px;margin:6px 0;overflow:hidden}
.bf{height:100%;border-radius:4px}.bf.g{background:linear-gradient(90deg,#00ff88,#00d4ff)}.bf.y{background:linear-gradient(90deg,#ffa500,#ffcc00)}.bf.r{background:linear-gradient(90deg,#ff4444,#ff6666)}
table{width:100%;border-collapse:collapse;font-size:.78em;margin-top:6px}th{color:#7b68ee;font-size:.75em;text-transform:uppercase;text-align:left;padding:4px 6px;border-bottom:1px solid #2a2a4a}td{padding:4px 6px;border-bottom:1px solid #151525}
.b{display:inline-block;padding:1px 6px;border-radius:3px;font-size:.7em;font-weight:600}.b.ok{background:#00ff8822;color:#00ff88}.b.w{background:#ffa50022;color:#ffa500}.b.e{background:#ff444422;color:#ff4444}.b.i{background:#00d4ff22;color:#00d4ff}
.fl{grid-column:1/-1}
.vd{text-align:center;padding:6px;margin-top:6px;border-radius:6px;background:#00ff8815;color:#00ff88;font-weight:700;font-size:.85em}
</style></head><body>
<div class="hd"><h1>WAM Hub (VSIX Embedded)</h1><div class="s">v7.2 \u00b7 :${HUB_PORT} \u00b7 Token Cost + Pool API</div></div>
<div class="g" id="a"></div>
<script>
const P=${JSON.stringify(_ANTHROPIC)};
const A=${JSON.stringify(_ACU)};
const CN=7.25,XY=4.5;
function cc(m,i,o){let p=P[m]||P["Claude Sonnet 4.6"];return{ic:i/1e6*p.i,oc:o/1e6*p.o,t:i/1e6*p.i+o/1e6*p.o}}
function f$(v){return v<0.01?'<$0.01':'$'+v.toFixed(v<1?4:2)}
function fY(v){return v<0.01?'<\\u00a50.01':'\\u00a5'+v.toFixed(2)}
function fK(v){return v>=1e6?(v/1e6).toFixed(1)+'M':v>=1e3?(v/1e3).toFixed(1)+'K':v.toString()}
async function ld(){
  const[s,ac,q,tc]=await Promise.all([
    fetch('/api/pool/status').then(r=>r.json()).catch(()=>({})),
    fetch('/api/pool/accounts').then(r=>r.json()).catch(()=>({accounts:[]})),
    fetch('/api/quota/cached').then(r=>r.json()).catch(()=>({})),
    fetch('/api/token/cost').then(r=>r.json()).catch(()=>({})),
  ]);
  const h=s.health||0,hc=h>70?'ok':h>30?'w':'d';
  const dy=q.daily!=null?q.daily:'?',wk=q.weekly!=null?q.weekly:'?';
  const qc=dy!=='?'?(dy>30?'ok':dy>10?'w':'d'):'ok';
  let html='';
  html+='<div class="c"><h3>Pool Health</h3><div class="m '+hc+'">'+h+'%</div>';
  html+='<div class="bar"><div class="bf '+(h>70?'g':h>30?'y':'r')+'" style="width:'+h+'%"></div></div>';
  html+='<div class="sm">'+(s.available||0)+' avail / '+(s.total||0)+' total / '+(s.depleted||0)+' depleted</div></div>';
  html+='<div class="c"><h3>Quota</h3><div class="m '+qc+'">D'+dy+'% W'+wk+'%</div>';
  html+='<div class="sm">Plan: '+(q.plan||'?')+' | Switches: '+(s.switchCount||0)+'</div></div>';
  html+='<div class="c"><h3>Active</h3><div class="m">#'+((s.activeIndex>=0?s.activeIndex+1:'?'))+'</div>';
  html+='<div class="sm">'+(s.activeEmail||'-')+' | rem: '+(s.activeRemaining!=null?s.activeRemaining:'?')+'</div></div>';
  if(tc.model){
    const d=tc.daily||{},xy=tc.xianyu||{};
    html+='<div class="c"><h3>Token Upload/Download</h3>';
    html+='<div style="display:flex;gap:12px;text-align:center">';
    html+='<div style="flex:1;background:#0d0d20;padding:8px;border-radius:6px"><div class="sm">\\u2b06 Input</div><div class="m" style="font-size:1.2em;color:#60a5fa">'+fK(tc.msgs_per_day*(tc.avg_input||4000))+'</div><div class="sm">'+f$(d.input_cost)+'/day</div></div>';
    html+='<div style="flex:1;background:#0d0d20;padding:8px;border-radius:6px"><div class="sm">\\u2b07 Output</div><div class="m" style="font-size:1.2em;color:#f472b6">'+fK(tc.msgs_per_day*(tc.avg_output||2000))+'</div><div class="sm">'+f$(d.output_cost)+'/day</div></div>';
    html+='</div><div class="sm" style="margin-top:6px">'+tc.model+' | ACU '+(tc.acu||1)+'x | '+tc.msgs_per_day+' msg/d</div></div>';
    html+='<div class="c"><h3>API Cost</h3><div class="m">'+f$(tc.monthly_usd)+'</div><div class="sm">/month ('+tc.model+')</div>';
    html+='<div class="sm" style="margin-top:6px">Per msg: '+f$(tc.per_msg)+' / '+fY(tc.per_msg*CN)+'<br>Per day: '+f$(d.total_usd)+' / '+fY(d.total_cny)+'</div></div>';
    html+='<div class="c"><h3>XianYu vs API</h3>';
    html+='<div class="sm">API: <span style="color:#ff4444">'+fY(xy.api_cny)+'/mo</span> | XianYu: <span style="color:#00ff88">\\u00a5'+xy.xianyu_cny+'/acct</span> | 1:'+xy.ratio+'</div>';
    html+='<div class="vd">\\ud83c\\udfc6 XianYu = API 1/'+xy.ratio+' | Save '+xy.savings_pct+'%</div></div>';
  }
  const al=ac.accounts||[];
  if(al.length>0){
    html+='<div class="c fl"><h3>Accounts ('+al.length+')</h3><table><tr><th>#</th><th>Email</th><th>Quota</th><th>Status</th></tr>';
    al.forEach(function(a){
      var r=a.effective!=null?a.effective:'?',ia=a.index===s.activeIndex,rl=a.rateLimited;
      var bg=ia?'<span class="b ok">Active</span>':rl?'<span class="b e">Limited</span>':(r!=='?'&&r<=15?'<span class="b w">Low</span>':'<span class="b i">Ready</span>');
      html+='<tr><td>'+(a.index+1)+'</td><td>'+a.email+'</td><td>'+r+'</td><td>'+bg+'</td></tr>';
    });
    html+='</table></div>';
  }
  document.getElementById('a').innerHTML=html;
}
ld();setInterval(ld,15000);
</script></body></html>`;
}

// ═══ 结构化日志系统 (v6.2 P1) ═══
function _log(level, tag, msg, data) {
  const ts = new Date().toLocaleTimeString();
  const prefix = `[${ts}] [${level}] [${tag}]`;
  const full =
    data !== undefined
      ? `${prefix} ${msg} ${JSON.stringify(data)}`
      : `${prefix} ${msg}`;
  // OutputChannel (用户可见)
  if (_outputChannel) _outputChannel.appendLine(full);
  // Console (开发者工具)
  if (level === "ERROR") console.error(`WAM: ${full}`);
  else console.log(`WAM: ${full}`);
  // 事件缓冲 (诊断用)
  _eventLog.push({
    ts: Date.now(),
    level,
    tag,
    msg: data !== undefined ? `${msg} ${JSON.stringify(data)}` : msg,
  });
  if (_eventLog.length > MAX_EVENT_LOG)
    _eventLog = _eventLog.slice(-MAX_EVENT_LOG);
}
function _logInfo(tag, msg, data) {
  _log("INFO", tag, msg, data);
}
function _logWarn(tag, msg, data) {
  _log("WARN", tag, msg, data);
}
function _logError(tag, msg, data) {
  _log("ERROR", tag, msg, data);
}

function _isBoost() {
  return Date.now() < _boostUntil;
}
function _activateBoost() {
  _boostUntil = Date.now() + BOOST_DURATION;
}

// ═══ 多窗口协调引擎 (v6.3 P0: 解决多窗口抢占同一账号的核心矛盾) ═══
// 原理: 每个Windsurf窗口是独立VS Code进程，号池引擎各自独立运行。
// 若不协调，所有窗口选同一"最优"账号 → N窗口×1账号 = N倍消耗 → rate limit命中加速。
// 解法: 共享状态文件，窗口注册+心跳+账号隔离，selectOptimal排除其他窗口占用。

function _getWindowStatePath() {
  const appdata =
    process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming");
  return path.join(
    appdata,
    "Windsurf",
    "User",
    "globalStorage",
    WINDOW_STATE_FILE,
  );
}

let _cachedWindowState = null; // 内存缓存，减少磁盘读取
let _cacheTs = 0;
const CACHE_TTL = 5000; // 缓存5s有效

function _readWindowState(forceRefresh = false) {
  if (
    !forceRefresh &&
    _cachedWindowState &&
    Date.now() - _cacheTs < CACHE_TTL
  ) {
    return JSON.parse(JSON.stringify(_cachedWindowState)); // 返回深拷贝防止外部修改
  }
  try {
    const p = _getWindowStatePath();
    if (!fs.existsSync(p)) return { windows: {} };
    const state = JSON.parse(fs.readFileSync(p, "utf8"));
    _cachedWindowState = state;
    _cacheTs = Date.now();
    return JSON.parse(JSON.stringify(state));
  } catch {
    return { windows: {} };
  }
}

function _writeWindowState(state) {
  try {
    const p = _getWindowStatePath();
    // 原子写入: 写临时文件 → rename，防止并发写入导致JSON损坏
    const tmp = p + ".tmp." + process.pid;
    fs.writeFileSync(tmp, JSON.stringify(state, null, 2), "utf8");
    fs.renameSync(tmp, p);
    _cachedWindowState = state;
    _cacheTs = Date.now();
  } catch (e) {
    // rename失败时降级为直写
    try {
      fs.writeFileSync(
        _getWindowStatePath(),
        JSON.stringify(state, null, 2),
        "utf8",
      );
    } catch {}
    _logWarn("WINDOW", "atomic write failed, used fallback", e.message);
  }
}

function _registerWindow(accountIndex) {
  _windowId = `w${process.pid}-${Date.now().toString(36)}`;
  const state = _readWindowState(true);
  const account = am ? am.get(accountIndex) : null;
  state.windows[_windowId] = {
    accountIndex,
    accountEmail: account?.email || null,
    lastHeartbeat: Date.now(),
    pid: process.pid,
    startedAt: Date.now(),
  };
  _writeWindowState(state);
  _logInfo("WINDOW", `registered ${_windowId} → #${accountIndex + 1} (${account?.email?.split('@')[0] || '?'})`);
}

function _heartbeatWindow() {
  if (!_windowId) return;
  const state = _readWindowState();
  if (!state.windows[_windowId]) {
    state.windows[_windowId] = { pid: process.pid, startedAt: Date.now() };
  }
  state.windows[_windowId].accountIndex = _activeIndex;
  state.windows[_windowId].accountEmail = am?.get(_activeIndex)?.email || null;
  state.windows[_windowId].lastHeartbeat = Date.now();
  const now = Date.now();
  for (const [id, w] of Object.entries(state.windows)) {
    if (now - w.lastHeartbeat > WINDOW_DEAD_MS) delete state.windows[id];
  }
  _writeWindowState(state);
}

function _deregisterWindow() {
  if (!_windowId) return;
  try {
    const state = _readWindowState(true); // 注销时强制刷新
    delete state.windows[_windowId];
    _writeWindowState(state);
    _logInfo("WINDOW", `deregistered ${_windowId}`);
  } catch {}
}

/** 获取其他活跃窗口占用的账号索引 */
function _getOtherWindowAccounts() {
  if (!_windowId) return [];
  const state = _readWindowState();
  const now = Date.now();
  const claimed = [];
  for (const [id, w] of Object.entries(state.windows)) {
    if (id === _windowId) continue;
    if (now - w.lastHeartbeat > WINDOW_DEAD_MS) continue;
    if (w.accountIndex >= 0) claimed.push(w.accountIndex);
  }
  return claimed;
}

/** 获取活跃窗口数(含自身) */
function _getActiveWindowCount() {
  const state = _readWindowState();
  const now = Date.now();
  return Object.values(state.windows).filter(
    (w) => now - w.lastHeartbeat <= WINDOW_DEAD_MS,
  ).length;
}

function _startWindowCoordinator(context) {
  _registerWindow(_activeIndex);
  _windowTimer = setInterval(() => _heartbeatWindow(), WINDOW_HEARTBEAT_MS);
  context.subscriptions.push({
    dispose: () => {
      if (_windowTimer) {
        clearInterval(_windowTimer);
        _windowTimer = null;
      }
      _deregisterWindow();
    },
  });
  const winCount = _getActiveWindowCount();
  _logInfo("WINDOW", `coordinator started — ${winCount} active window(s)`);
  if (winCount > 1) {
    const others = _getOtherWindowAccounts();
    _logInfo(
      "WINDOW",
      `other windows claim accounts: [${others.map((i) => "#" + (i + 1)).join(", ")}]`,
    );
  }
}

// ═══ 并发Tab感知引擎 (v6.4 P0) ═══

/** 探测当前窗口活跃Cascade对话数
 *  策略: 多层探测，取最高值
 *  L1: VS Code tabGroups API (最准确 — 直接枚举所有打开的Tab)
 *  L2: editor文档计数 (降级方案)
 *  L3: 窗口标题推断 (最后手段) */
function _detectCascadeTabs() {
  const now = Date.now();
  if (now - _lastTabCheck < TAB_CHECK_INTERVAL) return _cascadeTabCount;
  _lastTabCheck = now;

  let count = 0;
  try {
    // L1: tabGroups API — 精确枚举所有打开的tab
    if (vscode.window.tabGroups) {
      for (const group of vscode.window.tabGroups.all) {
        for (const tab of group.tabs) {
          // Cascade tabs have specific viewType or label patterns
          const label = (tab.label || "").toLowerCase();
          const inputUri =
            tab.input && tab.input.uri ? tab.input.uri.toString() : "";
          if (
            label.includes("cascade") ||
            label.includes("chat") ||
            inputUri.includes("cascade") ||
            inputUri.includes("chat") ||
            (tab.input &&
              tab.input.viewType &&
              /cascade|chat|copilot/i.test(tab.input.viewType))
          ) {
            count++;
          }
        }
      }
    }
  } catch {}

  // L2: 如果tabGroups检测不到，用活跃编辑器数做保守估计
  // (用户通常每个Tab对应一个并行任务，多个可见编辑器≈多个并行对话)
  if (count === 0) {
    try {
      const visibleEditors = vscode.window.visibleTextEditors.length;
      // 保守估计: 至少有1个cascade tab (我们知道有因为检测到了rate limit)
      if (visibleEditors > 1)
        count = Math.max(1, Math.floor(visibleEditors / 2));
    } catch {}
  }

  // L3: context key探测 — 如果任何quota/rate context key为true，至少1个活跃对话
  if (count === 0) count = 1; // 至少1个(插件本身在运行)

  const prev = _cascadeTabCount;
  _cascadeTabCount = count;
  if (count !== prev) {
    _logInfo(
      "TABS",
      `Cascade tab count: ${prev} → ${count}${count > CONCURRENT_TAB_SAFE ? " ⚠️ BURST RISK" : ""}`,
    );
    // 进入/退出burst防护模式
    if (count > CONCURRENT_TAB_SAFE && !_burstMode) {
      _burstMode = true;
      _activateBoost(); // 立即加速轮询
      _logWarn(
        "TABS",
        `BURST MODE ON — ${count} concurrent tabs detected, accelerating poll & preemptive rotation`,
      );
    } else if (count <= CONCURRENT_TAB_SAFE && _burstMode) {
      _burstMode = false;
      _logInfo("TABS", "BURST MODE OFF — safe concurrency level");
    }
  }
  return count;
}

/** 记录一次消息/请求事件(每次quota变化≈一次API消息) */
function _trackMessageRate() {
  _msgRateLog.push({ ts: Date.now() });
  // 清理过期记录
  const cutoff = Date.now() - MSG_RATE_WINDOW;
  _msgRateLog = _msgRateLog.filter((m) => m.ts > cutoff);
}

/** 获取当前消息速率(条/分钟) */
function _getCurrentMsgRate() {
  const cutoff = Date.now() - MSG_RATE_WINDOW;
  const recent = _msgRateLog.filter((m) => m.ts > cutoff);
  return recent.length; // 直接等于条/分钟(窗口是60s)
}

/** 判断是否接近消息速率上限 */
function _isNearMsgRateLimit() {
  const rate = _getCurrentMsgRate();
  const tabAdjustedLimit = Math.max(
    3,
    MSG_RATE_LIMIT / Math.max(1, _cascadeTabCount),
  );
  return rate >= tabAdjustedLimit * BURST_DETECT_THRESHOLD;
}

/** 获取当前最优轮询间隔(自适应: 正常→加速→burst) */
function _getAdaptivePollMs() {
  if (_burstMode) return POLL_BURST;
  if (_isBoost()) return POLL_BOOST;
  return POLL_NORMAL;
}

function activate(context) {
  try {
    _activate(context);
  } catch (e) {
    _logError("ACTIVATE", "activation failed", e.message);
  }
  // 无感磁盘维护 — 安装后自动清理历史遗留缓存，用户零感知
  try {
    const _dcDir = context.globalStorageUri
      ? path.dirname(context.globalStorageUri.fsPath)
      : path.join(os.homedir(), ".codeium", "windsurf");
    _diskSetLogger((msg) => { try { _logInfo("DC", msg); } catch {} });
    setImmediate(() => _diskClean(_dcDir).catch(() => {}));
  } catch {}
}

function _activate(context) {
  // ═══ 结构化日志通道 (v6.2 P1: 用户可见) ═══
  _outputChannel = vscode.window.createOutputChannel("WAM 号池引擎");
  context.subscriptions.push(_outputChannel);
  _logInfo(
    "BOOT",
    "无感号池引擎 v11.0 启动 (会话过渡修正 · 分级预算 · L5容量探测 · 四重闸门路由 · 无感切换 · 三重持久化)",
  );

  // 指纹完整性
  try {
    const r = ensureFingerprintComplete();
    if (r.fixed.length > 0) _logInfo("FP", `completed: ${r.fixed.join(", ")}`);
  } catch (e) {
    _logWarn("FP", "ensureComplete skipped", e.message);
  }

  const storagePath = context.globalStorageUri.fsPath;
  am = new AccountManager(storagePath);
  auth = new AuthService(storagePath);
  am.startWatching();

  // ═══ 状态栏：号池视图 ═══
  statusBar = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100,
  );
  statusBar.command = "wam.openPanel";
  statusBar.tooltip = "号池管理 · 点击查看";
  context.subscriptions.push(statusBar);

  // 恢复状态
  const savedIndex = context.globalState.get("wam-current-index", -1);
  const accounts = am.getAll();
  if (savedIndex >= 0 && savedIndex < accounts.length)
    _activeIndex = savedIndex;
  _updatePoolBar();
  statusBar.show();

  // 恢复代理
  const savedMode = context.globalState.get("wam-proxy-mode", null);
  if (savedMode) auth.setMode(savedMode);

  // 后台代理探测
  setTimeout(() => {
    if (!auth) return;
    auth
      .reprobeProxy()
      .then((r) => {
        if (r.port > 0) context.globalState.update("wam-proxy-mode", r.mode);
        _updatePoolBar();
        _logInfo("PROXY", `探测完成 → ${r.mode}:${r.port}`);
      })
      .catch((e) => {
        _logWarn("PROXY", "探测失败", e.message);
      });
  }, 1200);

  // ═══ 侧边栏 ═══
  const sidebarProvider = new AccountViewProvider(
    context.extensionUri,
    am,
    auth,
    (action, arg) => _handleAction(context, action, arg),
  );
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      "windsurf-assistant.assistantView",
      sidebarProvider,
    ),
  );
  _panelProvider = sidebarProvider;

  // ═══ 命令集 (精简 — 用户无需感知单个账号) ═══
  context.subscriptions.push(
    vscode.commands.registerCommand("wam.switchAccount", () =>
      _doPoolRotate(context),
    ),
    vscode.commands.registerCommand("wam.refreshCredits", () =>
      _doRefreshPool(context),
    ),
    vscode.commands.registerCommand("wam.openPanel", () => {
      const result = openAccountPanel(
        context,
        am,
        auth,
        (a, b) => _handleAction(context, a, b),
        _panel,
      );
      if (result) _panel = result.panel;
    }),
    vscode.commands.registerCommand("wam.switchMode", () =>
      _doSwitchMode(context),
    ),
    vscode.commands.registerCommand("wam.reprobeProxy", async () => {
      const r = await auth.reprobeProxy();
      context.globalState.update("wam-proxy-mode", r.mode);
      _updatePoolBar();
    }),
    vscode.commands.registerCommand("wam.resetFingerprint", () =>
      _doResetFingerprint(),
    ),
    vscode.commands.registerCommand("wam.panicSwitch", () =>
      _doPoolRotate(context, true),
    ),
    vscode.commands.registerCommand("wam.batchAdd", () => _doBatchAdd()),
    vscode.commands.registerCommand("wam.refreshAllCredits", () =>
      _doRefreshPool(context),
    ),
    vscode.commands.registerCommand("wam.smartRotate", () =>
      _doPoolRotate(context),
    ),
    vscode.commands.registerCommand("wam.importAccounts", () =>
      _doImport(context),
    ),
    vscode.commands.registerCommand("wam.initWorkspace", () =>
      _doInitWorkspace(context),
    ),
  );

  // ═══ 号池引擎启动 ═══
  _startPoolEngine(context);
  // ═══ 多窗口协调 (v6.3) ═══
  _startWindowCoordinator(context);
  // ═══ 并发Tab感知 (v6.4) ═══
  _detectCascadeTabs();
  // ═══ 内嵌Hub Server (v7.2) ═══
  _startHubServer();
  _logInfo(
    "BOOT",
    `号池引擎就绪 v11.0 — ${accounts.length}账号, proxy=${auth.getProxyStatus().mode}, win=${_getActiveWindowCount()}, tabs=${_cascadeTabCount}${_burstMode ? " BURST" : ""}, hub=:${HUB_PORT}, gates=4(Q/W/Model/Tier), detect=L1-2s/L3-10s/L5-3s(T)/45s, budget=T1M:${OPUS_THINKING_1M_BUDGET}/T:${OPUS_THINKING_BUDGET}/R:${OPUS_REGULAR_BUDGET}`,
  );
}

// ========== Refresh Helpers (deduplicated from 8 call sites) ==========

/** Refresh one account's usage/credits. Returns { credits, usageInfo }
 *  v5.11.0: Supplements QUOTA data from cachedPlanInfo when API doesn't return daily% */
async function _refreshOne(index) {
  const account = am.get(index);
  if (!account) return { credits: undefined };
  try {
    const usageInfo = await auth.getUsageInfo(account.email, account.password);
    if (usageInfo) {
      // v5.11.0: If billingStrategy=quota but no daily% from API, supplement from cachedPlanInfo
      if (
        usageInfo.billingStrategy === "quota" &&
        !usageInfo.daily &&
        index === _activeIndex &&
        auth
      ) {
        try {
          const cached = auth.readCachedQuota();
          if (cached && cached.daily !== null) {
            usageInfo.daily = {
              used: Math.max(0, 100 - cached.daily),
              total: 100,
              remaining: cached.daily,
            };
            if (cached.weekly !== null)
              usageInfo.weekly = {
                used: Math.max(0, 100 - cached.weekly),
                total: 100,
                remaining: cached.weekly,
              };
            if (cached.resetTime) usageInfo.resetTime = cached.resetTime;
            if (cached.weeklyReset) usageInfo.weeklyReset = cached.weeklyReset;
            if (cached.extraBalance)
              usageInfo.extraBalance = cached.extraBalance;
            usageInfo.mode = "quota";
            _logInfo(
              "SUPPLEMENT",
              `#${index + 1} quota from cachedPlanInfo: D${cached.daily}% W${cached.weekly}%`,
            );
          }
          // v6.9: Supplement plan dates from cachedPlanInfo (official alignment)
          if (cached) {
            if (cached.planStart && !usageInfo.planStart)
              usageInfo.planStart = cached.planStart;
            if (cached.planEnd && !usageInfo.planEnd)
              usageInfo.planEnd = cached.planEnd;
            if (cached.plan && !usageInfo.plan) usageInfo.plan = cached.plan;
          }
        } catch {}
      }
      // v6.9: For active account, always try to supplement plan dates even if daily is present
      if (index === _activeIndex && auth && !usageInfo.planEnd) {
        try {
          const cached = auth.readCachedQuota();
          if (cached) {
            if (cached.planStart && !usageInfo.planStart)
              usageInfo.planStart = cached.planStart;
            if (cached.planEnd && !usageInfo.planEnd)
              usageInfo.planEnd = cached.planEnd;
            if (cached.plan && !usageInfo.plan) usageInfo.plan = cached.plan;
          }
        } catch {}
      }
      am.updateUsage(index, usageInfo);
      return { credits: usageInfo.credits, usageInfo };
    }
  } catch {}
  try {
    const credits = await auth.getCredits(account.email, account.password);
    if (credits !== undefined) am.updateCredits(index, credits);
    return { credits };
  } catch {}
  return { credits: undefined };
}

/** Refresh all accounts with parallel batching. Optional progress callback(i, total).
 *  Concurrency=3 balances speed vs API rate limits. ~3x faster than sequential. */
async function _refreshAll(progressFn) {
  const accounts = am.getAll();
  const CONCURRENCY = 3;
  let completed = 0;
  for (let batch = 0; batch < accounts.length; batch += CONCURRENCY) {
    const slice = accounts.slice(batch, batch + CONCURRENCY);
    const promises = slice.map((_, j) => {
      const idx = batch + j;
      return _refreshOne(idx).then(() => {
        completed++;
        if (progressFn) progressFn(completed - 1, accounts.length);
      });
    });
    await Promise.allSettled(promises);
  }
}

// ========== 号池引擎 (v6.0 核心) ==========

/** 启动号池引擎 — 自适应轮询 + 自动选号 + 实时监控 + 并发Tab感知(v6.4) */
function _startPoolEngine(context) {
  const scheduleNext = () => {
    const ms = _getAdaptivePollMs(); // v6.4: 三级自适应(normal→boost→burst)
    _poolTimer = setTimeout(async () => {
      try {
        await _poolTick(context);
      } catch (e) {
        _logError("POOL", "tick error", e.message);
      }
      scheduleNext();
    }, ms);
  };
  // 首次启动延迟3s，等待代理探测完成
  setTimeout(async () => {
    await _poolTick(context);
    scheduleNext();
  }, 3000);
  // 同时启动限流检测
  _startQuotaWatcher(context);
}

/** 号池心跳 — 每次tick检查活跃账号，必要时自动轮转
 *  v6.7: + 全池实时监控 + 响应式切换(额度变动即切) + 并发Tab感知 */
async function _poolTick(context) {
  const accounts = am.getAll();
  if (accounts.length === 0) return;

  // v6.4: 每次tick探测并发Tab数
  _detectCascadeTabs();

  const autoRotate = vscode.workspace
    .getConfiguration("wam")
    .get("autoRotate", true);
  const threshold = PREEMPTIVE_THRESHOLD;

  // 无活跃账号 → 自动选择最优
  if (_activeIndex < 0 || _activeIndex >= accounts.length) {
    let best = am.selectOptimal(-1, threshold, _getOtherWindowAccounts());
    if (!best) best = am.selectOptimal(-1, threshold); // 降级: 忽略窗口隔离
    if (best) {
      _logInfo("POOL", `无活跃账号，自动选择 #${best.index + 1}`);
      await _seamlessSwitch(context, best.index);
    } else {
      _logWarn("POOL", "无活跃账号且无可用账号");
    }
    return;
  }

  // check expired active before wasting API call on refresh
  if (am.isExpired(_activeIndex)) {
    _logWarn("POOL", `活跃账号 #${_activeIndex + 1} 已过期 → 立即轮转`);
    if (autoRotate) {
      let best = am.selectOptimal(_activeIndex, threshold, _getOtherWindowAccounts());
      if (!best) best = am.selectOptimal(_activeIndex, threshold);
      if (best) await _seamlessSwitch(context, best.index);
    }
    return;
  }

  // 刷新活跃账号额度
  const prevQuota = _lastQuota;
  const { credits, usageInfo } = await _refreshOne(_activeIndex);
  const curQuota = am.effectiveRemaining(_activeIndex);
  _lastQuota = curQuota;
  _lastCheckTs = Date.now();

  // 记录斜率历史
  if (curQuota !== null && curQuota !== undefined) {
    _quotaHistory.push({ ts: Date.now(), remaining: curQuota });
    if (_quotaHistory.length > SLOPE_WINDOW * 2)
      _quotaHistory = _quotaHistory.slice(-SLOPE_WINDOW);
  }

  // 额度变化检测 + 消息速率追踪(v6.4) + 速度追踪(v7.0) + 小时消息追踪(v7.5)
  const quotaChanged =
    prevQuota !== null && prevQuota !== undefined && curQuota !== prevQuota;
  if (curQuota !== null) _trackVelocity(curQuota); // v7.0: 每次刷新都追踪速度
  if (quotaChanged) {
    _trackMessageRate(); // v6.4: 额度变化≈一次API消息
    _trackHourlyMsg(); // v7.5: Gate 4 小时消息追踪
    // v8.0: Opus消息预算追踪 — 额度下降+当前模型=Opus → 计为1条Opus消息
    if (curQuota < prevQuota) {
      const currentModel = _readCurrentModelUid();
      if (_isOpusModel(currentModel)) {
        _trackOpusMsg(_activeIndex);
        const opusCount = _getOpusMsgCount(_activeIndex);
        const _tierBudget = _getModelBudget(currentModel);
        _logInfo('OPUS_GUARD', `Opus追踪v10: #${_activeIndex+1} ${opusCount}/${_tierBudget}条 model=${currentModel} tier=${_isThinking1MModel(currentModel)?'T1M':_isThinkingModel(currentModel)?'T':'R'}${opusCount >= _tierBudget ? ' → WILL SWITCH!' : ''}`);
      }
    }
    const vel = _getVelocity();
    _logInfo(
      "POOL",
      `额度变化: ${prevQuota} → ${curQuota} (rate=${_getCurrentMsgRate()}/min, tabs=${_cascadeTabCount}, velocity=${vel.toFixed(1)}%/min)`,
    );
    _activateBoost(); // 加速轮询
    _updatePoolBar();
    _refreshPanel();
  }

  // ═══ v6.7 P0: 响应式切换 — 活跃账号额度下降 → 立即切到"静止"账号 ═══
  // 核心逻辑: 额度下降=正在被消耗 → 切到快照中额度未变的账号(未被使用)
  const quotaDrop =
    prevQuota !== null && curQuota !== null ? prevQuota - curQuota : 0;
  if (
    quotaChanged &&
    curQuota < prevQuota &&
    quotaDrop >= REACTIVE_DROP_MIN &&
    autoRotate &&
    Date.now() - _lastReactiveSwitchTs > REACTIVE_SWITCH_CD
  ) {
    const stableCandidates = [];
    for (let i = 0; i < accounts.length; i++) {
      if (i === _activeIndex) continue;
      if (am.isRateLimited(i)) continue;
      if (am.isExpired(i)) continue; // 跳过已过期账号
      const rem = am.effectiveRemaining(i);
      if (rem === null || rem === undefined || rem <= threshold) continue;
      // "静止" = 快照中额度与当前一致(未被其他窗口消耗)
      const snap = _allQuotaSnapshot.get(i);
      if (snap && snap.remaining !== null && snap.remaining === rem) {
        stableCandidates.push({ index: i, remaining: rem });
      } else if (!snap) {
        // 无快照 = 从未扫描过，也可作为候选(额度充足即可)
        stableCandidates.push({ index: i, remaining: rem });
      }
    }
    if (stableCandidates.length > 0) {
      // 排除其他窗口占用
      const otherClaimed = new Set(_getOtherWindowAccounts());
      const filtered = stableCandidates.filter(
        (c) => !otherClaimed.has(c.index),
      );
      const pool = filtered.length > 0 ? filtered : stableCandidates; // 降级: 忽略窗口隔离
      // UFEF-aware sort: 紧急过期账号优先使用
      pool.sort((a, b) => {
        const aU = am.getExpiryUrgency(a.index), bU = am.getExpiryUrgency(b.index);
        const aUrg = aU < 0 ? 2 : aU, bUrg = bU < 0 ? 2 : bU;
        if (aUrg !== bUrg) return aUrg - bUrg; // urgent first
        return b.remaining - a.remaining; // then highest remaining
      });
      _lastReactiveSwitchTs = Date.now();
      _logInfo(
        "REACTIVE",
        `活跃账号额度下降 ${prevQuota}→${curQuota}, 响应式切换到静止账号 #${pool[0].index + 1} (rem=${pool[0].remaining}, candidates=${pool.length})`,
      );
      await _seamlessSwitch(context, pool[0].index);
      return; // 已切换，跳过后续预防性判断
    }
  }

  // ═══ v6.7 P1: 全池扫描 — 定期刷新所有账号额度，更新快照 ═══
  if (Date.now() - _lastFullScanTs > FULL_SCAN_INTERVAL) {
    _lastFullScanTs = Date.now();
    _logInfo("SCAN", `全池扫描启动 (${accounts.length}账号)`);
    await _refreshAll();
    // 更新全池快照
    for (let i = 0; i < accounts.length; i++) {
      const rem = am.effectiveRemaining(i);
      const prev = _allQuotaSnapshot.get(i);
      if (prev && prev.remaining !== rem) {
        _logInfo("SCAN", `#${i + 1} 额度变化: ${prev.remaining} → ${rem}`);
      }
      _allQuotaSnapshot.set(i, { remaining: rem, checkedAt: Date.now() });
    }
    _refreshPanel();
  }

  // ═══ 预防性切换判断 ═══
  // 归宗: 三层结构 — 本(L5 gRPC)→辅(配额阈值)→备(启发式降级)
  // L5 gRPC容量探测返回服务端真值(hasCapacity/messagesRemaining/maxMessages/resetsInSeconds)
  // 当L5有效时，L2斜率/L4 burst/L5 Tab压力/L6速度/L7小时追踪皆为冗余启发式，跳过
  if (autoRotate) {
    let shouldRotate = false;
    let reason = "";
    const _l5Valid = _lastCapacityResult && _lastCapacityResult.messagesRemaining >= 0
      && (Date.now() - _lastCapacityCheck < 120000); // L5数据2min内有效

    // ── 本(Tier 1): L5 gRPC容量探测 — 服务端真值，一个接口解决所有 ──

    // L5-A: 容量耗尽 — hasCapacity=false → 用户下条消息必败 → 立即切
    if (!shouldRotate && _l5Valid && !_lastCapacityResult.hasCapacity) {
      shouldRotate = true;
      reason = `L5_no_capacity(remaining=${_lastCapacityResult.messagesRemaining}/${_lastCapacityResult.maxMessages},resets=${_lastCapacityResult.resetsInSeconds}s)`;
      _logWarn('POOL', `L5容量耗尽: 0容量 → 立即切号`);
      _invalidateApiKeyCache();
    }

    // L5-B: 容量预警 — 剩余≤3条或≤20%上限 → 提前切
    if (!shouldRotate && _l5Valid && _lastCapacityResult.hasCapacity) {
      const capMax = _lastCapacityResult.maxMessages > 0 ? _lastCapacityResult.maxMessages : TIER_MSG_CAP_ESTIMATE;
      const capRem = _lastCapacityResult.messagesRemaining;
      if (capRem <= CAPACITY_PREEMPT_REMAINING || (capMax > 0 && capRem <= capMax * 0.2)) {
        shouldRotate = true;
        reason = `L5_capacity_low(remaining=${capRem}/${capMax},resets=${_lastCapacityResult.resetsInSeconds}s)`;
        _logWarn('POOL', `L5容量预警: 剩余${capRem}/${capMax}条 → 提前切号`);
        _hourlyMsgLog = [];
        _invalidateApiKeyCache();
      }
    }

    // ── 辅(Tier 2): 配额阈值 — 独立于消息速率的日/周配额维度 ──

    // T2-A: 直接阈值判断 (effectiveRemaining ≤ 预防线15%)
    if (!shouldRotate) {
      const decision = am.shouldSwitch(_activeIndex, threshold);
      if (decision.switch) {
        shouldRotate = true;
        reason = decision.reason;
      }
    }

    // T2-B: rate limited状态(已标记的账号直接跳过)
    if (!shouldRotate && am.isRateLimited(_activeIndex)) {
      shouldRotate = true;
      reason = "rate_limited";
    }

    // T2-C: L8 Opus消息预算守卫 — per-model维度,L5可能未区分模型
    if (!shouldRotate && curQuota !== null && curQuota > threshold) {
      const currentModel = _readCurrentModelUid();
      if (_isOpusModel(currentModel) && _isNearOpusBudget(_activeIndex)) {
        const opusCount = _getOpusMsgCount(_activeIndex);
        shouldRotate = true;
        const tierBudget = _getModelBudget(currentModel);
        reason = `opus_budget_guard(model=${currentModel},msgs=${opusCount}/${tierBudget},tier=${_isThinking1MModel(currentModel)?'T1M':_isThinkingModel(currentModel)?'T':'R'})`;
        _logWarn('OPUS_GUARD', `Opus预算守卫v10: #${_activeIndex+1} 窗口内${opusCount}/${tierBudget}条 (tier=${_isThinking1MModel(currentModel)?'Thinking1M':'Thinking'}) → 主动切号`);
        _opusGuardSwitchCount++;
        for (const variant of OPUS_VARIANTS) {
          am.markModelRateLimited(_activeIndex, variant, OPUS_COOLDOWN_DEFAULT, { trigger: 'opus_budget_guard' });
        }
        _pushRateLimitEvent({ type: 'per_model', trigger: 'opus_budget_guard', model: currentModel, msgs: opusCount, budget: tierBudget, tier: _isThinking1MModel(currentModel)?'T1M':_isThinkingModel(currentModel)?'T':'R' });
      }
    }

    // T2-D: UFEF过期紧急 — 当前账号安全但有紧急账号额度充足 → 切到紧急账号避免浪费
    if (!shouldRotate && curQuota !== null && curQuota > threshold) {
      const activeUrg = am.getExpiryUrgency(_activeIndex);
      if (activeUrg >= 2 || activeUrg < 0) {
        for (let i = 0; i < accounts.length; i++) {
          if (i === _activeIndex) continue;
          if (am.isRateLimited(i) || am.isExpired(i)) continue;
          const iUrg = am.getExpiryUrgency(i);
          if (iUrg === 0) {
            const iRem = am.effectiveRemaining(i);
            if (iRem !== null && iRem > threshold) {
              shouldRotate = true;
              reason = `ufef_urgent(active_urg=${activeUrg},#${i+1}_urg=${iUrg},#${i+1}_rem=${iRem},#${i+1}_days=${am.getPlanDaysRemaining(i)})`;
              _logInfo('POOL', `UFEF: #${i+1}紧急(${am.getPlanDaysRemaining(i)}d) → 切到紧急账号避免浪费`);
              break;
            }
          }
        }
      }
    }

    // ── 备(Tier 3): 启发式降级 — 仅在L5 gRPC无效时启用 ──

    if (!shouldRotate && !_l5Valid) {
      // L2: 斜率预测 — 5分钟内跌穿预防线
      if (curQuota !== null && curQuota > threshold) {
        const predicted = _slopePredict();
        if (predicted !== null && predicted <= threshold) {
          shouldRotate = true;
          reason = `fallback_slope(cur=${curQuota},pred=${predicted})`;
        }
      }

      // L4: 并发burst预测
      if (!shouldRotate && _burstMode && _isNearMsgRateLimit()) {
        shouldRotate = true;
        reason = `fallback_burst(tabs=${_cascadeTabCount},rate=${_getCurrentMsgRate()}/${MSG_RATE_LIMIT})`;
      }

      // L5-Tab: 并发Tab高压
      if (!shouldRotate && _cascadeTabCount > CONCURRENT_TAB_SAFE && curQuota !== null) {
        const dynamicThreshold = threshold + (_cascadeTabCount - CONCURRENT_TAB_SAFE) * 5;
        if (curQuota <= dynamicThreshold && curQuota > threshold) {
          shouldRotate = true;
          reason = `fallback_tab_pressure(tabs=${_cascadeTabCount},cur=${curQuota},dyn=${dynamicThreshold})`;
        }
      }

      // L6: 高速消耗检测
      if (!shouldRotate && _isHighVelocity() && curQuota !== null && curQuota > threshold) {
        const vel = _getVelocity();
        shouldRotate = true;
        reason = `fallback_velocity(vel=${vel.toFixed(1)}%/min,cur=${curQuota})`;
        _logWarn('POOL', `高速消耗(降级): ${vel.toFixed(1)}%/min → 主动切号`);
      }

      // L7: Gate 4层级上限(小时消息追踪降级)
      if (!shouldRotate && curQuota !== null && curQuota > threshold && _isNearTierCap()) {
        const effectiveCap = _realMaxMessages > 0 ? _realMaxMessages : TIER_MSG_CAP_ESTIMATE;
        shouldRotate = true;
        reason = `fallback_tier_cap(hourly=${_getHourlyMsgCount()}/${effectiveCap})`;
        _hourlyMsgLog = [];
      }
    }

    if (shouldRotate) {
      _logInfo("POOL", `预防性轮转: ${reason}`);
      let best = am.selectOptimal(
        _activeIndex,
        threshold,
        _getOtherWindowAccounts(),
      );
      if (!best) best = am.selectOptimal(_activeIndex, threshold); // 降级: 忽略窗口隔离
      if (best) {
        await _seamlessSwitch(context, best.index);
      } else {
        _updatePoolBar();
        _logWarn("POOL", "预防性轮转失败: 所有账号额度不足");
      }
    }
  }

  _updatePoolBar();
}

/** 全感知限流检测 (v6.4: + 并发Tab感知 + 动态冷却 + burst加速检测) */
function _startQuotaWatcher(context) {
  const CONTEXTS = [
    "chatQuotaExceeded", // 对话配额耗尽
    "rateLimitExceeded", // 通用限流
    "windsurf.quotaExceeded", // Windsurf配额耗尽
    "windsurf.rateLimited", // Windsurf限流
    "cascade.rateLimited", // Cascade限流
    "windsurf.messageRateLimited", // 消息级限流(截图中的错误类型)
    "windsurf.modelRateLimited", // 模型级限流
    "windsurf.permissionDenied", // 权限拒绝
    "windsurf.modelProviderUnreachable", // 模型不可达
    "cascade.modelProviderUnreachable", // 模型不可达
    "windsurf.connectionError", // 连接错误
    "cascade.error", // 通用cascade错误
  ];
  let _lastTriggered = 0;

  // v6.8: 智能冷却 — 优先使用服务端报告的实际重置时间
  // 根因: v6.4假设message_rate=60-90s，但实测"Resets in: 19m27s"=1167s
  // 服务端有3级限流: burst_rate(<120s) / session_rate(120-3600s) / quota(>3600s)
  // 修复: 默认1200s(20min)匹配观测值，优先从state.vscdb或错误文本提取精确值
  const _smartCooldown = (rlType, serverResetSec) => {
    // 优先级1: 服务端报告的精确重置时间
    if (serverResetSec && serverResetSec > 0) return serverResetSec;
    // 优先级2: 从state.vscdb读取限流状态
    if (auth) {
      try {
        const cached = auth.readCachedRateLimit();
        if (cached && cached.resetsInSec && cached.resetsInSec > 0) {
          _logInfo(
            "COOLDOWN",
            `从state.vscdb获取实际冷却: ${cached.resetsInSec}s (type=${cached.type})`,
          );
          return cached.resetsInSec;
        }
      } catch {}
    }
    // 优先级3: 基于类型的默认值 (v8.0修正: message_rate从1200s→1500s匹配Opus 22m50s)
    if (rlType === "message_rate") return 1500; // 25min — 匹配实测"Resets in: 22m50s"(1370s)+裕量
    if (rlType === "quota") return 3600; // 1h — 等待日重置
    return 600; // unknown default 10min (保守)
  };

  // v6.8→v7.5: 从错误文本提取服务端重置时间
  // 支持: "Resets in: 19m27s" → 1167 | "about an hour" → 3600 | "Xh" → X*3600
  const _extractResetSeconds = (text) => {
    if (!text) return null;
    // Pattern 1: "Resets in: 19m27s"
    const m = text.match(/resets?\s*in:?\s*(\d+)m(?:(\d+)s)?/i);
    if (m) return parseInt(m[1]) * 60 + (parseInt(m[2]) || 0);
    // Pattern 2: "Resets in: 45s"
    const s = text.match(/resets?\s*in:?\s*(\d+)s/i);
    if (s) return parseInt(s[1]);
    // Pattern 3: "try again in about an hour" → 3600
    if (ABOUT_HOUR_RE.test(text)) return 3600;
    // Pattern 4: "try again in Xh" or "resets in Xh"
    const h = text.match(/(?:resets?|try\s*again)\s*in:?\s*(\d+)\s*h/i);
    if (h) return parseInt(h[1]) * 3600;
    return null;
  };

  // v7.4: 动态防抖 — 紧缩以快速响应(burst=2s, 正常=5s)
  const _getDebounce = () => (_burstMode ? 2000 : 5000);

  // ═══ Layer 1: Context Key检测 (v6.4: burst模式3s, 正常5s) ═══
  const checkContextKeys = async () => {
    if (_activeIndex < 0 || _switching) return;
    for (const ctx of CONTEXTS) {
      try {
        const exceeded = await vscode.commands.executeCommand(
          "getContext",
          ctx,
        );
        if (
          exceeded &&
          !_switching &&
          Date.now() - _lastTriggered > _getDebounce()
        ) {
          _lastTriggered = Date.now();
          const rlType =
            ctx.includes("quota") || ctx.includes("Quota")
              ? "quota"
              : "message_rate";
          const cooldown = _smartCooldown(rlType);
          _trackMessageRate(); // v6.4: 限流事件也计入消息速率
          _logWarn(
            "QUOTA",
            `检测到限流 context: ${ctx} (type=${rlType}, cooldown=${cooldown}s, tabs=${_cascadeTabCount}) → 立即轮转`,
          );
          // v7.5: 四重闸门路由 — 根据context key分类限流类型
          const currentModel = _readCurrentModelUid();
          const gateType = _classifyRateLimit(null, ctx);
          // Gate 4: 账号层级硬限 → 跳过模型轮转, 直接账号切换
          if (gateType === 'tier_cap') {
            _logWarn('QUOTA', `[L1→TIER_RL] Gate 4 账号层级硬限 via context: ${ctx}`);
            await _handleTierRateLimit(context, cooldown);
            return;
          }
          // Gate 3: per-model rate limit → 模型变体轮转策略
          if (gateType === 'per_model' && currentModel) {
            _logWarn('QUOTA', `[L1→MODEL_RL] Gate 3 per-model rate limit via context: ${ctx}, model=${currentModel}`);
            await _handlePerModelRateLimit(context, currentModel, cooldown);
            return;
          }
          // Gate 1/2: quota exhaustion → 标准账号切换
          am.markRateLimited(_activeIndex, cooldown, {
            model: currentModel || "current",
            trigger: ctx,
            type: rlType,
          });
          // v6.8: 推送限流事件到安全中枢(非阻塞)
          _pushRateLimitEvent({
            type: rlType,
            trigger: ctx,
            cooldown,
            tabs: _cascadeTabCount,
          });
          _activateBoost();
          await _doPoolRotate(context, true);
          return;
        }
      } catch (e) {
        // Suppress known harmless errors (getContext not found, Unknown context)
        // These flood logs every 2s × 12 keys = 360 noise events/min when command doesn't exist
        if (e.message && !e.message.includes("Unknown context") && !e.message.includes("not found")) {
          _logWarn("QUOTA", `context key ${ctx} 检测异常`, e.message);
        }
      }
    }
  };
  // v6.4: burst模式下加速context key轮询到3s
  // v7.4: 加速 context key 轮询(2s/1.5s)
  let ctxTimer = setInterval(checkContextKeys, 2000);
  const adaptiveCtxTimer = setInterval(() => {
    const targetMs = _burstMode ? 1500 : 2000;
    clearInterval(ctxTimer);
    ctxTimer = setInterval(checkContextKeys, targetMs);
  }, 30000);
  context.subscriptions.push({
    dispose: () => {
      clearInterval(ctxTimer);
      clearInterval(adaptiveCtxTimer);
    },
  });

  // ═══ Layer 2: 通知拦截 (v6.2 P2 新增 — 监听错误/警告消息中的rate limit文本) ═══
  const RATE_LIMIT_PATTERNS = [
    /rate\s*limit/i,
    /quota\s*exceed/i,
    /permission\s*denied.*rate/i,
    /reached.*message.*rate.*limit/i,
    /try\s*again\s*later.*resets?\s*in/i,
    /额度.*耗尽/,
    /限流/,
    /rate limit for this model/i,
    /message rate limit for this model/i,
    /no\s*credits\s*were\s*used/i,  // v7.5: Gate 4 tier cap indicator
    /upgrade\s*to\s*a?\s*pro/i,     // v7.5: Gate 4 tier cap indicator
    /try\s*again\s*in\s*about\s*an?\s*hour/i, // v7.5: Gate 4 ~1h recovery
    /model\s*provider\s*unreachable/i, // model availability error
    /provider.*(?:error|unavailable|unreachable)/i, // provider errors
    /incomplete\s*envelope/i, // gRPC framing error (broken session)
  ];
  const RESETS_IN_RE = /resets?\s*in:?\s*(\d+)m(?:(\d+)s)?/i;
  const PER_MODEL_RL_RE = /reached.*message.*rate.*limit.*for this model/i;
  const TRACE_ID_RE = /trace\s*(?:ID|id):?\s*([a-f0-9]+)/i;

  // v6.2: Layer 2文本模式用于诊断命令中的手动触发检测(matchRateLimitText)
  // VS Code API无法hook其他扩展的showMessage，故依赖Layer 1+3自动检测

  // ═══ Layer 3: cachedPlanInfo实时监控 (v6.2+v6.4: 动态防抖+智能冷却) ═══
  const checkCachedQuota = async () => {
    if (_activeIndex < 0 || _switching || !auth) return;
    try {
      const cached = auth.readCachedQuota();
      if (
        cached &&
        cached.exhausted &&
        !_switching &&
        Date.now() - _lastTriggered > _getDebounce()
      ) {
        _lastTriggered = Date.now();
        const cooldown = _smartCooldown("quota");
        _logWarn(
          "QUOTA",
          `cachedPlanInfo显示额度耗尽 (daily=${cached.daily}% weekly=${cached.weekly}%, cooldown=${cooldown}s) → 立即轮转`,
        );
        am.markRateLimited(_activeIndex, cooldown, {
          model: "current",
          trigger: "cachedPlanInfo_exhausted",
          type: "quota",
        });
        _pushRateLimitEvent({
          type: "quota",
          trigger: "cachedPlanInfo_exhausted",
          cooldown,
          daily: cached.daily,
          weekly: cached.weekly,
        });
        _activateBoost();
        await _doPoolRotate(context, true);
      }
    } catch (e) {
      _logWarn("QUOTA", "cachedPlanInfo检查异常", e.message);
    }
  };
  // v7.4: 加速 cachedPlanInfo 轮询(5s/10s)
  const cacheTimer = setInterval(checkCachedQuota, _burstMode ? 5000 : 10000);
  context.subscriptions.push({ dispose: () => clearInterval(cacheTimer) });

  // ═══ v11.0: L4(state.vscdb限流扫描)已移除 ═══
  // 根因: 每15s spawning Python进程读取state.vscdb, 性能开销大且数据不可靠
  // L1(context key) + L3(cachedPlanInfo) + L5(gRPC probe) 已足够覆盖所有场景

  // ═══ Layer 5: Active Rate Limit Capacity Probe — 主动调用gRPC预检端点 ═══
  // 核心突破: 主动调用 CheckUserMessageRateLimit gRPC 端点
  // Windsurf 在发送每条消息前调用此端点预检，我们也调用它获取精确容量数据
  // 当 hasCapacity=false 或 messagesRemaining<=2 → 立即切号，在用户消息失败前
  const checkCapacityProbe = async () => {
    if (_activeIndex < 0 || _switching || !auth) return;
    // 自适应间隔 — Thinking模型3s(最快), boost/burst 5s, 正幅45s
    const modelUid = _currentModelUid || _readCurrentModelUid();
    const isThinking = _isOpusModel(modelUid) && _isThinkingModel(modelUid);
    const interval = isThinking ? CAPACITY_CHECK_THINKING
      : (_isBoost() || _burstMode) ? CAPACITY_CHECK_FAST : CAPACITY_CHECK_INTERVAL;
    if (Date.now() - _lastCapacityCheck < interval) return;

    try {
      const capacity = await _probeCapacity();
      if (!capacity) return;

      // 🚫 容量已耗尽 → 立即切号(在用户下一条消息失败前!)
      if (!capacity.hasCapacity) {
        if (!_switching && Date.now() - _lastTriggered > _getDebounce()) {
          _lastTriggered = Date.now();
          _logWarn('CAPACITY', `[L5] 🚫 容量探测: hasCapacity=false → 立即切号`);
          await _handleCapacityExhausted(context, capacity);
          return;
        }
      }

      // ⚠️ 容量即将耗尽(剩余≤CAPACITY_PREEMPT_REMAINING) → 提前切号
      if (capacity.messagesRemaining >= 0 && capacity.messagesRemaining <= CAPACITY_PREEMPT_REMAINING) {
        if (!_switching && Date.now() - _lastTriggered > _getDebounce()) {
          _lastTriggered = Date.now();
          _logWarn('CAPACITY', `[L5] ⚠️ 容量预警: 剩余${capacity.messagesRemaining}/${capacity.maxMessages}条 → 提前切号`);
          await _handleCapacityExhausted(context, capacity);
          return;
        }
      }
    } catch (e) {
      // 非关键，静默处理
    }
  };
  // Layer 5 定时器: 首次延迟10s(等API key就绪), 之后每30s检查一次
  const l5Timer = setTimeout(() => {
    checkCapacityProbe(); // 首次探测
    const l5Interval = setInterval(checkCapacityProbe, 30000);
    context.subscriptions.push({ dispose: () => clearInterval(l5Interval) });
  }, 10000);
  context.subscriptions.push({ dispose: () => clearTimeout(l5Timer) });

  // ═══ v11.0: Watchdog已移除 ═══
  // 根因: Trial账号L5返回-1/-1(盲探) → Watchdog误判为"L5失败" → 无谓切号浪费号池
  // L1+L3+L5+Opus预算守卫 已足够覆盖: quota耗尽/rate limit/per-model limit/tier cap

  _logInfo(
    "WATCHER",
    `检测就绪v11: L1=${CONTEXTS.length}keys(2s) + L3=cachedPlanInfo(10s) + L5=gRPC(${CAPACITY_CHECK_THINKING/1000}s/${CAPACITY_CHECK_FAST/1000}s/${CAPACITY_CHECK_INTERVAL/1000}s) + 防抖(${_burstMode ? '2' : '5'}s) + 四重闸门(G1-G4) + 分级预算(T1M=${OPUS_THINKING_1M_BUDGET}/T=${OPUS_THINKING_BUDGET}/R=${OPUS_REGULAR_BUDGET})`,
  );
}

// ═══ Layer 5: Active Rate Limit Capacity Probe ═══
// 核心突破: 主动调用 CheckUserMessageRateLimit gRPC 端点
// Windsurf 在发送每条消息前调用此端点预检，我们也调用它获取精确容量数据
// 当 hasCapacity=false 或 messagesRemaining<=2 → 立即切号，在用户消息失败前

/** 获取缓存的apiKey(自动刷新) */
function _getCachedApiKey() {
  if (_cachedApiKey && Date.now() - _cachedApiKeyTs < APIKEY_CACHE_TTL) {
    return _cachedApiKey;
  }
  try {
    const key = auth?.readCurrentApiKey();
    if (key && key.length > 10) {
      _cachedApiKey = key;
      _cachedApiKeyTs = Date.now();
      return key;
    }
  } catch {}
  return _cachedApiKey; // 返回可能过期的缓存值(比null好)
}

/** 切号后使apiKey缓存失效(新账号有新apiKey) */
function _invalidateApiKeyCache() {
  _cachedApiKey = null;
  _cachedApiKeyTs = 0;
}

/** Layer 5: 主动容量探测 — 调用CheckUserMessageRateLimit获取精确容量
 *  返回: capacity result 或 null (失败时) */
async function _probeCapacity() {
  if (!auth || _activeIndex < 0) return null;

  // Reduced backoff: max 60s
  if (_capacityProbeFailCount >= 5) {
    if (Date.now() - _lastCapacityCheck < 60000) return _lastCapacityResult;
  }

  const apiKey = _getCachedApiKey();
  if (!apiKey) {
    _logWarn('CAPACITY', 'apiKey未获取，跳过容量探测');
    return null;
  }

  const modelUid = _readCurrentModelUid();
  if (!modelUid) return null;

  _lastCapacityCheck = Date.now();
  _capacityProbeCount++;

  try {
    const result = await auth.checkRateLimitCapacity(apiKey, modelUid);
    if (result) {
      // -1/-1 means server returned empty/useless data — don't count as success
      const hasUsefulData = result.messagesRemaining >= 0 || result.maxMessages >= 0 || !result.hasCapacity;
      if (hasUsefulData) {
        _capacityProbeFailCount = 0; // 重置失败计数
        _lastSuccessfulProbe = Date.now(); // 更新看门狗时间戳
      } else {
        // Got response but no useful data — increment fail count for watchdog
        _capacityProbeFailCount++;
      }
      _lastCapacityResult = result;

      // 更新真实消息上限(服务端权威数据)
      if (result.maxMessages > 0 && result.maxMessages !== _realMaxMessages) {
        const old = _realMaxMessages;
        _realMaxMessages = result.maxMessages;
        _logInfo('CAPACITY', `服务端消息上限更新: ${old} → ${_realMaxMessages} (model=${modelUid})`);
      }

      // Log capacity status (reduce noise: only log every 5th probe or on state change)
      if (_capacityProbeCount % 5 === 0 || !result.hasCapacity || !hasUsefulData) {
        const statusIcon = result.hasCapacity ? '✅' : '🚫';
        _logInfo('CAPACITY', `${statusIcon} probe #${_capacityProbeCount}: capacity=${result.hasCapacity} remaining=${result.messagesRemaining}/${result.maxMessages} resets=${result.resetsInSeconds}s model=${modelUid}${hasUsefulData ? '' : ' (NO_DATA)'}`);
      }

      return result;
    }
    _capacityProbeFailCount++;
    return null;
  } catch (e) {
    _capacityProbeFailCount++;
    _logWarn('CAPACITY', `探测失败 (#${_capacityProbeFailCount}): ${e.message}`);
    return null;
  }
}

/** 处理容量不足 — 立即切号 */
async function _handleCapacityExhausted(context, capacityResult) {
  _capacitySwitchCount++;
  const logPrefix = `[CAPACITY_RL #${_capacitySwitchCount}]`;
  const cooldown = capacityResult.resetsInSeconds || 3600;
  const model = _readCurrentModelUid();

  _logWarn('CAPACITY', `${logPrefix} 容量不足! hasCapacity=${capacityResult.hasCapacity} remaining=${capacityResult.messagesRemaining}/${capacityResult.maxMessages} resets=${cooldown}s msg="${capacityResult.message}"`);

  // 根据容量探测结果精确分类
  const gateType = _classifyRateLimit(capacityResult.message, null);

  // 标记当前账号限流
  am.markRateLimited(_activeIndex, cooldown, {
    model: model || 'current',
    trigger: 'capacity_probe',
    type: gateType || 'tier_cap',
    capacityData: {
      remaining: capacityResult.messagesRemaining,
      max: capacityResult.maxMessages,
      resets: capacityResult.resetsInSeconds,
    },
  });

  _pushRateLimitEvent({
    type: gateType || 'tier_cap',
    trigger: 'capacity_probe_L5',
    cooldown,
    model,
    messagesRemaining: capacityResult.messagesRemaining,
    maxMessages: capacityResult.maxMessages,
    resetsInSeconds: capacityResult.resetsInSeconds,
    message: capacityResult.message,
  });

  // Gate 4 or unknown → 直接账号切换
  if (gateType === 'tier_cap' || gateType === 'unknown') {
    _hourlyMsgLog = []; // 新账号从0开始
    _invalidateApiKeyCache(); // 切号后apiKey变化
    _activateBoost();
    await _doPoolRotate(context, true);
    return { action: 'capacity_account_switch', cooldown };
  }

  // Gate 3 (per-model) → 走模型级处理链
  if (gateType === 'per_model' && model) {
    _invalidateApiKeyCache();
    return await _handlePerModelRateLimit(context, model, cooldown);
  }

  // Default: 账号切换
  _invalidateApiKeyCache();
  _activateBoost();
  await _doPoolRotate(context, true);
  return { action: 'capacity_rotate', cooldown };
}

// ═══ 安全中枢融合 (v6.8: 限流事件推送 + 跨会话追踪) ═══

/** 推送限流事件到安全中枢 :9877 (非阻塞, 失败静默) */
function _pushRateLimitEvent(eventData) {
  try {
    const payload = JSON.stringify({
      event: "rate_limit",
      timestamp: Date.now(),
      activeIndex: _activeIndex,
      activeEmail: am?.get(_activeIndex)?.email?.split("@")[0] || "?",
      windowId: _windowId,
      cascadeTabs: _cascadeTabCount,
      burstMode: _burstMode,
      switchCount: _switchCount,
      poolStats: am?.getPoolStats(PREEMPTIVE_THRESHOLD) || {},
      ...eventData,
    });
    const req = http.request({
      hostname: "127.0.0.1",
      port: 9877,
      method: "POST",
      path: "/api/wam/rate_limit_event",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(payload),
      },
      timeout: 3000,
    });
    req.on("error", () => {}); // 静默失败
    req.on("timeout", () => req.destroy());
    req.write(payload);
    req.end();
    _logInfo(
      "HUB",
      `限流事件已推送 (type=${eventData.type}, trigger=${eventData.trigger})`,
    );
  } catch {}
}

// ========== 号池状态栏 ==========

// ═══ v7.0: 积分速度检测器 — 检测高速消耗模式 ═══
// 与斜率预测(slopePredict)不同: 速度检测器关注短期突变(2min内降>10%)
// 斜率预测关注长期趋势(5样本线性外推), 速度检测器关注即时危险

/** 追踪积分速度样本 */
function _trackVelocity(remaining) {
  if (remaining === null || remaining === undefined) return;
  _velocityLog.push({ ts: Date.now(), remaining });
  // 只保留窗口内的样本
  const cutoff = Date.now() - VELOCITY_WINDOW;
  _velocityLog = _velocityLog.filter((s) => s.ts >= cutoff);
}

/** 计算当前积分消耗速度 (%/min), 正值=消耗中 */
function _getVelocity() {
  if (_velocityLog.length < 2) return 0;
  const first = _velocityLog[0],
    last = _velocityLog[_velocityLog.length - 1];
  const dtMin = (last.ts - first.ts) / 60000;
  if (dtMin <= 0) return 0;
  const drop = first.remaining - last.remaining; // 正值=额度在降
  return drop / dtMin; // %/min
}

/** 检测是否处于高速消耗模式 (120s内降>VELOCITY_THRESHOLD%) */
function _isHighVelocity() {
  if (_velocityLog.length < 2) return false;
  const first = _velocityLog[0],
    last = _velocityLog[_velocityLog.length - 1];
  const drop = first.remaining - last.remaining;
  return drop >= VELOCITY_THRESHOLD;
}

/** 斜率预测: 基于最近N个quota样本，线性外推SLOPE_HORIZON后的剩余额度 */
function _slopePredict() {
  if (_quotaHistory.length < 2) return null;
  const recent = _quotaHistory.slice(-SLOPE_WINDOW);
  if (recent.length < 2) return null;
  const first = recent[0],
    last = recent[recent.length - 1];
  const dt = last.ts - first.ts;
  if (dt <= 0) return null;
  const rate = (last.remaining - first.remaining) / dt; // per ms (负值=消耗中)
  if (rate >= 0) return null; // 额度在增加或不变，无需预测
  const predicted = last.remaining + rate * SLOPE_HORIZON;
  return Math.round(predicted);
}

function _updatePoolBar() {
  if (!statusBar || !am) return;
  const accounts = am.getAll();
  if (accounts.length === 0) {
    statusBar.text = "$(add) 添加账号";
    statusBar.color = new vscode.ThemeColor("disabledForeground");
    statusBar.tooltip = "号池为空，点击添加账号";
    return;
  }

  const pool = am.getPoolStats(PREEMPTIVE_THRESHOLD);
  const mode = auth ? auth.getProxyStatus().mode : "?";
  const modeIcon = mode === "relay" ? "☁" : "⚡";

  // v6.6: Pool-wide aggregate quota (NOT single active account)
  let quotaDisplay = "?";
  let isLow = false;
  if (pool.avgDaily !== null) {
    quotaDisplay =
      pool.avgWeekly !== null
        ? `D${pool.avgDaily}%·W${pool.avgWeekly}%`
        : `D${pool.avgDaily}%`;
    const poolEffective =
      pool.avgWeekly !== null
        ? Math.min(pool.avgDaily, pool.avgWeekly)
        : pool.avgDaily;
    isLow = poolEffective <= 10;
  } else if (pool.avgCredits !== null) {
    quotaDisplay = `均${pool.avgCredits}分`;
    isLow = pool.avgCredits <= PREEMPTIVE_THRESHOLD;
  } else {
    quotaDisplay = `${pool.health}%`;
    isLow = pool.health <= 10;
  }

  // 号池健康度
  const poolTag = `${pool.available}/${pool.total}`;
  const boost = _isBoost() ? "⚡" : "";
  const burst = _burstMode ? "🔥" : ""; // v6.4: burst模式标识
  const auto = vscode.workspace.getConfiguration("wam").get("autoRotate", true)
    ? ""
    : "⏸";

  const winCount = _getActiveWindowCount();
  const winTag = winCount > 1 ? ` W${winCount}` : "";
  const tabTag =
    _cascadeTabCount > CONCURRENT_TAB_SAFE ? ` T${_cascadeTabCount}` : ""; // v6.4: 高并发Tab数
  statusBar.text = `${modeIcon} ${quotaDisplay} ${poolTag}${winTag}${tabTag}${burst}${boost}${auto}`;
  statusBar.color = isLow
    ? new vscode.ThemeColor("errorForeground")
    : pool.available === 0
      ? new vscode.ThemeColor("errorForeground")
      : _burstMode
        ? new vscode.ThemeColor("editorWarning.foreground") // v6.4: burst模式黄色警示
        : new vscode.ThemeColor("testing.iconPassed");

  // v6.9: 丰富tooltip (1:1 official alignment + pool aggregate + active account detail)
  const lines = [`号池: ${pool.available}可用/${pool.total}总计`];
  if (pool.depleted > 0) lines.push(`${pool.depleted}耗尽`);
  if (pool.rateLimited > 0) lines.push(`${pool.rateLimited}限流`);
  if (pool.expired > 0) lines.push(`${pool.expired}过期`);
  if (pool.urgentCount > 0) lines.push(`${pool.urgentCount}紧急(≤3d) — UFEF优先使用`);
  if (pool.soonCount > 0) lines.push(`${pool.soonCount}将到期(3-7d)`);
  // Effective pool metrics + weekly bottleneck + pre-reset waste
  if (pool.avgEffective !== null) lines.push(`有效均值: ${pool.avgEffective}% (min(D,W)真实容量)`);
  if (pool.weeklyBottleneckRatio > 50) lines.push(`ℹ️ W为瓶颈: ${pool.weeklyBottleneckCount}/${pool.effectiveCount}个账号W<D`);
  if (pool.preResetWasteCount > 0) lines.push(`⚠️ ${pool.preResetWasteCount}个账号周重置即将浪费${pool.preResetWasteTotal}%额度`);
  if (_switchCount > 0) lines.push(`已切换${_switchCount}次`);
  // v6.9: Active account detail — 1:1 official Plan display
  if (_activeIndex >= 0) {
    const q = am.getActiveQuota(_activeIndex);
    if (q) {
      const aName = am.get(_activeIndex)?.email?.split("@")[0] || "?";
      const aQuota =
        q.daily !== null
          ? q.weekly !== null
            ? `D${q.daily}%·W${q.weekly}%`
            : `D${q.daily}%`
          : q.credits !== null
            ? `${q.credits}分`
            : "?";
      const planTag = q.plan ? ` [${q.plan}]` : "";
      const expiryTag =
        q.planDays !== null
          ? q.planDays > 0
            ? ` ${q.planDays}d剩余`
            : " 已过期"
          : "";
      lines.push(
        `活跃: #${_activeIndex + 1} ${aName} ${aQuota}${planTag}${expiryTag}`,
      );
      if (q.resetCountdown)
        lines.push(
          `日重置: ${q.resetCountdown}${q.dailyResetRaw ? " (" + new Date(q.dailyResetRaw).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) + ")" : ""}`,
        );
      if (q.weeklyResetCountdown)
        lines.push(
          `周重置: ${q.weeklyResetCountdown}${q.weeklyReset ? " (" + new Date(q.weeklyReset).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) + ")" : ""}`,
        );
      if (q.extraBalance !== null && q.extraBalance > 0)
        lines.push(`额外余额: $${q.extraBalance.toFixed(2)}`);
    }
  }
  if (pool.nextReset)
    lines.push(`下次刷新: ${new Date(pool.nextReset).toLocaleTimeString()}`);
  const slopeInfo = _slopePredict();
  if (winCount > 1)
    lines.push(
      `${winCount}个窗口活跃 | 其他窗口占用: [${_getOtherWindowAccounts()
        .map((i) => "#" + (i + 1))
        .join(",")}]`,
    );
  if (_cascadeTabCount > 1)
    lines.push(
      `${_cascadeTabCount}个Cascade对话 | 消息速率: ${_getCurrentMsgRate()}/${MSG_RATE_LIMIT}/min`,
    );
  if (_burstMode) lines.push("BURST防护模式");
  // v7.0: 热重置+速度感知信息
  const vel = _getVelocity();
  if (vel > 0)
    lines.push(
      `消耗速度: ${vel.toFixed(1)}%/min${_isHighVelocity() ? " ⚡高速" : ""}`,
    );
  // v7.5: Gate 4 小时消息计数
  const hourlyCount = _getHourlyMsgCount();
  if (hourlyCount > 0) lines.push(`小时消息: ${hourlyCount}/${TIER_MSG_CAP_ESTIMATE}${_isNearTierCap() ? ' ⚠️接近层级上限' : ''}`);
  if (_tierRateLimitCount > 0) lines.push(`层级限流(G4): ${_tierRateLimitCount}次`);
  if (_hotResetCount > 0)
    lines.push(`热重置: ${_hotResetVerified}/${_hotResetCount}次验证`);
  // v8.0: Opus Guard stats
  const currentModel = _currentModelUid || _readCurrentModelUid();
  if (_isOpusModel(currentModel) && _activeIndex >= 0) {
    const opusCount = _getOpusMsgCount(_activeIndex);
    const tierBudget = _getModelBudget(currentModel);
    const tierLabel = _isThinking1MModel(currentModel) ? 'T1M' : _isThinkingModel(currentModel) ? 'T' : 'R';
    lines.push(`Opus预算: ${opusCount}/${tierBudget}条 (tier=${tierLabel}, model=${currentModel})`);
  }
  if (_opusGuardSwitchCount > 0) lines.push(`Opus守卫: ${_opusGuardSwitchCount}次主动切号`);
  if (_modelRateLimitCount > 0) lines.push(`模型限流(G3): ${_modelRateLimitCount}次`);
  // L5容量探测数据
  if (_lastCapacityResult) {
    const cap = _lastCapacityResult;
    const capIcon = cap.hasCapacity ? '✅' : '🚫';
    lines.push(`L5容量: ${capIcon} ${cap.messagesRemaining >= 0 ? cap.messagesRemaining : '?'}/${cap.maxMessages >= 0 ? cap.maxMessages : '?'}条 (probe#${_capacityProbeCount})`);
    if (cap.resetsInSeconds > 0) lines.push(`重置: ${Math.ceil(cap.resetsInSeconds / 60)}min`);
  }
  if (_capacitySwitchCount > 0) lines.push(`容量切号(L5): ${_capacitySwitchCount}次`);
  if (_capacityProbeFailCount > 0) lines.push(`L5探测失败: ${_capacityProbeFailCount}次连续`);
  // Watchdog status
  const wdAge = Math.round((Date.now() - _lastSuccessfulProbe) / 1000);
  const wdArmed = wdAge > WATCHDOG_TIMEOUT / 1000 && _capacityProbeFailCount >= 3;
  if (_watchdogSwitchCount > 0 || wdArmed) {
    lines.push(`看门狗: ${wdArmed ? '⚠️已待命' : '✅正常'} | ${wdAge}s自上次探测 | 切号${_watchdogSwitchCount}次`);
  }
  lines.push(
    `预防线: ${PREEMPTIVE_THRESHOLD}%${slopeInfo !== null ? " | 预测:" + slopeInfo + "%" : ""} | ${mode} | 10层防御(L1-L8+L5probe+Watchdog)`,
  );
  statusBar.tooltip = lines.join("\n");
}

// ========== 号池轮转 (无感切换) ==========

/** 无感切换 — 用户无需任何操作 */
async function _seamlessSwitch(context, targetIndex) {
  if (_switching || targetIndex === _activeIndex) return;
  _switching = true;
  const prevBar = statusBar.text;
  statusBar.text = "$(sync~spin) ...";
  const prevIndex = _activeIndex;

  try {
    _invalidateApiKeyCache(); // 切号后apiKey变化
    await _loginToAccount(context, targetIndex);
    _switchCount++;
    // reset tracking state — old account's data corrupts new account's predictions
    _quotaHistory = [];
    _velocityLog = [];
    _lastQuota = null;
    _heartbeatWindow();
    _logInfo(
      "SWITCH",
      `无感切换 #${prevIndex + 1}→#${targetIndex + 1} (第${_switchCount}次, ${_getActiveWindowCount()}窗口)`,
    );
  } catch (e) {
    _logError("SWITCH", `切换失败 #${targetIndex + 1}`, e.message);
    statusBar.text = prevBar;
  } finally {
    _switching = false;
    _updatePoolBar();
    _refreshPanel();
  }
}

/** 号池轮转命令 (用户触发或自动触发)
 *  v11.0: isPanic=true跳过_refreshAll(用缓存直切)，但注入始终完整验证 */
async function _doPoolRotate(context, isPanic = false) {
  if (_switching) return;
  const accounts = am.getAll();
  if (accounts.length === 0) {
    vscode.commands.executeCommand("wam.openPanel");
    return;
  }

  const threshold = PREEMPTIVE_THRESHOLD;

  // ═══ 紧急切换(跳过全池刷新，用缓存数据直切) ═══
  // v11.0: 不再跳过注入验证(_urgentSwitch已废弃)，杜绝"Invalid argument"根源
  if (isPanic && _activeIndex >= 0) {
    statusBar.text = "$(zap) 即时切换...";
    const t0 = Date.now();
    _logWarn("ROTATE", `紧急切换: 标记 #${_activeIndex + 1} 限流 → 用缓存选最优`);
    if (!am.isRateLimited(_activeIndex)) {
      am.markRateLimited(_activeIndex, 300, { model: "unknown", trigger: "panic_rotate" });
    }
    let best = am.selectOptimal(_activeIndex, threshold, _getOtherWindowAccounts());
    if (!best) best = am.selectOptimal(_activeIndex, threshold);
    if (!best) best = am.selectOptimal(_activeIndex, 0);
    if (best) {
      await _seamlessSwitch(context, best.index);
      _logInfo("ROTATE", `紧急切换完成: #${best.index + 1} (耗时${Date.now() - t0}ms)`);
      _updatePoolBar();
      _refreshPanel();
      setTimeout(() => _refreshAll().then(() => { _updatePoolBar(); _refreshPanel(); }).catch(() => {}), 5000);
      return;
    }
    if (accounts.length > 1) {
      let next = -1;
      for (let r = 1; r < accounts.length; r++) {
        const ci = (_activeIndex + r) % accounts.length;
        if (!am.isRateLimited(ci) && !am.isExpired(ci)) { next = ci; break; }
      }
      if (next < 0) next = (_activeIndex + 1) % accounts.length;
      await _seamlessSwitch(context, next);
      _logInfo("ROTATE", `紧急round-robin切换: #${next + 1} (耗时${Date.now() - t0}ms)`);
    }
    _updatePoolBar();
    _refreshPanel();
    return;
  }

  // ═══ 非紧急模式: 完整刷新+选优 ═══
  statusBar.text = "$(sync~spin) 轮转中...";
  await _refreshAll();

  let best = am.selectOptimal(
    _activeIndex,
    threshold,
    _getOtherWindowAccounts(),
  );
  if (!best) best = am.selectOptimal(_activeIndex, threshold);
  if (best) {
    await _seamlessSwitch(context, best.index);
  } else if (am.allDepleted(threshold)) {
    statusBar.text = "$(warning) 号池耗尽";
    statusBar.color = new vscode.ThemeColor("errorForeground");
    vscode.window.showWarningMessage(
      "WAM: 所有账号额度不足。SWE-1.5模型免费无限使用。",
      "确定",
    );
  } else {
    // Round-robin fallback (跳过不可用账号)
    if (accounts.length > 1) {
      let next = -1;
      for (let r = 1; r < accounts.length; r++) {
        const ci = (_activeIndex + r) % accounts.length;
        if (!am.isRateLimited(ci) && !am.isExpired(ci)) { next = ci; break; }
      }
      if (next < 0) next = (_activeIndex + 1) % accounts.length;
      await _seamlessSwitch(context, next);
    }
  }
  _updatePoolBar();
  _refreshPanel();
}

// ========== Core: Auth Infrastructure (battle-tested, kept intact) ==========

/** Discover the correct auth injection command at runtime */
async function _discoverAuthCommand() {
  if (_discoveredAuthCmd) return _discoveredAuthCmd;
  const allCmds = await vscode.commands.getCommands(true);
  const candidates = [
    ...allCmds.filter(
      (c) => /provideAuthToken.*AuthProvider/i.test(c) && !/Shit/i.test(c),
    ),
    ...allCmds.filter((c) => /provideAuthToken.*Shit/i.test(c)),
    ...allCmds.filter(
      (c) =>
        /windsurf/i.test(c) &&
        /auth/i.test(c) &&
        /token/i.test(c) &&
        c !== "windsurf.loginWithAuthToken",
    ),
  ];
  const seen = new Set();
  const unique = candidates.filter((c) => {
    if (seen.has(c)) return false;
    seen.add(c);
    return true;
  });
  _logInfo(
    "AUTH",
    `discovered ${unique.length} auth commands: [${unique.join(", ")}]`,
  );
  if (unique.length > 0) _discoveredAuthCmd = unique;
  return unique;
}

function _resetDiscoveredCommands() {
  _discoveredAuthCmd = null;
}

// ═══ v11.0 会话过渡等待 ═══
// 根因修正: provideAuthTokenToAuthProvider → handleAuthToken → registerUser → restartLS
// 是Windsurf内部自动完成的。旧版错误地重启TypeScript LS(无关)和清理.vscode-server(远程开发)。
// 真正需要的只是等待Windsurf内部的auth handler完成会话切换。

/**
 * 等待Windsurf内部会话过渡完成
 * provideAuthTokenToAuthProvider触发的内部链: handleAuthToken → registerUser → new session
 * 我们只需等待这个过程完成，不需要重启任何LS
 */
async function _waitForSessionTransition() {
  _logInfo("SESSION", "等待Windsurf会话过渡...");
  // Windsurf内部registerUser + session创建需要1-3秒
  await new Promise((resolve) => setTimeout(resolve, 2000));
  _logInfo("SESSION", "会话过渡等待完成");
  return true;
}

/**
 * v7.1.0 热重置验证
 * 验证新机器码是否真的被LS读取
 */
async function _verifyHotResetSuccess() {
  if (!_lastRotatedIds) {
    _logWarn("HOT_RESET", "无轮转记录可验证");
    return false;
  }

  try {
    // 等待LS完全启动并读取新机器码
    await new Promise((resolve) => setTimeout(resolve, 5000));

    // 验证新机器码是否生效
    const verify = hotVerify(_lastRotatedIds);
    if (verify.verified) {
      _hotResetVerified++;
      _logInfo(
        "HOT_RESET",
        `✅ 热重置验证成功 (#${_hotResetVerified}/${_hotResetCount})`,
      );
      return true;
    } else {
      _logWarn(
        "HOT_RESET",
        `❌ 热重置验证失败: ${verify.mismatches.join(", ")}`,
      );
      return false;
    }
  } catch (e) {
    _logError("HOT_RESET", "验证过程出错", e.message);
    return false;
  }
}

// ═══════════════════════════════════════════════════════════════════
// v6.0 CORE CHANGE: Split into checkAccount (SAFE) vs injectAuth (DISRUPTIVE)
//
// Root cause of "breaks Cascade": provideAuthTokenToAuthProvider switches the
// active auth session, invalidating any ongoing Cascade conversation.
//
// Solution: Default operations (login button, credit check, rotation monitoring)
// use checkAccount() which ONLY does Firebase auth + credit query — ZERO impact
// on Windsurf's internal auth state. Auth injection is a separate explicit action.
// ═══════════════════════════════════════════════════════════════════

/**
 * SAFE: Check account credentials and refresh credits.
 * Does Firebase login + GetPlanStatus only. Does NOT touch Windsurf auth.
 * Returns { ok, credits, usageInfo }
 */
async function _checkAccount(context, index) {
  const account = am.get(index);
  if (!account) return { ok: false };

  const result = await _refreshOne(index);
  _activeIndex = index;
  context.globalState.update("wam-current-index", index);
  _updatePoolBar();

  return { ok: true, credits: result.credits, usageInfo: result.usageInfo };
}

/**
 * DISRUPTIVE: Inject auth token into Windsurf to switch active account.
 * WARNING: This WILL disconnect any active Cascade conversation.
 * Should only be called with explicit user consent.
 * Returns { ok, injected, method }
 *
 * v5.8.0 Strategy (reverse-engineered from Windsurf 1.108.2):
 *   S0: idToken → PROVIDE_AUTH_TOKEN_TO_AUTH_PROVIDER (PRIMARY — Windsurf internally registerUser)
 *   S1: OneTimeAuthToken → command (FALLBACK — relay only, legacy)
 *   S2: registerUser apiKey → command (LAST RESORT)
 */
async function injectAuth(context, index) {
  const account = am.get(index);
  if (!account) return { ok: false };

  // ═══ v11.0 指纹轮转 + 会话过渡 ═══
  // 根因修正: provideAuthTokenToAuthProvider内部自动触发registerUser→restartLS
  // 不再手动重启LS(旧版错误地重启TypeScript LS)
  // 只需: 轮转指纹(写磁盘) → 等待 → 注入(Windsurf内部完成LS重启+读新ID)
  const config = vscode.workspace.getConfiguration("wam");
  if (config.get("rotateFingerprint", true)) {
    _rotateFingerprintForSwitch();
    _hotResetCount++;
    _logInfo("HOT_RESET", `fingerprint rotated (#${_hotResetCount})`);
    // 等待指纹写入磁盘完成(Windsurf注入后内部重启LS时会读取新指纹)
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }

  let injected = false;
  let method = "none";
  const discoveredCmds = await _discoverAuthCommand();

  // Strategy 0 (PRIMARY — Windsurf 1.108.2+): idToken direct
  // PROVIDE_AUTH_TOKEN_TO_AUTH_PROVIDER accepts firebase idToken,
  // internally calls registerUser(idToken) → {apiKey, name} → session
  try {
    const idToken = await auth.getFreshIdToken(account.email, account.password);
    if (idToken) {
      // Try well-known command name first
      try {
        const result = await vscode.commands.executeCommand(
          "windsurf.provideAuthTokenToAuthProvider",
          idToken,
        );
        // FIX: Check return value — command returns {session, error}, not throwing on auth failure
        if (result && result.error) {
          _logWarn(
            "INJECT",
            `[S0] command returned error: ${JSON.stringify(result.error)}`,
          );
        } else {
          injected = true;
          method = "S0-provideAuth-idToken";
          _logInfo(
            "INJECT",
            `[S0] injected idToken via provideAuthTokenToAuthProvider → session: ${result?.session?.account?.label || "unknown"}`,
          );
        }
      } catch (e) {
        _logWarn("INJECT", `[S0] primary command failed: ${e.message}`);
      }
      // Try discovered commands with idToken
      if (!injected) {
        for (const cmd of discoveredCmds || []) {
          if (injected) break;
          try {
            const result = await vscode.commands.executeCommand(cmd, idToken);
            if (result && result.error) {
              _logWarn(
                "INJECT",
                `[S0-discovered] ${cmd} returned error: ${JSON.stringify(result.error)}`,
              );
            } else {
              injected = true;
              method = `S0-${cmd}-idToken`;
              _logInfo("INJECT", `[S0-discovered] injected idToken via ${cmd}`);
            }
          } catch {}
        }
      }
    }
  } catch (e) {
    _logWarn("INJECT", "[S0] idToken injection failed", e.message);
  }

  // Strategy 1 (FALLBACK): OneTimeAuthToken via relay
  if (!injected) {
    try {
      const authToken = await auth.getOneTimeAuthToken(
        account.email,
        account.password,
      );
      if (authToken && authToken.length >= 30 && authToken.length <= 200) {
        try {
          await vscode.commands.executeCommand(
            "windsurf.provideAuthTokenToAuthProvider",
            authToken,
          );
          injected = true;
          method = "S1-provideAuth-otat";
          _logInfo(
            "INJECT",
            "[S1] injected OneTimeAuthToken via provideAuthTokenToAuthProvider",
          );
        } catch {}
        if (!injected) {
          for (const cmd of discoveredCmds || []) {
            if (injected) break;
            try {
              await vscode.commands.executeCommand(cmd, authToken);
              injected = true;
              method = `S1-${cmd}-otat`;
              _logInfo(
                "INJECT",
                `[S1-discovered] injected OneTimeAuthToken via ${cmd}`,
              );
            } catch {}
          }
        }
        if (injected) _writeAuthFilesCompat(authToken);
      }
    } catch (e) {
      _logWarn("INJECT", "[S1] OneTimeAuthToken fallback failed", e.message);
    }
  }

  // Strategy 2: registerUser apiKey via command
  if (!injected) {
    try {
      const regResult = await auth.registerUser(
        account.email,
        account.password,
      );
      if (regResult && regResult.apiKey) {
        for (const cmd of discoveredCmds || []) {
          if (injected) break;
          try {
            await vscode.commands.executeCommand(cmd, regResult.apiKey);
            injected = true;
            method = `S2-${cmd}-apiKey`;
            _logInfo("INJECT", `[S2] injected apiKey via ${cmd}`);
          } catch (e) {
            _logError("INJECT", `[S2] ${cmd} failed`, e.message);
          }
        }
        // Strategy 3 (DB DIRECT-WRITE — bypasses command system):
        // Writes new apiKey to windsurfAuthStatus in state.vscdb.
        // NOTE: sessions secret is DPAPI-encrypted → can't update via DB.
        // Must trigger window reload so Windsurf re-reads auth state from DB.
        if (!injected) {
          const dbResult = _dbInjectApiKey(regResult.apiKey);
          if (dbResult.ok) {
            injected = true;
            method = "S3-db-inject";
            _logInfo(
              "INJECT",
              `[S3] DB direct-write: ${dbResult.oldPrefix}→${dbResult.newPrefix}`,
            );
            // DB injection requires window reload to take effect (encrypted session unchanged)
            setTimeout(async () => {
              const reload = await vscode.window.showInformationMessage(
                "WAM: 账号已切换(DB注入)。需要重新加载窗口使新账号生效。",
                "立即重载",
                "稍后",
              );
              if (reload === "立即重载") {
                vscode.commands.executeCommand("workbench.action.reloadWindow");
              }
            }, 500);
          } else {
            _logWarn("INJECT", `[S3] DB inject failed: ${dbResult.error}`);
          }
        }
      }
    } catch (e) {
      _logWarn("INJECT", "[S2/S3] registerUser+DB fallback failed", e.message);
    }
  }

  // ═══ POST-INJECTION STATE REFRESH SEQUENCE ═══
  // Root cause chain (reverse-engineered 2026-03-20):
  //   1. handleAuthToken → registerUser → new session → restartLS → fireSessionChange
  //   2. But workbench's Zustand store keeps stale quota_exhausted banner (sticky!)
  //   3. cachedPlanInfo in state.vscdb is stale (in-memory state is separate)
  //   4. Status bar "Trial - Quota Exhausted" persists until explicitly cleared
  if (injected) {
    await _postInjectionRefresh();
  }

  return { ok: injected, injected, method };
}

/** Login to account: check credits → inject auth → verify
 *  v11.0: 始终验证会话建立，不跳过(杜绝"Invalid argument"错误的根源) */
async function _loginToAccount(context, index) {
  const account = am.get(index);
  if (!account) return;

  // v11.0: 始终设置activeIndex(即使后续注入失败，也有正确的目标)
  _activeIndex = index;
  context.globalState.update("wam-current-index", index);

  // 快速路径: 只做Firebase登录验证(不调GetPlanStatus，省1-2s)
  // 确保账号凭据有效，避免注入无效token
  try {
    const idToken = await auth.getFreshIdToken(account.email, account.password);
    if (!idToken) {
      _logWarn("LOGIN", `#${index + 1} Firebase登录失败，跳过`);
      return;
    }
  } catch (e) {
    _logWarn("LOGIN", `#${index + 1} 凭据验证失败: ${e.message}`);
    return;
  }

  const apiKeyBefore = _readAuthApiKeyPrefix();
  const injectResult = await injectAuth(context, index);

  if (injectResult.injected) {
    // v11.0: 始终等待会话过渡并验证apiKey变化
    await _waitForSessionTransition();
    const apiKeyAfter = _readAuthApiKeyPrefix();
    const changed = apiKeyBefore !== apiKeyAfter;
    _logInfo(
      "LOGIN",
      `✅ ${injectResult.method} → #${index + 1} | apiKey ${changed ? "CHANGED" : "SAME"}`,
    );
    // 如果apiKey未变，额外等待(Windsurf内部链可能较慢)
    if (!changed) {
      for (let attempt = 1; attempt <= 2; attempt++) {
        await new Promise((r) => setTimeout(r, 1500));
        if (_readAuthApiKeyPrefix() !== apiKeyBefore) break;
      }
    }
  }

  am.incrementLoginCount(index);
  _updatePoolBar();
}

// ========== Auth File Compatibility (v4.0) ==========
// Write windsurf-auth.json + cascade-auth.json for cross-compatibility.
// These files are written by windsurf-assistant and may be read by Windsurf.
// Only called AFTER successful command injection with a valid short authToken.
function _writeAuthFilesCompat(authToken) {
  if (!authToken || authToken.length < 30 || authToken.length > 60) return;
  try {
    const p = process.platform;
    let gsPath;
    if (p === "win32") {
      const appdata =
        process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming");
      gsPath = path.join(appdata, "Windsurf", "User", "globalStorage");
    } else if (p === "darwin") {
      gsPath = path.join(
        os.homedir(),
        "Library",
        "Application Support",
        "Windsurf",
        "User",
        "globalStorage",
      );
    } else {
      gsPath = path.join(
        os.homedir(),
        ".config",
        "Windsurf",
        "User",
        "globalStorage",
      );
    }
    if (!fs.existsSync(gsPath)) return; // don't create dir, must already exist
    const authData = JSON.stringify(
      {
        authToken,
        token: authToken,
        api_key: authToken,
        timestamp: Date.now(),
      },
      null,
      2,
    );
    fs.writeFileSync(path.join(gsPath, "windsurf-auth.json"), authData, "utf8");
    fs.writeFileSync(path.join(gsPath, "cascade-auth.json"), authData, "utf8");
    _logInfo("AUTH", "auth files written for cross-extension compatibility");
  } catch (e) {
    // Non-critical, don't break main flow
    _logWarn("AUTH", "auth file write skipped", e.message);
  }
}

// ========== 号池命令 (v6.0 精简) ==========

/** 刷新号池 — 全部账号额度 + 自动轮转 */
async function _doRefreshPool(context) {
  const accounts = am.getAll();
  if (accounts.length === 0) return;
  statusBar.text = "$(sync~spin) 刷新号池...";
  await _refreshAll((i, n) => {
    statusBar.text = `$(sync~spin) ${i + 1}/${n}...`;
  });
  // 刷新后自动轮转
  const threshold = PREEMPTIVE_THRESHOLD;
  if (
    vscode.workspace.getConfiguration("wam").get("autoRotate", true) &&
    _activeIndex >= 0
  ) {
    const decision = am.shouldSwitch(_activeIndex, threshold);
    if (decision.switch) {
      const best = am.selectOptimal(
        _activeIndex,
        threshold,
        _getOtherWindowAccounts(),
      );
      if (best) await _seamlessSwitch(context, best.index);
    }
  }
  _updatePoolBar();
  _refreshPanel();
}

/** Webview动作处理器 (v6.0 精简) */
function _handleAction(context, action, arg) {
  switch (action) {
    case "login":
      return _seamlessSwitch(context, arg);
    case "checkAccount":
      return _checkAccount(context, arg);
    case "explicitSwitch":
      return _seamlessSwitch(context, arg);
    case "refreshAll":
      return _doRefreshPool(context);
    case "refreshOne":
      return _refreshOne(arg).then(() => {
        _updatePoolBar();
        _refreshPanel();
      });
    case "getCurrentIndex":
      return _activeIndex;
    case "getProxyStatus":
      return auth ? auth.getProxyStatus() : { mode: "?", port: 0 };
    case "getPoolStats":
      return am.getPoolStats(PREEMPTIVE_THRESHOLD);
    case "getActiveQuota":
      return am.getActiveQuota(_activeIndex);
    case "getSwitchCount":
      return _switchCount;
    case "setMode":
      if (auth && arg) {
        auth.setMode(arg);
        context.globalState.update("wam-proxy-mode", arg);
        _updatePoolBar();
        _refreshPanel();
      }
      return;
    case "setProxyPort":
      if (auth && arg) {
        auth.setPort(arg);
        context.globalState.update("wam-proxy-mode", "local");
        _updatePoolBar();
        _refreshPanel();
      }
      return;
    case "reprobeProxy":
      if (auth)
        return auth.reprobeProxy().then((r) => {
          context.globalState.update("wam-proxy-mode", r.mode);
          _updatePoolBar();
          _refreshPanel();
          return r;
        });
      return;
    case "exportAccounts":
      return _doExport(context);
    case "importAccounts":
      return _doImport(context);
    case "resetFingerprint":
      return _doResetFingerprint();
    case "panicSwitch":
      return _doPoolRotate(context, true);
    case "batchAdd":
      return _doBatchAdd(arg);
    case "refreshAllAndRotate":
      return _doRefreshPool(context);
    case "getFingerprint":
      return readFingerprint();
    case "smartRotate":
      return _doPoolRotate(context);
    case "setAutoRotate":
      if (arg !== undefined)
        vscode.workspace
          .getConfiguration("wam")
          .update("autoRotate", !!arg, true);
      return;
  }
}

/** 重置指纹 */
async function _doResetFingerprint() {
  const confirm = await vscode.window.showWarningMessage(
    "重置设备指纹？下次切号时自动热生效(无需重启Windsurf)。",
    "重置",
    "取消",
  );
  if (confirm !== "重置") return;
  const result = resetFingerprint();
  if (result.ok) {
    _lastRotatedIds = result.new;
    vscode.window.showInformationMessage(
      "WAM: ✅ 指纹已重置，下次切号时热生效(无需重启)。",
    );
  } else {
    vscode.window.showErrorMessage(`WAM: 重置失败: ${result.error}`);
  }
}

/** 导入账号 */
async function _doImport(context) {
  const uris = await vscode.window.showOpenDialog({
    canSelectMany: false,
    filters: { "WAM Backup": ["json"] },
    title: "导入号池备份",
  });
  if (!uris || !uris.length) return;
  try {
    const r = am.importFromFile(uris[0].fsPath);
    vscode.window.showInformationMessage(
      `WAM: 导入 +${r.added} ↻${r.updated} =${r.total}`,
    );
    _refreshPanel();
  } catch (e) {
    vscode.window.showErrorMessage(`WAM: 导入失败: ${e.message}`);
  }
}

/** 导出账号 */
async function _doExport(context) {
  if (am.count() === 0) return;
  try {
    const fpath = am.exportToFile(context.globalStorageUri.fsPath);
    vscode.window
      .showInformationMessage(`WAM: ✅ 已导出 ${am.count()} 个账号`, "打开目录")
      .then((sel) => {
        if (sel)
          vscode.commands.executeCommand(
            "revealFileInOS",
            vscode.Uri.file(fpath),
          );
      });
  } catch (e) {
    vscode.window.showErrorMessage(`WAM: 导出失败: ${e.message}`);
  }
}

/** 切换代理模式 */
async function _doSwitchMode(context) {
  const status = auth.getProxyStatus();
  const pick = await vscode.window.showQuickPick(
    [
      {
        label: "$(globe) 本地代理",
        description: `端口 ${status.port}`,
        value: "local",
      },
      { label: "$(cloud) 网络中转", description: "无需VPN", value: "relay" },
    ],
    { placeHolder: `当前: ${status.mode}` },
  );
  if (pick) {
    auth.setMode(pick.value);
    context.globalState.update("wam-proxy-mode", pick.value);
    _updatePoolBar();
    _refreshPanel();
  }
}

/** 批量添加账号 */
async function _doBatchAdd(textFromWebview) {
  let text = textFromWebview;
  if (!text) {
    text = await vscode.window.showInputBox({
      prompt: "粘贴卖家消息，自动识别账号密码",
      placeHolder: "支持: 卡号/卡密 | 账号/密码 | email:pass | email----pass",
      value: "",
    });
  }
  if (!text) return { added: 0, skipped: 0 };

  const result = am.addBatch(text);
  if (result.added > 0) {
    _logInfo("BATCH", `added ${result.added} accounts (smart parse)`);
  }
  _refreshPanel();
  return result;
}

// ========== (v6.0: 旧监控已合并到号池引擎 _poolTick + _startQuotaWatcher) ==========

function _refreshPanel() {
  if (_panelProvider) {
    try {
      _panelProvider.refresh();
    } catch {}
  }
}

// ========== Post-Injection State Refresh (v5.9.0 — 核心锚定点修复) ==========
//
// Reverse-engineered anchoring points (2026-03-20):
//   Anchor 1: provideAuthTokenToAuthProvider → handleAuthToken → registerUser
//             → creates new session → restarts LS → fires onDidChangeSessions
//             → BUT workbench's in-memory state may lag
//   Anchor 2: quota_exhausted banner in Zustand store is STICKY
//             → DVe=Z=>false means client never checks quota locally
//             → banner persists until server returns success on next message
//   Anchor 3: cachedPlanInfo in state.vscdb is separate from in-memory state
//             → deleting DB record doesn't affect loaded workbench state
//
// Solution: Force a complete state refresh chain after confirmed injection.

async function _postInjectionRefresh() {
  try {
    // ═══ v11.0: 统一刷新链 — 始终await，杜绝"Invalid argument"根源 ═══
    // 根因: 旧版urgent模式fire-and-forget → 新session未建立 → 下条消息用旧apiKey → 报错

    // Step 1: 清除旧的cachedPlanInfo(防止Windsurf继续用旧账号数据)
    _clearCachedPlanInfo();

    // Step 2: 强制Windsurf重新获取PlanInfo
    try {
      await vscode.commands.executeCommand("windsurf.updatePlanInfo");
      _logInfo("POST", "forced updatePlanInfo");
    } catch (e) {
      _logWarn("POST", "updatePlanInfo skipped", e.message);
    }

    // Step 3: 等待Windsurf内部刷新完成
    await new Promise((r) => setTimeout(r, 1500));

    // Step 4: 强制刷新auth session(触发re-authentication)
    try {
      await vscode.commands.executeCommand("windsurf.refreshAuthenticationSession");
      _logInfo("POST", "forced refreshAuthenticationSession");
    } catch {
      // Command may not exist in all versions — non-critical
    }

    // Step 5: 验证apiKey已更新
    const newApiKey = _readAuthApiKeyPrefix();
    _logInfo("POST", `apiKey after refresh: ${newApiKey?.slice(0, 16) || "unknown"}`);

    // Step 6: 异步验证热重置(不阻塞后续操作)
    if (_lastRotatedIds) {
      setTimeout(() => {
        try {
          const verify = hotVerify(_lastRotatedIds);
          if (verify.verified) {
            _hotResetVerified++;
            _logInfo("HOT_RESET", `✅ 热重置验证成功 (#${_hotResetVerified}/${_hotResetCount})`);
          }
        } catch {}
      }, 3000);
    }
  } catch (e) {
    _logWarn("POST", "refresh sequence error (non-critical)", e.message);
  }
}

/** Clear cachedPlanInfo from state.vscdb so workbench fetches fresh data from server.
 *  Root cause: after token injection, workbench continues using old account's cached plan. */
function _clearCachedPlanInfo() {
  try {
    const dbPath = path.join(
      process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming"),
      "Windsurf",
      "User",
      "globalStorage",
      "state.vscdb",
    );
    if (!fs.existsSync(dbPath)) return;
    // Use sqlite3 CLI (available on Windows) to clear cache — non-blocking
    try {
      execSync(
        `sqlite3 "${dbPath}" "DELETE FROM ItemTable WHERE key='windsurf.settings.cachedPlanInfo'"`,
        { timeout: 3000, stdio: "pipe" },
      );
      _logInfo("CACHE", "cleared cachedPlanInfo from state.vscdb");
    } catch {
      // sqlite3 CLI not available — try Python fallback
      try {
        execSync(
          `python -c "import sqlite3; db=sqlite3.connect(r'${dbPath}'); db.execute('DELETE FROM ItemTable WHERE key=?',('windsurf.settings.cachedPlanInfo',)); db.commit(); db.close(); print('ok')"`,
          { timeout: 3000, stdio: "pipe" },
        );
        _logInfo("CACHE", "cleared cachedPlanInfo via Python");
      } catch (e2) {
        _logWarn("CACHE", "cache clear skipped (non-critical)", e2.message);
      }
    }
  } catch (e) {
    _logWarn("CACHE", "_clearCachedPlanInfo error", e.message);
  }
}

/** v5.8.0: Direct DB injection — write new apiKey to windsurfAuthStatus in state.vscdb.
 *  This is the MOST RELIABLE injection path, bypassing VS Code command system entirely.
 *  Uses temp file to handle 49KB+ windsurfAuthStatus JSON (too large for CLI args).
 *  Returns { ok, oldPrefix, newPrefix } */
function _dbInjectApiKey(newApiKey) {
  try {
    const dbPath = path.join(
      process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming"),
      "Windsurf",
      "User",
      "globalStorage",
      "state.vscdb",
    );
    if (!fs.existsSync(dbPath))
      return { ok: false, error: "state.vscdb not found" };

    // Step 1: Read current windsurfAuthStatus
    let currentJson;
    try {
      currentJson = execSync(
        `python -c "import sqlite3;db=sqlite3.connect(r'${dbPath}');c=db.cursor();c.execute('SELECT value FROM ItemTable WHERE key=?',('windsurfAuthStatus',));r=c.fetchone();print(r[0] if r else '');db.close()"`,
        { timeout: 5000, encoding: "utf8", maxBuffer: 200 * 1024 },
      ).trim();
    } catch (e) {
      return { ok: false, error: `read failed: ${e.message}` };
    }
    if (!currentJson)
      return { ok: false, error: "windsurfAuthStatus not found" };

    // Step 2: Parse, replace apiKey, write to temp file
    const data = JSON.parse(currentJson);
    const oldPrefix = (data.apiKey || "").substring(0, 20);
    data.apiKey = newApiKey;
    const tmpFile = path.join(os.tmpdir(), `wam_inject_${Date.now()}.json`);
    fs.writeFileSync(tmpFile, JSON.stringify(data), "utf8");

    // Step 3: Write back via Python (handles large values via file read)
    try {
      execSync(
        `python -c "import sqlite3;f=open(r'${tmpFile}','r',encoding='utf-8');v=f.read();f.close();db=sqlite3.connect(r'${dbPath}');db.execute('INSERT OR REPLACE INTO ItemTable(key,value) VALUES(?,?)',('windsurfAuthStatus',v));db.execute('DELETE FROM ItemTable WHERE key=?',('windsurf.settings.cachedPlanInfo',));db.commit();db.close();print('ok')"`,
        { timeout: 5000, encoding: "utf8" },
      );
    } catch (e) {
      try {
        fs.unlinkSync(tmpFile);
      } catch {}
      return { ok: false, error: `write failed: ${e.message}` };
    }
    try {
      fs.unlinkSync(tmpFile);
    } catch {}

    const newPrefix = newApiKey.substring(0, 20);
    _logInfo("DB", `apiKey ${oldPrefix}→${newPrefix}`);
    return { ok: true, oldPrefix, newPrefix };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

/** Read current windsurfAuthStatus apiKey prefix for injection verification */
function _readAuthApiKeyPrefix() {
  try {
    const dbPath = path.join(
      process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming"),
      "Windsurf",
      "User",
      "globalStorage",
      "state.vscdb",
    );
    if (!fs.existsSync(dbPath)) return null;
    const out = execSync(
      `python -c "import sqlite3,json; db=sqlite3.connect(r'${dbPath}'); cur=db.cursor(); cur.execute('SELECT value FROM ItemTable WHERE key=?',('windsurfAuthStatus',)); r=cur.fetchone(); db.close(); d=json.loads(r[0]) if r else {}; print(d.get('apiKey','')[:20])"`,
      { timeout: 3000, encoding: "utf8" },
    ).trim();
    return out || null;
  } catch {
    return null;
  }
}

// ========== Fingerprint Rotation on Switch (v5.10.0→v7.0 热重置核心) ==========
// v5.10.0: serviceMachineId未轮转 → 服务端关联所有账号到同一设备
// v7.0: 轮转移到注入BEFORE → LS重启自动拿新ID = 热重置, requiresRestart=false
// 关键: 此函数必须在injectAuth()的任何injection strategy之前调用

/** Rotate device fingerprint for account switch (v7.0: pre-injection for hot reset) */
function _rotateFingerprintForSwitch() {
  try {
    // Step 1: Rotate in storage.json + machineid file (persists across restarts)
    const result = resetFingerprint({ backup: false }); // no backup on auto-rotate (avoid clutter)
    if (!result.ok) {
      _logWarn("FP", "rotation failed", result.error);
      return;
    }
    const oldId = result.old["storage.serviceMachineId"]?.slice(0, 8) || "?";
    const newId = result.new["storage.serviceMachineId"]?.slice(0, 8) || "?";
    // v7.0: Save new IDs for post-injection hot verification
    _lastRotatedIds = result.new;
    _logInfo("FP", `rotated — ${oldId}→${newId} (saved for hot verify)`);

    // Step 2: Also update state.vscdb for runtime effect
    // (LS may re-read serviceMachineId on next request or after restart)
    const dbPath = path.join(
      process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming"),
      "Windsurf",
      "User",
      "globalStorage",
      "state.vscdb",
    );
    if (!fs.existsSync(dbPath)) return;

    // Build key-value pairs for DB update (UUIDs/hex only — safe for direct embedding)
    const dbKeys = [
      "storage.serviceMachineId",
      "telemetry.devDeviceId",
      "telemetry.machineId",
      "telemetry.macMachineId",
      "telemetry.sqmId",
    ];
    const pyPairs = dbKeys
      .filter((k) => result.new[k])
      .map((k) => `('${result.new[k]}','${k}')`)
      .join(",");

    if (!pyPairs) return;

    try {
      execSync(
        `python -c "import sqlite3;db=sqlite3.connect(r'${dbPath}');c=db.cursor();[c.execute('UPDATE ItemTable SET value=? WHERE key=?',p) for p in [${pyPairs}]];db.commit();db.close()"`,
        { timeout: 5000, stdio: "pipe" },
      );
      _logInfo("FP", "state.vscdb updated (runtime-effective)");
    } catch (e) {
      _logWarn("FP", "state.vscdb skip (non-critical)", e.message);
    }
  } catch (e) {
    _logWarn("FP", "error (non-critical)", e.message);
  }
}

// ========== Init Workspace (智慧部署 + 源启动) ==========

async function _doInitWorkspace(context) {
  // Get workspace path
  const wsFolders = vscode.workspace.workspaceFolders;
  const defaultPath =
    wsFolders && wsFolders.length > 0 ? wsFolders[0].uri.fsPath : "";

  const targetPath = await vscode.window.showInputBox({
    prompt: "目标工作区路径 (智慧部署)",
    placeHolder: defaultPath || "输入工作区绝对路径",
    value: defaultPath,
  });
  if (targetPath === undefined) return;

  const action = await vscode.window.showQuickPick(
    [
      { label: "🔍 扫描", description: "查看智慧模板安装状态", value: "scan" },
      {
        label: "⬇ 注入智慧框架",
        description: "部署规则+技能+工作流到目标工作区",
        value: "inject",
      },
      {
        label: "⬇ 注入(覆盖)",
        description: "覆盖已有文件重新注入",
        value: "inject_overwrite",
      },
      {
        label: "✨ 生成源启动提示词",
        description: "生成激活认知框架的初始提示词",
        value: "prompt",
      },
      {
        label: "🖥 检测环境",
        description: "检测IDE/OS/MCP/Python环境",
        value: "detect",
      },
      {
        label: "🌐 打开智慧部署器",
        description: "在浏览器打开 http://localhost:9876/",
        value: "browser",
      },
    ],
    { placeHolder: "选择操作", title: "工作区配置向导" },
  );

  if (!action) return;

  if (action.value === "browser") {
    vscode.env.openExternal(vscode.Uri.parse("http://localhost:9876/"));
    vscode.window.showInformationMessage(
      "WAM: 已打开智慧部署器 (需先启动: python 安全管理/windsurf_wisdom.py serve)",
    );
    return;
  }

  const base = "http://127.0.0.1:9876";
  const targ = targetPath.trim();

  const callApi = (apiPath, method = "GET", body = null) =>
    new Promise((resolve, reject) => {
      const url = new URL(base + apiPath);
      const bodyStr = body ? JSON.stringify(body) : null;
      const options = {
        hostname: url.hostname,
        port: parseInt(url.port) || 80,
        path: url.pathname + url.search,
        method,
        headers: bodyStr
          ? {
              "Content-Type": "application/json",
              "Content-Length": Buffer.byteLength(bodyStr),
            }
          : {},
        timeout: 10000,
      };
      const req = http.request(options, (res) => {
        let data = "";
        res.on("data", (d) => {
          data += d;
        });
        res.on("end", () => {
          try {
            resolve(JSON.parse(data));
          } catch {
            resolve({ raw: data });
          }
        });
      });
      req.on("error", reject);
      req.on("timeout", () => {
        req.destroy();
        reject(new Error("timeout"));
      });
      if (bodyStr) req.write(bodyStr);
      req.end();
    });

  const tq = targ ? "?target=" + encodeURIComponent(targ) : "";

  try {
    if (action.value === "scan") {
      const r = await callApi("/api/scan" + tq);
      const ins = (r.exists || []).length;
      const mis = (r.missing || []).length;
      vscode.window
        .showInformationMessage(
          `WAM: 扫描 — ${ins}已安装 / ${mis}缺失\n${(r.missing || [])
            .slice(0, 5)
            .map((x) => "❌ " + x.key)
            .join(", ")}`,
          mis > 0 ? "注入缺失项" : "已完整",
        )
        .then((sel) => {
          if (sel === "注入缺失项") _doInitWorkspace(context);
        });
    } else if (
      action.value === "inject" ||
      action.value === "inject_overwrite"
    ) {
      const r = await callApi("/api/inject", "POST", {
        target: targ || undefined,
        overwrite: action.value === "inject_overwrite",
      });
      vscode.window.showInformationMessage(
        `WAM: 注入完成 — ${r.summary}\n注入项: ${(r.injected || [])
          .slice(0, 8)
          .map((x) => x.key)
          .join(", ")}`,
      );
    } else if (action.value === "prompt") {
      const r = await callApi("/api/prompt" + tq);
      const prompt = r.prompt || "";
      await vscode.env.clipboard.writeText(prompt);
      vscode.window
        .showInformationMessage(
          `WAM: 源启动提示词已生成并复制到剪贴板！(${r.ide} / ${(r.installed.rules || []).length}规则 / ${(r.installed.skills || []).length}技能)`,
          "打开智慧部署器",
        )
        .then((sel) => {
          if (sel === "打开智慧部署器")
            vscode.env.openExternal(vscode.Uri.parse("http://localhost:9876/"));
        });
    } else if (action.value === "detect") {
      const r = await callApi("/api/detect" + tq);
      const mcps = Object.entries(r.mcps_installed || {})
        .map(([k, v]) => (v ? "✅" : "❌") + k)
        .join(" ");
      vscode.window.showInformationMessage(
        `WAM: 环境 — IDE:${r.ide} OS:${r.os} Python:${r.python_ok ? "✅" : "❌"} 安全中枢:${r.security_hub_running ? "✅" : "❌"}\nMCP: ${mcps}`,
      );
    }
  } catch (e) {
    // Server unavailable → fall back to embedded bundle injection
    if (
      action.value === "inject" ||
      action.value === "inject_overwrite" ||
      action.value === "scan"
    ) {
      await _doEmbeddedWisdom(context, targ, action.value);
    } else {
      const choice = await vscode.window.showWarningMessage(
        "WAM: 智慧部署服务未运行。已切换到内置模板模式。\n可直接注入47个智慧模板(规则+技能+工作流)。",
        "内置注入",
        "启动服务器",
        "取消",
      );
      if (choice === "内置注入") {
        await _doEmbeddedWisdom(context, targ, "inject");
      } else if (choice === "启动服务器") {
        const terminal = vscode.window.createTerminal("智慧部署器");
        terminal.sendText("python 安全管理/windsurf_wisdom.py serve");
        terminal.show();
      }
    }
  }
}

// ========== Embedded Wisdom Bundle (离线注入, 无需Python服务器) ==========

/** Load wisdom_bundle.json from extension directory */
function _loadWisdomBundle(context) {
  try {
    const bundlePath = path.join(
      path.dirname(__dirname),
      "data",
      "wisdom_bundle.json",
    );
    // Try extension's own src/ first (dev mode)
    if (fs.existsSync(bundlePath)) {
      return JSON.parse(fs.readFileSync(bundlePath, "utf8"));
    }
    // Try installed extension path
    const extPath = context.extensionPath || context.extensionUri?.fsPath;
    if (extPath) {
      const altPath = path.join(extPath, "data", "wisdom_bundle.json");
      if (fs.existsSync(altPath)) {
        return JSON.parse(fs.readFileSync(altPath, "utf8"));
      }
    }
  } catch (e) {
    _logError("WISDOM", "failed to load wisdom bundle", e.message);
  }
  return null;
}

/** Embedded wisdom operations: scan, inject, inject_overwrite */
async function _doEmbeddedWisdom(context, targetPath, action) {
  const bundle = _loadWisdomBundle(context);
  if (!bundle || !bundle.templates) {
    vscode.window.showErrorMessage("WAM: 智慧模板包未找到。请重新安装插件。");
    return;
  }

  const root =
    targetPath || vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || "";
  if (!root) {
    vscode.window.showWarningMessage("WAM: 未指定目标工作区。");
    return;
  }

  const templates = bundle.templates;
  const overwrite = action === "inject_overwrite";

  if (action === "scan") {
    // Scan: check which templates exist in target
    let exists = 0,
      missing = 0;
    const missingList = [];
    for (const [key, tmpl] of Object.entries(templates)) {
      const fpath = path.join(root, tmpl.path);
      if (fs.existsSync(fpath)) {
        exists++;
      } else {
        missing++;
        missingList.push(key);
      }
    }
    const sel = await vscode.window.showInformationMessage(
      `WAM: 扫描(内置) — ${exists}已安装 / ${missing}缺失 / ${Object.keys(templates).length}总计\n` +
        `缺失: ${missingList.slice(0, 8).join(", ")}${missingList.length > 8 ? "..." : ""}`,
      missing > 0 ? "注入缺失项" : "已完整",
    );
    if (sel === "注入缺失项") {
      await _doEmbeddedWisdom(context, root, "inject");
    }
    return;
  }

  // Inject: select categories
  const catPick = await vscode.window.showQuickPick(
    [
      {
        label: "🌟 全部注入",
        description: `${Object.keys(templates).length}个模板`,
        value: "all",
      },
      {
        label: "📐 仅规则",
        description: "kernel + protocol (Agent行为框架)",
        value: "rule",
      },
      {
        label: "🎯 仅技能",
        description: "32个通用技能 (错误诊断/代码质量/Git等)",
        value: "skill",
      },
      {
        label: "🔄 仅工作流",
        description: "13个工作流 (审查/循环/开发等)",
        value: "workflow",
      },
      {
        label: "🔧 选择性注入",
        description: "手动选择要注入的模板",
        value: "pick",
      },
    ],
    { placeHolder: `注入到: ${root}`, title: "选择注入范围" },
  );
  if (!catPick) return;

  let selectedKeys;
  if (catPick.value === "all") {
    selectedKeys = Object.keys(templates);
  } else if (catPick.value === "pick") {
    const items = Object.entries(templates).map(([key, tmpl]) => ({
      label: `${tmpl.category === "rule" ? "📐" : tmpl.category === "skill" ? "🎯" : "🔄"} ${key}`,
      description: tmpl.desc.slice(0, 60),
      picked: true,
      key,
    }));
    const picked = await vscode.window.showQuickPick(items, {
      canPickMany: true,
      placeHolder: "选择要注入的模板",
      title: `${items.length}个可用模板`,
    });
    if (!picked || picked.length === 0) return;
    selectedKeys = picked.map((p) => p.key);
  } else {
    selectedKeys = Object.entries(templates)
      .filter(([_, t]) => t.category === catPick.value)
      .map(([k]) => k);
  }

  // Execute injection
  let injected = 0,
    skipped = 0,
    errors = 0;
  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "WAM: 注入智慧模板",
      cancellable: false,
    },
    async (progress) => {
      for (let i = 0; i < selectedKeys.length; i++) {
        const key = selectedKeys[i];
        const tmpl = templates[key];
        if (!tmpl) continue;
        progress.report({
          message: `${key} (${i + 1}/${selectedKeys.length})`,
          increment: 100 / selectedKeys.length,
        });

        const fpath = path.join(root, tmpl.path);
        if (fs.existsSync(fpath) && !overwrite) {
          skipped++;
          continue;
        }

        try {
          const dir = path.dirname(fpath);
          if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
          fs.writeFileSync(fpath, tmpl.content, "utf8");
          // Write supporting files if any
          if (tmpl.supporting) {
            const parentDir = path.dirname(fpath);
            for (const [sfName, sfContent] of Object.entries(tmpl.supporting)) {
              fs.writeFileSync(path.join(parentDir, sfName), sfContent, "utf8");
            }
          }
          injected++;
        } catch (e) {
          errors++;
          _logError("WISDOM", `inject ${key} failed`, e.message);
        }
      }
    },
  );

  vscode.window.showInformationMessage(
    `WAM: 注入完成 — ${injected}成功 / ${skipped}跳过 / ${errors}失败\n` +
      `路径: ${root}/.windsurf/`,
  );
}

function deactivate() {
  _deregisterWindow();
  if (_poolTimer) { clearTimeout(_poolTimer); _poolTimer = null; }
  if (_windowTimer) { clearInterval(_windowTimer); _windowTimer = null; }
  if (_hubServer) { try { _hubServer.close(); } catch {} _hubServer = null; }
  if (am) am.dispose();
  if (auth) auth.dispose();
  if (statusBar) statusBar.dispose();
}

module.exports = { activate, deactivate };
