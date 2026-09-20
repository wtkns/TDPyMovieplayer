"""The names the host and the engine share, in one place.

Phase 9 splits the player across two TouchDesigner processes: the host owns
the window, audio out, MIDI, the panel and the settings, and an Engine COMP
runs a generated `.tox` owning the playlist, both players, the fade and the
mixer. The only things that cross are custom parameters (host to engine) and
TOP, CHOP and DAT outputs (engine to host), per `Engine_COMP.htm`.

Every one of those is a name spelled on both sides of a process boundary, and
a misspelling there does not raise - a parameter the engine never declared is
simply absent, and a channel the host reads that the engine never wrote reads
as nothing. So both halves take their names from here.

**Commands cross as pulse parameters**, which is what spike 1 answered on
2026-09-14: a host `.pulse()` on the Engine COMP ran `onPulse` inside the
engine. The fallback that answer made unnecessary was a counter channel on a
CHOP input.

Nothing here imports `td`, so all of it is testable at a normal prompt.
"""

import collections
import re

from . import player, settings

#: A custom parameter name TouchDesigner accepts. `Custom_Parameters.htm`
#: says the first letter must be upper case or "creation will fail", and then
#: says two different things about the rest - "all parameter names contain no
#: underscores" in one section, "lowercase letters, numbers or underscores" in
#: another. The stricter reading is the one used: a name that satisfies it
#: satisfies both.
PARAMETER_NAME = re.compile(r"[A-Z][a-z0-9]*\Z")


def parameters():
    """Every parameter the `.tox` declares, in settings order.

    One per setting and named the same, so the host fills each with an
    expression over the setting of that name and nothing maps between two
    vocabularies. Derived from `settings.SETTINGS` rather than listed again: a
    setting added there is a parameter here, which is the point.
    """
    return tuple(setting.name for setting in settings.SETTINGS)


def valid_parameter(name):
    """Whether TouchDesigner will create a custom parameter of that name."""
    return bool(PARAMETER_NAME.match(name))


#: One transport command, and the pulse parameter that carries it across.
#: `name` is the key in `player.COMMANDS`, which is what the panel's buttons and
#: `midi.MAP` already spell; `parameter` is that name as a custom parameter.
Command = collections.namedtuple("Command", "name parameter")

#: The page the command pulses go on, named for what they are rather than for
#: the direction they travel.
COMMAND_PAGE = "Transport"


def command_parameter(name):
    """A command's pulse parameter name: `toggle_a` becomes `Togglea`.

    A rule rather than a table, for the reason `parameters()` derives itself
    from the settings: a command added to `player.COMMANDS` should need nothing
    added here. The underscore goes because `PARAMETER_NAME` refuses it, and the
    capital arrives because TouchDesigner requires one - so the two ends of the
    rule are the same two facts the regex above is built on.
    """
    return name.replace("_", "").capitalize()


def commands():
    """Every command that crosses, in `player.COMMANDS` order.

    Derived from that table rather than listed again, so the panel's buttons,
    the MIDI map and the engine's dispatch all key off one set of names. The
    host pulses `parameter` on the Engine COMP; the engine turns it back into
    `name` with `command_for` and hands it to `player.command`.
    """
    return tuple(Command(name, command_parameter(name)) for name in player.COMMANDS)


def command_for(parameter):
    """The command a pulse parameter stands for, or None if nothing does.

    None rather than a raise: this answers a parameter name that arrived from
    another process, and an unknown one is a thing to report rather than an
    exception inside a DAT callback.
    """
    for command in commands():
        if command.parameter == parameter:
            return command.name
    return None


#: One top-level output of the `.tox`. `name` is the Out operator's name inside
#: it, `family` is which of the three kinds the Engine COMP passes, and
#: `label` is the Out operator's `label` parameter.
#:
#: **The host does not find an output by its position.** The stub documents
#: the Out operators' `connectorder` as "Help Not Available", so the order
#: below is the order they are created in and nothing more. How the host tells
#: the Engine COMP's connectors apart is what `spikes/engine_spike.tap()`
#: reports, and `label` is here in case the answer is the connector's
#: description.
Output = collections.namedtuple("Output", "name family label")

#: The families `Engine_COMP.htm` says cross: "Only TOP, CHOP and DAT inputs
#: and outputs are supported."
FAMILIES = ("TOP", "CHOP", "DAT")

#: Program first, then each deck, then the two that describe the engine rather
#: than carry its signal. Decks are outputs as well as the program so the host
#: can route either one through processing of its own - the reason for the
#: split in the first place.
OUTPUTS = (
    Output("program_video", "TOP", "program video"),
    Output("program_audio", "CHOP", "program audio"),
    Output("deck_a_video", "TOP", "deck A video"),
    Output("deck_a_audio", "CHOP", "deck A audio"),
    Output("deck_b_video", "TOP", "deck B video"),
    Output("deck_b_audio", "CHOP", "deck B audio"),
    Output("state", "CHOP", "state"),
    Output("playlist", "DAT", "playlist"),
)


