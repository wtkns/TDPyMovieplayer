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

**Commands are not here yet.** Whether a pulse parameter crosses an Engine COMP
is spike 1 on 160.0020; if it does not, commands become a counter channel on a
CHOP input instead, which is a different shape of entry. Adding them waits for
the answer rather than guessing it.

Nothing here imports `td`, so all of it is testable at a normal prompt.
"""

import collections
import re

from . import settings

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


def output(name):
    """The Output of that name. Raises KeyError, since a wrong name is a bug."""
    for item in OUTPUTS:
        if item.name == name:
            return item
    raise KeyError(f"no output {name!r} - have {', '.join(o.name for o in OUTPUTS)}")


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
