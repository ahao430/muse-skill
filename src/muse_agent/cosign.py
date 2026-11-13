"""COS XML API request presigning (pure Python, no SDK dependency).

Implements the documented COS signature algorithm so the Mac can mint
short-lived upload/download URLs. Muse only ever sees a presigned URL —
no credentials ever enter its VM.

Algorithm (https://cloud.tencent.com/document/product/436/7778):
  KeyTime      = "<start>;<end>" (unix seconds)
  SignKey      = hex(HMAC-SHA1(SecretKey, KeyTime))
  HttpString   = lower(method) + "\\n" + UrlPath + "\\n" + params + "\\n" + headers + "\\n"
                 (params/headers: "k=v&" pairs, key-lowercased, value-URL-encoded, &-sorted)
  StringToSign = "sha1\\n" + KeyTime + "\\n" + hex(SHA1(HttpString)) + "\\n"
  Signature    = hex(HMAC-SHA1(SignKey, StringToSign))
"""

from __future__ import annotations

import hashlib
import hmac
import time
import urllib.parse


def _hmac_sha1_hex(key: str, msg: str) -> str:
    return hmac.new(key.encode(), msg.encode(), hashlib.sha1).hexdigest()


def _sha1_hex(msg: str) -> str:
    return hashlib.sha1(msg.encode()).hexdigest()


def _encode_params(params: dict[str, str]) -> tuple[str, str]:
    """Return (param_string 'k=v&…', header_list 'k;k;…') with COS ordering."""
    if not params:
        return "", ""
    items = sorted((k.lower(), urllib.parse.quote(str(v), safe="")) for k, v in params.items())
    param_str = "".join(f"{k}={v}&" for k, v in items)
    key_list = ";".join(k for k, _ in items)
    return param_str, key_list


def _http_string(method: str, url_path: str, params: dict[str, str],
                 headers: dict[str, str]) -> str:
    param_str, _ = _encode_params(params)
    header_str, _ = _encode_params(headers)
    return f"{method.lower()}\n{url_path}\n{param_str}\n{header_str}\n"


def presign_url(method: str, bucket_domain: str, key: str, secret_id: str,
                secret_key: str, expires: int = 3600) -> str:
    """Mint a presigned URL for one object. `key` must not start with '/'."""
    key = key.lstrip("/")
    url_path = "/" + urllib.parse.quote(key, safe="/")
    now = int(time.time())
    key_time = f"{now};{now + expires}"

    sign_key = _hmac_sha1_hex(secret_key, key_time)
    http_string = _http_string(method, url_path, params={}, headers={})
    string_to_sign = f"sha1\n{key_time}\n{_sha1_hex(http_string)}\n"
    signature = _hmac_sha1_hex(sign_key, string_to_sign)

    # Empty signed lists (params and headers) keep the URL usable from any
    # client (Muse's curl PUT, our anonymous GET) without binding to headers.
    query = {
        "q-sign-algorithm": "sha1",
        "q-ak": secret_id,
        "q-sign-time": key_time,
        "q-key-time": key_time,
        "q-header-list": "",
        "q-url-param-list": "",
        "q-signature": signature,
    }
    qs = urllib.parse.urlencode(query, safe=";")
    return f"https://{bucket_domain}{url_path}?{qs}"
