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

    def images(self, message, session_id, timeout, upload_url=None, media_domain=None):
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
        def images(self, message, session_id, timeout, upload_url=None, media_domain=None):
            self.sent.append(message)
            return {"ok": True, "status": "completed", "reply": "",
                    "images": [],
                    "approvals": [{"action_label": "Upload a file and create a public link"}]}

    adapter.backend = ApprovalBackend()
    result = adapter.poll_image_task(task_id, wait_seconds=5)
    assert result["task"]["status"] == "approval_required"
    assert "Upload a file" in result["task"]["approvals"][0]["action_label"]


# ------------------------------------------------ ssh backend: text-link harvest

class FakeSshBackend:
    """The remote surface: only chat() exists (official CLI couples send+wait)."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []

    def chat(self, message, session_id, timeout):
        self.sent.append(message)
        if not self.replies:
            return {"ok": True, "reply": "", "detail": "sent, no answer yet"}
        return self.replies.pop(0)


def _ssh_adapter(tmp_path, monkeypatch, replies, cos=True):
    from muse_agent import tasks as tm

    bridge = tmp_path / "bridge"
    bridge.mkdir(exist_ok=True)
    (bridge / "bridge.mjs").write_text("//")
    monkeypatch.setattr(tm.TaskStore, "_load", lambda self: None)
    monkeypatch.setattr(tm.TaskStore, "_save", lambda self: None)
    kwargs = {"backend": "ssh", "host": "h"}
    if cos:
        kwargs.update(cos_bucket_domain="muse-t.cos.ap-guangzhou.myqcloud.com",
                      cos_secret_id="AKIDX", cos_secret_key="K")
    ad = GadgetAdapter(Config(**kwargs))
    ad.backend = FakeSshBackend(replies)
    ad._resolve = lambda s=None: "sess-remote"
    return ad


def test_remote_poll_harvests_cos_link(tmp_path, monkeypatch):
    ad = _ssh_adapter(tmp_path, monkeypatch, [
        {"ok": True, "reply": ""},  # CLI exit 3: delivered, no answer yet
        {"ok": True, "reply": "画好了\n![图片](https://muse-t.cos.ap-guangzhou.myqcloud.com/muse-media/a/b.webp)"},
    ])
    started = ad.start_image_task("画一只猫", None)
    tid = started["task"]["task_id"]
    first = ad.poll_image_task(tid, wait_seconds=5)
    assert first["task"]["status"] == "timeout"
    assert "curl -X PUT" in ad.backend.sent[0], "first send must carry the upload slot"
    second = ad.poll_image_task(tid, wait_seconds=5)
    assert second["task"]["status"] == "completed"
    assert second["task"]["images"][0]["url"] == \
        "https://muse-t.cos.ap-guangzhou.myqcloud.com/muse-media/a/b.webp"
    assert "不要重新画" in ad.backend.sent[1], "re-poll must nudge, not regenerate"


def test_remote_poll_answer_without_media(tmp_path, monkeypatch):
    ad = _ssh_adapter(tmp_path, monkeypatch, [
        {"ok": True, "reply": "这张没能画出来，要不要换个温和点的题材？"},
    ])
    started = ad.start_image_task("画打架", None)
    result = ad.poll_image_task(started["task"]["task_id"], wait_seconds=5)
    assert result["task"]["status"] == "completed"
    assert result["task"]["images"] == []
    assert "没能画出来" in result["task"]["reply"]


def test_remote_poll_network_error_is_retryable(tmp_path, monkeypatch):
    ad = _ssh_adapter(tmp_path, monkeypatch, [
        {"ok": False, "detail": "ssh: connect to host timed out"},
    ])
    started = ad.start_image_task("draw", None)
    tid = started["task"]["task_id"]
    result = ad.poll_image_task(tid, wait_seconds=5)
    assert result["task"]["status"] == "timeout", "network errors must stay re-pollable"
    # recover: next poll succeeds
    ad.backend.replies.append(
        {"ok": True, "reply": "![图片](https://muse-t.cos.ap-guangzhou.myqcloud.com/muse-media/c/d.webp)"})
    result = ad.poll_image_task(tid, wait_seconds=5)
    assert result["task"]["status"] == "completed"


def test_extract_media_links_dedupe_and_domains():
    from muse_agent.adapter import _extract_media_links
    text = ("看这个 https://muse.ai/files/a.webp 和 "
            "https://muse-t.cos.ap-guangzhou.myqcloud.com/muse-media/x/y.webp "
            "同一个 https://muse.ai/files/a.webp 不重复")
    links = _extract_media_links(text, "muse-t.cos.ap-guangzhou.myqcloud.com")
    assert [l["url"] for l in links] == [
        "https://muse.ai/files/a.webp",
        "https://muse-t.cos.ap-guangzhou.myqcloud.com/muse-media/x/y.webp"]


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


# ------------------------------------------------------- notifications tool

def test_notifications_dedupe_and_blocks(tmp_path, monkeypatch):
    import muse_agent.server as server
    from muse_agent import config as cfg_mod

    seen_file = tmp_path / "seen.json"
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg_mod, "SESSIONS_FILE", tmp_path / "sessions.json")
    # CONFIG_DIR is read at call time inside adapter via cfg.CONFIG_DIR attribute
    import muse_agent.adapter as ad_mod
    monkeypatch.setattr(ad_mod.cfg, "CONFIG_DIR", tmp_path, raising=False)

    calls = {"n": 0}

    class FakeBackend:
        def notifications(self, session_id, listen_seconds):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"ok": True,
                        "messages": [{"message_id": "m1", "text": "任务完成了", "done": True}],
                        "images": [{"url": "https://muse.ai/files/a.webp", "label": "cat",
                                    "mime": "image/png"}]}
            return {"ok": True, "messages": [], "images": []}

    class FakeAdapter:
        config = Config(backend="local")
        backend = None

        def _resolve(self, session_id):
            return "sess-default"

        def notifications(self, wait_seconds):
            if self.backend is None:
                self.backend = FakeBackend()
            return self.backend.notifications(None, wait_seconds)

    fake = FakeAdapter()
    monkeypatch.setattr(server, "_adapter", fake)

    png = tmp_path / "dl.png"
    png.write_bytes(b"PNGDATA")

    def fake_download(url, task_id, index):
        assert url.endswith("a.webp")
        return str(png)

    monkeypatch.setattr(server, "_download_image", fake_download)

    blocks = _run(server.muse_notifications(wait_seconds=0))
    meta = json.loads(blocks[0].text)
    assert meta["messages"][0]["text"] == "任务完成了"
    assert meta["images"][0]["inline"] is True and meta["images"][0]["path"] == str(png)
    assert [b for b in blocks if b.type == "image"], "image must inline"

    # second poll: everything already seen → no re-delivery
    blocks2 = _run(server.muse_notifications(wait_seconds=0))
    meta2 = json.loads(blocks2[0].text)
    assert meta2["messages"] == [] and meta2["images"] == []
    assert not [b for b in blocks2 if b.type == "image"]


def test_backend_local_proxy_branch_no_nameerror(tmp_path, monkeypatch):
    """bridge_proxy set → the proxychains wrapper path must build without
    NameError (regression: `cfg` was referenced but never imported)."""
    from muse_agent import backend_local as bl

    bridge = tmp_path / "bridge"
    bridge.mkdir(exist_ok=True)
    (bridge / "bridge.mjs").write_text("//")
    monkeypatch.setattr(bl.cfg, "CONFIG_DIR", tmp_path)
    captured = {}

    class FakeCompleted:
        def __init__(self, rc, out):
            self.returncode, self.stdout, self.stderr = rc, out, ""

    def fake_run(cmd, capture_output, text, timeout, env=None):
        captured["cmd"] = cmd
        return FakeCompleted(0, '{"ok": true, "reply": "hi"}')

    monkeypatch.setattr(bl.subprocess, "run", fake_run)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/proxychains4")
    backend = bl.LocalBackend(
        Config(backend="local", bridge_dir=str(bridge),
               bridge_proxy="http://127.0.0.1:7897"))
    payload = backend.chat("hello", "s", 5)
    assert payload["ok"] is True
    assert captured["cmd"][0] == "proxychains4", "must wrap via proxychains4"
    assert captured["cmd"][4].endswith("bridge.mjs")  # proxychains4 -f conf bun script…
    assert (tmp_path / "proxychains.conf").exists(), "conf must be auto-generated"


def test_backend_local_notifications_args(tmp_path, monkeypatch):
    from muse_agent import backend_local as bl

    bridge = tmp_path / "bridge"
    bridge.mkdir()
    (bridge / "bridge.mjs").write_text("//")
    calls = []

    def fake_run(args, timeout):
        calls.append((args, timeout))
        return {"ok": True, "messages": [], "images": []}

    monkeypatch.setattr(bl.LocalBackend, "_run", lambda self, args, timeout: fake_run(args, timeout))
    cfg = Config(backend="local", bridge_dir=str(bridge))
    result = bl.LocalBackend(cfg).notifications("sess-1", 5)
    assert result["ok"] is True
    args, timeout = calls[0]
    assert args[:2] == ["notifications", "--timeout"]
    assert args[args.index("--session") + 1] == "sess-1"
    assert timeout == 35


def test_adapter_notifications_seen_state(tmp_path, monkeypatch):
    from muse_agent import config as cfg_mod
    from muse_agent import tasks as tm

    bridge = tmp_path / "bridge"
    bridge.mkdir()
    (bridge / "bridge.mjs").write_text("//")
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cfg_mod, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(tm.TaskStore, "_load", lambda self: None)
    monkeypatch.setattr(tm.TaskStore, "_save", lambda self: None)

    state = {"n": 0}

    class FakeBackend:
        def notifications(self, session_id, listen_seconds):
            state["n"] += 1
            return {"ok": True,
                    "messages": [{"message_id": "m9", "text": "hi", "done": True}],
                    "images": [{"url": "https://muse.ai/files/z.webp"}]}

    cfg = Config(backend="local", bridge_dir=str(bridge))
    ad = GadgetAdapter(cfg)
    ad.backend = FakeBackend()
    monkeypatch.setattr(ad, "_resolve", lambda s=None: "sess-x")

    first = ad.notifications(0)
    assert len(first["messages"]) == 1 and len(first["images"]) == 1
    second = ad.notifications(0)   # same ids again → filtered by seen-state
    assert second["messages"] == [] and second["images"] == []
    assert (tmp_path / "notifications-seen.json").exists()


# ---------------------------------------------------------------- cosign

def test_cosign_presign_format():
    from muse_agent.cosign import presign_url

    url = presign_url("PUT", "bkt.cos.ap-guangzhou.myqcloud.com",
                      "muse-media/x/y.webp", "AKIDTEST", "secret", expires=600)
    assert url.startswith("https://bkt.cos.ap-guangzhou.myqcloud.com/muse-media/x/y.webp?")
    for part in ("q-sign-algorithm=sha1", "q-ak=AKIDTEST",
                 "q-header-list=", "q-url-param-list=", "q-signature="):
        assert part in url
    # deterministic for same inputs, differs per key
    url2 = presign_url("PUT", "bkt.cos.ap-guangzhou.myqcloud.com",
                       "muse-media/x/y.webp", "AKIDTEST", "secret", expires=600)
    url3 = presign_url("PUT", "bkt.cos.ap-guangzhou.myqcloud.com",
                       "muse-media/x/other.webp", "AKIDTEST", "secret", expires=600)
    assert url == url2 and url != url3


def test_adapter_presign_wired(tmp_path, monkeypatch):
    """With COS configured, the nudge must carry a presigned PUT + public URL,
    and both must flow into the backend call."""
    from muse_agent import tasks as tm

    bridge = tmp_path / "bridge"
    bridge.mkdir()
    (bridge / "bridge.mjs").write_text("//")
    monkeypatch.setattr(tm.TaskStore, "_load", lambda self: None)
    monkeypatch.setattr(tm.TaskStore, "_save", lambda self: None)
    cfg = Config(backend="local", bridge_dir=str(bridge),
                 cos_bucket_domain="muse-t.cos.ap-guangzhou.myqcloud.com",
                 cos_secret_id="AKIDX", cos_secret_key="K")
    ad = GadgetAdapter(cfg)
    captured = {}

    class Backend:
        def images(self, message, session_id, timeout, upload_url=None, media_domain=None):
            captured.update(message=message, upload_url=upload_url, media_domain=media_domain)
            return {"ok": True, "status": "timeout", "reply": "", "images": [], "approvals": []}

    ad.backend = Backend()
    started = ad.start_image_task("draw", None)
    tid = started["task"]["task_id"]
    ad._tasks.tasks[tid] = {**started["task"], "images": []}
    ad._tasks.update(tid, sent_prompt=True)   # force the nudge path
    ad.poll_image_task(tid, wait_seconds=3)
    assert "curl -X PUT" in captured["message"]
    assert captured["upload_url"].startswith(
        "https://muse-t.cos.ap-guangzhou.myqcloud.com/muse-media/")
    assert "q-signature=" in captured["upload_url"]
    assert captured["media_domain"] == "muse-t.cos.ap-guangzhou.myqcloud.com"
