"""Fixtures shared by the agent tests."""

import json

import httpx2 as httpx  # the HTTP client the openai SDK is built on
import pytest
from openai import OpenAI

from pm_agent import agent


def completion(blocks, finish_reason=None):
    """A chat completion as the OpenAI API returns it. A test scripts it as blocks: a text
    ({"type": "text", "text": …}) or a tool call ({"type": "tool_use", "id", "name", "input"})."""
    calls = [
        {
            "id": block["id"],
            "type": "function",
            "function": {
                "name": block["name"],
                "arguments": json.dumps(block["input"], ensure_ascii=False),
            },
        }
        for block in blocks
        if block["type"] == "tool_use"
    ]
    text = " ".join(block["text"] for block in blocks if block["type"] == "text")
    message = {"role": "assistant", "content": text or None, "refusal": None}
    if calls:
        message["tool_calls"] = calls
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-test",
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason or ("tool_calls" if calls else "stop"),
                "logprobs": None,
            }
        ],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 300, "total_tokens": 1500},
    }


@pytest.fixture
def api(monkeypatch):
    """Answers the agent's requests with the scripted replies and keeps the request bodies.
    The real SDK client runs against it, so the whole loop is tested without network."""
    replies, requests = [], []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=replies.pop(0))

    client = OpenAI(
        api_key="test",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    monkeypatch.setattr(agent, "OpenAI", lambda: client)
    monkeypatch.setenv("PM_AGENT_MODEL", "gpt-test")
    return replies, requests
