"""Tests for what the clip list decides, as opposed to how it draws.

Same rule as the rest of this suite: it runs at a normal prompt with no
TouchDesigner. That is possible because the parts of `lister.py` worth testing
were written to take their data rather than fetch it - `cell_text` takes a
table-shaped object and an order, `active_row` takes a list and an index, and
`row_bg` takes a row number. The `init_*` callbacks and `refresh` are not here,
because a test of those would be a test of a stub of a List COMP.

The two functions with real edge cases in them are the two that were easy to
get wrong. `format_duration` has to tell a short clip from an unmeasured one,
which are both small numbers. And `active_row` has to tell "row 0" from "no
row", which are both falsy - a caller that let those collapse would highlight
the header every time nothing was playing.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tdpy import lister, startup  # noqa: E402


class Cell:
    """The one thing this code asks of a DAT cell: a `.val`."""

    def __init__(self, val):
        self.val = val


class FakeTable:
    """A Table DAT's `[row, column]` and `numRows`, and nothing else.

    Indexed by column *name*, which is how `cell_text` reads it, and holding a
    header row, which is how `build._fill_playlist` writes it. Returns None for
    a cell that is not there, which is what a DAT does.
    """

    path = "/project1/generated/playlist"

    def __init__(self, columns):
        self.columns = dict(columns)
        self.numRows = max((len(v) for v in self.columns.values()), default=0)

    def __getitem__(self, key):
        row, column = key
        values = self.columns.get(column)
        if values is None or row < 0 or row >= len(values):
            return None
        return Cell(values[row])


@pytest.fixture
def playlist_of_three():
    """Three clips and a header row, as the playlist DAT holds them."""
    return FakeTable(
        {
            "name": ["name", "alpha", "bravo", "charlie"],
            "duration": ["duration", "222.7", "0", "3725.0"],
        }
    )


@pytest.fixture
def silent(monkeypatch):
    """Collect reported lines instead of writing them to the log."""
    lines = []
    monkeypatch.setattr(startup, "report", lines.append)
    return lines


class TestFormatDuration:
    def test_minutes_and_seconds(self):
        assert lister.format_duration(222.7) == "3:42"

    def test_seconds_are_always_two_digits(self):
        # 3:2 would sort and scan wrongly down a column of them.
        assert lister.format_duration(182) == "3:02"

    def test_hours_appear_only_when_there_are_some(self):
        assert lister.format_duration(3725.0) == "1:02:05"
        assert lister.format_duration(3599) == "59:59"

    def test_reads_the_strings_a_dat_actually_holds(self):
        # The table stores every cell as text, so this is the real input.
        assert lister.format_duration("222.7") == "3:42"

    def test_truncates_rather_than_rounds(self):
        # A 59.7 second clip reading 1:00 would be the one row in the table
        # that disagreed with the file it names.
        assert lister.format_duration(59.7) == "0:59"

    def test_zero_is_unmeasured_not_a_zero_length_clip(self):
        # Zero is TouchDesigner's own sentinel for a file it could not measure,
        # and what probe() returns when there is no ffprobe at all.
        assert lister.format_duration(0) == lister.UNMEASURED
        assert lister.format_duration("0") == lister.UNMEASURED
        assert lister.format_duration("0.0") == lister.UNMEASURED

    def test_a_negative_duration_is_unmeasured_too(self):
        assert lister.format_duration(-5) == lister.UNMEASURED

    def test_nonsense_reads_as_unmeasured_rather_than_raising(self):
        # This runs inside a cell callback, where an exception is both hard to
        # see and disproportionate to one bad row.
        assert lister.format_duration("") == lister.UNMEASURED
        assert lister.format_duration("n/a") == lister.UNMEASURED
        assert lister.format_duration(None) == lister.UNMEASURED


class TestActiveRow:
    def test_offsets_past_the_header(self):
        # Playlist row 0 is list row 1, because list row 0 is the header.
        assert lister.active_row([0, 1, 2], 0) == 1
        assert lister.active_row([0, 1, 2], 2) == 3

    def test_follows_the_order_rather_than_the_table(self):
        # The case Phase 4 introduces: a shuffled deck, where the clip at
        # playlist row 0 is not the first thing shown.
        assert lister.active_row([2, 0, 1], 0) == 2
        assert lister.active_row([2, 0, 1], 2) == 1

    def test_nothing_playing_is_none_not_the_header(self):
        # None and 0 are both falsy, and 0 is a real row - the header. A caller
        # that let them collapse would highlight the header whenever the player
        # had no file loaded.
        assert lister.active_row([0, 1, 2], None) is None

    def test_a_clip_outside_the_order_is_none(self):
        assert lister.active_row([0, 1], 5) is None

    def test_an_empty_order_highlights_nothing(self):
        assert lister.active_row([], 0) is None


class TestRowLook:
    def test_the_active_row_wins_over_striping(self):
        assert lister.row_bg(3, active=3) == lister.ACTIVE_BG
        assert lister.row_text_color(3, active=3) == lister.ACTIVE_TEXT_COLOR

    def test_the_header_is_its_own_colour(self):
        assert lister.row_bg(0) == lister.HEADER_BG
        assert lister.row_text_color(0) == lister.HEADER_TEXT_COLOR

    def test_ordinary_rows_stripe(self):
        assert lister.row_bg(1) != lister.row_bg(2)
        assert lister.row_bg(1) == lister.row_bg(3)

    def test_no_row_is_active_when_nothing_is_playing(self):
        # active=None must not match row None-ishly or compare equal to 0.
        assert lister.row_bg(0, active=None) == lister.HEADER_BG
        assert lister.row_bg(1, active=None) != lister.ACTIVE_BG

    def test_the_header_can_be_the_active_row_only_if_told_to_be(self):
        # Guards the arithmetic in active_row: nothing should ever pass 0, and
        # if something did it would be a visible bug rather than a silent one.
        assert lister.row_bg(0, active=0) == lister.ACTIVE_BG


class TestCellText:
    def test_the_header_row_comes_from_the_columns(self, playlist_of_three):
        labels = [
            lister.cell_text(playlist_of_three, [0, 1, 2], 0, col)
            for col in range(len(lister.COLUMNS))
        ]
        assert labels == [label for _, label, _, _ in lister.COLUMNS]

    def test_a_clip_reads_its_name_and_a_formatted_length(self, playlist_of_three):
        assert lister.cell_text(playlist_of_three, [0, 1, 2], 1, 0) == "alpha"
        assert lister.cell_text(playlist_of_three, [0, 1, 2], 1, 1) == "3:42"

    def test_rows_come_out_in_play_order(self, playlist_of_three):
        # The reason cell_text takes an order at all. With a shuffled deck the
        # list must read down in the order the clips will play, not the order
        # the table happens to store them in.
        names = [
            lister.cell_text(playlist_of_three, [2, 0, 1], row, 0)
            for row in (1, 2, 3)
        ]
        assert names == ["charlie", "alpha", "bravo"]

    def test_an_unmeasured_clip_says_so_in_its_own_row(self, playlist_of_three):
        assert lister.cell_text(playlist_of_three, [0, 1, 2], 2, 1) == (
            lister.UNMEASURED
        )

    def test_reads_by_column_name_not_position(self):
        # playlist.COLUMNS decides the table's order; COLUMNS here decides the
        # list's. Neither should have to agree with the other.
        table = FakeTable(
            {
                "duration": ["duration", "60"],
                "path": ["path", "media/alpha.mkv"],
                "name": ["name", "alpha"],
            }
        )
        assert lister.cell_text(table, [0], 1, 0) == "alpha"
        assert lister.cell_text(table, [0], 1, 1) == "1:00"

    def test_a_row_past_the_end_is_blank_rather_than_an_error(self, playlist_of_three):
        # The List COMP calls this for every cell its Rows parameter claims
        # exists, and a rescan can find fewer files than the last one did.
        assert lister.cell_text(playlist_of_three, [0, 1, 2], 9, 0) == ""

    def test_a_column_past_the_end_is_blank(self, playlist_of_three):
        assert lister.cell_text(playlist_of_three, [0, 1, 2], 1, 9) == ""
        assert lister.cell_text(playlist_of_three, [0, 1, 2], 0, 9) == ""

    def test_no_table_at_all_is_blank_but_still_draws_the_header(self):
        # A build with an empty media folder: the header is worth drawing, the
        # rows are not there to draw.
        assert lister.cell_text(None, [], 1, 0) == ""
        assert lister.cell_text(None, [], 0, 0) == lister.COLUMNS[0][1]

    def test_a_missing_column_in_the_table_is_blank(self):
        table = FakeTable({"name": ["name", "alpha"]})
        assert lister.cell_text(table, [0], 1, 0) == "alpha"
        assert lister.cell_text(table, [0], 1, 1) == ""


class TestColumnsAgreeWithTheRestOfTheProject:
    def test_every_displayed_column_exists_in_the_playlist(self):
        # The one place the two halves are checked against each other: the
        # playlist decides what it stores, this decides what is shown, and a
        # column renamed on either side would otherwise surface as a list of
        # empty cells rather than as a failure.
        from tdpy import playlist

        keys = {key for key, _, _, _ in lister.COLUMNS}
        assert keys <= set(playlist.COLUMNS)

    def test_the_build_sizes_the_list_from_these_columns(self):
        from tdpy import build

        assert len(lister.COLUMNS) >= 1
        assert build.CLIP_LIST_HEIGHT > lister.HEADER_HEIGHT + lister.ROW_HEIGHT

    def test_right_aligned_names_a_real_column(self):
        keys = {key for key, _, _, _ in lister.COLUMNS}
        assert lister.RIGHT_ALIGNED <= keys

    def test_exactly_one_column_stretches(self):
        # Zero and the list leaves a gap at its right edge; more than one and
        # the widths stop being predictable from the numbers written above.
        stretchy = [key for key, _, _, stretch in lister.COLUMNS if stretch]
        assert len(stretchy) == 1

    def test_the_columns_fit_the_panel_they_are_drawn_in(self):
        from tdpy import build

        fixed = sum(width for _, _, width, _ in lister.COLUMNS)
        assert fixed <= build._panel_width()

    def test_the_watched_parameter_is_the_one_the_clip_is_loaded_into(self):
        # The highlight follows this parameter and nothing else. It is the
        # coupling worth writing down, because breaking it does not fail: the
        # list would simply stop moving, which looks like a clip that is still
        # playing. `player.next_clip` and `build._add_player` are the two
        # places that write it.
        from tdpy import build

        assert build.CLIP_LIST_WATCH_PAR == "file"
