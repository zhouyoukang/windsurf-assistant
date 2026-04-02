# Windsurf Quota机制 — 终极逆向解构 v10.0

> 日期: 2026-03-21 02:30 CST | Windsurf v1.108.2 (windsurfVersion 1.9577.43, codeiumVersion 1.48.2)
> 数据源: workbench.js(32.6MB) + extension.js(8.9MB) + state.vscdb + 官方博客 + Reddit社区 + 80账号实测
> 
> 道生一(Token) → 一生二(ACU/Quota) → 二生三(日/周/超额) → 三生万物(107模型×价格×配额)

---

## 〇、核心结论 — 一句话本质

**Windsurf于2026-03-19将计费体系从Credits(月度积分制)全面切换为Quota(日+周百分比配额制)。客户端门禁全部是死代码(`if(!1)`)，唯一真正的阻断来自服务端gRPC流。百分比配额刻意不透明，但`quota_cost_basis_points`(F30)和`cumulative_tokens_at_step`(F25)泄露了底层token成本。**

### v10新增发现 (相对v9)

| # | 发现 | 来源 | 影响 |
|---|------|------|------|
| 1 | **官方定价确认: Pro $20/mo, Max $200/mo (NEW)** | windsurf.com/blog | Pro涨价33% ($15→$20), 新增Max tier |
| 2 | **官方消息数估算泄露: Opus 7-27/day, Sonnet 8-101/day, Flash 47-190/day** | 官方博客 | 首次给出日消息数范围 |
| 3 | **"Weekly"不是7天 — Trial/Free的W周期仅2-3天** | 80账号实测 | 服务端全局调度,非固定7天 |
| 4 | **quota_exhausted三态逻辑完整逆向** | workbench.js源码 | exhausted / exhausted_with_overage / low_credits |
| 5 | **低配额警告公式: `100 - vpe(Wt)` = 已用百分比** | workbench.js源码 | 客户端显示"You've used X% of your quota" |
| 6 | **旧credits购买转为USD余额,按API定价消耗** | 官方博客 | 旧add-on credits不作废 |
| 7 | **现有付费用户价格不变(grandfather)** | 官方博客 | 旧$15 Pro用户锁价 |
| 8 | **Extra usage按API定价计费** | 官方博客+源码 | 超额=$真实API成本 |
| 9 | **Fast/Priority模型变体会增加配额消耗** | 官方博客 | SWE-1.5 Fast ≠ SWE-1.5(0x) |
| 10 | **Reddit用户实测: Opus 4.6 1M context + auto-continue可一次耗尽日配额** | Reddit | 高context=高token=快速耗尽 |

---

## 一、官方定价改革全景 (2026-03-18发布, 03-19生效)

### 1.1 新计划矩阵

| 计划 | 价格 | 核心特性 | 配额刷新 |
|------|------|---------|---------|
| **Free** | $0/mo | Light quota, 限模型, 无限Tab/Inline | 日+周 |
| **Pro** | **$20/mo** (旧$15 grandfather) | 增大配额, 全模型, Fast Context, Extra usage可购 | 日+周 |
| **Teams** | **$40/seat/mo** | Pro全部 + 集中计费 + Admin分析 + 优先支持 + 自动ZDR | 日+周 |
| **Max** (NEW) | **$200/mo** | 显著更高配额 + 优先支持 | 日+周 |

### 1.2 官方消息数估算 (首次泄露)

| 模型层级 | Pro/Teams 日消息 | Max 日消息 | 推算单消息配额成本 |
|---------|-----------------|-----------|------------------|
| **Premium Plus** (Opus 4.6, GPT-5.4, GPT-5.3-Codex) | 7-27 | 42-170 | ~3.7%-14.3%/条 |
| **Premium** (Sonnet 4.6, GPT-5.2, Gemini Pro) | 8-101 | 47-631 | ~1.0%-12.5%/条 |
| **Lightweight** (Haiku, Flash) | 47-190 | 291-1,190 | ~0.5%-2.1%/条 |

