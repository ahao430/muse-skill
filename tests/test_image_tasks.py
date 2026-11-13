"""Image-task pipeline tests: state machine, no-regen, ImageContent blocks."""

from __future__ import annotations

import base64
import json

import mcp.types as mt
import pytest

from muse_agent import tasks as tasks_mod
from muse_agent.adapter import GadgetAdapter
from muse_agent.config import Config


# ---------------------------------------------------------------- TaskStore

def test_store_roundtrip_and_status_validation(tmp_path):
    store = tasks_mod.TaskStore(tmp_path / "tasks.json")
    task = store.create("draw a cat", "sess-1")
    assert task["status"] == "submitted"
    store.update(task["task_id"], status="pending")
    assert store.get(task["task_id"])["status"] == "pending"
    with pytest.raises(ValueError):
        store.update(task["task_id"], status="banana")


def test_store_persists_across_instances(tmp_path):
    store = tasks_mod.TaskStore(tmp_path / "tasks.json")
    task = store.create("p", "s")
    store2 = tasks_mod.TaskStore(tmp_path / "tasks.json")
    assert store2.get(task["task_id"])["prompt"] == "p"


def test_add_images_dedupes_by_url(tmp_path):
    store = tasks_mod.TaskStore(tmp_path / "tasks.json")
    task = store.create("p", "s")
    img = {"url": "https://muse.ai/files/x.webp", "label": "cat"}
    fresh = store.add_images(task["task_id"], [img, dict(img)])
    assert len(fresh) == 1
    fresh2 = store.add_images(task["task_id"], [dict(img)])
    assert fresh2 == []


def test_mark_image_path(tmp_path):
    store = tasks_mod.TaskStore(tmp_path / "tasks.json")
    task = store.create("p", "s")
    store.add_images(task["task_id"], [{"url": "u1"}])
    store.mark_image_path(task["task_id"], "u1", "/tmp/a.webp")
    assert store.get(task["task_id"])["images"][0]["path"] == "/tmp/a.webp"


# ------------------------------------------------- adapter: no re-generation

class FakeBackend:
    def __init__(self):
        self.sent = []

    def images(self, message, session_id, timeout):
        self.sent.append(message)
        # First call: Muse still generating → timeout; second: shares link.
        if len(self.sent) == 1:
            return {"ok": True, "status": "timeout", "reply": "", "images": [], "approvals": []}
        return {"ok": True, "status": "completed", "reply": "here",
                "images": [{"url": "https://muse.ai/files/cat.webp",
                            "label": "cat", "mime": "image/webp"}],
                "approvals": []}


@pytest.fixture
def adapter(tmp_path, monkeypatch):
    from muse_agent import tasks as tm

    bridge = tmp_path / "bridge"
    bridge.mkdir()
    (bridge / "bridge.mjs").write_text("//")
    cfg = Config(backend="local", bridge_dir=str(bridge))
    monkeypatch.setattr(tm.TaskStore, "__init__",
                        lambda self, path=None: self._fake_init(tmp_path))
    tm.TaskStore._fake_init = lambda self, root: (
        setattr(self, "path", root / "tasks.json"), setattr(self, "tasks", {}), None)[2]
    monkeypatch.setattr(tm.TaskStore, "_load", lambda self: None)
    monkeypatch.setattr(tm.TaskStore, "_save", lambda self: None)
    ad = GadgetAdapter(cfg)
    ad.backend = FakeBackend()
    return ad


def test_poll_does_not_regenerate(adapter, tmp_path):
    from muse_agent import tasks as tm

    monkey_store = tm.TaskStore(tmp_path / "t.json")
    started = adapter.start_image_task("draw a kitten", None)
    task_id = started["task"]["task_id"]
    adapter._tasks = monkey_store
    # seed the task created before we swapped the store
    monkey_store.tasks[task_id] = {**started["task"], "images": []}

    first = adapter.poll_image_task(task_id, wait_seconds=5)
    assert first["task"]["status"] == "timeout"  # Muse still generating
    second = adapter.poll_image_task(task_id, wait_seconds=5)
    assert second["task"]["status"] == "completed"
    backend = adapter.backend
    assert backend.sent[0] == "draw a kitten"
    assert "不要重新画" in backend.sent[1], "repeat polls must nudge, not regenerate"
    assert second["task"]["images"][0]["url"].endswith("cat.webp")


def test_unknown_task(adapter):
    result = adapter.poll_image_task("nope")
    assert not result["ok"]


