"""Transport - what the control panel's buttons actually do.

Separate from `build.py` on purpose. That module describes a network and runs
once; this one is called while the network is running, and is the file Phase 4
grows into: `advance()` belongs here, beside `next_clip()`, drawing from a
shuffled deck instead of walking the table in order.

Every function here is callable from the textport with no arguments:

    import tdpy.player; tdpy.player.next_clip()

which is the design rule the whole project is held to - advancing is a plain
function call, and the thing that triggers it is a shim. The panel's buttons
are one such shim today and a MIDI callback is another at Phase 7. Neither
knows anything the other does not.

Nothing is cached between calls. The operators are looked up by path every
time, because `build()` destroys and recreates them and a reference captured
at import would be pointing at a corpse after the first rebuild.
"""

from . import build, startup


def _ops():
    """The player TOP and the playlist DAT, or (None, None) with a log line.

    One lookup for both, since no caller wants one without the other and a
    missing container is the same failure either way - the build has not run,
    or it failed and `startup.build()` already said so.
    """
    import td

    parent = td.op(build.BUILD_PARENT) or td.op("/")
    container = parent.op(build.BUILD_ROOT)
    if container is None:
        startup.report(
            f"[{startup.PACKAGE}] no {build.BUILD_ROOT} under {parent.path}"
            " - has the build run?"
        )
        return None, None
    return container.op(build.PLAYER_TOP), container.op(build.PLAYLIST_DAT)


def play():
    """Resume the current clip.

    Silent on success. A button that logs a line every time it is pressed
    turns an append-only log into a click record, and the log is read for the
    launches, not for the presses.
    """
    player, _ = _ops()
    if player is None:
        return None
    return startup.set_par(player, "play", True)


def pause():
    """Hold the current clip on its current frame.

    Pause and play are two momentary buttons rather than one toggle, so
    neither reports the transport's actual state - `play` on the TOP is the
    only thing that knows, and reading it is what a state-showing toggle would
    do. Worth remembering when the panel appears to lie.
    """
    player, _ = _ops()
    if player is None:
        return None
    return startup.set_par(player, "play", False)


def clip_paths(table):
    """The playlist's `path` column, without its header, or [].

    By column name rather than position: `playlist.COLUMNS` decides the order
    and this should not have to agree with it separately. Row 0 is the header
    row `build._fill_playlist` writes, so it is dropped here.
    """
    if table is None:
        return []
    column = table.col("path")
    if not column:
        startup.report(f"[{startup.PACKAGE}] no 'path' column in {table.path}")
        return []
    return [cell.val for cell in column[1:]]


def next_index(paths, current):
    """Where in `paths` to go next, given what is loaded now.

    Ordinary Python over ordinary strings, so it is testable at a prompt like
    the rest of `playlist.py` - the reason it is not written inline below.

    A `current` that is not in the list answers 0, which covers both cases that
    produce one: an empty `file` parameter on a fresh build, and a clip that
    was in `media/` at the last scan and is not any more. Neither is an error,
    and both want the same thing - start at the top.
    """
    if not paths:
        return None
    if current not in paths:
        return 0
    return (paths.index(current) + 1) % len(paths)


def current_index(paths, current):
    """Which playlist row is loaded now, or None if none of them is.

    Deliberately not `next_index`'s answer for the same question. That one
    returns 0 for a `current` it cannot find, because starting at the top is
    the right thing to *play* next. Here the same case means nothing is
    playing, and answering 0 would tell the display to highlight the first
    clip - which is a lie a viewer has no way of catching.
    """
    if current in paths:
        return paths.index(current)
    return None


def play_order(count):
    """The playlist's rows, in the order they are going to be played.

    `range(count)` today, because `next_clip` walks the table top to bottom.
    Phase 4's shuffled deck replaces the body of this function and nothing
    else: the display asks for the order rather than reading the table in
    order, so a deck that is not the table's order arrives in the list without
    the list being touched.

    Takes a count rather than reaching for the table, which is what keeps it
    testable at a prompt like the rest of this module.
    """
    return list(range(max(int(count), 0)))


def playlist_table():
    """The playlist DAT, or None - the display reads its rows for their text."""
    _, table = _ops()
    return table


def now_playing():
    """(playlist row being shown, number of clips), or (None, 0).

    The display's one question, answered in the one place that knows how to
    ask it. Read off the player's own `file` every time, so there is no stored
    index here either - see the module docstring, and `next_clip` below.
    """
    player, table = _ops()
    if player is None:
        return None, 0
    paths = clip_paths(table)
    return current_index(paths, str(player.par.file.val)), len(paths)


def next_clip():
    """Load the following row of the playlist and play it.

    Sequential, and Phase 4 replaces that with a draw from a shuffled deck.
    What it does not replace is where the current position is kept, because
    nothing is kept: the answer is read back off the player's own `file`
    parameter every time. A rebuild therefore cannot desynchronise a stored
    index from what is on screen, since there is no stored index.
    """
    player, table = _ops()
    if player is None:
        return None

    paths = clip_paths(table)
    if not paths:
        startup.report(f"[{startup.PACKAGE}] playlist is empty - nothing to play")
        return None

    # .val rather than .eval(): the literal string the build wrote, which is
    # what the table holds. An evaluated File parameter can come back expanded
    # and would then match nothing.
    index = next_index(paths, str(player.par.file.val))
    path = paths[index]

    startup.set_par(player, "file", path)
    startup.set_par(player, "play", True)
    startup.report(f"[{startup.PACKAGE}] clip {index + 1}/{len(paths)}: {path}")
    return path


#: What the panel's buttons are wired to. The keys are operator names, because
#: the callback DAT dispatches on `panelValue.owner.name` - so adding a button
#: in `build.py` and adding a function here is the whole of adding a control,
#: with no third place listing them both.
COMMANDS = {
    "play": play,
    "pause": pause,
    "next": next_clip,
}


def command(name):
    """Run the transport command a button of that name stands for.

    Reports rather than raises on an unknown name. An exception here surfaces
    inconsistently - it is raised inside a Panel Execute callback, which is
    exactly the place `startup.report` exists to compensate for.
    """
    action = COMMANDS.get(name)
    if action is None:
        startup.report(
            f"[{startup.PACKAGE}] no transport command {name!r}"
            f" - have {', '.join(sorted(COMMANDS))}"
        )
        return None
    return action()
