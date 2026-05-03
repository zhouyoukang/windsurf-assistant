# 道Agent · 万法归宗 (dao-proxy-min) · v4.0

> **道法自然 · 无为而无不为.** —— 帛书《老子》
>
> **为学者日益, 闻道者日损. 损之又损, 以至于无为.** —— 帛书《老子》德经
>
> **兵无常势, 水无常形, 能因敌变化而取胜者, 谓之神.** —《孙子兵法 · 虚实》

## 一句话

反代 Windsurf Cascade 之 Connect-RPC，替 SP 为 **TAO_HEADER + 德道经**，深度递归剥离 **27 种侧信道** XML 标签，三档 RPC 全覆盖。per-user 端口自然隔离，二态零代价热切，SSE 实时推送，一键净卸归本源。

## v4.0 万法归宗 (vs v3.0)

| v3.0 | v4.0 万法归宗 |
|---|---|
| 3 命令 | **7 命令** (含 dao.toggleMode / dao.purge 净卸) |
| 固定端口 8889 | **per-user FNV-1a hash** (8889..8988 · 多账号自然隔离) |
| 模式切换需重载 | **二态零代价热切** (proxy 常驻 · 翻转 mode 即可) |
| 无实时推送 | **SSE** `/origin/stream` 推式通知 · webview 自动刷新 |
| 无侧边栏 | **本源观照 webview** (活动栏 → 道Agent · 实时 SP 面板) |
| 无编辑注入 | **自定义 SP 编辑器** (webview 内直改 · Ctrl+Enter 注入) |
| 仅 Windows | **跨平台 LS 重启** (Windows/macOS/Linux) |
| 无净卸 | **了事拂衣去** 一键净卸 (停反代 · 清设置 · 卸插件 · 归本源) |
| SP 观照仅 HTTP | 观照/原发切换 · 年龄计时 · 诊断 dot 指示灯 |
| 硬编码路径 | **全软编码** · 零硬编码用户名/路径 · 适应一切用户 |

## 架构

```text
http.createServer @ 127.0.0.1:{per-user-port}
  │
  ├─ /origin/*                → 控制面
  │    ├─ ping / mode / sig   → 状态 · 模式查改 · 变更签名
  │    ├─ preview / last      → SP 实时观照 · 最近注入
  │    ├─ selftest            → 4 路径闭环自检
  │    ├─ stream              → SSE 推式 (sp/mode/hb 事件)
  │    ├─ custom_sp           → 自定义 SP CRUD
  │    ├─ realprompt          → 捕获轨实提示词
  │    └─ paths               → 路径直方图
  │
  └─ /exa.*                   → 反代上游
       ├─ CHAT_PROTO  (GetChatMessage{,V2})  → SP 替换 + 深度净化
       ├─ CHAT_RAW    (RawGetChatMessage)    → field[3] SP 替换 + 深度净化
       ├─ INFER_STRIP (其他 inference RPC)   → 仅深度净化
       └─ PASSTHROUGH (非 inference)         → 零改写
```

## SP 替换 + 深度侧信道剥离

```text
1. invertSP(): 识别官方 SP (isLikelyOfficialSP) → 整段替为 TAO_HEADER + 德道经
2. deepStripSideChannels(): 递归下钻 proto 每个字段
   → 27 种 XML-like 侧信道标签 (<user_rules>/<MEMORY[...]>/<communication_style>/...)
   → MEMORY[name] 块特殊匹配
   → discipline 行剥除
   → 多 pass 确保嵌套干净
3. 输出: LLM 实收 = 德道经 + 用户消息 + 工具 schema · 官方指令全净
```

## 4 路径闭环自检

```text
GET /origin/selftest → all_paths_pass: true
  ├─ plain_utf8:          道=✓ · 泄漏=0
  ├─ nested_chat_message: 道=✓ · 泄漏=0
  ├─ raw_sp:              道=✓ · 泄漏=0
  └─ deep_strip_user_msg: 泄漏=0 · 保留真实用户问题=✓
```

## 装

```powershell
# 构建 vsix
.\_build_vsix.ps1

# 打包前 L1 自检
.\_build_vsix.ps1 -RunL1

# 打包 + L1 + L2 合成 (须反代在跑)
.\_build_vsix.ps1 -RunL1 -RunL2Syn

# 打包 + 装本机 Windsurf
.\_build_vsix.ps1 -InstallLocal

# 自定义端口
.\_build_vsix.ps1 -RunL2Syn -Port 8900
```

## 7 命令 (`Ctrl+Shift+P`)