def test_approval_required_state(adapter, tmp_path):
    from muse_agent import tasks as tm

    started = adapter.start_image_task("draw", None)
    task_id = started["task"]["task_id"]
    store = tm.TaskStore(tmp_path / "t.json")
    store.tasks[task_id] = {**started["task"], "images": []}
    adapter._tasks = store
    adapter.backend.sent = []

    class ApprovalBackend(FakeBackend):
        def images(self, message, session_id, timeout):
            self.sent.append(message)
            return {"ok": True, "status": "completed", "reply": "",
                    "images": [],
                    "approvals": [{"action_label": "Upload a file and create a public link"}]}

    adapter.backend = ApprovalBackend()
    result = adapter.poll_image_task(task_id, wait_seconds=5)
    assert result["task"]["status"] == "approval_required"
    assert "Upload a file" in result["task"]["approvals"][0]["action_label"]


# ------------------------------------------------------- server: ImageContent

def _run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro) if False else __import__("asyncio").run(coro)


def test_result_blocks_contain_native_image(tmp_path, monkeypatch):
    import muse_agent.server as server

    png = tmp_path / "cat.png"
    raw = b"\x89PNG" + b"0" * 64
    png.write_bytes(raw)
    task = {"task_id": "t1", "status": "completed", "reply": "done",
            "error": "", "approvals": [],
            "images": [{"url": "https://muse.ai/files/cat.webp", "label": "cat",
                        "mime": "image/png", "width": 100, "height": 100,
                        "path": str(png)}]}

    class FakeAdapter:
        config = Config(backend="local")

        def poll_image_task(self, task_id, wait_seconds):
            return {"ok": True, "task": task}

    monkeypatch.setattr(server, "_adapter", FakeAdapter())
    blocks = _run(server.muse_get_image_result("t1", wait_seconds=0))
    assert isinstance(blocks, list)
    assert blocks[0].type == "text"
    meta = json.loads(blocks[0].text)
    assert meta["status"] == "completed" and meta["images"][0]["inline"] is True
    images = [b for b in blocks if b.type == "image"]
    assert len(images) == 1
    assert base64.b64decode(images[0].data) == raw
    assert images[0].mimeType == "image/png"


def test_result_oversize_image_not_inlined(tmp_path, monkeypatch):
    import muse_agent.server as server

    big = tmp_path / "big.webp"
    big.write_bytes(b"B" * (server._MAX_INLINE_BYTES + 1))
    task = {"task_id": "t2", "status": "completed", "reply": "", "error": "",
            "approvals": [],
            "images": [{"url": "https://muse.ai/files/big.webp", "label": "",
                        "mime": "image/webp", "path": str(big)}]}

    class FakeAdapter:
        config = Config(backend="local")

        def poll_image_task(self, task_id, wait_seconds):
            return {"ok": True, "task": task}

    monkeypatch.setattr(server, "_adapter", FakeAdapter())
    blocks = _run(server.muse_get_image_result("t2", wait_seconds=0))
    assert not [b for b in blocks if b.type == "image"], "oversize must not inline"
    meta = json.loads(blocks[0].text)
    assert "too large" in meta["images"][0]["note"]


def test_return_image_false(tmp_path, monkeypatch):
    import muse_agent.server as server

    png = tmp_path / "c.png"
    png.write_bytes(b"x")
    task = {"task_id": "t3", "status": "completed", "reply": "", "error": "",
            "approvals": [],
            "images": [{"url": "u", "label": "", "mime": "image/png", "path": str(png)}]}

    class FakeAdapter:
        config = Config(backend="local")

        def poll_image_task(self, task_id, wait_seconds):
            return {"ok": True, "task": task}

    monkeypatch.setattr(server, "_adapter", FakeAdapter())
    blocks = _run(server.muse_get_image_result("t3", return_image=False))
    assert not [b for b in blocks if b.type == "image"]


def test_muse_get_images_convenience(tmp_path, monkeypatch):
    import muse_agent.server as server

    png = tmp_path / "k.png"
    png.write_bytes(b"K" * 10)

    class FakeAdapter:
        config = Config(backend="local")

        def start_image_task(self, prompt, session_id):
            return {"ok": True, "task": {"task_id": "kt", "status": "submitted",
                                          "prompt": prompt, "session_id": "s",
                                          "reply": "", "images": [], "approvals": [],
                                          "error": ""}}

        def poll_image_task(self, task_id, wait_seconds):
            return {"ok": True, "task": {"task_id": "kt", "status": "completed",
                                          "reply": "ok", "error": "", "approvals": [],
                                          "images": [{"url": "https://muse.ai/files/k.webp",
                                                      "label": "kitten", "mime": "image/png",
                                                      "path": str(png)}]}}

    monkeypatch.setattr(server, "_adapter", FakeAdapter())
    blocks = _run(server.muse_get_images("draw a kitten", timeout=5))
    images = [b for b in blocks if b.type == "image"]
    assert len(images) == 1
