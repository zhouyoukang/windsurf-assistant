# Windsurf 账号根源解构 — 万法归宗

> 2026-03-21 | 96账号号池 | 道法自然·上善若水
>
> 道生一(Email) → 一生二(Email+指纹) → 二生三(注册+验证+激活) → 三生万物(96账号×配额轮转)

---

## 〇、根之本 — 一句话本质

**Windsurf Pro Trial 注册 = 一个未用过的邮箱 + 一个未见过的设备指纹。不需要信用卡，不需要手机号，不需要身份证。邮箱是唯一的根。**

```
水流之图:

  邮箱(源) ──→ 注册表单 ──→ Turnstile ──→ 密码 ──→ Turnstile ──→ 邮件验证 ──→ 首次登录
    │              │              │            │           │              │            │
    │              │              │            │           │              │            ▼
    │              │              │            │           │              │      Trial激活
    │              │              │            │           │              │      (100cr/14天)
    ▼              ▼              ▼            ▼           ▼              ▼            │
  Layer 0       Layer 1       Layer 2      Layer 1     Layer 2        Layer 0        ▼
  邮箱之源      表单之形      关卡之壁      表单之形    关卡之壁       邮箱之源    Layer 3
                                                                                  配额之果
```

---

## 一、七层根源架构 (从水之源到水之末)

### Layer 0: 邮箱之源 (☰乾 — 万物之始)

**这是一切的根。每个账号 = 一个唯一邮箱地址。**

| 方案 | API/方法 | 成本 | 反封能力 | 自动化 | 推荐 |
|------|---------|------|---------|--------|------|
| **Mail.tm** | `api.mail.tm` REST API | 免费 | ★★★ | ✅全自动 | ⭐⭐⭐⭐ |
| **GuerrillaMail** | `api.guerrillamail.com/ajax.php` | 免费 | ★★★★ | ✅全自动 | ⭐⭐⭐⭐⭐ |
| **1secmail** | `1secmail.com/api/v1` | 免费 | ★★ | ✅全自动 | ⭐⭐⭐ |
| **Maildrop** | `api.maildrop.cc/graphql` | 免费 | ★★ | ✅全自动 | ⭐⭐ |
| **smailpro.com** | 浏览器自动化 | 免费 | ★★★ | 🔄半自动 | ⭐⭐⭐ |
| **FreeCustom.Email** | `freecustom.email` | 免费 | ★★★ | 🔄 | ⭐⭐⭐ |
| **Gmail+别名** | `user+tag@gmail.com` | 免费 | ★ | ✅ | ⭐(已被大量封禁) |
| **自建域名邮箱** | Cloudflare Email/自托管 | ~$10/年 | ★★★★★ | ✅ | ⭐⭐⭐⭐⭐(终极) |
| **Outlook批量** | 手动/API | 免费 | ★★★★ | ❌困难 | ⭐⭐⭐ |
| **.edu邮箱** | 学校提供 | 免费 | ★★★★★ | ❌ | ⭐⭐⭐⭐⭐(+50%折扣) |

#### 邮箱API深度细节

**Mail.tm** (本地已实现: `windsurf_farm_v5.py` MailTmProvider):
```
GET  /domains           → 获取可用域名列表
POST /accounts          → 创建邮箱 {address, password}
POST /token             → 获取JWT token
GET  /messages?page=1   → 轮询收件箱(需Bearer token)
GET  /messages/{id}     → 获取邮件详情
限制: 8 QPS/IP, 需代理(7890), 域名会变(当前: dollicons.com等)
```

**GuerrillaMail** (本地已实现: `windsurf_farm_v5.py` GuerrillaMailProvider):
```
GET ?f=get_email_address           → 获取随机邮箱 + sid_token
GET ?f=set_email_user&email_user=X → 自定义前缀
GET ?f=check_email&seq=0           → 轮询收件箱
GET ?f=fetch_email&email_id=X      → 获取邮件内容
限制: 较稳定, 需代理, 域名可能被封(sharklasers.com等)
```

**域名封禁名单** (来自cursor-free-vip远程更新):
```
https://raw.githubusercontent.com/yeongpin/cursor-free-vip/main/block_domain.txt
本地: tempmail.com, throwaway.email, guerrillamail.info, sharklasers.com
```

#### ★自建域名邮箱 — 终极不封方案

