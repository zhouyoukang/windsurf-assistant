# Windsurf Assistant

> 上善若水。水善利万物而不争。

**Windsurf 无感切号插件** — 主动容量探测 · 即时切换 · 智能轮转 · 零中断

---

## 它做什么

安装后，Windsurf 编码时额度耗尽会 **自动无感切换到下一个可用账号**，编码体验零中断。

核心能力：
- **无感切换** — 额度不足时自动切到最优账号，不logout、不重启、不丢上下文
- **智能轮转** — 日额度/周额度实时监控，预判切换（<25%预选，<5%自动切）
- **多账号管理** — 暗色主题管理面板，批量验证/清理/刷新有效期
- **WAM/官方双模式** — 一键切换，随时回退官方登录

## 安装

1. 从 [Releases](https://github.com/zhouyoukang/windsurf-assistant/releases) 下载最新 `.vsix`
2. Windsurf 中 `Ctrl+Shift+P` → `Extensions: Install from VSIX...` → 选择下载的文件
3. 重启 Windsurf，侧边栏出现「无感切号·账号管理」面板

## 源码

`wam-bundle/` 目录包含完整可读源码（WAM v9.1.0，3280行JS）：

```
wam-bundle/
├── extension.js    # 切号引擎核心
└── package.json    # 扩展清单
```

## 许可证

MIT License © 2026
