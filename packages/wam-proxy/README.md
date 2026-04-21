# WAM-Proxy · 切号 + 反代中继

> WAM 无感切号 + 本地反代 · 道Agent SP 注入 · API 密钥路由

## 定位

| 能力 | WAM (纯切号) | WAM-Proxy (本包) |
|------|-------------|-----------------|
| 百号轮转 | ✅ | ✅ (复用 WAM 核心) |
| 消息锚定切号 | ✅ | ✅ |
| 道Agent SP 注入 | ❌ | ✅ |
| Anthropic/OpenAI 中继 | ❌ | ✅ |
| TLS 本地代理 | ❌ | ✅ |
| 零外部依赖 | ✅ | ❌ (需 Node proxy) |

## 架构

```text
┌─────────────────────────────┐
│ Windsurf (client)           │
└──────────┬──────────────────┘
           │ extension.js (WAM + proxy 管理)
           ▼
┌─────────────────────────────┐
│ 本地反代 (dao-proxy)         │
│  - SP 拦截 · 道德经替换      │
│  - API key 路由              │
│  - TLS 自签证书              │
└──────────┬──────────────────┘
           │
           ▼
     server.codeium.com / windsurf.com / api.anthropic.com
```

## 状态

🚧 **规划中** — WAM 核心已稳定 (v17.41), proxy 层将从 `010-反代_Proxy` 整合迁入.

## License

MIT.
