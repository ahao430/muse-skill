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
| `muse_start_image_generation(prompt)` | Ask Muse to draw; returns task_id immediately (non-blocking) |
| `muse_get_image_result(task_id)` | Poll the task; on completion returns native MCP images + local paths |
| `muse_get_images(prompt, timeout?)` | Convenience: start + poll in one call (blocks up to timeout) |
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
4. **Repeated timeouts on one session = backlog, not failure.** A side chat
   that received many rapid requests builds up a queued Muse side: it keeps
   timing out while a fresh chat answers instantly. After 2–3 consecutive
   timeouts in the same session, stop retrying there — create a new session
   (`muse_sessions(label="retry")`) and resend. For image tasks start a *new*
   task in the new session (the old one stays resumable if the old session
   ever drains). Muse also refuses some subjects itself (e.g. violence) —
   it usually offers milder alternatives; accept one instead of re-sending
   the same prompt.

## Workflows

- **Consult Muse**: `muse_chat("Review this API design: …")`, relay the answer.
- **Draw an image**: use `muse_start_image_generation(prompt)` then
  `muse_get_image_result(task_id, wait_seconds=90)`. The result returns
  native MCP images (rendered inline by the client) plus local file paths.
  - status `approval_required`: tell the user to approve the egress card in
    the Muse app (choose "allow always" to stop future prompts), then poll
    again — the task is kept, nothing re-generates.
  - status `timeout`: Muse is still working; poll again later. Never
    re-submit the same drawing.
  - **When showing images to the user, ALWAYS use Markdown image syntax**
    (`![描述](https://直链)`) — a bare URL does not render in the chat.
    With a COS media relay configured, prefer the COS direct link from the
    task's image metadata (permanent, no expiry). The relay's *first* upload
    pops one domain approval card in the Muse app (curl → myqcloud.com) —
    tell the user to pick "always allow"; every later upload is silent.
  - If the client cannot render images, give the user the local paths.
- **Long tasks**: `muse_send` the request, then poll with `muse_chat`
  follow-ups ("status?") in the same `session_id`.

## Constraints

- One waiting request per chat at a time (Muse protocol limit).
- Images ≤ 2 MiB (JPEG/PNG/GIF/WebP); no other file transfer in v1.
- Everything the user sees should say "Muse", never "Hatch" (official rule).
