"""MIDI in: a controller as one more writer to the settings parameters.

Phase 7, and it is small for a reason decided three phases ago. Every setting
is already a custom parameter with TouchDesigner's binding doing the
synchronising, and every transport action is already a function looked up by
name in `player.COMMANDS`. So a knob writes the parameter the panel's slider is
bound to and the slider follows without being told, and a button asks for the
same command the panel's button asks for. Nothing here has to keep anything in
step.

**Phase 9.4 moved the transport into another process and changed one line.**
A button now goes through `engine.send`, which pulses that command's parameter
on the Engine COMP; a knob still writes the settings COMP, and the engine reads
it through an expression the host put on the same parameter. The controller did
not become an engine control, and this module did not learn anything about the
split beyond the name of the function it calls.

**The lamps are inert at 9.4** and nothing calls `refresh_lights`. They report
which deck is live and which is playing, both of which are facts in the other
process now; at 9.5 they come back off the state CHOP's channels.

**The Device Mapper is used once, to discover, and never to configure.**
Corrected 2026-09-12: this docstring used to say the dialog was not used at all
and that its output lived at `/local/midi/userdevices`. What it actually writes
is a five-column Table DAT at `/local/midi/device`, and a table is something
`build()` can author on every launch - see `DEVICE_TABLE` below. So the `.toe`
still carries nothing, and the dialog was needed exactly once, to find out what
the table is called.

What is genuinely not used is the dialog's *definition* column - the mapping
from controls to meanings. That lives in `MAP` below, in a file that is version
controlled and can be diffed, and `LEARN` is how its rows are found.

Nothing in this module imports `td` at module scope, so the map and everything
derived from it is testable at a normal prompt.
"""

import collections

from . import engine, link, player, settings, startup

#: The message strings TouchDesigner hands the callback. Spelled as it spells
#: them: the MIDI In DAT's Message filter documents "Control Change" and the
#: stock callback file's example row shows "Note On".
CONTROL_CHANGE = "Control Change"
NOTE_ON = "Note On"
NOTE_OFF = "Note Off"

#: Report every control the first time it is seen, with its message, channel
#: and index - which is the whole of what writing a MAP row needs.
#:
#: On rather than off, and it stays on: a first sighting is one line, so a full
#: pass over a Launch Control XL costs as many lines as it has controls and
#: then goes quiet. A controller that is behaving generates nothing. Turn it
#: off from the textport with `tdpy.midi.LEARN = False` if it is ever in the
#: way.
LEARN = True

#: What has been seen, keyed by `_key`. Values are `Seen`. Lives in this module
#: so `startup.reload()` clears it - a fresh learn pass is a click of rebuild.
SEEN = collections.OrderedDict()

Seen = collections.namedtuple("Seen", "count lowest highest")

#: One mapped control.
#:
#: `kind` is what the target is rather than what the hardware is: "setting"
#: writes the custom parameter of that name, "command" calls the function
#: `player.COMMANDS` has under it. A toggle setting is still "setting" - the
#: difference between a fader and a button is handled by `target_value`, which
#: reads the setting's own spec rather than being told again here.
Control = collections.namedtuple("Control", "message channel index kind target")

#: The MIDI channel this controller's left strip reports on. Nine, which is
#: not the 1 in the device table and not the "channel 1" the hardware is
#: labelled with - that one means the leftmost channel *strip*. Three
#: different numbers called channel, so the map is keyed on the one the
#: messages actually carry, learned rather than assumed.
CHANNEL = 9

