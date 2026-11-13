"""The standalone cos skill must behave exactly like muse_agent.cosign
and read the same config store."""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skills" / "cos" / "cos.py"


def _load_skill():
    spec = importlib.util.spec_from_file_location("cos_skill", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_signature_parity_with_cosign(monkeypatch):
    """Same inputs must mint byte-identical URLs (frozen clock)."""
    monkeypatch.setattr(time, "time", lambda: 1760000000)
    from muse_agent import cosign
    skill = _load_skill()
    for method in ("PUT", "GET", "DELETE"):
        a = cosign.presign_url(method, "b.example.com", "uploads/日 猫.webp",
                               "AKIDx", "k" * 32, 900)
        b = skill.presign_url(method, "b.example.com", "uploads/日 猫.webp",
                              "AKIDx", "k" * 32, 900)
        assert a == b


def test_sanitize_and_default_key():
    skill = _load_skill()
    assert skill.sanitize_filename("my file (1).png") == "my_file_1.png"
    assert skill.sanitize_filename("猫猫.webp") == "猫猫.webp"  # unicode survives
    assert skill.default_key(Path("/tmp/照片.jpg")).startswith("uploads/20")
    assert skill.default_key(Path("/tmp/照片.jpg")).endswith("/照片.jpg")


def test_config_from_file_and_env(tmp_path, monkeypatch):
    skill = _load_skill()
    for var in ("COS_BUCKET_DOMAIN", "COS_SECRET_ID", "COS_SECRET_KEY"):
        monkeypatch.delenv(var, raising=False)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "cos_bucket_domain: b.example.com\n"
        "cos_secret_id: AKIDfile\n"
        "cos_secret_key: filekey123\n"
        "bridge_proxy: http://x  # other keys ignored\n"
    )
    got = skill.load_cos_config(cfg)
    assert got == {"bucket_domain": "b.example.com",
                   "secret_id": "AKIDfile", "secret_key": "filekey123"}

    empty = skill.load_cos_config(tmp_path / "missing.yaml")
    assert empty == {"bucket_domain": "", "secret_id": "", "secret_key": ""}

    monkeypatch.setenv("COS_SECRET_ID", "AKIDenv")
    got = skill.load_cos_config(cfg)
    assert got["secret_id"] == "AKIDenv"          # env wins
    assert got["secret_key"] == "filekey123"      # file still used
