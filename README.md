# Windsurf Assistant

> 水善利万物而不争，处众人之所恶，故几于道。

Windsurf multi-account management — auto-rotate, quota-aware, zero-config.

## Structure

| Directory | Description | Version |
|-----------|-------------|---------|
| [`packages/wam/`](packages/wam/) | WAM 本源 · full edition · message anchoring · token pool · Firebase + Devin | v17.42.20 |
| [`packages/wam-proxy/`](packages/wam-proxy/) | WAM + reverse proxy · archived · 后续独立发布 | v17.58.0 🧊 |
| [`wam-bundle/`](wam-bundle/) | **部署包** · minimal single-file · Devin-only · clean UI | **v2.1.0** ✅ |

## Quick Start (wam-bundle)

1. Put accounts in `~/.wam/accounts.md`:
   ```
   user@example.com password123
   user2@shop.com----password456
   ```
2. Copy `wam-bundle/` to your extensions directory, or build VSIX
3. Done — it activates on startup, no interaction needed

## WAM 本源 (packages/wam)

Full edition with all features:

- **Message anchoring** — 5-probe detection → switch on chat send
- **Token pool** — burst/cruise pre-warming cycle
- **Proxy scanning** — port scan + relay gateway
- **Firebase + Devin** — dual auth with multi-key failover
- **Auto-update** — jsDelivr / SMB source
- **ExtHost sentinel** — event-loop lag detection
- **Instance coordination** — heartbeat + claims across windows

## wam-bundle (Deployment)

Minimal single-file edition (~106KB):

- **Auto-rotate** — quota-aware switching with predictive pre-warming
- **Time rotation** — `rotatePeriodMs` for stealth periodic switching
- **Drought mode** — weekly exhaustion → daily-only fallback
- **Claude gate** — detect Claude model availability per account
- **3-path injection** — IDE internal API → clipboard → hijack (failover)
- **Webview panel** — sidebar + editor panel, live quota bars
- **Invisible mode** — zero-UI stealth operation

### Testing

```bash
cd wam-bundle
node _test_harness.cjs           # offline tests (24 cases)
```

## Configuration

All settings under `wam.*` in settings.

| Setting | Default | Description |
|---|---|---|
| `wam.autoRotate` | `true` | Enable auto-switching |
| `wam.invisible` | `false` | Stealth mode |
| `wam.autoSwitchThreshold` | `5` | Switch threshold (%) |
| `wam.rotatePeriodMs` | `0` | Time rotation (ms, 0=off) |
| `wam.accountsFile` | `""` | Account file (auto-detect) |

## Philosophy

> 分而治之 · 鸡犬相闻 · 民至老死不相往来

- **WAM** — account rotation (本仓)
- **Proxy** — 道德经 prompt injection (后续独立插件)

Two concerns, two plugins, no interference.

## License

MIT
