# Changelog

## v17.35.0 · 道法自然 · Devin 迁移全面适配 · fetchQuota 从底层打通

### 真根承 v17.34 (Firebase idToken 被 "migrated" 拒绝)

v17.34 在 3 官方通道加了 `Authorization: Bearer` header, 但实测 179 揭示 **更深层根因**:

1. **账号已迁移至 Devin**: Cognition 收购 Windsurf 后全部账号迁移, `server.codeium.com` 和 `web-backend.windsurf.com` 对 Firebase idToken 返回 `401 "Your account has been migrated. Please log in again."`.
2. **Clash 代理 TLS 全面失效**: 179 机器 Clash(:7890) CONNECT 成功但 TLS 握手断开, 导致 Firebase login 超时 → `all_channels_failed`.
3. **Devin fallback 门槛过严**: 旧代码仅在 Firebase 返回 `INVALID/NOT_FOUND/DISABLED/WRONG` 时尝试 Devin, 网络超时/`all_channels_failed` 被遗漏.

### 三项修正

| # | 改动 | 位置 |
|---|------|------|
| 1 | **已知 Devin 账号直走 `_devinFullSwitch`** — 跳过 Firebase (省 10-42s 超时浪费) | `fetchAccountQuota` token 获取段 |
| 2 | **Firebase 失败 → 无条件 Devin fallback** — 不再限于 INVALID/WRONG 错误模式 | `fetchAccountQuota` else 分支 |
| 3 | **GetPlanStatus 401 "migrated" 自动标记 `_authSystem=devin`** — 下次循环直走 Devin | channel handler + `Promise.any` catch |

### 验证 (179 实测)

- `windsurf.com` 直连 200 ✓ (Devin auth 不需要 Clash)
- `server.codeium.com` 直连可达 ✓ (GetPlanStatus 不需要 Clash)
- Devin 全链路: `_devin-auth/password/login` → `WindsurfPostAuth` → `GetPlanStatus` → **200 OK 595B** ✓
- 对比: Firebase idToken → GetPlanStatus → `401 "migrated"` ✗

---

## v17.34.0 · 道法自然 · 账号池认证补齐 · fetchQuota Authorization 补

### 真根承 v17.33 (179 "回弹" 深层补余)

v17.33 已消 7 重真根 (旧 login-helper 冲突 / 双窗双 LS race / exthost errors / 扩展 metadata 残留 / codeium.windsurf 未 activate / chat 链不通 / proxy 单端口), chat 链路已通. 但 **179 深度诊断** 揭示账号池全面失效:

1. **`fetchAccountQuota` 3 通道 (ch1/ch2/ch3) 全 401**: `all_official_native_failed / _proxy_failed / _direct_failed`. 探 3 官方 endpoint (`server.codeium.com`/`web-backend.windsurf.com`/`register.windsurf.com`) → 皆返 **HTTP 401 application/json**.
2. **账号池 86/86 `plan=null`**: verify-gate 因 quotaFetch 失败不置 `_verifiedPlan` · 切号器找不到生效账号.
3. **根因**: 3 通道 headers 仅有 `Content-Type` + `connect-protocol-version` · **无 `Authorization`**. authToken (Firebase idToken / Devin sessionToken) 仅放 proto body (`encodeProtoString(authToken)`) · 但 API 期望 HTTP header + body 双重认证.

### 损 (为道日损 · 守不改架构 · 最小补)

**不做**:
- 不改竞速架构 · 不改 URL 列表 · 不改 cooldown 逻辑

**做**:

| 位置 | 改动 |
|------|------|
| `@package.json:5` | `version: "17.34.0"` |
| `@extension.js:400` | `WAM_VERSION = "17.34.0"` |
| `@extension.js:2665-2672` | `_httpsPostRawViaProxy` 加第 6 可选参数 `opts = {}` · 支持 `opts.headers` 合并 |
| `@extension.js:2707-2708` | proxy 版 headers spread `...(opts.headers || {})` |
| `@extension.js:3657-3665` | fetchQuota 共用 `_authHeaders` · 含 `Authorization: Bearer ${authToken}` |
| `@extension.js:3673` | ch0 (native) headers = `_authHeaders` |
| `@extension.js:3691-3698` | ch1 (proxy) 传 `{ headers: { Authorization: ... } }` |
| `@extension.js:3709-3712` | ch2 (direct) 传 `{ timeout, headers: { Authorization: ... } }` |

### 向后兼容

