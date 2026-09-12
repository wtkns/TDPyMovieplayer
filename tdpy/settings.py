"""The player's settings, as custom parameters on a COMP of their own.

Five values decide how the cycle behaves: what happens when a file ends, where
a clip starts when it changes, how long a clip is held, how much of that hold
is spent crossfading into the next one, and how fast it runs.
Each of them has **several writers** - a slider, a typed field, and a MIDI CC
at Phase 7 - and that is what makes them different from the deck's seed, which
has exactly one writer and is an action rather than a value. A seed can be a
Python global. A value with three writers held as a Python global needs bespoke
plumbing per writer and nothing keeping them in step.

So they are custom parameters, and TouchDesigner's binding does the
synchronising: the parameter is the master, the slider and the Parameter COMP
bind to it, MIDI writes it, and the engine reads it. One value, many views, no
synchronisation code.

The COMP lives **beside** the build container, for the reason the windows do:
`build()` destroys and recreates its own container, and a rebuild while tuning
should not reset the dwell. `ensure()` is therefore a converge rather than a
create - it appends the parameters that are missing and leaves the values of
the ones already there exactly where they were put.

Nothing here imports `td` at module scope, so the specification and everything
derived from it is testable at a normal prompt.
"""

import collections

from . import build, startup

#: One setting. `node` is the name of the panel operator that drives it, kept
#: here rather than in `build.py` so a setting is one row in one table - adding
#: another means adding a line below and nothing else.
#:
#: `minimum` is always a hard limit - a negative dwell, fade or speed means
#: nothing - and `maximum` is where the slider stops, which is a different
#: claim. `bounded` is which of the two the top is: False leaves it open, so a
#: speed of 8 can be typed into the Parameter COMP even though the slider only
#: reaches 4, and True makes it a real ceiling.
#:
#: Only a setting whose range *means* something is bounded. Fade is a fraction
#: of the dwell, so 1 is all of it and there is nothing above that to ask for;
#: speed and dwell have no natural top and their sliders are a convenience.
Setting = collections.namedtuple(
    "Setting", "name node label kind default minimum maximum bounded"
)

#: The custom page the parameters go on. One page, named for what it configures
#: rather than "Settings", since the COMP is already called that.
PAGE = "Player"

#: The five settings, in the order they are drawn.
#:
#: **Every stochastic or automatic behaviour is off at launch.** The clips play
#: in the playlist's order, each from its start, at speed 1, held for as long as
#: it lasts - and shuffle, random cue and the dwell timer are each switched on
#: deliberately. That is the same choice `player.SEED = None` makes for the
#: deck: a launch is plain, and the interesting behaviour is asked for.
#:
#: A dwell of 0 is not a very fast cut - it is the timer switched off, which is
#: what makes the bottom of the slider a real mode rather than an accident.
#:
#: **Fade is a fraction of the dwell rather than a duration of its own**, which
#: is the same choice the cue point makes and for the same reason: it stays
#: correct when the thing it is measured against changes. A fade of 0.2 is a
#: fifth of the hold however long the hold is, so tuning the dwell does not
#: silently turn a gentle blend into most of the clip. 0 is a hard cut and 1 is
#: a player that is always mid-fade.
#:
#: The consequence worth knowing is at the bottom of the dwell: with Dwell at 0
#: the fade is 0 seconds too, so every cut is hard - including a next press and
#: an end-of-file advance. That follows from what the parameter says it is, and
#: it keeps the bottom of the dwell slider one clear mode rather than two.
SETTINGS = (
    Setting(
        "Advanceonend", "advanceonend", "advance at end", "toggle", True,
        None, None, False,
    ),
    Setting(
        "Randomcue", "randomcue", "random cue", "toggle", False,
        None, None, False,
    ),
    Setting("Dwell", "dwell", "dwell", "float", 0.0, 0.0, 60.0, False),
    Setting("Fade", "fade", "fade", "float", 0.0, 0.0, 1.0, True),
    Setting("Speed", "speed", "speed", "float", 1.0, 0.0, 4.0, False),
)

#: Names the rest of the project refers to, so a rename here is caught by the
#: interpreter rather than by a parameter that silently is not there.
ADVANCE_ON_END = "Advanceonend"
RANDOM_CUE = "Randomcue"
DWELL = "Dwell"
FADE = "Fade"
SPEED = "Speed"


