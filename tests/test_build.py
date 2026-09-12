"""Tests for the parts of the build that decide something.

`build.py` mostly describes a network, and a test of that would be a test of a
stub of TouchDesigner. Two functions in it are not description, and both are
here: the display-index check, and the panel geometry the window is sized from.

The display check is tested because it was wrong. It was written as a 1-based
range on the assumption that three displays are numbered 1, 2, 3, and it
therefore passed a display 3 that does not exist and would have refused display
0, which is the primary. The Window COMP's Display parameter is a zero-based
index into the same list the Monitors DAT shows - TouchDesigner's own message
for an out-of-range one, in libTD.dll, is "Monitor specified in <op> does not
exist. Opening on monitor 0 instead.", and a fallback onto monitor 0 only makes
sense where 0 is a monitor.

`td` is passed into that function rather than imported by it, which is what
makes this testable at a prompt at all - a fake with a `monitors` list is the
whole of the stub required.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tdpy import build, startup  # noqa: E402


class FakeTd:
    """Just enough `td` for the display check: a monitors sequence."""

    def __init__(self, count):
        self.monitors = list(range(count))


@pytest.fixture
def silent(monkeypatch):
    """Collect reported lines instead of writing them to the log."""
    lines = []
    monkeypatch.setattr(startup, "report", lines.append)
    return lines


class TestDisplayAttached:
    def test_every_index_of_a_three_display_machine(self, silent):
        td = FakeTd(3)
        assert [build._display_attached(n, td) for n in (0, 1, 2)] == [True] * 3
        assert silent == []

    def test_the_primary_is_display_zero_not_display_one(self, silent):
        # The half of the original bug that never showed up on this machine,
        # because nothing here asked for the primary.
        assert build._display_attached(0, FakeTd(1)) is True
        assert silent == []

    def test_one_past_the_end_is_refused(self, silent):
        # The half that did: three displays, and 3 is not one of them.
        assert build._display_attached(3, FakeTd(3)) is False
        assert len(silent) == 1

    def test_the_report_gives_the_range_rather_than_only_the_count(self, silent):
        # A count alone is what made 3 look reasonable in the first place.
        build._display_attached(3, FakeTd(3))
        assert "0-2" in silent[0]

    def test_a_negative_index_is_refused(self, silent):
        assert build._display_attached(-1, FakeTd(3)) is False

    def test_a_single_display_machine_refuses_the_second(self, silent):
        assert build._display_attached(1, FakeTd(1)) is False

    def test_no_monitors_list_leaves_the_placing_to_touchdesigner(self, silent):
        # Outside TouchDesigner there is no td.monitors at all. Guessing wrong
        # here should not stop a build, so the answer is to say nothing and let
        # TouchDesigner place the window - it has its own fallback.
        class Bare:
            pass

        assert build._display_attached(2, Bare()) is True
        assert silent == []

    def test_the_project_puts_its_two_windows_on_different_displays(self):
        # The requirement the phase exists for, and the one thing about these
        # two constants that a later edit could quietly break.
        assert build.VIDEO_WINDOW_DISPLAY != build.CONTROL_WINDOW_DISPLAY


class TestPanelWidth:
    def test_spacing_falls_between_buttons_and_not_outside_them(self, monkeypatch):
        monkeypatch.setattr(build, "BUTTON_WIDTH", 100)
        monkeypatch.setattr(build, "PANEL_SPACING", 10)
        monkeypatch.setattr(build, "CONTROL_BUTTONS", (("a", "a"), ("b", "b")))
        assert build._panel_width() == 210

    def test_one_button_has_no_spacing_at_all(self, monkeypatch):
        monkeypatch.setattr(build, "BUTTON_WIDTH", 100)
        monkeypatch.setattr(build, "PANEL_SPACING", 10)
        monkeypatch.setattr(build, "CONTROL_BUTTONS", (("a", "a"),))
        assert build._panel_width() == 100

    def test_no_buttons_is_not_a_negative_width(self, monkeypatch):
        monkeypatch.setattr(build, "CONTROL_BUTTONS", ())
        assert build._panel_width() == 0


class TestPanelHeight:
    #: The row heights `_panel_height` sums, named here so this test knows what
    #: the panel is made of without restating how many rows that is. Adding a
    #: row means adding a name to this tuple and nothing else - the previous
    #: version of these tests wrote the arithmetic out longhand and broke the
    #: moment the diagnostics strip arrived, which is the failure this avoids.
    ROW_HEIGHTS = (
        "BUTTON_HEIGHT",
        "SETTINGS_ROW_HEIGHT",
        "PARAMETER_HEIGHT",
        "CLIP_LIST_HEIGHT",
        "DIAGNOSTICS_HEIGHT",
    )

    def test_gaps_fall_between_the_rows_and_not_below_the_last(self, monkeypatch):
        # Every row 100 and every gap 10, so the answer is readable: n rows and
        # n-1 gaps. A gap below the last row is the bug this catches, and it
        # shows up as the panel being exactly one spacing too tall.
        for name in self.ROW_HEIGHTS:
            monkeypatch.setattr(build, name, 100)
        monkeypatch.setattr(build, "PANEL_SPACING", 10)
        count = len(self.ROW_HEIGHTS)
        assert build._panel_height() == count * 100 + (count - 1) * 10

    def test_it_sums_every_row_the_panel_actually_has(self, monkeypatch):
        # Guards the list above against the module moving on without it. Each
        # row is given a distinct height, so a row left out of `_panel_height`
        # or missing from ROW_HEIGHTS changes the total.
        for index, name in enumerate(self.ROW_HEIGHTS):
            monkeypatch.setattr(build, name, 2 ** index)
        monkeypatch.setattr(build, "PANEL_SPACING", 0)
        assert build._panel_height() == 2 ** len(self.ROW_HEIGHTS) - 1

    def test_the_window_is_not_taller_than_the_display_it_opens_on(self):
        # 1080 on a 1440-high panel, with a title bar to spare. Worth a test
        # because the panel has grown three times now and each time by a whole
        # row, and a window taller than its display is not obviously wrong on a
        # machine with a 4K primary to open it on instead.
        assert build._panel_height() <= 1400


class TestSliderWidth:
    def test_the_row_fills_the_panel_exactly(self):
        # The sliders absorb what the toggles leave, so the row is the panel's
        # width give or take the integer division - a strip of dead panel here
        # is the symptom of getting the gap count wrong.
        from tdpy import settings

        used = (
            len(settings.toggles()) * build.SETTINGS_TOGGLE_WIDTH
            + len(settings.sliders()) * build._slider_width()
            + (len(settings.SETTINGS) - 1) * build.PANEL_SPACING
        )
        assert build._panel_width() - used < len(settings.sliders())

    def test_no_sliders_is_not_a_division_by_zero(self, monkeypatch):
        from tdpy import settings

        monkeypatch.setattr(settings, "SETTINGS", settings.toggles())
        assert build._slider_width() == 0

    def test_a_row_wider_than_the_panel_is_not_a_negative_width(self, monkeypatch):
        monkeypatch.setattr(build, "SETTINGS_TOGGLE_WIDTH", 10_000)
        assert build._slider_width() == 0


class FakeChannel:
    """A `td.Channel` as far as this expression is concerned: `eval()`, no more.

    Deliberately **not** a float and deliberately not formattable. The first
    version of these tests used plain floats and passed while both readouts sat
    in error in TouchDesigner, because a float supports `:.1f` and a Channel
    does not. A fake that accepts more than the real object is not a test.
    """

    def __init__(self, value):
        self.value = value

    def eval(self, index=None):
        return self.value


class FakeChannels:
    """An Info CHOP's `[]`, answering a FakeChannel per channel name."""

    def __init__(self, values):
        self.values = values

    def __getitem__(self, name):
        return FakeChannel(self.values[name])


