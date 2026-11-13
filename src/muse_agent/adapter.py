"""GadgetAdapter: one API over two backends.

- "local": muse-client (TypeScript) on this machine, via bridge/bridge.mjs —
  pairing and chat both run locally on macOS (recommended).
- "ssh": the official musegadget service on an always-on Linux gadget host.

Sessions (side-chat bookkeeping) are backend-independent local state.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from . import config as cfg
from .backend_ssh import MuseUnavailable, NotPaired  # re-exported for server

MAX_WAIT = 600


@dataclass
class SendResult:
    ok: bool
    text: str = ""
    detail: str = ""


def _to_send_result(payload: dict) -> SendResult:
    if payload.get("ok") and payload.get("error"):
        payload = {"ok": False, "detail": payload["error"]}
    return SendResult(
        ok=bool(payload.get("ok")),
        text=str(payload.get("reply", "")),
        detail=str(payload.get("detail", "") or payload.get("error", "")),
    )


class GadgetAdapter:
    def __init__(self, config: cfg.Config | None = None):
        self.config = config or cfg.load_config()
        from .tasks import TaskStore
        self._tasks = TaskStore()
        if self.config.backend == "ssh":
            from .backend_ssh import SshBackend
            self.backend = SshBackend(self.config)
        else:
            from .backend_local import LocalBackend, LocalBackendError
            try:
                self.backend = LocalBackend(self.config)
            except LocalBackendError as exc:
                raise MuseUnavailable(str(exc)) from exc

    # -- status -----------------------------------------------------------

    def status(self) -> dict:
        status = dict(self.backend.status())
        status["backend"] = self.config.backend
        if not status.get("ready"):
            status["hint"] = (
                "pair on this Mac: `bun bridge/bridge.mjs pair` (docs/pairing.md)"
                if self.config.backend == "local"
                else "check the gadget host / docs/pairing.md"
            )
        return status

    # -- messaging ----------------------------------------------------------

    def send(self, message: str, session_id: str | None = None) -> SendResult:
        return _to_send_result(self.backend.send(message, session_id))

    def chat(self, message: str, session_id: str | None = None,
             timeout: int | None = None) -> SendResult:
        seconds = min(max(timeout or self.config.timeout, 1), MAX_WAIT)
        return _to_send_result(self.backend.chat(message, self._resolve(session_id), seconds))

    def wait(self, session_id: str, timeout: int | None = None) -> SendResult:
        """Not supported: both backends couple send+wait in one call."""
        raise NotImplementedError("standalone wait is unsupported; use muse_chat")

    def send_image(self, image_path: str, message: str = "",
                   session_id: str | None = None, timeout: int | None = None) -> SendResult:
        return _to_send_result(self.backend.send_image(image_path, message,
                                                       self._resolve(session_id), timeout))

    def get_images(self, prompt: str | None = None, session_id: str | None = None,
                   timeout: int | None = None) -> dict:
        """Generate-and-fetch: ask Muse to produce media and return public links.

        Local backend only — the ssh backend's musegadget CLI has no media
        collection channel. Returns {"ok", "reply", "images": [{url, label…}]}.
        """
        if self.config.backend != "local":
            return {"ok": False,
                    "error": "muse_get_images requires backend: local (the ssh backend has no media channel)"}
        session = self._resolve(session_id)
        seconds = min(max(timeout or 240, 30), 600)
        return self.backend.images(prompt, session, seconds)

    # -- image generation tasks ---------------------------------------------

    def start_image_task(self, prompt: str, session_id: str | None = None) -> dict:
        """Submit an image-generation request; returns the task record at once.

        Does NOT wait for Muse: the MCP call stays fast, results are polled
        via poll_image_task(). Local backend only.
        """
        if self.config.backend != "local":
            return {"ok": False,
                    "error": "image generation requires backend: local "
                             "(the ssh backend's musegadget CLI has no media channel)"}
        session = self._resolve(session_id)
        task = self._tasks.create(prompt, session)
        return {"ok": True, "task": task}

    def poll_image_task(self, task_id: str, wait_seconds: int = 90) -> dict:
        """Poll a task: if still pending, wait up to wait_seconds inside the
        bridge (single long subscribe) and return the freshest state.

        Timeout is a STATE, not an error: the task is kept and re-pollable.
        """
        if self.config.backend != "local":
            return {"ok": False, "error": "local backend required"}
        task = self._tasks.get(task_id)
        if task is None:
            return {"ok": False, "error": f"unknown task_id {task_id!r}"}
        if task["status"] == "failed":
            return {"ok": True, "task": task}
        if task["status"] == "completed" and task.get("images"):
            return {"ok": True, "task": task}
        # completed-without-images falls through: Muse presentations can
        # arrive late (or be re-presented on request), so re-polls absorb
        # newly seen links instead of short-circuiting on the old state.
        # First poll delivers the original prompt; later polls must NOT
        # regenerate and must NOT re-upload (each upload burns an egress
        # approval) — just ask Muse to re-present the existing file card.
        message = task["prompt"]
        if task.get("sent_prompt"):
            message = ("请把刚才生成图片的 muse.ai/files 文件卡片链接再发一次"
                       "（贴在回复里即可，不要重新上传，不要重新画）。")
        self._tasks.update(task_id, sent_prompt=True, status="pending")
        try:
            payload = self.backend.images(message, task["session_id"], wait_seconds)
        except Exception as exc:  # noqa: BLE001 — bridge crash must not lose the task
            self._tasks.update(task_id, status="timeout",
                               error=f"bridge error: {exc}")
            return {"ok": True, "task": self._tasks.get(task_id)}

        if not payload.get("ok"):
            self._tasks.update(task_id, status="failed", error=str(payload.get("error", "")))
            return {"ok": True, "task": self._tasks.get(task_id)}

        updates: dict = {}
        approvals = payload.get("approvals") or []
        images = payload.get("images") or []
        if approvals and not images:
            updates["status"] = "approval_required"
            updates["approvals"] = approvals
        elif images:
            self._tasks.add_images(task_id, images)
            updates["status"] = "completed"
            updates["reply"] = payload.get("reply", "")
            updates["approvals"] = approvals
        elif payload.get("status") == "timeout":
            updates["status"] = "timeout"
            updates["reply"] = payload.get("reply", "")
        elif payload.get("status") == "failed":
            updates["status"] = "failed"
            updates["error"] = payload.get("detail", "")
        else:
            # completed turn, no images, no approvals — Muse answered without media
            updates["status"] = "completed"
            updates["reply"] = payload.get("reply", "")
        if payload.get("reply") and not updates.get("reply"):
            updates["reply"] = payload["reply"]
        self._tasks.update(task_id, **updates)
        return {"ok": True, "task": self._tasks.get(task_id)}

    def doctor(self) -> dict:
        return self.backend.doctor()

    # -- sessions -----------------------------------------------------------

    def _resolve(self, session_id: str | None) -> str | None:
        """Resolve the session to chat in. Main chat replies can't be proven
        bound to a programmatic request, so the agent always talks in its own
        persistent side chat (auto-provisioned on first use)."""
        if session_id:
            return session_id
        sessions = cfg.load_sessions()
        default = sessions.get("_default")
        if default and isinstance(default, dict) and default.get("session_id"):
            return default["session_id"]
        new_id = str(uuid.uuid4())
        sessions["_default"] = {"label": "agent default", "session_id": new_id}
        cfg.save_sessions(sessions)
        return new_id

    def new_session(self, label: str = "") -> str:
        # Muse requires side-chat ids to be UUIDs; anything else 400s.
        session_id = str(uuid.uuid4())
        sessions = cfg.load_sessions()
        sessions[session_id] = {"label": label}
        cfg.save_sessions(sessions)
        return session_id

    def list_sessions(self) -> list[dict]:
        sessions = cfg.load_sessions()
        return [{"session_id": m.get("session_id", sid), "label": m.get("label", ""), **m}
                for sid, m in sessions.items() if sid != "_default"]