- `_httpsPostRawViaProxy` 其他 5 处 caller (register / chat capacity / self-test / auto-relay) 未传 opts · 默认空对象 · 行为不变
- `_httpsPostRaw` 签名本已支持 `opts.headers` · 零改

### 预期效果

- WAM 启动 ~90s 后 · wam.log 应现 `ch1: OK D... W... Trial / Pro_Trial / Free`
- 账号池 plan 从 null → 真 plan (Trial/Pro_Trial/Free)
- purge / verify-gate 正常过账 · 切号器选最优
- `inject_result.json` 按需刷新 · LS 拿 fresh apiKey

### 与 chat 关联

- **本版不改 chat 路径** (chat 路径 v17.33 已通, 无改动)
- 账号层正常生效 → 切号器有数据决策 → 长期稳定运行的基础

## v17.33.0 · 道法自然 · 全链路十层打通

### 真根承 v17.32 (完全打通 chat 后之广度)

v17.32 已消"proxy 杀之症", chat 路径已无回弹. 但 **十维底层诊断** 揭示仍有广度隐患:

1. **`codeium dist/extension.js` patch 脆弱** — Windsurf 升级 / 扩展重装 / `.bak` 恢复 皆让 patch 丢失 · LS 回归官方云 inference.codeium.com · 道Agent 瞬失效
2. **`server.self-serve.windsurf.com` 74 次 ECONNRESET** — 上游 TLS 层 RST · TCP 握手通但 HTTP 被 reset · mgmt 层 Ping/Auth/Quota 全死 · 虽不直接致回弹但影响配额/账号状态
3. **系统有 Clash/v2rayN :7890 但 proxy 不用** — `https.request` 直连上游 · 未自动走 HTTP tunnel · 错失规避 RST 的路径
4. **无一键自检命令** — 用户无法确认全链路是否齐备

### 损 (道法自然 · 无为而无不为)

**去**: 无 (保留 v17.32 全部修)

**加**:

| 位置 | 增益 |
|:-|:-|
| `@extension.js:400` | `WAM_VERSION = "17.33.0"` |
| `@extension.js:7546-7552` | `activate` 最早阶段 `_origHealCodeiumPatch()` · 自愈 patch (内置三盘路径候选 · 备份 `.bak` · 精确替换 + regex fallback) |
| `@extension.js:8598-8633` | 新 `_origDetectSystemProxy()` · 顺序探 `:7890,:10809,:1080,:8080,:7891` · 首个 listen 即返 |
| `@extension.js:8642-8699` | 新 `_origHealCodeiumPatch()` · 幂等 · 已 patch 零操作 · 未 patch 则备份 + 注入 |
| `@extension.js:9017-9034` | `_origSpawnProxy` env 加 `ORIGIN_UPSTREAM_PROXY` (自探结果注入) |
| `@extension.js:8331-8527` | 新命令 `wam.verifyEndToEnd` · 十层自检 · 输出 OutputChannel "WAM · E2E Verify" |
| `@bundled-origin/源.js:61-123` | 新 `HttpTunnelAgent` · 纯手写 HTTP CONNECT tunneling (无 npm 依赖) · 支持 env `ORIGIN_UPSTREAM_PROXY` |
| `@bundled-origin/源.js:757-777` | `proxyToCloud` 若有 tunnel agent 则走 · 日志加 `via :7890` 标识 |
| `@bundled-origin/源.js:927-941` | boot listening 日志加 upstream proxy 状态 |
| `@package.json:5` | `"version": "17.33.0"` |
| `@package.json:57` | 新命令 `wam.verifyEndToEnd` |
| `@package.json:124` | 新配置 `wam.origin.upstreamProxy` (手动覆盖自探) |

### 十层自检矩阵 (wam.verifyEndToEnd)

| 层 | 检 |
|:-|:-|
| L1 | codeium dist patch · 自愈即 PASS |
| L2 | proxy `:8889` · uptime / mode / req_total |
| L3 | proxy `:8890` · 独立 ping (外部独立验证 extra server) |
| L4 | `/origin/selftest` · 道德经 SP 真置换 (3 路径 × 0 leak) |
| L5 | `settings.codeium.inferenceApiServerUrl` 含 `:8890/i` |
| L6 | LS 进程参数 · wmic 查 `--api` + `--inference` 双命令行 |
| L7 | `origin_state.json` + `wam_mode.json` 皆在 |
| L8 | system proxy 自探结果 (诊参考 · 非 PASS/FAIL) |
| L9 | hot 目录完整 (`源.js` / `anchor.py` / `_dao_81.txt` / `VERSION`) |
| L10 | 版本 pkg 与 hot VERSION 一致 |