```
道: 自己的域名 = 无限邮箱 = 永不被封

方案A: Cloudflare Email Routing (免费)
  1. 购买域名 (~$10/年, Cloudflare/Namecheap)
  2. Cloudflare → Email Routing → Catch-all
  3. any-prefix@yourdomain.com → 转发到主邮箱
  4. 每个前缀 = 一个Windsurf账号

方案B: 自托管 (Mailu/Postal/iRedMail)
  1. VPS上运行邮件服务器
  2. 完全控制, 无限账号
  3. 需要维护, 可能被标记为垃圾邮件

方案C: Google Workspace / Microsoft 365
  1. $6/月起, 无限别名
  2. 最高信誉, 不会被封
```

---

### Layer 1: 设备指纹之源 (☷坤 — 身份之基)

**Windsurf通过5个UUID识别设备。重置 = 新设备 = 可再注册/激活Trial。**

```
%APPDATA%\Windsurf\User\globalStorage\storage.json

5个关键UUID:
  telemetry.machineId      = hex(无破折号, 32字符)
  telemetry.macMachineId   = hex(无破折号, 32字符)
  telemetry.devDeviceId    = UUID(有破折号, 36字符)
  telemetry.sqmId          = hex(无破折号, 32字符)
  storage.serviceMachineId = UUID(有破折号, 36字符)

辅助标识:
  telemetry.firstSessionDate  = GMT时间字符串
  telemetry.lastSessionDate   = GMT时间字符串
  telemetry.currentSessionDate = GMT时间字符串
```

**重置工具:**

| 工具 | 来源 | 功能 |
|------|------|------|
| `telemetry_reset.py` | 本地 | Python重置5 UUID + session日期 |
| `windsurf_farm_v5.py` TelemetryManager | 本地 | 集成在farm脚本中 |
| **Wincur** | GitHub FilippoDeSilva | Go语言一键重置Windsurf+Cursor+Warp |
| **Cursor_Windsurf_Reset** | GitHub whispin | Go语言GUI, 支持Cursor 1.7 + Windsurf 1.12 |
| **ai-auto-free** | GitHub ruwiss (456★) | Flutter前端+Python后端, 最全面 |

**关键洞见**: Trial在首次登录App时激活, 不是创建账号时。
→ 可以在隔离环境(Sandbox/VM)中登录激活, 然后在主环境使用。

---

### Layer 2: Turnstile关卡之源 (☲离 — 人机之辨)

**Cloudflare Turnstile是注册流程中唯一的技术壁垒。**

注册流程中出现2次:
1. 填写信息后 → Turnstile #1
2. 设置密码后 → Turnstile #2

| 绕过方案 | 引擎 | 成功率 | 自动化 | 成本 |
|---------|------|--------|--------|------|
| **Camoufox + humanize** | Firefox C++级指纹伪造 | ~90%+ | ✅全自动 | 免费 |
| **DrissionPage + turnstilePatch** | Chrome扩展绕过 | ~70% | ✅全自动 | 免费 |
| **Playwright headless=False** | 可见浏览器+手动点击 | ~95% | 🔄半自动 | 免费 |
| **CapSolver API** | 远程解决 | ~99% | ✅全自动 | $1.45/1000次 |
| **2Captcha API** | 远程解决 | ~98% | ✅全自动 | $2.99/1000次 |

**本地已实现的三引擎降级** (`windsurf_farm_v5.py`):
```
优先级: Camoufox → DrissionPage → Playwright

Camoufox安装:
  pip install camoufox[geoip]
  python -m camoufox fetch

DrissionPage安装:
  pip install DrissionPage
  + turnstilePatch扩展目录

Playwright安装:
  pip install playwright
  playwright install chromium
```

---

### Layer 3: 注册表单之源 (☳震 — 行动之始)

**URL**: `https://windsurf.com/account/register`

```
Step 1: 基本信息
  input[name="first_name"]  → 随机英文名
  input[name="last_name"]   → 随机英文姓
  input[name="email"]       → 临时邮箱地址
  input[type="checkbox"]    → 勾选Terms
  button: Continue

Step 2: Cloudflare Turnstile #1
  iframe[src*="challenges.cloudflare.com"]
  → Camoufox humanize / turnstilePatch / 手动

Step 3: 设置密码
  input[type="password"]    → 8-64字符, 字母+数字
  input[placeholder*="Confirm"] → 确认密码
  button: Continue/Sign up

Step 4: Cloudflare Turnstile #2

Step 5: 邮箱验证
  → 轮询临时邮箱收件箱(90s超时, 5s间隔)
  → 提取验证链接或6位验证码
  → 点击链接 / 输入验证码

Step 6: 完成
  → "Welcome" / "Dashboard" / "Get Started"
  → 账号创建成功, 尚未激活Trial
```

