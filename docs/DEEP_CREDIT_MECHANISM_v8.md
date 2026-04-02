# Windsurf 计费系统 — 终极逆向解构 v8.0

> 日期: 2026-03-20 | 版本: Windsurf v1.108.2 | workbench.js + extension.js 源码级逆向

---

## 〇、核心结论

### Q: 今天(3/20)Windsurf是否降低了每个对话消耗的LLM上限？

**是。3月18日Windsurf发布定价改革,3月19日起生效,新旧体系由服务端`BillingStrategy`枚举控制：**

```javascript
// 一切的根源 — PlanInfo.billing_strategy (protobuf field no:35)
BillingStrategy {
  UNSPECIFIED = 0,
  CREDITS     = 1,  // 旧: 固定积分 × creditMultiplier
  QUOTA       = 2,  // 新: 日+周百分比配额
  ACU         = 3,  // 新: AI Compute Units token级精确计费
}
```

| 维度 | 旧体系 CREDITS | 新体系 QUOTA/ACU |
|------|---------------|------------------|
| **计费单位** | Credits整数 (÷100) | 日/周百分比 + ACU浮点(.toFixed(4)) |
| **刷新周期** | 月度 (10000积分) | **日+周双重刷新** (dailyQuotaResetAtUnix / weeklyQuotaResetAtUnix) |
| **模型成本** | creditMultiplier固定倍率 | ACU按实际token消耗 |
| **超限处理** | 购买add-on积分 | 购买extra usage (overageBalanceMicros, 美元÷1M) |
| **本质差异** | 固定扣费,不管用多少token | **按token精确计费 → 输出越多扣越多** |

**核心影响**: 新体系下同一模型同一对话,输出更多tokens = 消耗更多配额百分比/ACU。日配额更快耗尽 = 变相降低每日有效LLM输出上限。

---

## 一、六层计费架构 (源码级完整逆向)

### Layer 0: BillingStrategy决策层 (最顶层 — 决定走哪条路)

```javascript
// workbench.js中的核心判断函数
AF = Z => Z?.billingStrategy === mn.QUOTA  // 是否为配额制

// UI分支: billingStrategy === "quota" → $Had(配额组件) : $Gad(积分组件)
// 服务端通过PlanInfo.billing_strategy告知客户端使用哪种计费
```

### Layer 1: Token计数层 (最底层原子)

```protobuf
exa.codeium_common_pb.ModelUsageStats {
  1: model_deprecated (enum Model)
  9: model_uid (string)
  2: input_tokens (uint64)                 // ← 输入token数
  3: output_tokens (uint64)                // ← 输出token数
  4: cache_write_tokens (uint64)           // prompt cache写入
  5: cache_read_tokens (uint64)            // prompt cache命中
  6: api_provider (enum APIProvider)
}
```

**一切计费的原子层**。每次LLM调用产生ModelUsageStats。

### Layer 2: LLM调用层 (每次模型调用)

```protobuf
exa.cortex_pb.ChatModelMetadata {
  1:  system_prompt (string)
  2:  message_prompts (repeated)
  10: message_metadata (repeated)
  3:  model_deprecated → 15: model_uid (string)
  4:  usage (ModelUsageStats)              // ← 引用Layer 1
  5:  model_cost (float)                   // API美元成本
  6:  last_cache_index (uint32)            // 缓存断点
  7:  tool_choice (message)
  8:  tools (repeated)
  9:  chat_start_metadata (message)
  11: time_to_first_token (Duration)
  12: streaming_duration (Duration)
  13: credit_cost (int32)                  // ← 旧积分成本 (÷100)
  14: retries (uint32)
  16: acu_cost (float)                     // ← 新! ACU成本 (浮点精度!)
}
```

### Layer 3: Step元数据层 (每个执行步骤)