用户可于命令面板 `Windsurf Assistant: 全链路十层自检 (E2E)` 一键触发 · 10 秒出报告.

### 本源之理

**无为而无不为**: activate 时自愈 patch + spawn 时自探 proxy + `源.js` 内建 tunnel · 一切皆在背景默发 · 用户无感. 按一个 E2E 命令即见全貌.

**无感而万感**: proxy tunnel 不改体验 (只改路由) · selftest 证 SP 置换真伪 · wmic 证 LS 参数真态 · 十层皆可验证. 用户不用问"通不通", 按即见真.

## v17.32.0 · 为道再损 · 消 179 回弹真根

### 真根溯源 (v17.31 后四态控制变量实测)

179 v17.31 部署后实测, 发现 `origin_state=off + proxy 仍活` 之撕裂态, 并 chat 仍回弹. 深究四态矩阵 × LS 命令行 × proxy 存活三轴联动, 真根终显:

1. **v17.30 `dist/extension.js` 硬编 LS `--inference=:8890/i`** (本是为让 mgmt/infer origin 不同, 绕 codeium LS binary origin 比对 bug)
2. **`setOrigin("passthrough")` 与 `setCombo('pure')` 皆调 `OriginCtl.deactivate()` 杀 proxy** (v17.22 之"真正撤锚 + 杀 proxy · 零中间层" 有为之法)
3. 两轴相遇: 用户按"官方Agent" → proxy 死 → LS 命令行仍硬编 `:8890/i` → chat 打向**死端口** → **回弹** (LS `get client()` 抛 `Language server has not been started` 实为下游失败之上症)
4. **`ensure` 分支 1**: `proxy 未活 + passthrough · 停留 off 零操作` 之 v17.25 遗设, 在 v17.30 patch 后变成**破坏性路径** (off 态下 LS 打 :8890 必死)

### 损 (为道再损 · 无为而无不为)

**去**: 三处"官方Agent = 杀 proxy"之有为之法 + ensure 分支 1 之"停留 off"

**改**:

| 位置 | 旧 | 新 |
|------|----|----|
| `@extension.js:6480-6488` setOrigin("passthrough") | `OriginCtl.deactivate()` 杀 proxy | `OriginCtl.ensure("passthrough")` proxy 永在位 |
| `@extension.js:6542-6550` setCombo('pure') | `deactivate()` | `ensure("passthrough")` |
| `@extension.js:8303` wam.originPassthrough | `deactivate()` | `ensure("passthrough")` |
| `@extension.js:9172-9185` ensure 分支 1 | `proxy 未活 + passthrough → 停留 off · 零操作` | **去** · 直接走冷路径 activate (spawn + anchor 三层 · SP_MODE=passthrough 纯透传) |

### 本源之理 (源.js:768 所证)

```js
if (kind === "PASSTHROUGH" || SP_MODE === "passthrough") {
  proxyToCloud(req, res, undefined, rid);
  return;
}
```

SP_MODE=passthrough 时, proxy **纯透传字节**, 不改 body, 不注 SP. 体验 = 官方直连. 但 proxy 仍监 :8889 + :8890, LS 命令行硬编 :8890 永有人接. **proxy 存在 ≠ proxy 劫持**; 劫持由 `SP_MODE` 决定, 非由 proxy 是否存在决定. 此即"无为而无不为"之本意.

### 四态矩阵 (v17.32 已完备)

| mode | origin | 路径 | proxy | SP_MODE | chat 通 | 体验 |
|------|--------|------|-------|---------|---------|------|
| wam | invert | 道法自然 一键 | 活 | invert | ✓ | WAM 切号 + 道德经 SP 注入 |
| wam | passthrough | WAM + 官方Agent | 活 | passthrough | ✓ | WAM 切号 + 原生 SP 透传 |
| official | invert | 官方登录 + 道Agent | 活 | invert | ✓ | 用户账号 + 道德经 SP 注入 |
| official | passthrough | 纯官方 一键 | 活 | passthrough | ✓ | 用户账号 + 原生 SP 透传 |

**皆活 · 皆通 · 无回弹**. 4 态之差唯在 SP_MODE 一字.

### 保留 `OriginCtl.deactivate`