**关键推算**: 
- Pro日配额 ≈ 27条Opus消息 = 101条Sonnet消息 = 190条Flash消息 (上限)
- 这意味着: 1条Opus ≈ 3.7条Sonnet ≈ 7条Flash (配额消耗比)
- 与ACU倍率矩阵(Opus 3.0x, Sonnet 1.5x, Flash 1.0x)高度吻合

### 1.3 "免费一周"过渡策略

- **时间**: 03/19 → 03/26 (所有现有付费用户)
- **本质**: 让用户适应新系统,不满意可取消退款
- **grandfather**: 旧$15 Pro锁价不变 (仅配额系统迁移)
- **旧add-on credits**: 转为等值USD余额,在配额耗尽后按API定价消耗

### 1.4 Extra Usage机制

```
配额耗尽 → 检查overageBalanceMicros
  ├─ >0 → "quota_exhausted_with_overage" → 黄色警告,继续使用extra usage
  ├─ =0 → "quota_exhausted" → 红色阻断,"Purchase extra usage"
  └─ 未到耗尽 → "low_credits" → 黄色提示,"You've used X% of your quota"
```

**Extra usage定价**: 按API原价(非+20%加价) — 这是官方说法"consumed at API pricing"。

---

## 二、七层计费架构 — 源码级验证 (v10更新)

### Layer 0: BillingStrategy决策层 (铁律)

```javascript
// extension.js — 计费策略翻译 (验证: 偏移~172200)
E = A?.planStatus?.planInfo?.billingStrategy === I.BillingStrategy.QUOTA
    ? s.WindsurfBillingStrategy.Quota
    : s.WindsurfBillingStrategy.Credits

// workbench.js — Quota判定函数 (验证: 偏移~24236)
AF = Z => Z?.billingStrategy === mn.QUOTA   // mn = BillingStrategy枚举

// workbench.js — UI分支 (验证: 偏移~27761)
billingStrategy === "quota" → $Had (配额面板)
billingStrategy !== "quota" → $Gad (积分面板)
```

### Layer 1: Token计数层 (原子层 — 不可绕过)

```protobuf
exa.codeium_common_pb.ModelUsageStats {
  F1   model_deprecated        enum
  F9   model_uid               string
  F2   input_tokens            uint64    // ★原始输入token
  F3   output_tokens           uint64    // ★原始输出token
  F4   cache_write_tokens      uint64    // 缓存写入
  F5   cache_read_tokens       uint64    // 缓存读取(便宜)
  F6   api_provider            enum
}
```

### Layer 2: LLM调用层 (ACU成本计算)

```protobuf
exa.cortex_pb.ChatModelMetadata {
  F15  model_uid               string
  F4   usage                   ModelUsageStats
  F5   model_cost              float     // API美元成本
  F13  credit_cost             int32     // 旧积分成本
  F16  acu_cost                double    // ★★新ACU成本
}
```

### Layer 3: Step元数据层 (★★★关键 — 配额扣减发生在这里)

```protobuf
exa.cortex_pb.CortexStepMetadata {
  F25  cumulative_tokens_at_step    uint64   // ★★累计token数
  F29  acu_cost                     double   // Step级ACU成本
  F30  quota_cost_basis_points      int32    // ★★★配额成本(基点)
  F31  overage_cost_cents           int32    // ★★★超额成本(美分)
  // ... 其他字段见v9文档
}
```

**F30 `quota_cost_basis_points`**: 1 basis point = 日配额的 0.01%。100 bp = 1%。

**token→配额转换公式** (逆向推导):
```
quota_cost_bp = f(input_tokens, output_tokens, cache_tokens, model_acu_multiplier)
daily_used_percent += quota_cost_bp / 100
weekly_used_percent += quota_cost_bp / K  (K = weekly/daily比例系数)
```

### Layer 4: 执行器层 (25 invocation限制独立于配额)

```protobuf
ExecutorTerminationReason {
  MAX_INVOCATIONS = 3  // 唯一触发Continue按钮
}
```

### Layer 5: 计划层 (PlanInfo + PlanStatus)