```protobuf
exa.cortex_pb.CortexStepMetadata {
  21: step_generation_version (uint32)
  1:  created_at (Timestamp)
  6:  viewable_at (Timestamp)
  7:  finished_generating_at (Timestamp)
  22: last_completed_chunk_at (Timestamp)
  8:  completed_at (Timestamp)
  3:  source (enum CortexStepSource)
  4:  tool_call (ChatToolCall)
  5:  arguments_order (repeated string)
  9:  model_usage (ModelUsageStats)        // ← 引用Layer 1
  10: model_cost (float)
  11→27: generator_model_uid (string)      // 实际执行的模型
  13→28: requested_model_uid (string)      // 用户请求的模型
  12: execution_id (string)
  14: flow_credits_used (int32)
  15: prompt_credits_used (int32)          // ← 旧积分 (÷100=显示值)
  26: planner_mode (enum)
  18: non_standard_credit_reasons (repeated enum)
  16: tool_call_choices (repeated ChatToolCall)
  17: tool_call_choice_reason (string)
  19: cortex_request_source (enum)
  23: tool_call_output_tokens (int32)      // ← 工具调用的输出token
  20: source_trajectory_step_info (message)
  24: request_id (string)
  25: cumulative_tokens_at_step (uint64)   // ← 新! 累计token总数!
  29: acu_cost (float)                     // ← 新! Step级ACU成本
}
```

### Layer 4: 执行器层 (对话级)

```protobuf
exa.cortex_pb.ExecutorMetadata {
  1: termination_reason (enum)             // 0-7终止原因
  2: num_generator_invocations (int32)     // 服务端invocation计数
  3: last_step_idx (int32)
  4: proceeded_with_auto_continue (bool)
}
```

### Layer 5: 计划层 (账户级 — 新旧并存的完整结构)

```protobuf
exa.codeium_common_pb.PlanInfo {
  2:  plan_name (string)                   // "Trial"/"Pro"/"Teams"/"Max"
  6:  max_num_premium_chat_messages (int64)
  7:  max_num_chat_input_tokens (int64)    // ← 输入token硬上限!
  12: monthly_prompt_credits (int32)       // 旧体系月度积分
  13: monthly_flow_credits (int32)
  14: monthly_flex_credit_purchase_amount (int32)
  18: can_buy_more_credits (bool)
  35: billing_strategy (enum BillingStrategy)  // ← 新! 决定计费模式!
  ...
}

exa.codeium_common_pb.PlanStatus {
  1:  plan_info (PlanInfo)
  2:  plan_start (Timestamp)
  3:  plan_end (Timestamp)
  // === 旧积分字段 ===
  8:  available_prompt_credits (int32)
  9:  available_flow_credits (int32)
  4:  available_flex_credits (int32)
  7:  used_flex_credits (int32)
  5:  used_flow_credits (int32)
  6:  used_prompt_credits (int32)
  10: top_up_status (TopUpStatus)
  11: was_reduced_by_orphaned_usage (bool)
  12: grace_period_status (enum GracePeriodStatus)
  13: grace_period_end (Timestamp)
  // === 新配额字段 ===
  14: daily_quota_remaining_percent (int32)   // ← 日配额剩余百分比!
  15: weekly_quota_remaining_percent (int32)  // ← 周配额剩余百分比!
  16: overage_balance_micros (int64)          // ← 超额余额(美分÷1M)!
  17: daily_quota_reset_at_unix (int64)       // ← 日配额重置时间戳!
  18: weekly_quota_reset_at_unix (int64)      // ← 周配额重置时间戳!
}
```

---

## 二、新旧计费本质对比

### 旧体系: CREDITS (BillingStrategy=1) + STATIC_CREDIT (ModelPricingType=1)

```
用户发消息 → sendCascadeInput
  → 服务端: 1 credit × creditMultiplier (整数)
  → 客户端: promptCreditsUsed ÷ 100 = 显示积分
  → 剩余 = monthlyPromptCredits - usedPromptCredits + availableFlexCredits - usedFlexCredits
  → 每prompt ~25 invocations (服务端硬限)
  → 超限 → MAX_INVOCATIONS → Continue = 再扣1×multiplier
```

**核心**: **固定扣费**。Opus 4.5用500 tokens和50000 tokens = 同样扣4积分。

### 新体系: QUOTA (BillingStrategy=2) + ACU_TOKEN/ACU_CREDIT (ModelPricingType=4/5)

```
用户发消息 → sendCascadeInput
  → 服务端: 按实际token消耗计算ACU + 扣减配额百分比
  → ACU = f(input_tokens, output_tokens, cache_tokens, model_rate)
  → 客户端: acuCost (float, .toFixed(4)) + dailyQuotaRemainingPercent + weeklyQuotaRemainingPercent
  → 日+周双重配额限制 (取min值)
  → 配额耗尽 → 购买extra usage (overageBalanceMicros, formatMicrosAsUsd: $÷1M)
```

