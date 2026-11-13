#!/usr/bin/env python3
"""cos.py — standalone Tencent COS uploader (stdlib only, no SDK).

Shares the cos_* settings in ~/.config/muse-agent/config.yaml with the
muse-skill MCP server, so the machine has exactly one COS credential store.
Signature algorithm mirrors src/muse_agent/cosign.py — keep them in sync
(guarded by tests/test_cos_skill.py).

Usage:
  python3 cos.py upload <file>... [--key KEY] [--md]   # PUT + print public URLs
  python3 cos.py presign <key> [--method GET|PUT|DELETE] [--expires N]
  python3 cos.py delete <key>
  python3 cos.py selftest                              # PUT/GET/DELETE roundtrip

Credentials never leave this machine and are never printed.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import mimetypes
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_CONFIG = Path(
    os.environ.get("MUSE_AGENT_CONFIG_DIR", "~/.config/muse-agent")
).expanduser() / "config.yaml"


# -- COS XML API presigning (mirror of src/muse_agent/cosign.py) ------------
# https://cloud.tencent.com/document/product/436/7778

def _hmac_sha1_hex(key: str, msg: str) -> str:
    return hmac.new(key.encode(), msg.encode(), hashlib.sha1).hexdigest()


def _sha1_hex(msg: str) -> str:
    return hashlib.sha1(msg.encode()).hexdigest()


def presign_url(method: str, bucket_domain: str, key: str, secret_id: str,
                secret_key: str, expires: int = 3600) -> str:
    """Mint a presigned URL for one object. `key` must not start with '/'."""
    key = key.lstrip("/")
    url_path = "/" + urllib.parse.quote(key, safe="/")
    now = int(time.time())
    key_time = f"{now};{now + expires}"
    sign_key = _hmac_sha1_hex(secret_key, key_time)
    http_string = f"{method.lower()}\n{url_path}\n\n\n"
    string_to_sign = f"sha1\n{key_time}\n{_sha1_hex(http_string)}\n"
    query = {
        "q-sign-algorithm": "sha1",
        "q-ak": secret_id,
        "q-sign-time": key_time,
        "q-key-time": key_time,
        "q-header-list": "",
        "q-url-param-list": "",
        "q-signature": _hmac_sha1_hex(sign_key, string_to_sign),
    }
    qs = urllib.parse.urlencode(query, safe=";")
    return f"https://{bucket_domain}{url_path}?{qs}"


# -- config -------------------------------------------------------------------

def load_cos_config(path: Path | None = None) -> dict[str, str]:
    """cos_* fields from the flat YAML; env vars COS_* win over the file."""
    values: dict[str, str] = {}
    cfg = path or DEFAULT_CONFIG
    if cfg.exists():
        for line in cfg.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            k, _, v = line.partition(":")
            values[k.strip()] = v.strip().strip("'\"")
    return {
        "bucket_domain": os.environ.get("COS_BUCKET_DOMAIN", values.get("cos_bucket_domain", "")),
        "secret_id": os.environ.get("COS_SECRET_ID", values.get("cos_secret_id", "")),
        "secret_key": os.environ.get("COS_SECRET_KEY", values.get("cos_secret_key", "")),
    }


def _require(cfg: dict[str, str]) -> tuple[str, str, str]:
    missing = [k for k in ("bucket_domain", "secret_id", "secret_key") if not cfg[k]]
    if missing:
        sys.exit(f"cos: missing config {missing} — set cos_bucket_domain / cos_secret_id /"
                 f" cos_secret_key in {DEFAULT_CONFIG} (see muse-skill README, route A3)")
    return cfg["bucket_domain"], cfg["secret_id"], cfg["secret_key"]


# -- helpers ------------------------------------------------------------------

def sanitize_filename(name: str) -> str:
    """Spaces and odd punctuation become '_' (shells/URLs stay happy);
    unicode letters (e.g. Chinese) survive — COS keys are UTF-8."""
    name = re.sub(r"[^\w.\-]+", "_", name)
    name = re.sub(r"_(?=\.[^.]+$)", "", name)  # no stray '_' before the extension
    return name.strip("._") or "file"


def default_key(path: Path) -> str:
    return f"uploads/{time.strftime('%Y%m%d')}/{sanitize_filename(path.name)}"


def public_url(bucket_domain: str, key: str) -> str:
    return f"https://{bucket_domain}/{urllib.parse.quote(key.lstrip('/'), safe='/')}"


def _https_opener() -> urllib.request.OpenerDirector:
    """An opener whose TLS still verifies, but finds a CA bundle even on
    python.org macOS builds (no bundled certs). Fallbacks stay verified —
    we only point at an explicit CA file, never disable checks."""
    ca_candidates: list[str] = []
    try:
        import certifi
        ca_candidates.append(certifi.where())
    except ImportError:
        pass
    ca_candidates += [
        "/etc/ssl/cert.pem",                    # macOS system store
        "/etc/ssl/certs/ca-certificates.crt",   # Debian/Ubuntu/WSL2
        "/etc/pki/tls/certs/ca-bundle.crt",     # Fedora
    ]
    for ca in ca_candidates:
        if Path(ca).exists():
            try:
                ctx = ssl.create_default_context(cafile=ca)
                return urllib.request.build_opener(
                    urllib.request.HTTPSHandler(context=ctx))
            except (OSError, ssl.SSLError):
                continue
    return urllib.request.build_opener()


_OPENER: urllib.request.OpenerDirector | None = None


def _http(url: str, data: bytes | None = None, method: str = "GET",
          headers: dict[str, str] | None = None, timeout: int = 60) -> int:
    global _OPENER
    if _OPENER is None:
        _OPENER = _https_opener()
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:  # 4xx/5xx raise; caller wants the code
        return exc.code


# -- subcommands ----------------------------------------------------------------

def cmd_upload(args: argparse.Namespace) -> int:
    bucket, sid, skey = _require(load_cos_config(args.config))
    files = [Path(f).expanduser() for f in args.files]
    if args.key and len(files) > 1:
        sys.exit("cos: --key only makes sense with a single file")
    for f in files:
        if not f.is_file():
            sys.exit(f"cos: not a file: {f}")
        key = args.key or default_key(f)
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        put = presign_url("PUT", bucket, key, sid, skey, expires=900)
        status = _http(put, data=f.read_bytes(), method="PUT",
                       headers={"Content-Type": ctype})
        if status != 200:
            sys.exit(f"cos: PUT {key} -> HTTP {status}")
        url = public_url(bucket, key)
        print(f"![{f.stem or 'file'}]({url})" if args.md else url)
    return 0


def cmd_presign(args: argparse.Namespace) -> int:
    bucket, sid, skey = _require(load_cos_config(args.config))
    print(presign_url(args.method, bucket, args.key, sid, skey, args.expires))
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    bucket, sid, skey = _require(load_cos_config(args.config))
    url = presign_url("DELETE", bucket, args.key, sid, skey, expires=300)
    status = _http(url, method="DELETE")
    # 204 = gone, 404 = already absent — both count as deleted
    if status not in (200, 204, 404):
        sys.exit(f"cos: DELETE {args.key} -> HTTP {status}")
    print(f"deleted {args.key}")
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    bucket, sid, skey = _require(load_cos_config(args.config))
    key = "uploads/selftest.txt"
    put = presign_url("PUT", bucket, key, sid, skey, expires=600)
    if _http(put, data=f"muse-agent selftest {time.strftime('%FT%T')}".encode(),
             method="PUT") != 200:
        sys.exit("cos: selftest PUT failed (check cos_secret_key — see README 排错)")
    status = _http(public_url(bucket, key))  # anonymous GET: proves public readability
    if status != 200:
        cmd_delete(argparse.Namespace(key=key, config=args.config))
        sys.exit(f"cos: selftest public GET -> HTTP {status}"
                 " (bucket not public-read? check COS bucket permissions)")
    print(f"PUT 200, public GET {status}")
    cmd_delete(argparse.Namespace(key=key, config=args.config))
    print("selftest PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cos", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", type=Path, default=None,
                   help="config.yaml path (default ~/.config/muse-agent/config.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("upload", help="PUT file(s), print public URL(s)")
    up.add_argument("files", nargs="+")
    up.add_argument("--key", help="object key (single file only; default uploads/YYYYMMDD/name)")
    up.add_argument("--md", action="store_true", help="print ![name](url) Markdown")
    up.set_defaults(fn=cmd_upload)

    pre = sub.add_parser("presign", help="mint a presigned URL without uploading")
    pre.add_argument("key")
    pre.add_argument("--method", default="GET", choices=["GET", "PUT", "DELETE"])
    pre.add_argument("--expires", type=int, default=3600)
    pre.set_defaults(fn=cmd_presign)

    de = sub.add_parser("delete", help="delete an object")
    de.add_argument("key")
    de.set_defaults(fn=cmd_delete)

    st = sub.add_parser("selftest", help="PUT/GET/DELETE roundtrip + public-read check")
    st.set_defaults(fn=cmd_selftest)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
