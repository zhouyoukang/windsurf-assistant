# WAM · Windsurf Account Manager

> 道可道，非常道。名可名，非常名。

**WAM v17.0** — 道法自然 · 零硬编码 · 动态配置 · 跨平台自适应 · 所有Windsurf环境 · 所有代理环境

---

## 它做什么

安装后，Windsurf 编码时额度耗尽会 **自动无感切换到下一个可用账号**，编码体验零中断。

### v17.0 核心突破: 从根本底层去除一切硬编码

**审视插件本源，从根本底层去除各个无意义确定性编码。** 28个硬编码常量全部替换为动态getter函数，通过VS Code settings (`wam.*`) 可覆盖一切参数。真正实现彻底的适配：

| 维度 | 机制 | 配置入口 |
|------|------|---------|
| **产品名** | `_detectProductName()` 自动识别 Windsurf/Cursor/Code | `wam.productName` |
| **数据目录** | `_resolveDataDir()` Win/Mac/Linux 候选链 | `wam.dataDir` |
| **网络环境** | `_getSystemProxy()` + `_detectProxy()` 并行TCP+CONNECT | `wam.proxy.extraPorts` |
| **Firebase** | `_getFirebaseKeys()` 可追加key | `wam.firebase.extraKeys` |
| **API端点** | `_getOfficialPlanStatusUrls()` 可追加 | `wam.officialEndpoints` |
| **注入命令** | `_getInjectCommands()` 3命令候选可覆盖 | `wam.injectCommands` |
| **中继** | `_getRelayHost()` 占位符自动禁用 | `wam.relayHost` |
| **时序阈值** | 14个 getter (monitor/scan/burst/cooldown等) | `wam.monitorIntervalMs` 等 |
| **电脑环境** | 仅依赖 Node.js 标准库 | — |
| **DNS环境** | DoH双路径 (Google + Cloudflare) | — |

### 核心能力

- **动态配置层** — 28个常量全部getter化，`_cfg(key, default)` 读 VS Code settings，0/false作为合法值
- **跨平台自适应** — Windows `%APPDATA%` / macOS `~/Library` / Linux `~/.config` 自动检测
- **4阶段递进注入** — P1快探3s → P2收割4s → P3无条件重试4s → P4备选命令5s
- **Token活水池** — 后台持续预热所有账号Token，切号必然cache HIT，切换<3s
- **消息锚定切号** — 实时监测额度波动，波动即切号，确保下条消息用新号
- **多源额度竞速** — 5通道并行(Chromium/官方proxy/官方direct/中继IP/中继proxy)
- **3官方端点** — `server.codeium.com` + `web-backend.windsurf.com` + `register.windsurf.com`
- **五感模式** — 绝不logout、绝不杀agent、不重启、不丢上下文
- **Weekly干旱模式** — 全池W耗尽自动切入Daily模式
- **热部署** — `restartExtensionHost` 仅重启扩展，不中断对话
- **自诊断** — `wam.selfTest` 一键全链路检测

## 安装

1. 从 [Releases](https://github.com/zhouyoukang/windsurf-assistant/releases) 下载最新 `.vsix`
2. Windsurf 中 `Ctrl+Shift+P` → `Extensions: Install from VSIX...` → 选择下载的文件
3. 重启 Windsurf，侧边栏出现「无感切号·账号管理」面板

## 可选配置 (Settings JSON)

所有配置项均有合理默认值，**零配置即可使用**。高级用户可通过 `settings.json` 微调：

```jsonc
{
  "wam.autoRotate": true,              // 自动切号
  "wam.autoSwitchThreshold": 5,        // 额度<5%切号
  "wam.predictiveThreshold": 25,       // 额度<25%预热Token
  "wam.monitorIntervalMs": 3000,       // 监测间隔
  "wam.proxy.extraPorts": [9999],      // 追加代理端口
  "wam.relayHost": "",                 // 中继域名(留空禁用)
  "wam.firebase.extraKeys": [],        // 追加Firebase key
  "wam.officialEndpoints": []          // 追加API端点
}
```

## 源码

```
wam-bundle/
├── extension.js    # 切号引擎核心 (~6100行, 纯Node.js标准库)
├── package.json    # VS Code 扩展清单
└── media/
    └── icon.svg    # 侧边栏图标
```

## 命令列表

| 命令 | 说明 |
|------|------|
| `WAM: 管理面板` | 打开中央管理面板 |
| `WAM: 切换账号` | 手动选择账号切换 |
| `WAM: 智能轮转` | 自动选择最优账号切换 |
| `WAM: 紧急切换` | 无条件切换（不跳过使用中账号） |
| `WAM: 验证清理` | 批量验证并剔除无效/过期账号 |
| `WAM: 刷新有效期` | 批量获取缺失的planEnd |
| `WAM: 自诊断` | 一键检测网络/代理/端点/注入 |
| `WAM: 官方模式` | 暂停WAM，回退官方登录 |

## 许可证

MIT License © 2026
