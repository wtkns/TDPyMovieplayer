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
    """The sum the control window is sized from.

    `_panel_height` reads `PANEL_ROW_HEIGHTS` over `PANEL_ROWS` since 9.6, so
    these monkeypatch that mapping rather than the constants behind it. The
    earlier version named the constants in a parallel tuple of its own, which
    was the same duplication the module had and broke each time a row arrived.
    """

    def _heights(self, monkeypatch, value):
        """Give every row in PANEL_ROWS the same height, whatever the rows are."""
        monkeypatch.setattr(
            build, "PANEL_ROW_HEIGHTS", {name: value for name in build.PANEL_ROWS}
        )

    def test_gaps_fall_between_the_rows_and_not_below_the_last(self, monkeypatch):
        # Every row 100 and every gap 10, so the answer is readable: n rows and
        # n-1 gaps. A gap below the last row is the bug this catches, and it
        # shows up as the panel being exactly one spacing too tall.
        self._heights(monkeypatch, 100)
        monkeypatch.setattr(build, "PANEL_SPACING", 10)
        count = len(build.PANEL_ROWS)
        assert build._panel_height() == count * 100 + (count - 1) * 10

    def test_it_sums_every_row_the_panel_actually_has(self, monkeypatch):
        # Each row a distinct power of two, so a row summed twice or skipped
        # changes the total rather than cancelling out.
        monkeypatch.setattr(
            build,
            "PANEL_ROW_HEIGHTS",
            {name: 2 ** index for index, name in enumerate(build.PANEL_ROWS)},
        )
        monkeypatch.setattr(build, "PANEL_SPACING", 0)
        assert build._panel_height() == 2 ** len(build.PANEL_ROWS) - 1

    def test_every_row_on_the_panel_has_a_height(self):
        # The trap 9.6 walked into and then closed. PANEL_ROWS decided a row's
        # position and a separate list decided its height, so a row added to
        # one and not the other left the panel taller than the window sized
        # from it - and a clipped bottom row reads as a layout bug rather than
        # as a missing number. A name missing now raises where it is summed.
        assert set(build.PANEL_ROW_HEIGHTS) == set(build.PANEL_ROWS)

    def test_a_row_with_no_height_raises_rather_than_being_skipped(
        self, monkeypatch
    ):
        # The control for the test above: it has to be able to fail. A row
        # silently worth nothing is the failure that was possible before.
        monkeypatch.setattr(build, "PANEL_ROWS", build.PANEL_ROWS + ("mixer",))
        with pytest.raises(KeyError):
            build._panel_height()

    def test_the_window_is_not_taller_than_the_display_it_opens_on(self):
        # 1400, with a title bar to spare on a 1440-high display. Worth a test
        # because the panel has grown four times now and each time by a whole
        # row, and a window taller than its display is not obviously wrong on a
        # machine with a 4K primary to open it on instead.
        #
        # 9.6 hit this bound rather than passing it: the health row needed 180
        # against 60 spare, and the clip list gave up 140 to make room. The
        # assertion is what forced that to be a decision rather than a window
        # quietly opening off the bottom of the screen.
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

    # A count of `PANEL_ROWS` against the heights beside it stood here until
    # 9.6. The two lists it reconciled are one mapping now, so the question it
    # asked is `TestPanelHeight.test_every_row_on_the_panel_has_a_height` -
    # set equality rather than a length, and with a control beside it.

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
    """An Info CHOP's `[]`, answering a FakeChannel per channel name.

    **None for a channel that is not there, because that is what a CHOP does.**
    This raised KeyError until 9.6, which made it stricter than the operator it
    stands for - and that is why nothing here caught `engine_frame_msec`, a
    channel `Engine_COMP.htm` lists and the live Info CHOP does not carry. In
    the app the absent channel answered None, `None.eval()` raised inside the
    parameter expression, and the readout went blank; in these tests it would
    have raised KeyError at the point of lookup, loudly and in the wrong place.
    A double that refuses what the real object permits hides exactly the bug
    the real object would have.
    """

    def __init__(self, values):
        self.values = values

    def __getitem__(self, name):
        found = self.values.get(name)
        return None if found is None else FakeChannel(found)


