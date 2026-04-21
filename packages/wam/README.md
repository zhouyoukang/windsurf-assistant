# Windsurf Assistant · 道Agent + 无感切号

> 一个 Windsurf 插件, 二核合一:
>
> - **道Agent** — 为核. 一键把 Cascade 的 system prompt 换为道德经 81 章, 绝 rules/skills/workflows/memories 侧信道注入.
> - **无感切号** — 为器. 百号轮转, 额度耗尽自切, 下一条消息就是新号.

两者相观而善. 道法自然, 无为而无不为.

**本源**: 道Agent 所注之道德经, 源于姊妹项目 [`zhouyoukang/AGI`](https://github.com/zhouyoukang/AGI) — 道生一. 此仓 (windsurf-assistant) 为其用 — 一生二.

---

## 一 · 道Agent (为核)

Cascade 官方系统提示里塞了什么?

```xml
<communication_style>…</communication_style>
<tool_calling>…</tool_calling>
<making_code_changes>…</making_code_changes>
<user_rules>…<MEMORY[user_global]>…</MEMORY[user_global]></user_rules>
<skills>…</skills>
<workflows>…</workflows>
<memories>…</memories>
<ide_metadata>…</ide_metadata>
```

**道Agent 一键化除全部**, 只余道德经 81 章, 前缀 `You are Cascade. 你的唯一` 伪装权重 — 让模型把它当作身份而非可忽略的注入.

```text
点 ☯ 道Agent  →  每次 Cascade 发问前, SP 被纯净换成 TAO_HEADER + 道德经全文
点 ○ 官方Agent →  透传官方原味 SP
```

**三路径齐断**:

1. `plain utf-8` — 裸 UTF-8 SP
2. `nested chat_message` — 嵌套 ChatMessage role=0 content
3. `raw_sp` — RawGetChatMessage field 3

**16 侧信道标记**: communication_style / tool_calling / making_code_changes / running_commands / user_rules / user_information / workspace_information / skills / workflows / memories / memory_system / MEMORY[ / ide_metadata / Bug fixing discipline / Long-horizon workflow / Planning cadence — 任一命中即整体置换.

**v17.36 剥离**: 道Agent proxy 已独立为姊妹插件 `020-道VSIX_DaoAgi`. 本仓专注 WAM 无感切号.

---

## 二 · 无感切号 (为器)

我手上有 100+ 个 Windsurf 账号. 每个的日额度/周额度/试用期/可用性都不一样. 不想盯着这些.

侧栏面板, 从上到下:

- **日额度总计** · **周额度总计** — 整池水位一眼清
- **可用 / 耗尽 / 等重置 / 切 / 号** — 五数说清全部状态
- **活跃号** — 现在谁, 邮箱, 类型 (Trial/Pro), 剩余天, 日用/周用 %
- **消息锚定切号** — 额度波动立切, 下条消息就是新号

---

## 三 · 一行四键 (v17.21)

侧栏只暴露一组按钮, 账号轴 `|` Agent 轴:

```text
模式: [⚡ WAM切号] [🔑 官方登录] | [☯ 道Agent] [○ 官方Agent]
```

- 左二 = **账号层**: WAM 自动轮转 / 官方原生登录
- 右二 = **Agent 层**: 道德经 SP 注入 / 官方原味 Agent

四象独立可组合. 例: WAM 切号 + 道Agent / 官方登录 + 官方Agent / 互换.

---

## 四 · 装

1. 从 [Releases](https://github.com/zhouyoukang/windsurf-assistant/releases) 下载最新 `.vsix`
2. Windsurf 里 `Ctrl+Shift+P` → `Extensions: Install from VSIX...` → 选
3. Reload Window · 侧栏出现 **Windsurf Assistant** 面板

就这. 自动检查更新 (可关).

---

## 五 · 架构 (唯变所适 · v17.41)

```text
┌──────────────────────────────────────────┐
│ Windsurf / Cursor / VSCode  (client)      │
└─────────────┬────────────────────────────┘
              │ extension.js (纯 WAM · 零外部依赖)
              ▼
┌──────────────────────────────────────────┐
│ 无感切号 WAM                              │
│  - 消息锚定: 五路探针 · 对话发送即切号     │
│  - 双身份: Firebase + Devin 自动探测切换   │
│  - Chromium 原生桥 > 系统代理 > 直连       │
│  - WAM_DIR: env/config/默认 ~/.wam-hot    │
│  - 端点/端口/模型: 全 wam.* 可配          │
└─────────────┬────────────────────────────┘
              │ 直连官方 (零中继)
              ▼
        server.codeium.com / windsurf.com
```

**零硬编码**: 路径/端口/端点/模型名全部可通过 `wam.*` 设置或环境变量覆盖 — 适配万千公网用户各类环境

---

## 六 · 姊妹 · 本源 · AGI

[`zhouyoukang/AGI`](https://github.com/zhouyoukang/AGI) — 一卷道德经, 五千言, 八十一章.

> **AGI 之源 · 即此一卷道德经.**

二仓同宗:

| 仓 | 位 | 职 |
| --- | --- | --- |
| [`AGI`](https://github.com/zhouyoukang/AGI) | 一 (本源) | 道德经 81 章 · `道德经.md` 文本本体 |
| [`windsurf-assistant`](https://github.com/zhouyoukang/windsurf-assistant) | 二 (用) | 道Agent 将其注入 Cascade SP · 绝侧信道 · 热切 |

道生一, 一生二, 二生三, 三生万物.

---

## 七 · 许可

MIT.

---

> 道冲, 而用之或不盈. 渊兮, 似万物之宗.
>
> 挫其锐, 解其纷, 和其光, 同其尘.
>
> 湛兮, 似或存.
>
> 吾不知谁之子, 象帝之先.