#: The map, written from a learn pass rather than from a chart.
#:
#: Every index here was read off the log on 2026-09-12 with the controller in
#: front of the listener, and each was identified by hand: the device has eight
#: factory and eight user templates sending different CCs on each, so a map
#: taken from a chart would have been a guess that looked exactly like a
#: measurement.
#:
#: **Two channel strips now, one per player.** Column 1 drives player A and
#: column 2 drives player B, top to bottom: level, pan, speed, then the fader,
#: then the strip's two buttons. The two faders are the exception - `Dwell` and
#: `Fade` belong to the cycle rather than to either deck, and they are placed
#: one per column because that is where the faders are, not because column 2
#: owns the fade.
#:
#: Only the Note On is mapped. The device sends Note On 127 then Note Off 0 for
#: every press, and `is_press` refuses the release - but a Note Off row here
#: would be a second way to say the same thing, and the one that fires at the
#: wrong end if `is_press` were ever relaxed.
MAP = (
    # Column 1 - player A
    Control(CONTROL_CHANGE, CHANNEL, 14, "setting", settings.LEVEL_A),
    Control(CONTROL_CHANGE, CHANNEL, 30, "setting", settings.PAN_A),
    Control(CONTROL_CHANGE, CHANNEL, 50, "setting", settings.SPEED_A),
    Control(CONTROL_CHANGE, CHANNEL, 78, "setting", settings.DWELL),
    Control(NOTE_ON, CHANNEL, 42, "command", "toggle_a"),
    Control(NOTE_ON, CHANNEL, 74, "command", "next_a"),
    # Column 2 - player B
    Control(CONTROL_CHANGE, CHANNEL, 15, "setting", settings.LEVEL_B),
    Control(CONTROL_CHANGE, CHANNEL, 31, "setting", settings.PAN_B),
    Control(CONTROL_CHANGE, CHANNEL, 51, "setting", settings.SPEED_B),
    Control(CONTROL_CHANGE, CHANNEL, 79, "setting", settings.FADE),
    Control(NOTE_ON, CHANNEL, 43, "command", "toggle_b"),
    Control(NOTE_ON, CHANNEL, 75, "command", "next_b"),
)

#: The highest value a MIDI byte carries. Everything scaled out of a CC comes
#: through this, so it is named once rather than appearing as 127 in the middle
#: of arithmetic.
FULL = 127


#: The device mapping, which TouchDesigner keeps as an ordinary Table DAT.
#:
#: This is the part that had to be discovered rather than read. The MIDI In DAT
#: hears nothing without a mapping, and the documented way to make one is the
#: MIDI Device Mapper dialog - which writes into `/local`, inside the `.toe`,
#: the one file this project keeps disposable. But the thing the dialog writes
#: turns out to be a five-column Table DAT at `/local/midi/device`, and a table
#: is something `build()` can author on every launch like everything else.
#:
#: So the dialog is a one-time discovery step rather than a setup step: it was
#: used once, here, to find out what the table is called and what is in it.
#: Nothing has to click it again, on this machine or another.
DEVICE_TABLE = "/local/midi/device"

#: Columns, in the order the dialog wrote them. `outdevice` was empty while
#: this project only listened; it is the same device now that the buttons have
#: lights, since the lamps are written back down the same cable.
DEVICE_COLUMNS = ("id", "indevice", "outdevice", "definition", "channel")

#: The Device ID the MIDI In DAT asks for, as a string because a DAT cell is
#: text. "1" is what the dialog assigns first and what this project's DAT was
#: found on.
DEVICE_ID = "1"

#: The device as Windows names it. **The one machine-specific string here** -
#: another controller, or the same one seen under another name, means changing
#: this and nothing else. Read off `/local/midi/device` on 2026-09-12.
DEVICE_NAME = "Launch Control XL"

#: The mapping's channel column, which is not the channel the messages arrive
#: on - this device's controls report channel 9 while the table says 1. The
#: dispatch below reads the channel off each message, so nothing depends on
#: this being any particular number; it is written as the dialog wrote it.
DEVICE_CHANNEL = "1"


def device_row(existing=None):
    """The row `/local/midi/device` should hold for this controller.

    Takes the row that is already there, if any, so that a definition made by
    hand in the dialog is **preserved rather than overwritten**. This project
    needs no definition - the MIDI In DAT reports raw messages and `MAP` below
    does the mapping in Python, where it can be diffed - but a definition
    someone put there is a MIDI map they built, and a build that silently
    deleted it would be the same mistake as saving the `.toe`, pointed the
    other way.

    `existing` is a sequence of cell strings in `DEVICE_COLUMNS` order.
    """
    definition = ""
    if existing is not None and len(existing) > 3:
        definition = existing[3]
    return [DEVICE_ID, DEVICE_NAME, DEVICE_NAME, definition, DEVICE_CHANNEL]