class TestDiagnosticsExpression:
    """The readout's text, which is a Python expression TouchDesigner evaluates.

    Worth testing at a prompt precisely because its failure mode in the app is
    quiet from the panel's side: the parameter goes into error and the strip
    stays blank, which reads as a player with nothing to report rather than as a
    readout that never worked.
    """

    PATH = "/project1/state"

    #: The state output as the host receives it. Both decks are on one CHOP
    #: now, which is why the expression has to pick its own deck's channels -
    #: a readout reading the other deck's would be a plausible number in the
    #: wrong column.
    VALUES = {
        "misses_a": 3.0,
        "buffer_a": 12.0,
        "misses_b": 1.0,
        "buffer_b": 9.0,
    }

    def test_it_is_a_valid_python_expression(self):
        # The whole point. compile() in eval mode is the same parse
        # TouchDesigner will do, run somewhere the failure is visible.
        expression = build._diagnostics_expression("playerA", self.PATH, 0)
        compile(expression, "<expr>", "eval")

    def test_it_evaluates_to_the_line_it_promises(self):
        # Evaluated against a stand-in `op` so the formatting is checked rather
        # than assumed - the f-string nesting here is easy to get subtly wrong
        # and impossible to see wrong in a screenshot.
        expression = build._diagnostics_expression("playerA", self.PATH, 0)
        result = eval(expression, {"op": lambda path: FakeChannels(self.VALUES)})
        assert result == "playerA  miss 3 buf 12"

    def test_each_deck_reads_its_own_channels(self):
        expression = build._diagnostics_expression("playerB", self.PATH, 1)
        result = eval(expression, {"op": lambda path: FakeChannels(self.VALUES)})
        assert result == "playerB  miss 1 buf 9"

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
        expression = build._diagnostics_expression("playerA", self.PATH, 0)
        assert expression.count(".eval():") == len(build.DIAGNOSTIC_READINGS)

    def test_it_does_not_work_against_plain_numbers(self):
        # The other half of the same point, from the opposite direction: if
        # this ever passes, the expression has stopped requiring the shape the
        # app actually hands it and the fake above has stopped being a fake.
        expression = build._diagnostics_expression("playerA", self.PATH, 0)
        with pytest.raises(AttributeError):
            eval(expression, {"op": lambda path: self.VALUES})

    def test_it_names_the_chop_it_was_given(self):
        # The dependency TouchDesigner tracks. If the path stopped appearing in
        # the expression the readout would cook when it felt like it, and a
        # stale diagnostic is worse than none.
        expression = build._diagnostics_expression("playerB", self.PATH, 1)
        assert expression.count(self.PATH) == len(build.DIAGNOSTIC_READINGS)

    def test_every_reading_is_named(self):
        from tdpy import link

        expression = build._diagnostics_expression("playerA", self.PATH, 0)
        for pair, _, _ in build.DIAGNOSTIC_READINGS:
            assert getattr(link, pair)[0] in expression

    def test_the_readings_are_channels_the_engine_publishes(self):
        # They were Movie File In TOP channels read off an Info CHOP until 9.5,
        # and are the same two numbers - `pre_read_misses` and
        # `num_pre_read_frames` - now derived where the decoder is and sent
        # across. A reading naming a channel the state output does not carry
        # would leave the strip blank, which reads as a player with nothing to
        # report rather than as a readout pointed at nothing.
        from tdpy import link

        for pair, _, _ in build.DIAGNOSTIC_READINGS:
            assert set(getattr(link, pair)) <= set(link.STATE_CHANNELS), pair


#: Every Info CHOP channel the health row names, at rest: TouchEngine has not
#: been asked for anything and the component is not loaded. Written as a dict
#: the tests turn on one flag at a time, because the thing being checked is
#: which flag the line picks out of a family and not what a healthy engine
#: happens to report.
def _engine_at_rest():
    values = {
        channel: 0.0 for _, states in build.HEALTH_STATES for _, channel in states
    }
    values.update({channel: 0.0 for channel, _, _ in build.HEALTH_READINGS})
    return values


