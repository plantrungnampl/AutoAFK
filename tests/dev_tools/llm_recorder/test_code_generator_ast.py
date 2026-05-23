"""Unit tests for :class:`src.dev_tools.llm_recorder.code_generator.CodeGenerator`.

Covers the six cases listed in tasks.md task 5.2:

- ``module_filename`` missing the ``_activities`` suffix raises ``ValueError``.
- ``class_name`` not matching the ``^[A-Z][A-Za-z0-9]*Activities$`` regex
  raises ``ValueError``.
- A valid source string is written byte-for-byte and reads back identical UTF-8.
- Invalid Python source raises ``SyntaxError`` and writes no file.
- ``force=False`` raises ``FileExistsError`` on a pre-existing target.
- ``force=True`` overwrites a pre-existing target.

Tests inject a temporary activities directory via the ``CodeGenerator``
constructor so the real ``src/activities/`` is never touched.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from src.dev_tools.llm_recorder.code_generator import CodeGenerator
from src.dev_tools.llm_recorder.models import ActivityProposal


VALID_SOURCE = (
    '"""Generated event_x activity module."""\n'
    "\n"
    "\n"
    "class EventXActivities:\n"
    "    def run(self):\n"
    "        return True\n"
)


def make_proposal(**overrides) -> ActivityProposal:
    """Build a fully-valid ActivityProposal that callers can mutate one field at a time."""
    base = ActivityProposal(
        module_filename="event_x_activities.py",
        class_name="EventXActivities",
        source_text=VALID_SOURCE,
        registration_snippet="self.event_x = EventXActivities(...)",
        call_site_snippet="if config.getboolean('DAILIES', 'runeventx', fallback=False):\n    self.event_x.run()",
        config_section="DAILIES",
        config_key="runeventx",
    )
    return replace(base, **overrides)


@pytest.fixture
def generator(tmp_path: Path) -> CodeGenerator:
    """A CodeGenerator writing under ``tmp_path/activities`` (never the real tree)."""
    return CodeGenerator(activities_dir=tmp_path / "activities")


def test_module_filename_missing_suffix_raises_value_error(generator: CodeGenerator) -> None:
    proposal = make_proposal(module_filename="foo.py")

    with pytest.raises(ValueError):
        generator.save(proposal)

    assert list(generator.activities_dir.glob("*")) == []


def test_class_name_lowercase_first_letter_raises_value_error(generator: CodeGenerator) -> None:
    proposal = make_proposal(class_name="fooActivities")

    with pytest.raises(ValueError):
        generator.save(proposal)

    assert list(generator.activities_dir.glob("*")) == []


def test_valid_source_written_byte_for_byte(generator: CodeGenerator) -> None:
    source = "x = 1\n"
    proposal = make_proposal(source_text=source)

    target = generator.save(proposal)

    assert target == generator.activities_dir / "event_x_activities.py"
    assert target.read_bytes() == source.encode("utf-8")
    assert target.read_text(encoding="utf-8") == source


def test_invalid_source_raises_syntax_error_and_writes_no_file(generator: CodeGenerator) -> None:
    proposal = make_proposal(source_text="def ")

    with pytest.raises(SyntaxError):
        generator.save(proposal)

    target = generator.activities_dir / "event_x_activities.py"
    assert not target.exists()
    # No leftover temp files either.
    if generator.activities_dir.exists():
        assert list(generator.activities_dir.glob("*")) == []


def test_force_false_raises_file_exists_error_on_existing_target(generator: CodeGenerator) -> None:
    proposal = make_proposal(source_text="x = 1\n")
    generator.save(proposal)

    second = make_proposal(source_text="x = 2\n")
    with pytest.raises(FileExistsError):
        generator.save(second, force=False)

    target = generator.activities_dir / "event_x_activities.py"
    assert target.read_text(encoding="utf-8") == "x = 1\n"


def test_force_true_overwrites_existing_target(generator: CodeGenerator) -> None:
    generator.save(make_proposal(source_text="x = 1\n"))

    target = generator.save(make_proposal(source_text="x = 2\n"), force=True)

    assert target.read_text(encoding="utf-8") == "x = 2\n"
