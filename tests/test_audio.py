"""Tests for the mixer's arithmetic and the expressions that carry it.

Two things are being held here, and they are different claims.

The first is the pan law itself: what a level, a pan and a fade position mean
as a gain. That is `strip_gain`, and it is checked against **numbers written
out longhand** rather than against the constants the module uses - a test that
asserted `pan_gains(0.5)[0] == pan_gains(0.5)[1]` would pass under any law at
all, including one that returned zero.

The second is that the generated expression computes the same thing. That is
the failure this project has already paid for twice: an expression is a string
until TouchDesigner cooks it, and a string that is subtly wrong looks exactly
like a string that is right. So the expressions are **evaluated** here, against
doubles that refuse what the real objects refuse - a Par that has to be
`.eval()`ed and a Channel that will do arithmetic but is not a number.
"""

import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tdpy import audio, build, settings  # noqa: E402


class FakeChannel:
    """A `td.Channel` as far as a cross expression is concerned.

    Arithmetic and nothing else. The real class is not a float - it is the
    object `op(chop)['name']` answers - and it took a broken diagnostics
    readout to establish that treating one as a number fails in some contexts
    and not others. It does do arithmetic, which is why `build.CROSS_EXPR`
    works without `.eval()`, so this does too; it is not convertible to a
    float, so a test that only passes because Python coerced it will not.
    """

    def __init__(self, value):
        self._value = float(value)

    def __add__(self, other):
        return self._value + _number(other)

    __radd__ = __add__

    def __sub__(self, other):
        return self._value - _number(other)

    def __rsub__(self, other):
        return _number(other) - self._value

    def __mul__(self, other):
        return self._value * _number(other)

    __rmul__ = __mul__


def _number(other):
    return other._value if isinstance(other, FakeChannel) else other


class FakePar:
    """A `td.Par` as far as a gain expression is concerned: `eval()`, no more.

    Deliberately not a number and deliberately not arithmetic. `Par_Class.htm`
    documents `eval()` as the way to get a parameter's working value - the one
    that accounts for a binding, which every one of these settings has - and an
    expression that read the Par itself would be writing a Par into a float
    parameter. This double is what makes that a failing test rather than a
    surprise at cook time.
    """

    def __init__(self, value):
        self._value = value

    def eval(self):
        return self._value


class FakeSettings:
    def __init__(self, values):
        self.par = type("Pars", (), {name: FakePar(value)
                                     for name, value in values.items()})()


class FakeChop:
    def __init__(self, channels):
        self._channels = channels

    def __getitem__(self, name):
        return FakeChannel(self._channels[name])


SETTINGS_PATH = "/project1/settings"
CONTAINER_PATH = "/project1/generated"


def evaluate(expression, values, start=0.0, target=0.0, fraction=0.0):
    """Evaluate a generated expression the way TouchDesigner would.

    `op` resolves the two paths the expressions actually name and nothing else,
    so a path this project got wrong is a KeyError here rather than a silent
    zero.
    """
    nodes = {
        SETTINGS_PATH: FakeSettings(values),
        f"{CONTAINER_PATH}/{build.FADE_STATE_CHOP}": FakeChop(
            {build.FADE_START_CHANNEL: start, build.FADE_TARGET_CHANNEL: target}
        ),
        f"{CONTAINER_PATH}/{build.FADE_TIMER_CHOP}": FakeChop(
            {build.FADE_FRACTION_CHANNEL: fraction}
        ),
    }
    return eval(expression, {"op": nodes.__getitem__})  # noqa: S307


def shares():
    return audio.share_expressions(
        build.CROSS_EXPR_TEMPLATE.format(prefix=f"{CONTAINER_PATH}/")
    )


class TestPanLaw:
    def test_hard_left_is_all_left_and_no_right(self):
        assert audio.pan_gains(0.0) == (1.0, 0.0)

    def test_hard_right_is_all_right_and_no_left(self):
        assert audio.pan_gains(1.0) == (0.0, 1.0)

    def test_centre_is_three_decibels_down_on_both_sides(self):
        # 0.7071..., written out rather than derived from the implementation.
        # The number is what a constant-power law means at the middle, and a
        # linear law would put 0.5 here - which is the mistake this catches.
        left, right = audio.pan_gains(0.5)
        assert left == pytest.approx(0.70710678, abs=1e-8)
        assert right == pytest.approx(0.70710678, abs=1e-8)

    def test_power_is_constant_across_the_whole_sweep(self):
        # The defining property: the two gains square to 1 everywhere. A law
        # that got the ends right and sagged in between passes every test
        # above and fails this one.
        for step in range(0, 21):
            left, right = audio.pan_gains(step / 20)
            assert left ** 2 + right ** 2 == pytest.approx(1.0, abs=1e-9)

    def test_it_is_monotonic_from_left_to_right(self):
        gains = [audio.pan_gains(step / 20) for step in range(0, 21)]
        assert [left for left, _ in gains] == sorted(
            (left for left, _ in gains), reverse=True
        )
        assert [right for _, right in gains] == sorted(right for _, right in gains)

    def test_a_pan_outside_the_range_is_clamped_rather_than_complex(self):
        # `(-0.1) ** 0.5` is a complex number in Python, and one of those
        # reaching a float parameter is a stranger failure than a pan that
        # stops moving. The parameters are clamped too; this is the guard that
        # does not depend on that being true.
        assert audio.pan_gains(-1.0) == (1.0, 0.0)
        assert audio.pan_gains(2.0) == (0.0, 1.0)
        for gain in audio.pan_gains(-1.0) + audio.pan_gains(2.0):
            assert isinstance(gain, float)

    def test_it_is_not_the_linear_law(self):
        # A control. Linear would answer 0.25 and 0.75 here; the square-root
        # law answers 0.5 and 0.866. Written as literals so this fails if the
        # law is ever swapped without the swap being intended.
        left, right = audio.pan_gains(0.75)
        assert left == pytest.approx(0.5, abs=1e-8)
        assert right == pytest.approx(0.8660254, abs=1e-7)


