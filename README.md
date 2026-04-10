# WAM · Windsurf Account Manager

> 道法自然。上善若水，水善利万物而不争。

**WAM v14.2** — 官方API直连 · 系统代理自适应 · 版本自适应注入 · 多源额度竞速 · 零环境依赖 · 纯热替换 · 绝不logout

---

## 它做什么

安装后，Windsurf 编码时额度耗尽会 **自动无感切换到下一个可用账号**，编码体验零中断。

### 核心能力

- **零环境依赖** — 不依赖特定代理软件、端口、网络环境或Windsurf版本，开箱即用
- **系统代理自适应** — 自动读取 `HTTPS_PROXY`/`HTTP_PROXY`/VS Code配置，并行探测验证，无需手动配置
- **版本自适应注入** — 自动适配不同Windsurf版本的注入命令（`provideAuthTokenToAuthProvider`/`provideAuthToken`等）
- **官方API直连** — 额度查询直连 `server.codeium.com` + `web-backend.windsurf.com`，不依赖中继服务器
- **纯热替换** — 绝不logout、绝不杀agent、不重启、不丢上下文（五感模式）
- **Token预热** — 预判下一个最优账号并提前获取Token，切换瞬间完成（<3s）
- **智能轮转** — 日额度/周额度实时监控，消息锚定切号（波动即切）+ 耗尽保护（<5%自动切）
- **多源竞速** — 4通道并行（官方proxy/官方direct/中继direct/中继proxy），第一个成功即返回
- **根治hung注入** — Phase1-4递进式注入：快探3s→收割4s→无条件重试5s→备选命令5s
- **Weekly干旱模式** — 全池W耗尽时自动切入只看Daily模式，避免无效轮转死循环
- **多账号管理** — 暗色主题管理面板，批量验证/清理/刷新有效期/自诊断
- **WAM/官方双模式** — 一键切换，随时回退官方登录

### v14.2 核心改进（相比v10.x）

- **根治环境依赖** — `_getSystemProxy()` 自动读取系统代理配置，`_detectProxy()` 并行TCP探测+CONNECT功能验证
- **根治注入失败** — 4阶段注入+多命令候选+连续失败自动重置命令缓存，实测成功率>95%
- **根治hung promise** — Phase3无条件发新命令逃逸hung provider，不复用卡死的Promise
- **根治额度时效矛盾** — 消息锚定切号（波动=有人发消息→立即切新号）+ 15s cooldown防抖 + 手动切号force无cooldown
- **单key精简** — 移除多key轮转复杂度，单Firebase key + Referer头 + 限流保护
- **Token缓存持久化** — `_token_cache.json` 跨重启保留，冷启动无需重新登录
- **额度查询3端点** — `server.codeium.com` + `web-backend.windsurf.com` + `register.windsurf.com`
- **自诊断命令** — `wam.selfTest` 一键检测网络/代理/端点/注入全链路

## 安装

1. 从 [Releases](https://github.com/zhouyoukang/windsurf-assistant/releases) 下载最新 `.vsix`
2. Windsurf 中 `Ctrl+Shift+P` → `Extensions: Install from VSIX...` → 选择下载的文件
3. 重启 Windsurf，侧边栏出现「无感切号·账号管理」面板

## 源码

`wam-bundle/` 目录包含完整可读源码：

```
wam-bundle/
├── extension.js    # 切号引擎核心 (~5400行)
├── package.json    # 扩展清单
└── media/
    └── icon.svg    # 侧边栏图标
```

## 命令列表

| 命令 | 说明 |
|------|------|
| `WAM: 管理面板` | 打开中央管理面板 |
| `WAM: 切换账号` | 手动选择账号切换（无cooldown限制） |
| `WAM: 智能轮转` | 自动选择最优账号切换 |
| `WAM: 紧急切换` | 无条件切换（不跳过使用中账号） |
| `WAM: 验证清理` | 批量验证并剔除无效/过期账号 |
| `WAM: 刷新有效期` | 批量获取缺失的planEnd |
| `WAM: 自诊断` | 一键检测网络/代理/端点/注入 |
| `WAM: 官方模式` | 暂停WAM，回退官方登录 |

## 许可证

MIT License © 2026
