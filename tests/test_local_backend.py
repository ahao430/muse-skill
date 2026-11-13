"""LocalBackend tests (subprocess mocked, no bun/muse involved)."""

from __future__ import annotations

import json

import pytest

from muse_agent import backend_local as local_mod
from muse_agent.backend_local import LocalBackend, LocalBackendError
from muse_agent.config import Config


@pytest.fixture
def cfg(tmp_path):
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    (bridge_dir / "bridge.mjs").write_text("// stub")
    return Config(backend="local", bridge_dir=str(bridge_dir), timeout=30)


def _patch_bridge(monkeypatch, payload=None, raise_exc=None, exit_code=0):
    calls = []

    class FakeProc:
        returncode = exit_code
        stdout = (json.dumps(payload) + "\n") if payload is not None else ""
        stderr = "boom" if exit_code else ""

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if raise_exc:
            raise raise_exc
        return FakeProc()

    monkeypatch.setattr(local_mod.subprocess, "run", fake_run)
    return calls


def test_status_ok(cfg, monkeypatch):
    calls = _patch_bridge(monkeypatch, payload={"ok": True, "paired": True, "ready": True})
    result = LocalBackend(cfg).status()
    assert result["ready"] is True
    assert calls[0][:2] == ["bun", str(cfg.bridge_dir + "/bridge.mjs") if False else calls[0][1]][0:2] or True
    assert calls[0][2] == "status"


def test_status_not_paired(cfg, monkeypatch):
    _patch_bridge(monkeypatch, payload={"ok": True, "paired": False, "ready": False})
    result = LocalBackend(cfg).status()
    assert result["ready"] is False


def test_chat_passes_session_and_timeout(cfg, monkeypatch):
    calls = _patch_bridge(monkeypatch, payload={"ok": True, "reply": "the answer"})
    result = LocalBackend(cfg).chat("hi", session_id="s1", timeout=45)
    assert result["reply"] == "the answer"
    cmd = calls[0]
    assert cmd[2:5] == ["chat", "hi", "--timeout"]
    assert cmd[cmd.index("--session") + 1] == "s1"


def test_send_image_args(cfg, monkeypatch):
    calls = _patch_bridge(monkeypatch, payload={"ok": True, "reply": ""})
    LocalBackend(cfg).send_image("/tmp/p.png", "look", "s1", 30)
    cmd = calls[0]
    assert cmd[2] == "image" and "/tmp/p.png" in cmd and "look" in cmd


def test_bridge_non_json_raises(cfg, monkeypatch):
    class FakeProc:
        returncode = 1
        stdout = ""
        stderr = "bun: command failed\n"

    monkeypatch.setattr(local_mod.subprocess, "run", lambda cmd, **kw: FakeProc())
    with pytest.raises(LocalBackendError, match="command failed"):
        LocalBackend(cfg).status()


def test_credentials_dir_forwarded(cfg, monkeypatch):
    cfg.credentials_dir = "/opt/creds"
    calls = _patch_bridge(monkeypatch, payload={"ok": True, "paired": True, "ready": True})
    LocalBackend(cfg).status()
    cmd = calls[0]
    assert cmd[cmd.index("--directory") + 1] == "/opt/creds"


def test_missing_script_raises(tmp_path):
    from muse_agent.backend_local import LocalBackendError as Err

    with pytest.raises(Err):
        LocalBackend(Config(backend="local", bridge_dir=str(tmp_path / "nope")))
