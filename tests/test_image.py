"""Tests for muse_send_image / muse_doctor (ssh + scp mocked)."""

from __future__ import annotations

import pytest

from muse_agent import adapter as adapter_mod
from muse_agent.adapter import GadgetAdapter
from muse_agent.config import Config


@pytest.fixture
def cfg():
    return Config(host="test@example.com", timeout=30, connect_timeout=5)


@pytest.fixture
def png(tmp_path):
    path = tmp_path / "pic.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 100)
    return str(path)


def _patch(monkeypatch, scp_rc=0, ssh_out="Sent to your Muse.\n"):
    runs = {"scp": [], "ssh": [], "rm": []}

    def fake_sub_run(cmd, **kw):
        if cmd[0] == "scp":
            runs["scp"].append(cmd)
            class P:
                returncode = scp_rc
                stderr = "scp boom" if scp_rc else ""
            return P()
        return None

    def fake_run_ssh(host, remote_args, **kw):
        runs["ssh"].append(remote_args)
        return ssh_out

    monkeypatch.setattr("subprocess.run", fake_sub_run)
    monkeypatch.setattr(adapter_mod, "run_ssh", fake_run_ssh)
    return runs


def test_send_image_happy_path(cfg, png, monkeypatch):
    runs = _patch(monkeypatch)
    ad = GadgetAdapter(cfg)
    result = ad.send_image(png, "look at this", timeout=20)
    assert result.ok
    assert runs["scp"], "image must be scp'd to the host"
    ssh_args = runs["ssh"][0]
    assert "--image" in ssh_args
    assert ssh_args[ssh_args.index("--wait") + 1] == "20"


def test_send_image_rejects_oversized(cfg, tmp_path):
    big = tmp_path / "big.png"
    big.write_bytes(b"0" * (2 * 1024 * 1024 + 1))
    ad = GadgetAdapter(cfg)
    result = ad.send_image(str(big))
    assert not result.ok and "2 MiB" in result.detail


def test_send_image_rejects_type(cfg, tmp_path):
    p = tmp_path / "pic.bmp"
    p.write_bytes(b"BM" + b"0" * 10)
    ad = GadgetAdapter(cfg)
    result = ad.send_image(str(p))
    assert not result.ok and "unsupported type" in result.detail


def test_send_image_scp_failure(cfg, png, monkeypatch):
    _patch(monkeypatch, scp_rc=1)
    ad = GadgetAdapter(cfg)
    result = ad.send_image(png)
    assert not result.ok and "scp failed" in result.detail


def test_doctor_ok(cfg, monkeypatch):
    monkeypatch.setattr(
        adapter_mod, "run_ssh",
        lambda *a, **k: "pairing: ok\nservice: active\n",
    )
    ad = GadgetAdapter(cfg)
    report = ad.doctor()
    assert report["ok"] and "pairing" in report["report"]
