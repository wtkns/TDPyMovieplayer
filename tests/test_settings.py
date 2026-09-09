"""Tests for the settings specification, as opposed to the COMP it builds.

`ensure()` is not here, for the same reason the `init_*` callbacks are not in
the lister's tests: it describes a network, and a test of it would be a test of
a stub of TouchDesigner. What is here is everything the specification decides -
the attributes each kind of setting is given, the two partitions the surface is
drawn from, and the defaults, which are a decision rather than a detail.

The defaults are tested because they are an argument. Every automatic or
stochastic behaviour in this player is off when it launches: the deck is the
playlist's order, clips start at their beginning, speed is 1, and a dwell of 0
means no timer at all. Each of those is switched on deliberately, and a change
to any of them should have to walk past a failing test that says so.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tdpy import settings, startup  # noqa: E402


@pytest.fixture
def silent(monkeypatch):
    """Collect reported lines instead of writing them to the log."""
    lines = []
    monkeypatch.setattr(startup, "report", lines.append)
    return lines


class TestSpecification:
    def test_every_setting_is_findable_by_the_name_the_project_uses(self, silent):
        named = (
            settings.ADVANCE_ON_END,
            settings.RANDOM_CUE,
            settings.DWELL,
            settings.SPEED,
        )
        assert [settings.spec(name).name for name in named] == list(named)
        assert silent == []

    def test_an_unknown_setting_is_reported_with_the_real_ones(self, silent):
        assert settings.spec("Dwelltime") is None
        assert any("no setting 'Dwelltime'" in line for line in silent)
        assert any("Dwell" in line for line in silent)

    def test_the_two_partitions_cover_every_setting_exactly_once(self):
        # The surface draws from these two and nothing else, so a kind that
        # falls into neither would be a setting with no control on the panel.
        assert set(settings.toggles()) | set(settings.sliders()) == set(
            settings.SETTINGS
        )
        assert len(settings.toggles()) + len(settings.sliders()) == len(
            settings.SETTINGS
        )

    def test_names_are_legal_custom_parameter_names(self):
        # TouchDesigner requires a capital first letter on a custom parameter.
        # Getting this wrong fails inside appendFloat rather than here.
        for setting in settings.SETTINGS:
            assert setting.name[:1].isupper(), setting.name
            assert setting.name.isalnum(), setting.name

    def test_node_names_are_distinct_and_lowercase(self):
        # They are operator names in one container, so a collision would cost
        # a control - startup.create would hand back the other one's name.
        nodes = [setting.node for setting in settings.SETTINGS]
        assert nodes == [node.lower() for node in nodes]
        assert len(set(nodes)) == len(nodes)

    def test_every_range_holds_its_own_default(self):
        for setting in settings.sliders():
            assert setting.minimum < setting.maximum, setting.name
            assert setting.minimum <= setting.default <= setting.maximum, setting.name


class TestDefaults:
    def test_a_launch_runs_the_files_as_they_are(self):
        # No random cue point, and speed 1 - the plain reading of the folder.
        assert settings.spec(settings.RANDOM_CUE).default is False
        assert settings.spec(settings.SPEED).default == 1.0

    def test_a_dwell_of_zero_is_the_timer_switched_off(self):
        # Not a very fast cut: 0 is the bottom of the slider and it is a mode.
        # Phase 4c reads it that way, and this is where that is written down.
        assert settings.spec(settings.DWELL).default == 0.0
        assert settings.spec(settings.DWELL).minimum == 0.0

    def test_a_clip_that_ends_moves_on(self):
        # The one automatic behaviour that is on at launch, and it has to be:
        # with no timer and no button press, nothing else would ever advance.
        assert settings.spec(settings.ADVANCE_ON_END).default is True


class TestAttributes:
    def test_a_float_is_clamped_at_the_bottom_and_not_at_the_top(self):
        # The slider stops at the maximum; the parameter does not. A speed of 8
        # can be typed into the Parameter COMP, a speed of -1 cannot be reached
        # at all, and neither of those is an accident.
        attributes = settings.attributes(settings.spec(settings.SPEED))
        assert attributes["clampMin"] is True
        assert attributes["clampMax"] is False

    def test_a_float_carries_the_slider_range_that_makes_it_draw_as_one(self):
        attributes = settings.attributes(settings.spec(settings.DWELL))
        assert (attributes["normMin"], attributes["normMax"]) == (0.0, 60.0)
        assert (attributes["min"], attributes["max"]) == (0.0, 60.0)

    def test_a_toggle_is_given_a_default_and_nothing_else(self):
        # A range on a toggle is meaningless, and normMin on one is an
        # attribute error reported out of custom_par for no reason.
        assert settings.attributes(settings.spec(settings.RANDOM_CUE)) == {
            "default": False
        }

    def test_the_attributes_are_spelled_the_way_touchdesigner_spells_them(self):
        # custom_par passes these straight through to setattr, so a lowercase
        # `clampmin` here would be reported at build time and do nothing.
        for setting in settings.SETTINGS:
            for attribute in settings.attributes(setting):
                assert attribute in {
                    "default",
                    "min",
                    "max",
                    "clampMin",
                    "clampMax",
                    "normMin",
                    "normMax",
                }
