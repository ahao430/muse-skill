"""MCP stdio server exposing Muse tools to coding agents."""

from __future__ import annotations

import asyncio
import json
import sys

from mcp.server.fastmcp import FastMCP

from . import config as cfg
from .adapter import GadgetAdapter, MuseUnavailable, NotPaired

mcp = FastMCP("muse-agent")
_adapter = GadgetAdapter()

# Blocking calls (subprocess, ssh) must not stall the stdio event loop.
async def _call(fn, *args):
    return await asyncio.to_thread(fn, *args)


def _adapter_error_text(exc: Exception) -> str:
    if isinstance(exc, NotPaired):
        return (
            f"Muse is not paired yet: {exc}. "
            "Complete the one-time BLE pairing described in docs/pairing.md."
        )
    if isinstance(exc, MuseUnavailable):
        if _adapter.config.backend == "local":
            return (
                f"The local Muse backend failed: {exc}. "
                "Run `muse_doctor` for a component-by-component checklist."
            )
        return (
            f"Cannot reach the Muse gadget host: {exc}. "
            "Check SSH access and that the musegadget service is running "
            "(scripts/provision.sh sets it up)."
        )
    return str(exc)


# Inline-image budget for MCP responses: 4 MiB of raw bytes ≈ 5.4 MiB base64.
_MAX_INLINE_BYTES = 4 * 1024 * 1024