**核心**: **按token精确计费**。用更多token = 消耗更多配额/ACU。

### 客户端双轨显示逻辑 (workbench.js逆向)

```javascript
// === 总览: UI组件分支 ===
// billingStrategy === "quota" → 实例化$Had (配额组件)
// billingStrategy !== "quota" → 实例化$Gad (积分组件)

// === 对话统计面板: ACU vs Credits ===
(Ie?.acuCost ?? 0) > 0 
  ? "ACUs spent"           // 新: 显示ACU
  : "Credits spent"        // 旧: 显示积分
(Ie?.acuCost ?? 0) > 0
  ? (Ie?.acuCost ?? 0).toFixed(4)   // ACU: 4位小数
  : Ie?.creditsSpent                // 积分: 整数

// === 配额面板($Had) ===
// daily_used% = Math.max(0, Math.min(100, 100 - dailyRemainingPercent))
// weekly_used% = Math.max(0, Math.min(100, 100 - weeklyRemainingPercent))
// extra_usage = formatMicrosAsUsd(overageBalanceMicros) = `$${(micros/1e6).toFixed(2)}`
// reset_time = new Date(unix * 1000).toLocaleString(...)

// === 配额警告逻辑 ===
// quota_exhausted: daily≤0 || weekly≤0, 无overage → "Purchase extra usage"
// quota_exhausted_with_overage: 有overage余额 → "Using your extra usage. Quota resets {time}"
// low_quota: "You've used {100-min(daily,weekly)}% of your quota"

// === 剩余积分计算($Gad, 旧体系) ===
dye = (planInfo, planStatus) => 
  planInfo.monthlyPromptCredits === -1 
    ? MAX_SAFE_INTEGER  // Enterprise无限
    : Math.max(0, monthlyPromptCredits - usedPromptCredits + availableFlexCredits - usedFlexCredits)

// === 配额剩余计算(新体系) ===
vpe = Z => Math.min(Z.dailyQuotaRemainingPercent, Z.weeklyQuotaRemainingPercent)
ype = Z => { // 下次重置时间
  daily≤0 && weekly≤0 ? Math.max(dailyResetUnix, weeklyResetUnix)
  : weekly < daily ? weeklyResetUnix : dailyResetUnix
}
```

---

## 三、完整枚举体系 (计费根源)

```javascript
// === 账户级计费策略 (PlanInfo.billing_strategy) ===
BillingStrategy {
  UNSPECIFIED = 0,
  CREDITS     = 1,  // 旧: 月度积分制
  QUOTA       = 2,  // 新: 日+周百分比配额
  ACU         = 3,  // 新: ACU精确计费
}

// === 模型级定价类型 ===
ModelPricingType {
  UNSPECIFIED   = 0,
  STATIC_CREDIT = 1,  // 旧: 固定积分 × creditMultiplier
  API           = 2,  // API定价: 按token美元成本
  BYOK          = 3,  // 自带Key: 0 Windsurf成本
  ACU_TOKEN     = 4,  // 新: ACU按token计费
  ACU_CREDIT    = 5,  // 新: ACU+积分混合
}

// === 模型成本层级 ===
ModelCostTier {
  UNSPECIFIED = 0,
  LOW         = 1,
  MEDIUM      = 2,
  HIGH        = 3,
  FREE        = 4,
}

// === 执行器终止原因 ===
ExecutorTerminationReason {
  UNSPECIFIED          = 0,
  ERROR                = 1,
  USER_CANCELED        = 2,
  MAX_INVOCATIONS      = 3,  // ← 唯一触发Continue
  NO_TOOL_CALL         = 4,  // 自然结束
  HALTED_STEP          = 5,
  HOOK_BLOCKED         = 6,
  ARENA_INVOCATION_CAP = 7,
}
```

---

## 四、Token计数的本质 (计费原子)

### 4.1 每次LLM调用的token计数

```
total_cost_per_call = f(
  input_tokens,          // 输入: system_prompt + context + history + user_msg
  output_tokens,         // 输出: 模型生成的文本 + tool_calls
  cache_write_tokens,    // 缓存写入 (首次调用的prompt)
  cache_read_tokens,     // 缓存命中 (后续调用复用的prompt)
  model_rate             // 模型定价率 (不同模型不同)
)
```