class TestHealthExpression:
    """The engine health line, which is a Python expression as the strip is.

    Tested at a prompt for the reason the diagnostics strip is: its failure in
    the app is a blank row, which looks like an engine with nothing to say
    rather than a readout that never parsed. This one is worse in that respect,
    because a blank health row is indistinguishable from a healthy one unless
    you know it should be saying something.
    """

    PATH = "/project1/engineInfo"

    def _expression(self):
        return build._health_expression(
            self.PATH, build.HEALTH_STATES, build.HEALTH_READINGS
        )

    def _line(self, values):
        return eval(self._expression(), {"op": lambda path: FakeChannels(values)})

    def test_it_is_a_valid_python_expression(self):
        compile(self._expression(), "<expr>", "eval")

    def test_it_reads_the_state_each_family_is_actually_in(self):
        values = _engine_at_rest()
        values["engine_running"] = 1.0
        values["component_loaded"] = 1.0
        values["engine_fps"] = 59.94
        values["engine_read_ahead_misses"] = 3.0
        assert self._line(values) == (
            "engine running  component loaded  fps 59.9  drop 0  miss 3"
        )

    def test_a_fault_reads_as_a_fault_rather_than_as_a_missing_number(self):
        values = _engine_at_rest()
        values["engine_running"] = 1.0
        values["component_error"] = 1.0
        assert "component error" in self._line(values)

    def test_a_family_with_nothing_set_says_so(self):
        # What the line reads before the Info CHOP has cooked. '?' rather than
        # the first label, because "none" there would be a measurement that had
        # not been made - and this row's whole job is to be trusted about what
        # the engine is doing.
        assert self._line(_engine_at_rest()).startswith("engine ?  component ?")

    def test_every_channel_in_a_family_is_named_in_the_expression(self):
        # The dependency TouchDesigner tracks. A family whose channels were
        # assembled from a prefix would read the right number and register the
        # wrong dependency, so the line would cook when it felt like it.
        expression = self._expression()
        for _, states in build.HEALTH_STATES:
            for _, channel in states:
                assert repr(channel) in expression, channel

    def test_every_reading_is_named_in_the_expression(self):
        expression = self._expression()
        for channel, _, _ in build.HEALTH_READINGS:
            assert repr(channel) in expression, channel

    def test_every_reference_goes_through_eval(self):
        # `op(chop)['chan']` answers a td.Channel, and formatting one raises.
        # The diagnostics strip shipped that bug with green tests, because its
        # fake handed back floats and floats format fine.
        expression = self._expression()
        channels = sum(len(states) for _, states in build.HEALTH_STATES)
        assert expression.count(".eval()") == channels + len(build.HEALTH_READINGS)

    def test_it_does_not_work_against_plain_numbers(self):
        # The control for the test above: the fake has to be refusing what the
        # app refuses, or none of this measures anything.
        expression = self._expression()
        with pytest.raises(AttributeError):
            eval(expression, {"op": lambda path: _engine_at_rest()})

    def test_it_names_the_chop_it_was_given(self):
        assert self.PATH in self._expression()

    def test_the_channels_are_the_engine_comps_own(self):
        # Every name here is from `Engine_COMP.htm`'s "Specific Engine COMP
        # Info Channels" section, which is the authority for which exist - the
        # binary can refuse a name but never confirm one is this operator's.
        # Written out as literals rather than derived from the module, so a
        # channel renamed in build.py fails here instead of being agreed with.
        assert [c for c, _, _ in build.HEALTH_READINGS] == [
            "engine_fps",
            "engine_dropped_frames",
            "engine_read_ahead_misses",
        ]
        assert build.ENGINE_ERROR_CHANNELS == ("engine_error", "component_error")

    def test_the_channel_the_help_has_and_the_operator_does_not_is_gone(self):
        # `engine_frame_msec` is in `Engine_COMP.htm`'s Info CHOP section and
        # not on the live Info CHOP, which carries 53 channels and answers None
        # for it - read off the running Engine COMP on 2026-09-19. Named here
        # rather than only deleted, because the reason it left is the point: a
        # channel list that passed every test in this file until an operator
        # was asked.
        named = {c for c, _, _ in build.HEALTH_READINGS}
        named |= {c for _, states in build.HEALTH_STATES for _, c in states}
        assert "engine_frame_msec" not in named

    def test_the_error_channels_are_ones_the_line_also_reports(self):
        # The row colours on these two and names them in its state words, so a
        # red row always has a word explaining itself. A colour with no
        # matching word would be a panel that says broken and not what.
        named = {channel for _, states in build.HEALTH_STATES for _, channel in states}
        assert set(build.ENGINE_ERROR_CHANNELS) <= named


