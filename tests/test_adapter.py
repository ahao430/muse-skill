"""Unit tests for the SSH adapter (no network; ssh output is mocked)."""

from __future__ import annotations

import pytest

from muse_agent import adapter as adapter_mod
from muse_agent.adapter import GadgetAdapter, MuseUnavailable, NotPaired
from muse_agent.config import Config
from muse_agent.ssh import SSHError


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter_mod.cfg, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(adapter_mod.cfg, "SESSIONS_FILE", tmp_path / "sessions.json")
    return Config(host="test@example.com", timeout=30, connect_timeout=5)


def test_send_ok(cfg, monkeypatch):
    calls = []

    def fake_run_ssh(host, remote_args, **kw):
        calls.append((host, remote_args, kw))
        return "Sent to your Muse.\n"

    monkeypatch.setattr(adapter_mod, "run_ssh", fake_run_ssh)
    ad = GadgetAdapter(cfg)
    result = ad.send("hello")
    assert result.ok
    host, args, kw = calls[0]
    assert host == "test@example.com"
    assert args == ["musegadget", "send-user-msg", "-"]
    assert kw["stdin_text"] == "hello"


def test_chat_ok(cfg, monkeypatch):
    def fake_run_ssh(host, remote_args, **kw):
        assert "--wait" in remote_args
        assert kw["stdin_text"] == "hi"
        return "Muse says hello back\n"

    monkeypatch.setattr(adapter_mod, "run_ssh", fake_run_ssh)
    ad = GadgetAdapter(cfg)
    result = ad.chat("hi", session_id="muse-agent-abc", timeout=10)
    assert result.ok and result.text == "Muse says hello back"


def test_chat_timeout_caps_at_600(cfg, monkeypatch):
    seen = {}

    def fake_run_ssh(host, remote_args, **kw):
        seen["args"] = remote_args
        return "answer"

    monkeypatch.setattr(adapter_mod, "run_ssh", fake_run_ssh)
    ad = GadgetAdapter(cfg)
    ad.chat("hi", timeout=9999)
    assert seen["args"][seen["args"].index("--wait") + 1] == "600"


def test_chat_exit3_is_partial_success(cfg, monkeypatch):
    def fake_run_ssh(host, remote_args, **kw):
        raise SSHError("remote command failed: Muse was still answering", 3)

    monkeypatch.setattr(adapter_mod, "run_ssh", fake_run_ssh)
    ad = GadgetAdapter(cfg)
    result = ad.chat("hi")
    assert result.ok and "still answering" in result.detail


def test_chat_failure(cfg, monkeypatch):
    monkeypatch.setattr(
        adapter_mod, "run_ssh",
        lambda *a, **k: (_ for _ in ()).throw(SSHError("Permission denied", 255)),
    )
    ad = GadgetAdapter(cfg)
    result = ad.chat("hi")
    assert not result.ok


def test_status_not_paired(cfg, monkeypatch):
    monkeypatch.setattr(
        adapter_mod, "run_ssh",
        lambda *a, **k: (_ for _ in ()).throw(SSHError("Not paired; run `musegadget pair` first.", 1)),
    )
    ad = GadgetAdapter(cfg)
    with pytest.raises(NotPaired):
        ad.status()


def test_status_unreachable(cfg, monkeypatch):
    monkeypatch.setattr(
        adapter_mod, "run_ssh",
        lambda *a, **k: (_ for _ in ()).throw(SSHError("Connection timed out", 255)),
    )
    ad = GadgetAdapter(cfg)
    with pytest.raises(MuseUnavailable):
        ad.status()


def test_status_parses_info(cfg, monkeypatch):
    def fake_run_ssh(host, remote_args, **kw):
        if remote_args[1] == "info":
            return "Identity: homelink-ab12cd\nPaired: yes\nBLE name: MuseGadgetAB12CD\n"
        return "active\n"

    monkeypatch.setattr(adapter_mod, "run_ssh", fake_run_ssh)
    ad = GadgetAdapter(cfg)
    status = ad.status()
    assert status["paired"] is True
    assert status["service"] == "active"
    assert status["ready"] is True
    assert status["identity"]["identity"] == "homelink-ab12cd"


def test_wait_not_supported(cfg):
    ad = GadgetAdapter(cfg)
    with pytest.raises(NotImplementedError):
        ad.wait("muse-agent-abc")


def test_sessions_roundtrip(cfg, monkeypatch):
    ad = GadgetAdapter(cfg)
    sid = ad.new_session("code-review")
    assert sid.startswith("muse-agent-")
    sessions = ad.list_sessions()
    assert any(s["session_id"] == sid and s["label"] == "code-review" for s in sessions)