### 4.2 cumulative_tokens_at_step (新字段!)

这是**3/18新增的关键字段**,追踪整个对话过程中的**累计token消耗**:

```
Step 1: input=5000, output=2000 → cumulative = 7000
Step 2: input=7000, output=3000 → cumulative = 17000
Step 3: input=10000, output=1000 → cumulative = 28000
...
```

**这个字段的存在意味着**: 服务端在**实时追踪每个对话的总token消耗**,并可能基于此做出限制决策。

### 4.3 max_num_chat_input_tokens (PlanInfo中的硬上限)

```protobuf
PlanInfo.max_num_chat_input_tokens (int64)
```

这是**服务端对每次聊天输入token的硬上限**。在新配额体系下,这个值决定了:
- 你能发送多长的上下文
- 你的对话能累积多长的历史

---

## 五、25 Invocation硬限制的真相

### 终止原因链 (完整)

```javascript
ExecutorTerminationReason {
  UNSPECIFIED           = 0,  // 未指定
  ERROR                 = 1,  // 错误
  USER_CANCELED         = 2,  // 用户取消
  MAX_INVOCATIONS       = 3,  // ← 触发Continue的唯一原因
  NO_TOOL_CALL          = 4,  // 模型未调用工具 = 自然结束
  HALTED_STEP           = 5,  // 步骤被停止
  HOOK_BLOCKED          = 6,  // Hook阻断
  ARENA_INVOCATION_CAP  = 7,  // Arena模式上限
}
```

### Invocation计数的本质

```
1 generator invocation = 1次LLM生成
  可以包含N个并行tool calls (1 invocation)
  也可以只有文本输出 (1 invocation)

服务端硬限 ≈ 25 invocations/prompt
客户端 maxGeneratorInvocations = 9999 (P1-P3 patch)
实际限制 = min(client, server) = ~25
```

**新体系下的变化**: 25 invocation限制可能仍然存在,但**真正的限制变成了ACU消耗**。即使你有25次invocation机会,如果ACU消耗完了,你就必须等配额刷新或购买额外用量。

---

## 六、3/18定价改革完整逆向

### 6.1 服务端双轨切换机制

```
服务端PlanInfo.billing_strategy 决定:
  CREDITS → 客户端实例化$Gad(积分面板), 显示"credits left"
  QUOTA   → 客户端实例化$Had(配额面板), 显示daily%/weekly%/extra usage
  ACU     → 两者混合,对话统计显示ACU cost
```

当前v1.108.2客户端**已完全支持双轨**,服务端按账户/计划推送不同BillingStrategy:
- Trial用户可能仍为CREDITS
- Pro新用户/迁移用户为QUOTA
- 企业用户可能为ACU

### 6.2 配额面板完整UI逆向

```
$Had (配额面板):
  Daily quota usage:  {100 - dailyRemainingPercent}%
  Weekly quota usage: {100 - weeklyRemainingPercent}%
  Extra usage balance: ${overageBalanceMicros / 1,000,000}
  [Resets: {date from unix timestamp}]

$Gad (积分面板):
  {remainingMessages + remainingFlexCredits} credits left
  prompt credits left: {remainingMessages}/{messages}
  add-on credits available: {remainingFlexCredits}
  [Purchase Credits] [Enable Auto-Refill]
```

### 6.3 对现有逆向体系的影响

| 逆向成果 | CREDITS体系 | QUOTA体系 |
|----------|------------|----------|
| P1-P3 maxGen=9999 | 有效 | **仍有效** (invocation独立) |
| P4 AutoContinue | 有效 | **仍有效** (Continue机制不变) |
| SWE-1.5 0x免费 | 有效 | **待验证** (可能按ACU计费) |
| BYOK 0积分 | 有效 | **仍有效** (BYOK独立) |
| Telemetry重置 | 有效 | **风险更高** (配额绑定账户) |

### 6.4 新体系对用户的本质影响

**旧体系**: Opus 4.5一条消息 = 固定4积分,不管token多少
**新体系**: 按实际token计费,context越大每条消息越贵
**关键推论**: 在QUOTA体系下,**减少system prompt token = 直接省钱**

---