| 命令 | 道义 |
|---|---|
| **道Agent: 启** (invert) | 反者道之动 · 启代理 + 锚 settings + LS 重启 |
| **官方Agent: 启** (passthrough) | 上善如水 · 透传观照 · SP 不改 |
| **道Agent: 切换模式** (道 ⇄ 官方) | 二态热切 · 零代价翻转 · 下次对话生效 |
| **道Agent: 浏览器观真 SP** | 打开 `/origin/preview` · 全貌解剖 |
| **全链路自检** (E2E) | 致虚守静 · L1+L2 报告 |
| **闭环自检** (L1+L2) | 同上 |
| **了事拂衣去** · 净卸 | 停反代 · 清设置 · 卸插件 · 归本源 |

## 控制面端点

端口默认 per-user 自动哈希 (8889..8988)，可通过 `dao.origin.port` 覆盖。

```http
GET  /origin/ping           # 状态 (mode/uptime/req_total/dao_chars)
GET  /origin/mode           # 当前模式
POST /origin/mode           # 切模式 {"mode":"invert"|"passthrough"}
GET  /origin/sig            # 变更签名 (轻量 · webview 用)
GET  /origin/preview        # 实时全貌 (before+after+结构解剖)
GET  /origin/last           # 最近一次 SP 注入 (?full=1 全文)
GET  /origin/lastinject     # 同 /last (兼容旧版)
GET  /origin/realprompt     # 捕获轨实 SP (?full=1)
GET  /origin/selftest       # 4 路径闭环自检
GET  /origin/paths          # 路径直方图 (?n=10)
GET  /origin/stream         # SSE 推式 (?replay=1)
GET  /origin/custom_sp      # 读自定义 SP
POST /origin/custom_sp      # 写自定义 SP
DELETE /origin/custom_sp    # 清自定义 SP
```

## 配置

| key | 默认 | 说明 |
|---|---|---|
| `dao.origin.port` | `0` (自动) | 反代端口 · 0=per-user FNV-1a hash (8889..8988) · 非0覆盖 |
| `dao.origin.defaultMode` | `passthrough` | 首激默模 · `invert`/`passthrough` |
| `dao.origin.banner` | `true` | 启动时显德道经横幅 |

运行时自动锚定 (无需手动设):

| key | 说明 |
|---|---|
| `codeium.apiServerUrl` | 道Agent 启时设 `http://127.0.0.1:{port}` · 净卸时清 |
| `codeium.inferenceApiServerUrl` | 同上 |

## 文件

```text
dao-proxy-min/
├─ extension.js                              # ~1580 行 · VSCode 壳 + 锚定 + webview
├─ package.json                              # 7 命令 + 3 配置项
├─ vendor/bundled-origin/
│  ├─ source.js (源.js)                      # ~1500 行 · 本源反代核 · 字段级 proto
│  └─ _dao_81.txt                            # 德道经八十章 (6776 字 · 19716B)
├─ tests/
│  ├─ L1_unit.js                             # 合成 proto 单元 (离线 · 毫秒)
│  ├─ L2_synthetic.js                        # 合成帧 → 反代闭环 (在线)
│  ├─ L2_replay.js                           # 代理 → 真云端
│  └─ L3_live.md                             # 真 Windsurf 活检指引
├─ _build_vsix.ps1                           # 构建脚本 · -RunL1 -RunL2Syn -Port
├─ media/icon.png
├─ README.md
├─ LICENSE
└─ .vscodeignore
```

## per-user 端口隔离

多账号同机时，每用户自动分配唯一端口 (FNV-1a hash of username → 8889..8988)。
无需配置，无需协调，自然隔离。可通过 `dao.origin.port` 显式覆盖。

```text
fnv1a("zhou")          → 8923   (示例)
fnv1a("administrator") → 8947   (示例)
fnv1a("alice")         → 8901   (示例)
```

## 道义

> 卅辐同一毂, 当其无有, 车之用也. —— 帛书《老子》道经
>
> 反也者, 道之动也; 弱也者, 道之用也. —— 帛书《老子》德经
>
> 大成若缺, 其用不敝; 大盈若盅, 其用不窘. —— 帛书《老子》德经

v4.0 万法归宗:

- **字段级 proto** 解析/序列化 · 不再脆弱字节扫描
- **27 种侧信道** 深度递归剥离 · LLM 不再收官方暗指令
- **TAO_HEADER** 身份锚 · 借 "You are Cascade." 格式提升权重
- **三档 RPC** 全覆盖 · 不止 GetChatMessage
- **per-user 端口** · 多账号自然隔离 · 无需配置
- **二态热切** · 道/官零代价翻转 · proxy 常驻
- **SSE 推式** · webview 自动刷新 · 无轮询浪费
- **本源观照** · 实时 SP 面板 · 原发/实收切换 · 自定义注入
- **跨平台** · Windows/macOS/Linux LS 重启
- **了事拂衣去** · 一键净卸归本源
- **全软编码** · 零硬编码 · 唯变所适
- 道法自然 · 无为而无不为
