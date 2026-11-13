# Muse Agent Skill

Connect [Muse](https://muse.ai) to coding agents (Claude Code, Zcode, …)
through **MCP** and **Agent Skills**. Ask Muse questions, get answers, and run
cross-agent workflows — no public server, everything local.

```
Claude Code / Zcode ──MCP stdio──> muse-agent (this repo, Mac)
                                       │ SSH
                                       ▼
                       musegadget 服务 (常驻 Linux gadget 主机)
                                       │ WSS + Noise
                                       ▼
                                    Muse VM
```

## Quick start

1. **Provision the gadget host** (once):

   ```sh
   scripts/provision.sh --host USER@HOST --sdk-token mgst_…
   ```

2. **Pair once over BLE** — needs any BLE-capable Linux + the Muse phone app.
   Full guide: [docs/pairing.md](docs/pairing.md). Then import the pairing:

   ```sh
   scripts/import_state.sh ~/muse-pairing --host USER@HOST
   ```

3. **Register the MCP server** in your agent client:
   [Claude Code](docs/claude-code.md) · [Zcode](docs/zcode.md)

4. **Install the skill** (optional but recommended): copy `skills/muse/` into
   your agent's skills directory.

## Tools

| Tool | Purpose |
|---|---|
| `muse_status` | gadget host reachable? paired? service active? |
| `muse_send` | fire-and-forget message to Muse |
| `muse_chat` | send + wait for Muse's answer (1–600 s) |
| `muse_wait` | not supported by remote CLI (kept as explicit error) |
| `muse_sessions` | create/list agent side chats |

## Configuration

`~/.config/muse-agent/config.yaml` (all optional):

```yaml
host: root@example.com      # gadget host; env MUSE_AGENT_HOST overrides
timeout: 120                # default muse_chat wait seconds
connect_timeout: 10
```

Secrets (SDK token, pairing JSON) live only on the gadget host — never in
this repo. See [docs/pairing.md](docs/pairing.md) for the security notes.

## Development

```sh
uv sync
uv run pytest
uv run muse-agent --status   # debug outside MCP
```

## Status

- [x] MCP server + SSH adapter + skill + provisioning scripts
- [ ] One-time BLE pairing (needs USB BLE adapter; see docs/pairing.md)
- [ ] End-to-end `muse_chat` verification after pairing
