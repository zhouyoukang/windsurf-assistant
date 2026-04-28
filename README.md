# Windsurf Assistant

> 水善利万物而不争，处众人之所恶，故几于道。

Windsurf multi-account management — auto-rotate, quota-aware, zero-config.

## Packages

| Package | Path | Description | Status |
|---------|------|-------------|--------|
| **WAM** | [`packages/wam/`](packages/wam/) | Full edition · message anchoring · token pool · proxy scan · Firebase + Devin | v17.42.20 |
| **WAM Min** | [`packages/wam-min/`](packages/wam-min/) | Minimal edition · ~106KB single file · Devin-only · clean UI | **v2.1.0** ✅ |
| **WAM-Proxy** | [`packages/wam-proxy/`](packages/wam-proxy/) | WAM + reverse proxy · archived | v17.58.0 🧊 |

## WAM Min (packages/wam-min) — Recommended

The minimal edition. One file, zero dependencies, works everywhere.

### Features
- **Auto-rotate** — quota drops below threshold → switch to best account
- **Predictive pre-warming** — pre-select next candidate before exhaustion
- **Time rotation** — optional `rotatePeriodMs` for stealth periodic switching
- **Drought mode** — all weekly quotas exhausted → daily-only fallback
- **Claude gate** — detect Claude model availability per account
- **3-path injection** — IDE internal API → clipboard → hijack (failover)
- **Webview panel** — sidebar + editor panel, live quota bars
- **Batch verify** — parallel account verification
- **Invisible mode** — `wam.invisible: true` for zero-UI stealth operation

### Quick Start

1. Put accounts in `~/.wam/accounts.md`:
   ```
   user@example.com password123
   user2@shop.com----password456
   ```
2. Install the `.vsix` or copy to extensions directory
3. Done — it activates on startup, no interaction needed

### Testing

```bash
cd packages/wam-min
node _test_harness.cjs           # offline tests (24 cases)
node _test_harness.cjs --devin   # live pipeline test
```

## WAM Full (packages/wam)

The full edition with advanced features:

- **Message anchoring** — 5-probe detection (network/command/file) → switch on chat send
- **Token pool** — burst/cruise pre-warming cycle
- **Proxy scanning** — port scan + relay gateway
- **Firebase + Devin** — dual auth with multi-key failover
- **Auto-update** — jsDelivr / SMB source
- **ExtHost sentinel** — event-loop lag detection
- **Instance coordination** — heartbeat + claims across windows

## Configuration

All settings under `wam.*` in VSCode settings. Both editions share the same namespace.

| Setting | Default | Description |
|---|---|---|
| `wam.autoRotate` | `true` | Enable auto-switching |
| `wam.invisible` | `false` | Stealth mode |
| `wam.autoSwitchThreshold` | `5` | Switch threshold (%) |
| `wam.rotatePeriodMs` | `0` | Time rotation (ms, 0=off) |
| `wam.accountsFile` | `""` | Account file (auto-detect) |

See each package's README for full configuration reference.

## License

MIT