class TestStripGain:
    def test_a_silent_player_contributes_nothing_wherever_it_is_panned(self):
        for pan in (0.0, 0.5, 1.0):
            assert audio.strip_gain(0.0, pan, 1.0, audio.LEFT) == 0.0
            assert audio.strip_gain(0.0, pan, 1.0, audio.RIGHT) == 0.0

    def test_a_player_the_fade_has_left_contributes_nothing(self):
        # The whole of what makes the sound follow the picture: share 0 is a
        # player that is not on screen, and it is silent however loud it is.
        assert audio.strip_gain(1.0, 0.5, 0.0, audio.LEFT) == 0.0
        assert audio.strip_gain(1.0, 0.5, 0.0, audio.RIGHT) == 0.0

    def test_full_level_hard_left_fully_faded_in_is_unity_on_the_left(self):
        assert audio.strip_gain(1.0, 0.0, 1.0, audio.LEFT) == 1.0
        assert audio.strip_gain(1.0, 0.0, 1.0, audio.RIGHT) == 0.0

    def test_level_scales_the_gain_proportionally(self):
        full = audio.strip_gain(1.0, 0.3, 1.0, audio.LEFT)
        assert audio.strip_gain(0.5, 0.3, 1.0, audio.LEFT) == pytest.approx(full / 2)

    def test_the_share_scales_the_gain_proportionally(self):
        full = audio.strip_gain(1.0, 0.3, 1.0, audio.RIGHT)
        assert audio.strip_gain(1.0, 0.3, 0.25, audio.RIGHT) == pytest.approx(
            full / 4
        )


class TestShareExpressions:
    def test_a_settled_cross_at_zero_is_all_of_the_first_player(self):
        first, second = shares()
        assert evaluate(first, {}, start=0.0, target=0.0) == 1.0
        assert evaluate(second, {}, start=0.0, target=0.0) == 0.0

    def test_a_settled_cross_at_one_is_all_of_the_second_player(self):
        first, second = shares()
        assert evaluate(first, {}, start=1.0, target=1.0) == 0.0
        assert evaluate(second, {}, start=1.0, target=1.0) == 1.0

    def test_the_two_shares_always_sum_to_one(self):
        # No moment in a fade where the mix is quieter or louder overall than
        # the two clips are individually.
        first, second = shares()
        for step in range(0, 11):
            fraction = step / 10
            total = evaluate(first, {}, 0.0, 1.0, fraction) + evaluate(
                second, {}, 0.0, 1.0, fraction
            )
            assert total == pytest.approx(1.0)

    def test_it_tracks_the_fade_timer_rather_than_jumping(self):
        first, second = shares()
        assert evaluate(second, {}, 0.0, 1.0, 0.25) == pytest.approx(0.25)
        assert evaluate(first, {}, 0.0, 1.0, 0.25) == pytest.approx(0.75)

    def test_it_reads_the_same_operators_the_picture_reads(self):
        # Not a second description of the fade. If these ever stop naming the
        # nodes `build.CROSS_EXPR` names, the sound and the image can disagree
        # and nothing else in the suite would notice.
        for expression in shares():
            assert build.FADE_STATE_CHOP in expression
            assert build.FADE_TIMER_CHOP in expression
            assert build.FADE_FRACTION_CHANNEL in expression


