"""Unit tests for ``src.dev_tools.llm_agent.action_schema``."""

import pytest

from src.dev_tools.llm_agent.action_schema import ActionSchemaError, validate
from src.dev_tools.llm_agent.models import AgentAction


# Image space the validator checks against in these tests.
IMG_W = 1080
IMG_H = 1920


def test_valid_tap_accepted():
    body = {"kind": "tap", "x": 540, "y": 1500, "rationale": "tap claim"}
    action = validate(body, IMG_W, IMG_H)
    assert isinstance(action, AgentAction)
    assert action.kind == "tap"
    assert action.x == 540
    assert action.y == 1500
    assert action.rationale == "tap claim"


def test_valid_swipe_accepted():
    body = {
        "kind": "swipe",
        "x1": 100, "y1": 1000, "x2": 100, "y2": 200,
        "rationale": "scroll up",
    }
    action = validate(body, IMG_W, IMG_H)
    assert action.kind == "swipe"
    assert action.x1 == 100 and action.y1 == 1000
    assert action.x2 == 100 and action.y2 == 200


def test_valid_wait_accepted():
    body = {"kind": "wait", "seconds": 1.5, "rationale": "wait for animation"}
    action = validate(body, IMG_W, IMG_H)
    assert action.kind == "wait"
    assert action.seconds == 1.5


def test_valid_done_accepted():
    body = {"kind": "done", "done_reason": "claim collected"}
    action = validate(body, IMG_W, IMG_H)
    assert action.kind == "done"
    assert action.done_reason == "claim collected"


def test_unknown_kind_rejected():
    body = {"kind": "magic", "rationale": "abracadabra"}
    with pytest.raises(ActionSchemaError) as exc:
        validate(body, IMG_W, IMG_H)
    assert exc.value.path == "kind"


def test_tap_missing_x_rejected():
    body = {"kind": "tap", "y": 100, "rationale": "no x"}
    with pytest.raises(ActionSchemaError) as exc:
        validate(body, IMG_W, IMG_H)
    assert exc.value.path == "x"


def test_tap_missing_y_rejected():
    body = {"kind": "tap", "x": 100, "rationale": "no y"}
    with pytest.raises(ActionSchemaError) as exc:
        validate(body, IMG_W, IMG_H)
    assert exc.value.path == "y"


def test_tap_x_negative_rejected():
    body = {"kind": "tap", "x": -1, "y": 100, "rationale": "neg"}
    with pytest.raises(ActionSchemaError) as exc:
        validate(body, IMG_W, IMG_H)
    assert exc.value.path == "x"


def test_tap_x_out_of_bounds_rejected():
    body = {"kind": "tap", "x": IMG_W, "y": 100, "rationale": "edge"}
    with pytest.raises(ActionSchemaError) as exc:
        validate(body, IMG_W, IMG_H)
    assert exc.value.path == "x"


def test_swipe_missing_x2_rejected():
    body = {"kind": "swipe", "x1": 0, "y1": 0, "y2": 100, "rationale": "no x2"}
    with pytest.raises(ActionSchemaError) as exc:
        validate(body, IMG_W, IMG_H)
    assert exc.value.path == "x2"


def test_wait_seconds_too_large_rejected():
    body = {"kind": "wait", "seconds": 999, "rationale": "forever"}
    with pytest.raises(ActionSchemaError) as exc:
        validate(body, IMG_W, IMG_H)
    assert exc.value.path == "seconds"


def test_done_missing_done_reason_rejected():
    body = {"kind": "done"}
    with pytest.raises(ActionSchemaError) as exc:
        validate(body, IMG_W, IMG_H)
    assert exc.value.path == "done_reason"
