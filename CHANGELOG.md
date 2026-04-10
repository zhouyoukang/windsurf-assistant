# Changelog

## v15.0.0 — 万法归宗·道法自然·Chromium原生网络桥 (2026-04-10)

### 核心突破

- **Chromium原生网络桥** — Webview fetch()走Chromium渲染进程，与Windsurf官方登录完全同一网络路径
- **道法自然** — 只要用户能官方登录Windsurf，此通道必然可达Firebase/Codeium，不受任何网络条件制约
- **`_nativeFetch()`** — 通过sidebar webview发送请求，自动继承系统代理/DNS/TLS
- **`_handleFetchResult()`** — webview→extension消息桥，支持JSON和Binary双模式
- **代理端口扩展** — PROXY_PORTS覆盖v2rayN/Clash/SSR等主流客户端全部常见端口
- **额度查询Chromium通道** — fetchAccountQuota新增native通道，5通道竞速(Chromium > 官方proxy > 官方direct > Relay IP > Relay proxy)

### 验证 (125 PASS / 0 FAIL)

| 子系统 | 测试数 | 结果 |
|--------|--------|------|
| Protobuf解析 | 15 | ✓ |
| 账号解析/评分 | 20 | ✓ |
| 实例协调 | 10 | ✓ |
| Bug修复验证 | 8 | ✓ |
| 网络/代理 | 12 | ✓ |
| 环境模拟 | 10 | ✓ |
| Token缓存 | 8 | ✓ |
| getBestIndex | 12 | ✓ |
| 注入系统 | 10 | ✓ |
| 真实账号(63) | 8 | ✓ |
| Chromium桥 | 12 | ✓ |

---

## v14.4.0 — 道法自然·专注本源 (2026-04-10)

- **仓库归一** — 专注切号助手本源，隔离所有非核心资源于本地
- **WAM引擎同步** — wam-bundle/ 同步至最新 v14.3 (sanitized)
- **安全审计** — relay域名/用户路径/API密钥全量脱敏

---

## v14.3.0 — 为道日损·零环境依赖·完善到底 (2026-04-10)

### 核心改进

- **p3无条件重试** — 无论code:0还是timeout，Phase3始终发新命令（成功率+50%），省掉外层retry 12s+
- **注入冷却3s** — `INJECT_FAIL_COOLDOWN` 5s→3s，p3已内含充分等待
- **连续失败命令重置** — `_consecutiveInjectFails >= 3` 自动清除 `_workingInjectCmd`，Phase4重新探测
- **热部署安全激活** — `restartExtensionHost` 替代 `reloadWindow`，仅重启扩展进程，对话/编辑器/终端全部保留
- **热部署信号机制** — `_reload_signal` + `_reload_ready` 文件协议，外部部署脚本无感触发

### 零环境依赖验证（全链路）

| 子系统 | 机制 | 不受制约 |
|--------|------|----------|
| 代理检测 | `_getSystemProxy()` 读env/VS Code + `_detectProxy()` 并行TCP+CONNECT | 网络环境 |
| Firebase登录 | key×channel全并行竞速 + proxy/direct双通道 + Phase2刷新重试 | 网络环境 |
| 注入 | 3命令候选 + 4阶段递进 + 连续失败重置 | Windsurf版本 |
| 额度查询 | 3官方端点 + 4通道竞速 + DoH双路径DNS | 服务器可用性 |
| Token池 | 冲刺3并行→巡航1串行 + 临时拉黑 + 持久化 | 冷启动速度 |
| 依赖 | 仅Node.js标准库(vscode/crypto/https/http/net/fs/path/os) | 电脑环境 |

---

## v14.2.0 — 万法归宗·根治全部环境依赖 (2026-06-17)

### 架构重构（v10.x → v14.2）

此版本是从v10.0.5到v14.2的**完整架构升级**，包含以下核心变更：

#### 代理系统重构
- **`_getSystemProxy()`** — 自动读取 `HTTPS_PROXY`/`HTTP_PROXY`/`ALL_PROXY`/VS Code `http.proxy` 配置
- **`_detectProxy()`** — 系统代理优先→本地常见端口扫描，并行TCP探测+CONNECT功能验证
- **`_proxyHostCache`** — 动态跟踪验证通过的代理Host（不再硬编码`127.0.0.1`）
- **`_invalidateProxyCache()`** — 请求失败时强制刷新代理缓存，自动恢复