class TestDiagnosticsExpression:
    """The readout's text, which is a Python expression TouchDesigner evaluates.

    Worth testing at a prompt precisely because its failure mode in the app is
    quiet from the panel's side: the parameter goes into error and the strip
    stays blank, which reads as a player with nothing to report rather than as a
    readout that never worked.
    """

    PATH = "/project1/generated/playerAInfo"

    VALUES = {
        "hardware_decode": 1.0,
        "pre_read_misses": 3.0,
        "num_pre_read_frames": 12.0,
        "last_frame_decode_time": 4.25,
        "last_gpu_upload_time": 0.5,
        "has_decode_errors": 0.0,
    }

    def test_it_is_a_valid_python_expression(self):
        # The whole point. compile() in eval mode is the same parse
        # TouchDesigner will do, run somewhere the failure is visible.
        expression = build._diagnostics_expression("playerA", self.PATH)
        compile(expression, "<expr>", "eval")

    def test_it_evaluates_to_the_line_it_promises(self):
        # Evaluated against a stand-in `op` so the formatting is checked rather
        # than assumed - the f-string nesting here is easy to get subtly wrong
        # and impossible to see wrong in a screenshot.
        expression = build._diagnostics_expression("playerA", self.PATH)
        result = eval(expression, {"op": lambda path: FakeChannels(self.VALUES)})
        assert result == (
            "playerA  hw 1 miss 3 buf 12 dec 4.2 gpu 0.5 err 0"
        )

    def test_every_channel_is_evaluated_rather_than_formatted_directly(self):
        # The bug this class failed to catch the first time, now the thing it
        # exists for. `op(chop)['chan']` answers a td.Channel, and formatting
        # one raises "unsupported format string passed to
        # td.Channel.__format__" - which both readouts did in TouchDesigner
        # while these tests were green, because the fake handed back floats.
        # Floats format fine and are not what the app has.
        #
        # Asserted on the text rather than by catching an exception: the
        # question is whether every reference goes through Channel.eval(), and
        # one that did not would simply format the object it was given.
        expression = build._diagnostics_expression("playerA", self.PATH)
        assert expression.count(".eval():") == len(build.DIAGNOSTIC_CHANNELS)

    def test_it_does_not_work_against_plain_numbers(self):
        # The other half of the same point, from the opposite direction: if
        # this ever passes, the expression has stopped requiring the shape the
        # app actually hands it and the fake above has stopped being a fake.
        expression = build._diagnostics_expression("playerA", self.PATH)
        with pytest.raises(AttributeError):
            eval(expression, {"op": lambda path: self.VALUES})

    def test_it_names_the_info_chop_it_was_given(self):
        # The dependency TouchDesigner tracks. If the path stopped appearing in
        # the expression the readout would cook when it felt like it, and a
        # stale diagnostic is worse than none.
        expression = build._diagnostics_expression("playerB", self.PATH)
        assert expression.count(self.PATH) == len(build.DIAGNOSTIC_CHANNELS)

    def test_every_channel_is_named(self):
        expression = build._diagnostics_expression("playerA", self.PATH)
        for channel, _, _ in build.DIAGNOSTIC_CHANNELS:
            assert channel in expression

    def test_the_channels_are_movie_file_in_top_channels(self):
        # `dropped_frames` is in libTD.dll and belongs to the Video Device Out
        # TOP, not to this one - it was the obvious name for the symptom and
        # would have been a channel that is simply not there. The list below is
        # from Point_File_In_TOP.htm, which enumerates the shared file-reading
        # channel set that Movie File In TOP's own page gives only in prose.
        published = {
            "loop_frame", "pre_read_misses", "last_pre_read_miss_wait",
            "hard_drive_timeouts", "num_pre_read_frames", "first_index_to_read",
            "last_frame_hd_read_time", "last_frame_decode_time",
            "last_gpu_upload_time", "open", "opening", "open_failed",
            "fully_pre_read", "true_length", "hardware_yuv_to_rgb",
            "has_non_av_track", "pre_read_fails", "disk_read_mbit_rate",
            "has_decode_errors", "num_decode_chunks", "hardware_decode",
        }
        for channel, _, _ in build.DIAGNOSTIC_CHANNELS:
            assert channel in published, f"{channel} is not on this operator"
        assert "dropped_frames" not in published
