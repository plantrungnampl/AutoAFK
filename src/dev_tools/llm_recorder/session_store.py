"""Session persistence for the LLM Flow Recorder.

Saves a :class:`~src.dev_tools.llm_recorder.models.RecordingSession` to a
timestamped directory under ``debug/llm_recorder/`` and loads it back into
memory. The on-disk layout (PNG-per-screenshot plus ``session.json``) is
documented in ``design.md`` under "Directory layout" and "Save flow".

Design contract:

* ``session.json`` is written **last** so its presence on disk implies that
  every referenced PNG already exists.
* ``schema_version`` is hard-pinned to ``1``; loading any other value raises
  rather than silently migrating.
* On load, every referenced PNG is verified to exist **before** any
  ``RecordingSession`` state is built, so failures never produce a partial
  session.

Python 3.8-compatible.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Union

from PIL import Image

from src.dev_tools.llm_recorder.models import RecordedStep, RecordingSession

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_BASE_DIR = "debug/llm_recorder"
SESSION_JSON_NAME = "session.json"


class SessionLoadError(ValueError):
    """Raised when a saved session cannot be loaded.

    Used for schema-version mismatches and other structural errors in
    ``session.json``. A missing PNG referenced by a session raises
    :class:`FileNotFoundError` instead.
    """


def _step_basename(index: int, kind: str) -> str:
    """Return the canonical PNG basename for a step screenshot.

    Args:
        index: 0-based step index.
        kind: Either ``"before"`` or ``"after"``.

    Returns:
        str: Filename like ``"step_000_before.png"``.
    """
    return "step_{:03d}_{}.png".format(index, kind)


def _allocate_dir(base_dir: Path, timestamp: str) -> Path:
    """Find an unused subdirectory under ``base_dir`` for ``timestamp``.

    Tries ``base_dir/timestamp`` first; on collision appends ``_2``,
    ``_3``, ... until :func:`os.makedirs` with ``exist_ok=False`` succeeds.

    Args:
        base_dir: Parent directory; created if missing.
        timestamp: Timestamp string from ``time.strftime``.

    Returns:
        Path: The created (and now empty) target directory.
    """
    base_dir.mkdir(parents=True, exist_ok=True)
    candidate = base_dir / timestamp
    suffix = 2
    while True:
        try:
            os.makedirs(candidate, exist_ok=False)
            return candidate
        except FileExistsError:
            candidate = base_dir / "{}_{}".format(timestamp, suffix)
            suffix += 1


class SessionStore:
    """Persist and reload :class:`RecordingSession` instances.

    The store is stateless; instantiate one per save/load call (or share a
    single instance across the GUI's lifetime — both work).
    """

    def save(
        self,
        session: RecordingSession,
        base_dir: Union[str, Path] = DEFAULT_BASE_DIR,
    ) -> Path:
        """Write a recording session to disk.

        Creates ``<base_dir>/<YYYYmmdd_HHMMSS>/`` (suffixing ``_2``, ``_3``,
        ... on directory collision), writes each step's
        ``screenshot_before`` and ``screenshot_after`` as PNGs named
        ``step_{i:03d}_before.png`` / ``step_{i:03d}_after.png``, and
        finally writes ``session.json``. The JSON is intentionally written
        last so that observers can rely on its presence as a "fully
        committed" signal.

        Args:
            session: The recording session to persist.
            base_dir: Parent directory under which the timestamped session
                directory is created. Defaults to ``"debug/llm_recorder"``.

        Returns:
            Path: The newly-created session directory containing all PNGs
            and ``session.json``.
        """
        base = Path(base_dir)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        target_dir = _allocate_dir(base, timestamp)

        steps_meta = []
        for step in session.steps:
            before_name = _step_basename(step.index, "before")
            after_name = _step_basename(step.index, "after")
            step.screenshot_before.save(target_dir / before_name, "PNG")
            step.screenshot_after.save(target_dir / after_name, "PNG")
            steps_meta.append(
                {
                    "index": step.index,
                    "tap_coords": [
                        int(step.tap_coords[0]),
                        int(step.tap_coords[1]),
                    ],
                    "label": step.label,
                    "screenshot_before": before_name,
                    "screenshot_after": after_name,
                }
            )

        body = {
            "schema_version": SCHEMA_VERSION,
            "started_at": float(session.started_at),
            "device_resolution": [
                int(session.device_resolution[0]),
                int(session.device_resolution[1]),
            ],
            "steps": steps_meta,
        }

        # Write session.json LAST so its presence implies all PNGs exist.
        with (target_dir / SESSION_JSON_NAME).open("w", encoding="utf-8") as fp:
            json.dump(body, fp, indent=2)

        return target_dir

    def load(self, session_json: Path) -> RecordingSession:
        """Load a recording session from a ``session.json`` path.

        Parses the JSON, verifies ``schema_version == 1``, then verifies
        that every referenced PNG exists in the same directory **before**
        opening any image. Each PNG is loaded via
        ``PIL.Image.open(path).copy()`` so the underlying file handle is
        released immediately and the returned images are safe to use after
        this method returns.

        Args:
            session_json: Path to a ``session.json`` produced by
                :meth:`save`.

        Returns:
            RecordingSession: The reconstructed session with PIL images
            attached to each step.

        Raises:
            SessionLoadError: If ``schema_version`` is missing or not
                equal to ``1``, or if the JSON is otherwise structurally
                invalid.
            FileNotFoundError: If any PNG referenced by the JSON is
                missing from the session directory. Raised before any
                ``RecordingSession`` state is built.
        """
        session_json = Path(session_json)
        with session_json.open("r", encoding="utf-8") as fp:
            body = json.load(fp)

        version = body.get("schema_version")
        if version != SCHEMA_VERSION:
            raise SessionLoadError(
                "unsupported session schema_version={!r} (expected {})".format(
                    version, SCHEMA_VERSION
                )
            )

        if not isinstance(body.get("steps"), list):
            raise SessionLoadError("session.json 'steps' is missing or not a list")

        session_dir = session_json.parent
        steps_meta = body["steps"]

        # Verify every PNG exists BEFORE building any state.
        for step_meta in steps_meta:
            for key in ("screenshot_before", "screenshot_after"):
                name = step_meta.get(key)
                if not isinstance(name, str):
                    raise SessionLoadError(
                        "step {} missing string field {!r}".format(
                            step_meta.get("index"), key
                        )
                    )
                png_path = session_dir / name
                if not png_path.is_file():
                    raise FileNotFoundError(str(png_path))

        steps = []
        for step_meta in steps_meta:
            before_path = session_dir / step_meta["screenshot_before"]
            after_path = session_dir / step_meta["screenshot_after"]
            # .copy() forces a load and releases the file handle.
            with Image.open(before_path) as im:
                before_img = im.copy()
            with Image.open(after_path) as im:
                after_img = im.copy()
            tap_coords = step_meta.get("tap_coords") or [0, 0]
            steps.append(
                RecordedStep(
                    index=int(step_meta["index"]),
                    screenshot_before=before_img,
                    screenshot_after=after_img,
                    tap_coords=(int(tap_coords[0]), int(tap_coords[1])),
                    label=step_meta.get("label"),
                )
            )

        device_resolution = body.get("device_resolution") or [1080, 1920]
        return RecordingSession(
            steps=steps,
            device_resolution=(
                int(device_resolution[0]),
                int(device_resolution[1]),
            ),
            started_at=float(body.get("started_at", 0.0)),
        )
