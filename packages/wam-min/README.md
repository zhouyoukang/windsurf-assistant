# WAM Min · v2.1.0

> 水善利万物而不争，处众人之所恶，故几于道。

Minimal edition of **Windsurf Account Manager** — a single-file VSCode extension (~106KB) that manages a pool of Windsurf accounts with automatic rotation.

## What it does

- **Auto-rotate** — monitors active account quota (daily/weekly %), switches to the best available when exhausted
- **Predictive pre-warming** — pre-selects next candidate before quota hits zero
- **Time-based rotation** — optional periodic rotation (`rotatePeriodMs`) for stealth
- **Drought detection** — when all weekly quotas are exhausted, switches to daily-only mode
- **Three injection paths** — IDE internal API → clipboard → hijack (failover chain)
- **Webview panel** — sidebar + editor panel with live quota bars, domain badges, lock/unlock
- **Batch verify** — parallel account verification with rate-limiting
- **Zero config required** — works out of the box with `onStartupFinished`

## Quick Start

1. Place account file at `~/.wam/accounts.md` (one per line: `email password`)
2. Install the extension
3. It activates automatically — no buttons to click

Supported account formats:
```
user@example.com password123
user@shop.com----password456
user@gmail.com:password789
user@outlook.com|password000
```

## Architecture

```
extension.js      — single file, zero dependencies
_test_harness.cjs — offline test suite (mocks vscode API)
package.json      — VSCode extension manifest
```

### Key internals

| Component | Role |
|---|---|
| `Store` | Account pool + health state + persistence (`~/.wam/wam-state.json`) |
| `Engine` | Auto-rotation loop (`_tick`), exhaust/time rotation, health checks |
| `buildHtml` | Webview UI renderer (domain badges, quota bars, Claude gate) |
| `verifyAllAccounts` | Parallel batch verify with configurable gap/parallelism |
| `loginAccount` | Devin 3-step pipeline: login → postAuth → registerUser → inject |
| `injectToken` | 3-path failover: IDE API (丙) → clipboard (乙) → hijack (甲) |

### Differences from WAM full (`../wam/`)

| | WAM full (v17.42.20) | WAM min (v2.1.0) |
|---|---|---|
| Size | ~435 KB | ~106 KB |
| Message anchoring | ✅ 5-probe network/command/file | — |
| Token pool pre-warming | ✅ burst/cruise cycle | — |
| Proxy scanning | ✅ port scan + relay | — |
| Firebase auth | ✅ multi-key failover | — (Devin-only) |
| Auto-update | ✅ jsDelivr/SMB | — |
| ExtHost lag sentinel | ✅ event-loop probe | — |
| Instance coordination | ✅ heartbeat + claims | — |
| Core rotation | ✅ | ✅ |
| Webview panel | ✅ | ✅ (simplified UI) |
| Claude gate detection | ✅ | ✅ |
| Drought mode | ✅ | ✅ |
| Time-based rotation | — | ✅ (`rotatePeriodMs`) |

## Configuration

All settings are under `wam.*` in VSCode settings. Key ones:

| Setting | Default | Description |
|---|---|---|
| `wam.autoRotate` | `true` | Enable auto-switching |
| `wam.invisible` | `false` | Stealth mode — minimal UI |
| `wam.rotatePeriodMs` | `0` | Time rotation (ms, 0=off) |
| `wam.autoSwitchThreshold` | `5` | Switch when quota < N% |
| `wam.verify.parallel` | `3` | Batch verify parallelism |
| `wam.accountsFile` | `""` | Account file path (auto-detect) |

## Testing

```bash
node _test_harness.cjs           # offline (mocked vscode API, 24 cases)
node _test_harness.cjs --devin   # live Devin pipeline (needs accounts)
```

## License

MIT
