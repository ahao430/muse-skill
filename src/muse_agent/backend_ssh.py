"""SSH backend: drive the remote musegadget service on the gadget host.

Remote surface (official SDK CLI):
  musegadget info                                   identity + pairing state
  musegadget doctor                                 setup health check
  musegadget send-user-msg - --session-id S --wait N  message via stdin, optional wait
    exit 0: answer on stdout; exit 3: sent but no/partial answer; exit 1: not delivered.

All methods return plain dicts shaped like bridge/bridge.mjs output:
  {"ok": bool, "reply"?: str, "detail"?: str, ...}
"""

from __future__ import annotations

import os
import subprocess
import uuid

from .config import Config
from .ssh import SSHError, run_ssh

MAX_WAIT = 600  # official SDK cap for --wait


class MuseUnavailable(RuntimeError):
    """The gadget host or musegadget service is not usable."""


class NotPaired(RuntimeError):
    """The gadget host has no pairing yet; see docs/pairing.md."""


class SshBackend:
    def __init__(self, config: Config):
        self.config = config

    # -- Backend API ---------------------------------------------------------

    def status(self) -> dict:
        out = self._run(["musegadget", "info"], timeout=20)
        info = self._parse_info(out)
        try:
            svc = self._run(["systemctl", "is-active", "musegadget"], timeout=15).strip()
        except SSHError:
            svc = "unknown"
        paired = info.get("paired") is True
        return {
            "ok": True,
            "host": self.config.host,
            "service": svc,
            "paired": paired,
            "identity": info,
            "ready": paired and svc in ("active", "unknown"),
        }

    def send(self, message: str, session_id: str | None) -> dict:
        args = ["musegadget", "send-user-msg", "-"]
        if session_id:
            args += ["--session-id", session_id]
        try:
            run_ssh(self.config.host, args, timeout=60,
                    connect_timeout=self.config.connect_timeout, stdin_text=message)
        except SSHError as exc:
            if exc.returncode == 3:
                return {"ok": True, "detail": "sent, but no answer was available"}
            return {"ok": False, "detail": str(exc)}
        return {"ok": True, "detail": "sent to Muse"}

    def chat(self, message: str, session_id: str | None, timeout: int) -> dict:
        seconds = min(max(timeout, 1), MAX_WAIT)
        args = ["musegadget", "send-user-msg", "-", "--wait", str(seconds)]
        if session_id:
            args += ["--session-id", session_id]
        try:
            out = run_ssh(self.config.host, args, timeout=seconds + 60,
                          connect_timeout=self.config.connect_timeout, stdin_text=message)
        except SSHError as exc:
            if exc.returncode == 3:
                # Sent, but no (complete) answer; stderr detail folded into the error.
                return {"ok": True, "detail": str(exc)}
            return {"ok": False, "detail": str(exc)}
        return {"ok": True, "reply": out.strip()}

    def send_image(self, image_path: str, message: str, session_id: str | None,
                   timeout: int | None) -> dict:
        """scp the image to the host, send with --image, remove it after."""
        path = os.path.expanduser(image_path)
        if not os.path.isfile(path):
            return {"ok": False, "detail": f"no such file: {path}"}
        if os.path.getsize(path) > 2 * 1024 * 1024:
            return {"ok": False, "detail": "image exceeds the 2 MiB limit"}
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
            return {"ok": False, "detail": f"unsupported type .{ext} (JPEG/PNG/GIF/WebP only)"}

        remote_file = f"/tmp/muse-agent-img-{uuid.uuid4().hex[:8]}.{ext}"
        scp_cmd = [
            "scp", "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={self.config.connect_timeout}",
            path, f"{self.config.host}:{remote_file}",
        ]
        proc = subprocess.run(scp_cmd, capture_output=True, text=True,
                              timeout=self.config.connect_timeout + 60)
        if proc.returncode != 0:
            return {"ok": False, "detail": f"scp failed: {(proc.stderr or '').strip()}"}
        try:
            args = ["musegadget", "send-user-msg", "-", "--image", remote_file]
            if timeout:
                args += ["--wait", str(min(max(timeout, 1), MAX_WAIT))]
            if session_id:
                args += ["--session-id", session_id]
            try:
                out = run_ssh(self.config.host, args, timeout=(timeout or 60) + 60,
                              connect_timeout=self.config.connect_timeout, stdin_text=message)
            except SSHError as exc:
                if exc.returncode == 3:
                    return {"ok": True, "detail": str(exc)}
                return {"ok": False, "detail": str(exc)}
            return {"ok": True, "reply": out.strip()}
        finally:
            subprocess.run(
                ["ssh", "-o", "BatchMode=yes", self.config.host, "--", "rm", "-f", remote_file],
                capture_output=True, timeout=30,
            )

    def doctor(self) -> dict:
        try:
            out = self._run(["musegadget", "doctor"], timeout=60)
        except (MuseUnavailable, NotPaired) as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "report": out.strip()}

    # -- internals ----------------------------------------------------------

    def _run(self, remote_args: list[str], timeout: int) -> str:
        try:
            return run_ssh(self.config.host, remote_args, timeout=timeout,
                           connect_timeout=self.config.connect_timeout)
        except SSHError as exc:
            msg = str(exc)
            if "Not paired" in msg or "not paired" in msg:
                raise NotPaired("gadget host is not paired yet — follow docs/pairing.md") from exc
            raise MuseUnavailable(msg) from exc

    @staticmethod
    def _parse_info(text: str) -> dict:
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