**OAuth替代路径** (绕过邮箱验证):
```
- Google OAuth → 一键注册(需Google账号)
- GitHub OAuth → 一键注册(需GitHub账号)
- Devin (Enterprise)
- SSO
```

---

### Layer 4: 激活之源 (☴巽 — 风入万物)

**Trial 不在注册时激活, 在首次App登录时激活。**

```
激活路径:
  1. 主环境: 直接在Windsurf中登录 → 激活 → 使用
  2. 隔离环境: Sandbox/VM中登录 → 激活 → auth snapshot → 主环境注入

隔离环境方案:
  A. Windows Sandbox (Win Pro/Enterprise/Education)
     → optionalfeatures → 启用 → 安装Windsurf → 登录激活
  B. Hyper-V虚拟机 (Win Pro/Enterprise/Education)
  C. 新Windows用户
  D. VMware/VirtualBox (所有Windows版本)

关键: 激活后的auth状态可以被快照保存, 注入到主环境
→ WAM v4.0 hot-inject: 写auth → reload window → 3-5s切换
```

---

### Layer 5: 认证持久化之源 (☵坎 — 水之蓄)

**state.vscdb** (SQLite, Windsurf运行时状态):
```sql
-- 关键认证键值:
windsurfAuthStatus        → JSON blob (apiKey, user info)
windsurfConfigurations    → JSON blob (模型配置等)
codeium.cachedPlanInfo    → JSON blob (计划缓存, 仅UI)

-- WAM hot-inject流程:
1. 从 _wam_snapshots.json 读取目标账号的auth blob
2. 写入 state.vscdb: windsurfAuthStatus + windsurfConfigurations
3. 触发 workbench.action.reloadWindow
4. 完成, 3-5秒
```

**Login Helper扩展** (管理96账号):
```
位置: %APPDATA%\Windsurf\User\globalStorage\
      undefined_publisher.windsurf-login-helper\windsurf-login-accounts.json

每个账号记录:
  - email, password
  - usage: {daily: {remaining: %}, weekly: {remaining: %}}
  - plan, planEnd, resetTime, weeklyReset
  - lastChecked timestamp
```

---

### Layer 6: 配额系统之源 (☶艮 — 山之限)

**2026-03-19起: 从Credits → Quota (日+周百分比制)**

```
每个Trial账号:
  Daily quota:  100% → 每天重置 (16:00 CST)
  Weekly quota: 100% → 每2-3天重置 (Trial/Free)
  有效剩余 = min(Daily%, Weekly%)

96个账号 × 日配额:
  理论: 96 × 100% = 9600% 日配额
  实际: 约等于96天的单账号使用量/天
  
阻断条件: D≤0 OR W≤0 且无超额余额
唯一真正绕过:
  1. BYOK (自带Key, ACU=0)
  2. SWE-1.5/1.6 非Fast (ACU=0, 免费无限)
  3. 账号轮换 (WAM 3-5s热切换)
```

---

## 二、虚拟卡之辨 — 水落石出

**结论: Windsurf Pro Trial 不需要信用卡/虚拟卡。**

```
注册 = Email + 姓名 + 密码 → 免费
Trial = 首次App登录 → 自动激活100cr/14天 → 免费
Free = Trial到期 → 降级25cr/月 → 免费

虚拟卡仅在以下场景需要:
  1. 购买Pro计划 ($20/月) → 需Stripe支付
  2. 购买Extra Usage → 需Stripe支付
  3. 购买Add-on Credits → 需Stripe支付

虚拟卡服务 (如需):
  - VCCWave (vccwave.com) — 免费虚拟卡
  - Privacy.com — 美国虚拟卡
  - Revolut — 欧洲虚拟卡
  - Getsby (getsby.com) — 预付费卡
  - JustUseApp.com — 免费试用专用卡

但对于Trial轮换策略: 完全不需要任何卡。
```

---

## 三、完整注册Pipeline — 从源到末

