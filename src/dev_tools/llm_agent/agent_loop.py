"""Agent loop: orchestrates Agent_Client + DeviceManager.

The loop is the pure-Python core of the agent. The GUI hosts it on a
background thread and exchanges Approve/Skip/Stop decisions via the
``AgentLoopCallbacks`` adaptor.
"""

import logging
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Union

from src.dev_tools.llm_agent.models import (
    AgentAction, AgentError, AgentSession, AgentStep,
)

logger = logging.getLogger(__name__)


@dataclass
class AgentLoopCallbacks:
    """Hooks into the GUI from the loop thread.

    Attributes:
        request_confirm: Called for every proposed action when
            ``session.trust_mode`` is False. Returns ``True`` for Approve,
            ``False`` for Skip, or the string ``"stop"`` to exit the loop.
            The implementation is responsible for blocking the loop thread
            until the user has chosen.
        render_step: Called once per iteration after the step has been
            recorded (regardless of approve/skip).
        render_error: Called once when the loop terminates with an
            :class:`AgentError`.
    """

    request_confirm: Callable[[AgentAction], Union[bool, str]]
    render_step: Callable[[AgentStep], None]
    render_error: Callable[[AgentError], None]


@dataclass
class AgentResult:
    """Final outcome of one ``AgentLoop.run(session)`` call.

    Exactly one of ``done``, ``stopped``, ``error`` is truthy.

    Attributes:
        done: ``True`` if the LLM returned ``kind="done"``.
        done_reason: When ``done`` is ``True``, the LLM's summary.
        stopped: ``True`` if the user clicked Stop.
        error: When set, an :class:`AgentError` describing the failure.
    """

    done: bool = False
    done_reason: str = ""
    stopped: bool = False
    error: Optional[AgentError] = None


class AgentLoop:
    """Drives an :class:`AgentSession` from goal to done/stop/error.

    Attributes:
        client: An ``AgentClient`` (or duck-typed equivalent with
            ``next_action(goal, history, screenshot, config)``).
        device_manager: An object exposing ``get_screenshot()``,
            ``tap(x, y)``, ``swipe(x1, y1, x2, y2)``.
        callbacks: GUI integration hooks (see :class:`AgentLoopCallbacks`).
        config: ``configparser``-compatible config object; ``[LLM_TOOLING]
            tap_settle_ms`` is read for the post-action settle delay.
    """

    def __init__(self, client, device_manager, callbacks, config) -> None:
        self.client = client
        self.device_manager = device_manager
        self.callbacks = callbacks
        self.config = config

    def run(self, session: AgentSession) -> AgentResult:
        """Execute the loop until done, stop, error, or max_steps."""
        logger.info("Agent loop started: goal=%r", session.goal)
        tap_settle_ms = self.config.getint(
            "LLM_TOOLING", "tap_settle_ms", fallback=1000
        )

        while True:
            if len(session.steps) >= session.max_steps:
                err = AgentError(
                    category="MAX_STEPS",
                    message="Reached max_steps={} without 'done'.".format(
                        session.max_steps
                    ),
                )
                self.callbacks.render_error(err)
                return AgentResult(error=err)

            try:
                screenshot = self.device_manager.get_screenshot()
            except Exception as exc:
                err = AgentError(
                    category="ADB_FAILURE",
                    message="get_screenshot failed: {}".format(exc),
                )
                logger.error("agent_adb_failure: %s", exc)
                self.callbacks.render_error(err)
                return AgentResult(error=err)

            history = self._history_window(session)
            outcome = self.client.next_action(
                session.goal, history, screenshot, self.config,
            )

            if isinstance(outcome, AgentError):
                logger.error("agent_%s: %s", outcome.category.lower(), outcome.message)
                self.callbacks.render_error(outcome)
                return AgentResult(error=outcome)

            action = outcome
            step = AgentStep(
                index=len(session.steps),
                screenshot=screenshot,
                proposed=action,
            )

            # Confirm phase.
            if not session.trust_mode and action.kind != "done":
                decision = self.callbacks.request_confirm(action)
                if decision == "stop":
                    session.steps.append(step)
                    self.callbacks.render_step(step)
                    return AgentResult(stopped=True)
                approved = bool(decision)
            else:
                approved = True

            step.approved = approved

            # Execute phase.
            if action.kind == "done":
                session.steps.append(step)
                self.callbacks.render_step(step)
                logger.info("Agent done: %s", action.done_reason)
                return AgentResult(done=True, done_reason=action.done_reason)

            if approved:
                try:
                    self._execute(action)
                    step.executed = True
                except Exception as exc:
                    err = AgentError(
                        category="ADB_FAILURE",
                        message="execute {} failed: {}".format(action.kind, exc),
                    )
                    logger.error("agent_adb_failure: %s", exc)
                    session.steps.append(step)
                    self.callbacks.render_step(step)
                    self.callbacks.render_error(err)
                    return AgentResult(error=err)

                # Settle delay matches the recorder convention.
                time.sleep(max(0, tap_settle_ms) / 1000.0)

            session.steps.append(step)
            self.callbacks.render_step(step)

    def _history_window(self, session: AgentSession) -> List[AgentStep]:
        if session.history_window <= 0 or not session.steps:
            return []
        return list(session.steps[-session.history_window:])

    def _execute(self, action: AgentAction) -> None:
        if action.kind == "tap":
            self.device_manager.tap(action.x, action.y)
        elif action.kind == "swipe":
            self.device_manager.swipe(
                action.x1, action.y1, action.x2, action.y2
            )
        elif action.kind == "wait":
            time.sleep(max(0.0, action.seconds))
        # 'done' never reaches here.