def device_table_rows(existing_rows=None):
    """Every row the device table should hold, header included.

    Rows for other device IDs are kept: this project owns ID 1 and has no
    opinion about a second controller somebody attaches later.
    """
    rows = [list(DEVICE_COLUMNS)]
    ours = None
    others = []
    for row in existing_rows or ():
        cells = list(row)
        if not cells or cells[0] == DEVICE_COLUMNS[0]:
            continue  # the header, which is rebuilt rather than carried over
        if cells[0] == DEVICE_ID:
            ours = cells
        else:
            others.append(cells)
    rows.append(device_row(ours))
    rows.extend(others)
    return rows


#: One lamp: a button's LED and the thing it reports.
#:
#: `state` names a question in `LIGHT_STATES` rather than carrying a value, so
#: a lamp is a *view* of the machine in the same way the panel's sliders are
#: views of the settings parameters. Nothing stores whether a light is on.
Light = collections.namedtuple("Light", "index state")

#: Velocities for on and off.
#:
#: Full and zero rather than a colour. `midioutCHOP.sendNoteOn`'s help says the
#: valid range is "determined by the CHOP Note Normalize parameter", whose menu
#: tokens are in neither the help nor the type stubs - so a velocity in the
#: middle means one thing under one setting and another under the other, while
#: the two ends clamp to the same place either way. A specific colour needs
#: that menu resolved against the live parameter first.
LIGHT_ON = 127
LIGHT_OFF = 0

#: The lamps, by note index. Each index must also be a button in `MAP` - a
#: light on a button that sends nothing would be a lamp nobody can reach - and
#: a test holds the two tables to that rather than merging them, since a
#: button that sends without lighting is perfectly reasonable.
#:
#: **A lamp under the button it describes.** Each pause button lights while its
#: own deck is running, and each next button lights on the deck the cross is
#: settling on - so the surface answers the two questions a two-deck controller
#: otherwise cannot: is this deck moving, and is it the one on screen.
#:
#: The `fading` state that note 74 used to show is gone from the lamps, and
#: nothing is lost: a fade is exactly the interval when neither `live` light
#: is the whole truth, and watching the pair change is a better reading of it
#: than one light that says a fade is happening somewhere.
LIGHTS = (
    Light(42, "playing_a"),
    Light(43, "playing_b"),
    Light(74, "live_a"),
    Light(75, "live_b"),
)


def light_states():
    """What each named state currently is, as a dict of name to bool.

    The one place the lamps ask the machine anything. Every answer is read
    rather than remembered - `playing_*` is that deck's transport parameter and
    `live` is the fade state's target, both derived where the player is and
    published as channels - so a light cannot drift from what it reports, and a
    rebuild needs nothing restored.

    A channel the engine has not published yet reads as False, which leaves the
    lamp dark. That is the honest answer for a player that is not running: the
    alternative is a light saying a deck is live before there is a deck.
    """
    live = engine.state("live")
    return {
        "playing_a": bool(engine.state(link.DECK_PLAYING[0])),
        "playing_b": bool(engine.state(link.DECK_PLAYING[1])),
        "live_a": live is not None and round(live) == 0,
        "live_b": live is not None and round(live) == 1,
    }


def light_messages(states):
    """The (index, velocity) to send for every lamp, given the states.

    Pure, so the whole lamp policy is testable without a MIDI device. A lamp
    whose state is not in `states` is reported and skipped rather than guessed
    at, because a light stuck on is worse than a light that never comes on.
    """
    messages = []
    for lamp in LIGHTS:
        if lamp.state not in states:
            startup.report(
                f"[{startup.PACKAGE}] midi light {lamp.index} wants unknown"
                f" state {lamp.state!r} - have {', '.join(sorted(states))}"
            )
            continue
        messages.append(
            (lamp.index, LIGHT_ON if states[lamp.state] else LIGHT_OFF)
        )
    return messages