## 七、对你的直接影响与应对策略

### 7.1 最优应对 (按优先级)

| 优先级 | 策略 | 原因 |
|--------|------|------|
| **P0** | **BYOK** | 完全绕过Windsurf计费,自付API费 |
| **P1** | **SWE-1.5执行** | 如果新体系中仍然0 ACU |
| **P2** | **减少Context膨胀** | 新体系按token计费,context越大每条消息越贵 |
| **P3** | **精简Rules/Memories** | Always-On rules = 每条消息的固定token税 |
| **P4** | **并行tool calls** | 1 invocation = N parallel calls,减少总invocations |
| **P5** | **选择高性价比模型** | 新体系下不同模型的ACU/token率不同 |

### 7.2 Token税概念 (新体系独有)

```
每条消息的固定token税 =
  Layer 0: System Identity           ≈ 4000 tokens
  Layer 1: Global Rules              ≈ 1500 tokens
  Layer 2: Always-On Rules (kernel)  ≈ 1800 tokens
  Layer 3: Always-On Rules (protocol)≈ 2200 tokens
  Layer 4: Workspace Info            ≈ 2500 tokens
  Layer 5: Retrieved Memories        ≈ 5000-20000 tokens (!)
  ────────────────────────────────────
  总固定税: ≈ 17000-32000 tokens/消息

在旧体系下: 这些token"免费" (固定积分制)
在新体系下: 这些token每条消息都消耗ACU!
```

**这意味着**: 清理不需要的Memories、将always_on规则改为model_decision,在新体系下有**直接的经济价值**。

---

## 八、实测数据 — 当前账户实际状态 (state.vscdb逆向提取)

```json
// 来源: globalStorage/state.vscdb → windsurf.settings.cachedPlanInfo
{
  "planName": "Trial",
  "billingStrategy": "quota",              // ← 已切换到QUOTA配额制!
  "startTimestamp": 1773891784000,         // 2026-03-17T02:56:24Z
  "endTimestamp": 1775101384000,           // 2026-03-31T02:56:24Z
  "usage": {
    "duration": 12,                        // 剩余12天
    "messages": 10000,                     // 旧字段:总积分(保留兼容)
    "usedMessages": 3600,                  // 旧字段:已用积分
    "remainingMessages": 6400,             // 旧字段:剩余积分
    "flowActions": 20000,
    "usedFlowActions": 0,
    "remainingFlowActions": 20000,
    "flexCredits": 0,
    "usedFlexCredits": 0,
    "remainingFlexCredits": 0
  },
  "hasBillingWritePermissions": true,
  "gracePeriodStatus": 1,                  // NONE = 无宽限期
  "quotaUsage": {                          // ← 新配额字段!
    "dailyRemainingPercent": 100,          // 今日配额100%未用
    "weeklyRemainingPercent": 100,         // 本周配额100%未用
    "overageBalanceMicros": 0,             // 无超额购买
    "dailyResetAtUnix": 1774080000,        // 日重置时间戳
    "weeklyResetAtUnix": 1774166400        // 周重置时间戳
  }
}
```

### 关键发现

1. **Trial账户已切换到QUOTA** — billingStrategy="quota" 而非 "credits"
2. **双轨并行** — 旧的messages/usedMessages字段保留(兼容),新的quotaUsage字段同时存在
3. **配额以百分比表示** — 不透露绝对值,只显示0-100%
4. **日+周双重限制** — dailyResetAtUnix和weeklyResetAtUnix独立刷新
5. **超额以微美元计** — overageBalanceMicros = 0 (未购买extra usage)

---

## 九、客户端门禁与Fail-Open设计 (INFINITE_CREDITS逆向融合)

### 9.1 MBe函数 — ACU模型成本映射为"无"

```javascript
// workbench.desktop.main.js offset ~17833084
function MBe(Z) {
  const B = Z.pricingType;
  switch(B) {
    case Vn.STATIC_CREDIT: {
      const j = Z.creditMultiplier;
      return j < 0 ? {type:"none"} : j === 0 ? {type:"free"} : {type:"credit", multiplier:j};
    }
    case Vn.API:       return {type:"api"};
    case Vn.BYOK:      return {type:"byok"};
    case Vn.ACU_TOKEN:                    // ← 新ACU按token计费
    case Vn.ACU_CREDIT:                   // ← 新ACU积分混合
    case Vn.UNSPECIFIED:                  // ← 未指定
      return {type:"none"};              // ← 全部映射为"无成本"!!!
  }
}
```

