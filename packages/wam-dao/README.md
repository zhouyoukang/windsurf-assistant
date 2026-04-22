# 道Agent · 万法归宗 (wam-dao)

> **v17.51 · 反向出发 · 解剖观本源 · 不一叶障泰山**
>
> 道可道,非常道。 名可名,非常名。
> 无,名天地之始; 有,名万物之母。
> 反者道之动, 弱者道之用。

## 一、道境

此包为 **010-WAM本源_Origin** 之本源化身 —— 将原 `020-道VSIX_DaoAgi` 的薄壳 + WAM 本体合并, 构建单一 VSIX, 无需 TypeScript 编译, 直接运行。

| 层次 | 本源位置 | 说明 |
|------|---------|------|
| **extension.js** | 本目录 · 34 KB 手写 | 薄壳 · 引 WAM + 内联 hijack/state-bridge/双按钮 |
| **essence.js** | 本目录 · 25 KB | 本源一览 webview · 九源汇一屏 · 解剖观注 |
| **vendor/wam/extension.js** | 352 KB · 原片不动 | WAM 战斗源 v17.42.2 (`../wam/extension.js` 快照) |
| **vendor/wam/bundled-origin/** | 源.js + 锚.py + 道德经 | 反代三件套 · v17.51 含 `dissectSP` |
| **media/icon.{png,svg}** | 图标 | 活动栏入口 |

## 二、v17 三里程碑 (反者道之动)

### v17.48 · 根路观察层 (二模皆捕)

proxy 在 chat 路径加观察钩: 凡 LLM 收之 SP, 无论 `invert` / `passthrough`, 皆入 `_lastInject`。
对外 `/origin/lastinject` 可取当下注入全文, **官方模亦捕** · 无为而无不为。

### v17.50 · 抱一守中 (跨模恒显)

`_lastInject` 持盘至 `_lastinject.json` (0o600), 跨重启恒存。
`/origin/preview` 万法归一字段 `after` :
- `invert` 模 → `TAO_HEADER + 道德经` (内存合成 · 永恒)
- `passthrough` 模 → `_lastInject.before` (持盘 · 下次请求即刷)

### v17.51 · 解剖观本源 (不一叶障泰山)

新增 `dissectSP(sp)` 将 SP 整串反向解剖为三部:
1. **身份首言** (`identity_head`) · 首 `<tag>` 前散文 · "You are Cascade..."
2. **块序列** (`blocks[]`) · 每 `<tag>...</tag>` 一项, 含 `tag / content_head / content_chars / depth`
   深嵌如 `<MEMORY[dao-de-jing.md]>` 亦识
3. **末尾倾向** (`tail_head`) · 末块后散文 · Bug fixing / Long-horizon / ...

`/origin/preview` 返:

```
{
  after, after_chars, after_dissect,     // 实注 (LLM 所收)
  before, before_chars, before_dissect,  // 原 (Windsurf 意投)
  has_captured_before, captured_at, age_s
}
```

道模亦示官模之原文, 令用户见所舍; 官模示所留。**二观并行 · 万法具通**。

## 三、双按钮热切换 (太上不知有之)

活动栏 → "道Agent · 万法归宗" 容器内顶部:

```
┌────────────────────────────────────┐
│ 道法自然 · 无为而无不为            │
│ [🌊 道Agent] [☁ 官方] [✕]          │
│ 当前: 道Agent 运行中 :8889         │
├────────────────────────────────────┤
│ 本源一览 (essence webview)         │
│ § 实注之文 · LLM 所收              │
│ § 身份首言 / 块序列 / 末尾倾向     │
│ § 原 SP · Windsurf 意投            │
└────────────────────────────────────┘
│ 切号面板 (WAM 原生)                │
└────────────────────────────────────┘
```

- 🌊 **道Agent** → `invert` 模式 · 道德经 SP 注入 · 绝侧信道
- ☁ **官方** → `passthrough` 模式 · 原味透传 · 零改写
- ✕ → 关闭代理 · 还原 apiServerUrl · kill proxy

状态自动刷新 · 端口自动发现 · 模式持久化 · 持盘跨重启恒显。

## 四、自验 (四测皆绿)

| 测 | 境 | 验 |
|---|---|---|
| `_test_dissect.js` | 3 境 24 断言 | `dissectSP` 反向解剖无失真 · 空/异常守中 · 工具块含 run_command |
| `_test_preview_persist.js` | 4 境 36 断言 | `invert` 冷启即具 · `passthrough` 持盘恒存 · 跨模切换守真 · 解剖字数守 |
| `_test_observer.js` | 3 Phase | `invert`→捕 / `passthrough`→捕 / 切模即同步 |
| `_test_essence.js` | 结构验 | `gatherEssence` 唯四键 `{ts, port, ping, preview}` · 万法归一 |

跑法:

```bash
cd wam-dao
node _test_dissect.js
node _test_preview_persist.js
node _test_observer.js
node _test_essence.js
```

## 五、构建与安装

### 本机构建

```cmd
cd E:\道\道生一\一生二\Windsurf万法归宗\070-插件_Plugins\010-WAM本源_Origin\_github_src\packages\wam-dao
.\build.cmd
```

产出:
- `./dao-agi.vsix` — 本目录产物
- `../../../rt-flow-dao-17.51.0.vsix` — 归档到 010 根目录

### 一键部署到 179 笔记本

```pwsh
cd E:\道\道生一\一生二\Windsurf万法归宗\070-插件_Plugins\020-道VSIX_DaoAgi
.\deploy-dao-agi-179.ps1 -VsixPath ..\010-WAM本源_Origin\rt-flow-dao-17.51.0.vsix -Force -Restart
.\e2e-179.ps1
```

`deploy-dao-agi-179.ps1` 已支持 `-VsixPath` 参数 · 零硬编码 · 唯变所适。

## 六、道义归一

- **大制不割**: 不分 020/010 两地,一包通杀, 单一真理源
- **水善利万物而不争**: 不改 WAM 原片(`vendor/wam/extension.js`), 不与其争一字
- **太上不知有之**: 双按钮默认启用, 模式持久化, 跨重启恒显, 用户不需操心
- **利而不害**: `anchor()` 失败不阻塞激活 · WAM 激活失败有明确 fallback
- **为而不争**: `dao.toggle` + `dao.essence` 视图独立存在, 零侵入
- **反者道之动**: 命令 `dao.toggleMode` 在 off → dao → official → off 间轮转
- **抱一守中**: `/origin/preview` 万法归于 `after` 一字段 · 模式之辨不累用户
- **解剖观本源**: 不一叶障泰山 · 身份/块/末三分 · 深嵌 MEMORY 亦识

## 七、自检与命令

```
Ctrl+Shift+P → "全链路自检 (E2E)"
Ctrl+Shift+P → "道Agent: 切换模式 (道/官方)"
Ctrl+Shift+P → "道Agent: 启 (道德经 SP · 绝侧信道)"
Ctrl+Shift+P → "道Agent: 启 (官方原味 · 零改写)"
Ctrl+Shift+P → "道Agent: 本源一览 (观注入)"
Ctrl+Shift+P → "道Agent: 关闭 (restore 锚 · kill proxy)"
```

## 八、HTTP 观察接口 (源.js 暴)

| 路由 | 返 |
|------|---|
| `GET /origin/ping` | `{ok, mode, pid, dao_chars}` |
| `GET /origin/preview` | `{mode, source, after, after_dissect, before, before_dissect, ...}` |
| `GET /origin/lastinject` | `{has_inject, kind, variant, mode, transformed, before, after, ...}` |
| `POST /origin/mode?mode=invert\|passthrough` | 热切模式 · 立即同步持盘 |

## 九、关系

```
010-WAM本源_Origin/                               ← 本源
├── _github_src/packages/
│   ├── wam/                ← WAM 纯源 (devaid publisher)
│   ├── wam-proxy/          ← 2024 规划占位符 (保留)
│   └── wam-dao/            ← ★ 本包 · 二核合一 · dao-agi publisher
├── rt-flow-17.42.2.vsix    ← WAM 单包发布
└── rt-flow-dao-17.51.0.vsix ← ★ 本包归档 (build.cmd 产出)

020-道VSIX_DaoAgi/          ← 渐进迁移 · deploy/e2e 脚本保留 · VsixPath 指向本包即可
030-转制VSIX_Repack/        ← 姊妹包 · 披褐怀玉 · Windsurf exe → VSIX 完全转化
```

**一言以蔽之**: WAM 本源是道, 此包是道之化身, 一气化三清。
**v17.51 一言**: 以反向之思解剖官方 SP, 令用户不被一叶障泰山, 道模知所舍, 官模知所留, 万法具通。
