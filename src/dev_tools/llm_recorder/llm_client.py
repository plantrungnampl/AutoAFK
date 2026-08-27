"""LLM Client for the LLM Flow Recorder.

Sends a recorded session to a local Ollama instance, validates the
returned JSON against the recorder's schema, and converts it into a
``(list[TemplateProposal], ActivityProposal)`` tuple. All failures are
returned as :class:`LLMError` instances rather than raised exceptions so
the GUI can render them as modal dialogs without crashing.

The ``[LLM_TOOLING] enabled`` flag is enforced by the GUI (the "Analyze
with LLM" button is ``state="disabled"`` when ``enabled=False``); this
client therefore does not re-check the flag.

Python 3.8-compatible.
"""

import base64
import io
import json
import logging
from typing import List, Tuple, Union

import requests
from PIL import Image

from src.dev_tools.llm_recorder import prompt_templates, schema
from src.dev_tools.llm_recorder.models import (
    ActivityProposal,
    LLMError,
    RecordingSession,
    TemplateProposal,
)

logger = logging.getLogger(__name__)


class LLMClient:
    """Drives the Ollama analysis request for a ``RecordingSession``.

    The client is stateless; instantiate one per call (or share one across
    the GUI's lifetime — both are safe).
    """

    def analyze(
        self,
        session: RecordingSession,
        config,
    ) -> Union[Tuple[List[TemplateProposal], ActivityProposal], LLMError]:
        """Run analysis on ``session`` via the configured Ollama instance.

        Reads ``[LLM_TOOLING]`` keys from ``config`` with the fallbacks
        documented in the design's Configuration table:

        ============================ ===========================
        Key                          Default
        ============================ ===========================
        ``ollama_host``              ``http://localhost:11434``
        ``model_name``               ``qwen2.5vl:7b``
        ``request_timeout_s``        ``120``
        ``error_excerpt_max_chars``  ``2000``
        ============================ ===========================

        ``enabled`` is read by the GUI, not by this method.

        Args:
            session: The recording to analyze.
            config: A ``configparser``-compatible object exposing
                ``.get()``, ``.getint()``, and ``.getboolean()`` with
                ``fallback=`` keyword arguments.

        Returns:
            On success, a ``(templates, activity)`` tuple where
            ``templates`` is a possibly-empty list of
            :class:`TemplateProposal` and ``activity`` is the single
            :class:`ActivityProposal`.
            On failure, an :class:`LLMError` describing the failure.
        """
        ollama_host = config.get(
            "LLM_TOOLING", "ollama_host", fallback="http://localhost:11434"
        )
        model_name = config.get(
            "LLM_TOOLING", "model_name", fallback="qwen2.5vl:7b"
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
        num_ctx = config.getint(
            "LLM_TOOLING", "num_ctx", fallback=8192
        )

        # Pre-flight: zero-step sessions never hit the network.
        if len(session.steps) == 0:
            return LLMError(
                category="EMPTY_SESSION",
                message="Cannot analyze: recording session has no steps.",
                raw_excerpt="",
                ollama_host=ollama_host,
                model_name=model_name,
            )

        # Downscale screenshots to keep payload + vision tokens small.
        device_w, device_h = session.device_resolution
        scale = self._compute_scale(device_w, device_h, image_max_dim)
        image_w = max(1, int(round(device_w * scale)))
        image_h = max(1, int(round(device_h * scale)))

        # Reachability probe (Req 5.1).
        try:
            requests.get(
                "{}/api/tags".format(ollama_host),
                timeout=request_timeout_s,
            )
        except requests.exceptions.Timeout as err:
            logger.error("ollama_timeout after %ss", request_timeout_s)
            return LLMError(
                category="OLLAMA_TIMEOUT",
                message="Ollama did not respond within {}s at {}.".format(
                    request_timeout_s, ollama_host
                ),
                raw_excerpt=self._truncate(str(err), error_excerpt_max_chars),
                ollama_host=ollama_host,
                model_name=model_name,
            )
        except requests.exceptions.RequestException as err:
            logger.error("ollama_unreachable: %s: %s", ollama_host, err)
            return LLMError(
                category="OLLAMA_UNREACHABLE",
                message="Ollama not reachable at {} (model {}).".format(
                    ollama_host, model_name
                ),
                raw_excerpt=self._truncate(str(err), error_excerpt_max_chars),
                ollama_host=ollama_host,
                model_name=model_name,
            )

        # Build the multimodal /api/chat payload.
        messages = [
            {
                "role": "system",
                "content": prompt_templates.build_system_prompt(image_w, image_h),
            }
        ]
        for step in session.steps:
            messages.append(
                {
                    "role": "user",
                    "content": prompt_templates.format_user_message(
                        step,
                        image_w=image_w,
                        image_h=image_h,
                        scale_factor=scale,
                    ),
                    "images": [
                        self._encode_png(step.screenshot_before, image_w, image_h),
                        self._encode_png(step.screenshot_after, image_w, image_h),
                    ],
                }
            )
        messages.append(
            {"role": "user", "content": prompt_templates.CLOSING_INSTRUCTION}
        )
        payload = {
            "model": model_name,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2, "num_ctx": num_ctx},
            "messages": messages,
        }

        # POST /api/chat.
        try:
            response = requests.post(
                "{}/api/chat".format(ollama_host),
                json=payload,
                timeout=request_timeout_s,
            )
        except requests.exceptions.Timeout as err:
            logger.error("ollama_timeout after %ss", request_timeout_s)
            return LLMError(
                category="OLLAMA_TIMEOUT",
                message="Ollama did not respond within {}s at {}.".format(
                    request_timeout_s, ollama_host
                ),
                raw_excerpt=self._truncate(str(err), error_excerpt_max_chars),
                ollama_host=ollama_host,
                model_name=model_name,
            )
        except requests.exceptions.RequestException as err:
            logger.error("ollama_unreachable: %s: %s", ollama_host, err)
            return LLMError(
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

        # Status-code- and body-based MODEL_MISSING detection (Req 5.3).
        if response.status_code == 404 or "model not found" in body_text.lower():
            logger.error(
                "ollama_model_missing: %s: %s", model_name, body_excerpt
            )
            return LLMError(
                category="MODEL_MISSING",
                message="Model {} not available on {}.".format(
                    model_name, ollama_host
                ),
                raw_excerpt=body_excerpt,
                ollama_host=ollama_host,
                model_name=model_name,
            )

        if response.status_code != 200:
            logger.error(
                "ollama_unreachable: %s status=%s body=%s",
                ollama_host,
                response.status_code,
                body_excerpt,
            )
            return LLMError(
                category="OLLAMA_UNREACHABLE",
                message="Ollama returned HTTP {} from {}.".format(
                    response.status_code, ollama_host
                ),
                raw_excerpt=body_excerpt,
                ollama_host=ollama_host,
                model_name=model_name,
            )

        # Parse the outer JSON envelope first.
        try:
            resp_json = response.json()
        except (json.JSONDecodeError, ValueError):
            logger.error(
                "llm_invalid_response: INVALID_JSON: %s", body_excerpt
            )
            return LLMError(
                category="INVALID_JSON",
                message="Model returned non-JSON content.",
                raw_excerpt=body_excerpt,
                ollama_host=ollama_host,
                model_name=model_name,
            )

        # Extract the model's content string and parse it as JSON
        # (Ollama wraps the model output in a `message.content` field).
        content = ""
        if isinstance(resp_json, dict):
            message_obj = resp_json.get("message")
            if isinstance(message_obj, dict):
                raw_content = message_obj.get("content", "")
                if isinstance(raw_content, str):
                    content = raw_content

        content_excerpt = self._truncate(content, error_excerpt_max_chars)

        try:
            body = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            logger.error(
                "llm_invalid_response: INVALID_JSON: %s", content_excerpt
            )
            return LLMError(
                category="INVALID_JSON",
                message="Model returned non-JSON content.",
                raw_excerpt=content_excerpt,
                ollama_host=ollama_host,
                model_name=model_name,
            )

        # Schema validation.
        try:
            schema.validate(body, max_w=image_w, max_h=image_h)
        except schema.SchemaError as err:
            logger.error(
                "llm_invalid_response: SCHEMA_VIOLATION at %s: %s",
                err.path,
                err.reason,
            )
            return LLMError(
                category="SCHEMA_VIOLATION",
                message=(
                    "Model returned JSON that violates the schema "
                    "at {}: {}"
                ).format(err.path, err.reason),
                raw_excerpt=content_excerpt,
                ollama_host=ollama_host,
                model_name=model_name,
            )

        # Build proposals from the validated dict. Bboxes come back in
        # the (downscaled) image coordinate space; rescale them to the
        # device coordinate space the rest of the recorder uses.
        inv_scale = 1.0 / scale if scale else 1.0
        templates = []  # type: List[TemplateProposal]
        for tpl in body["templates"]:
            bbox = tpl["bbox"]
            x_dev = int(round(bbox["x"] * inv_scale))
            y_dev = int(round(bbox["y"] * inv_scale))
            w_dev = max(1, int(round(bbox["w"] * inv_scale)))
            h_dev = max(1, int(round(bbox["h"] * inv_scale)))
            # Clamp the rescaled bbox to device bounds so a rounding
            # overflow never trips TemplateSaver's bbox check.
            if x_dev + w_dev > device_w:
                w_dev = device_w - x_dev
            if y_dev + h_dev > device_h:
                h_dev = device_h - y_dev
            templates.append(
                TemplateProposal(
                    source_step_index=tpl["source_step_index"],
                    bbox=(x_dev, y_dev, w_dev, h_dev),
                    filename=tpl["filename"],
                    rationale=tpl.get("rationale", ""),
                )
            )

        if len(templates) == 0:
            logger.purple(
                "LLM returned 0 templates; falling back to activity-only"
            )

        a = body["activity"]
        activity = ActivityProposal(
            module_filename=a["module_filename"],
            class_name=a["class_name"],
            source_text=a["source_text"],
            registration_snippet=a["registration_snippet"],
            call_site_snippet=a["call_site_snippet"],
            config_section=a["config_section"],
            config_key=a["config_key"],
            rationale=a.get("rationale", ""),
        )

        return (templates, activity)

    @staticmethod
    def _compute_scale(device_w: int, device_h: int, max_dim: int) -> float:
        """Return a uniform scale factor that fits the image within ``max_dim``.

        Uses the longer axis so portrait and landscape device captures
        both reach exactly ``max_dim`` on their largest side. Returns
        ``1.0`` (no resize) when ``max_dim`` is already at least as
        large as both axes.

        Args:
            device_w: Source width in pixels.
            device_h: Source height in pixels.
            max_dim: Desired maximum of (width, height) in pixels.

        Returns:
            A float in ``(0, 1]`` such that
            ``round(device_w * scale) <= max_dim`` and likewise for height.
        """
        if max_dim <= 0:
            return 1.0
        longest = max(device_w, device_h)
        if longest <= max_dim:
            return 1.0
        return float(max_dim) / float(longest)

    @staticmethod
    def _encode_png(image, target_w: int, target_h: int) -> str:
        """Resize ``image`` to ``target_w x target_h`` and base64-encode it.

        Args:
            image: A PIL ``Image.Image`` instance (typically 1080x1920).
            target_w: Output width in pixels.
            target_h: Output height in pixels.

        Returns:
            ASCII base64 string with no MIME prefix.
        """
        buf = io.BytesIO()
        if image.size == (target_w, target_h):
            image.save(buf, format="PNG")
        else:
            resized = image.resize((target_w, target_h), Image.LANCZOS)
            resized.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        """Truncate ``text`` to at most ``limit`` characters.

        Per the design's ``error_excerpt_max_chars`` contract, the result
        never exceeds ``limit``.

        Args:
            text: Text to truncate; ``None`` is treated as ``""``.
            limit: Maximum length in characters; non-positive values
                short-circuit to an empty string.

        Returns:
            ``text`` itself when its length is ``<= limit``, otherwise
            ``text[:limit]``.
        """
        if not text:
            return ""
        if limit <= 0:
            return ""
        if len(text) <= limit:
            return text
        return text[:limit]