仅供 extension host `deactivate()` (VSCode 卸载/重装/关窗时) 调用, 不再暴露于 UI. 用户按钮永不触杀 proxy.

## v17.31.0 · 隔离体系显露 · 四态矩阵 + 一键组合

### 真根承 v17.30 (179 回弹之深究)

v17.30 已闭全链 (proxy 多端口 + LS 两 URL origin 不同 + codeium dist patch), 但 179 用户仍报"回弹". 取 179 当下全息发现:

1. **`exthost.log` 直揭**: `[error] Error: Language server has not been started!` @ `codeium.windsurf` extension 之 `get client()` · LS 尚未 spawn 前被调用 · **真回弹源之一**
2. **扩展激活时序 race**: `10:13:40 codeium.windsurf activate` → `10:13:40.746 exthost exit` → `10:13:51 wam activate (新 host)` → `10:13:54 [error] LS not started` · Windsurf 内部之 extension host race
3. **proxy.log 实际**: LS 启后 mgmt 流量 (Ping/RecordEvent/GetUserJwt) 皆 200 · 但 **0 条 inference/chat 流量** (用户试发消息 · 可能在 LS race 时 abort · 或 chat 根本未触到 proxy)
4. **隔离 UI 漏洞**: 用户难直观看清当前所处组合态 · "官方登录" 按钮只停 WAM · Agent 层若 `invert` 仍劫流量 · "纯官方"体验需两步操作
5. **`http.proxy=127.0.0.1:7890`**: 用户系统级 VS Code 代理 (v2rayN/Clash) · 对 LS native binary 无影响 · 但 webview/mgmt 吃此

### 损 (为道日损 · 守两轴正交 · 加原子组合)

**不做**:
- 不改 `setMode` / `setOrigin` 各自的正交行为 (守用户独立意愿)
- 不触 codeium 内部 LS race (非 wam 责任域)

**做**:

| 位置 | 改动 |
|------|------|
| `@package.json:5` | `version: "17.31.0"` |
| `@extension.js:400` | `WAM_VERSION = "17.31.0"` |
| `@extension.js:6511-6559` | 新 `setCombo` handler · `dao` = `setMode(wam) + ensure(invert)` · `pure` = `setMode(official) + cleanup + deactivate` |
| `@extension.js:6945-6975` | `mode-bar` 清晰分"账号/Agent"两层 + 新增 `combo-bar` 显当前组合态 (道法自然/纯官方/混合) |
| `@extension.js:6901-6912` | 新 CSS: `.combo-bar` `.combo-btn.dao` `.combo-btn.pure` `.combo-now.mix` |
| `@extension.js:7022` | `setCombo(kind)` JS helper |

### 用户体验

**UI 层**:
```
账号: [⚡ WAM切号] [🔑 官方登录]  ‖  Agent: [☯ 道Agent] [○ 官方Agent]  [注入 :8889]
一键: [☯ 道法自然] [🕊️ 纯官方]                  当前: 道法自然 ☯
```

按"官方登录" 只停 WAM 层 · 按"官方Agent" 只撤锚杀 proxy · 两按钮**正交** · 互不干扰.

按"道法自然" 原子切到 (WAM切号 + 道Agent) · 按"纯官方" 原子切到 (官方登录 + 官方Agent + 撤锚). 一步到位.

### 控制变量实验 (179 验收)

用户可按如下 4 态逐一测, 找"回弹"真根之控制变量:

| 组合 | 按钮路径 | 期望 chat 行为 | 观测 |
|------|---------|---------------|------|
| WAM + 道Agent | 一键"道法自然" | 道德经 SP 注入 · chat 走 proxy | proxy.log 现 `/i/` + `CHAT_PROTO` |
| WAM + 官方Agent | WAM切号 → 官方Agent | 官方 SP · chat 直连云 | LS 云端 TCP 增 · proxy.log 仅 mgmt |
| 官方 + 道Agent | 官方登录 → 道Agent | 仅原生账号, 道德经注入 | proxy.log 现 `/i/` · 无 WAM 流量 |
| 官方 + 官方Agent | 一键"纯官方" | 纯原版 Windsurf | proxy.log 几乎空 (WAM 引擎停) |

若某态下 chat 能发, 其他态回弹 → 差异即真根.

## v17.29.0 · 为道再损 · `anchor.py` 循环剥除灾难之终结

### 真根定位 (179 场景 · v17.28 上线后仍 "不可用")