class TestHealthAvailable:
    """The check that stopped one wrong channel name costing the whole row.

    The failure it closes, seen on 2026-09-19: `engine_frame_msec` is in the
    help and not on the operator, `op(chop)['engine_frame_msec']` answered
    None, `None.eval()` raised, and the `text` parameter went into error. A
    Text COMP in error renders blank, and blank on a black container reads as
    empty panel - so the surface that exists to report a dead player was
    silently saying nothing, and looked exactly like a healthy one.
    """

    def test_an_info_chop_with_everything_keeps_everything(self):
        info = FakeChannels(_engine_at_rest())
        states, readings, errors, missing = build._health_available(info)
        assert states == build.HEALTH_STATES
        assert readings == build.HEALTH_READINGS
        assert errors == build.ENGINE_ERROR_CHANNELS
        assert missing == ()

    def test_a_channel_the_operator_lacks_is_dropped_and_named(self):
        values = _engine_at_rest()
        del values["engine_fps"]
        _, readings, _, missing = build._health_available(FakeChannels(values))
        assert "engine_fps" not in [c for c, _, _ in readings]
        assert missing == ("engine_fps",)

    def test_the_rest_of_the_row_survives_one_missing_channel(self):
        # The whole point. Losing a number should cost that number, not the
        # state words and not the error colour.
        values = _engine_at_rest()
        del values["engine_fps"]
        states, readings, errors, _ = build._health_available(
            FakeChannels(values)
        )
        assert states == build.HEALTH_STATES
        assert errors == build.ENGINE_ERROR_CHANNELS
        assert len(readings) == len(build.HEALTH_READINGS) - 1

    def test_a_family_that_loses_one_flag_keeps_the_others(self):
        values = _engine_at_rest()
        del values["component_unloading"]
        states, _, _, missing = build._health_available(FakeChannels(values))
        families = dict(states)
        assert "component" in families
        assert "component_unloading" not in [c for _, c in families["component"]]
        assert missing == ("component_unloading",)

    def test_a_family_that_loses_every_flag_is_dropped_whole(self):
        values = _engine_at_rest()
        for _, channel in dict(build.HEALTH_STATES)["engine"]:
            del values[channel]
        states, _, _, _ = build._health_available(FakeChannels(values))
        assert "engine" not in dict(states)

    def test_what_survives_still_builds_an_expression_that_runs(self):
        # The check and the expression have to agree, or this has moved the
        # failure rather than fixed it.
        values = _engine_at_rest()
        del values["engine_fps"]
        info = FakeChannels(values)
        states, readings, _, _ = build._health_available(info)
        expression = build._health_expression("/project1/engineInfo", states, readings)
        result = eval(expression, {"op": lambda path: info})
        assert "fps" not in result
        assert result.startswith("engine ?  component ?")


