"""Schema validator for the Ollama response body.

This module enforces the output JSON schema documented in ``design.md``
under "Output JSON schema sent to / required from Ollama". It uses only
the Python standard library so the recorder itself never depends on the
optional ``jsonschema`` dev package (Req 12.6).

The validator raises :class:`SchemaError` on the first violation. The
caller (``LLMClient``) is responsible for converting it into an
``LLMError(category="SCHEMA_VIOLATION", ...)``.

Python 3.8-compatible.
"""

import re
from typing import Any


# Regex constants — kept identical to the rules listed in design.md so
# the prompt copy and the validator agree on what "valid" means.
_TEMPLATE_FILENAME_RE = re.compile(r"^(buttons|labels)/[a-z0-9_]+\.png$")
_MODULE_FILENAME_RE = re.compile(r"^[a-z][a-z0-9_]*_activities\.py$")
_CLASS_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9]*Activities$")
_CONFIG_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")

_ALLOWED_CONFIG_SECTIONS = frozenset({
    "ADVANCED",
    "DISCORD",
    "TELEGRAM",
    "DAILIES",
    "ARENA",
    "EVENTS",
    "BOUNTIES",
    "PUSH",
})

# Device pixel bounds used for bbox checks. The design treats the device
# as 1080x1920 portrait; see "Open Issues / Risks" entry 5 in design.md.
_DEVICE_W = 1080
_DEVICE_H = 1920

_BBOX_KEYS = ("x", "y", "w", "h")


class SchemaError(Exception):
    """Raised on the first schema rule violation in a response body.

    Attributes:
        path: JSONPath-style location of the offending field, e.g.
            ``"templates[2].bbox.w"`` or ``"activity.config_section"``.
        reason: One-line human-readable explanation of the violation.
    """

    def __init__(self, path: str, reason: str) -> None:
        """Initialize the error.

        Args:
            path: JSONPath-style location of the offending field.
            reason: One-line human-readable explanation.
        """
        self.path = path
        self.reason = reason
        super().__init__("{}: {}".format(path, reason))