v17.28 解 "kill 全段" 爆 exthost 之谬, 但 179 笔记本 chat 仍不可用. 深究:

1. **`LS pid=33596` TCP 证据**: `[192.168.31.179]:52264 → [35.223.238.178]:443` (googleusercontent.com · inference.codeium.com 真身) — **LS chat 直连云端 · 绕 proxy!**
2. **settings.json 真实状**: `codeium.inferenceApiServerUrl = ""` (空串!) — **被人为剥除?!**
3. **wam.log 实证**: 多次 `restore-inf: anchor.py restore-inference rc=1: Traceback` + `deactivate · restored + stopped` 循环
4. **真因揭**: `anchor.py` 第 398 行:
   ```python
   datetime.datetime.now(datetime.UTC)  # AttributeError
   # from datetime import datetime 后 datetime 已是 class
   # 无 datetime 属性; 无 UTC 属性
   ```

### 死穴之执行顺序

`op_restore_inference` 逻辑:
1. ✓ 读备份 JSON
2. ✓ **从 settings.json 移除 key `codeium.inferenceApiServerUrl`**
3. ✓ **保存 settings.json** (key 已被永久剥!)
4. ✗ 归档备份 (rename) → **抛 AttributeError**
5. function 崩溃, **backup 文件未归档 → 下次 restore 再 strip 一遍**

每次 `deactivate()` 触发一次剥除循环. 用户因"不可用"反复点"关闭",10+ 次 deactivate → settings.json 的 codeium.* 键被彻底洗白 → LS 启动时读 undefined, 用 Windsurf 硬编码默认 `http://127.0.0.1:8889` (无 `/i`) → LS 判 URL 不完整 → fallback 直连 `inference.codeium.com`.

### 损 (为道日损)

```diff
 def op_restore_inference():
     ...
-    s.pop(INFERENCE_KEY, None) or s[INFERENCE_KEY] = orig
-    _save_settings(s)                                   # 先改 settings
-    SETTINGS_BACKUP.rename(
-        f"_settings_backup_restored_{datetime.datetime.now(datetime.UTC)...}"  # 错·炸
-    )
+    # 先归档备份 (与 op_restore_globalstate 一致的正确写法)
+    SETTINGS_BACKUP.rename(
+        SETTINGS_BACKUP.stem + "_restored_" + datetime.now().strftime(...)
+    )
+    s.pop(INFERENCE_KEY, None) or s[INFERENCE_KEY] = orig
+    _save_settings(s)                                   # 备份归档后再改 settings
```

### 双重防御

1. **归档在前**: 若 rename 失败 (极端情况), settings 不会被剥 (exception 前未 save)
2. **归档成功后**: backup 已改名, 下次 restore "无备份跳过" · 循环自断

### 改动

| 位置 | 改动 |
|------|------|
| `@package.json:5` | `version: "17.29.0"` |
| `@extension.js:400` | `WAM_VERSION = "17.29.0"` |
| `@bundled-origin/anchor.py:383-406` | `op_restore_inference` 归档顺序调整 + datetime 修正 |
| `@bundled-origin/VERSION` | 版本号对齐 |

## v17.28.0 · 为道再损 · 精准杀 orphan · 弃端口全段爆破

v17.27 验收于 179 时揭第二真根: `init()` 之 `_killRange` 循环 111 次 `spawnSync powershell.exe`, 累计 30+ 秒, 阻塞 extension host 事件循环, VSCode 判"extension host 无响应"而杀之. wam.log 自 "init: pid 不符 ... kill 全段" 后寂灭, 活 proxy 变 detached child 被 reparent 至 SSH powershell, 呈假活之象.

### 损

单句替代: `for (p=8889;p<=8999;p++) _origKillByPort(p)` → `if(st.port)_origKillByPort(st.port); if(st.pid)_origKillPid(st.pid)`.

### 得

- **1 次 spawn 取代 111 次**: <100ms 取代 30+ 秒 · 不再爆 exthost
- **原则归真**: 只杀已辨之真 orphan (port+pid from ping body) · 不扫不猜
- **他端口野 proxy 容**: 若某实例在 :8900 · 与本无冲 · 不干预 (柔弱处下)

### 改动

| 位置 | 改动 |
|------|------|
| `@extension.js:400` | `WAM_VERSION = "17.28.0"` |
| `@extension.js:8979-9030` | `_killRange` → `_killOrphan` · port+pid 精准杀 |

## v17.27.0 · 为道日损 · 反者道之动 · 四损四得

