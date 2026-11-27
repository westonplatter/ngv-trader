"""Fire-and-forget POSTs from worker processes to the API's SSE notify endpoints."""

from __future__ import annotations

import json
import os
import urllib.request

_API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000/api/v1")


def post_to_api(path: str, payload: dict) -> None:
    url = f"{_API_BASE_URL}{path}"
    if not url.startswith(("http://", "https://")):
        return
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=2)  # nosec B310
