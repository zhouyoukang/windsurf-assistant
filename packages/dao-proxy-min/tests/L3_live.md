# L3 活检手册 · 真 Windsurf · 真 Cascade · 真云端

> "知者不博，博者不知；善者不多，多者不善。" —《帛书·德经》
> L3 是 L1 (proto 字节级) + L2 (本地 → 云端 200) 之上的最终一跳：
> 真 Windsurf 启动 → LS 经代理 → 云端真返 AI 回复 → 验回复"含道义"。

## 前置

- 已装 dao-proxy-min v2.0+ vsix
- Windsurf 已登录可用 (官方 Agent 默工作正常)

## 步骤

### 1. 启 Windsurf · 验本基

打开 Cascade 窗口，问：

> who are you? answer in one short sentence.

期：官方答 "I'm Cascade, an AI coding assistant..."（说明本基官方路径正常）。

### 2. 道Agent · 启

`Ctrl+Shift+P` → 输 `道Agent: 启 (invert · 道德经 SP · 反代替换)` → 回车

提示弹出 → 点 **重载窗口**

### 3. 重载后 · 实问

Cascade 中再问：

> 你是谁？用一句中文回答。

期：

- 答中含"道"/"无为"/"自然"/"圣人"等关键词 (说明 SP 已替为道德经，云端按道经语义生成)
- 不再答"I'm Cascade, AI coding assistant"
- 不报 `invalid_argument` 或网络错

### 4. 跑闭环自检 · 验代理捕获

`Ctrl+Shift+P` → 输 `闭环自检 (L1 单元 + L2 路径)` → 回车

输出通道 "道Agent" 应显：

```text
── L1 · proto 单元自检 ──
  道德经字数: 6776
  通过率: 7/7
  总体: ✓ 全绿
  ✓ classic_chat_messages: ...
  ✓ chat_message_with_role: ...
  ...

── L2 · 反代路径 ──
  端口: 8889
  settings.codeium.apiServerUrl: http://127.0.0.1:8889
  settings.codeium.inferenceApiServerUrl: http://127.0.0.1:8889
  ✓ 代理 ping: mode=invert uptime=Ns req_total=N capture_count=≥1
  最近替换: at=...  url=/exa.api_server_pb.ApiServerService/GetChatMessage
     before(NB): You are Cascade, a powerful agentic AI coding assistant...
     after(MB):  道可道，非常道。名可名，非常名。无，名天地之始；有，名万物之母。...
     after_starts_with_dao: true
```

**关键**: `after_starts_with_dao: true` + `capture_count > 0` 即真证 LS 实经代理且 SP 真被替为道德经。

### 5. 官方Agent · 还原

`Ctrl+Shift+P` → 输 `官方Agent: 启 (passthrough · 不动一切 · LS 直飞云)` → 回车 → 点 **重载窗口**

重载后 Cascade 应回归官方答案 ("I'm Cascade...")，验态可逆。

## 排错

| 现象 | 因 | 治 |
|---|---|---|
| 道Agent 启后 Cascade 不答 | LS 未重载 | 强制 `Ctrl+Shift+P → Reload Window` |
| 答中无道义关键词 | LS 仍连云端 | 验 settings.json 的 `codeium.apiServerUrl` 是否 `http://127.0.0.1:8889` |
| `EADDRINUSE :8889` | 旧实例端口未释放 | 重载窗口 (extension deactivate 会 stop server) |
| `capture_count=0` | LS 未发 GetChatMessage 经代理 | 实问 Cascade 一句, 再跑自检 |
| 云端返 `invalid_argument` | 不应再发生 (L1 已证 proto 字节级正确). 若发生 → 在自检日志贴 capture before/after | 反馈 issue |
| 卸 vsix 后 Cascade 不连云 | settings.json 二键残留 | 手编 settings.json 删 `codeium.apiServerUrl` 与 `codeium.inferenceApiServerUrl` |