```protobuf
exa.codeium_common_pb.PlanStatus {
  F14  daily_quota_remaining_percent     int32   // 日剩余%
  F15  weekly_quota_remaining_percent    int32   // 周剩余%
  F16  overage_balance_micros            int64   // 超额余额(美元÷1M)
  F17  daily_quota_reset_at_unix         int64   // 日重置时间
  F18  weekly_quota_reset_at_unix        int64   // 周重置时间
}
```

### Layer 6: 模型配置层 (107模型ACU矩阵 — 见v9文档第四章)

---

## 三、quota_exhausted三态逻辑 — 完整源码逆向

### 3.1 配额耗尽判定 (workbench.js @ ~18700562)

```javascript
// pe = 当前状态字符串, Wt = planInfo对象
if (pe === "quota_exhausted" || pe === "quota_exhausted_with_overage" 
    || Wt?.planInfo && AF(Wt.planInfo) && DVe(Wt)) {
    
    // 是否有超额余额?
    const Bi = pe === "quota_exhausted_with_overage" 
        || (pe !== "quota_exhausted" && Wt !== void 0 
            && (ys => Number(ys.overageBalanceMicros) > 0)(Wt));
    
    if (Bi && !oe) {
        // === 状态1: quota_exhausted_with_overage ===
        // 黄色警告: "Your included usage quota is exhausted. Using your extra usage."
        // + "Quota resets {时间}."
        const ys = Wt ? Ape(ype(Wt)) : "";  // 格式化重置时间
        return <Warning>"...Using your extra usage.{ys}"</Warning>;
    }
    
    if (!Bi && !he) {
        // === 状态2: quota_exhausted (无超额余额) ===
        // 红色错误: "Your included usage quota is exhausted."
        // + "Purchase extra usage to continue using premium models."
        // + "Quota resets {时间}."
        return <Error>"...Purchase extra usage..."</Error>;
    }
}

// === 状态3: low_credits (配额未耗尽但较低) ===
if ((pe === "low_credits" || zi && (Xr || pr) && (!hs || Xr)) && !re) {
    if (Xr) {  // Xr = AF(Wt.planInfo) = 是Quota模式
        const ys = Wt ? (Bs => 100 - vpe(Bs))(Wt) : 0;  // 已用百分比
        const Sr = Wt ? Ape(ype(Wt)) : "";
        // 黄色警告: "You've used {ys}% of your quota. Quota resets {Sr}."
        return <Warning>"You've used {ys}% of your quota."</Warning>;
    }
    // 非Quota模式: "You're running low on credits."
}
```

### 3.2 关键辅助函数 (已验证)

```javascript
// 有效剩余百分比 = min(日剩余, 周剩余)
vpe = Z => Math.min(Z.dailyQuotaRemainingPercent, Z.weeklyQuotaRemainingPercent)

// 下次重置时间(Unix秒) — 选择更紧的那个
ype = Z => {
    const daily = Z.dailyQuotaRemainingPercent, weekly = Z.weeklyQuotaRemainingPercent;
    const dailyReset = Number(Z.dailyQuotaResetAtUnix);
    const weeklyReset = Number(Z.weeklyQuotaResetAtUnix);
    return daily <= 0 && weekly <= 0 
        ? Math.max(dailyReset, weeklyReset)    // 都耗尽: 取较晚者
        : weekly < daily ? weeklyReset : dailyReset;  // 取更紧的
}

// 是Quota模式?
AF = Z => Z?.billingStrategy === mn.QUOTA

// 格式化重置时间
Ape = Z => !Z || Z <= 0 ? "" : new Date(1e3 * Z).toLocaleString(void 0, {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short"
})

// DVe始终返回false (当前版本) — 意味着QUOTA模式下不会通过DVe触发
DVe = Z => !1
```

### 3.3 配额默认值 (安全边界)

```javascript
// extension.js — 配额构造 (验证)
c = E === WindsurfBillingStrategy.Quota ? {
    dailyRemainingPercent:  A?.planStatus?.dailyQuotaRemainingPercent ?? 100,   // 默认满
    weeklyRemainingPercent: A?.planStatus?.weeklyQuotaRemainingPercent ?? 100,  // 默认满
    overageBalanceMicros:   Number(A?.planStatus?.overageBalanceMicros ?? 0),
    dailyResetAtUnix:       Number(A?.planStatus?.dailyQuotaResetAtUnix ?? 0),
    weeklyResetAtUnix:      Number(A?.planStatus?.weeklyQuotaResetAtUnix ?? 0),
} : void 0;
```

