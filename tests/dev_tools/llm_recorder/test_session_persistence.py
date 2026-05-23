"""Unit tests for ``src.dev_tools.llm_recorder.session_store.SessionStore``.

Covers the on-disk contract from design.md:

* Save -> load round-trip preserves step ``index``, ``tap_coords``,
  ``label``, and PNG dimensions.
* Loading a ``session.json`` with an unsupported ``schema_version`` is
  rejected with :class:`SessionLoadError`.
* Loading a session whose referenced PNG is missing raises
  :class:`FileNotFoundError` before any in-memory state is built.
* Directory-collision suffixing: two saves landing on the same timestamp
  produce ``<dir>`` and ``<dir>_2``.
* Save ordering: ``session.json`` is written last, so its mtime is at
  least the mtime of every PNG.
"""

import json
import os

import pytest
from PIL import Image

from src.dev_tools.llm_recorder import session_store as session_store_module
from src.dev_tools.llm_recorder.models import RecordedStep, RecordingSession
from src.dev_tools.llm_recorder.session_store import (
    SESSION_JSON_NAME,
    SessionLoadError,
    SessionStore,
)


def _make_session() -> RecordingSession:
    """Build a session with two steps backed by tiny in-memory images."""
    step0 = RecordedStep(
        index=0,
        screenshot_before=Image.new("RGB", (1080, 1920), "red"),
        screenshot_after=Image.new("RGB", (1080, 1920), "green"),
        tap_coords=(540, 1500),
        label="tap collect button",
    )
    step1 = RecordedStep(
        index=1,
        screenshot_before=Image.new("RGB", (1080, 1920), "blue"),
        screenshot_after=Image.new("RGB", (1080, 1920), "yellow"),
        tap_coords=(100, 200),
        label=None,
    )
    return RecordingSession(
        steps=[step0, step1],
        device_resolution=(1080, 1920),
        started_at=1737000000.0,
    )


def test_save_load_round_trip_preserves_step_metadata_and_dimensions(tmp_path):
    session = _make_session()
    store = SessionStore()

    target_dir = store.save(session, base_dir=tmp_path)
    loaded = store.load(target_dir / SESSION_JSON_NAME)

    assert len(loaded.steps) == 2
    assert loaded.device_resolution == (1080, 1920)

    for original, restored in zip(session.steps, loaded.steps):
        assert restored.index == original.index
        assert restored.tap_coords == original.tap_coords
        assert restored.label == original.label
        assert restored.screenshot_before.size == (1080, 1920)
        assert restored.screenshot_after.size == (1080, 1920)


def test_load_rejects_unsupported_schema_version(tmp_path):
    session = _make_session()
    store = SessionStore()

    target_dir = store.save(session, base_dir=tmp_path)
    json_path = target_dir / SESSION_JSON_NAME

    body = json.loads(json_path.read_text(encoding="utf-8"))
    body["schema_version"] = 2
    json_path.write_text(json.dumps(body), encoding="utf-8")

    with pytest.raises(SessionLoadError):
        store.load(json_path)


def test_load_rejects_missing_referenced_png(tmp_path):
    session = _make_session()
    store = SessionStore()

    target_dir = store.save(session, base_dir=tmp_path)
    json_path = target_dir / SESSION_JSON_NAME

    body = json.loads(json_path.read_text(encoding="utf-8"))
    missing = target_dir / body["steps"][1]["screenshot_after"]
    assert missing.is_file()
    os.remove(missing)

    with pytest.raises(FileNotFoundError):
        store.load(json_path)


def test_directory_collision_appends_numeric_suffix(tmp_path, monkeypatch):
    session = _make_session()
    store = SessionStore()

    monkeypatch.setattr(
        session_store_module.time, "strftime", lambda fmt: "20250115_134522"
    )

    first = store.save(session, base_dir=tmp_path)
    second = store.save(session, base_dir=tmp_path)

    assert first == tmp_path / "20250115_134522"
    assert second == tmp_path / "20250115_134522_2"
    assert (first / SESSION_JSON_NAME).is_file()
    assert (second / SESSION_JSON_NAME).is_file()


def test_session_json_is_written_after_all_pngs(tmp_path):
    session = _make_session()
    store = SessionStore()

    target_dir = store.save(session, base_dir=tmp_path)

    json_mtime = (target_dir / SESSION_JSON_NAME).stat().st_mtime
    png_paths = sorted(target_dir.glob("step_*.png"))
    assert len(png_paths) == 4  # 2 steps * (before + after)

    for png_path in png_paths:
        assert json_mtime >= png_path.stat().st_mtime, (
            "session.json must be written last; "
            "{} mtime exceeds session.json mtime".format(png_path.name)
        )
