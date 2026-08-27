"""Action-schema validator for ``AgentClient``.

Parses the JSON object the LLM returns into a typed :class:`AgentAction`,
raising :class:`ActionSchemaError` on the first violation. Stdlib only.
Python 3.8-compatible.
"""

from typing import Any

from src.dev_tools.llm_agent.models import AgentAction

_ALLOWED_KINDS = frozenset({"tap", "swipe", "wait", "done"})

# Wait duration bounds match the system prompt (0.5..5.0).
_MIN_WAIT = 0.5
_MAX_WAIT = 5.0


class ActionSchemaError(Exception):
    """Raised on the first schema rule violation in an action body.

    Attributes:
        path: The offending field name (e.g. ``"kind"`` or ``"x"``).
        reason: One-line explanation.
    """

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__("{}: {}".format(path, reason))


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _validate_coord(value: Any, path: str, max_excl: int) -> int:
    """Validate one integer coordinate in ``[0, max_excl)``."""
    if not _is_int(value):
        raise ActionSchemaError(path, "must be an integer")
    if value < 0:
        raise ActionSchemaError(path, "must be >= 0")
    if value >= max_excl:
        raise ActionSchemaError(path, "must be < {}".format(max_excl))
    return value


def validate(body: dict, image_w: int, image_h: int) -> AgentAction:
    """Validate ``body`` and return a typed :class:`AgentAction`.

    Args:
        body: Parsed JSON object from the model.
        image_w: Image-space width the LLM was prompted with. Coordinates
            are checked against ``[0, image_w)``.
        image_h: Image-space height. Same semantics as ``image_w``.

    Returns:
        A fully populated :class:`AgentAction`.

    Raises:
        ActionSchemaError: On the first rule violation. ``path`` names the
            offending field and ``reason`` explains why.
    """
    if not isinstance(body, dict):
        raise ActionSchemaError("", "response body must be a JSON object")
    if "kind" not in body:
        raise ActionSchemaError("kind", "missing required field")
    kind = body["kind"]
    if not isinstance(kind, str):
        raise ActionSchemaError("kind", "must be a string")
    if kind not in _ALLOWED_KINDS:
        raise ActionSchemaError(
            "kind",
            "must be one of: {}".format(", ".join(sorted(_ALLOWED_KINDS))),
        )

    rationale = body.get("rationale", "")
    if not isinstance(rationale, str):
        raise ActionSchemaError("rationale", "must be a string")

    if kind == "tap":
        if "x" not in body:
            raise ActionSchemaError("x", "missing required field")
        if "y" not in body:
            raise ActionSchemaError("y", "missing required field")
        x = _validate_coord(body["x"], "x", image_w)
        y = _validate_coord(body["y"], "y", image_h)
        return AgentAction(kind="tap", rationale=rationale, x=x, y=y)

    if kind == "swipe":
        for axis_key, max_excl in (
            ("x1", image_w), ("y1", image_h),
            ("x2", image_w), ("y2", image_h),
        ):
            if axis_key not in body:
                raise ActionSchemaError(axis_key, "missing required field")
        x1 = _validate_coord(body["x1"], "x1", image_w)
        y1 = _validate_coord(body["y1"], "y1", image_h)
        x2 = _validate_coord(body["x2"], "x2", image_w)
        y2 = _validate_coord(body["y2"], "y2", image_h)
        return AgentAction(
            kind="swipe",
            rationale=rationale,
            x1=x1, y1=y1, x2=x2, y2=y2,
        )

    if kind == "wait":
        if "seconds" not in body:
            raise ActionSchemaError("seconds", "missing required field")
        seconds = body["seconds"]
        if not _is_number(seconds):
            raise ActionSchemaError("seconds", "must be a number")
        if seconds < _MIN_WAIT or seconds > _MAX_WAIT:
            raise ActionSchemaError(
                "seconds",
                "must be in [{}, {}]".format(_MIN_WAIT, _MAX_WAIT),
            )
        return AgentAction(
            kind="wait", rationale=rationale, seconds=float(seconds)
        )

    # kind == "done"
    if "done_reason" not in body:
        raise ActionSchemaError("done_reason", "missing required field")
    done_reason = body["done_reason"]
    if not isinstance(done_reason, str):
        raise ActionSchemaError("done_reason", "must be a string")
    if not done_reason:
        raise ActionSchemaError("done_reason", "must be a non-empty string")
    return AgentAction(kind="done", done_reason=done_reason)
