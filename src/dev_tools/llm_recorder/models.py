"""Data models for the LLM Flow Recorder.

This module defines the in-memory dataclasses used by the dev-time-only
LLM Flow Recorder tool. All classes are mutable (``frozen=False``) because
the developer edits proposals (bbox, filename, source text) in the GUI
before saving.

Python 3.8-compatible: uses ``Tuple``/``List``/``Optional`` from ``typing``;
no PEP 604 ``X | Y`` unions.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from PIL import Image


@dataclass
class RecordedStep:
    """One ordered step in a ``RecordingSession``.

    Attributes:
        index: 0-based position of this step inside the session.
        screenshot_before: PIL image captured before the tap, at 1080x1920.
        screenshot_after: PIL image captured after the tap, at 1080x1920.
        tap_coords: ``(x, y)`` in device pixels (1080 wide x 1920 tall).
        label: Optional developer-supplied note for this step.
    """

    index: int
    screenshot_before: Image.Image
    screenshot_after: Image.Image
    tap_coords: Tuple[int, int]
    label: Optional[str] = None


@dataclass
class RecordingSession:
    """Ordered list of ``RecordedStep`` entries for one developer recording.

    Attributes:
        steps: Recorded steps in click order.
        device_resolution: ``(width, height)`` in device pixels. Defaults
            to ``(1080, 1920)`` matching the AutoAFK target resolution.
        started_at: Epoch seconds when the recording began.
    """

    steps: List[RecordedStep] = field(default_factory=list)
    device_resolution: Tuple[int, int] = (1080, 1920)
    started_at: float = 0.0


@dataclass
class TemplateProposal:
    """LLM proposal for one cropped template image.

    Attributes:
        source_step_index: Index of the ``RecordedStep`` this crop came from.
        bbox: ``(x, y, width, height)`` in device pixels.
        filename: Relative path under ``img/``, e.g.
            ``"buttons/event_claim.png"``.
        rationale: Short human-readable reason, surfaced in the review UI.
        accepted: Set to ``True`` when the developer clicks Save for this
            proposal.
    """

    source_step_index: int
    bbox: Tuple[int, int, int, int]
    filename: str
    rationale: str = ""
    accepted: bool = False


@dataclass
class ActivityProposal:
    """LLM proposal for one Python activity module.

    Attributes:
        module_filename: Target filename inside ``src/activities/``,
            e.g. ``"event_x_activities.py"``.
        class_name: PascalCase class name ending in ``Activities``,
            e.g. ``"EventXActivities"``.
        source_text: Full editable Python source for the module.
        registration_snippet: Single-line snippet for
            ``ActivityManager.__init__()``.
        call_site_snippet: Snippet for ``dailies_runner.py`` gated on the
            config toggle.
        config_section: One of the existing ``settings.ini`` section names
            (e.g. ``"DAILIES"``).
        config_key: Lowercase snake_case key under that section
            (e.g. ``"runeventx"``).
        rationale: Short human-readable reason, surfaced in the review UI.
        accepted: Set to ``True`` when the developer clicks Save for this
            proposal.
    """

    module_filename: str
    class_name: str
    source_text: str
    registration_snippet: str
    call_site_snippet: str
    config_section: str
    config_key: str
    rationale: str = ""
    accepted: bool = False


@dataclass
class LLMError:
    """Structured error returned by ``LLMClient`` when a request fails.

    Attributes:
        category: Error category identifier (e.g. ``"OLLAMA_UNREACHABLE"``,
            ``"OLLAMA_TIMEOUT"``, ``"MODEL_MISSING"``, ``"INVALID_JSON"``,
            ``"SCHEMA_VIOLATION"``, ``"EMPTY_SESSION"``).
        message: Human-readable summary suitable for surfacing in the GUI.
        raw_excerpt: Truncated upstream response or error text.
        ollama_host: The Ollama host URL used for the request.
        model_name: The Ollama model name used for the request.
    """

    category: str
    message: str
    raw_excerpt: str
    ollama_host: str
    model_name: str
