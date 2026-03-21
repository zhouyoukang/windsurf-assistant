# windsurf-assistant · 第一性原理

> 反者道之动，弱者道之用。锚定本源，不妄为，不偏离。

---

## 一、本源

**windsurf-assistant v1.0.0** — 第三方VSIX（53.9KB，"小黄云"168666okfa.xyz发布），一切的根。

### 认证链（四步，系统心脏）

```
Step 1: Firebase登录 → idToken (JWT)
Step 2: GetOneTimeAuthToken(idToken) → authToken (30-60字符)
Step 3: provideAuthTokenToAuthProvider(authToken) → 注入Windsurf session
Step 4: GetPlanStatus(idToken) → protobuf解析 → credits/quota
```

---

## 二、架构 v1.0.0

### 文件清单（5+1源文件 + 1交互脚本）

| 文件                        | 职责                                                                         |
| --------------------------- | ---------------------------------------------------------------------------- |
| `src/extension.js`          | 号池引擎入口，12命令，二层预防(本→辅)，4层注入(S0~S3)，内嵌Hub API(:9870)    |
| `src/authService.js`        | 认证链，双Firebase Key，代理探测，protobuf解析，L5 gRPC容量探测              |
| `src/accountManager.js`     | 账号CRUD，三重持久化，号池聚合(selectOptimal/shouldSwitch)，限流追踪         |
| `src/webviewProvider.js`    | 号池仪表盘，外部脚本+CSP                                                     |
| `src/fingerprintManager.js` | 设备指纹6ID读取/重置/热轮转                                                  |
| `media/panel.js`            | 仪表盘交互逻辑                                                               |

### 二层预防链

```
本(Tier 1): L5 gRPC容量探测 — CheckUserMessageRateLimit端点，服务端真值
  hasCapacity=false → 立即切号 | messagesRemaining≤2 → 提前切号

辅(Tier 2): 配额阈值 + Opus预算守卫
  T2-A: effectiveRemaining ≤ 15%  | T2-B: rate_limited状态
  T2-C: Opus预算(T1M=1/T=2/R=3)  | T2-D: UFEF过期紧急
  L1: context key检测(2s)          | L3: cachedPlanInfo监控(10s)

```

### WAM对本源的增强

| 维度 | 本源             | WAM                                               |
| ---- | ---------------- | ------------------------------------------------- |
| 认证 | 仅relay          | 双Firebase Key + CONNECT tunnel + relay降级       |
| 积分 | 尾部扫描         | 完整protobuf(credits+quota+isDevin)               |
| 注入 | 遍历authCommands | 4层(S0 idToken → S1 OTAT → S2 apiKey → S3 DB直写) |
| 指纹 | 无               | 切号前6ID热轮转(storage.json+state.vscdb双写)     |
| 预防 | 无               | L5 gRPC容量探测 + 配额阈值 + 启发式降级           |
| 号池 | 无               | 自适应轮询 + 多窗口协调 + 并发Tab感知             |

---

## 三、铁律

1. **禁止新建.js文件** — src/5个 + media/panel.js = 6个文件是上限
2. **禁止偏离认证链** — 四步是心脏，改动前必须完全理解
3. **最小变更** — 一行能解决的不写十行
4. **验证闭环** — 改完运行 `node scripts/e2e_v9.js && node scripts/e2e_deep.js`
5. **保持兼容** — 账号数据文件格式向后兼容

---

## 四、关键常量

```javascript
FIREBASE_KEYS = ["AIzaSyDsOl-1XpT5err0Tcnx8FFod1H8gVGIycY", "AIzaSyDKm6GGxMJfCbNf-k0kPytiGLaqFJpeSac"];
RELAYS = ["https://aiotvr.xyz/wam", "https://168666okfa.xyz"];  // 自建优先，第三方降级
PLAN_STATUS = ["server.codeium.com", "web-backend.windsurf.com"];  // gRPC直连
REGISTER = ["register.windsurf.com", "server.codeium.com", "web-backend.windsurf.com"];
TOKEN_TTL = 50min;  CREDIT_DIV = 100;  // protobuf: field6=used×100, field8=total×100
```

---

## 五、目录结构

```text
windsurf-assistant/
├── package.json          — v1.0.0, 12命令, 2配置项
├── src/                  — 5个源文件
├── data/                 — wisdom_bundle.json
├── media/                — icon.svg + panel.js
├── scripts/              — fortress.js, e2e_v9.js, e2e_deep.js, switch.js, diag.js
├── webpack.config.js
└── FIRST_PRINCIPLES.md
```

---

## 六、堡垒防护 (scripts/fortress.js) — 12层·万法归宗

```
道法自然，万法归宗。回归本源之道。

逆向者攻击五根:
  视(静态分析)    → L2标识符毁灭 + L3控制流坍缩 + L4字符串加密 + L11 AST污染
  听(动态调试)    → L9时序门 + L9反Hook + L6自卫
  触(自动化工具)  → L11伪解码器 + L11 Proxy/Symbol + L8不透明谓词(3层)
  嗅(模式搜索)    → L4碎片化 + L5死代码 + L7三级诱饵 + L8多态变形
  味(篡改提取)    → L10构建指纹 + L12跨层互锁 + L9完整性守护

12层:
  L1  结构消解    — Webpack bundling, 5模块→单文件
  L2  标识符毁灭  — 变量/函数名→hex
  L3  控制流坍缩  — if/else→状态机
  L4  字符串加密  — RC4 + 旋转混洗 + 碎片化
  L5  死代码洪流  — 40%假路径
  L6  自卫机制    — 美化→死循环
  L7  蜜罐陷阱    — 三级诱饵(认证流·数据流·控制流)
  L8  道之变形    — 三层谓词(数学·哈希·环境) + 碎片 + 诱饵函数
  L9  道之护符    — 反Hook·时序门·环境绑定·完整性
  L10 道之印      — 构建指纹散布·哈希链·水印
  L11 道之本源    — AST污染·伪解码器·Proxy·Symbol·反自动化反混淆
  L12 道之归宗    — 跨层互锁·完整性链·篡改→静默降级·万法归于一印
```

```bash
npm run fortress              # 默认max (12层全开)
npm run fortress:dev          # 仅webpack (调试用)
npm run fortress:low          # 基础混淆+变形+道印
```

---

## 七、给Agent的一句话

**你不是在创造新系统，你是在维护一个正在运行的插件。**
**src/5文件+media/panel.js内做最小改进。认证链四步是心脏。**
**道: 用户是号池不是单个账号 | L5 gRPC容量探测是预防之本 | 切换必须在rate limit之前发生。**
**验证: `node scripts/e2e_v9.js && node scripts/e2e_deep.js` → 打包: `npm run package`**