def _is_int(value: Any) -> bool:
    """Return ``True`` if ``value`` is an ``int`` (excluding ``bool``)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_bbox(bbox: Any, path: str, max_w: int, max_h: int) -> None:
    """Validate a single template bbox dict in-place.

    Args:
        bbox: The candidate bbox value.
        path: JSONPath prefix used when reporting violations.
        max_w: Inclusive upper bound for ``x + w``.
        max_h: Inclusive upper bound for ``y + h``.

    Raises:
        SchemaError: On the first failing rule.
    """
    if not isinstance(bbox, dict):
        raise SchemaError(path, "must be an object")
    for key in _BBOX_KEYS:
        if key not in bbox:
            raise SchemaError("{}.{}".format(path, key), "missing required field")
        if not _is_int(bbox[key]):
            raise SchemaError("{}.{}".format(path, key), "must be an integer")

    x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
    if x < 0:
        raise SchemaError("{}.x".format(path), "must be >= 0")
    if y < 0:
        raise SchemaError("{}.y".format(path), "must be >= 0")
    if w < 1:
        raise SchemaError("{}.w".format(path), "must be >= 1")
    if h < 1:
        raise SchemaError("{}.h".format(path), "must be >= 1")
    if x + w > max_w:
        raise SchemaError(
            "{}.w".format(path),
            "x + w must be <= {}".format(max_w),
        )
    if y + h > max_h:
        raise SchemaError(
            "{}.h".format(path),
            "y + h must be <= {}".format(max_h),
        )


def _validate_template(tpl: Any, path: str, max_w: int, max_h: int) -> None:
    """Validate a single ``templates[i]`` entry.

    Args:
        tpl: The candidate template object.
        path: JSONPath prefix (e.g. ``"templates[0]"``).

    Raises:
        SchemaError: On the first failing rule.
    """
    if not isinstance(tpl, dict):
        raise SchemaError(path, "must be an object")

    if "source_step_index" not in tpl:
        raise SchemaError(
            "{}.source_step_index".format(path), "missing required field"
        )
    idx = tpl["source_step_index"]
    if not _is_int(idx):
        raise SchemaError(
            "{}.source_step_index".format(path), "must be an integer"
        )
    if idx < 0:
        raise SchemaError(
            "{}.source_step_index".format(path), "must be >= 0"
        )

    if "bbox" not in tpl:
        raise SchemaError("{}.bbox".format(path), "missing required field")
    _validate_bbox(tpl["bbox"], "{}.bbox".format(path), max_w, max_h)

    if "filename" not in tpl:
        raise SchemaError("{}.filename".format(path), "missing required field")
    filename = tpl["filename"]
    if not isinstance(filename, str):
        raise SchemaError("{}.filename".format(path), "must be a string")
    if not _TEMPLATE_FILENAME_RE.match(filename):
        raise SchemaError(
            "{}.filename".format(path),
            "must match ^(buttons|labels)/[a-z0-9_]+\\.png$",
        )

    if "rationale" not in tpl:
        raise SchemaError(
            "{}.rationale".format(path), "missing required field"
        )
    if not isinstance(tpl["rationale"], str):
        raise SchemaError("{}.rationale".format(path), "must be a string")


def _validate_non_empty_string(value: Any, path: str) -> None:
    """Raise ``SchemaError`` unless ``value`` is a non-empty ``str``."""
    if not isinstance(value, str):
        raise SchemaError(path, "must be a string")
    if not value:
        raise SchemaError(path, "must be a non-empty string")


def _validate_activity(activity: Any, path: str) -> None:
    """Validate the ``activity`` object.

    Args:
        activity: The candidate activity object.
        path: JSONPath prefix (always ``"activity"`` from the public entry).

    Raises:
        SchemaError: On the first failing rule.
    """
    if not isinstance(activity, dict):
        raise SchemaError(path, "must be an object")

    # module_filename
    if "module_filename" not in activity:
        raise SchemaError(
            "{}.module_filename".format(path), "missing required field"
        )
    module_filename = activity["module_filename"]
    if not isinstance(module_filename, str):
        raise SchemaError(
            "{}.module_filename".format(path), "must be a string"
        )
    if not _MODULE_FILENAME_RE.match(module_filename):
        raise SchemaError(
            "{}.module_filename".format(path),
            "must match ^[a-z][a-z0-9_]*_activities\\.py$",
        )

    # class_name
    if "class_name" not in activity:
        raise SchemaError(
            "{}.class_name".format(path), "missing required field"
        )
    class_name = activity["class_name"]
    if not isinstance(class_name, str):
        raise SchemaError("{}.class_name".format(path), "must be a string")
    if not _CLASS_NAME_RE.match(class_name):
        raise SchemaError(
            "{}.class_name".format(path),
            "must match ^[A-Z][A-Za-z0-9]*Activities$",
        )

    # source_text — non-empty string (ast.parse is checked at save time, not here)
    if "source_text" not in activity:
        raise SchemaError(
            "{}.source_text".format(path), "missing required field"
        )
    _validate_non_empty_string(
        activity["source_text"], "{}.source_text".format(path)
    )

    # config_section
    if "config_section" not in activity:
        raise SchemaError(
            "{}.config_section".format(path), "missing required field"
        )
    config_section = activity["config_section"]
    if not isinstance(config_section, str):
        raise SchemaError(
            "{}.config_section".format(path), "must be a string"
        )
    if config_section not in _ALLOWED_CONFIG_SECTIONS:
        allowed = ", ".join(sorted(_ALLOWED_CONFIG_SECTIONS))
        raise SchemaError(
            "{}.config_section".format(path),
            "must be one of: {}".format(allowed),
        )

    # config_key
    if "config_key" not in activity:
        raise SchemaError(
            "{}.config_key".format(path), "missing required field"
        )
    config_key = activity["config_key"]
    if not isinstance(config_key, str):
        raise SchemaError("{}.config_key".format(path), "must be a string")
    if not _CONFIG_KEY_RE.match(config_key):
        raise SchemaError(
            "{}.config_key".format(path),
            "must match ^[a-z][a-z0-9_]*$",
        )

    # registration_snippet
    if "registration_snippet" not in activity:
        raise SchemaError(
            "{}.registration_snippet".format(path), "missing required field"
        )
    _validate_non_empty_string(
        activity["registration_snippet"],
        "{}.registration_snippet".format(path),
    )

    # call_site_snippet
    if "call_site_snippet" not in activity:
        raise SchemaError(
            "{}.call_site_snippet".format(path), "missing required field"
        )
    _validate_non_empty_string(
        activity["call_site_snippet"],
        "{}.call_site_snippet".format(path),
    )


def validate(body: dict, max_w: int = _DEVICE_W, max_h: int = _DEVICE_H) -> None:
    """Validate an Ollama response body against the recorder's schema.

    Enforces the rules from ``design.md``'s "Output JSON schema sent to /
    required from Ollama" table. Raises :class:`SchemaError` on the first
    violation; returns ``None`` on success.

    Args:
        body: Parsed JSON object returned by the model.
        max_w: Inclusive upper bound for ``bbox.x + bbox.w``. Defaults to
            the device width (1080) so callers that don't downscale see
            no behavior change. ``LLMClient`` passes the downscaled image
            width when ``image_max_dim`` is configured.
        max_h: Same as ``max_w`` for the height axis.

    Raises:
        SchemaError: When any rule is violated. ``path`` identifies the
            offending field (e.g. ``"templates[2].bbox.w"``) and
            ``reason`` is a one-line explanation.
    """
    if not isinstance(body, dict):
        raise SchemaError("", "response body must be a JSON object")

    if "templates" not in body:
        raise SchemaError("templates", "missing required field")
    templates = body["templates"]
    if not isinstance(templates, list):
        raise SchemaError("templates", "must be a list")
    for i, tpl in enumerate(templates):
        _validate_template(tpl, "templates[{}]".format(i), max_w, max_h)

    if "activity" not in body:
        raise SchemaError("activity", "missing required field")
    _validate_activity(body["activity"], "activity")
