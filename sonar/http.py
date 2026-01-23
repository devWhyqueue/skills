from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from typing import Any, Dict

try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass


def _basic_auth_header(token: str) -> str:
    raw = f"{token}:".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _http_get_json(url: str, token: str) -> Dict[str, Any]:
    req = urllib.request.Request(url)
    req.add_header("Authorization", _basic_auth_header(token))
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_json_with_params(
    base_url: str, token: str, params: Dict[str, Any]
) -> Dict[str, Any]:
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    return _http_get_json(url, token)