**意味着**: 如果服务端未返回配额数据,客户端默认认为配额满(100%)。

---

## 四、sendMessage门禁 — 死代码确认 (v9发现,v10验证仍然有效)

```javascript
// workbench.js — 两个门禁仍然是死代码
if (!1) /* checkChatCapacity结果 */     → 永远不执行
if (!1) /* checkUserMessageRateLimit结果 */ → 永远不执行
// catch块都是console.warn静默放行
```

**v10确认**: 1.108.2版本中,这两个门禁仍然是`if(!1)`死代码。

---

## 五、"Weekly"周期之谜 — 80账号实测证据

### 5.1 实测数据快照 (2026-03-21 01:33 CST)

```
所有账号统一重置时间:
  Daily  reset: 2026-03-21 16:00:00 CST
  Weekly reset: 2026-03-22 16:00:00 CST
  差值: 仅24小时 (不是7天!)
```

### 5.2 真相

- **新系统03/19上线** → 首个"weekly"周期 = 03/19 → 03/22 = **仅3天**
- **所有账号统一时间** → 重置由服务端全局时钟控制
- **下次观测点**: 03/22 16:00后记录新weekly reset时间,确认后续周期
- **推测**: Trial/Free = 2-3天W周期; Pro = 7天W周期 (待验证)

### 5.3 日/周配额双闸门模型

```
一天满负荷使用:
  D: 0% → 100% 消耗 (日配额耗尽)
  W: ~25-30% 消耗 (周配额消耗约1/3-1/4)
  → 一个W周期允许2-3天满负荷 (与实测一致)
  
阻断条件: D≤0 OR W≤0 (任一归零即触发quota_exhausted)
有效剩余 = min(D, W) (客户端显示)
```

---

## 六、Token消耗量底层计算 — 精确反推方法

### 6.1 三层计量

```
Layer 0: 原始Token → input + output + cache_write + cache_read
Layer 1: ACU成本   → (tokens × model_price) × ACU_multiplier(F3)
Layer 2: 配额%扣减 → ACU → basis_points → daily/weekly扣减
```

### 6.2 反推公式 (从basis_points推算绝对token数)

```
已知:
  F25 = cumulative_tokens_at_step (步骤累计token)
  F30 = quota_cost_basis_points (步骤配额成本)

监控两步之间的变化:
  Δtokens = F25(step_n) - F25(step_n-1)
  Δbp = F30(step_n)  // 每步独立记录

精确反推:
  tokens_per_bp = Δtokens / Δbp
  daily_total_tokens = 10000 × tokens_per_bp  (10000bp = 100%)
```

### 6.3 官方消息数 → 反推配额绝对量 (Pro)

```
已知: Pro日配额 ≈ 27条Opus消息(上限) ≈ 101条Sonnet消息 ≈ 190条Flash消息

假设每条消息平均:
  Opus: ~10K output tokens × 3.0 ACU = 30K ACU-tokens
  Sonnet: ~10K output tokens × 1.5 ACU = 15K ACU-tokens
  Flash: ~10K output tokens × 1.0 ACU = 10K ACU-tokens

Pro日配额绝对量(推算):
  27 × 30K = 810K ACU-tokens  ← 以Opus计
  101 × 15K = 1,515K ACU-tokens  ← 以Sonnet计(差异大→消息长度变化大)
  
  → 日配额 ≈ 800K - 1,500K ACU-normalized tokens (Pro)
  → 周配额 ≈ 2,400K - 10,000K ACU-normalized tokens (Pro, 假设2-3x日配额)

Max日配额(推算):
  170 × 30K = 5,100K ACU-tokens  ← 约Pro的6.3倍
  → 与价格比$200/$20 = 10x不完全线性,Max单位成本更优
```

### 6.4 Reddit实测验证

