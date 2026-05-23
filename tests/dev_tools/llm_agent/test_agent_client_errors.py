"""Error-path tests for ``AgentClient``."""

import configparser
from unittest.mock import MagicMock, patch

import pytest
import requests
from PIL import Image

from src.dev_tools.llm_agent.agent_client import AgentClient
from src.dev_tools.llm_agent.models import AgentAction, AgentError


_GET = "src.dev_tools.llm_agent.agent_client.requests.get"
_POST = "src.dev_tools.llm_agent.agent_client.requests.post"


def _config(error_excerpt_max_chars: int = 2000) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg["LLM_TOOLING"] = {
        "ollama_host": "http://localhost:11434",
        "model_name": "qwen2.5vl:3b",
        "request_timeout_s": "120",
        "error_excerpt_max_chars": str(error_excerpt_max_chars),
        "image_max_dim": "1024",
        "num_ctx": "8192",
    }
    return cfg


def _screenshot() -> Image.Image:
    return Image.new("RGB", (1080, 1920), "red")


def _ok_get():
    r = MagicMock()
    r.status_code = 200
    r.text = '{"models": []}'
    r.json.return_value = {"models": []}
    return r


def _post(content: str, *, status_code: int = 200, text: str = None):
    r = MagicMock()
    r.status_code = status_code
    r.text = text if text is not None else '{"message": {"content": "..."}}'
    r.json.return_value = {"message": {"content": content}}
    return r


def test_connection_error_returns_ollama_unreachable():
    client = AgentClient()
    with patch(_GET, side_effect=requests.exceptions.ConnectionError("nope")):
        result = client.next_action("goal", [], _screenshot(), _config())
    assert isinstance(result, AgentError)
    assert result.category == "OLLAMA_UNREACHABLE"
    assert result.model_name == "qwen2.5vl:3b"


def test_get_timeout_returns_ollama_timeout():
    client = AgentClient()
    with patch(_GET, side_effect=requests.exceptions.Timeout("slow")):
        result = client.next_action("goal", [], _screenshot(), _config())
    assert isinstance(result, AgentError)
    assert result.category == "OLLAMA_TIMEOUT"


def test_post_404_with_model_not_found_returns_model_missing():
    client = AgentClient()
    body_text = '{"error":"model not found"}'
    with patch(_GET, return_value=_ok_get()), patch(
        _POST, return_value=_post("", status_code=404, text=body_text)
    ):
        result = client.next_action("goal", [], _screenshot(), _config())
    assert isinstance(result, AgentError)
    assert result.category == "MODEL_MISSING"
    assert "model not found" in result.raw_excerpt


def test_invalid_json_after_retry_returns_invalid_json():
    """Two consecutive non-JSON replies surface INVALID_JSON."""
    client = AgentClient()
    with patch(_GET, return_value=_ok_get()), patch(
        _POST, return_value=_post("<not json>")
    ) as mock_post:
        result = client.next_action("goal", [], _screenshot(), _config(50))
    assert isinstance(result, AgentError)
    assert result.category == "INVALID_JSON"
    assert mock_post.call_count == 2  # initial + 1 auto-retry
    assert len(result.raw_excerpt) <= 50


def test_schema_violation_after_retry_returns_schema_violation():
    """Valid JSON missing required fields surfaces SCHEMA_VIOLATION."""
    client = AgentClient()
    bad = '{"kind": "tap"}'  # missing x, y
    with patch(_GET, return_value=_ok_get()), patch(
        _POST, return_value=_post(bad)
    ) as mock_post:
        result = client.next_action("goal", [], _screenshot(), _config())
    assert isinstance(result, AgentError)
    assert result.category == "SCHEMA_VIOLATION"
    assert mock_post.call_count == 2
    assert "x" in result.message or "y" in result.message


def test_invalid_then_valid_recovers():
    """First reply non-JSON, retry returns valid action -> AgentAction."""
    client = AgentClient()
    valid = '{"kind": "tap", "x": 100, "y": 200, "rationale": "ok"}'
    responses = [_post("<not json>"), _post(valid)]
    with patch(_GET, return_value=_ok_get()), patch(
        _POST, side_effect=responses
    ) as mock_post:
        result = client.next_action("goal", [], _screenshot(), _config())
    assert isinstance(result, AgentAction)
    # Coords are rescaled from image-space (1024-dim major axis) to device.
    assert mock_post.call_count == 2


def test_valid_tap_action_rescaled_to_device_space():
    """Image-space coords scale up to device-space (1080x1920)."""
    client = AgentClient()
    # In image space (576x1024), x=288 maps to device x=540 at scale 0.5333.
    valid = '{"kind": "tap", "x": 288, "y": 512, "rationale": "center"}'
    with patch(_GET, return_value=_ok_get()), patch(
        _POST, return_value=_post(valid)
    ):
        result = client.next_action("goal", [], _screenshot(), _config())
    assert isinstance(result, AgentAction)
    assert result.kind == "tap"
    # 288 / 0.5333 ≈ 540, 512 / 0.5333 ≈ 960
    assert 535 <= result.x <= 545
    assert 955 <= result.y <= 965
