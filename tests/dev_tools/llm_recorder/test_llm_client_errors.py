"""Error-path unit tests for ``LLMClient``.

Covers each of the six ``LLMError`` categories declared in the design's
"Error categories and their triggers" table:

* ``EMPTY_SESSION``        — pre-flight check, no HTTP must be issued.
* ``OLLAMA_UNREACHABLE``   — ``requests.get`` raises ``ConnectionError``.
* ``OLLAMA_TIMEOUT``       — ``requests.get`` raises ``requests.exceptions.Timeout``.
* ``MODEL_MISSING``        — POST returns 404 with ``"model not found"``.
* ``INVALID_JSON``         — POST returns 200 but ``message.content`` is not JSON,
                             and the raw excerpt is truncated to
                             ``error_excerpt_max_chars``.
* ``SCHEMA_VIOLATION``     — POST returns 200 with valid JSON missing ``activity``.

Network calls are stubbed with ``unittest.mock.patch`` against the
module-level ``requests`` reference inside ``llm_client``. Configuration is
supplied via a stock ``configparser.ConfigParser`` to exercise the same
``.get()/.getint()/.getboolean()`` API the GUI uses.
"""

import configparser
from unittest.mock import MagicMock, patch

import pytest
import requests
from PIL import Image

from src.dev_tools.llm_recorder.llm_client import LLMClient
from src.dev_tools.llm_recorder.models import (
    LLMError,
    RecordedStep,
    RecordingSession,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The module path used for ``patch`` so we hit the ``requests`` name bound
# inside ``llm_client``, not just the global one. See the implementation
# note in tasks.md (8.2).
_GET_PATCH = "src.dev_tools.llm_recorder.llm_client.requests.get"
_POST_PATCH = "src.dev_tools.llm_recorder.llm_client.requests.post"


def _make_config(error_excerpt_max_chars: int = 2000) -> configparser.ConfigParser:
    """Build a ``ConfigParser`` carrying the keys ``LLMClient`` reads.

    The defaults match the design's Configuration table; only
    ``error_excerpt_max_chars`` is parameterized so the truncation test
    can shrink it.
    """
    cfg = configparser.ConfigParser()
    cfg["LLM_TOOLING"] = {
        "ollama_host": "http://localhost:11434",
        "model_name": "qwen2.5vl:7b",
        "request_timeout_s": "120",
        "error_excerpt_max_chars": str(error_excerpt_max_chars),
    }
    return cfg


def _make_session(num_steps: int = 1) -> RecordingSession:
    """Build a recording session with ``num_steps`` tiny PIL screenshots."""
    steps = []
    for i in range(num_steps):
        before = Image.new("RGB", (1080, 1920), "red")
        after = Image.new("RGB", (1080, 1920), "red")
        steps.append(
            RecordedStep(
                index=i,
                screenshot_before=before,
                screenshot_after=after,
                tap_coords=(100, 200),
                label=None,
            )
        )
    return RecordingSession(steps=steps)


def _ok_get_response() -> MagicMock:
    """A successful ``/api/tags`` reply for the reachability probe."""
    resp = MagicMock()
    resp.status_code = 200
    resp.text = '{"models": []}'
    resp.json.return_value = {"models": []}
    return resp


def _post_response(*, status_code: int, content: str = "", text: str = None) -> MagicMock:
    """Build a fake ``/api/chat`` POST response.

    ``content`` is wrapped in ``{"message": {"content": ...}}`` to match
    Ollama's envelope; ``text`` overrides the ``.text`` attribute for the
    cases (e.g. 404) where the body is plain text rather than JSON.
    """
    body = {"message": {"content": content}}
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text if text is not None else f'{{"message": {{"content": {content!r}}}}}'
    resp.json.return_value = body
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_empty_session_returns_empty_session_error_without_network():
    """Zero-step session short-circuits before any HTTP call (Req 5.4)."""
    client = LLMClient()
    session = RecordingSession(steps=[])
    config = _make_config()

    with patch(_GET_PATCH) as mock_get, patch(_POST_PATCH) as mock_post:
        result = client.analyze(session, config)

    assert isinstance(result, LLMError)
    assert result.category == "EMPTY_SESSION"
    assert result.ollama_host == "http://localhost:11434"
    assert result.model_name == "qwen2.5vl:7b"
    mock_get.assert_not_called()
    mock_post.assert_not_called()


def test_connection_error_returns_ollama_unreachable():
    """``requests.get`` raising ``ConnectionError`` maps to OLLAMA_UNREACHABLE (Req 5.1)."""
    client = LLMClient()
    session = _make_session()
    config = _make_config()

    with patch(_GET_PATCH, side_effect=requests.exceptions.ConnectionError("nope")):
        result = client.analyze(session, config)

    assert isinstance(result, LLMError)
    assert result.category == "OLLAMA_UNREACHABLE"
    assert "localhost:11434" in result.message
    assert "qwen2.5vl:7b" in result.message


def test_get_timeout_returns_ollama_timeout():
    """``requests.get`` raising ``Timeout`` maps to OLLAMA_TIMEOUT (Req 5.2)."""
    client = LLMClient()
    session = _make_session()
    config = _make_config()

    with patch(_GET_PATCH, side_effect=requests.exceptions.Timeout("slow")):
        result = client.analyze(session, config)

    assert isinstance(result, LLMError)
    assert result.category == "OLLAMA_TIMEOUT"
    assert "120" in result.message  # request_timeout_s surfaces in message


def test_post_404_with_model_not_found_returns_model_missing():
    """A 404 carrying ``"model not found"`` maps to MODEL_MISSING (Req 5.3)."""
    client = LLMClient()
    session = _make_session()
    config = _make_config()

    body_text = '{"error":"model not found, try `ollama pull qwen2.5vl:7b`"}'
    post_resp = MagicMock()
    post_resp.status_code = 404
    post_resp.text = body_text
    post_resp.json.return_value = {"error": "model not found"}

    with patch(_GET_PATCH, return_value=_ok_get_response()), patch(
        _POST_PATCH, return_value=post_resp
    ):
        result = client.analyze(session, config)

    assert isinstance(result, LLMError)
    assert result.category == "MODEL_MISSING"
    # Raw upstream text must be preserved (truncated by limit, but here it
    # is well under 2000 chars so it survives intact).
    assert "model not found" in result.raw_excerpt
    assert result.model_name == "qwen2.5vl:7b"


def test_post_invalid_json_truncates_excerpt_to_limit():
    """Non-JSON ``message.content`` maps to INVALID_JSON with truncated excerpt (Req 6.4)."""
    client = LLMClient()
    session = _make_session()
    limit = 50
    config = _make_config(error_excerpt_max_chars=limit)

    # Content is plainly not JSON and longer than ``limit`` so we can
    # observe truncation.
    long_content = "<not json " + ("x" * 200) + ">"
    assert len(long_content) > limit

    post_resp = MagicMock()
    post_resp.status_code = 200
    post_resp.text = '{"message": {"content": "..."}}'  # outer envelope is fine
    post_resp.json.return_value = {"message": {"content": long_content}}

    with patch(_GET_PATCH, return_value=_ok_get_response()), patch(
        _POST_PATCH, return_value=post_resp
    ):
        result = client.analyze(session, config)

    assert isinstance(result, LLMError)
    assert result.category == "INVALID_JSON"
    assert len(result.raw_excerpt) <= limit
    assert result.raw_excerpt == long_content[:limit]


def test_post_valid_json_missing_activity_returns_schema_violation():
    """Valid JSON without ``activity`` maps to SCHEMA_VIOLATION (Req 6.5)."""
    client = LLMClient()
    session = _make_session()
    config = _make_config()

    # ``content`` itself is a JSON string carrying a body that is missing
    # the required ``activity`` field.
    content = '{"templates": []}'
    post_resp = MagicMock()
    post_resp.status_code = 200
    post_resp.text = '{"message": {"content": "..."}}'
    post_resp.json.return_value = {"message": {"content": content}}

    with patch(_GET_PATCH, return_value=_ok_get_response()), patch(
        _POST_PATCH, return_value=post_resp
    ):
        result = client.analyze(session, config)

    assert isinstance(result, LLMError)
    assert result.category == "SCHEMA_VIOLATION"
    # The schema validator emits ``path="activity"`` for the missing
    # field; ``LLMClient.message`` embeds that path verbatim.
    assert "activity" in result.message
    assert result.raw_excerpt == content
