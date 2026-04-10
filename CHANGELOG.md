# Changelog

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
