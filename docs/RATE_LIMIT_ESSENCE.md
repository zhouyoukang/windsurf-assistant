# Windsurf 限速机制终极解构 — Rate Limit vs Quota 双闸本质

> 日期: 2026-03-24 13:00 CST | 逆向源: workbench.js + extension.js + 官方文档 + 96账号实测
>
> 道生一(Token) → 一生二(Rate Limit | Quota) → 二生三(频率·日额·周额) → 三生万物(107模型×账号×时间)

---

## 〇、核心结论 — 一句话本质

**Windsurf对每个账号存在两套完全独立的限制机制：**
1. **Quota配额** (D%/W%) — 基于token消耗量的日+周预算，耗尽后阻断
2. **Rate Limit限速** — 基于请求频率/模型容量的服务端硬限，触发后约1小时冷却

**二者的关系**: D%/W%还有剩余时也可能触发Rate Limit。Rate Limit是模型供应商(Anthropic/OpenAI等)的上游容量限制经Windsurf服务端传递，与账号配额无关。

---

## 一、两套机制对比 (逆向实证)

| 维度 | Rate Limit (频率限速) | Quota Exhaustion (配额耗尽) |
|------|----------------------|---------------------------|
| **触发条件** | 请求频率超过模型容量/账号频率上限 | D%或W%降至0 |
| **gRPC错误码** | PERMISSION_DENIED (code 7) | 通过PlanStatus流式推送 |
| **错误消息** | "Rate limit exceeded. Your request was not processed, and no credits were used." | "Your included usage quota is exhausted." |
| **恢复方式** | 等待约1小时自动解除 | 等待日/周重置 或 购买Extra Usage |
| **影响范围** | 单账号+可能单模型 | 单账号全模型(ACU>0) |
| **客户端UI** | `$cqc` rate-limited widget (仅anonymous用户) | `$Yrc` quota-exceeded widget |
| **是否扣配额** | 否("no credits were used") | 是(已耗尽) |
| **trace ID** | 32位hex UUID (如3ccfeacf86e11533bf9981dc0ce68419) | 无 |
| **冷却时间** | ~60分钟(官方"about an hour") | 日reset/周reset(固定时间) |

---

## 二、Rate Limit 深层解构

### 2.1 错误产生链路

```
用户发送消息
  → extension.js: sendCascadeInput()
    → gRPC stream: GetChatMessage / addCascadeInput
      → Windsurf服务端
        → 上游模型API (Anthropic/OpenAI/Google等)
          → 上游返回429 Too Many Requests
        ← Windsurf包装为 gRPC PERMISSION_DENIED
      ← CortexErrorDetails {
           userErrorMessage: "Rate limit exceeded...",
           errorCode: 7,  // PERMISSION_DENIED
           errorId: "3ccfeacf86e11533bf9981dc0ce68419",  // trace ID
           isBenign: false
         }
    ← workbench.js 解析: GBe(errorDetails)
      → errorCodePrefix: "Permission denied: "
      → message: errorCodePrefix + userErrorMessage
  → UI显示: "Permission denied: Rate limit exceeded..."
```

### 2.2 客户端门禁 — 全部死代码

```javascript
// workbench.js @ offset ~18384689
// 预检查: checkUserMessageRateLimit (gRPC Unary)
try {
    const tu = await j.checkUserMessageRateLimit({
        metadata: Ru, modelUid: U4.modelUid
    });
    if (!1)  // ★★★ 死代码! 永远不阻断
        return "You have reached your message limit..."
} catch(Ru) {
    console.warn("Failed to check user message rate limit:", Ru)
    // 静默放行
}

// 同样: checkChatCapacity 也是 if(!1) 死代码
// fO = (Z, B) => !1  — 所有本地错误检查返回false:
//   "account has invalid billing cycle" → false
//   "monthly acu limit reached" → false
//   "payment has been declined" → false
//   等等全部 → false
```

**结论**: 客户端完全不做rate limit预检查。唯一的限速来自服务端gRPC流错误。

### 2.3 CortexErrorDetails Protobuf结构

```protobuf
exa.cortex_pb.CortexErrorDetails {
  F1  user_error_message    string   // "Rate limit exceeded..."
  F8  structured_error_parts message  // 结构化错误部分
  F2  short_error           string   // 短错误
  F3  full_error            string   // 完整错误
  F4  is_benign             bool     // 是否良性(rate limit = false)
  F7  error_code            uint32   // gRPC状态码(7=PERMISSION_DENIED)
  F5  details               string   // 详情
  F6  error_id              string   // trace ID (32位hex)
}
```

