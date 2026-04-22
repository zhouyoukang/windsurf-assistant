# Windsurf Assistant · Monorepo

> 道生一, 一生二, 二生三, 三生万物.

一个仓, 两个插件 — 同源异用.

## Packages

| 子项 | 路径 | 职责 | 状态 |
|------|------|------|------|
| **WAM** | [`packages/wam/`](packages/wam/) | 纯无感切号 · 百号轮转 · 消息锚定 · 零中继直连 | ✅ v17.42.13 |
| **WAM-Proxy** | [`packages/wam-proxy/`](packages/wam-proxy/) | WAM + 反代 · 道德经 SP 注入 · 绝侧信道 | � 未发布 |

## WAM (packages/wam)

纯切号插件. 无外部依赖, 单文件 `extension.js`.

- **四级容错 activate**: 产品名/数据目录/存储路径/日志 逐段 try/catch
- **六级 WAM_DIR 兜底**: env → config → legacy → 用户隔离 → globalStorage → tmpdir
- **消息锚定**: 五路探针, 对话发送即切号
- **双身份**: Firebase + Devin 自动探测
- **零硬编码**: 路径/端口/端点/模型全 `wam.*` 可配

## WAM-Proxy (packages/wam-proxy)

WAM 切号 + 反代注入道德经. 未发布.

- **三路径齐断**: plain UTF-8 / nested ChatMessage / raw_sp
- **16 侧信道标记**: 全部识别并置换
- **vendor 内嵌 WAM core**: 零依赖独立运行

## 共享基建

```text
scripts/
  deploy.js        # 141/179 双端部署
  build-vsix.js    # VSIX 打包
.github/
  workflows/
    ci.yml         # E2E 自动验证
```

## 姊妹仓

| 仓 | 位 | 职 |
|---|---|---|
| [`zhouyoukang/AGI`](https://github.com/zhouyoukang/AGI) | 一 (本源) | 道德经 81 章 · 道德经.md 文本本体 |
| [`zhouyoukang/windsurf-assistant`](https://github.com/zhouyoukang/windsurf-assistant) | 二 (用) | WAM 切号 + 道Agent 注入 |

## License

MIT.

---

> 道冲, 而用之或不盈. 渊兮, 似万物之宗.
