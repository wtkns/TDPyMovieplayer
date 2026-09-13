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
#:
#: `page` is which custom page the parameter goes on, and it is also how the
#: panel is divided into rows: a page is a band of controls. It exists because
#: the settings row shares its width between however many sliders there are,
#: so putting the mixer's four on the same row as the cycle's three would have
#: taken every slider down to about a third of its width.
#:
#: `curve` names **another setting** holding the exponent that shapes how a
#: MIDI control sweeps this one, or None for a control that sweeps evenly. It
#: is a name rather than a number for the reason everything here is: an
#: exponent somebody wants to change is a value with writers, and a value with
#: writers is a parameter. See `midi.target_value`.
Setting = collections.namedtuple(
    "Setting", "name node label kind default minimum maximum bounded page curve"
)

#: The custom pages the parameters go on. Named for what each configures rather
#: than "Settings", since the COMP is already called that.
PAGE_PLAYER = "Player"
PAGE_AUDIO = "Audio"
PAGE_TUNING = "Tuning"
PAGES = (PAGE_PLAYER, PAGE_AUDIO, PAGE_TUNING)

#: The pages the panel draws a row of big sliders for, in the order they stack.
#:
#: **Not every page is a row.** `Tuning` holds settings that shape how another
#: control behaves rather than what the player does - they are set once and
#: then left, so they belong in the Parameter COMP's typed fields, which show
#: every custom page, and not in a band of performance sliders where they would
#: take width from the controls that are actually being played.
PANEL_PAGES = (PAGE_PLAYER, PAGE_AUDIO)

#: Every setting, in the order each page draws them.
#:
#: **Every stochastic or automatic behaviour is off at launch.** The clips play
#: in the playlist's order, each from its start, at speed 1, held for as long as
#: it lasts - and shuffle, random cue and the dwell timer are each switched on
#: deliberately. That is the same choice `player.SEED = None` makes for the
#: deck: a launch is plain, and the interesting behaviour is asked for.
#:
#: **The dwell is a duration and nothing else.** It used to read 0 as the timer
#: switched off, which put a mode at the bottom of a rate control - so the
#: fastest cutting and no cutting at all were neighbouring positions on one
#: fader. `Dwellon` is the switch now and the dwell's range is 1/30s to a
#: minute, one frame of 30fps media being the shortest hold that can put a
#: different picture on screen.
#:
#: **Fade is a fraction of the dwell rather than a duration of its own**, which
#: is the same choice the cue point makes and for the same reason: it stays
#: correct when the thing it is measured against changes. A fade of 0.2 is a
#: fifth of the hold however long the hold is, so tuning the dwell does not
#: silently turn a gentle blend into most of the clip. 0 is a hard cut and 1 is
#: a player that is always mid-fade.
#:
#: So a hard cut is a fade of 0, and only that. Until the switch was split out
#: it was also what a dwell of 0 gave, which meant switching the cycle off
#: switched blending off with it - see `player.fade_seconds`.
#:
#: The mixer's four are all bounded, and both bounds mean something. A level of
#: 1 is full signal by the Audio Movie CHOP's own definition of `volume`, and
#: there is nothing above it to ask for that is not clipping; a pan runs from
#: hard left to hard right and 0.5 is the middle. Neither has the open top that
#: speed and dwell have, so neither is a slider whose end is a convenience.
#:
#: The levels default to 1 and the pans to centre - a plain launch, in the same
#: sense the cycle's defaults are plain: both clips full and centred, and the
#: placing is something asked for rather than arrived at.
SETTINGS = (
    Setting(
        "Advanceonend", "advanceonend", "advance at end", "toggle", True,
        None, None, False, PAGE_PLAYER, None,
    ),
    Setting(
        "Randomcue", "randomcue", "random cue", "toggle", False,
        None, None, False, PAGE_PLAYER, None,
    ),
    Setting(
        "Dwellon", "dwellon", "auto cut", "toggle", False,
        None, None, False, PAGE_PLAYER, None,
    ),
    Setting(
        "Dwell", "dwell", "dwell", "float", 4.0, 1.0 / 30.0, 60.0, True,
        PAGE_PLAYER, "Dwellcurve",
    ),
    Setting("Fade", "fade", "fade", "float", 0.0, 0.0, 1.0, True, PAGE_PLAYER, None),
    Setting(
        "Speeda", "speeda", "speed A", "float", 1.0, -2.0, 4.0, False,
        PAGE_PLAYER, None,
    ),
    Setting(
        "Speedb", "speedb", "speed B", "float", 1.0, -2.0, 4.0, False,
        PAGE_PLAYER, None,
    ),
    Setting(
        "Levela", "levela", "level A", "float", 1.0, 0.0, 1.0, True,
        PAGE_AUDIO, None,
    ),
    Setting("Pana", "pana", "pan A", "float", 0.5, 0.0, 1.0, True, PAGE_AUDIO, None),
    Setting(
        "Levelb", "levelb", "level B", "float", 1.0, 0.0, 1.0, True,
        PAGE_AUDIO, None,
    ),
    Setting("Panb", "panb", "pan B", "float", 0.5, 0.0, 1.0, True, PAGE_AUDIO, None),
    Setting(
        "Dwellcurve", "dwellcurve", "dwell curve", "float", 3.0, 1.0, 4.0, True,
        PAGE_TUNING, None,
    ),
)

