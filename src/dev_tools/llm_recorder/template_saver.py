"""Template Saver for the LLM Flow Recorder.

Crops a region of a recorded screenshot and writes it as a PNG into the
project's ``img/`` tree. All filesystem I/O is atomic: the PNG is written
first to ``<target>.tmp-<pid>`` in the same directory, then moved into
place via :func:`os.replace`, so a crashed save never leaves a partial
file at the canonical path.

This module is dev-time-only and lives outside the production code path.
It uses the standard library logger only; the project's ``Logger``
overlays ``.blue/.green/.purple`` levels at runtime, but TemplateSaver
itself only ever calls ``logger.error(...)`` on validation failures.
Successful saves are logged by the caller via ``logger.green(...)``.
"""

import logging
import os
import re
from pathlib import Path
from typing import Optional

from .models import RecordingSession, TemplateProposal

logger = logging.getLogger(__name__)

#: Filename regex per design's "Bbox validation rules" section. Must be
#: ``buttons/<snake>.png`` or ``labels/<snake>.png`` with no subdirectories.
_FILENAME_RE = re.compile(r"^(buttons|labels)/[a-z0-9_]+\.png$")

#: Default ``img/`` root, resolved from this file's location so the path
#: works regardless of the process's current working directory.
#: ``parents[3]`` walks ``llm_recorder -> dev_tools -> src -> <repo>``.
_DEFAULT_IMG_ROOT = Path(__file__).resolve().parents[3] / "img"


class TemplateSaver:
    """Crop a recorded screenshot and atomically save it as a template PNG.

    Attributes:
        img_root: Directory under which ``buttons/`` and ``labels/``
            template files are written. Defaults to the repo's ``img/``
            directory; tests inject a ``tmp_path`` here.
    """

    def __init__(self, img_root: Optional[Path] = None) -> None:
        """Initialize the saver.

        Args:
            img_root: Optional override for the base ``img/`` directory.
                When ``None`` (the default), the repo's ``img/`` directory
                is used.
        """
        self.img_root = Path(img_root) if img_root is not None else _DEFAULT_IMG_ROOT

    def save(
        self,
        proposal: TemplateProposal,
        session: RecordingSession,
        *,
        force: bool = False,
    ) -> Path:
        """Validate, crop, and atomically write a template PNG.

        Validation runs in the order documented by the design's "Bbox
        validation rules" section:

        1. ``proposal.filename`` must match
           ``^(buttons|labels)/[a-z0-9_]+\\.png$``.
        2. ``proposal.bbox`` must lie within
           ``session.device_resolution`` with ``w >= 1`` and ``h >= 1``.
        3. ``proposal.source_step_index`` must index into
           ``session.steps``.

        Args:
            proposal: The template crop to write.
            session: The recording session that supplies the source
                screenshot and device resolution.
            force: When ``True``, overwrite an existing target file.
                When ``False`` (the default), raise ``FileExistsError``
                if the target already exists.

        Returns:
            The absolute path of the written PNG.

        Raises:
            ValueError: If the filename regex, bbox bounds, or source
                step index check fails.
            FileExistsError: If the target already exists and
                ``force=False``.
        """
        # 1. Filename regex.
        if not _FILENAME_RE.match(proposal.filename):
            logger.error(
                "template_save_invalid_filename: %r does not match %s",
                proposal.filename,
                _FILENAME_RE.pattern,
            )
            raise ValueError(
                "filename must match {}: got {!r}".format(
                    _FILENAME_RE.pattern, proposal.filename
                )
            )

        # 2. Bbox bounds against session.device_resolution.
        x, y, w, h = proposal.bbox
        device_w, device_h = session.device_resolution
        if (
            x < 0
            or y < 0
            or w < 1
            or h < 1
            or x + w > device_w
            or y + h > device_h
        ):
            logger.error(
                "template_save_invalid_bbox: bbox=%s outside %sx%s",
                proposal.bbox,
                device_w,
                device_h,
            )
            raise ValueError(
                "bbox {} is outside device bounds {}x{}".format(
                    proposal.bbox, device_w, device_h
                )
            )

        # 3. Source step index must be in range.
        if not 0 <= proposal.source_step_index < len(session.steps):
            logger.error(
                "template_save_invalid_step_index: %d not in [0, %d)",
                proposal.source_step_index,
                len(session.steps),
            )
            raise ValueError(
                "source_step_index {} not in [0, {})".format(
                    proposal.source_step_index, len(session.steps)
                )
            )

        target = self.img_root / proposal.filename

        # 4. Existence check.
        if target.exists() and not force:
            raise FileExistsError(str(target))

        # 5. Crop + atomic write.
        target.parent.mkdir(parents=True, exist_ok=True)
        source_image = session.steps[proposal.source_step_index].screenshot_before
        crop = source_image.crop((x, y, x + w, y + h))

        tmp_path = target.with_name(target.name + ".tmp-{}".format(os.getpid()))
        crop.save(str(tmp_path), format="PNG")
        os.replace(str(tmp_path), str(target))

        return target