def refresh_lights():
    """Write every lamp from what the machine currently is. Returns what it sent.

    Named for `player.refresh_dwell` and `lister.refresh`, and doing their job:
    recomputing a derived state from its sources rather than being told what to
    set. Called from the Parameter Execute DAT watching the player's `play`,
    from both ends of a fade, and once from `build()` - because a launch is not
    a change and no watcher would otherwise fire.

    Sending unconditionally rather than only on a difference: the controller's
    lamps are not ours to remember. It may have been unplugged, switched
    template, or had its LEDs cleared by something else since the last write,
    and a cache of what we last sent would be a second source of truth about a
    device across a cable.
    """
    out = _out_chop()
    if out is None:
        return []

    sent = light_messages(light_states())
    for index, velocity in sent:
        out.sendNoteOn(CHANNEL, index, velocity)
    return sent


def _out_chop():
    """The MIDI Out CHOP, or None with a line saying so once it matters."""
    import td

    from . import build

    parent = td.op(build.BUILD_PARENT) or td.op("/")
    container = parent.op(build.BUILD_ROOT)
    if container is None:
        return None  # no build yet; nothing to light and nothing to say
    out = container.op(build.MIDI_OUT_CHOP)
    if out is None:
        startup.report(
            f"[{startup.PACKAGE}] no {build.MIDI_OUT_CHOP} in {container.path}"
            " - button lights will not work"
        )
    return out


def _key(message, channel, index):
    """What makes a control that control, and nothing about its value."""
    return (message, channel, index)


def note(message, channel, index, value):
    """Record a sighting, reporting the first one.

    Deliberately one line per *control* rather than per message. A fader sweep
    is a hundred messages and one control, and a learn mode that printed them
    all would bury the eight lines actually wanted in a thousand that repeat.

    The running low/high is kept because it is the other half of identifying a
    control by hand: a button reads 0 and 127 and nothing between, a fader
    fills the range, and an endless encoder does neither.
    """
    key = _key(message, channel, index)
    previous = SEEN.get(key)
    if previous is None:
        SEEN[key] = Seen(1, value, value)
        startup.report(
            f"[{startup.PACKAGE}] midi learn: {message} ch{channel}"
            f" index {index} (first value {value})"
        )
        return SEEN[key]
    SEEN[key] = Seen(
        previous.count + 1,
        min(previous.lowest, value),
        max(previous.highest, value),
    )
    return SEEN[key]


def learned():
    """Every control seen so far, as lines ready to be read off the log.

    Run from the textport after moving each control once:

        import tdpy.midi; tdpy.midi.learned()

    Returns the lines as well as reporting them, so a test can read them.
    """
    lines = [
        f"{message} ch{channel} index {index}:"
        f" {seen.count} messages, {seen.lowest}-{seen.highest}"
        for (message, channel, index), seen in SEEN.items()
    ]
    if not lines:
        startup.report(
            f"[{startup.PACKAGE}] midi: nothing heard yet"
            " - is the device connected, and is the MIDI In DAT active?"
        )
        return lines
    for line in lines:
        startup.report(f"[{startup.PACKAGE}] midi {line}")
    return lines


def control_for(message, channel, index):
    """The mapped control for a message, or None if nothing is mapped to it."""
    for entry in MAP:
        if _key(entry.message, entry.channel, entry.index) == _key(
            message, channel, index
        ):
            return entry
    return None


def is_press(message, value):
    """Whether this message is a button going down rather than coming up.

    A Note Off is never a press. A Note On of velocity 0 is one too - the MIDI
    spec lets a device end a note either way, and a controller that used the
    second form would otherwise fire every command twice, once on the way down
    and once on the way up.
    """
    if message == NOTE_OFF:
        return False
    return value > 0