为学日益, 为道日损. 损之又损, 以至于无为. 无为而无不为.

本版损去三处"盲信"谬设, 损去一处外部依赖. 从根本解决 179 笔记本"发消息回弹"真根.

### 真根定位 (179 场景)

1. 部署脚本 pre-install `restore-all-force` 清三层锚 → 三层空
2. v17.24 extension host 仍跑 → orphan proxy 仍在 :8889
3. 安装 v17.25 VSIX (仅落盘 · 不触 host)
4. 用户 Reload → v17.25 `init()` 载入 state={mode:off}, `_originPort=0`
5. `status()` 用 `_originPort || 8889` → 击中 orphan → 返 `{alive:true, mode:"invert"}`
6. `auto-ensure("invert")` → **ensure Branch 2** (alive + mode 同) → **立即返 · 不调 anchor** → 三层仍空
7. Windsurf Cascade 请求 → 默认走 cloud → **回弹**

附: wam.log `proxy alive on :0` 之古怪日志亦属此 bug 之副征 (status 不副作用更新 `_originPort`).

### 四损四得

**损 1 · 得 1 · orphan 盲信**:
  - 损: `init()` 对 `state=off` 而 `status=alive` 之矛盾现象盲从
  - 得: 强辨 orphan (state=off 却 alive · 或 state.pid ≠ alive.pid) · kill 全端口段 · reset off · 让后续走冷路径正常启 + 锚

**损 2 · 得 2 · "proxy 活即锚齐"谬设**:
  - 损: `ensure()` 热路径假设"alive 则锚齐" · Branch 2/3 跳过 `_origAnchorAll`
  - 得: 热路径 invert 目标必调 `_origAnchorAll` (幂等 · anchor.py op_anchor 已锚则直返) · 防外置清锚后回弹

**损 3 · 得 3 · 外部 Node 依赖**:
  - 损: `_origFindNode` 复杂扫描链 (Windsurf resDir / ../node.exe / PATH)
  - 得: 直用 `process.execPath` + `ELECTRON_RUN_AS_NODE=1` · Electron runtime 即 Node runtime · 一切 VSCode 即一切 Node · 适一切电脑一切用户零安装

**损 4 · 得 4 · 日志真相不一**:
  - 损: `status()` 无副作用洁癖 · 导致 `_originPort=0` 却显示 alive
  - 得: `init()` 真活分支同步 `_originPort = st.port` · 消"proxy alive on :0"古怪日志

### 改动摘要

| 位置 | 改动 |
|------|------|
| `@extension.js:400` | `WAM_VERSION = "17.26.0"` |
| `@extension.js:8666-8687` | `_origFindNode` 改用 `process.execPath` |
| `@extension.js:8810-8826` | spawn env 加 `ELECTRON_RUN_AS_NODE: "1"` |
| `@extension.js:8979-9030` | `OriginCtl.init` 强辨 orphan (state vs alive 矛盾即 kill) |
| `@extension.js:9077-9143` | `OriginCtl.ensure` 热路径亦强验三层锚 (invert) |

### 验收 (`@extension.js:wam.log`)

```
init: orphan proxy :8889 pid=XXXXX (state=off) → kill 全段   # 若前版本 orphan
boot sweep: restore-all-force · done (proxy dead)            # 锚清
boot auto-ensure: invert · 道法自然 · 用户无感                 # 启 invert
proxy up · pid=YYYYY port=8889 node=E:\Windsurf\Windsurf.exe # node= Electron 自身 (证损 4)
activate mode=invert port=8889 anchored=3/3                  # 三层锚齐
```

## v17.25.0 · 二相归一 · 道法自然 · 默认道Agent · 大音希声

### 用户态 (大道至简)

- **二相归一**: 用户视角**只存二态**: **道Agent** (invert) ↔ **官方Agent** (passthrough) · `off` 概念从用户层消失
- **默认道Agent**: 插件首装 + Reload 后**自动启道Agent**, 无需用户按 `Ctrl+Shift+P → 道Agent: 启`
- **尊重用户**: 用户首次主动选"官方Agent"后, 意愿持久化到 `origin_state.json.intent`, 后续启动**不再自启道Agent**
- **命令面板**: `道Agent: 关闭` 命令**移除** · 仅保留 `切道Agent` / `切官方Agent` 二命令

### 引入字段