**影响**: 所有ACU定价模型在模型选择器中不显示任何成本标签。

### 9.2 S5t计算 — 三条通往无限的路径

```javascript
S5t = useMemo(() =>
  Ep === void 0 || Ep.planInfo === void 0
    ? Number.MAX_SAFE_INTEGER              // ← planStatus/planInfo未定义 = 无限!
    : rye(Ep.planInfo, Ep),
  [Ep]
)

// rye: 旧积分公式
iye = Z => Z === -1                        // -1 = 企业版无限
rye = (Z, B) => iye(Z.monthlyPromptCredits)
  ? Number.MAX_SAFE_INTEGER
  : Math.max(0, (Z.monthlyPromptCredits - B.usedPromptCredits)
      + (B.availableFlexCredits - B.usedFlexCredits))
```

**三条无限路径**: planStatus undefined / planInfo undefined / monthlyPromptCredits === -1

### 9.3 Fail-Open门禁 (try/catch静默放行)

```javascript
// sendMessage函数中的两个门禁:

// 门禁1: 模型容量检查 (仅isCapacityLimited时)
if (q4.isCapacityLimited) try {
  const Pu = await j.checkChatCapacity({metadata:B(), modelUid:q4.modelUid});
  if (!Pu.hasCapacity) return false;
} catch(Pu) {
  console.warn("Failed to check chat capacity:", Pu);
  // ← 失败: 静默放行!
}

// 门禁2: 用户消息速率限制
try {
  const Q1 = await j.checkUserMessageRateLimit({metadata:Pu, modelUid:q4.modelUid});
  if (!Q1.hasCapacity) return false;
} catch(Pu) {
  console.warn("Failed to check user message rate limit:", Pu);
  // ← 失败: 静默放行!
}
```

**canSendMessage(O5t)只检查Arena模式**，无任何客户端级积分检查。

### 9.4 CheckUserMessageRateLimit Protobuf

```protobuf
// 请求
exa.language_server_pb.CheckUserMessageRateLimitRequest {
  1: metadata (GetCompletionMetadata)
  3: model_uid (string)
}
// 响应 — 新配额系统的唯一执行点
exa.language_server_pb.CheckUserMessageRateLimitResponse {
  1: has_capacity (bool)                  // ← 唯一门禁! true=放行
  2: message (string)
  3: messages_remaining (int32)
  4: max_messages (int32)
  5: resets_in_seconds (int64)            // 配额刷新倒计时
}
```

### 9.5 服务端三层防御体系

```
Layer 1: 输入区错误状态 (UI级, REACTIVE)
  ├── WRITE_CHAT_INSUFFICIENT_CASCADE_CREDITS → 阻止发送
  ├── 来源: CortexErrorDetails (gRPC流响应)
  └── 只在服务端返回错误后才阻止

Layer 2: 消息发送前检查 (Pre-check, fail-open)
  ├── checkChatCapacity (仅isCapacityLimited模型)
  ├── checkUserMessageRateLimit (所有模型)
  └── try/catch静默放行

Layer 3: gRPC流处理 (Server-side)
  ├── addCascadeInput → 服务端处理
  ├── 可返回CortexErrorDetails错误
  └── 返回INSUFFICIENT后 → Layer 1激活
```

---

## 十、补充枚举与Protobuf (OPTIMIZATION_v6融合)

### 10.1 CascadeExecutorConfig (客户端→服务端)

```protobuf
exa.cortex_pb.CascadeExecutorConfig {
  1: disable_async (bool)
  2: max_generator_invocations (int32)    // 已patch→9999, 服务端cap~25
  3: terminal_step_types (enum[], repeated)
  4: run_pending_steps (bool)
  5: hold_for_valid_checkpoint (bool)
  6: hold_for_valid_checkpoint_timeout (int32)
}
```

### 10.2 计费相关补充枚举

