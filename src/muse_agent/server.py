"""MCP stdio server exposing Muse tools to coding agents."""

from __future__ import annotations

import asyncio
import sys

from mcp.server.fastmcp import FastMCP

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
async def muse_get_images(
    prompt: str | None = None,
    session_id: str | None = None,
    timeout: int | None = None,
) -> dict:
    """Ask Muse to generate images and get them back as downloadable files.

    prompt describes what to draw (default: re-share its latest generated
    media as public links). Muse renders via its generate_image tool; this
    tool waits for the reply, extracts the public muse.ai/files URLs from
    the presentation events, downloads each to a local temp file, and
    returns the file paths. Local backend only.
    """
    import tempfile
    import urllib.request

    try:
        payload = await _call(_adapter.get_images, prompt, session_id, timeout)
    except (MuseUnavailable, NotPaired) as exc:
        return {"ok": False, "error": _adapter_error_text(exc)}
    if not payload.get("ok"):
        return {"ok": False, "error": payload.get("error", "image collection failed")}
    saved = []
    for img in payload.get("images", []):
        url = img.get("url")
        if not url:
            continue
        try:
            def _download(u=url):
                import urllib.request as ur
                req = ur.Request(u, headers={"User-Agent": "muse-agent/0.1"})
                with ur.urlopen(req, timeout=60) as resp, tempfile.NamedTemporaryFile(
                        suffix=".webp", delete=False) as f:
                    f.write(resp.read())
                    return f.name
            path = await _call(_download)
            saved.append({"path": path, "label": img.get("label", ""),
                          "url": url, "width": img.get("width"), "height": img.get("height")})
        except Exception as exc:  # noqa: BLE001 — one bad URL must not kill the batch
            saved.append({"url": url, "error": str(exc)})
    return {"ok": True, "reply": payload.get("reply", ""),
            "note": "sandbox 里的原图链接外部不可达；这里返回的是 Muse 转存的公网直链与本地落盘路径",
            "images": saved}


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