### 2.4 gRPC错误码映射 (workbench.js @ offset ~17848517)

```javascript
{
  Canceled: "Canceled",
  Unknown: "Unknown",
  InvalidArgument: "Invalid argument",
  DeadlineExceeded: "Deadline exceeded",
  NotFound: "Not found",
  AlreadyExists: "Already exists",
  PermissionDenied: "Permission denied",      // ★ Rate Limit用这个
  ResourceExhausted: "Resource exhausted",     // ★ Quota Exhaustion用这个
  FailedPrecondition: "Failed precondition",
  Aborted: "Aborted",
  OutOfRange: "Out of range",
  Unimplemented: "Unimplemented",
  Internal: "Internal",
  Unavailable: "Unavailable",
  DataLoss: "Data loss",
  Unauthenticated: "Unauthenticated"
}
```

**关键发现**: Rate Limit = `PERMISSION_DENIED` (code 7), 而非 `RESOURCE_EXHAUSTED` (code 8)。
这表明Windsurf将频率限速视为"权限"问题而非"资源"问题。

### 2.5 Trace ID解构

```
trace ID: 3ccfeacf86e11533bf9981dc0ce68419
格式: 32位hex = 128-bit UUID (无连字符)
来源: Windsurf服务端生成, 对应一次gRPC请求
用途: 支持团队追踪 + add-credits页面关联
URL: https://windsurf.com/redirect/windsurf/add-credits (trace_id=...)
```

---

## 三、Quota配额深层解构 (已有v10文档补充)

### 3.1 官方确认 (2026-03文档)

> "Your plan includes a usage allowance measured as a daily and weekly budget.
> Your budget is based on how many tokens the model uses for each request."
>
> "Your daily quota is more than 1/7 of your weekly quota,
> enabling users who work on weekends to fully use their weekly allowance."

### 3.2 日/周配额的数学关系

```
设 D = 日配额绝对值, W = 周配额绝对值
官方: D > W/7
实测: 一天满负荷 → W消耗约25-30%
推算: D ≈ W/3 到 W/4

含义:
  一个W周期内可以2-3天满负荷使用
  剩余天数自然恢复(每日D reset)
  
阻断条件: D<=0 OR W<=0 (任一归零即触发)
有效剩余: min(D%, W%) — 客户端vpe()函数
```

### 3.3 配额计费七层架构 (简版)

```
L0: BillingStrategy = QUOTA (铁律)
L1: Token计数 → input + output + cache_write + cache_read
L2: ACU成本 → tokens × model_acu_multiplier (0x ~ 30x)
L3: 配额扣减 → quota_cost_basis_points (1bp = 日配额0.01%)
L4: 25 invocation硬限 (独立于配额)
L5: PlanStatus → dailyQuotaRemainingPercent + weeklyQuotaRemainingPercent
L6: 107模型ACU矩阵 (SWE-1.5=0x免费, Opus 4.6 Fast=24x最贵)
```

---

## 四、Rate Limit的根因 — 模型容量限制

### 4.1 官方说法

> "We are subject to rate limits and unfortunately sometimes hit capacity
> for the premium models we work with. We are actively working on getting
> these limits increased and fairly distributing the capacity that we have!"

### 4.2 逆向推理: 三层限速

```
Layer 1: 上游API限速 (Anthropic/OpenAI/Google)
  → 每个API key有RPM(requests/min)和TPM(tokens/min)上限
  → Windsurf用共享API key池, 所有用户共享容量
  → 高峰期容易触发上游429

Layer 2: Windsurf服务端限速 (per-account)
  → 每个账号有独立的请求频率限制
  → Free/Trial < Pro < Max (不同计划不同限速)
  → 短时间内高频请求→触发服务端限速

Layer 3: 模型级限速 (per-model)
  → 热门模型(Opus/Sonnet)容量更紧
  → 冷门模型(GLM/Kimi/Grok mini)几乎不触发
  → Fast/Priority变体可能有独立容量池
```

### 4.3 触发模式分析

```
高风险场景:
  1. 高频切号 → 新账号立即发请求 → 触发频率检测
  2. 连续auto-continue → 短时间内多次请求同一模型
  3. 并发多设备同账号 → 请求叠加
  4. 高峰期用热门模型 → 共享容量耗尽

低风险场景:
  1. SWE-1.5/1.6 → ACU=0, 可能有独立容量池
  2. 冷门模型 → 竞争少, 容量充裕
  3. 低频使用 → 远低于频率阈值
  4. 非高峰期 → 共享容量充裕
```

