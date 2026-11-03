"""Default tests must never let an unmocked HTTP request leave Python."""

import httpx
import pytest


def test_unmocked_default_http_is_blocked_before_transport():
    with httpx.Client(trust_env=False) as client, pytest.raises(AssertionError, match="not mocked"):
        client.get("http://127.0.0.1:9/offline-boundary", timeout=0.1)
