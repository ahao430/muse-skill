"""MCP server tool tests (adapter mocked, no network)."""

from __future__ import annotations

import pytest

from muse_agent.adapter import MuseUnavailable, NotPaired
from muse_agent.adapter import GadgetAdapter, SendResult


@pytest.fixture
def fake_adapter(monkeypatch):
    class FakeAdapter(GadgetAdapter):
        def __init__(self):
            from muse_agent.config import Config

            self.config = Config(backend="ssh")
            self.sent = []
            self.chats = []
            self.fail_with = None

        def status(self):
            if self.fail_with:
                raise self.fail_with
            return {"ready": True, "paired": True, "service": "active", "host": "h"}

        def send(self, message, session_id=None):
            if self.fail_with:
                raise self.fail_with
            self.sent.append((message, session_id))
            return SendResult(ok=True, detail="sent to Muse")

        def chat(self, message, session_id=None, timeout=None):
            if self.fail_with:
                raise self.fail_with
            self.chats.append((message, session_id, timeout))
            return SendResult(ok=True, text="the answer")

    fake = FakeAdapter()
    import muse_agent.server as server

    monkeypatch.setattr(server, "_adapter", fake)
    return fake


async def test_status_ok(fake_adapter):
    import muse_agent.server as server

    result = await server.muse_status()
    assert result["ready"] is True


async def test_status_not_paired_hint(fake_adapter):
    import muse_agent.server as server

    fake_adapter.fail_with = NotPaired("nope")
    result = await server.muse_status()
    assert result["ready"] is False
    assert "docs/pairing.md" in result["error"]


async def test_status_unreachable_hint(fake_adapter):
    import muse_agent.server as server

    fake_adapter.fail_with = MuseUnavailable("timeout")
    result = await server.muse_status()
    assert result["ready"] is False
    assert "provision.sh" in result["error"]


async def test_status_local_backend_hint(fake_adapter):
    import muse_agent.server as server

    fake_adapter.config.backend = "local"
    fake_adapter.fail_with = MuseUnavailable("bun not found")
    result = await server.muse_status()
    assert result["ready"] is False
    assert "bun install" in result["error"]


async def test_chat_returns_reply(fake_adapter):
    import muse_agent.server as server

    result = await server.muse_chat("hi", session_id="s1", timeout=30)
    assert result == {"ok": True, "reply": "the answer", "detail": ""}
    assert fake_adapter.chats == [("hi", "s1", 30)]


async def test_send_records(fake_adapter):
    import muse_agent.server as server

    result = await server.muse_send("note", session_id="s1")
    assert result["ok"] is True
    assert fake_adapter.sent == [("note", "s1")]


async def test_wait_reports_unsupported():
    import muse_agent.server as server

    result = await server.muse_wait("s1", 30)
    assert result["ok"] is False
    assert "muse_chat" in result["error"]


async def test_sessions_tool_lists(fake_adapter, monkeypatch, tmp_path):
    import muse_agent.server as server

    from muse_agent import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "SESSIONS_FILE", tmp_path / "s.json")
    result = await server.muse_sessions()
    assert "sessions" in result
    result = await server.muse_sessions(label="review")
    assert result["label"] == "review"
