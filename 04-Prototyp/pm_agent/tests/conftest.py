"""Fixtures shared by the agent tests."""

import json

import httpx2 as httpx  # the HTTP client the openai SDK is built on
import pytest
from openai import OpenAI

from pm_agent import agent, comparison, lifecycle, tracking, workbench


@pytest.fixture(autouse=True)
def no_real_data(monkeypatch, tmp_path):
    """Every file the site reads or writes, in the test's own folder: no test touches the
    real data/ and logs/. A test that replaced only a loader (load_team) still saved into
    data/team.json. Fixtures and tests may point a file elsewhere on top of this."""
    data = tmp_path / "data"
    monkeypatch.setattr(workbench, "DATA_DIR", data)
    monkeypatch.setattr(workbench, "TEAM_FILE", data / "team.json")
    monkeypatch.setattr(workbench, "RUNS_CSV", tmp_path / "logs" / "runs.csv")
    monkeypatch.setattr(comparison, "COMPARISON_CSV", tmp_path / "logs" / "agent_vergleich.csv")
    monkeypatch.setattr(tracking, "PROJECT_FILE", data / "projekt.json")
    monkeypatch.setattr(lifecycle, "FILE", data / "vorhaben.json")
    monkeypatch.setattr(agent, "LOG_DIR", tmp_path / "logs")


def response(blocks, status="completed", reason=None):
    """A Responses API reply. A test scripts it as blocks: a text ({"type": "text", "text": …}),
    a refusal ({"type": "refusal", "refusal": …}) or a tool call ({"type": "tool_use", "id",
    "name", "input"})."""
    output = []
    for block in blocks:
        if block["type"] == "tool_use":
            output.append(
                {
                    "type": "function_call",
                    "id": "fc_" + block["id"],
                    "call_id": block["id"],
                    "name": block["name"],
                    "arguments": json.dumps(block["input"], ensure_ascii=False),
                    "status": "completed",
                }
            )
        else:
            part = (
                {"type": "refusal", "refusal": block["refusal"]}
                if block["type"] == "refusal"
                else {"type": "output_text", "text": block["text"], "annotations": []}
            )
            output.append(
                {
                    "type": "message",
                    "id": "msg_test",
                    "role": "assistant",
                    "status": "completed",
                    "content": [part],
                }
            )
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 0,
        "model": "gpt-test",
        "status": status,
        "incomplete_details": {"reason": reason} if reason else None,
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "error": None,
        "instructions": None,
        "metadata": {},
        "usage": {
            "input_tokens": 1200,
            "output_tokens": 300,
            "total_tokens": 1500,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
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
    monkeypatch.setattr(agent, "OpenAI", lambda *args, **kwargs: client)
    monkeypatch.setenv("PM_AGENT_MODEL", "gpt-test")
    return replies, requests
