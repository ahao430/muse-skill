"""Local backend: drive muse-client through bridge/bridge.mjs (bun)."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .backend_ssh import MuseUnavailable
from .config import Config


class LocalBackendError(MuseUnavailable):
    """The bridge failed to run or returned invalid output."""


@dataclass
class LocalResult:
    payload: dict


class LocalBackend:
    """Runs `bun bridge/bridge.mjs <cmd> --json-ish` and parses its JSON line."""

    def __init__(self, config: Config):
        self.config = config
        self.script = Path(config.bridge_dir) / "bridge.mjs"
        if not self.script.exists():
            raise LocalBackendError(f"bridge script not found: {self.script}")

    def _run(self, args: list[str], timeout: int) -> dict:
        cmd = [self.config.bridge_command, str(self.script), *args]
        if self.config.credentials_dir:
            cmd += ["--directory", self.config.credentials_dir]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout + 15,
            )
        except FileNotFoundError as exc:
            raise LocalBackendError(
                f"{self.config.bridge_command!r} not found — install bun or set bridge_command"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise LocalBackendError(f"bridge timed out after {timeout + 15}s") from exc
        line = (proc.stdout or "").strip().splitlines()
        if not line:
            detail = (proc.stderr or "").strip().splitlines()
            raise LocalBackendError(detail[-1] if detail else f"bridge exit {proc.returncode}")
        try:
            payload = json.loads(line[-1])
        except json.JSONDecodeError as exc:
            raise LocalBackendError(f"bridge output not JSON: {line[-1][:200]}") from exc
        return payload

    # -- Backend API ---------------------------------------------------------

    def status(self) -> dict:
        payload = self._run(["status"], timeout=30)
        if not payload.get("ok"):
            raise LocalBackendError(payload.get("error", "status failed"))
        return payload

    def send(self, message: str, session_id: str | None) -> dict:
        args = ["send", message] + self._session(session_id)
        return self._run(args, timeout=90)

    def chat(self, message: str, session_id: str | None, timeout: int) -> dict:
        args = ["chat", message, "--timeout", str(timeout)] + self._session(session_id)
        return self._run(args, timeout=timeout + 60)

    def send_image(self, image_path: str, message: str, session_id: str | None, timeout: int | None) -> dict:
        args = ["image", image_path]
        if message:
            args.append(message)
        if timeout:
            args += ["--timeout", str(timeout)]
        args += self._session(session_id)
        return self._run(args, timeout=(timeout or 120) + 60)

    def doctor(self) -> dict:
        payload = self.status()
        return {
            "ok": True,
            "report": (
                "credentials present, connection ok" if payload.get("ready")
                else "not paired yet — run `bun bridge/bridge.mjs pair` (docs/pairing.md)"
            ),
        }

    def _session(self, session_id: str | None) -> list[str]:
        return ["--session", session_id] if session_id else []
