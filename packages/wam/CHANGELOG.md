# CHANGELOG · packages/wam (rt-flow 道极版)

> 反者道之动 · 弱者道之用 · 天下之物生于有 · 有生于无. —— 帛书《老子》德经

## v2.5.5 (2026-05-04) · ideVersion 根因解 · 当前

**根因发现**: 后端按 `metadata.ideVersion` 能力协商返回字段.

- `ideVersion="1.0.0"` → 后端省略 `planEnd / planStart` (老客户端不懂)
- `ideVersion="1.99.0"` → 后端返完整 `planEnd="2026-05-09T20:56:09Z"`

实证 (`_probe_ideversion.cjs`): 同账号同 API · 仅版本差异 · `planEnd` 字段有无之别.

此为 Trial 类账号 `planEnd=0` 脏数据的真正根因 (比 postAuth 401 更本).

**修**: `tryFetchPlanStatus` metadata default `ideVersion` 由 `"1.0.0"` 改为 `"1.99.0"`.

## v2.5.4 (2026-05-04) · `_isTrialLike` 软判据

**问题**: `_cleanseHealthOnLoad` 硬编码 `h.plan === "Trial"` · 漏 `Team Trial / Free Trial / 小写 trial` 等变体.

**修**: 抽 `_isTrialLike(h)` 软判 (正则 `/trial/i`) · `_buildExpTag / _cleanseHealthOnLoad` 同步用软判据.

## v2.5.3 (2026-05-04) · Trial 脏数据自洁

**问题**: `plan="Trial" && planEnd=0 && checked=true` 的状态 → UI 误显 "永久" (∞).

**修**:

1. `_buildExpTag` 增第 5 态 `Trial?` (黄色 · 提示需重验)
2. `_cleanseHealthOnLoad` 加规则: `Trial && planEnd=0 && checked=true` → `checked=false` (下次自动重验)
3. `store.load` log 加 `trialNoPlanEnd` 计数

## v2.5.2 (2026-05-03) · `_buildExpTag` 5 态 UI 标签

UI 列每行账号有效期 5 态:

- `?天` (灰) — 未验
- `N天` (颜色阶梯: 红 ≤2 / 橙 ≤5 / 绿 >5)
- `已过期` (红)
- `Trial?` (黄) — Trial 脏数据 · 需重验
- `∞` (灰) — Pro 永久或字段缺

## v2.5.1 (2026-05-03) · `X-Devin-Auth1-Token` HTTP header

**问题**: 后端协议变 · postAuth 401 未认证.

**修**: `windsurfPostAuth` body `auth1_token` → HTTP header `X-Devin-Auth1-Token`.

实证 (`_probe_postauth.cjs`): 真账号 + 真后端 · 修前 401 / 修后 200.

## v2.5.0 (2026-05-02) · 大减法 · Layer 6 跨进程触发

**根因**: Layer 1-5 网络钩 (http.request / net.Socket / undici / fetch / WebSocket) 在 cross-process 隔离下无效 — 切号工作进程与 Cascade 渲染进程不共享 hook.

**修**: 引入 Layer 6 — `fs.watchFile()` 监听 `%APPDATA%\Windsurf\User\workspaceStorage\<hash>\state.vscdb` 的 mtime 变化.

每条 Cascade 消息发送会触发 `state.vscdb` 写 → Layer 6 收到 → 触发切号. **跨进程稳**.

**减**: 删 Layer 1-5 全部网络钩代码 (-2300 行).

## v2.4.x → v2.5.0 减法路 (-62%)

| 减项 | 行 | 减因 |
|---|---|---|
| Layer 1-5 网络钩 | -2300 | cross-process 无效 |
| TurnTracker | -800 | Layer 6 已替 |
| AutoUpdate (`_DEFAULT_PUBLIC_SOURCE`) | -600 | 用户自部署 · 公开 repo 无源 |
| 代币池跨账号管理 | -400 | 单文件本地 state 即可 |
| Firebase / Devin 全套登录链 | -2200 | `devinLogin + windsurfPostAuth` 双步即足 |
| 多重 fallback 兜底 | -200 | 信道单点已稳 |
| **共减** | **-6648** | **(10913 → 4265)** |

## 测试矩阵 (本仓 8 测 · 公开 repo 模式 231 过 · 0 败 · 本地真打模式 236 过)

| 测试 | 断言 | 关注 |
|---|---|---|
| `_test_set_health.cjs` | 24 | health 写入幂等 + planEnd 保留 |
| `_test_v241_real.cjs` | 15 (公开) / 20 (真打) | proto3 default + 真 5 号验证 |
| `_test_in_use.cjs` | 57 | 使用中锁 + 失败计数 (不禁号) |
| `_test_e2e_msg_rotate.cjs` | 33 | 消息轮转 E2E |
| `_test_quota.cjs` | 12 | 配额波动检测 |
| `_test_v251_postauth_header.cjs` | 8 | postAuth header 协议 |
| `_test_v252_exptag.cjs` | 73 | UI 5 态 + Trial 清洗 |
| `_test_v255_ideversion.cjs` | 9 | ideVersion 1.99.0 锁 |

## 历史: v17.42.x 系满载版

v17.42.20 (2026-04-末) 及 v17.42.x 全系**满载本体**已归档于 [`_archive/wam-v17.42.20/`](../../_archive/wam-v17.42.20/):

- 完整 `extension.js` 437 KB / 10913 行
- 387 E2E 断言
- 完整 v17 CHANGELOG 72 KB · `_archive/wam-v17.42.20/CHANGELOG.md`

二者为**同名异体 · 各臻其极** · 不相代而相成.

---

*德经曰: 上士闻道 · 堇而行之. 道极版即「闻道而行」之践*
