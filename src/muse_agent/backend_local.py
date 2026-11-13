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
        """First-use checklist: every component needed for a working chat,
        in order, with the exact next command for the first missing one."""
        import shutil

        checks: list[dict] = []

        ok = bool(shutil.which(self.config.bridge_command))
        checks.append({"check": f"runner '{self.config.bridge_command}' on PATH",
                       "ok": ok,
                       "fix": "install bun (curl -fsSL https://bun.sh/install | bash)" if not ok else ""})

        ok = self.script.exists()
        checks.append({"check": "bridge/bridge.mjs present", "ok": ok,
                       "fix": "git clone the repo / restore bridge/" if not ok else ""})

        node_modules = self.script.parent / "node_modules" / "muse-client"
        ok = node_modules.exists()
        checks.append({"check": "bridge dependencies installed (node_modules/muse-client)",
                       "ok": ok,
                       "fix": "cd bridge && bun install" if not ok else ""})

        creds_dir = Path(self.config.credentials_dir) if self.config.credentials_dir else \
            Path.home() / "Library" / "Application Support" / "MuseGadgetPair"
        paired = any((creds_dir / name).exists() for name in ("pairing.json", "credentials.json"))
        token = (Path.home() / ".config" / "muse-agent" / "sdk_token").exists()
        checks.append({"check": "paired with Muse (credentials present)",
                       "ok": paired,
                       "fix": ("run `bun bridge/bridge.mjs pair` (docs/pairing.md)"
                               if token else
                               "save your SDK token to ~/.config/muse-agent/sdk_token, "
                               "then run `bun bridge/bridge.mjs pair`")})

        connection: dict | None = None
        if paired and checks[0]["ok"] and checks[1]["ok"] and checks[2]["ok"]:
            try:
                connection = self.status()
                checks.append({"check": "connection to Muse VM", "ok": bool(connection.get("ready")),
                               "fix": "" if connection.get("ready") else str(connection.get("error", "connection failed"))})
            except LocalBackendError as exc:
                checks.append({"check": "connection to Muse VM", "ok": False, "fix": str(exc)})

        all_ok = all(c["ok"] for c in checks)
        return {"ok": all_ok,
                "ready": bool(connection and connection.get("ready")),
                "checks": checks,
                "next": next((c["fix"] for c in checks if not c["ok"]), "")}

    def _session(self, session_id: str | None) -> list[str]:
        return ["--session", session_id] if session_id else []
