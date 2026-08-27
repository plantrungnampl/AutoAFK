"""Code Generator for the LLM Flow Recorder.

Writes an :class:`~src.dev_tools.llm_recorder.models.ActivityProposal` to
``src/activities/<module_filename>`` after validating the proposed filename,
class name, and Python source. Intentionally does **not** touch
``activity_manager.py``, ``dailies_runner.py``, or ``settings.ini`` — those
integration points stay copy-paste by design (Req 8.7, Req 12.3).

Python 3.8-compatible.
"""

import ast
import logging
import os
import re
from pathlib import Path

from src.dev_tools.llm_recorder.models import ActivityProposal

logger = logging.getLogger(__name__)

MODULE_FILENAME_RE = re.compile(r"^[a-z][a-z0-9_]*_activities\.py$")
CLASS_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9]*Activities$")

DEFAULT_ACTIVITIES_DIR = Path("src/activities")


class CodeGenerator:
    """Persist an ``ActivityProposal`` as a Python module under ``src/activities``.

    The generator is configured with the target activities directory so tests
    can inject a temporary path; in production it defaults to the repo's
    ``src/activities/`` folder.

    Attributes:
        activities_dir: Directory where generated modules are written.
    """

    def __init__(self, activities_dir: Path = DEFAULT_ACTIVITIES_DIR) -> None:
        """Initialize the generator.

        Args:
            activities_dir: Directory where activity modules are written.
                Defaults to ``Path("src/activities")``.
        """
        self.activities_dir = Path(activities_dir)

    def save(self, proposal: ActivityProposal, *, force: bool = False) -> Path:
        """Validate and atomically write an activity module.

        Validation runs in the order documented by the design's
        "Save sequence" diagram:

        1. ``proposal.module_filename`` must match
           ``^[a-z][a-z0-9_]*_activities\\.py$``.
        2. ``proposal.class_name`` must match
           ``^[A-Z][A-Za-z0-9]*Activities$``.
        3. ``ast.parse(proposal.source_text)`` must succeed; any
           :class:`SyntaxError` is re-raised unchanged so the caller can
           surface ``line``/``offset`` to the developer.

        On success the source is written to
        ``<activities_dir>/<module_filename>`` via a temporary file in the
        same directory followed by :func:`os.replace`, giving an atomic
        swap on POSIX and Windows.

        Args:
            proposal: The activity proposal to persist.
            force: When ``False`` (the default), raise
                :class:`FileExistsError` if the target already exists.
                When ``True``, overwrite the existing file.

        Returns:
            Path: Absolute or relative path to the written module.

        Raises:
            ValueError: If ``module_filename`` or ``class_name`` does not
                match its required pattern.
            SyntaxError: Re-raised from :func:`ast.parse` when
                ``source_text`` is not valid Python.
            FileExistsError: When the target file already exists and
                ``force`` is ``False``.
            OSError: For any underlying filesystem I/O failure.
        """
        if not MODULE_FILENAME_RE.match(proposal.module_filename):
            raise ValueError(
                "module_filename {!r} does not match {}".format(
                    proposal.module_filename, MODULE_FILENAME_RE.pattern
                )
            )

        if not CLASS_NAME_RE.match(proposal.class_name):
            raise ValueError(
                "class_name {!r} does not match {}".format(
                    proposal.class_name, CLASS_NAME_RE.pattern
                )
            )

        # Re-raise SyntaxError unchanged so the GUI can surface line + offset.
        ast.parse(proposal.source_text)

        target = self.activities_dir / proposal.module_filename

        if target.exists() and not force:
            raise FileExistsError(target)

        self.activities_dir.mkdir(parents=True, exist_ok=True)

        tmp = target.with_name("{}.tmp-{}".format(target.name, os.getpid()))
        try:
            tmp.write_bytes(proposal.source_text.encode("utf-8"))
            os.replace(tmp, target)
        except OSError as err:
            logger.error("activity_save_failed %s: %s", target, err)
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            raise

        return target
