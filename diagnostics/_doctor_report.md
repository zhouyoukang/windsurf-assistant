# Windsurf Doctor 诊断报告

**时间**: 2026-03-24T16:07:54.746292
**健康评分**: 49/100

## 配置层全景

| 层 | 项目 | 值 |
|---|------|-----|
| L0 | 安装完整性 | 1/6 被修改 | Windsurf v1.9577.43 |
| L1 | settings.json | 70B |
| L2 | user_settings.pb | 84025B, 69个模型 |
| L3 | MCP (Codeium) | 8个服务器 |
| L3 | MCP (User) | 4个服务器 |
| L4 | workspaces | 12个, 健康12/损坏0 |
| L5 | PS会话 | 31个 |
| L6 | Skills/Workflows | 4/4 |

## 发现的问题

### 🔴 [L0] 安装完整性校验失败: 1/6文件被修改 ✅

被修改: workbench.desktop.main.js
这会触发 "Your Windsurf installation appears to be corrupt" 警告

### 🟢 [L2] 39个Windsurf进程运行中

多进程并发写入user_settings.pb可能导致数据竞争

### 🟢 [L3] MCP仅在Codeium级存在: {'tavily', 'user-input', 'dispatch-commander', 'gitee'}

Codeium MCP有更多服务器定义, User级MCP是子集

### 🟢 [L4] 历史工作区记录指向旧路径(ScreenStream_v2)

工作区记录: file:///f%3A/github/AIOT/ScreenStream_v2
这是历史残留, Windsurf按实际打开的文件夹确定当前工作区, 不影响功能

### 🟡 [L5] PowerShell会话文件泄漏: 31个 ✅

过多的陈旧会话文件可能影响扩展性能

### 🟡 [L6] .windsurfrules不存在

## 腐化根因模型

```
L1 settings.json trailing comma → 严格JSON解析器部分失败
    ↓
L1 augment远程配置不可达 → Cascade设置超时/无响应
    ↓
L2 多进程并发写user_settings.pb → protobuf数据竞争
    ↓
L4 state.vscdb写入竞争 → 工作区设置丢失/回退
    ↓
重装清除APPDATA → 临时恢复 → 同样模式重现 → 循环
```

## 为什么重装能临时缓解

1. 清除`APPDATA\Windsurf\` → 所有state.vscdb/WebStorage/缓存重建
2. `~\.codeium\windsurf\` **未被清除** → user_settings.pb/mcp_config/memories保留
3. 用户重新配置settings.json → 可能带入相同的trailing comma和augment配置
4. 根因(并发写入+JSON语法+远程配置)未解决 → 腐化重现

## 永久修复方案

1. **修复settings.json** — 移除trailing comma + 移除augment远程配置
2. **定期诊断** — `python windsurf_doctor.py` 检查配置健康
3. **守护模式** — `python windsurf_doctor.py --watch` 监视配置变化
4. **清理积累** — 陈旧workspace/PS会话/MCP备份