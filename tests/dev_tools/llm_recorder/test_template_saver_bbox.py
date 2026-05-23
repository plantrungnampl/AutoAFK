"""Unit tests for ``TemplateSaver``.

Covers the design's "Bbox validation rules" plus atomic-write behaviour:
filename regex, bbox bounds, source-step-index range, force semantics,
crop round-trip dimensions, and resilience when ``os.replace`` fails.
"""

import os
from pathlib import Path

import pytest
from PIL import Image

from src.dev_tools.llm_recorder import template_saver as template_saver_module
from src.dev_tools.llm_recorder.models import (
    RecordedStep,
    RecordingSession,
    TemplateProposal,
)
from src.dev_tools.llm_recorder.template_saver import TemplateSaver


def _make_session(num_steps: int = 1) -> RecordingSession:
    """Build a ``RecordingSession`` with ``num_steps`` tiny red 1080x1920 steps."""
    steps = []
    for i in range(num_steps):
        before = Image.new("RGB", (1080, 1920), "red")
        after = Image.new("RGB", (1080, 1920), "red")
        steps.append(
            RecordedStep(
                index=i,
                screenshot_before=before,
                screenshot_after=after,
                tap_coords=(100 + i, 200 + i),
                label=None,
            )
        )
    return RecordingSession(steps=steps)


def _make_proposal(
    *,
    filename: str = "buttons/foo.png",
    bbox=(10, 20, 100, 50),
    source_step_index: int = 0,
) -> TemplateProposal:
    return TemplateProposal(
        source_step_index=source_step_index,
        bbox=bbox,
        filename=filename,
        rationale="test",
    )


# --- Filename regex enforcement -------------------------------------------------


def test_filename_regex_rejects_disallowed_subdirectory(tmp_path: Path) -> None:
    saver = TemplateSaver(img_root=tmp_path)
    proposal = _make_proposal(filename="mercs/foo.png")
    session = _make_session()

    with pytest.raises(ValueError):
        saver.save(proposal, session)


def test_filename_regex_rejects_uppercase(tmp_path: Path) -> None:
    saver = TemplateSaver(img_root=tmp_path)
    proposal = _make_proposal(filename="buttons/Foo.png")
    session = _make_session()

    with pytest.raises(ValueError):
        saver.save(proposal, session)


def test_filename_regex_rejects_nested_path(tmp_path: Path) -> None:
    saver = TemplateSaver(img_root=tmp_path)
    proposal = _make_proposal(filename="buttons/sub/foo.png")
    session = _make_session()

    with pytest.raises(ValueError):
        saver.save(proposal, session)


# --- Bbox out-of-bounds rejection ----------------------------------------------


def test_bbox_x_plus_w_exceeds_device_width_raises(tmp_path: Path) -> None:
    saver = TemplateSaver(img_root=tmp_path)
    proposal = _make_proposal(bbox=(1000, 0, 200, 50))
    session = _make_session()

    with pytest.raises(ValueError):
        saver.save(proposal, session)


def test_bbox_y_plus_h_exceeds_device_height_raises(tmp_path: Path) -> None:
    saver = TemplateSaver(img_root=tmp_path)
    proposal = _make_proposal(bbox=(0, 1900, 50, 100))
    session = _make_session()

    with pytest.raises(ValueError):
        saver.save(proposal, session)


def test_bbox_zero_width_raises(tmp_path: Path) -> None:
    saver = TemplateSaver(img_root=tmp_path)
    proposal = _make_proposal(bbox=(0, 0, 0, 50))
    session = _make_session()

    with pytest.raises(ValueError):
        saver.save(proposal, session)


def test_bbox_negative_origin_raises(tmp_path: Path) -> None:
    saver = TemplateSaver(img_root=tmp_path)
    proposal = _make_proposal(bbox=(-1, 0, 50, 50))
    session = _make_session()

    with pytest.raises(ValueError):
        saver.save(proposal, session)


# --- Source step index range ---------------------------------------------------


def test_source_step_index_negative_raises(tmp_path: Path) -> None:
    saver = TemplateSaver(img_root=tmp_path)
    proposal = _make_proposal(source_step_index=-1)
    session = _make_session(num_steps=2)

    with pytest.raises(ValueError):
        saver.save(proposal, session)


def test_source_step_index_at_or_above_len_raises(tmp_path: Path) -> None:
    saver = TemplateSaver(img_root=tmp_path)
    session = _make_session(num_steps=2)
    proposal = _make_proposal(source_step_index=len(session.steps))

    with pytest.raises(ValueError):
        saver.save(proposal, session)


# --- Round-trip ----------------------------------------------------------------


def test_round_trip_writes_png_with_expected_pixel_dimensions(tmp_path: Path) -> None:
    saver = TemplateSaver(img_root=tmp_path)
    bbox = (10, 20, 123, 45)  # x, y, w, h
    proposal = _make_proposal(filename="labels/round_trip.png", bbox=bbox)
    session = _make_session()

    written = saver.save(proposal, session)

    assert written == tmp_path / "labels" / "round_trip.png"
    assert written.is_file()
    with Image.open(written) as opened:
        assert opened.size == (bbox[2], bbox[3])
        assert opened.format == "PNG"


# --- force semantics -----------------------------------------------------------


def test_force_false_raises_file_exists_error(tmp_path: Path) -> None:
    saver = TemplateSaver(img_root=tmp_path)
    proposal = _make_proposal(filename="buttons/dup.png", bbox=(0, 0, 32, 32))
    session = _make_session()

    saver.save(proposal, session)

    with pytest.raises(FileExistsError):
        saver.save(proposal, session)


def test_force_true_overwrites_existing_target(tmp_path: Path) -> None:
    saver = TemplateSaver(img_root=tmp_path)
    target_rel = "buttons/over.png"
    first = _make_proposal(filename=target_rel, bbox=(0, 0, 10, 10))
    second = _make_proposal(filename=target_rel, bbox=(0, 0, 50, 70))
    session = _make_session()

    written = saver.save(first, session)
    with Image.open(written) as opened:
        assert opened.size == (10, 10)

    overwritten = saver.save(second, session, force=True)
    assert overwritten == written
    with Image.open(overwritten) as opened:
        assert opened.size == (50, 70)


# --- Partial-write resilience --------------------------------------------------


def test_os_replace_failure_leaves_no_file_at_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saver = TemplateSaver(img_root=tmp_path)
    proposal = _make_proposal(filename="buttons/partial.png", bbox=(0, 0, 32, 32))
    session = _make_session()

    def boom(src: str, dst: str) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(template_saver_module.os, "replace", boom)

    with pytest.raises(OSError):
        saver.save(proposal, session)

    target = tmp_path / "buttons" / "partial.png"
    assert not target.exists(), "target file must not exist after failed replace"

    # Only the temp artifact (if any) may remain in the target's directory.
    leftovers = list((tmp_path / "buttons").iterdir())
    for leftover in leftovers:
        assert leftover.name.startswith("partial.png.tmp-"), (
            "unexpected leftover file: {}".format(leftover)
        )
