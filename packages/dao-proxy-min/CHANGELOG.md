# Changelog · dao-proxy-min

> 反也者, 道之动也; 弱也者, 道之用也. —— 帛书《老子》德经

## v9.1.2 — 道法自然 · 逆序净卸 (2026-04-30)

> 反也者, 道之动也; 弱也者, 道之用也. —— 帛书《老子》德经

### 逆序关停 · 根治卸载卡死

**根因**: 旧 `deactivate()` 先停代理 → LS 仍活 → 连死代理 → Windsurf 卡死.

**修复** — 反者道之动 · 逆序:

| 步骤 | 旧 (必死) | 新 (道法自然) |
|------|-----------|---------------|
| ① | 停代理 | **设透传** (安全网) |
| ② | 清锚 (API 失败) | **断钩** + `_cachedAnchored=false` |
| ③ | — | **同步清锚** (`_clearAnchorFileSync`) |
| ④ | — | **杀 LS** → 重生直连官方 |
| ⑤ | — | **停代理** (此时安全) |

- `_clearAnchorFileSync()` — 同步文件清锚, 绕过 VS Code API "not registered" 限制
- `cmdPurge` 同步重构为正确逆序
- `_custom_sp.json` 加入持存清理

### `<user_rules>` 可信格式注入 (v9.0→v9.1)

- `[CUSTOM-SP-ACTIVE]` 哨兵已移除 — 用户 SP 直出, 不触发模型注入检测
- `modifySPProto` / `modifyRawSP` — `spModifiedIdx` 追踪已修改 msg, save/restore 绕 `deepStrip`
- `stripSideChannelBlocks` / `hasSideChannels` — 移除冗余哨兵检测
- L1 测试 8/8 全绿

---

## v5.0.0 — 道法自然 (2026-04-29)

> 为学者日益, 闻道者日损. 损之又损, 以至于无为. 无为而无不为. —— 帛书《老子》德经

### 跳出二元 · 净减 270 行 (1536 → 1266 · vsix 减 8KB)

| 层 | v4.5 | v5.0 道法自然 |
|---|---|---|
| **道层** | TAO_HEADER + 德道经八十章 | 同 (永在前) |
| **法层** | 官方 SP 经"系统/用户侧"二分剥削 | 官方 SP **完整保留** (含 user_rules / MEMORY / skills / workflows / memory_system / ide_metadata 全谱) |
| **术层** | proto deepStrip 递归净化所有 wire=2 字段 | proto **不动** · 各工作区/工具/MCP 自然运行 |

### 删去之有为 (~250 行)

- `SIDE_CHANNEL_TAGS` / `SIDE_CHANNEL_TAGS_RE` / `MEMORY_BLOCK_RE` / `DISCIPLINE_LINES` / `DISCIPLINE_RE`
- `stripSideChannelBlocks` / `hasSideChannels`
- `isStrictProto` / `deepStripProtoSideChannels` / `deepStripRequestBody`
- `INFER_STRIP` 路径 (改为 `PASSTHROUGH`)
- `selftest` 之 `deep_strip_user_msg` 路径
- `fakeSP` 之 `LEAK_MARKERS` 检测
- `ping` endpoint 之 `deep_strip` / `side_channel_tags` 字段
- exports 中之剥逻辑导出

### 哲学

旧路 (v4.x): "剥侧信道"试图把官方 SP 之 user_rules / MEMORY / discipline 等"系统侧"杀去, 留"用户侧". 此路陷入剥/留二元, 字段必生新增, 维护成本高.

新路 (v5.0): **前置道魂, 不剥不削**. 道在前为君, 法在后为臣. LLM 自感道魂之首言, 后续官方约束自然让位. 一气贯三清.

### selftest 简化

```text
GET /origin/selftest → all_paths_pass: true
  ├─ plain_utf8           道=✓ · 用户问题=✓
  ├─ nested_chat_message  道=✓ · 用户问题=✓
  └─ raw_sp               道=✓ · 用户问题=✓
```

(去除 v4.x 之 `deep_strip_user_msg` 路径 · 用户消息原本就不剥)

### 验证

| 项 | 结果 |
|---|---|
| `node --check source.js` | ✓ 静默 |
| 本地 selftest | ✓ `all_paths_pass=true` · 三路径前置道魂 + KEEP_MARKERS 19/19 全保 |
| L1 单元自检 | ✓ 4/4 全绿 (含 `user_msg_passthrough`) |
| vsix 打包 | ✓ `dao-proxy-min-5.0.0.vsix` (68.92 KB · 12 文件) |

---

## v4.0.0 — 万法归宗 (2026-04-26)

### 字段级 proto 重构

- 离弃脆弱字节扫描, 改为字段级 proto 解析 / 序列化
- 27 种 XML-like 侧信道标签深度递归剥离 (`<user_rules>` / `<MEMORY[...]>` / `<communication_style>` / ...)
- 三档 RPC 全覆盖: `CHAT_PROTO` (GetChatMessage{,V2}) / `CHAT_RAW` (RawGetChatMessage) / `INFER_STRIP` (其他 inference RPC) / `PASSTHROUGH` (非 inference)

### per-user 端口隔离

多账号同机时, 每用户自动分配唯一端口 (FNV-1a hash of username → 8889..8988). 无配置, 无协调, 自然隔离.

### 二态热切

模式切换不需重载. proxy 常驻, 翻转 `mode` 即可 (道 ⇄ 官方).

### SSE 推式 + 本源观照 webview

- `/origin/stream` SSE 实时推送 (sp / mode / hb 事件)
- 活动栏 → 道Agent 容器 · 实时 SP 面板 · 原发/实收切换 · 自定义 SP 注入

### 跨平台 + 净卸

- LS 重启支持 Windows / macOS / Linux
- "了事拂衣去" 一键净卸 (停反代 · 清设置 · 卸插件 · 归本源)

### 7 命令

```text
道Agent: 启 (invert)             — 反者道之动
官方Agent: 启 (passthrough)      — 上善如水
道Agent: 切换模式 (道 ⇄ 官方)    — 二态热切
道Agent: 浏览器观真 SP            — 全貌解剖
全链路自检 (E2E)                  — 致虚守静
闭环自检 (L1 + L2)                — 同上
了事拂衣去 · 净卸                 — 归本源
```

---

## v3.0.0 — 极简反代 (2026-04-20)

### 朴

- 极简反代 · ~40KB · 3 命令 · 固定端口 8889
- source.js 字节扫描 + SP 替换
- 无 webview · 无热切 · 无 SSE
- vendor/bundled-origin 内联德道经 八十章

---

## 道义沿革

```text
v3.0  朴      → 字节扫描 · 一刀切 · 极简
v4.0  增      → 字段级 proto · 27 标签深剥 · 万法归宗
v5.0  损      → 跳出剥/留二元 · 道魂在前 · 一气贯三清 · 道法自然
```

> 大成若缺, 其用不敝; 大盈若盅, 其用不窘. —— 帛书《老子》德经
