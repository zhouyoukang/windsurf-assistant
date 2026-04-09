# Windsurf Assistant (WAM)

> 上善若水。水善利万物而不争。

**Windsurf Account Manager v10.0.5** — 纯热替换 · Token预热 · Rate-limit拦截 · 智能轮转 · 首选账号同步 · 零中断

---

## 它做什么

安装后，Windsurf 编码时额度耗尽会 **自动无感切换到下一个可用账号**，编码体验零中断。

### 核心能力

- **纯热替换** — 绝不logout、绝不杀agent、不重启、不丢上下文
- **Token预热** — 预判下一个最优账号并提前获取Token，切换瞬间完成
- **智能轮转** — 日额度/周额度实时监控，预判切换（<25%预选，<5%自动切）
- **Rate-limit拦截** — 429检测+指数退避+多通道竞速(直连/中转/代理)
- **多账号管理** — 暗色主题管理面板，批量验证/清理/刷新有效期
- **WAM/官方双模式** — 一键切换，随时回退官方登录

### v10.0.5 修复

- **首选账号同步** — 注入成功后自动更新 `state.vscdb` 的首选账号，解决 Windsurf v1.108+ 切号后实际不生效的根因
- **`@vscode/sqlite3` 集成** — 使用 Windsurf 内置 SQLite 模块，零依赖
- **双路径覆盖** — `switchToAccount` 和 `fileWatcher` 两个注入入口均同步

### v10.0.4 修复

- **切号不受cooldown限制** — `switchToAccount` 调用 `firebaseLogin` 时 `force=true`，绕过全局冷却
- **冷却时间大幅降低** — 基础冷却90s→15s，最大冷却600s→60s，防止deadlock
- **误判修复** — Firebase quota错误匹配从宽泛的 `quota|App Check` 收窄为精确的 `Quota exceeded|RESOURCE_EXHAUSTED`
- **多Firebase Key支持** — 恢复多key轮转，单key不再是单点故障

## 安装

1. 从 [Releases](https://github.com/zhouyoukang/windsurf-assistant/releases) 下载最新 `.vsix`
2. Windsurf 中 `Ctrl+Shift+P` → `Extensions: Install from VSIX...` → 选择下载的文件
3. 重启 Windsurf，侧边栏出现「无感切号·账号管理」面板

## 源码

`wam-bundle/` 目录包含完整可读源码（WAM v10.0.5）：

```
wam-bundle/
├── extension.js    # 切号引擎核心 (~4900行)
├── package.json    # 扩展清单
└── media/
    └── icon.svg    # 侧边栏图标
```

## 许可证

MIT License © 2026
