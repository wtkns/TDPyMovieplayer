"""MIDI in: a controller as one more writer to the settings parameters.

Phase 7, and it is small for a reason decided three phases ago. Every setting
is already a custom parameter with TouchDesigner's binding doing the
synchronising, and every transport action is already a function looked up by
name in `player.COMMANDS`. So a knob writes the parameter the panel's slider is
bound to and the slider follows without being told, and a button calls the same
function the panel's button calls. Nothing here has to keep anything in step.

**The Device Mapper is deliberately not used.** TouchDesigner's usual route is
the MIDI Device Mapper dialog, whose User Maps live at `/local/midi/userdevices`
- inside the `.toe`. This project's rule is that nothing may require the `.toe`
to have been saved, so the map lives here instead, in a file that is version
controlled and can be read. The cost is that the mapping is written out by hand
rather than clicked together, which is what `LEARN` below is for.

Nothing in this module imports `td` at module scope, so the map and everything
derived from it is testable at a normal prompt.
"""

import collections

from . import player, settings, startup

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
#: All four are the **leftmost channel strip**. Send A (CC 14) is deliberately
#: absent: the settings it could still drive are the two toggles, and a knob
#: that has to be swept past halfway to flip a switch is a worse control than
#: no control. It is written down here so the next person to look does not
#: rediscover it as a gap.
#: Only the Note On is mapped. The device sends Note On 127 then Note Off 0 for
#: every press, and `is_press` refuses the release - but a Note Off row here
#: would be a second way to say the same thing, and the one that fires at the
#: wrong end if `is_press` were ever relaxed.
MAP = (
    Control(CONTROL_CHANGE, CHANNEL, 78, "setting", settings.DWELL),
    Control(CONTROL_CHANGE, CHANNEL, 50, "setting", settings.FADE),
    Control(CONTROL_CHANGE, CHANNEL, 30, "setting", settings.SPEED),
    Control(NOTE_ON, CHANNEL, 42, "command", "toggle"),
    Control(NOTE_ON, CHANNEL, 74, "command", "next"),
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
LIGHTS = (
    Light(42, "playing"),
    Light(74, "fading"),
)


def light_states():
    """What each named state currently is, as a dict of name to bool.

    The one place the lamps ask the machine anything. Both answers are read
    rather than remembered - `player.playing()` is the transport parameter and
    `player.is_fading()` is the fade's two ends disagreeing - so a light cannot
    drift from what it reports, and a rebuild needs nothing restored.
    """
    return {
        "playing": player.playing(),
        "fading": player.is_fading(),
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


def target_value(setting, value, current=None):
    """What a MIDI value means for that setting.

    A float setting is the CC scaled across the range the setting declares, so
    the map does not carry a second copy of any number `settings.SETTINGS`
    already holds - change a slider's maximum there and the knob follows.

    A toggle is flipped rather than set, because the controller's button has no
    idea what the parameter currently holds. Given `current`, a press returns
    its opposite; given nothing, it returns True, which is the best a caller
    who could not read the parameter can do.
    """
    if setting.kind == "toggle":
        return True if current is None else not current
    span = setting.maximum - setting.minimum
    return setting.minimum + (value / FULL) * span


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
        return player.command(entry.target)

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

    parameter.val = target_value(specification, value, current=parameter.eval())
    return parameter.eval()
