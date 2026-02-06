from __future__ import annotations

import logging
import urllib.parse
from typing import Any, Dict

import requests

try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30  # seconds


def _http_get_json(url: str, token: str) -> Dict[str, Any]:
    """GET *url* with token auth and return parsed JSON."""
    resp = requests.get(
        url,
        auth=(token, ""),
        headers={"Accept": "application/json"},
        timeout=_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


def _http_get_json_with_params(
    base_url: str, token: str, params: Dict[str, Any]
) -> Dict[str, Any]:
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    return _http_get_json(url, token)