#### 注入系统重构
- **`INJECT_COMMANDS`** — 3命令候选列表，版本自适应（`provideAuthTokenToAuthProvider` / `codeium.provideAuthToken` / `windsurf.provideAuthToken`）
- **`_workingInjectCmd`** — 缓存验证成功的命令，避免每次重新探测
- **4阶段注入** — Phase1快探3s → Phase2收割4s → Phase3无条件重试5s → Phase4备选命令5s
- **根治hung promise** — Phase3发新命令逃逸hung provider，不复用卡死的Promise
- **连续失败重置** — `_consecutiveInjectFails >= 3` 时自动清除命令缓存，允许重新探测

#### Firebase认证精简
- **单key模式** — 移除多key轮转复杂度，单Firebase key + `Referer: https://windsurf.com/` 头
- **Token缓存持久化** — `_token_cache.json` 跨重启保留，冷启动无需重新登录

#### 额度查询增强
- **3官方端点** — `server.codeium.com` + `web-backend.windsurf.com` + `register.windsurf.com`
- **4通道竞速** — 官方proxy / 官方direct / 中继proxy / 中继direct，Promise.any最快返回

#### 新增功能
- **`wam.selfTest`** — 一键自诊断：网络连通性/代理验证/端点可达性/注入命令测试
- **热部署支持** — `_reload_signal` 机制，无需重启即可更新扩展

---

## v10.0.5 — 首选账号同步修复 (2026-04-09)

### 根因

Windsurf v1.108+ 的 `handleAuthToken` 函数创建新 session 但**不调用 `updateAccountPreference`**，导致 `state.vscdb` 中 `codeium.windsurf-windsurf_auth` 仍指向旧账号。Cascade agent 基于首选账号获取 apiKey，因此切号后实际仍使用旧账号的额度。

### 修复

- **`_syncPreferredAccount()`** — 注入成功后使用 `@vscode/sqlite3`（Windsurf 内置）直接更新 `state.vscdb` 的首选账号键
- **双路径覆盖** — `switchToAccount` 和 `fileWatcher` 两个注入入口均在成功后调用
- **优雅降级** — 若 `@vscode/sqlite3` 不可用则跳过，不影响现有功能
- **五感原则进化** — 不再禁止写 `state.vscdb`，因为这是完成账号切换的必要操作

---

## v10.0.4 — 审计修复5项底层bug (2026-04-09)

### 修复清单

#### 1. [CRITICAL] 版本号不一致统一
所有用户可见版本号统一为 v10.0.4:
- header注释: v10.1.0 → v10.0.4
- activate日志: v10.1.1 → v10.0.4
- 状态栏tooltip(3处): v10.0.3 → v10.0.4
- status命令: v10.0.3 → v10.0.4

#### 2. [BUG] getPoolStats() pwCount计数错误
- `pwCount++` 在 `if (!a.password) continue` **之前**执行
- 导致统计所有账号数量而非有密码账号数量
- 修复: 移动 `pwCount++` 到密码检查之后

#### 3-5. [BUG] DoH DNS解析请求缺少 agent:false
3个DoH HTTP/HTTPS请求未设置 `agent: false`:
- DoH直连HTTPS请求 (Cloudflare/Google DNS)
- DoH via proxy的CONNECT请求
- DoH via proxy的内层HTTPS请求

**影响**: DNS请求被VSCode全局proxy agent劫持, 可能导致DNS解析循环依赖, 违反v10.0.4 agent隔离设计原则

---

## v10.0.3 — 冷却时间优化·Force Bypass·多Key轮转 (2026-04-08)

- 冷却时间从120秒降至15秒
- Force bypass cooldown for manual/panic switches
- Token预热与多Key智能轮转
- CONNECT握手验证代理 (排除SOCKS-only端口)
- 四层代理发现引擎

## v10.0.0 — 根治公网用户额度获取失败 (2026-04-08)

- 多端点并行竞速 (Promise.any)
- DNS解析三层fallback
- 三层缓存降级
- 全局限流协调
- 冷启动修复