#: Names the rest of the project refers to, so a rename here is caught by the
#: interpreter rather than by a parameter that silently is not there.
ADVANCE_ON_END = "Advanceonend"
RANDOM_CUE = "Randomcue"
DWELL = "Dwell"
FADE = "Fade"

#: Whether the dwell timer counts at all.
#:
#: **A duration is not a switch.** Until 2026-09-13 a dwell of 0 meant the
#: timer off, so one parameter answered both "how long between cuts" and
#: "should there be cuts", and the two ends of one fader were a rate and a
#: mode. Splitting them is the same move the transport already makes in keeping
#: `play` separate from `speed`, and it is what let the dwell's bottom become a
#: real duration - one frame of 30fps media - instead of a place the timer
#: switches off.
#:
#: Off at launch, like every other automatic behaviour here.
DWELL_ON = "Dwellon"
SPEED_A = "Speeda"
SPEED_B = "Speedb"
LEVEL_A = "Levela"
PAN_A = "Pana"
LEVEL_B = "Levelb"
PAN_B = "Panb"

#: The exponent shaping how a MIDI control sweeps the dwell, and the one
#: setting that is about another setting rather than about the player.
#:
#: **Why the dwell needed one and nothing else does.** Dwell runs 0 to 60 and
#: the interesting end is the bottom: the difference between a half-second hold
#: and a two-second hold is the difference between a strobe and a rhythm, while
#: the difference between 35 and 40 seconds is nothing anybody can see. Swept
#: evenly, a 128-step fader spends two steps on the first second and forty on
#: the last twenty. Cubed, it spends about thirty on the first second.
#:
#: **An exponent rather than a menu of named curves.** 1 is exactly linear, 2
#: is gentle, 3 is the default, and everything between is reachable - so this
#: is the whole family of power curves in one float, which needs no new setting
#: kind and no list of formulas to keep in step with the code that applies
#: them. A knob on it sweeps the response of another knob.
DWELL_CURVE = "Dwellcurve"

#: The mixer's settings in `build.PLAYER_TOPS` order, as (level, pan) pairs.
#: One place says which strip belongs to which player, so `build._add_audio`
#: iterates rather than spelling four names out again in a different order.
STRIPS = ((LEVEL_A, PAN_A), (LEVEL_B, PAN_B))

#: Each player's speed, in the same order. Speed was one setting bound to both
#: players until 2026-09-13, on the argument that one master with two views
#: costs nothing - which was true, and the reason splitting it costs nothing
#: either: the binding does the same work twice instead of once.
#:
#: **The range is asymmetric on purpose.** -2 to 4 is what puts 1 - normal
#: speed - exactly at the middle of the range, and therefore at the centre of a
#: MIDI knob's travel. A symmetric -2 to 2 would put 0 there, which is a frozen
#: frame at the detent. The Movie File In TOP's help says negative values play
#: the movie backwards, and that this works only in Sequential play mode, which
#: is the mode `build.PLAY_MODE` sets.
SPEEDS = (SPEED_A, SPEED_B)


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


def on_page(page=None):
    """Every setting on that page, in order. All of them when page is None.

    The panel draws one row per page, so this is what a row is. `None` rather
    than a default page, because a caller asking about the whole specification
    - the Parameter COMP, and the tests that check the named constants cover it
    - is asking a different question from one drawing a row.
    """
    if page is None:
        return SETTINGS
    return tuple(item for item in SETTINGS if item.page == page)


def toggles(page=None):
    """The settings drawn as buttons."""
    return tuple(item for item in on_page(page) if item.kind == "toggle")


def sliders(page=None):
    """The settings drawn as sliders - the ones with a range to slide over."""
    return tuple(item for item in on_page(page) if item.kind == "float")


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
            setting.page,
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
