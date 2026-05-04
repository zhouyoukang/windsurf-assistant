# 010-WAM本源_Origin · v2.5.5 · 道极减法分支

> 太上，下知有之 · 道法自然 · 用户无为 · 插件无不为

WAM `rt-flow` 道极减法分支 · 活体源 · 改一处万法响应

## 〇 · 血缘锚定 (重要)

两条同名异体的代码线 · 并立互不覆盖：

| 线 | 位置 | 版本 | 体积 | 特征 |
|---|---|---|---|---|
| **本源 · 完整版** | [`github.com/zhouyoukang/windsurf-assistant/packages/wam`](https://github.com/zhouyoukang/windsurf-assistant) | v17.42.20 | 437 KB · 10913 行 | 逆向 codeium · auto-update · TurnTracker · 387 E2E 断言 |
| **道极减法版 (本仓)** | `010-WAM本源_Origin/` | **v2.5.5** | **168 KB · 4265 行 (-62%)** | Layer 6 watch · 不禁号 · 236/0 回归测 · `_isTrialLike` 软判 · ideVersion 根因解 |

同 `publisher=devaid` · 同 `name=rt-flow` · 但**核心函数零重叠** (github 有 `TurnTracker/_getAutoUpdateSource` 无 Layer 6/`_buildExpTag`/`tryFetchPlanStatus` · 本仓反之)。

**不妄为不着相** · 两线各安其位 · 本源不动 · 改良版独立演化 · 用户按需装其一。

---

## 一 · 本源需求

```
用户在 Cascade panel 发消息 → WAM 自动切到下一健康号
    ↑
用户无为 (无任何额外操作)
插件无不为 (auto-verify · 评分 · 切号 · 流式避让 · 永不禁号)
```

## 二 · 文件清单 (12 项 · 一物不剩)

```text
extension.js                       168 KB    核心源码 (v2.5.5)
package.json                         6 KB    VSCode manifest
账号库最新.md                         3 KB    活号池 · 运行时读
README.md                            本文件
_test_set_health.cjs                 8 KB    health 评分 (24 测)
_test_v241_real.cjs                  9 KB    v2.4.1 真路径 (20 测)
_test_in_use.cjs                    14 KB    使用中🔒 + 永不禁 (57 测)
_test_e2e_msg_rotate.cjs            11 KB    E2E 消息切号 (33 测)
_test_quota.cjs                      5 KB    proto3 quota (12 测)
_test_v251_postauth_header.cjs       6 KB    postAuth header (8 测)
_test_v252_exptag.cjs               12 KB    expTag 5 态 + Trial (73 测)
_test_v255_ideversion.cjs            2 KB    ideVersion 根因锁 (9 测)
_archive/                                    历史归档 (可回溯)
_github_src/                                 历时源码 (锚定参考)
_releases/                                   历代 VSIX (15 个)
```

## 三 · v2.5 家族演化史 (2026-05-04 一日五变)

| 版本 | 时间 | 核心动作 | 体积 | 测 |
|---|---|---|---|---|
| v2.4.13b | baseline | 5 hook + 3 self-test + 15min ban | 198 KB · 4933 行 | 182/2 pre-fail |
| **v2.5.0** | 16:50 | 大减法 · 删 L1-L5 / self-test · 不禁号 | 162 KB | 143/2 |
| **v2.5.1** | 17:04 | 单行修 · postAuth 加 `X-Devin-Auth1-Token` header | 163 KB | 154/0 |
| **v2.5.2** | 17:16 | expTag 4 态恒显 · `_buildExpTag` 纯函数化 | 164 KB | 185/0 |
| **v2.5.3** | 17:36 | Trial 脏数据清洗 + 第 5 态 "Trial?" | 166 KB | 195/0 |
| **v2.5.4** | 17:50 | 软编码 `_isTrialLike` regex · 兼后端 tier 变体 | 167 KB | 227/0 |
| **v2.5.5** | 18:26 | **真根因解 · ideVersion `1.0.0`→`1.99.0`** | **168 KB** | **236/0** |

**v2.5.5 真根因** (probe 独立实证):

```
ideVersion="1.0.0"  → 后端能力协商 → 省 planEnd → parsePlan daysLeft=0
ideVersion="1.99.0" → 后端返完整结构 → planEnd="2026-05-09" ✓
```

一行修：`tryFetchPlanStatus` 默认 ideVersion 从 "1.0.0" → "1.99.0"

## 四 · 测试矩阵 (236/0)

```bash
node _test_set_health.cjs              # 24 过
node _test_v241_real.cjs               # 20 过
node _test_in_use.cjs                  # 57 过
node _test_e2e_msg_rotate.cjs          # 33 过
node _test_quota.cjs                   # 12 过
node _test_v251_postauth_header.cjs    #  8 过
node _test_v252_exptag.cjs             # 73 过
node _test_v255_ideversion.cjs         #  9 过
node --check extension.js              # exit 0
```

合计 **236 过 · 0 败** · 全 8 个测套件均纯真实回归测 · 无 mock fail。

## 五 · 部署

### 装载点

- **本机**: `C:\Users\Administrator\.windsurf\extensions\devaid.rt-flow-2.1.1\extension.js`
- **远程 179**: `\\192.168.31.179\C\Users\zhouyoukang\.windsurf\extensions\devaid.rt-flow-2.1.1\extension.js`

### 部署流程 (实证)

```powershell
# 1. 备份 → 写文件 → 同步 size 到 package.json + extensions.json
# 2. 不 kill ext host (上善如水 · 不抢路)
# 3. 用户 Ctrl+Shift+P → Developer: Reload Window 即热加载
```

历次部署日志归 `_archive/v2.5_pre_daoist/_deploy_v25*.log` (5 次 · v2.5.0~v2.5.5)。

## 六 · 用户唯一操作

```
Ctrl+Shift+P → Developer: Reload Window
```

Reload 后流程 (全自动):

```text
1. v2.5.5 activate → Store.load() → _cleanseHealthOnLoad
   洗 Trial-planEnd=0 脏数据 → checked=false → UI 显 "?天"
2. uncheckedPct 高 → auto-verify(stale) 加速 10s 启
3. verifyAll 跑 · 逐号 devinLogin → postAuth → registerUser → GetUserStatus
4. ★ ideVersion="1.99.0" → 后端返完整 planEnd ★
5. parsePlan 解 daysLeft · setHealth 写 state.json
6. UI 陆续从 "?天" → "11天" 绿 / "4天" 橙 / "2天" 红 / "已过期" 红
7. 切号自动继续 · 用户发消息自动切健康号
```

## 七 · 道之精要

- **反者道之动** — v2.5 从 v2.3 加 5 hook 反向到去 hook · 损之又损
- **弱者道之用** — Layer 6 watch state.vscdb · 1500ms poll · 4s debounce · 水之柔
- **上善如水** — 不 kill 进程 · 不抢路 · 等 cascade 流完再切
- **不禁账号** — 失败仅记数 · 号永远可选 · 历史 until 自动清
- **道法自然** — 后端本就返完整数据 · 只因 ideVersion 太老被省 · 一字之修自正
- **太上下知有之** — 仅切号 3s 状态栏高亮 · 否则全无感

## 八 · 历史归档

```text
_archive/
├── v2.5_pre_daoist/                v2.5.0~v2.5.4 演化全档
│   ├── extension_v2413b.js         pre-v2.5 baseline
│   ├── ROOT_CAUSE_v25_DAOIST.md    v2.5.0 时刻分析
│   ├── ROOT_CAUSE_*.md             v2.1~v2.3 历时根因 4 卷
│   ├── _probe_*.cjs                v2.5.5 真根因 probe 5 卷
│   ├── _deploy_v25*.{ps1,log}      5 次部署轨迹
│   ├── DEPRECATED.md / VERSION_INDEX.md
│   └── LINKS.md                    旧 dao-agi vendor 链 (已废)
├── 2026-04-29-cleanup/             4/29 一次性清理
├── 179_probes/                     179 远端探针 (旧)
├── builds/                         历代构建脚本
├── releases_history/               28 中间 VSIX
├── tests/                          历代测试
├── webrev / webrev_2026-04-23/     Windsurf web 反向工程原料
├── v2.4.11_pre-jiantou/            v2.4.11 时刻 pre-tip 分支
└── USER_TEST_GUIDE_v17.60.md       老用户测试指南
```

## 九 · 修改即部署

```powershell
# 1. 编辑 extension.js
# 2. 全测
node _test_set_health.cjs ; node _test_v241_real.cjs ; node _test_in_use.cjs
node _test_e2e_msg_rotate.cjs ; node _test_quota.cjs ; node _test_v251_postauth_header.cjs
node _test_v252_exptag.cjs ; node _test_v255_ideversion.cjs
# 3. 语法
node --check extension.js
# 4. 部署到本机 + 179 (历次部署脚本归 _archive/v2.5_pre_daoist/)
# 5. 用户 Reload Window
```

---

> 致虚极, 守静笃 · 万物并作, 吾以观其复
>
> 道恒无为而无不为 · 反者也, 道之动也 · 弱者也, 道之用也