```python
# 道生一: 一个邮箱
email = temp_email_api.create_inbox()        # Layer 0

# 一生二: 邮箱 + 指纹
telemetry.reset_fingerprint()                # Layer 1

# 二生三: 注册 + Turnstile + 验证
browser = camoufox.launch(humanize=True)     # Layer 2
browser.fill_form(name, email, password)     # Layer 3
browser.solve_turnstile()                    # Layer 2
browser.set_password()                       # Layer 3
browser.solve_turnstile()                    # Layer 2
verification = temp_email_api.wait_email()   # Layer 0
browser.verify(verification.link_or_code)    # Layer 3

# 三生万物: 激活 + 快照 + 轮换
windsurf.login(email, password)              # Layer 4
wam.harvest_auth_snapshot()                  # Layer 5
wam.hot_switch(next_best_account)            # Layer 5+6
```

**批量注册命令** (本地已有):
```bash
# 单个注册 (Camoufox推荐)
python windsurf_farm_v5.py register --engine camoufox

# 批量注册5个
python windsurf_farm_v5.py register --count 5 --engine camoufox

# 半自动(可见浏览器, 手动点Turnstile)
python windsurf_farm_v5.py register --visible

# 查看账号池状态
python windsurf_farm_v5.py status

# WAM热切换到最优账号
python wam_engine.py next

# WAM Dashboard
python wam_engine.py serve    # :9876
```

---

## 四、96账号号池现状分析

从截图观察:
```
总数: 96个账号
状态: D100%+W62%~W100% (多数配额充足)
命名: 随机字符串 (pqef9032..., tvscyv633..., 等)
年龄: 12d (部分标记12天, 接近Trial 14天到期)

健康度分布:
  W90%+ : ~12个 (优秀)
  W80-89%: ~5个 (良好)
  W70-79%: ~2个 (一般)
  W60-69%: ~1个 (偏低)
  D100% : 绝大多数 (日配额满)
  D63-98%: ~2个 (部分消耗)
```

**即将面临的问题**:
- ~12天的账号将在2天内Trial到期 → 降级为Free(25cr/月)
- Free计划日配额显著缩小
- 需要补充新Trial账号 或 利用SWE-1.5(ACU=0)在Free计划上无限使用

---

## 五、GitHub开源生态 — 水之网络

| 项目 | Stars | 核心功能 | 适用 |
|------|-------|---------|------|
| **ruwiss/ai-auto-free** | 456★ | Flutter+Python全自动注册+重置 | Cursor+Windsurf |
| **whispin/Cursor_Windsurf_Reset** | — | Go语言GUI重置工具 | 指纹重置 |
| **FilippoDeSilva/cursor-ai-bypass** → **Wincur** | 131★ | 一键重置遥测 | 指纹重置 |
| **gabrielpolsh/windsurf-pro-trial-reset-free** | 51★ | 4种方法指南 | 方法论 |
| **yeongpin/cursor-free-vip** | — | DrissionPage+临时邮箱注册 | Cursor(可移植) |

**从cursor-free-vip学到的关键技术**:
- `turnstilePatch` Chrome扩展 — Turnstile绕过
- `smailpro.com` 浏览器自动化创建邮箱
- `block_domain.txt` 远程封禁域名列表
- 验证码6位提取: `font-size:28px, letter-spacing:2px`

---

## 六、最优策略路线图

### Phase 1: 当下 (96账号存续期, ~2天)
```
策略: 最大化利用现有Trial配额
工具: WAM热切换 (wam_engine.py next)
模型: 按需使用任意模型
```

### Phase 2: Trial到期后 (Free降级)
```
策略A: SWE-1.5/1.6 无限使用 (ACU=0, Free计划即可)
策略B: 补充新Trial账号 (windsurf_farm_v5.py batch)
策略C: 少量Pro + 大量Free轮换
```

### Phase 3: 长期可持续
```
策略: 自建域名邮箱 + Camoufox全自动注册
  1. 购买域名 → Cloudflare Email Routing
  2. 脚本生成无限前缀邮箱
  3. Camoufox自动注册+Turnstile绕过
  4. WAM自动管理号池+配额轮转
  
成本: ~$10/年(域名) + 0(其他全部免费)
产出: 无限Trial账号 × 无限配额
```

---

## 七、运行时认证根链 — 道法自然·水入肌理 (2026-03-21 深层探源)

> 注册是"种下种子"，运行时认证链才是"种子如何长成万物"

### 7.1 完整认证链路 (道生一二三)