```javascript
// 非标准计费原因
CortexStepCreditReason {
  UNSPECIFIED        = 0,
  LINT_FIXING_DISCOUNT = 1,  // ← 唯一免费路径! lint修复折扣
}

// 请求来源 (可能影响计费权重)
CortexRequestSource {
  UNSPECIFIED = 0, CASCADE_CLIENT = 1, EXPLAIN_PROBLEM = 2,
  REFACTOR_FUNCTION = 3, EVAL = 4, EVAL_TASK = 5,
  ASYNC_PRR = 6, ASYNC_CF = 7, ASYNC_SL = 8,
}

// 规划器模式
ConversationalPlannerMode {
  UNSPECIFIED = 0, DEFAULT = 1, READ_ONLY = 2,
  NO_TOOL = 3, EXPLORE = 4, PLANNING = 5, AUTO = 6,
}
// NO_TOOL模式不使用tool calls → 不触发MAX_INVOCATIONS

// 异步执行级别
ExecutionAsyncLevel {
  UNSPECIFIED = 0, INVOCATION_BLOCKING = 1,
  EXECUTOR_BLOCKING = 2, FULL_ASYNC = 3,
}
```

### 10.3 ParallelRolloutConfig (P5潜在突破)

```protobuf
CascadeConfig.parallel_rollout_config {
  1: num_parallel_rollouts (int32)        // 并行rollout数 (默认0)
  2: max_invocations_per_rollout (uint32) // 每rollout独立invocation限制
  6: guide_model_uid (string)             // 引导模型UID
  4: max_guide_invocations (int32)
  5: force_bad_rollout (bool)             // 测试用
}
```

理论: `num_parallel_rollouts=3 × max_invocations_per_rollout=25 = 75` invocations。
风险: 服务端可能忽略/额外计费/检测异常。

### 10.4 GracePeriodStatus枚举

```javascript
GracePeriodStatus {
  UNSPECIFIED = 0,
  NONE        = 1,    // 无宽限期
  ACTIVE      = 2,    // 免费周期间 → hasCapacity始终true
  EXPIRED     = 3,    // 宽限期结束
}
```

---

## 十一、关键代码偏移量索引

| 功能 | 偏移量 | 变量/函数 |
|------|--------|----------|
| ModelPricingType枚举 | ~2117862 | `ModelPricingType` |
| MBe模型成本映射 | ~17833084 | `MBe(Z)` |
| iye无限检查 | ~17874639 | `iye=Z=>Z===-1` |
| rye剩余积分计算 | ~17874664 | `rye=(Z,B)=>...` |
| S5t剩余积分memo | ~18371491 | `S5t=useMemo(...)` |
| ZWe对话消耗统计 | ~18405932 | `ZWe=(Z,B)=>{...}` |
| 显示逻辑ACU vs Credits | ~18424260 | `acuCost>0?"ACUs"` |
| sendMessage门禁 | ~18378423 | `checkChatCapacity` |
| sendMessage门禁2 | ~18378712 | `checkUserMessageRateLimit` |
| canSendMessage | ~18374530 | `O5t=!Xve(wp).code` |
| GracePeriodStatus枚举 | ~2119412 | `GracePeriodStatus` |
| RateLimit Request PB | ~25006296 | `CheckUserMessageRateLimitRequest` |
| RateLimit Response PB | ~25006869 | `CheckUserMessageRateLimitResponse` |

---

## 十二、底层根源总结

> **一切的根源 = `PlanInfo.billing_strategy` (protobuf field no:35)。服务端通过此字段决定走CREDITS/QUOTA/ACU哪条路。客户端v1.108.2已完全支持三种模式的双轨并行。**

### 不可绕过的铁律

1. **服务端控制一切计费** — 客户端patch无法减少实际扣费
2. **token是最底层计量单位** — 一切成本 = input/output tokens × model rate
3. **25 invocation限制独立于配额** — 两者并行,先触发哪个就停哪个
4. **BYOK是唯一真正的绕过** — 自付API费 = 0 Windsurf成本
5. **配额百分比不透明** — 只有%,无绝对token数,无法精确预算

### 可优化的维度

1. **模型选择**: 低ACU率模型 (SWE-1.5, Gemini Flash, GPT-5-Codex)
2. **Context减肥**: 精简Rules/Memories = QUOTA体系下直接省配额
3. **工作流设计**: 规划→委派→验证 (最小化高价模型使用)
4. **并行效率**: 最大化每个invocation的工具并行度
5. **缓存利用**: cache_read_tokens比input_tokens便宜