def spec(name):
    """The Setting of that name, or None with a line saying which exist."""
    for setting in SETTINGS:
        if setting.name == name:
            return setting
    startup.report(
        f"[{startup.PACKAGE}] no setting {name!r}"
        f" - have {', '.join(item.name for item in SETTINGS)}"
    )
    return None


def toggles():
    """The settings drawn as buttons."""
    return tuple(item for item in SETTINGS if item.kind == "toggle")


def sliders():
    """The settings drawn as sliders - the ones with a range to slide over."""
    return tuple(item for item in SETTINGS if item.kind == "float")


def attributes(setting):
    """The Par members `startup.custom_par` should apply for this setting.

    Spelled as TouchDesigner spells them, because that is what `custom_par`
    passes through - there is no second vocabulary to keep in step with the
    first.

    `clampMin` is always on and `clampMax` follows the setting's `bounded`, for
    the reason in the Setting docstring: the bottom of every range is a real
    limit, and whether the top is one depends on what the number means. A fade
    is a fraction and 1 is all of it; a speed of 8 is a thing somebody might
    reasonably type into a slider that only draws as far as 4.

    `normMin`/`normMax` are what make the parameter draw as a slider in a
    Parameter COMP at all, which is half of what the surface is.
    """
    if setting.kind != "float":
        return {"default": setting.default}
    return {
        "default": setting.default,
        "min": setting.minimum,
        "max": setting.maximum,
        "clampMin": True,
        "clampMax": setting.bounded,
        "normMin": setting.minimum,
        "normMax": setting.maximum,
    }


def ensure(parent, td):
    """The settings COMP, converged onto rather than rebuilt. Returns it.

    Created beside the build container and never destroyed by `build()`, so the
    values survive a rebuild - which is the point of them being here rather
    than inside. A parameter that is missing is appended and seeded with its
    default; one that already exists keeps its value and takes any change to
    its label or range.
    """
    existing = parent.op(build.SETTINGS_COMP)
    comp = existing if existing is not None else startup.create(
        parent, td.baseCOMP, build.SETTINGS_COMP
    )
    comp.nodeX, comp.nodeY = -250, -450

    made = []
    for setting in SETTINGS:
        parameter, created = startup.custom_par(
            comp,
            PAGE,
            setting.kind,
            setting.name,
            label=setting.label,
            **attributes(setting),
        )
        if parameter is None:
            continue
        if created:
            # A parameter arrives holding zero, not its default - the default
            # is what a Reset would put back, and nothing has reset anything
            # yet. This is the one place a value is written from code.
            parameter.val = setting.default
            made.append(setting.name)

    startup.report(
        f"[{startup.PACKAGE}] settings at {comp.path}: "
        + (f"created {', '.join(made)}" if made else "all present, values kept")
    )
    return comp


def parameter(comp, name):
    """One setting's Par on the settings COMP, or None with a line about it.

    The lookup every caller that binds to a setting needs, in one place that
    says so when it fails. `getattr(comp.par, name, None)` at four call sites
    would be four chances to get the quiet version of this wrong.
    """
    if comp is None:
        startup.report(f"[{startup.PACKAGE}] no settings COMP - cannot bind {name}")
        return None
    found = getattr(comp.par, name, None)
    if found is None:
        startup.report(f"[{startup.PACKAGE}] no {name} on {comp.path}")
    return found


def comp():
    """The settings COMP as it stands now, or None.

    Looked up by path every time rather than cached, for the reason
    `player._ops()` does: a reference captured at import points at a corpse
    after the first rebuild.
    """
    import td

    parent = td.op(build.BUILD_PARENT) or td.op("/")
    return parent.op(build.SETTINGS_COMP)


def value(name):
    """The current value of a setting, or its default if it cannot be read.

    `eval()` rather than `.val`: a bound parameter's working value is what the
    caller wants, and the master here may well be driven by something else
    later. Falling back to the default is a fallback that **says so** - the
    engine should keep running with a sane number, and the log should carry the
    reason it is that number rather than the one on the panel.
    """
    setting = spec(name)
    if setting is None:
        return None
    found = parameter(comp(), name)
    if found is None:
        startup.report(
            f"[{startup.PACKAGE}] {name} unreadable - using {setting.default!r}"
        )
        return setting.default
    return found.eval()