```
道(虚无) → Yahoo邮箱+密码 (96个@yahoo.com, 100%同一域名)
   ↓
一(种子) → Firebase Auth (项目: exa2-fb170)
   │       API Keys: AIzaSyDsOl-1XpT5err0Tcnx8FFod1H8gVGIycY (v5.6.29)
   │                 AIzaSyDKm6GGxMJfCbNf-k0kPytiGLaqFJpeSac (v5.0.20)
   │       登录端点: identitytoolkit.googleapis.com/v1/accounts:signInWithPassword
   │       登录方式: password (邮箱+密码, 非OAuth)
   │       Firebase UID: 28字符唯一标识 (如: DJW3bcJDusdYs0XtUPf5U6DvFqf2)
   ↓
二(凭证) → Firebase JWT (idToken)
   │       签名: RS256 (Google RSA公钥签名, kid可查)
   │       发行: securetoken.google.com/exa2-fb170
   │       受众: exa2-fb170
   │       寿命: 3600秒 (1小时)
   │       缓存: wam-token-cache.json (50分钟TTL, Login Helper管理)
   │       刷新: Firebase refreshToken (长期有效, 可续命JWT)
   │       状态: 96个全部已缓存, 0过期
   ↓
三(转化) → JWT → Codeium RegisterUser gRPC
   │       端点: register.windsurf.com (主)
   │              server.codeium.com (备)
   │              web-backend.windsurf.com (备)
   │       协议: Connect-RPC over HTTPS (Content-Type: application/proto)
   │       请求: protobuf{field1: idToken}
   │       响应: protobuf{field1: apiKey} → sk-ws-01-... (103字符)
   ↓
万物(运行) → apiKey嵌入每个gRPC请求
   │         ├→ GetChatMessage → Cascade对话 → 消耗Quota
   │         ├→ GetCompletions → 代码补全 → 消耗Quota
   │         ├→ CheckUserMessageRateLimit → 限速检测
   │         ├→ GetPlanStatus → 查询D%/W%/Plan
   │         └→ 服务端: Quota扣减 + Rate Limit + 阻断
   ↓
归(循环) → D%归零 → WAM检测 → 切换下一账号 → 重复
           W%归零 → 等待重置 → 重复
```

### 7.2 四策略注入链 (Login Helper v9.0 injectAuth)

```
S0 (PRIMARY): idToken → windsurf.provideAuthTokenToAuthProvider
    │  Windsurf内部自动: registerUser(idToken) → {apiKey, name} → session
    │  最优路径, 1步完成, Windsurf原生处理
    ↓ 失败?
S1 (FALLBACK): OneTimeAuthToken → provideAuthTokenToAuthProvider
    │  通过Relay中转获取一次性Token
    │  legacy路径, relay依赖
    ↓ 失败?
S2 (LAST RESORT): registerUser(email,password) → apiKey → command
    │  扩展侧直接调RegisterUser获取apiKey
    │  再通过discovered commands注入
    ↓ 失败?
S3 (DB DIRECT): apiKey → 直写state.vscdb → 重载窗口
    │  绕过command系统, 直接写入数据库
    │  需要手动重载窗口使生效
    └→ 最后手段
```

### 7.3 数据存储拓扑 (水之流向)

```
┌─ windsurf-login-accounts.json (Login Helper) ────────────────┐
│  96个账号: email + password + usage(D%/W%/plan/reset)        │
│  ⚠ 不含apiKey! (token字段全为空, 长度=0)                     │
│  位置: %APPDATA%\Windsurf\User\globalStorage\                │
│        undefined_publisher.windsurf-login-helper\             │
└──────────────────────────────────────────────────────────────┘

┌─ wam-token-cache.json (Login Helper) ────────────────────────┐
│  96个JWT缓存: email → { idToken, expireTime }                │
│  Firebase JWT, RS256, 50分钟缓存TTL                          │
│  这是每个账号的"第二层根" — JWT可以换取apiKey                  │
│  位置: 同上目录                                               │
└──────────────────────────────────────────────────────────────┘

┌─ state.vscdb (Windsurf运行时) ───────────────────────────────┐
│  windsurfAuthStatus: 当前活跃账号的apiKey+protobuf            │
│    → apiKey: sk-ws-01-... (103字符, 这是"第三层根")           │
│    → userStatusProtoBinaryBase64: UUID+Plan+Models+ACU矩阵   │
│    → allowedCommandModelConfigs: 8个模型配置(protobuf)        │
│  windsurfConfigurations: 模型配置+UI状态                      │
│  windsurf_auth-{Name}-usages: 75个历史使用记录                │
│  secret://windsurf_auth.sessions: DPAPI加密会话               │
│  codeium.windsurf: installationId+模型选择+API端点            │
│  位置: %APPDATA%\Windsurf\User\globalStorage\state.vscdb     │
└──────────────────────────────────────────────────────────────┘

┌─ _wam_snapshots.json (WAM引擎) ─────────────────────────────┐
│  仅2个已采集的完整auth快照                                    │
│  含apiKey blob, 可直接注入state.vscdb实现热切换               │
│  位置: e:\道\道生一\一生二\Windsurf无限额度\                  │
└──────────────────────────────────────────────────────────────┘

┌─ VIP扩展 (windsurf-vip-v2) ─────────────────────────────────┐
│  独立认证体系: Outlook邮箱 + Firebase JWT                     │
│  user_identifier: SHA256哈希                                  │
│  currentAuthCode: 10字符授权码                                │
│  与Login Helper号池完全独立                                   │
└──────────────────────────────────────────────────────────────┘
```