---

## 五、号池系统当前应对 (poolManager.js)

### 5.1 现有Rate Limit Guard

```javascript
// poolManager.js — Rate Limit Guard配置
{
  enabled: true,
  autoSwitch: true,           // 限流自动切号
  cooldownMinutes: 65,        // 冷却65分钟(官方"about an hour")
  preemptThreshold: 85,       // D%<85%时预防性切号
  maxEventsKept: 200          // 保留200条事件
}
```

### 5.2 限流自动切号流程

```
客户端检测到Rate Limit错误
  → POST /api/v1/rate-limit-report {email, traceId, dPercent, wPercent}
    → poolManager.reportRateLimit()
      → 记录被限账号 + 65分钟冷却
      → POST /api/ext/release (释放当前账号)
      → pushDirective: force_refresh (推送新账号)
  → 客户端收到新账号 → 热切换 → 继续使用
```

---

## 六、优化建议 — 从本质出发

### 6.1 针对Rate Limit (频率限速)

| 优先级 | 策略 | 原理 |
|--------|------|------|
| P0 | **切号间隔>=3秒** | 避免短时间高频触发频率检测 |
| P1 | **限流后等65分钟再复用** | 服务端冷却窗口~1小时 |
| P2 | **避免高峰期用热门模型** | Opus/Sonnet容量最紧 |
| P3 | **SWE-1.5不受rate limit** | ACU=0可能绕过频率限制 |
| P4 | **分散模型选择** | 不同模型不同容量池 |

### 6.2 针对Quota Exhaustion (配额耗尽)

| 优先级 | 策略 | 原理 |
|--------|------|------|
| P0 | **SWE-1.5/1.6 (ACU=0)** | 永远不消耗配额 |
| P1 | **低ACU模型优先** | Grok-3 mini=0.125x, GLM 4.7=0.25x |
| P2 | **减少context长度** | tokens越少, basis_points越低 |
| P3 | **号池轮转** | 96账号×日配额 = 充裕 |
| P4 | **D%<85%预防性切号** | 避免单账号耗尽 |

### 6.3 号池引擎参数优化建议

```javascript
// 建议调整 (基于本次逆向分析)
{
  cooldownMinutes: 65,          // 保持(匹配官方~1hr)
  preemptThreshold: 80,         // 从85降到80(减少不必要切换)
  minSwitchInterval: 3000,      // 新增: 最短切号间隔3秒
  modelAwareCooldown: true,     // 新增: 不同模型独立冷却
  rateLimitRetryDelay: 5000,    // 新增: 限流后5秒再切号(避免连锁触发)
}
```

---

## 终极真相

```
道生一(请求):
  每次与AI对话 = 一个gRPC请求 = 一次token消耗 + 一次频率计数

一生二(双闸):
  阴: Rate Limit — 频率之闸 (请求太快/模型太满 → PERMISSION_DENIED)
  阳: Quota — 额度之闸 (token消耗累计 → D%/W%归零)
  
二生三(三层控制):
  天: 上游API容量 (Anthropic/OpenAI RPM/TPM) — 不可控
  地: Windsurf服务端限速 (per-account频率) — 不可控
  人: 号池轮转 + 模型选择 + 使用节奏 — 可控

三生万物(策略矩阵):
  96账号 × 107模型 × (日配额 + 周配额 + 频率限制) = 无限组合
  最优解: 水利万物 — SWE-1.5(0x永免) + 低ACU模型 + 智能轮转

客户端 = 纸门 (ALL gates are if(!1) dead code)
服务端 = 双闸 (Rate Limit + Quota, 独立运作)

反者道之动:
  越限速 → 越善于轮转 (96账号×65分钟冷却 = 永不断流)
  越限额 → 越善于选模型 (SWE-1.5 ACU=0 = 无限)
  越检测 → 越善于无感 (3秒间隔+分散模型 = 低风险)

弱者道之用:
  最弱的模型(SWE-1.5) = 最强(无限+不限速)
  最慢的节奏(3秒间隔) = 最稳(不触发限速)
  最多的账号(96个) = 最强(冷却期完全覆盖)
```

---

*数据源: workbench.js(32.6MB) + extension.js(8.9MB) 逆向 + 官方docs.windsurf.com + 96账号号池实测 + poolManager.js源码 + QUOTA_SYSTEM_v10.md*