def target_value(setting, value, current=None, exponent=1.0):
    """What a MIDI value means for that setting.

    A float setting is the CC scaled across the range the setting declares, so
    the map does not carry a second copy of any number `settings.SETTINGS`
    already holds - change a slider's maximum there and the knob follows.

    A toggle is flipped rather than set, because the controller's button has no
    idea what the parameter currently holds. Given `current`, a press returns
    its opposite; given nothing, it returns True, which is the best a caller
    who could not read the parameter can do.

    **`exponent` shapes where the control's travel goes**, by raising the
    fraction of the way along before it is mapped onto the range. 1 spreads the
    range evenly; above 1 crowds it at the bottom, which is a log taper by its
    usual name - the value is spaced logarithmically even though the arithmetic
    here is a power. A power rather than an actual logarithm because
    `log(0)` is undefined and 0 is a real position on the dwell: it is the
    timer switched off, and a curve that could not reach it would have taken a
    mode away to gain a taper.

    Pure, and takes the exponent rather than reading it. The setting that holds
    it is looked up by `apply_setting`, which is the function here that is
    allowed to touch the network - the same split the rest of this module is
    built on.

    Clamped at 0.01 rather than trusted. The parameter holding it is clamped at
    1, but an exponent of 0 would make every position answer the maximum
    (`0 ** 0` is 1 in Python), so a control that had somehow reached it would
    not look broken - it would look like a fader that had stopped moving while
    reading full.
    """
    if setting.kind == "toggle":
        return True if current is None else not current
    span = setting.maximum - setting.minimum
    position = (value / FULL) ** max(float(exponent), 0.01)
    return setting.minimum + position * span


def on_message(message, channel, index, value):
    """Dispatch one MIDI message. The callback in `build.py` calls only this.

    Reports rather than raises throughout, for the reason `player.command`
    does: this runs inside a DAT callback, where an exception surfaces
    inconsistently and is easy to lose entirely.
    """
    if LEARN:
        note(message, channel, index, value)

    entry = control_for(message, channel, index)
    if entry is None:
        return None

    if entry.kind == "command":
        # Only on the way down. Without this a button would fire its command
        # twice per press, which on `next` is a clip skipped.
        if not is_press(message, value):
            return None
        # `engine.send` rather than `player.command`: the transport is in the
        # engine's process since 9.4, and the names in `MAP` are the same names
        # either way - `link.commands` derives the parameters from the very
        # table `player.COMMANDS` keys this map against.
        return engine.send(entry.target)

    if entry.kind == "setting":
        return apply_setting(entry.target, message, value)

    startup.report(
        f"[{startup.PACKAGE}] midi: unknown control kind {entry.kind!r}"
        f" for {entry.target!r}"
    )
    return None


def apply_setting(name, message, value):
    """Write a MIDI value into the settings parameter of that name.

    The one function here that touches the network, and it is four lines
    because everything it decides was decided above, where it can be tested.
    It goes through `settings.comp()` and `settings.parameter()` rather than
    finding the COMP itself, so a rename of either is caught in one place.

    The parameter written is the **bind master**, which is the end that may be
    written: the panel's slider and its Parameter COMP are bind references and
    follow on their own. Writing the slider instead would be writing the bound
    end, and binding is two-way.
    """
    specification = settings.spec(name)
    if specification is None:
        return None  # settings.spec has already said which names exist

    # A toggle flips on the way down and ignores the release. Without this a
    # button that sends Note On and Note Off would flip twice per press and
    # appear to do nothing at all.
    if specification.kind == "toggle" and not is_press(message, value):
        return None

    parameter = settings.parameter(settings.comp(), name)
    if parameter is None:
        return None  # settings.parameter has already said why

    parameter.val = target_value(
        specification,
        value,
        current=parameter.eval(),
        exponent=curve_exponent(specification),
    )
    return parameter.eval()


def curve_exponent(setting):
    """The exponent shaping this setting's MIDI response. 1.0 if it has none.

    Reads the *other* setting named by `setting.curve`, which is what makes the
    taper something a knob can change rather than a constant compiled into this
    module. `settings.value` already falls back to a spec's default and says so
    in the log when the parameter cannot be read, so a missing Dwellcurve gives
    a cubed sweep and a line explaining why, rather than a silent linear one.

    1.0 for a setting with no curve, because raising a fraction to the first
    power is exactly the even sweep every other control wants - so there is no
    branch downstream and no second code path to keep correct.
    """
    if setting.curve is None:
        return 1.0
    exponent = settings.value(setting.curve)
    if exponent is None:
        # settings.value has already reported the unknown name. 1.0 is the
        # honest fallback: an even sweep is wrong but usable, and the log says
        # which setting was not found.
        return 1.0
    return exponent