class TestGainExpression:
    def build_one(self, side, level_name=settings.LEVEL_A, pan_name=settings.PAN_A,
                  share="1"):
        return audio.gain_expression(
            SETTINGS_PATH, level_name, pan_name, share, side
        )

    def test_it_is_a_valid_python_expression(self):
        for side in audio.SIDES:
            compile(self.build_one(side), "<gain>", "eval")

    def test_it_evaluates_to_the_arithmetic_it_stands_for(self):
        # The claim the whole module rests on: the string and the function
        # agree. Swept rather than spot-checked, because the two could agree at
        # the ends and differ in the middle.
        for level in (0.0, 0.4, 1.0):
            for pan in (0.0, 0.25, 0.5, 0.75, 1.0):
                values = {settings.LEVEL_A: level, settings.PAN_A: pan}
                for side in audio.SIDES:
                    expression = self.build_one(side, share="0.6")
                    assert evaluate(expression, values) == pytest.approx(
                        audio.strip_gain(level, pan, 0.6, side)
                    )

    def test_a_hard_left_pan_puts_nothing_on_the_right_channel(self):
        # The literal the outside world sees - zero signal down one wire -
        # rather than a comparison against the module's own pan_gains.
        values = {settings.LEVEL_A: 1.0, settings.PAN_A: 0.0}
        assert evaluate(self.build_one(audio.RIGHT), values) == 0.0
        assert evaluate(self.build_one(audio.LEFT), values) == 1.0

    def test_a_hard_right_pan_puts_nothing_on_the_left_channel(self):
        values = {settings.LEVEL_A: 1.0, settings.PAN_A: 1.0}
        assert evaluate(self.build_one(audio.LEFT), values) == 0.0
        assert evaluate(self.build_one(audio.RIGHT), values) == 1.0

    def test_the_two_sides_are_not_the_same_expression(self):
        # A control. The two sides differ only in whether the pan is
        # subtracted from 1, which is one character of the generator, and
        # getting it wrong gives a mixer whose pan control does nothing
        # audible - both sides move together and the image stays centred.
        assert self.build_one(audio.LEFT) != self.build_one(audio.RIGHT)
        values = {settings.LEVEL_A: 1.0, settings.PAN_A: 0.2}
        assert evaluate(self.build_one(audio.LEFT), values) != evaluate(
            self.build_one(audio.RIGHT), values
        )

    def test_every_parameter_is_read_through_eval(self):
        # `FakePar` has no arithmetic at all, so an expression that used the
        # Par rather than its value raises TypeError here. That is the same
        # failure the diagnostics readout shipped with, arrived at from the
        # parameter side instead of the channel side.
        for side in audio.SIDES:
            assert ".eval()" in self.build_one(side)

    def test_it_does_not_work_against_a_parameter_that_is_not_evaluated(self):
        # The control for the test above: confirm FakePar really would refuse.
        broken = self.build_one(audio.LEFT).replace(".eval()", "")
        with pytest.raises(TypeError):
            evaluate(broken, {settings.LEVEL_A: 1.0, settings.PAN_A: 0.5})

    def test_it_names_both_settings_inside_the_expression(self):
        # TouchDesigner works out a parameter's dependencies from what its
        # expression references. A gain that called a helper to read these
        # would cook when it felt like it, which for a level means audio that
        # lags the knob by an arbitrary number of frames.
        expression = self.build_one(audio.LEFT)
        assert f".par.{settings.LEVEL_A}." in expression
        assert f".par.{settings.PAN_A}." in expression
        assert SETTINGS_PATH in expression

    def test_the_whole_chain_is_silent_for_the_hidden_player(self):
        # End to end: player B's gain with the cross settled at 0. This is the
        # case that matters most, because the hidden player is not idle - it is
        # decoding the next clip for the whole of a dwell, and before this
        # phase there was nothing at all keeping it quiet.
        first_share, second_share = shares()
        values = {settings.LEVEL_B: 1.0, settings.PAN_B: 0.5}
        for side in audio.SIDES:
            expression = audio.gain_expression(
                SETTINGS_PATH, settings.LEVEL_B, settings.PAN_B, second_share, side
            )
            assert evaluate(expression, values, start=0.0, target=0.0) == 0.0


class TestMixerSettings:
    def test_the_strips_are_in_player_order(self):
        assert len(settings.STRIPS) == len(build.PLAYER_TOPS)

    def test_every_strip_names_settings_that_exist(self, ):
        for level_name, pan_name in settings.STRIPS:
            assert settings.spec(level_name) is not None
            assert settings.spec(pan_name) is not None

    def test_a_level_runs_from_silence_to_unity_and_stops_there(self):
        for level_name, _ in settings.STRIPS:
            level = settings.spec(level_name)
            assert (level.minimum, level.maximum) == (0.0, 1.0)
            assert level.default == 1.0
            assert level.bounded is True

    def test_a_pan_runs_left_to_right_and_starts_centred(self):
        for _, pan_name in settings.STRIPS:
            pan = settings.spec(pan_name)
            assert (pan.minimum, pan.maximum) == (0.0, 1.0)
            assert pan.default == 0.5
            assert pan.bounded is True

    def test_the_mixer_settings_are_all_on_the_audio_page(self):
        named = {name for pair in settings.STRIPS for name in pair}
        assert {item.name for item in settings.on_page(settings.PAGE_AUDIO)} == named

    def test_a_default_launch_is_both_clips_full_and_centred(self):
        # The plain reading, matching the cycle's defaults: nothing placed,
        # nothing attenuated, and the fade is what decides which is audible.
        for level_name, pan_name in settings.STRIPS:
            level = settings.spec(level_name).default
            pan = settings.spec(pan_name).default
            left, right = audio.pan_gains(pan)
            assert left == pytest.approx(right)
            assert level * left == pytest.approx(math.sqrt(0.5))
