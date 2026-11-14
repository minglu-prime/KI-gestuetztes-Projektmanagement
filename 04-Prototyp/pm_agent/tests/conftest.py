"""Fixtures shared by the agent tests."""

import json

import httpx2 as httpx  # the HTTP client the anthropic SDK is built on
import pytest
from anthropic import Anthropic

from pm_agent import agent


@pytest.fixture
def api(monkeypatch):
    """Answers the agent's requests with the scripted replies and keeps the request bodies.
    The real SDK tool runner runs against it, so the whole loop is tested without network."""
    replies, requests = [], []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=replies.pop(0))

    client = Anthropic(
        api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handle))
    )
    monkeypatch.setattr(agent, "Anthropic", lambda: client)
    return replies, requests
