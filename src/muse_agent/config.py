"""Configuration for the Muse agent MCP server.

Settings come from (highest priority first):
  1. Environment variables (MUSE_AGENT_HOST, MUSE_AGENT_TIMEOUT)
  2. ~/.config/muse-agent/config.yaml  (simple flat keys, parsed without PyYAML)
  3. Defaults

The YAML is intentionally minimal: flat ``key: value`` lines only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("MUSE_AGENT_CONFIG_DIR", "~/.config/muse-agent")).expanduser()
CONFIG_FILE = CONFIG_DIR / "config.yaml"
SESSIONS_FILE = CONFIG_DIR / "sessions.json"
BRIDGE_DIR = Path(__file__).resolve().parent.parent.parent / "bridge"

DEFAULT_HOST = "root@2607:9d00:2000:143::31b0:2854"  # ssh syntax: bare IPv6, no brackets
DEFAULT_TIMEOUT = 120  # seconds; muse chat caps at 600


@dataclass
class Config:
    backend: str = "local"  # "local" (muse-client on this Mac) | "ssh" (remote musegadget)
    host: str = DEFAULT_HOST
    timeout: int = DEFAULT_TIMEOUT
    connect_timeout: int = 10
    default_session: str | None = None  # None = main chat
    bridge_command: str = "bun"  # runner for bridge/bridge.mjs (local backend)
    bridge_dir: str = str(BRIDGE_DIR)
    bridge_proxy: str = ""      # e.g. http://127.0.0.1:7897 — routes the bridge
    #                          # through an HTTP proxy via node+global-agent
    #                          # (bun's proxied WebSocket is broken)
    credentials_dir: str | None = None  # muse-client credentials dir override
    # COS media relay: Mac holds the keys, Muse only receives presigned URLs.
    cos_bucket_domain: str = ""       # e.g. muse-1300xxx.cos.ap-guangzhou.myqcloud.com
    cos_secret_id: str = ""
    cos_secret_key: str = ""
    sessions: dict[str, dict] = field(default_factory=dict)  # side chat bookkeeping

    @property
    def media_domain(self) -> str:
        return self.cos_bucket_domain

    @property
    def cos_relay_ready(self) -> bool:
        return bool(self.cos_bucket_domain and self.cos_secret_id and self.cos_secret_key)


def _parse_flat_yaml(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def load_config() -> Config:
    cfg = Config()
    file_values = _parse_flat_yaml(CONFIG_FILE)
    if "backend" in file_values:
        cfg.backend = file_values["backend"]
    if "host" in file_values:
        cfg.host = file_values["host"]
    if "bridge_command" in file_values:
        cfg.bridge_command = file_values["bridge_command"]
    if "bridge_dir" in file_values:
        cfg.bridge_dir = file_values["bridge_dir"]
    if "credentials_dir" in file_values and file_values["credentials_dir"]:
        cfg.credentials_dir = file_values["credentials_dir"]
    if "bridge_proxy" in file_values and file_values["bridge_proxy"]:
        cfg.bridge_proxy = file_values["bridge_proxy"]
    for field in ("cos_bucket_domain", "cos_secret_id", "cos_secret_key"):
        if field in file_values and file_values[field]:
            setattr(cfg, field, file_values[field])
    if "timeout" in file_values:
        try:
            cfg.timeout = int(file_values["timeout"])
        except ValueError:
            pass
    if "connect_timeout" in file_values:
        try:
            cfg.connect_timeout = int(file_values["connect_timeout"])
        except ValueError:
            pass
    if "default_session" in file_values and file_values["default_session"] not in ("", "main"):
        cfg.default_session = file_values["default_session"]
    cfg.host = os.environ.get("MUSE_AGENT_HOST", cfg.host)
    cfg.backend = os.environ.get("MUSE_AGENT_BACKEND", cfg.backend)
    if "MUSE_AGENT_TIMEOUT" in os.environ:
        try:
            cfg.timeout = int(os.environ["MUSE_AGENT_TIMEOUT"])
        except ValueError:
            pass
    return cfg


def load_sessions() -> dict[str, dict]:
    import json

    if SESSIONS_FILE.exists():
        try:
            data = json.loads(SESSIONS_FILE.read_text())
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_sessions(sessions: dict[str, dict]) -> None:
    import json

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_FILE.write_text(json.dumps(sessions, indent=2, ensure_ascii=False))
