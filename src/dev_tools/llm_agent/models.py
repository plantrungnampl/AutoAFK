"""Data models for the LLM Agent.

Dataclasses are mutable (frozen=False) because the GUI displays partially-
filled steps as the loop runs. Python 3.8-compatible — uses ``Optional``,
``List``, ``Tuple`` from ``typing``, no PEP 604 union syntax.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from PIL import Image


@dataclass
class AgentAction:
    """One action proposed by the LLM.

    Attributes:
        kind: One of ``"tap"``, ``"swipe"``, ``"wait"``, ``"done"``.
        rationale: One-sentence justification surfaced in the UI.
        x: Tap x-coordinate in device pixels (only when ``kind == "tap"``).
        y: Tap y-coordinate in device pixels (only when ``kind == "tap"``).
        x1: Swipe start x (only when ``kind == "swipe"``).
        y1: Swipe start y (only when ``kind == "swipe"``).
        x2: Swipe end x (only when ``kind == "swipe"``).
        y2: Swipe end y (only when ``kind == "swipe"``).
        seconds: Wait duration in seconds (only when ``kind == "wait"``).
        done_reason: Completion summary (only when ``kind == "done"``).
    """

    kind: str
    rationale: str = ""
    x: Optional[int] = None
    y: Optional[int] = None
    x1: Optional[int] = None
    y1: Optional[int] = None
    x2: Optional[int] = None
    y2: Optional[int] = None
    seconds: float = 1.0
    done_reason: str = ""


@dataclass
class AgentStep:
    """One iteration of the loop, kept for history display.

    Attributes:
        index: 0-based step number within the session.
        screenshot: Device screenshot at the moment the LLM was called
            (1080x1920 device pixels).
        proposed: Action the LLM returned.
        approved: ``True`` after the user clicks Approve (or trust mode auto-
            approves), ``False`` after Skip.
        executed: ``True`` after the action ran successfully against ADB.
    """

    index: int
    screenshot: Image.Image
    proposed: AgentAction
    approved: bool = False
    executed: bool = False


@dataclass
class AgentSession:
    """In-memory state of one agent run.

    Attributes:
        goal: Free-form text the developer entered.
        steps: Steps in order; latest is at the end.
        device_resolution: ``(width, height)`` in device pixels. Defaults
            to ``(1080, 1920)``.
        max_steps: Hard cap; the loop aborts with ``MAX_STEPS`` once
            ``len(steps) >= max_steps`` and the LLM has not returned ``done``.
        history_window: How many previous steps' rationale + action to
            forward to the LLM with the next request.
        trust_mode: When ``True``, the loop skips the confirm dialog.
    """

    goal: str
    steps: List[AgentStep] = field(default_factory=list)
    device_resolution: Tuple[int, int] = (1080, 1920)
    max_steps: int = 20
    history_window: int = 3
    trust_mode: bool = False


@dataclass
class AgentError:
    """Structured error returned by ``AgentClient`` or ``AgentLoop``.

    Attributes:
        category: One of ``OLLAMA_UNREACHABLE``, ``OLLAMA_TIMEOUT``,
            ``MODEL_MISSING``, ``INVALID_JSON``, ``SCHEMA_VIOLATION``,
            ``ADB_FAILURE``, ``MAX_STEPS``, ``USER_STOP``.
        message: Human-readable summary suitable for a modal.
        raw_excerpt: Truncated upstream response or error text.
        ollama_host: Configured Ollama URL.
        model_name: Configured model name.
    """

    category: str
    message: str
    raw_excerpt: str = ""
    ollama_host: str = ""
    model_name: str = ""