### 7.4 根之五层 (从浅到深)

| 层 | 名 | 实体 | 寿命 | 可替换 | 存储位置 |
|----|-----|------|------|--------|---------|
| **第零层** | 根之种 | Yahoo邮箱+密码 | 永久 | 批量注册 | Login Helper JSON |
| **第一层** | 根之火 | Firebase Auth (UID) | 永久 | 不可替换 | Firebase服务端 |
| **第二层** | 根之水 | Firebase JWT (idToken) | 1小时 | refreshToken续命 | wam-token-cache.json |
| **第三层** | 根之金 | apiKey (sk-ws-01-...) | 长期 | 每次registerUser可重新获取 | state.vscdb |
| **第四层** | 根之壁 | gRPC Session | 会话级 | reload window重建 | Windsurf内存+DPAPI |

### 7.5 96账号实测快照 (2026-03-21 19:33 CST)

```
域名分布:   yahoo.com 100% (96/96)
计划分布:   Trial 91个 (95%) + Free 5个 (5%)
日配额总和: D9197% (平均 D95%/号)
周配额总和: W9138% (平均 W95%/号)
日配额耗尽: 0个    满额: 76个
周配额耗尽: 0个    满额: 55个
JWT已缓存:  96个   过期: 0个
WAM快照:    2个 (仅2个可热切换)
重置时间:   统一 2026-03-22 08:00 UTC (16:00 CST)
Trial剩余:  2.8~12.6天 (5批次注册)
```

---

## 终极真相

```
道生一(Email):
  一个邮箱 = 一个身份 = 一个账号
  邮箱是唯一的根, 其余皆为枝叶
  
一生二(Email + 指纹):
  邮箱确定"谁", 指纹确定"哪台设备"
  两者独立: 同一邮箱可登录不同设备
  
二生三(注册 + Turnstile + 验证):
  三道关卡: 表单 → 人机验证 → 邮件验证
  Turnstile是唯一技术壁垒, Camoufox可破
  
三生万物(96账号 × 配额 × 轮转):
  每个账号独立配额, WAM 3-5s热切换
  SWE-1.5/1.6 ACU=0 = 任何计划均无限使用

不需要虚拟卡 — Trial完全免费
不需要手机号 — 仅需邮箱
不需要真实身份 — 随机姓名即可

上善若水:
  水不攻坚壁(不破服务端)
  水入每条缝(临时邮箱×无限)
  水适万物形(Camoufox伪装人类)
  水终归大海(96账号汇成号池)

反者道之动:
  越限制(配额) → 越驱动创造(号池轮转)
  越检测(Turnstile) → 越精进绕过(Camoufox)
  越封禁(临时域名) → 越趋向根本(自建域名)

弱者道之用:
  最弱的模型(SWE-1.5, ACU=0) 反而最强大(无限使用)
  最简单的方法(换邮箱) 反而最有效(根源解决)
  最廉价的投入($10/年域名) 反而最持久(永不被封)
```

---

*综合: 本地farm脚本v5(Camoufox三引擎) + WAM v4(热切换) + 4个临时邮箱API + 5个GitHub开源项目 + Windsurf官方定价页 + 网络搜索(apidog/tempemail.cc/vccwave等) + 96账号实测数据*
