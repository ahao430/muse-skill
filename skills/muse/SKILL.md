---
name: muse
description: Talk to Muse (Meta's AI device assistant) from coding agents — send messages, get answers, run cross-agent workflows. Use when the user asks to consult Muse, ask Muse something, or collaborate with Muse on a task.
---

# Muse Skill

Send messages to Muse and receive answers (text and images), through the
`muse` MCP server. Default backend talks to Muse directly from this Mac
(muse-client); an optional SSH backend uses a remote musegadget host.

## Tools

| Tool | When to use |
|---|---|
| `muse_status` | First call of a session: verify host reachable + paired |
| `muse_chat(message, session_id?, timeout?)` | Ask Muse something and get its answer |
| `muse_send(message, session_id?)` | Notify Muse without waiting (fire-and-forget) |
| `muse_send_image(image_path, message?, …)` | Show Muse a picture (≤2 MiB, JPEG/PNG/GIF/WebP) |
| `muse_get_images(prompt?, …)` | Ask Muse to draw and get the images back as local file paths (local backend only) |
| `muse_doctor()` | When status looks broken: setup checklist with next commands |
| `muse_sessions(label?)` | Create/list agent side chats |

## How to use

1. Call `muse_status` once. If `ready` is false, follow its `error`/`hint`
   fields (pairing: `bun bridge/bridge.mjs pair`, see docs/pairing.md).
2. Create a side chat for the task: `muse_sessions(label="code-review")`
   → returns `session_id`. Keep using that `session_id` for the whole
   conversation so agent↔Muse talk stays out of the user's main chat.
3. Ask with `muse_chat(message, session_id=…)`. `timeout` defaults to 120s
   (max 600s). If it times out, the message **was still delivered** — Muse may
   answer later; retry `muse_chat` with a longer timeout instead of assuming
   failure.

## Workflows

- **Consult Muse**: `muse_chat("Review this API design: …")`, relay the answer.
- **Long tasks**: `muse_send` the request, then poll with `muse_chat`
  follow-ups ("status?") in the same `session_id`.
- **Analysis/drawing**: just ask in natural language via `muse_chat`; Muse
  decides what to do. Image results land in the Muse chat, not in this tool.

## Constraints

- One waiting request per chat at a time (Muse protocol limit).
- Images ≤ 2 MiB (JPEG/PNG/GIF/WebP); no other file transfer in v1.
- Everything the user sees should say "Muse", never "Hatch" (official rule).