| | | |
|---|---|---|
| `_userIntent` | `"invert" \| "passthrough" \| null` | 用户意愿 (持久) · 与运行时 `_origin` 正交 |
| `origin_state.json.intent` | 磁盘持久 | `_userIntent` 落盘 |
| `wam.origin.defaultMode` | `"invert" \| "passthrough"` | 首装默认 (默认 `"invert"`) · 可在 settings.json 改 |

### Boot 链硬化

- **init 异常不阻断后续流程**: `try/catch` + `_origin = "off"` fallback
- **Boot sweep 基于 proxy 真活性**: `await OriginCtl.status()` 断是否 `!alive` 才 sweep (不依赖内存字段)
- **Boot auto-ensure(invert)**: 条件 = `defaultMode === "invert"` && `_userIntent !== "passthrough"` && `_origin !== "invert"` && `dir 可寻`

### UI 改

- `origin-hint` 从 `"proxy 未启"` / `:{port}` 改为:
  - `invert` → `道Agent 注入 :{port}`
  - `passthrough` → `官方Agent 直通 :{port}`
  - `off` (瞬态) → `启动中…`

### 逆推报告

本版源于一次"反者道之动 · 逆流至根"的审视. 发现多个真根: 验证脚本盲视 secret 层 (`_deploy_179_v1724.ps1` 76-84), 孤儿 proxy (detached + unref), boot sweep 条件脆弱 (依赖 `_origin === "off"`), 实证 globalState 残锚 `http://127.0.0.1:8889/i` 导致 Cascade 弹回. 本版修核心逆向所得.

## v17.24.0 · 唯变所适 · 全量软编码 · 道法自然

### 底层重构 (一切硬编码 → 软编码)

- **Origin 端口**: `ORIGIN_DEFAULT_PORT=8889` / `ORIGIN_PORT_MAX=8999` → `_cfg("origin.defaultPort")` / `_cfg("origin.portMax")` · settings.json 可覆盖
- **Origin 绑定地址**: `127.0.0.1` → `_cfg("origin.bindHost")` · 完全可配
- **Origin 超时**: fetch/anchor/spawn 三套超时全 `_cfg` getter 化 · ops 可应急调参
- **Origin 上游域名**: `server.self-serve.windsurf.com` / `inference.codeium.com` → `_cfg("origin.upstreamMgmt")` / `_cfg("origin.upstreamInfer")` · 万一上游迁域名零改代码
- **源.js**: PORT / BIND_HOST / UPSTREAM_MGMT / UPSTREAM_INFER / CLOUD_PORT 全 env 可覆盖
- **锚.py / anchor.py**: DEFAULT_ANCHOR / DEFAULT_INFERENCE_ANCHOR / CLOUD_ORIGIN 全 env 可覆盖
- **spawn env 传递**: extension.js spawn 源.js 时注入 ORIGIN_BIND_HOST / ORIGIN_UPSTREAM_MGMT / ORIGIN_UPSTREAM_INFER

### 跨平台适配

- **`_origKillByPort`**: Windows→powershell, Linux/macOS→fuser/lsof 三级 fallback · 不再 Windows-only
- **`_origFindDir` 盘符发现**: 硬编码 `[E:,D:,C:,F:]` → `DriveInfo.GetDrives()` 动态获取 (Windows) / `["/"]` (Unix)

### package.json 新增配置项

| 项 | 默认值 | 说明 |
|---|---|---|
| `wam.origin.defaultPort` | 8889 | 起始端口 |
| `wam.origin.portMax` | 8999 | 端口上界 |
| `wam.origin.bindHost` | 127.0.0.1 | 绑定地址 |
| `wam.origin.spawnReadyRetries` | 15 | spawn 就绪轮次 |
| `wam.origin.anchorTimeout` | 15000 | 锚.py 超时 ms |
| `wam.origin.fetchTimeout` | 2000 | 控制面超时 ms |
| `wam.origin.upstreamMgmt` | server.self-serve.windsurf.com | 管理上游 |
| `wam.origin.upstreamInfer` | inference.codeium.com | 推理上游 |

## v17.23.0 · anchor.py ASCII 名防编码断裂

## v17.22.0 · 根本归一 · 逆流寻本源

### 救火 (Cascade 回弹根治)

- **根因**: "官方Agent" 按钮旧语义是 `OriginCtl.ensure("passthrough")` — 只切 proxy 模式, **不撤锚**. 用户以为回到原生, 但 secret/settings.json/globalState 三层本地锚 (`http://127.0.0.1:8889`) 仍在, Cascade 流量仍经 proxy → 上游 404 → 消息回弹
- **根治**: "官方Agent" 现调 `OriginCtl.deactivate()` — 三层锚尽撤 + 杀 proxy · 原生直通云端 · 零中间层