def _read_file_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _download_image(url: str, task_id: str, index: int) -> str:
    """Download a public muse.ai/files link to a persistent per-task file."""
    import urllib.request

    dest_dir = cfg.CONFIG_DIR / "images" / task_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"image-{index}.webp"
    req = urllib.request.Request(url, headers={"User-Agent": "muse-agent/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp, dest.open("wb") as f:
        f.write(resp.read())
    return str(dest)


def _download_task_images(task_id: str, images: list[dict]) -> None:
    """Fill in `path` for task images missing one; skips known URLs so a
    repeated poll never re-downloads."""
    import os

    for index, img in enumerate(images):
        if img.get("path") and os.path.exists(img["path"]):
            continue
        if not img.get("url", "").startswith("https://muse.ai/"):
            continue
        try:
            img["path"] = _download_image(img["url"], task_id, index)
        except Exception as exc:  # noqa: BLE001 — keep other images flowing
            img["download_error"] = str(exc)


@mcp.tool()
async def muse_status() -> dict:
    """Check the Muse connection: host, service state, pairing identity.

    Use this first to verify the gadget host is reachable and paired.
    """
    try:
        return await _call(_adapter.status)
    except (MuseUnavailable, NotPaired) as exc:
        return {"ready": False, "error": _adapter_error_text(exc)}


@mcp.tool()
async def muse_send(message: str, session_id: str | None = None) -> dict:
    """Send a message to Muse without waiting for the answer.

    Use for notifications or fire-and-forget updates. The reply, if any,
    appears in the Muse chat; use muse_chat when you need the answer.
    """
    try:
        result = await _call(_adapter.send, message, session_id)
    except (MuseUnavailable, NotPaired) as exc:
        return {"ok": False, "error": _adapter_error_text(exc)}
    return {"ok": result.ok, "detail": result.detail}


@mcp.tool()
async def muse_chat(
    message: str,
    session_id: str | None = None,
    timeout: int | None = None,
) -> dict:
    """Send a message to Muse and wait for its full answer.

    Prefer a dedicated side chat session_id (see muse_sessions) so this
    conversation does not interleave with the user's main Muse chat.
    timeout is seconds (1-600, default from config). If Muse does not answer
    in time, the message was still delivered; retry muse_chat rather than
    assuming failure.
    """
    try:
        result = await _call(_adapter.chat, message, session_id, timeout)
    except (MuseUnavailable, NotPaired) as exc:
        return {"ok": False, "error": _adapter_error_text(exc)}
    return {"ok": result.ok, "reply": result.text, "detail": result.detail}


@mcp.tool()
async def muse_send_image(
    image_path: str,
    message: str = "",
    session_id: str | None = None,
    timeout: int | None = None,
) -> dict:
    """Send a picture to Muse (with optional text) and optionally wait.

    image_path is a local file (JPEG/PNG/GIF/WebP, max 2 MiB); it is copied
    to the gadget host and sent through Muse. Pass timeout to wait for
    Muse's answer like muse_chat.
    """
    try:
        result = await _call(_adapter.send_image, image_path, message, session_id, timeout)
    except (MuseUnavailable, NotPaired) as exc:
        return {"ok": False, "error": _adapter_error_text(exc)}
    return {"ok": result.ok, "reply": result.text, "detail": result.detail}


@mcp.tool()
async def muse_doctor() -> dict:
    """Diagnose the Muse setup and return a first-use checklist.

    Local backend: checks runner, bridge script, dependencies, pairing
    credentials and the live connection, each with the exact next command
    for the first missing piece. SSH backend: runs the official
    `musegadget doctor` on the gadget host. Use when anything is broken.
    """
    try:
        return await _call(_adapter.doctor)
    except (MuseUnavailable, NotPaired) as exc:
        return {"ok": False, "error": _adapter_error_text(exc)}


@mcp.tool()
async def muse_start_image_generation(
    prompt: str,
    session_id: str | None = None,
) -> dict:
    """Submit an image-generation request to Muse and return a task_id at once.

    Non-blocking: Muse renders asynchronously (tens of seconds), so follow up
    with muse_get_image_result(task_id) instead of waiting here. Do NOT call
    this twice for the same drawing — repeated polls of the same task never
    re-generate.
    """
    try:
        return await _call(_adapter.start_image_task, prompt, session_id)
    except (MuseUnavailable, NotPaired) as exc:
        return {"ok": False, "error": _adapter_error_text(exc)}


@mcp.tool()
async def muse_get_image_result(
    task_id: str,
    wait_seconds: int = 90,
    return_image: bool = True,
) -> list:
    """Poll an image-generation task; on completion return Muse's drawings as
    native MCP image content plus local file paths.

    Statuses: pending / approval_required / completed / timeout / failed.
    timeout means Muse is still working — the task is kept, just call this
    again later (optionally wait_seconds>0). Never re-generates on re-poll.
    If status is approval_required, approve the egress card in the Muse app
    (choose "allow always"), then poll again (see docs/auto-approve.md).
    """
    import base64
    import mcp.types as mt

    blocks: list = []
    try:
        result = await _call(_adapter.poll_image_task, task_id, max(0, min(wait_seconds, 240)))
        if result.get("task", {}).get("images"):
            await _call(_download_task_images, task_id, result["task"]["images"])
    except (MuseUnavailable, NotPaired) as exc:
        return [mt.TextContent(type="text", text=_adapter_error_text(exc))]
    task = result.get("task", {})
    status = task.get("status", "unknown")
    meta = {
        "task_id": task_id,
        "status": status,
        "reply": task.get("reply", ""),
        "images": [],
        "error": task.get("error", ""),
    }
    if status == "approval_required":
        meta["approvals"] = task.get("approvals", [])
        meta["hint"] = ("在 Muse app 中批准外联审批（建议选永久允许），批准后任务自动继续，"
                        "再次调用 muse_get_image_result 查询。详见 docs/auto-approve.md")
    if status == "timeout":
        meta["hint"] = ("Muse 仍在生成/等待上传，任务未丢失：稍后再次调用 "
                        "muse_get_image_result(task_id) 即可，不会重新生成。")

    for img in task.get("images", []):
        entry = {"label": img.get("label", ""), "url": img.get("url", ""),
                 "width": img.get("width"), "height": img.get("height"),
                 "path": img.get("path", ""), "inline": False}
        meta["images"].append(entry)
        if not return_image or not img.get("path"):
            continue
        try:
            raw = await _call(_read_file_bytes, img["path"])
            if len(raw) > _MAX_INLINE_BYTES:
                entry["note"] = (f"image too large to inline ({len(raw):,} B > "
                                 f"{_MAX_INLINE_BYTES:,} B); use the local path")
                continue
            blocks.append(mt.ImageContent(
                type="image", data=base64.b64encode(raw).decode(),
                mimeType=img.get("mime") or "image/webp"))
            entry["inline"] = True
        except Exception as exc:  # noqa: BLE001 — one bad download must not kill the batch
            entry["error"] = str(exc)
    blocks.insert(0, mt.TextContent(
        type="text",
        text=json.dumps(meta, ensure_ascii=False, indent=1),
    ))
    return blocks


@mcp.tool()
async def muse_get_images(
    prompt: str,
    session_id: str | None = None,
    timeout: int = 180,
    return_image: bool = True,
) -> list:
    """Convenience: start an image generation, then poll until done (or
    timeout) in one call. Equivalent to muse_start_image_generation followed
    by muse_get_image_result. Prefer the split tools when you want to
    report progress to the user instead of blocking.
    """
    import mcp.types as mt

    started = await muse_start_image_generation.fn(prompt, session_id) \
        if hasattr(muse_start_image_generation, "fn") else \
        await muse_start_image_generation(prompt, session_id)
    if not started.get("ok"):
        return [mt.TextContent(type="text",
                               text=json.dumps(started, ensure_ascii=False))]
    task_id = started["task"]["task_id"]
    return await muse_get_image_result(task_id, wait_seconds=timeout,
                                       return_image=return_image)


@mcp.tool()
async def muse_wait(session_id: str, timeout: int | None = None) -> dict:
    """Not supported by the remote Muse CLI, which couples send+wait.

    Use muse_chat instead: it sends and waits in a single call.
    """
    return {
        "ok": False,
        "error": "standalone wait is not supported by the musegadget CLI; use muse_chat",
    }


@mcp.tool()
async def muse_sessions(label: str = "") -> dict:
    """Create a new Muse side chat for this agent, or list existing ones.

    Call without arguments to list known sessions; pass a label to create a
    fresh side chat (a short purpose, e.g. 'code-review'). Pass its
    session_id to muse_chat/muse_send to keep agent talk out of the main chat.
    """
    if label:
        session_id = _adapter.new_session(label)
        return {"created": session_id, "label": label}
    return {"sessions": _adapter.list_sessions()}


def main() -> None:
    """Entry point: run the MCP server over stdio."""
    if "--status" in sys.argv:  # small debug helper outside MCP
        import json

        try:
            payload = _adapter.status()
        except (MuseUnavailable, NotPaired) as exc:
            payload = {"ready": False, "error": _adapter_error_text(exc)}
        print(json.dumps(payload, indent=2, default=str))
        return
    mcp.run()


if __name__ == "__main__":
    main()
