# Changelog

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