### 结构修 (永杜残锚)

- **`锚.py` 新增 `restore-all-force`**: 无备份亦能无条件扫三层 (secret / settings.json / globalState) 内一切 `127.0.0.1` / `localhost` 残锚. 幂等 · 安全 · 任何时刻可调用
- **extension.js 启动即扫**: `activate()` 内 `OriginCtl.init()` 后若见 proxy off, 异步调 `restore-all-force` — 用户崩溃/手动卸载留下的残锚永不再累积
- **`_origRestoreAll` + `deactivateSync` 亦加入兜底**: 任何撤锚操作末尾都再跑一次 `restore-all-force`, 三层尽净

### 可视 (本源日志加 X 光)

- **`源.js` 请求入口日志**: `#{rid} IN {METHOD} {URL} kind={CHAT_PROTO|CHAT_RAW|PASSTHROUGH} mode={invert|passthrough}` — Cascade 真实端点一目了然
- **上游响应日志**: `#{rid} UP {host} {METHOD} {path} → {status} ct={...} ce={...} http/{ver} {ms}ms` — "回弹"之由可追到字节
- **HTTP Trailer 转发**: gRPC/Connect-RPC `grpc-status` 等 trailer 完整透传, 不再吞
- **改写失败兜底**: `modifySPProto` / `modifyRawSP` 异常 · 结果空帧 · 结果 3x 以上膨胀 — 皆 fallback 透传原 body (宁可道不注, 不可字节烂)

### 对照表 (v17.21 → v17.22)

| 项 | v17.21 | v17.22 |
|---|---|---|
| 官方Agent 按钮 | `ensure("passthrough")` · 仅切 proxy 模式 · **锚仍在** | `deactivate()` · **撤三层锚 + 杀 proxy** · 真·原生直通 |
| 启动自净 | 无 | `boot sweep: restore-all-force · done` · 任何残锚一键去 |
| 命令 `restore-all-force` | 无 | 新增 · 幂等 · 无需备份 |
| proxy 请求日志 | `[SP-PLAIN] msg[0] field=N before=xB` 单一 | `IN {METHOD} {URL} kind= mode=` + `UP {host} ... → {status} ct= ce= http/` 完整 |
| 改写失败处理 | 抛 500 / 回 JSON err | fallback passthrough 原 body |
| HTTP trailer | 不转发 | 转发 `grpc-status` 等 |

---

## v17.21.0 · 二核合一 · 道法自然

### 道Agent (为核)

- **四键一行 UI**: `⚡ WAM切号 | 🔑 官方登录 | ☯ 道Agent | ○ 官方Agent` — 账号轴 `|` Agent 轴
- **热切 1-3ms**: `OriginCtl.ensure(mode)` 分冷热路径 · 运行态切模式纯 HTTP POST · 进程复用 · 无 Reload Window
- **16 侧信道标记**: rules / skills / workflows / memories / memory_system / MEMORY[ / ide_metadata / communication_style / tool_calling / making_code_changes / running_commands / user_rules / user_information / workspace_information / Bug fixing discipline / Long-horizon workflow / Planning cadence — 任一命中整 SP 置换
- **三路径 invertSP**: plain utf-8 · nested chat_message · raw_sp field 3 — 皆归于道德经
- **自证**: `GET /origin/selftest` 返 `all_paths_pass` + `leaked_markers[]` + `leaked_count` 三路径摘要

### 切号 (为器)

- 项目更名 `windsurf-login-helper` → `windsurf-assistant`, VSIX 同步
- 扁平化: `wam-bundle/*` → 根
- `bundled-origin/` 进 VSIX (源.js + 锚.py + 道德经 + VERSION) · 首次 ☯ 道Agent 自解压到 `~/.wam-hot/origin/`

### 持久无感

- 过往所有 `WAM:` 命令名皆 `切号:` / `道Agent:` / `Windsurf Assistant:` 三分
- 老用户 command ID 不变 (`wam.*` 保留), 仅 UI 文案演化

---

历史变更见 [git tags](https://github.com/zhouyoukang/windsurf-assistant/tags) 与 [Releases](https://github.com/zhouyoukang/windsurf-assistant/releases).

---

*功成事遂, 百姓皆谓我自然.*
