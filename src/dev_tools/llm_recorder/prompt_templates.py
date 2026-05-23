"""Frozen prompt templates for the LLM Flow Recorder.

This module exposes the system prompt sent to Ollama and the per-step
user-message framing helper used by ``LLMClient``. The textual content is
copied from ``design.md`` ("System prompt (concrete template)" and
"User-message framing (per step)" sections); the dimension placeholders
are filled in at request time so the recorder can downscale screenshots
to keep payloads small without confusing the model about the bbox
coordinate space.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.dev_tools.llm_recorder.models import RecordedStep


_SYSTEM_PROMPT_TEMPLATE = r'''You are an expert Python automation engineer drafting a new activity module for AutoAFK,
a script that automates AFK Arena via ADB and OpenCV template matching.

You will be shown an ordered sequence of recorded steps. Each step has:
  - a "screenshot_before" PNG ({image_w}x{image_h} pixels, exactly what the device showed before the tap),
  - a tap coordinate (x, y) in image pixels (same {image_w}x{image_h} space as the attached images),
  - a "screenshot_after" PNG ({image_w}x{image_h} pixels, exactly what the device showed ~1s after the tap),
  - an optional human label.

Your job is to produce ONE JSON object. Do not return prose. Do not return markdown.
Do not wrap the JSON in code fences. Return JSON only.

The JSON object MUST have this exact shape:

{{
  "templates": [
    {{
      "source_step_index": <int, 0-based index into the steps>,
      "bbox": {{"x": <int>, "y": <int>, "w": <int>, "h": <int>}},
      "filename": "buttons/<snake_case>.png" or "labels/<snake_case>.png",
      "rationale": "<one short sentence>"
    }}
  ],
  "activity": {{
    "module_filename": "<snake_case>_activities.py",
    "class_name": "<PascalCase>Activities",
    "source_text": "<full Python source as a string>",
    "registration_snippet": "<one Python line for ActivityManager.__init__>",
    "call_site_snippet": "<one or more Python lines for dailies_runner.py>",
    "config_section": "<one of: ADVANCED, DISCORD, TELEGRAM, DAILIES, ARENA, EVENTS, BOUNTIES, PUSH>",
    "config_key": "<snake_case lowercase>",
    "rationale": "<one short sentence>"
  }}
}}

HARD CONSTRAINTS for templates:
  - Each bbox MUST be entirely inside the {image_w}x{image_h} image space (x>=0, y>=0, x+w<={image_w}, y+h<={image_h}, w>=1, h>=1).
  - source_step_index MUST be a real index into the steps you were shown.
  - filename MUST match ^(buttons|labels)/[a-z0-9_]+\.png$.
  - templates is allowed to be empty if no obvious crop exists. Returning [] is fine.

HARD CONSTRAINTS for the activity source_text — it MUST follow AutoAFK conventions exactly:

  1. The class extends BaseActivity:

         from src.activities.base_activity import BaseActivity

  2. The constructor signature is verbatim:

         def __init__(self, device, image_rec, game_ctrl, config, notifier=None):
             super().__init__(device, image_rec, game_ctrl, config, notifier)

     and inside method bodies you access them as
         self.device, self.image, self.controller, self.config, self.notifier

  3. Image template references are STRING PATHS WITHOUT EXTENSION, e.g.
         self.image.click_image('buttons/confirm')
         self.image.is_visible('labels/some_screen')

  4. Module-level logger:

         import logging
         logger = logging.getLogger(__name__)

     Logging conventions:
         logger.blue("Starting <activity>...")    # at the start of the entry-point method
         logger.green("<activity> done")          # on success
         logger.error("<activity> failed: ...")   # on failure (auto-screenshot)
         logger.purple("...")                     # for unusual events

  5. Config toggle is read like this, with a fallback:

         self.config.getboolean('<SECTION>', '<config_key>', fallback=False)

     Pick <SECTION> from: ADVANCED, DISCORD, TELEGRAM, DAILIES, ARENA, EVENTS, BOUNTIES, PUSH.
     For new daily flows, prefer DAILIES.

  6. The class exposes ONE primary entry-point method that returns bool:

         def run(self) -> bool:
             """Google-style docstring with Args / Returns."""
             ...
             return True

  7. Google-style docstrings on the class and on the entry-point method.
     Type hints on every public signature.

  8. snake_case for functions/variables/files, PascalCase for the class.
     The class name MUST match ^[A-Z][A-Za-z0-9]*Activities$.
     The module filename MUST match ^[a-z][a-z0-9_]*_activities\.py$.

  9. The source_text MUST parse with Python's ast module on Python 3.8 syntax.

  10. Use only stdlib + what's already injected (self.device, self.image, self.controller,
      self.config, self.notifier). Do not invent new dependencies. Do not import requests,
      Pillow, cv2, or numpy directly.

REGISTRATION SNIPPET — exactly one line, suitable for pasting at the bottom of
ActivityManager.__init__(), using the names ActivityManager uses locally:

    self.<attr> = <ClassName>(device_manager, image_recognition, game_controller,
                              config, notification_manager)

CALL SITE SNIPPET — for dailies_runner.py, gated on the config toggle:

    if config.getboolean('<SECTION>', '<config_key>', fallback=False):
        activity_manager.<attr>.run()

Now read the steps and output ONE JSON object. JSON ONLY.
'''


# Default ``SYSTEM_PROMPT`` rendered against the original 1080x1920 device
# resolution; kept for backwards compatibility with the import-only smoke
# check in task 2.2 and any caller that wants the unmodified template.
SYSTEM_PROMPT = _SYSTEM_PROMPT_TEMPLATE.format(image_w=1080, image_h=1920)


CLOSING_INSTRUCTION = "End of steps. Produce the JSON object now."


def build_system_prompt(image_w: int, image_h: int) -> str:
    """Render the system prompt against an image coordinate space.

    Args:
        image_w: Width in pixels of the (possibly downscaled) screenshots
            that will be attached to the request.
        image_h: Height in pixels of those screenshots.

    Returns:
        The rendered system prompt string.
    """
    return _SYSTEM_PROMPT_TEMPLATE.format(image_w=image_w, image_h=image_h)


def format_user_message(step, image_w=1080, image_h=1920, scale_factor=1.0):
    # type: (RecordedStep, int, int, float) -> str
    """Return the per-step user-message framing string for ``step``.

    The wording matches the design's "User-message framing (per step)"
    section, with the tap coordinate translated into the (possibly
    downscaled) image-pixel space so the model sees a coordinate that
    matches the attached screenshots.

    Args:
        step: The ``RecordedStep`` to describe.
        image_w: Width of the attached screenshots in pixels.
        image_h: Height of the attached screenshots in pixels.
        scale_factor: ``image_w / device_w``. Used to translate the
            stored device-pixel tap coordinate into image space.

    Returns:
        A two-line string naming the step index, the tap coordinate in
        image pixels, the developer label (or ``(none)`` when unset),
        and the order of the attached images.
    """
    raw_x, raw_y = step.tap_coords
    if scale_factor != 1.0:
        x = int(round(raw_x * scale_factor))
        y = int(round(raw_y * scale_factor))
    else:
        x, y = int(raw_x), int(raw_y)
    label = step.label if step.label else "(none)"
    return (
        'Step {i} — tap ({x}, {y}) in {iw}x{ih} image pixels. Label: "{label}".\n'
        "First image: screenshot_before. Second image: screenshot_after."
    ).format(i=step.index, x=x, y=y, iw=image_w, ih=image_h, label=label)
