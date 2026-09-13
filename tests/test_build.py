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

from tdpy import build, controls, startup  # noqa: E402


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
        "AUDIO_ROW_HEIGHT",
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
    def test_every_row_fills_the_panel_exactly(self):
        # The sliders absorb what the toggles leave, so a row is the panel's
        # width give or take the integer division - a strip of dead panel here
        # is the symptom of getting the gap count wrong.
        #
        # Per page, because a page is a row. Measuring every setting at once
        # would still have balanced, and would have described a single-row
        # panel that no longer exists.
        from tdpy import settings

        for page in settings.PANEL_PAGES:
            used = (
                len(settings.toggles(page)) * build.SETTINGS_TOGGLE_WIDTH
                + len(settings.sliders(page)) * build._slider_width(page)
                + (len(settings.on_page(page)) - 1) * build.PANEL_SPACING
            )
            assert build._panel_width() - used < len(settings.sliders(page)), page

    def test_a_row_of_four_sliders_is_not_measured_against_all_nine(self):
        # The mixer's row and the cycle's row hold different numbers of
        # controls, so their sliders are different widths. A `_slider_width`
        # that ignored its page would hand both rows the same number and one
        # of the two would not fill the panel - which is exactly what the
        # single-row version did when the audio settings arrived.
        from tdpy import settings

        player = build._slider_width(settings.PAGE_PLAYER)
        audio = build._slider_width(settings.PAGE_AUDIO)
        assert player != audio
        assert player > 0 and audio > 0

    def test_no_sliders_is_not_a_division_by_zero(self, monkeypatch):
        from tdpy import settings

        monkeypatch.setattr(settings, "SETTINGS", settings.toggles())
        assert build._slider_width(settings.PAGE_PLAYER) == 0

    def test_a_row_wider_than_the_panel_is_not_a_negative_width(self, monkeypatch):
        from tdpy import settings

        monkeypatch.setattr(build, "SETTINGS_TOGGLE_WIDTH", 10_000)
        assert build._slider_width(settings.PAGE_PLAYER) == 0


class TestSettingsRows:
    def test_every_drawn_page_has_a_row_to_draw_it_in(self):
        # PANEL_PAGES decides which pages become bands; this table says what
        # each band is made of. A page in one and not the other is a row that
        # never appears, which on a panel of six bands is not obvious.
        from tdpy import settings

        rows = build._settings_rows(settings)
        for page in settings.PANEL_PAGES:
            assert page in rows, page

    def test_a_page_with_no_row_is_not_drawn_at_all(self):
        # Tuning holds settings that shape other settings. They belong in the
        # Parameter COMP, which shows every custom page, and not in a band of
        # performance sliders where they would take width from the controls
        # being played.
        from tdpy import settings

        assert settings.PAGE_TUNING in settings.PAGES
        assert settings.PAGE_TUNING not in settings.PANEL_PAGES
        assert settings.PAGE_TUNING not in build._settings_rows(settings)

    def test_every_row_names_a_place_in_the_stack(self):
        from tdpy import settings

        for _, row, _ in build._settings_rows(settings).values():
            assert row in build.PANEL_ROWS, row


class TestRowOrder:
    def test_every_named_row_has_a_distinct_place(self):
        assert len(set(build.PANEL_ROWS)) == len(build.PANEL_ROWS)

    def test_the_panel_stacks_as_many_rows_as_it_names(self):
        # PANEL_ROWS decides where a row sits and `_panel_height` decides how
        # tall the panel is. A row named in one and missing from the other is
        # either a band drawn off the bottom edge or a strip of dead panel, and
        # neither says which list was not updated.
        assert len(build.PANEL_ROWS) == len(TestPanelHeight.ROW_HEIGHTS)

    def test_the_mixer_sits_between_the_cycle_and_the_typed_fields(self):
        assert (
            build._row_order("settings")
            < build._row_order("audio")
            < build._row_order("parameters")
        )

    def test_an_unknown_row_raises_rather_than_landing_at_the_top(self):
        # ValueError out of .index(), not a silent 0 - a row that quietly took
        # the transport's position would look like a layout bug, not a typo.
        with pytest.raises(ValueError):
            build._row_order("mixer")


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


class FakePulsePar:
    """A pulse parameter: it can be fired, and it counts. Nothing else.

    Deliberately without a value to read or assign. `build.pulse` exists
    because assigning to a pulse parameter is not the same as firing it, and a
    fake that accepted an assignment would let that mistake back in.
    """

    def __init__(self):
        self.pulses = 0

    def pulse(self):
        self.pulses += 1


class FakeWindowPars:
    def __init__(self):
        self.winopen = FakePulsePar()


class FakeWindow:
    """A Window COMP with a Open as Separate Window pulse and an open state.

    `isOpen` is here and nothing reads it, on purpose: it is a real member of
    `windowCOMP`, it was the candidate guard for this function, and the
    decision was to pulse regardless. A test below states that by setting it.
    """

    def __init__(self, path, is_open=False):
        self.path = path
        self.par = FakeWindowPars()
        self.isOpen = is_open


class FakeParent:
    def __init__(self, windows):
        self.path = "/project1"
        self._windows = windows

    def op(self, name):
        return self._windows.get(name)


class TestReopenWindows:
    """The rebuild button's second half - see `tdpy/controls.py`'s CALLBACK."""

    def _both(self, **kwargs):
        return FakeParent({
            build.VIDEO_WINDOW_COMP: FakeWindow("/project1/videoPlayerWindow", **kwargs),
            build.CONTROL_WINDOW_COMP: FakeWindow("/project1/controlPanelWindow", **kwargs),
        })

    def test_it_pulses_both_windows(self, silent):
        parent = self._both()
        reopened = build._reopen_windows_under(parent)
        assert len(reopened) == 2
        assert all(window.par.winopen.pulses == 1 for window in reopened)
        assert silent == []

    def test_an_open_window_is_pulsed_anyway(self, silent):
        # The decision, stated as a test. Guarding on isOpen would make the
        # button do nothing for a window that is open but buried behind the
        # editor, which is one of the cases it is clicked for. The cost is a
        # display mode change on the exclusive video window every click.
        parent = self._both(is_open=True)
        reopened = build._reopen_windows_under(parent)
        assert [window.par.winopen.pulses for window in reopened] == [1, 1]

    def test_a_missing_window_does_not_stop_the_other(self, silent):
        # A failed build never made them, and startup.build() swallowed the
        # exception - so the button runs this against a parent holding neither.
        survivor = FakeWindow("/project1/controlPanelWindow")
        parent = FakeParent({build.CONTROL_WINDOW_COMP: survivor})
        reopened = build._reopen_windows_under(parent)
        assert reopened == [survivor]
        assert survivor.par.winopen.pulses == 1
        assert len(silent) == 1
        assert build.VIDEO_WINDOW_COMP in silent[0]

    def test_neither_window_is_reported_twice_and_raises_nothing(self, silent):
        assert build._reopen_windows_under(FakeParent({})) == []
        assert len(silent) == 2

    def test_the_button_calls_it_after_reloading(self):
        # The shim is a string, so nothing else would catch a rename of
        # reopen_windows - the button would simply stop working, at the moment
        # it is clicked rather than when the code is edited.
        assert hasattr(build, "reopen_windows")
        callback = controls.CALLBACK
        assert "build.reopen_windows()" in callback
        assert callback.index("tdpy.startup.reload()") < callback.index(
            "build.reopen_windows()"
        )
