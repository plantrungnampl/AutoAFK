"""Unit tests for ``AgentLoop``."""

from typing import List
from unittest.mock import MagicMock

from PIL import Image

from src.dev_tools.llm_agent.agent_loop import (
    AgentLoop, AgentLoopCallbacks, AgentResult,
)
from src.dev_tools.llm_agent.models import (
    AgentAction, AgentError, AgentSession, AgentStep,
)


class _FakeClient:
    """Returns a queued list of actions/errors, one per ``next_action`` call."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def next_action(self, goal, history, screenshot, config):
        self.calls += 1
        if not self.replies:
            return AgentError(category="INVALID_JSON", message="no more replies")
        return self.replies.pop(0)


class _FakeDevice:
    """Records all tap/swipe/screenshot calls."""

    def __init__(self):
        self.taps: List = []
        self.swipes: List = []
        self.screenshot_count = 0

    def get_screenshot(self):
        self.screenshot_count += 1
        return Image.new("RGB", (1080, 1920), "blue")

    def tap(self, x, y):
        self.taps.append((x, y))

    def swipe(self, x1, y1, x2, y2, duration_ms=None):
        self.swipes.append((x1, y1, x2, y2))


def _callbacks(confirm_replies):
    """Build callbacks where confirm replies are scripted in order."""
    confirms = list(confirm_replies)
    cbs = AgentLoopCallbacks(
        request_confirm=lambda action: confirms.pop(0) if confirms else "stop",
        render_step=MagicMock(),
        render_error=MagicMock(),
    )
    return cbs


def test_loop_runs_one_tap_then_done():
    client = _FakeClient([
        AgentAction(kind="tap", x=100, y=200, rationale="t1"),
        AgentAction(kind="done", done_reason="ok"),
    ])
    device = _FakeDevice()
    config = MagicMock()
    config.getint.return_value = 0  # tap_settle_ms=0 to keep tests fast
    cbs = _callbacks([True])  # approve the tap
    session = AgentSession(goal="test")

    loop = AgentLoop(client, device, cbs, config)
    result = loop.run(session)

    assert isinstance(result, AgentResult)
    assert result.done is True
    assert result.done_reason == "ok"
    assert len(device.taps) == 1
    assert device.taps[0] == (100, 200)
    assert len(session.steps) == 2  # tap step + done step (no exec)


def test_skip_does_not_execute_tap():
    client = _FakeClient([
        AgentAction(kind="tap", x=100, y=200, rationale="t1"),
        AgentAction(kind="done", done_reason="ok"),
    ])
    device = _FakeDevice()
    config = MagicMock()
    config.getint.return_value = 0
    cbs = _callbacks([False])  # skip
    session = AgentSession(goal="test")

    AgentLoop(client, device, cbs, config).run(session)

    assert device.taps == []
    assert session.steps[0].approved is False
    assert session.steps[0].executed is False


def test_user_stop_exits_loop():
    client = _FakeClient([
        AgentAction(kind="tap", x=10, y=20, rationale="t"),
    ])
    device = _FakeDevice()
    config = MagicMock()
    config.getint.return_value = 0
    cbs = _callbacks(["stop"])
    session = AgentSession(goal="test")

    result = AgentLoop(client, device, cbs, config).run(session)

    assert result.stopped is True
    assert device.taps == []


def test_max_steps_aborts_with_error():
    # Five tap actions, but max_steps=3; loop must stop after 3 iterations.
    client = _FakeClient([
        AgentAction(kind="tap", x=i*10, y=i*10, rationale=str(i))
        for i in range(5)
    ])
    device = _FakeDevice()
    config = MagicMock()
    config.getint.return_value = 0
    cbs = _callbacks([True, True, True])
    session = AgentSession(goal="test", max_steps=3)

    result = AgentLoop(client, device, cbs, config).run(session)

    assert isinstance(result.error, AgentError)
    assert result.error.category == "MAX_STEPS"
    assert len(session.steps) == 3


def test_agent_error_aborts_loop():
    client = _FakeClient([
        AgentError(
            category="OLLAMA_UNREACHABLE",
            message="nope",
            ollama_host="http://localhost:11434",
            model_name="qwen2.5vl:3b",
        ),
    ])
    device = _FakeDevice()
    config = MagicMock()
    config.getint.return_value = 0
    cbs = _callbacks([])
    session = AgentSession(goal="test")

    result = AgentLoop(client, device, cbs, config).run(session)

    assert isinstance(result.error, AgentError)
    assert result.error.category == "OLLAMA_UNREACHABLE"
    assert device.taps == []


def test_trust_mode_skips_confirm():
    """When trust_mode=True, confirm callback is never called."""
    client = _FakeClient([
        AgentAction(kind="tap", x=50, y=60, rationale="t"),
        AgentAction(kind="done", done_reason="ok"),
    ])
    device = _FakeDevice()
    config = MagicMock()
    config.getint.return_value = 0
    confirm_called = []

    def fake_confirm(action):
        confirm_called.append(action)
        return True

    cbs = AgentLoopCallbacks(
        request_confirm=fake_confirm,
        render_step=MagicMock(),
        render_error=MagicMock(),
    )
    session = AgentSession(goal="test", trust_mode=True)

    AgentLoop(client, device, cbs, config).run(session)

    assert confirm_called == []
    assert device.taps == [(50, 60)]


def test_swipe_action_executes_via_device_swipe():
    client = _FakeClient([
        AgentAction(
            kind="swipe", x1=100, y1=1000, x2=100, y2=200, rationale="scroll"
        ),
        AgentAction(kind="done", done_reason="ok"),
    ])
    device = _FakeDevice()
    config = MagicMock()
    config.getint.return_value = 0
    cbs = _callbacks([True])
    session = AgentSession(goal="test")

    AgentLoop(client, device, cbs, config).run(session)

    assert device.swipes == [(100, 1000, 100, 200)]


def test_history_is_truncated_to_window():
    """The client receives only the last `history_window` steps."""
    captured = []

    class _CaptureClient:
        def next_action(self, goal, history, screenshot, config):
            captured.append(list(history))
            if len(captured) >= 4:
                return AgentAction(kind="done", done_reason="end")
            return AgentAction(kind="tap", x=10, y=10, rationale="t")

    device = _FakeDevice()
    config = MagicMock()
    config.getint.return_value = 0
    cbs = _callbacks([True, True, True])
    session = AgentSession(goal="test", history_window=2)

    AgentLoop(_CaptureClient(), device, cbs, config).run(session)

    # 4 calls: empty, [s0], [s0,s1], [s1,s2]
    assert len(captured[0]) == 0
    assert len(captured[1]) == 1
    assert len(captured[2]) == 2
    assert len(captured[3]) == 2  # truncated, not 3
