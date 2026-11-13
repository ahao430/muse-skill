"""SshBackend tests (ssh output mocked, no network)."""

from __future__ import annotations

import pytest

from muse_agent import backend_ssh as ssh_mod
from muse_agent.backend_ssh import MuseUnavailable, NotPaired, SshBackend
from muse_agent.config import Config
from muse_agent.ssh import SSHError


@pytest.fixture
def cfg():
    return Config(backend="ssh", host="test@example.com", timeout=30, connect_timeout=5)


def test_send_ok(cfg, monkeypatch):
    calls = []

    def fake_run_ssh(host, remote_args, **kw):
        calls.append((host, remote_args, kw))
        return "Sent to your Muse.\n"

    monkeypatch.setattr(ssh_mod, "run_ssh", fake_run_ssh)
    result = SshBackend(cfg).send("hello", None)
    assert result["ok"]
    host, args, kw = calls[0]
    assert host == "test@example.com"
    assert args == ["musegadget", "send-user-msg", "-"]
    assert kw["stdin_text"] == "hello"


def test_chat_ok(cfg, monkeypatch):
    def fake_run_ssh(host, remote_args, **kw):
        assert "--wait" in remote_args
        assert kw["stdin_text"] == "hi"
        return "Muse says hello back\n"

    monkeypatch.setattr(ssh_mod, "run_ssh", fake_run_ssh)
    result = SshBackend(cfg).chat("hi", session_id="muse-agent-abc", timeout=10)
    assert result["ok"] and result["reply"] == "Muse says hello back"


def test_chat_timeout_caps_at_600(cfg, monkeypatch):
    seen = {}

    def fake_run_ssh(host, remote_args, **kw):
        seen["args"] = remote_args
        return "answer"

    monkeypatch.setattr(ssh_mod, "run_ssh", fake_run_ssh)
    SshBackend(cfg).chat("hi", None, timeout=9999)
    assert seen["args"][seen["args"].index("--wait") + 1] == "600"


def test_chat_exit3_is_partial_success(cfg, monkeypatch):
    def fake_run_ssh(host, remote_args, **kw):
        raise SSHError("remote command failed: Muse was still answering", 3)

    monkeypatch.setattr(ssh_mod, "run_ssh", fake_run_ssh)
    result = SshBackend(cfg).chat("hi", None, 30)
    assert result["ok"] and "still answering" in result["detail"]


def test_chat_failure(cfg, monkeypatch):
    monkeypatch.setattr(
        ssh_mod, "run_ssh",
        lambda *a, **k: (_ for _ in ()).throw(SSHError("Permission denied", 255)),
    )
    result = SshBackend(cfg).chat("hi", None, 30)
    assert not result["ok"]


def test_status_not_paired(cfg, monkeypatch):
    monkeypatch.setattr(
        ssh_mod, "run_ssh",
        lambda *a, **k: (_ for _ in ()).throw(
            SSHError("Not paired; run `musegadget pair` first.", 1)),
    )
    with pytest.raises(NotPaired):
        SshBackend(cfg).status()


def test_status_unreachable(cfg, monkeypatch):
    monkeypatch.setattr(
        ssh_mod, "run_ssh",
        lambda *a, **k: (_ for _ in ()).throw(SSHError("Connection timed out", 255)),
    )
    with pytest.raises(MuseUnavailable):
        SshBackend(cfg).status()


def test_status_parses_info(cfg, monkeypatch):
    def fake_run_ssh(host, remote_args, **kw):
        if remote_args[1] == "info":
            return "Identity: homelink-ab12cd\nPaired: yes\nBLE name: MuseGadgetAB12CD\n"
        return "active\n"

    monkeypatch.setattr(ssh_mod, "run_ssh", fake_run_ssh)
    status = SshBackend(cfg).status()
    assert status["paired"] is True
    assert status["service"] == "active"
    assert status["ready"] is True
    assert status["identity"]["identity"] == "homelink-ab12cd"
