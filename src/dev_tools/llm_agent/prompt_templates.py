"""Prompt templates for the LLM Agent.

The system prompt is templated against the downscaled image dimensions so
the LLM emits coordinates in the same space as the attached screenshot.
``LLMClient`` (in ``llm_agent.agent_client``) renders this prompt at
request time and rescales returned coordinates back to device pixels.
"""

from typing import Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from src.dev_tools.llm_agent.models import AgentStep


_SYSTEM_PROMPT_TEMPLATE = r'''You are an automation agent driving an Android phone running the AFK Arena game.
You will be shown:
  - a high-level goal in plain English (e.g. "collect daily login reward")
  - an optional history of the last few actions you took, each with a short
    rationale and the screenshot that was on screen when you decided
  - the current screenshot (after the last action)

Your job is to produce ONE JSON object describing the SINGLE next action
toward the goal. Do not return prose. Do not return markdown. Do not wrap
the JSON in code fences. Return JSON only.

The JSON object MUST have one of these exact shapes:

  {{"kind": "tap", "x": <0..{image_w}>, "y": <0..{image_h}>, "rationale": "<one short sentence>"}}
  {{"kind": "swipe", "x1": <int>, "y1": <int>, "x2": <int>, "y2": <int>, "rationale": "<one short sentence>"}}
  {{"kind": "wait", "seconds": <0.5..5.0>, "rationale": "<one short sentence>"}}
  {{"kind": "done", "done_reason": "<one short sentence summarising completion>"}}

HARD CONSTRAINTS:
  - Coordinates MUST be inside the {image_w}x{image_h} screen.
  - Pick the SINGLE most likely action that advances the goal.
  - If the goal has clearly been achieved (the screenshot shows the
    expected end state), return kind="done".
  - If you are uncertain, prefer "wait" with a short delay over a random tap.
  - Do not propose a "tap" identical to the immediately previous "tap" if
    the screen did not change — try a different action.

The screenshots have been downscaled from the device's native 1080x1920
resolution to {image_w}x{image_h}. Coordinates you return must be in the
{image_w}x{image_h} space; the agent will rescale to device pixels.
'''


def build_system_prompt(image_w: int, image_h: int) -> str:
    """Render the system prompt for the given downscaled image space.

    Args:
        image_w: Image-space width passed to the LLM.
        image_h: Image-space height passed to the LLM.

    Returns:
        Fully rendered system prompt string.
    """
    return _SYSTEM_PROMPT_TEMPLATE.format(image_w=image_w, image_h=image_h)


def _format_history_line(step):
    # type: (AgentStep) -> str
    """Render one history line: ``Step <i>: <action_summary> — "<rationale>"``."""
    a = step.proposed
    if a.kind == "tap":
        summary = "tap ({}, {})".format(a.x, a.y)
    elif a.kind == "swipe":
        summary = "swipe ({},{}) -> ({},{})".format(a.x1, a.y1, a.x2, a.y2)
    elif a.kind == "wait":
        summary = "wait {:.1f}s".format(a.seconds)
    else:
        summary = a.kind
    rationale = a.rationale or "(no rationale)"
    return 'Step {}: {} — "{}"'.format(step.index, summary, rationale)


def format_user_message(goal, history):
    # type: (str, Iterable[AgentStep]) -> str
    """Render the per-step user-message text.

    Screenshot bytes are attached separately via the Ollama ``images``
    field; this function only renders the textual framing.

    Args:
        goal: The user-supplied goal string.
        history: Most recent ``AgentStep`` instances (already truncated to
            ``history_window`` by the caller).

    Returns:
        A formatted string with the goal, history lines, and a closing
        instruction to produce JSON.
    """
    history = list(history)
    if history:
        history_block = "\n".join(
            "  " + _format_history_line(s) for s in history
        )
        history_section = "History (last {} step{}):\n{}\n".format(
            len(history),
            "" if len(history) == 1 else "s",
            history_block,
        )
    else:
        history_section = "History: (no prior actions)\n"
    return (
        "Goal: {goal}\n\n"
        "{history_section}\n"
        "Current screenshot is attached. Produce the JSON action."
    ).format(goal=goal, history_section=history_section)
