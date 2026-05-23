"""Unit tests for ``src.dev_tools.llm_recorder.schema``.

The fixture mirrors the example response body from ``design.md`` under
"Output JSON schema sent to / required from Ollama". Each test deep-copies
the valid body and mutates a single field, asserting that
:class:`SchemaError` is raised with ``path`` pointing at the violated
field.
"""

import copy

import pytest

from src.dev_tools.llm_recorder.schema import SchemaError, validate


def _valid_body() -> dict:
    """Return a fresh deep copy of the design's example response body."""
    return copy.deepcopy(
        {
            "templates": [
                {
                    "source_step_index": 0,
                    "bbox": {"x": 100, "y": 200, "w": 300, "h": 80},
                    "filename": "buttons/event_claim.png",
                    "rationale": "tapped region holds the Claim button",
                }
            ],
            "activity": {
                "module_filename": "event_x_activities.py",
                "class_name": "EventXActivities",
                "source_text": "<full python source>",
                "registration_snippet": (
                    "self.event_x = EventXActivities(device_manager, "
                    "image_recognition, game_controller, config, "
                    "notification_manager)"
                ),
                "call_site_snippet": (
                    "if config.getboolean('DAILIES', 'runeventx', "
                    "fallback=False):\n    activity_manager.event_x.run()"
                ),
                "config_section": "DAILIES",
                "config_key": "runeventx",
                "rationale": "drafted activity module for the recorded flow",
            },
        }
    )


def test_valid_body_accepted():
    """A fully-valid response from the design's example JSON passes."""
    validate(_valid_body())


def test_empty_templates_accepted():
    """``templates: []`` is allowed (Req 6.3, 10.3)."""
    body = _valid_body()
    body["templates"] = []
    validate(body)


def test_missing_activity_rejected():
    """Removing ``activity`` triggers ``path == "activity"``."""
    body = _valid_body()
    del body["activity"]
    with pytest.raises(SchemaError) as exc:
        validate(body)
    assert exc.value.path == "activity"


def test_activity_config_section_not_in_allowlist_rejected():
    """``GENERAL`` is not in the 8-name allowlist."""
    body = _valid_body()
    body["activity"]["config_section"] = "GENERAL"
    with pytest.raises(SchemaError) as exc:
        validate(body)
    assert exc.value.path == "activity.config_section"


def test_activity_module_filename_regex_miss_rejected():
    """``Foo.py`` lacks the ``_activities.py`` suffix and starts uppercase."""
    body = _valid_body()
    body["activity"]["module_filename"] = "Foo.py"
    with pytest.raises(SchemaError) as exc:
        validate(body)
    assert exc.value.path == "activity.module_filename"


def test_activity_class_name_regex_miss_rejected():
    """``fooActivities`` does not start with an uppercase letter."""
    body = _valid_body()
    body["activity"]["class_name"] = "fooActivities"
    with pytest.raises(SchemaError) as exc:
        validate(body)
    assert exc.value.path == "activity.class_name"


def test_activity_config_key_uppercase_rejected():
    """``RunFoo`` violates the lowercase ``[a-z][a-z0-9_]*`` rule."""
    body = _valid_body()
    body["activity"]["config_key"] = "RunFoo"
    with pytest.raises(SchemaError) as exc:
        validate(body)
    assert exc.value.path == "activity.config_key"


def test_templates_bbox_x_plus_w_exceeds_device_width_rejected():
    """``x=1000, w=200`` overflows the 1080 device width on the ``w`` axis."""
    body = _valid_body()
    body["templates"][0]["bbox"] = {"x": 1000, "y": 0, "w": 200, "h": 50}
    with pytest.raises(SchemaError) as exc:
        validate(body)
    assert exc.value.path == "templates[0].bbox.w"


def test_templates_bbox_w_below_one_rejected():
    """``w == 0`` violates ``w >= 1``."""
    body = _valid_body()
    body["templates"][0]["bbox"] = {"x": 0, "y": 0, "w": 0, "h": 50}
    with pytest.raises(SchemaError) as exc:
        validate(body)
    assert exc.value.path == "templates[0].bbox.w"


def test_templates_filename_outside_buttons_or_labels_rejected():
    """``mercs/foo.png`` is not under ``buttons|labels``."""
    body = _valid_body()
    body["templates"][0]["filename"] = "mercs/foo.png"
    with pytest.raises(SchemaError) as exc:
        validate(body)
    assert exc.value.path == "templates[0].filename"


def test_templates_source_step_index_negative_rejected():
    """A negative ``source_step_index`` violates the ``>= 0`` rule."""
    body = _valid_body()
    body["templates"][0]["source_step_index"] = -1
    with pytest.raises(SchemaError) as exc:
        validate(body)
    assert exc.value.path == "templates[0].source_step_index"
