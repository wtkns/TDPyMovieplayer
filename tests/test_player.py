"""Tests for the transport's decision-making.

Same rule as `test_playlist.py`: this runs at a normal prompt, with no
TouchDesigner. That is possible for exactly the parts of `player.py` that were
written to make it possible - `next_index` takes a list of strings, and
`clip_paths` takes anything shaped like a Table DAT. The functions that reach
for `td.op` are not tested here, because a test of those would be a test of a
stub of TouchDesigner rather than of this project.

`startup.report` is stubbed out wherever a test drives a reporting path. It
appends to `logs/startup.log`, which is a record of launches, and a test suite
writing into it would leave lines there that never happened in a session.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tdpy import player, startup  # noqa: E402


class Cell:
    """The one thing this code asks of a DAT cell: a `.val`."""

    def __init__(self, val):
        self.val = val


class FakeTable:
    """A Table DAT's `col()`, and nothing else.

    Returns None for an unknown column, which is what a DAT does, and includes
    the header cell in the column, which is also what a DAT does - both are the
    behaviours `clip_paths` is written against.
    """

    path = "/project1/generated/playlist"

    def __init__(self, columns):
        self.columns = {name: [Cell(v) for v in values]
                        for name, values in columns.items()}

    def col(self, name):
        return self.columns.get(name)


@pytest.fixture
def silent(monkeypatch):
    """Collect reported lines instead of writing them to the log."""
    lines = []
    monkeypatch.setattr(startup, "report", lines.append)
    return lines


class TestNextIndex:
    def test_steps_forward_one(self):
        assert player.next_index(["a", "b", "c"], "a") == 1
        assert player.next_index(["a", "b", "c"], "b") == 2

    def test_wraps_at_the_end(self):
        assert player.next_index(["a", "b", "c"], "c") == 0

    def test_a_single_clip_is_its_own_successor(self):
        assert player.next_index(["only.mkv"], "only.mkv") == 0

    def test_an_unknown_clip_starts_at_the_top(self):
        # Both cases that produce one: a build that loaded no file, and a clip
        # that has since been removed from media/.
        assert player.next_index(["a", "b"], "") == 0
        assert player.next_index(["a", "b"], "gone.mkv") == 0

    def test_an_empty_playlist_has_no_next(self):
        # None rather than 0: there is no row to load, and next_clip has to
        # tell that apart from "load the first one".
        assert player.next_index([], "a") is None

    def test_a_repeated_path_takes_the_first_of_them(self):
        # Two rows cannot really hold the same path - scan() walks a folder -
        # but index() picking the first is the behaviour, so it is written down
        # rather than left to be discovered.
        assert player.next_index(["a", "b", "a"], "a") == 1


class TestClipPaths:
    def test_drops_the_header_row(self):
        table = FakeTable({"path": ["path", "media/one.mkv", "media/two.mkv"]})
        assert player.clip_paths(table) == ["media/one.mkv", "media/two.mkv"]

    def test_a_header_only_table_is_empty(self):
        assert player.clip_paths(FakeTable({"path": ["path"]})) == []

    def test_no_table_at_all_is_empty(self):
        assert player.clip_paths(None) == []

    def test_a_missing_column_reports_and_returns_empty(self, silent):
        table = FakeTable({"name": ["name", "one.mkv"]})
        assert player.clip_paths(table) == []
        assert len(silent) == 1
        assert "path" in silent[0]

    def test_reads_by_column_name_not_position(self):
        # playlist.COLUMNS decides the order; this should not have to agree
        # with it separately.
        table = FakeTable(
            {
                "name": ["name", "one.mkv"],
                "path": ["path", "media/one.mkv"],
            }
        )
        assert player.clip_paths(table) == ["media/one.mkv"]


class TestCommand:
    def test_every_button_in_the_build_has_a_command(self):
        # The one place the two halves are checked against each other: build.py
        # names the buttons, player.py implements them, and nothing at runtime
        # would notice a button wired to nothing until it was pressed.
        from tdpy import build

        names = {name for name, _ in build.CONTROL_BUTTONS}
        assert names == set(player.COMMANDS)

    def test_an_unknown_command_reports_rather_than_raises(self, silent):
        assert player.command("rewind") is None
        assert len(silent) == 1
        assert "rewind" in silent[0]

    def test_the_report_lists_what_is_available(self, silent):
        player.command("rewind")
        for name in player.COMMANDS:
            assert name in silent[0]