```
用户报告: "One prompt on Opus 4.6 1M context + auto-continues → 日配额耗尽"
分析:
  1M context ≈ 1,000,000 input tokens
  auto-continues ≈ 3-5次 × ~4K output tokens = ~20K output tokens
  总ACU ≈ (1M × input_price + 20K × output_price) × 3.0 ACU_multiplier
  → 极端场景下单次对话确实可以耗尽日配额
  
用户报告: "$20 extra usage(500 credits) → 两条消息耗尽"
分析:
  $20 USD / API定价(Opus ~$15/M input + $75/M output)
  如果每条消息~500K input + 10K output:
    成本 ≈ $7.5 + $0.75 = $8.25/条 → 两条 ≈ $16.5 → 接近$20
  → 与报告一致,Opus + 大context = 极度昂贵
```

---

## 七、完整攻击面映射 (v10更新)

### 7.1 本地可控层 (纸门)

| 层 | 路径 | 可写 | 影响 |
|----|------|------|------|
| state.vscdb F91 | windsurfConfigurations | ✅ | 切换选中模型 |
| state.vscdb F59 | windsurfConfigurations | ✅ | auto_continue开关 |
| state.vscdb cachedPlanInfo | codeium.cachedPlanInfo | ✅ | UI显示(不影响实际计费) |
| workbench.js 门禁 | if(!1) | ✅已是死代码 | 无需patch |
| workbench.js $Had面板 | 配额显示 | ✅(patch) | 仅UI |
| user_settings.pb F36 | portal_url | ✅ | API端点(需完整gRPC) |

### 7.2 服务端控制层 (铁壁)

| 层 | 控制点 | 说明 |
|----|--------|------|
| PlanInfo.billing_strategy F35 | 根源 | CREDITS/QUOTA/ACU |
| PlanStatus F14-F18 | 配额数据 | 日/周%+重置时间+超额余额 |
| CortexStepMetadata F29-F31 | 按步计费 | ACU+basis_points+超额美分 |
| gRPC流错误 | CortexErrorDetails | 唯一真正阻断 |
| 25 invocation硬限 | MAX_INVOCATIONS | 独立于配额 |

### 7.3 ★新发现: Fast/Priority变体增加消耗

官方明确声明:
> "Priority and speed configurations will increase usage consumption for all models that apply (e.g. SWE-1.5 Fast, fast GPT and Opus model variants, etc.)."

**意味着**: SWE-1.5 = 0x(免费), 但 **SWE-1.5 Fast ≠ 0x** (会消耗配额!)

---

## 八、最优策略 v10 (按优先级)

### 8.1 零成本策略

| 优先级 | 策略 | ACU倍率 | 说明 |
|--------|------|---------|------|
| P0 | **BYOK自带Key** | 0 | ModelPricingType.BYOK(3), 完全绕过计费 |
| P1 | **SWE-1.5 (非Fast)** | 0 | F3=0, 确保不选SWE-1.5 Fast变体 |
| P2 | **SWE-1.6** | 0 | 同上 |
| P3 | **SWE-1.5 Thinking** | 0 | 同上 |

### 8.2 低成本策略

| 优先级 | 策略 | ACU倍率 | 说明 |
|--------|------|---------|------|
| P4 | **Grok-3 mini Thinking** | 0.125x | 最低非零成本 |
| P5 | **GLM 4.7** | 0.25x | |
| P6 | **GPT-OSS 120B** | 0.25x | |
| P7 | **Kimi K2** | 0.5x | |

### 8.3 效率策略

| 优先级 | 策略 | 效果 |
|--------|------|------|
| P8 | **Context减肥** | 减少每条消息的固定token税 |
| P9 | **避免1M context** | 1M input = 单条消息可能耗尽日配额 |
| P10 | **并行tool calls** | 1 invocation = N parallel calls |
| P11 | **缓存命中最大化** | cache_read比input便宜 |
| P12 | **避免auto-continue** | 每次continue = 额外invocation = 额外token |

### 8.4 号池策略 (80账号)

