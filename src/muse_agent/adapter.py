"""GadgetAdapter: talk to the remote musegadget service over SSH.

Remote surface (official SDK CLI):
  musegadget info                                   identity + pairing state
  musegadget doctor                                 setup health check
  musegadget send-user-msg - --session-id S --wait N  message via stdin, optional wait
    exit 0: answer on stdout; exit 3: sent but no/partial answer; exit 1: not delivered.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from . import config as cfg
from .ssh import SSHError, run_ssh

MAX_WAIT = 600  # official SDK cap for --wait


class MuseUnavailable(RuntimeError):
    """The remote gadget host or musegadget service is not usable."""


class NotPaired(RuntimeError):
    """The gadget host has no pairing yet; see docs/pairing.md."""


@dataclass
class SendResult:
    ok: bool
    text: str = ""
    detail: str = ""


class GadgetAdapter:
    def __init__(self, config: cfg.Config | None = None):
        self.config = config or cfg.load_config()

    # -- status -----------------------------------------------------------

    def status(self) -> dict:
        out = self._run(["musegadget", "info"], timeout=20)
        info = self._parse_info(out)
        try:
            svc = self._run(
                ["systemctl", "is-active", "musegadget"], timeout=15
            ).strip()
        except SSHError:
            svc = "unknown"
        paired = info.get("paired") is True
        return {
            "host": self.config.host,
            "service": svc,
            "paired": paired,
            "identity": info,
            "ready": paired and svc in ("active", "unknown"),
        }

    # -- messaging ----------------------------------------------------------

    def send(self, message: str, session_id: str | None = None) -> SendResult:
        """Fire-and-forget send. Returns delivery status only."""
        args = ["musegadget", "send-user-msg", "-"]
        if session_id:
            args += ["--session-id", session_id]
        try:
            run_ssh(
                self.config.host, args,
                timeout=60, connect_timeout=self.config.connect_timeout,
                stdin_text=message,
            )
        except SSHError as exc:
            if exc.returncode == 3:
                return SendResult(ok=True, detail="sent, but no answer was available")
            return SendResult(ok=False, detail=str(exc))
        return SendResult(ok=True, detail="sent to Muse")

    def wait(self, session_id: str, timeout: int | None = None) -> SendResult:
        """Wait for the next answer in a chat without sending anything.

        The remote CLI couples send+wait into one call, so a standalone wait
        cannot be forwarded faithfully; we surface that instead of pretending.
        Use chat() for send-and-wait.
        """
        raise NotImplementedError(
            "the remote CLI only supports send+wait in one call; use muse_chat"
        )

    def chat(self, message: str, session_id: str | None = None,
             timeout: int | None = None) -> SendResult:
        """Send and wait for Muse's full answer."""
        seconds = min(max(timeout or self.config.timeout, 1), MAX_WAIT)
        return self._send_wait(message, session_id, seconds)

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

    def _send_wait(self, message: str, session_id: str | None, seconds: int) -> SendResult:
        args = ["musegadget", "send-user-msg", "-", "--wait", str(seconds)]
        if session_id:
            args += ["--session-id", session_id]
        try:
            out = run_ssh(
                self.config.host, args,
                timeout=seconds + 60, connect_timeout=self.config.connect_timeout,
                stdin_text=message,
            )
        except SSHError as exc:
            if exc.returncode == 3:
                # Sent, but no (complete) answer. stderr detail is folded into
                # the SSHError message; surface it as a partial result.
                return SendResult(ok=True, detail=str(exc))
            return SendResult(ok=False, detail=str(exc))
        return SendResult(ok=True, text=out.strip())

    def _wait_poll(self, session_id: str, seconds: int) -> SendResult:
        raise NotImplementedError(
            "standalone wait is not supported by the remote CLI; use muse_chat"
        )

    def _run(self, remote_args: list[str], timeout: int) -> str:
        try:
            return run_ssh(
                self.config.host, remote_args,
                timeout=timeout, connect_timeout=self.config.connect_timeout,
            )
        except SSHError as exc:
            msg = str(exc)
            if "Not paired" in msg or "not paired" in msg:
                raise NotPaired(
                    "gadget host is not paired yet — follow docs/pairing.md"
                ) from exc
            raise MuseUnavailable(msg) from exc

    @staticmethod
    def _parse_info(text: str) -> dict:
        """Parse `musegadget info` key/value output into a dict."""
        info: dict = {}
        for line in text.splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key, value = key.strip().lower().replace(" ", "_"), value.strip()
            if key == "paired":
                info["paired"] = value.lower() in ("yes", "true", "paired")
            elif key:
                info[key] = value
        return info
