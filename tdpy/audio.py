"""The audio mixer: each player summed to mono, then panned into the output.

Two mixer strips and a sum. A clip's own stereo image is **discarded** - the
Audio Movie CHOP's two channels are averaged to one - and the resulting mono
point source is placed in the stereo field by its own pan control. That is what
a mixer strip does, and it is a different operation from tilting the balance of
a stereo pair, which would leave a clip's own left and right where the clip put
them.

**Nothing here stores a gain.** Each strip's two gains are parameter
expressions on the Math CHOPs that apply them, recomputed by TouchDesigner
every cook from the settings parameters and the fade - the same move the Cross
TOP makes with `build.CROSS_EXPR`, and for the same reason: a level that is
pushed has to be pushed from everywhere that could change it, and a level that
is pulled cannot be stale.

The gains are the product of three things:

    gain = level  x  pan-law term  x  the fade's share of this player

The third term is what makes the audio follow the picture. Player A is
multiplied by `1 - cross` and player B by `cross`, where `cross` is the same
expression driving the Cross TOP - not a reading of the Cross TOP's value,
which is a frame stale, but the arithmetic itself over the fade's two ends and
the fade timer. So the hidden player, which is already decoding the next clip
through the whole dwell, is silent until its fade begins.

Nothing in this module imports `td` at module scope, so the pan law and every
expression derived from it is testable at a normal prompt.
"""

from . import startup

#: The two sides of the output, in the order the Audio Device Out CHOP takes
#: them, and the channel name each carries. Audio channel names in
#: TouchDesigner are `chan1`, `chan2`, which is what the Audio Movie CHOP
#: produces and what the Rename CHOPs downstream of each gain put back.
LEFT = "chan1"
RIGHT = "chan2"
SIDES = (LEFT, RIGHT)


def pan_gains(pan):
    """The (left, right) gains for a pan of 0 to 1. Constant power.

    **The square-root law**: `left = sqrt(1 - p)`, `right = sqrt(p)`. The two
    gains square to 1 at every position, so a source keeps its perceived
    loudness as it is swept - a centred source sits at 0.707 on both sides,
    which is 3 dB down, rather than the 6 dB a linear law would cost it.

    The sinusoidal law (`cos`/`sin` of `p * pi/2`) is the other constant-power
    curve and differs from this one only slightly between the ends. This one is
    used because it is pure arithmetic: these gains are also written out as
    parameter expressions, and an expression that needs nothing imported is one
    less thing to be right about.

    Clamped rather than trusted. The pan parameters are clamped at both ends by
    `settings.attributes`, so this should never see a value outside 0 to 1 -
    but `(-0.1) ** 0.5` is a complex number in Python, and a complex number
    reaching a parameter is a worse failure than a pan that stops moving.
    """
    position = min(max(float(pan), 0.0), 1.0)
    return ((1.0 - position) ** 0.5, position ** 0.5)


def strip_gain(level, pan, share, side):
    """What one Math CHOP's gain should be, as a number.

    The reference implementation of the expression built below, and the thing
    the tests compare that expression's evaluated result against. Keeping the
    two in one file is deliberate: a gain expression that has drifted from the
    arithmetic it is supposed to encode is silent, and the only way to catch it
    is to run both.

    `share` is how much of this player is on screen - `1 - cross` for the
    player on the Cross TOP's first input, `cross` for the second.
    """
    left, right = pan_gains(pan)
    return float(level) * (left if side == LEFT else right) * float(share)


def parameter_expression(settings_path, name):
    """A parameter read, spelled for a TouchDesigner expression.

    `.eval()` rather than bare `op(...).par.X`, for the reason the diagnostics
    strip learned the hard way: TouchDesigner's objects are not the numbers
    they stand for, and the one that raises does so at cook time in a
    parameter, where it is easy to miss. `Par.eval()` is documented in
    `Par_Class.htm` as evaluating "the parameter's constant value, expression,
    export, or bind, dependent on its mode" - which is what a bound setting
    needs, since the panel's slider is bound to it.

    The path is absolute and baked in at build time, the way
    `build._diagnostics_expression` bakes its Info CHOP path. A relative path
    would have to count the levels between the mixer's own COMP and the
    settings COMP beside the build container, and that count is a thing that
    changes when a node is moved.
    """
    return f"op({settings_path!r}).par.{name}.eval()"


def gain_expression(settings_path, level_name, pan_name, share_expression, side):
    """The expression for one Math CHOP's `gain`. Returns the string.

    An ordinary Python expression, because that is what a parameter expression
    is. The three factors are written out in the order `strip_gain` multiplies
    them so the two can be read against each other.

    **Every operand is named inside the expression** rather than fetched by a
    function this calls. TouchDesigner works out what a parameter depends on
    from what its expression references, so a gain that called
    `tdpy.audio.something()` to read the same values would cook when it felt
    like it - which for a level means audio that lags a knob by an arbitrary
    number of frames.
    """
    level = parameter_expression(settings_path, level_name)
    pan = parameter_expression(settings_path, pan_name)
    if side == LEFT:
        law = f"(1 - {pan}) ** 0.5"
    else:
        law = f"({pan}) ** 0.5"
    return f"{level} * {law} * ({share_expression})"


def share_expressions(cross_expression):
    """How much of each player is audible, given the cross expression.

    Returned in `build.PLAYER_TOPS` order, and that order is load-bearing in
    exactly the way it is for the Cross TOP: index 0 is Input1, which is what a
    cross of 0 shows, so its share is `1 - cross`. Index 1 is Input2 and its
    share is the cross itself.

    Derived from the same expression the picture uses rather than from a second
    description of the fade, so there is no arrangement of the two in which the
    sound is doing something the image is not.
    """
    return (f"1 - ({cross_expression})", f"({cross_expression})")


def report_strip(name, side, expression):
    """One line naming a gain that was written, for the build log."""
    startup.report(
        f"[{startup.PACKAGE}] audio {name} {side}: {expression}"
    )