class TestHealthBackground:
    """The row's colour, which is pulled rather than set on noticing."""

    PATH = "/project1/engineInfo"

    def _colour(self, values):
        return [
            eval(
                build._health_background_expression(
                    self.PATH, index, build.ENGINE_ERROR_CHANNELS
                ),
                {"op": lambda path: FakeChannels(values)},
            )
            for index in range(3)
        ]

    def test_a_healthy_engine_leaves_the_row_alone(self):
        assert self._colour(_engine_at_rest()) == list(build.HEALTH_OK_BG)

    def test_either_error_channel_reddens_the_row(self):
        for channel in build.ENGINE_ERROR_CHANNELS:
            values = _engine_at_rest()
            values[channel] = 1.0
            assert self._colour(values) == list(build.HEALTH_ERROR_BG), channel

    def test_a_cleared_error_takes_the_colour_back(self):
        # The failure an expression cannot have and a pushed colour can: a
        # panel left red over a player that a reload fixed.
        values = _engine_at_rest()
        values["component_error"] = 1.0
        assert self._colour(values) == list(build.HEALTH_ERROR_BG)
        values["component_error"] = 0.0
        assert self._colour(values) == list(build.HEALTH_OK_BG)

    def test_it_names_both_error_channels(self):
        for index in range(3):
            expression = build._health_background_expression(
                self.PATH, index, build.ENGINE_ERROR_CHANNELS
            )
            for channel in build.ENGINE_ERROR_CHANNELS:
                assert repr(channel) in expression, channel

    def test_there_is_one_colour_per_parameter_it_is_written_to(self):
        # Three expressions and three parameters, and the index into one is the
        # index into the other. A tuple shorter than the parameter list would
        # leave a component at whatever it was, which on a red row is a colour
        # nobody chose.
        assert len(build.HEALTH_BG_PARS) == len(build.HEALTH_OK_BG)
        assert len(build.HEALTH_BG_PARS) == len(build.HEALTH_ERROR_BG)

    def test_the_parameters_are_the_text_comps_own(self):
        # Literals from `bin/Lib/tdi/ops/comps/textCOMP.py`. A parameter name
        # that does not exist is reported by `set_par` but an expression set
        # through `getattr` would raise at build time instead, which is louder
        # and still worth pinning.
        assert build.HEALTH_BG_PARS == ("bgcolorr", "bgcolorg", "bgcolorb")


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


class FakeNetwork:
    """A container of named operators, and nothing else a lookup needs."""

    def __init__(self, path, children=None):
        self.path = path
        self.children = dict(children or {})

    def op(self, name):
        return self.children.get(name)


def _built_container(audio=True):
    """The engine's container as `build_player` leaves it.

    Named from the module's own constants rather than spelled again, because
    the point of these tests is which operator each output carries - not
    whether the mixer's nodes are called what this file says they are.
    """
    mixer = FakeNetwork(
        "/engineSource/generated/audio",
        {
            build.AUDIO_MIX_CHOP: FakeNetwork("/engineSource/generated/audio/mix"),
            "audioA": FakeNetwork("/engineSource/generated/audio/audioA"),
            "audioB": FakeNetwork("/engineSource/generated/audio/audioB"),
        },
    )
    children = {
        build.OUT_TOP: FakeNetwork("/engineSource/generated/out"),
        build.PLAYER_TOPS[0]: FakeNetwork("/engineSource/generated/playerA"),
        build.PLAYER_TOPS[1]: FakeNetwork("/engineSource/generated/playerB"),
        build.PLAYLIST_DAT: FakeNetwork("/engineSource/generated/playlist"),
        build.STATE_CHOP: FakeNetwork("/engineSource/generated/state"),
    }
    if audio:
        children[build.AUDIO_COMP] = mixer
    return FakeNetwork("/engineSource/generated", children)


class TestEngineSources:
    """Which operator inside the engine each output carries."""

    def test_the_program_pair_is_taken_after_the_blend(self):
        sources = build.engine_sources(_built_container())
        assert sources["program_video"].path.endswith("/out")
        assert sources["program_audio"].path.endswith("/audio/mix")

    def test_a_deck_is_taken_before_it(self):
        # Deck video is the player's own picture, so deck audio is the clip's
        # own stereo off the Audio Movie CHOP - no level, pan or fade share.
        # Taking the mixer's strip instead would hand the host a deck that
        # silences itself whenever the other one is on screen.
        sources = build.engine_sources(_built_container())
        assert sources["deck_a_video"].path.endswith("/playerA")
        assert sources["deck_b_video"].path.endswith("/playerB")
        assert sources["deck_a_audio"].path.endswith("/audio/audioA")
        assert sources["deck_b_audio"].path.endswith("/audio/audioB")

    def test_every_declared_output_has_something_to_carry(self):
        from tdpy import link

        sources = build.engine_sources(_built_container())
        assert [
            item.name for item in link.declared() if sources.get(item.name) is None
        ] == []

    def test_a_mixer_that_was_never_built_answers_none_rather_than_raising(self):
        # `engine.main` turns this into a LookupError naming the output, which
        # reaches the host as the Engine COMP's error. Raising here would name
        # the AttributeError instead.
        sources = build.engine_sources(_built_container(audio=False))
        assert sources["program_audio"] is None
        assert sources["deck_a_audio"] is None
        assert sources["program_video"] is not None