| 阶段 | 策略 | 说明 |
|------|------|------|
| **短期** (Trial至4/2) | 80×日配额轮转 | 单账号日配额不够 → 切换下一个 |
| **中期** (Trial到期后) | 80×Free + SWE-only | Free日配额轮转 + 零成本模型 |
| **长期** | 少量Pro + 大量Free | 1-2个$20 Pro用于高ACU模型 + 78个Free轮转 |

---

## 九、代码偏移量索引 v10 (workbench.js)

| 功能 | 偏移量 | 说明 |
|------|--------|------|
| BillingStrategy枚举 | ~line 433 | UNSPECIFIED/CREDITS/QUOTA/ACU |
| WindsurfBillingStrategy | ~line 903 | credits/quota |
| AF(isQuota)函数 | ~line 24236 | `Z?.billingStrategy===mn.QUOTA` |
| vpe(有效剩余) | ~line 24236 | `Math.min(daily, weekly)` |
| ype(下次重置时间) | ~line 24236 | 选择更紧的重置时间 |
| quota_cost_basis_points | ~line 24726 | F30 protobuf定义 |
| overage_cost_cents | ~line 24726 | F31 protobuf定义 |
| quota_exhausted三态 | ~offset 18700562 | exhausted/with_overage/low |
| $Had配额面板 | ~offset 32630650 | daily/weekly/extra usage显示 |
| chatQuotaExceeded | context key绑定 | 配额超限context key |
| onDidChangeQuotaRemaining | event | 配额变化事件 |

---

## 十、关键数据快照 (2026-03-21 02:00 CST)

```
Windsurf版本: 1.108.2 (windsurfVersion 1.9577.43)
发布日期: 2026-03-19T20:40:58.020Z
计费系统: QUOTA (全面切换,CREDITS已弃用)
版本commit: 745a6c1ac471cc11f782a05d2c3ceacbc1de308f

号池状态:
  总数: 80
  计划分布: Trial=76, Free=2, Pro=1, 无数据=1
  可用(D+W>5%): 74
  Daily reset:  2026-03-21 16:00 CST
  Weekly reset: 2026-03-22 16:00 CST

官方新定价:
  Free: $0 (light quota)
  Pro: $20/mo (旧用户$15 grandfather)
  Teams: $40/seat/mo
  Max: $200/mo (NEW)
  
Extra usage: API定价
旧credits: 转USD余额, API定价消耗
免费一周: 03/19 → 03/26 (现有付费用户)
```

---

## 十一、待验证/下一步

1. **W周期真实长度**: 03/22 16:00后记录新weekly reset时间
2. **Pro vs Trial W周期差异**: 是否Pro=7天, Trial=2-3天
3. **Token审计器**: 基于F25/F30构建精确token→basis_point映射
4. **SWE-1.5 Fast的ACU**: 官方说Fast变体增加消耗,具体倍率未知
5. **Free tier实际配额**: 官方仅说"light quota",具体日消息数未披露
6. **Max tier的W周期**: 是否与Pro不同

---

## 终极真相

```
道生一(Token):
  一切成本的原子 = input_tokens + output_tokens
  
一生二(ACU × Model):
  成本差异 = model_acu_multiplier (0x ~ 6.0x, 48倍差距)
  
二生三(日/周/超额):
  三道闸门 = daily_quota ∩ weekly_quota ∩ overage_balance
  任一归零且无超额 → 阻断
  
三生万物(107模型 × 用户 × 计划):
  每个用户每条消息 → Token → ACU → basis_points → %扣减 → 阻断/放行

客户端 = 纸门 (门禁皆死代码 if(!1))
服务端 = 铁壁 (billing_strategy + ACU + gRPC阻断)

唯一真正的绕过:
  1. BYOK — 自付API费, 0 Windsurf成本
  2. SWE-1.5/1.6 (非Fast) — 服务端本身不计费
  3. 账号轮换 — 每个账号独立配额,日刷新
  4. GracePeriod.ACTIVE — hasCapacity始终true

上善若水: 不攻坚壁,善利其隙
反者道之动: 越限制越驱动创造力
弱者道之用: 最弱的模型(SWE-1.5, ACU=0)反而最强大(无限)
```