#: The deck outputs in `build.PLAYER_TOPS` order, so an index into one of these
#: is the same number that indexes the players, the Cross TOP's inputs and the
#: mixer's strips. Spelled out rather than built from the letters, for the
#: reason `player.COMMANDS` is: a name assembled in a loop cannot be grepped.
DECK_VIDEO = ("deck_a_video", "deck_b_video")
DECK_AUDIO = ("deck_a_audio", "deck_b_audio")

#: Every output the generated `.tox` carries: the program pair, both decks, and
#: since 9.5 the two that describe the player rather than carry its signal.
#:
#: An Out operator the engine has nothing to feed would be an output connector
#: answering an empty image, which is a worse thing for the host to find than
#: no connector at all - so a name arrives here when the engine has something to
#: put through it.
DECLARED = (
    "program_video",
    "program_audio",
    DECK_VIDEO[0],
    DECK_AUDIO[0],
    DECK_VIDEO[1],
    DECK_AUDIO[1],
    "state",
    "playlist",
)


def output(name):
    """The Output of that name. Raises KeyError, since a wrong name is a bug."""
    for item in OUTPUTS:
        if item.name == name:
            return item
    raise KeyError(f"no output {name!r} - have {', '.join(o.name for o in OUTPUTS)}")


def declared():
    """Every Output the `.tox` declares today, in DECLARED order.

    The host builds one Out operator per entry when it generates the component,
    one Null beside its own container to receive it, and wires the two together
    by label when the engine reports ready. One list drives all three, so an
    output added here arrives end to end.
    """
    return tuple(output(name) for name in DECLARED)


#: The state output's channels, one number each.
#:
#: This is what the host's clip list, MIDI lamps and diagnostics strip read
#: once the players are in another process, in place of the parameters they
#: watch today. Each is something the engine already derives rather than
#: stores - `live` is `player.live_index()`, `cross` the Cross TOP's value -
#: so the channel is a view, and the host still stores nothing.
#:
#: `misses_*` and `buffer_*` are each player's `pre_read_misses` and
#: `num_pre_read_frames`, which the diagnostics strip reads off an Info CHOP
#: the host will no longer be able to reach.
STATE_CHANNELS = (
    "live",
    "fading",
    "cross",
    "seed",
    "playing_a",
    "row_a",
    "misses_a",
    "buffer_a",
    "playing_b",
    "row_b",
    "misses_b",
    "buffer_b",
)

#: The per-deck channels, in `build.PLAYER_TOPS` order, like the deck outputs
#: above - so an index into any of these is the index into the players, the
#: Cross TOP's inputs and the mixer's strips. Written out rather than built from
#: the letters, for the reason `player.COMMANDS` is: a name assembled in a loop
#: cannot be grepped.
DECK_PLAYING = ("playing_a", "playing_b")
DECK_ROW = ("row_a", "row_b")
DECK_MISSES = ("misses_a", "misses_b")
DECK_BUFFER = ("buffer_a", "buffer_b")

#: The channels the host has to be *told* about rather than reading off an
#: operator, and so the ones a Constant CHOP block holds rather than computes.
#: `seed` is a Python global and `row_*` is a lookup over the playlist table;
#: everything else in STATE_CHANNELS is an expression over an operator that
#: already knows the answer. See `build._add_state`.
PUSHED = ("seed",) + DECK_ROW


def channel_index(name):
    """Which Constant CHOP block carries that channel. Raises on a wrong name.

    The engine writes the pushed channels by index and the host reads them all
    by name, so this is the one place the order in STATE_CHANNELS means
    anything. A wrong name is a bug rather than a runtime condition, hence the
    raise: nothing here is answering another process.
    """
    return STATE_CHANNELS.index(name)


#: A channel carries a number, and two of these values can be absent. The seed
#: is None when the deck is in playlist order, and a deck with no clip loaded
#: has no row. Both are non-negative when present - seeds are drawn from
#: 1 to 999999 by `player.shuffle`, rows index a table - so -1 is free to mean
#: absent. A seed that size survives the trip: `CHOP.htm` gives channel samples
#: as "32-bit floating point format", which holds every integer below 2**24
#: exactly.
ABSENT = -1


def to_channel(value):
    """A seed or row as a channel value: the number, or ABSENT for None."""
    return ABSENT if value is None else int(value)


def from_channel(value):
    """A channel value back to a seed or row: an int, or None for ABSENT.

    Rounded rather than truncated, because the value has been through a float
    and `int(418272.99999)` would be a different seed.
    """
    number = int(round(value))
    return None if number < 0 else number