class TestStateExpressions:
    """What the engine computes, as against what it writes.

    Every channel on the state output is one or the other. A channel that were
    neither would sit at ABSENT for the life of the component and read, from
    the host, exactly like a player that never did anything.
    """

    def test_every_channel_is_either_computed_or_written(self):
        from tdpy import link

        assert set(build.state_expressions()) | set(link.PUSHED) == set(
            link.STATE_CHANNELS
        )

    def test_nothing_is_both(self):
        # An expression on a block that `publish_state` also writes would be
        # overwritten once and then never recomputed - a reading that stops.
        from tdpy import link

        assert set(build.state_expressions()).isdisjoint(link.PUSHED)

    def test_each_one_is_an_expression_python_accepts(self):
        for channel, expression in build.state_expressions().items():
            compile(expression, f"<{channel}>", "eval")

    def test_the_live_deck_is_read_off_the_fade_rather_than_remembered(self):
        # The same derivation `player.fade_target` makes, from the same two
        # numbers. A second way of answering "which deck is showing" is a
        # second thing that can be wrong about it.
        expressions = build.state_expressions()
        assert expressions["live"] == (
            "1 if op('fadeState')['target'] >= 0.5 else 0"
        )

    def test_fading_uses_the_tolerance_the_transport_uses(self):
        # Written from `player.FADE_SETTLED` rather than repeated here: a
        # tolerance spelled twice is two tolerances, and the host would call a
        # fade finished a fraction before or after the engine did.
        from tdpy import player

        assert repr(player.FADE_SETTLED) in build.state_expressions()["fading"]

    def test_the_cross_is_the_arithmetic_and_not_a_reading_of_the_top(self):
        # `cross.par.cross` is a frame stale, which is the open issue that
        # makes an interrupted fade jump. The channel carries the same
        # expression the Cross TOP and the mixer's gains are driven by.
        assert build.state_expressions()["cross"] == build.CROSS_EXPR

    def test_a_prefix_reaches_the_same_operators_from_one_level_out(self):
        # The mixer needed the fade's arithmetic from inside its own COMP, and
        # anything reading these channels from outside the container needs the
        # same. One template, so the two spellings cannot disagree.
        prefixed = build.state_expressions("generated/")
        assert "op('generated/fadeState')" in prefixed["live"]

    def test_each_deck_reads_its_own_player_and_info_chop(self):
        from tdpy import link

        expressions = build.state_expressions()
        for index, name in enumerate(build.PLAYER_TOPS):
            assert name in expressions[link.DECK_PLAYING[index]]
            assert build.PLAYER_INFO_CHOPS[index] in expressions[link.DECK_MISSES[index]]
            assert build.PLAYER_INFO_CHOPS[index] in expressions[link.DECK_BUFFER[index]]

    def test_the_decoder_readings_are_the_channels_the_baseline_was_read_from(self):
        # `pre_read_misses` is the one that answers what the 9.0 baseline
        # asked. Written as the literal the operator publishes, not as
        # whatever this project calls it on the panel.
        from tdpy import link

        expressions = build.state_expressions()
        assert "pre_read_misses" in expressions[link.DECK_MISSES[0]]
        assert "num_pre_read_frames" in expressions[link.DECK_BUFFER[0]]


class TestStateWatchChannels:
    def test_the_host_watches_what_its_surfaces_draw_from(self):
        assert build.state_watch_channels() == (
            "live", "seed", "row_a", "row_b", "playing_a", "playing_b"
        )

    def test_the_decoder_readings_are_not_watched(self):
        # They change constantly and are drawn by expressions, which need no
        # callback. A watcher on one would repaint the clip list every frame.
        from tdpy import link

        watched = set(build.state_watch_channels())
        assert watched.isdisjoint(link.DECK_MISSES + link.DECK_BUFFER)

    def test_every_watched_channel_is_published(self):
        from tdpy import link

        assert set(build.state_watch_channels()) <= set(link.STATE_CHANNELS)
