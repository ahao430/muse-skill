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
        return _to_send_result(self.backend.chat(message, session_id, seconds))

    def wait(self, session_id: str, timeout: int | None = None) -> SendResult:
        """Not supported: both backends couple send+wait in one call."""
        raise NotImplementedError("standalone wait is unsupported; use muse_chat")

    def send_image(self, image_path: str, message: str = "",
                   session_id: str | None = None, timeout: int | None = None) -> SendResult:
        return _to_send_result(self.backend.send_image(image_path, message, session_id, timeout))

    def doctor(self) -> dict:
        return self.backend.doctor()

    # -- sessions -----------------------------------------------------------

    def new_session(self, label: str = "") -> str:
        session_id = f"muse-agent-{uuid.uuid4().hex[:12]}"
        sessions = cfg.load_sessions()
        sessions[session_id] = {"label": label}
        cfg.save_sessions(sessions)
        return session_id

    def list_sessions(self) -> list[dict]:
        sessions = cfg.load_sessions()
        return [{"session_id": sid, **meta} for sid, meta in sessions.items()]
