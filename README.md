# Muse Agent Skill

Connect [Muse](https://muse.ai) to coding agents (Claude Code, Zcode, …)
through **MCP** and **Agent Skills**. Ask Muse questions, get answers, send
images, and run cross-agent workflows — everything local, no public server.

```
Claude Code / Zcode ──MCP stdio──> muse-agent (this repo, Mac)
                                       │ backend: local (default)
                                       ▼
                    muse-client (TypeScript, macOS BLE pairing)
                                       │ WSS + Noise
                                       ▼
                                    Muse VM
```

Optional `ssh` backend runs the official musegadget service on an always-on
Linux host instead (for 24/7 availability) — see
[docs/pairing.md](docs/pairing.md#方式二可选后端linux-gadget-主机).

## Quick start

0. **Sanity check** (any time, no Muse needed):

   ```sh
   uv sync && uv run pytest
   (cd bridge && bun install)
   bun bridge/bridge.mjs status        # → {"paired": false, ...}
   ```

1. **Pair once on this Mac** (internal Bluetooth, no extra hardware):
   [docs/pairing.md](docs/pairing.md) 方式一 —

   ```sh
   export MUSE_SDK_TOKEN=mgst_…        # gadgets.muse.ai
   bun bridge/bridge.mjs pair          # phone app: Developer mode → Add Device
   ```

2. **Register the MCP server** in your agent client:
   [Claude Code](docs/claude-code.md) · [Zcode](docs/zcode.md)

3. **Install the skill** (optional but recommended): copy `skills/muse/` into
   your agent's skills directory.

## Tools

| Tool | Purpose |
|---|---|
| `muse_status` | paired? connected? (first call of a session) |
| `muse_send` | fire-and-forget message to Muse |
| `muse_chat` | send + wait for Muse's answer (1–600 s) |
| `muse_send_image` | send a picture (≤2 MiB, JPEG/PNG/GIF/WebP) + optional text |
| `muse_doctor` | troubleshooting (backend health check) |
| `muse_wait` | not supported by Muse's protocol (kept as explicit error) |
| `muse_sessions` | create/list agent side chats |

If Muse does not answer within the timeout, the message **was still
delivered** — retry `muse_chat` with a longer timeout rather than assuming
failure (see SKILL.md).

## Configuration

`~/.config/muse-agent/config.yaml` (all optional):

```yaml
backend: local        # local (default) | ssh
host: root@example.com  # gadget host; backend: ssh only
timeout: 120            # default muse_chat wait seconds
# bridge_command: bun  # runner for bridge/bridge.mjs
# credentials_dir: …   # muse-client credentials dir override
```

Secrets (SDK token, pairing credentials) live only on this machine — never
in this repo. Security notes: [docs/pairing.md](docs/pairing.md).

## Development

```sh
uv sync
uv run pytest
uv run muse-agent --status     # debug outside MCP
bun bridge/bridge.mjs --help   # the Node bridge underneath
```

## Status

- [x] Dual-backend MCP server (local muse-client / remote musegadget) + skill
      + provisioning scripts (23 unit tests)
- [x] One-time BLE pairing on the Mac (internal Bluetooth, no extra hardware)
- [x] End-to-end verified: `muse_chat` text, new-session auto-provisioning,
      and image send/reply through the MCP stdio tool
- Known limits: main-chat replies can't be proven bound to programmatic
  requests — the agent auto-talks in its own persistent side chat (UUID ids
  only, auto-created on first use).
