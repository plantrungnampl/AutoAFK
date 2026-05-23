"""Network-touching client for the LLM Agent.

Wraps a single ``/api/chat`` request to a local Ollama instance: builds the
multimodal payload, runs the request inside the ``[LLM_TOOLING]`` timeout,
parses the JSON action body, and rescales image-space coordinates back to
device pixels. Auto-retries once on ``INVALID_JSON`` or ``SCHEMA_VIOLATION``.

All failures are returned as :class:`AgentError` rather than raised, so the
GUI can render structured modals without crashing the loop thread.
"""

import base64
import io
import json
import logging
from typing import Iterable, List, Tuple, Union

import requests
from PIL import Image

from src.dev_tools.llm_agent import action_schema, prompt_templates
from src.dev_tools.llm_agent.models import AgentAction, AgentError, AgentStep

logger = logging.getLogger(__name__)


class AgentClient:
    """Drives a single Ollama request for one agent loop iteration.

    Stateless; instantiate one per call or share a single instance across
    a session.
    """

    def next_action(
        self,
        goal: str,
        history: Iterable[AgentStep],
        screenshot: Image.Image,
        config,
    ) -> Union[AgentAction, AgentError]:
        """Ask the LLM for the single next action.

        Args:
            goal: Free-form goal text supplied by the developer.
            history: Most recent :class:`AgentStep` items (already truncated
                to ``history_window``).
            screenshot: Current device screenshot (1080x1920 device pixels).
            config: A ``configparser``-compatible object exposing
                ``.get()``, ``.getint()`` with ``fallback=`` keyword
                arguments. ``[LLM_TOOLING]`` is read.

        Returns:
            An :class:`AgentAction` on success, or an :class:`AgentError`
            describing the failure.
        """
        ollama_host = config.get(
            "LLM_TOOLING", "ollama_host", fallback="http://localhost:11434"
        )
        model_name = config.get(
            "LLM_TOOLING", "model_name", fallback="qwen2.5vl:3b"
        )
        request_timeout_s = config.getint(
            "LLM_TOOLING", "request_timeout_s", fallback=120
        )
        error_excerpt_max_chars = config.getint(
            "LLM_TOOLING", "error_excerpt_max_chars", fallback=2000
        )
        image_max_dim = config.getint(
            "LLM_TOOLING", "image_max_dim", fallback=1024
        )
        num_ctx = config.getint("LLM_TOOLING", "num_ctx", fallback=8192)

        # Reachability probe.
        try:
            requests.get(
                "{}/api/tags".format(ollama_host),
                timeout=request_timeout_s,
            )
        except requests.exceptions.Timeout as err:
            logger.error("ollama_timeout after %ss", request_timeout_s)
            return AgentError(
                category="OLLAMA_TIMEOUT",
                message="Ollama did not respond within {}s at {}.".format(
                    request_timeout_s, ollama_host
                ),
                raw_excerpt=self._truncate(str(err), error_excerpt_max_chars),
                ollama_host=ollama_host,
                model_name=model_name,
            )
        except requests.exceptions.RequestException as err:
            logger.error("ollama_unreachable: %s", err)
            return AgentError(
                category="OLLAMA_UNREACHABLE",
                message="Ollama not reachable at {} (model {}).".format(
                    ollama_host, model_name
                ),
                raw_excerpt=self._truncate(str(err), error_excerpt_max_chars),
                ollama_host=ollama_host,
                model_name=model_name,
            )

        # Resize screenshot.
        device_w, device_h = screenshot.size
        scale = self._compute_scale(device_w, device_h, image_max_dim)
        image_w = max(1, int(round(device_w * scale)))
        image_h = max(1, int(round(device_h * scale)))
        encoded = self._encode_png(screenshot, image_w, image_h)

        system_prompt = prompt_templates.build_system_prompt(image_w, image_h)
        user_message = prompt_templates.format_user_message(goal, history)

        payload = {
            "model": model_name,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2, "num_ctx": num_ctx},
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_message,
                    "images": [encoded],
                },
            ],
        }

        # First attempt + one retry on INVALID_JSON / SCHEMA_VIOLATION.
        last_excerpt = ""
        last_message = ""
        last_error_category = ""
        for attempt in range(2):
            outcome = self._post_once(
                payload, ollama_host, model_name, request_timeout_s,
                error_excerpt_max_chars, image_w, image_h,
            )
            if isinstance(outcome, AgentAction):
                # Rescale coords back to device space.
                inv = 1.0 / scale if scale else 1.0
                return self._rescale_action(outcome, inv, device_w, device_h)
            if outcome.category not in ("INVALID_JSON", "SCHEMA_VIOLATION"):
                return outcome
            # Remember the latest error so we can return it after the retry.
            last_excerpt = outcome.raw_excerpt
            last_message = outcome.message
            last_error_category = outcome.category

        return AgentError(
            category=last_error_category,
            message=last_message,
            raw_excerpt=last_excerpt,
            ollama_host=ollama_host,
            model_name=model_name,
        )

    def _post_once(
        self,
        payload: dict,
        ollama_host: str,
        model_name: str,
        request_timeout_s: int,
        error_excerpt_max_chars: int,
        image_w: int,
        image_h: int,
    ) -> Union[AgentAction, AgentError]:
        try:
            response = requests.post(
                "{}/api/chat".format(ollama_host),
                json=payload,
                timeout=request_timeout_s,
            )
        except requests.exceptions.Timeout as err:
            return AgentError(
                category="OLLAMA_TIMEOUT",
                message="Ollama did not respond within {}s at {}.".format(
                    request_timeout_s, ollama_host
                ),
                raw_excerpt=self._truncate(str(err), error_excerpt_max_chars),
                ollama_host=ollama_host,
                model_name=model_name,
            )
        except requests.exceptions.RequestException as err:
            return AgentError(
                category="OLLAMA_UNREACHABLE",
                message="Ollama not reachable at {} (model {}).".format(
                    ollama_host, model_name
                ),
                raw_excerpt=self._truncate(str(err), error_excerpt_max_chars),
                ollama_host=ollama_host,
                model_name=model_name,
            )

        body_text = response.text or ""
        body_excerpt = self._truncate(body_text, error_excerpt_max_chars)

        if response.status_code == 404 or "model not found" in body_text.lower():
            return AgentError(
                category="MODEL_MISSING",
                message="Model {} not available on {}.".format(
                    model_name, ollama_host
                ),
                raw_excerpt=body_excerpt,
                ollama_host=ollama_host,
                model_name=model_name,
            )
        if response.status_code != 200:
            return AgentError(
                category="OLLAMA_UNREACHABLE",
                message="Ollama returned HTTP {} from {}.".format(
                    response.status_code, ollama_host
                ),
                raw_excerpt=body_excerpt,
                ollama_host=ollama_host,
                model_name=model_name,
            )

        try:
            envelope = response.json()
        except (json.JSONDecodeError, ValueError):
            return AgentError(
                category="INVALID_JSON",
                message="Model returned non-JSON content.",
                raw_excerpt=body_excerpt,
                ollama_host=ollama_host,
                model_name=model_name,
            )

        content = ""
        if isinstance(envelope, dict):
            msg = envelope.get("message")
            if isinstance(msg, dict):
                raw = msg.get("content", "")
                if isinstance(raw, str):
                    content = raw
        content_excerpt = self._truncate(content, error_excerpt_max_chars)

        try:
            inner = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            return AgentError(
                category="INVALID_JSON",
                message="Model returned non-JSON content.",
                raw_excerpt=content_excerpt,
                ollama_host=ollama_host,
                model_name=model_name,
            )

        try:
            action = action_schema.validate(inner, image_w, image_h)
        except action_schema.ActionSchemaError as err:
            return AgentError(
                category="SCHEMA_VIOLATION",
                message=(
                    "Model returned JSON that violates the schema "
                    "at {}: {}"
                ).format(err.path, err.reason),
                raw_excerpt=content_excerpt,
                ollama_host=ollama_host,
                model_name=model_name,
            )
        return action

    @staticmethod
    def _compute_scale(device_w: int, device_h: int, max_dim: int) -> float:
        if max_dim <= 0:
            return 1.0
        longest = max(device_w, device_h)
        if longest <= max_dim:
            return 1.0
        return float(max_dim) / float(longest)

    @staticmethod
    def _encode_png(image: Image.Image, w: int, h: int) -> str:
        buf = io.BytesIO()
        if image.size == (w, h):
            image.save(buf, format="PNG")
        else:
            image.resize((w, h), Image.LANCZOS).save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        if not text:
            return ""
        if limit <= 0:
            return ""
        if len(text) <= limit:
            return text
        return text[:limit]

    @staticmethod
    def _rescale_action(
        action: AgentAction, inv_scale: float, device_w: int, device_h: int,
    ) -> AgentAction:
        if action.kind == "tap":
            x = int(round(action.x * inv_scale))
            y = int(round(action.y * inv_scale))
            x = max(0, min(device_w - 1, x))
            y = max(0, min(device_h - 1, y))
            return AgentAction(
                kind="tap", rationale=action.rationale, x=x, y=y,
            )
        if action.kind == "swipe":
            def _scale(v: int, axis_max: int) -> int:
                return max(0, min(axis_max - 1, int(round(v * inv_scale))))
            return AgentAction(
                kind="swipe", rationale=action.rationale,
                x1=_scale(action.x1, device_w), y1=_scale(action.y1, device_h),
                x2=_scale(action.x2, device_w), y2=_scale(action.y2, device_h),
            )
        return action
