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

import random

from . import build, startup

#: The deck's seed, and the whole of this project's persistent runtime state.
#:
#: None means the playlist's own order, which is what a launch starts in - the
#: files play in the order they sit in `media/` until somebody presses shuffle.
#:
#: A seed rather than a shuffled list, for three reasons that all point the
#: same way. It is reproducible, so a sequence that did something interesting
#: can be replayed from the number in the log. It cannot fall out of step with
#: a playlist that was rescanned underneath it, the way a stored list of row
#: indices could. And it is one integer, which makes the question of where
#: runtime state lives small enough to answer honestly.
#:
#: It lives in this module, so it survives a rebuild of the network and dies
#: with the process - never reaching the .toe, which this project keeps
#: disposable. `startup.reload()` drops this module and takes the deck with
#: it, which is the one case worth knowing: the rebuild button resets the
#: order to the playlist's own.
SEED = None


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


def current_index(paths, current):
    """Which playlist row is loaded now, or None if none of them is.

    Deliberately not `step_index`'s answer for the same question. That one
    answers an end of the deck, because a transport button pressed with
    nothing loaded should still play something. Here the same case means
    nothing is playing, and answering 0 would tell the display to highlight
    the first clip - a lie a viewer has no way of catching.
    """
    if current in paths:
        return paths.index(current)
    return None


def deck(count, seed=None):
    """The playlist's rows in the order they will be played.

    Table order when `seed` is None, and a shuffle of it otherwise. Every row
    appears exactly once either way, which is the property that makes this a
    deck rather than a series of independent draws: a clip cannot repeat until
    every other clip has played.

    **The order is derived from a seed rather than stored as a list.** One
    integer regenerates it, which is what makes a run reproducible - the plan
    wanted seeding for exactly this reason, since a sequence that cannot be
    replayed cannot be debugged. It also means the thing that has to survive a
    rebuild is a number rather than a list that could fall out of step with
    the playlist it indexes.

    Caveat worth knowing: `random.Random(seed).shuffle` is stable for a given
    seed within a Python version, not across versions. Reproducing a sequence
    from a logged seed means the same TouchDesigner build, which for replaying
    a session is the case anyway.
    """
    rows = list(range(max(int(count), 0)))
    if seed is None:
        return rows
    random.Random(seed).shuffle(rows)
    return rows


def play_order(count):
    """`deck()` under whatever seed is currently set.

    The one function the display asks for the order, and the one the shuffle
    button changes the answer of. Everything else - the list, the transport,
    Phase 7's MIDI - goes through here rather than assuming the table's own
    order is the play order.
    """
    return deck(count, SEED)


def set_seed(seed):
    """Set the deck's seed. `None` restores the playlist's own order.

    The way back from a shuffle, and the way to replay one: a seed printed in
    the log can be typed at the textport to get that exact sequence again.

        import tdpy.player; tdpy.player.set_seed(419273)

    Redraws the list, because the order it shows has changed while the clip it
    is showing has not - see `shuffle` for why that redraw is a push where the
    highlight is a pull.
    """
    global SEED

    SEED = None if seed is None else int(seed)
    startup.report(
        f"[{startup.PACKAGE}] deck order: "
        + ("playlist order" if SEED is None else f"seed {SEED}")
    )
    _redraw()
    return SEED


def shuffle():
    """Deal a new deck, and say which one, so it can be dealt again.

    The seed is drawn rather than the order, and reported rather than kept
    quiet: an unrepeatable random sequence is the one kind that cannot be
    investigated when it does something interesting.

    **The clip playing now keeps playing.** Nothing here touches the player -
    a shuffle changes what comes *next*, not what is on screen, and it can be
    pressed mid-clip without a cut. That falls out of the transport reading
    its position from the player's own `file` every time rather than holding
    an index that a reshuffle would invalidate.
    """
    return set_seed(random.randrange(1, 1_000_000))


def step_index(order, index, step):
    """The playlist row `step` places from `index` in the deck, or None.

    Works in deck positions and answers in playlist rows, which is the whole
    of what the deck does to the transport: `next` means the next card, not
    the next table row, and those stopped being the same thing the moment
    shuffle existed.

    An `index` the deck does not contain answers an end of it - the first card
    going forwards, the last going backwards. Both cases that produce one want
    that: an empty `file` on a fresh build, and a clip that was in `media/` at
    the last scan and is not any more. Pressing previous with nothing loaded
    landing on the last clip is the same courtesy as next landing on the first.
    """
    order = list(order)
    if not order:
        return None
    if index is None or index not in order:
        return order[0] if step >= 0 else order[-1]
    return order[(order.index(index) + step) % len(order)]


def playlist_table():
    """The playlist DAT, or None - the display reads its rows for their text."""
    _, table = _ops()
    return table


def now_playing():
    """(playlist row being shown, number of clips), or (None, 0).

    The display's one question, answered in the one place that knows how to
    ask it. Read off the player's own `file` every time, so there is no stored
    index here either - see the module docstring.
    """
    player, table = _ops()
    if player is None:
        return None, 0
    paths = clip_paths(table)
    return current_index(paths, str(player.par.file.val)), len(paths)


def _step(step):
    """Move `step` places through the deck and play what is there.

    Both transport directions in one function, because next and previous
    differ by a sign and nothing else. Where the current position is kept is
    still nowhere: it is read back off the player's `file` parameter every
    time, so a rebuild, a reshuffle or a rescan cannot desynchronise a stored
    index from what is on screen.
    """
    player, table = _ops()
    if player is None:
        return None

    paths = clip_paths(table)
    if not paths:
        startup.report(f"[{startup.PACKAGE}] playlist is empty - nothing to play")
        return None

    order = play_order(len(paths))
    # .val rather than .eval(): the literal string the build wrote, which is
    # what the table holds. An evaluated File parameter can come back expanded
    # and would then match nothing.
    index = step_index(order, current_index(paths, str(player.par.file.val)), step)
    path = paths[index]

    startup.set_par(player, "file", path)
    startup.set_par(player, "play", True)
    # The position in the deck, not the row in the table - once shuffled, the
    # table row is not the number anyone watching the panel is looking at.
    startup.report(
        f"[{startup.PACKAGE}] clip {order.index(index) + 1}/{len(order)}: {path}"
    )
    return path


def next_clip():
    """Load the next card of the deck and play it."""
    return _step(1)


def previous_clip():
    """Load the previous card of the deck and play it."""
    return _step(-1)


def _redraw():
    """Ask the clip list to rebuild its rows, if there is one.

    The one place the display is *pushed* rather than deriving what it shows,
    and the distinction is worth being exact about. The **highlight** is
    pulled: it follows the player's `file`, which many things change, so
    nothing has to remember to redraw it. The **order** has exactly one thing
    that changes it - this module's seed - and nothing in TouchDesigner is
    watching a Python global, so that one caller says so explicitly.

    Imported here rather than at module scope because `lister` imports this
    module, and two module-scope imports of each other is a cycle.
    """
    from . import lister

    lister.reset()


#: What the panel's buttons are wired to. The keys are operator names, because
#: the callback DAT dispatches on `panelValue.owner.name` - so adding a button
#: in `build.py` and adding a function here is the whole of adding a control,
#: with no third place listing them both.
COMMANDS = {
    "play": play,
    "pause": pause,
    "previous": previous_clip,
    "next": next_clip,
    "shuffle": shuffle,
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
