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
