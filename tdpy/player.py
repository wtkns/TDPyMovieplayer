"""Transport - what the control panel's buttons actually do.

Separate from `build.py` on purpose. That module describes a network and runs
once; this one is called while the network is running.

**Since 9.4 it runs in the engine's process**, which is where the players are.
Every function here is still callable with no arguments, from the *engine's*
textport:

    import tdpy.player; tdpy.player.next_clip()

which is the design rule the whole project is held to - advancing is a plain
function call, and the thing that triggers it is a shim. The panel's buttons
and the MIDI map are two such shims, and both now reach this module from the
host by pulsing a parameter: see `tdpy.engine.send`. Neither knows anything the
other does not, and neither knows it crossed a process to get here.

From the host, the same commands are `tdpy.engine.send("next")`. Called there,
the functions below report that the player is elsewhere rather than answering
from an empty container - see `_container`.

**Phase 4c added two more shims and no new way of advancing.** The end-of-file
watcher calls `on_loop()` and the dwell timer calls `on_dwell()`, and both of
them read a setting and then call `next_clip()` or do nothing. There is
therefore no `advance()` distinct from `next_clip()`, which the plan had
expected: the deck already made the next clip a question with one answer, so a
second entry point would have been a second name for the same call.

`_step()` is the single funnel every clip change goes through, which is what
lets the cue policy and the dwell restart live in one place and be inherited
identically by all five triggers.

**Phase 6 added a second player and changed none of that.** There are now two
Movie File In TOPs behind a Cross TOP, and `_step()` loads the hidden one and
sends the cross at it rather than replacing the clip that is showing. The
shims above are untouched, because "advance" still means one function call -
what changed is which operator that call writes to, and that is answered by
`fade_target()` from the network rather than tracked here.

Nothing is cached between calls, and nothing about which player is live is
stored. The operators are looked up by path every time, because `build()`
destroys and recreates them and a reference captured at import would be
pointing at a corpse after the first rebuild - and the live player is read off
the fade state for the same reason the current clip is read off `file`: a
second record of a fact is a second thing that can be wrong about it.

The one remaining piece of runtime state in this project is still `SEED`.
"""

import random

from . import build, settings, startup

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


def _container():
    """The container holding the player, or None with a line saying why.

    Inside the engine that is `generated` under the component's top level, which
    `tdpy.engine.root()` names. In the host there is no player to find and this
    says so, rather than answering the host's own container - which exists,
    holds the playlist and MIDI, and would have every lookup below come back
    empty one operator at a time.

    Looked up by path every time rather than held, for the reason in the module
    docstring: the build destroys and recreates it.
    """
    from . import engine

    root = engine.root()
    if root is None:
        startup.report(
            f"[{startup.PACKAGE}] the player runs in the engine"
            " - from the host, call tdpy.engine.send(command)"
        )
        return None

    container = root.op(build.BUILD_ROOT)
    if container is None:
        startup.report(
            f"[{startup.PACKAGE}] no {build.BUILD_ROOT} under {root.path}"
            " - has the component built?"
        )
    return container


def _ops():
    """The player TOP on screen and the playlist DAT, or (None, None).

    One lookup for both, since no caller wants one without the other and a
    missing container is the same failure either way - the build has not run,
    or it failed and `startup.build()` already said so.

    **"The player" is now a question with an answer that changes**, and this is
    where it is asked. Phase 6 put two Movie File In TOPs behind a Cross TOP,
    and the one that matters is whichever the fade is heading towards - see
    `live_index`. Every caller that used to mean "the player" means that one,
    which is why they did not have to change.
    """
    container = _container()
    if container is None:
        return None, None
    return _live_player(container), container.op(build.PLAYLIST_DAT)


def _players(container):
    """Both Movie File In TOPs, in PLAYER_TOPS order, or [] with a line.

    Order is the Cross TOP's wiring: index 0 is Input1 and index 1 is Input2,
    so a position in this list and a cross value are the same number.
    """
    found = [container.op(name) for name in build.PLAYER_TOPS]
    if any(player is None for player in found):
        startup.report(
            f"[{startup.PACKAGE}] missing {', '.join(build.PLAYER_TOPS)} in"
            f" {container.path} - has the build run?"
        )
        return []
    return found


def _fade_state(container):
    """The Constant CHOP holding the fade's two ends, or None with a line."""
    state = container.op(build.FADE_STATE_CHOP)
    if state is None:
        startup.report(
            f"[{startup.PACKAGE}] no {build.FADE_STATE_CHOP} in"
            f" {container.path} - cuts cannot cross from one player to the other"
        )
    return state


def fade_target(state):
    """Which player the cross is settling on, as 0 or 1, from the fade state.

    **This is what "the current clip" means with two players**, and it is read
    off the network rather than remembered. The target is written once per cut
    and holds until the next one, so it answers the same thing during a fade
    and at rest - which is what makes the clip list highlight the incoming clip
    from the moment the fade starts rather than flipping halfway through it.

    Nothing here stores anything. That was the property Phase 4 was careful to
    keep - no index in Python that a rebuild or a reshuffle could desynchronise
    from what is on screen - and two players is exactly the change that would
    have broken it, had the answer been kept rather than derived.
    """
    if state is None:
        return 0
    return 1 if state.par.const1value.eval() >= 0.5 else 0


def _live_player(container):
    """The Movie File In TOP the cross is settling on, or None."""
    players = _players(container)
    if not players:
        return None
    return players[fade_target(_fade_state(container))]


def _hidden_player(container):
    """The other one - the player that is about to be loaded for the next cut."""
    players = _players(container)
    if not players:
        return None
    return players[1 - fade_target(_fade_state(container))]


def play():
    """Resume the current clip.

    Silent on success. A button that logs a line every time it is pressed
    turns an append-only log into a click record, and the log is read for the
    launches, not for the presses.

    **Both players**, because a hidden player that kept running while the
    visible one was paused would arrive at the next cut somewhere other than
    where it was cued - and the cue is the one thing about the incoming clip
    that was decided in advance. Pause holds the whole machine, not the frame
    that happens to be showing.
    """
    return _set_play(True)


def _set_play(running):
    """Write Play on both players. Returns them, or None if there are none.

    One function because play and pause differ by a bool and nothing else -
    the same reason next and previous are `_step` with a sign.
    """
    container = _container()
    if container is None:
        return None
    players = _players(container)
    if not players:
        return None
    for player in players:
        startup.set_par(player, "play", running)
    return players


def pause():
    """Hold the current clip on its current frame.

    Pause and play are two momentary buttons rather than one toggle, so
    neither reports the transport's actual state - `play` on the TOP is the
    only thing that knows, and reading it is what a state-showing toggle would
    do. Worth remembering when the panel appears to lie.

    **The dwell stops with it**, and not because this function stops it. Writing
    `play` is all this does; a Parameter Execute DAT watching that parameter
    calls `refresh_dwell()`, which is also what a hand on the parameter or a
    MIDI note writing it directly would trigger. Pausing from a fourth place
    later needs nothing added here.

    A fade already in flight is **not** held. It is driven by its own Timer CHOP
    and finishes, which is the honest behaviour: pausing mid-blend leaves a
    blend on screen, and a machine that froze halfway between two clips would
    be showing a frame that is not in either of them.
    """
    return _set_play(False)


def toggle():
    """Pause if running, resume if held. Returns the players, or None.

    For a controller with one button where the panel has two. The panel keeps
    `play` and `pause` as separate momentary buttons - two buttons that each
    do one thing cannot lie about the state, and neither shows it - but a MIDI
    button that only ever paused would be a control with no way back, which is
    what it was on its first evening.

    **Reads the state rather than remembering it.** `play` has five writers by
    now - both panel buttons, `_step()` on every clip change, a hand on the
    parameter, and this - so a Python bool tracking "are we paused" would be a
    sixth thing to keep in step with the one that actually knows. Asking the
    player costs a parameter read.
    """
    return _set_play(not playing())


def playing():
    """Whether the clip on screen is running. False if there is no player.

    The one place the transport's state is read, so the LED on a controller
    and anything else that wants it are asking the same question of the same
    parameter rather than each deriving their own answer.
    """
    player, _ = _ops()
    if player is None:
        return False
    return bool(player.par.play.eval())


def player_at(index):
    """One player by its index in `build.PLAYER_TOPS`, or None.

    The per-deck controls all need this and all need it to fail the same way -
    a controller button for a player that is not there should cost a line, not
    an exception inside a MIDI callback.
    """
    container = _container()
    if container is None:
        return None
    players = _players(container)
    if not 0 <= index < len(players):
        startup.report(
            f"[{startup.PACKAGE}] no player {index} - there are {len(players)}"
        )
        return None
    return players[index]


def playing_at(index):
    """Whether that player is running. False if it is not there."""
    player = player_at(index)
    if player is None:
        return False
    return bool(player.par.play.eval())


def toggle_at(index):
    """Pause or resume **one** player. Returns its new state, or None.

    The per-deck version of `toggle`, and the two are deliberately different
    things rather than one generalised over the other. `toggle` holds the whole
    machine; this holds one deck while the other keeps going.

    **What it does to the hidden deck is worth knowing before pressing it.**
    `_step` writes `play = True` on the incoming player at every cut, so a deck
    paused while it is hidden starts again the moment the crossfade reaches it.
    That is not a bug being tolerated: the incoming clip has just been cued and
    a cut that landed on a frozen frame would be a cut to nothing. The button
    is therefore a hold on the deck you can see, and a no-op with a delay on
    the one you cannot.
    """
    player = player_at(index)
    if player is None:
        return None
    running = not bool(player.par.play.eval())
    startup.set_par(player, "play", running)
    return running


def live_index():
    """Which player the cross is settling on, as an index. 0 if unknowable.

    The number `_step` derives `incoming` from, exposed because the
    controller's lamps want it: a light per deck saying which one is on screen
    is the fact a two-deck surface is missing otherwise. Derived from the fade
    state like everything else about the fade, so there is nothing to keep in
    step.
    """
    container = _container()
    if container is None:
        return 0
    state = _fade_state(container)
    if state is None:
        return 0
    return fade_target(state)


def is_live(index):
    """Whether that player is the one the cross is settling on."""
    return live_index() == index


def next_into(index):
    """Load the next clip of the deck into that player and cross to it.

    The per-deck Next. Pressing it for the player that is already live cuts
    that clip out from under itself rather than blending, which is the honest
    consequence of naming a destination instead of asking for a crossfade -
    see `_step`.
    """
    return _step(1, into=index)


#: How close the fade's two ends must be to count as settled. A blend is drawn
#: in 8 bits per channel, so a difference below this cannot be seen anyway.
FADE_SETTLED = 1.0 / 255


def is_fading():
    """Whether a crossfade is in flight.

    Derived, like everything else about the fade: the Constant CHOP holds the
    blend's two ends, and `on_fade_done` settles them to the same number when
    the fade finishes. So the two disagreeing *is* a fade in progress, and
    there is no flag to set, unset, or forget to unset on a rebuild.

    Compared with a tolerance rather than `!=` because both ends are floats
    that arrive by way of a Timer CHOP's fraction. An exact comparison would
    call a settled fade unsettled on whatever the last bit rounded to.
    """
    container = _container()
    if container is None:
        return False
    state = _fade_state(container)
    if state is None:
        return False
    start = state.par.const0value.eval()
    target = state.par.const1value.eval()
    return abs(target - start) > FADE_SETTLED


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


def cue_fraction(random_cue, draw=None):
    """Where a clip starts, as a fraction of its own length.

    0.0 - the head of the clip - unless random cue is on, in which case a
    fraction drawn across the whole of it. A **fraction** rather than a number
    of seconds, which is what makes this answerable without knowing the
    duration: the row whose length reads `--` because ffprobe could not open it
    cues exactly as correctly as the rest.

    **The draw is not constrained to the part of the clip that fits.** At speed
    *s* and dwell *T* a clip consumes *s* x *T* seconds, so a cue point late in a
    long clip will sometimes reach the end before the dwell expires - and that
    is what the advance-at-end setting is for. Clamping the draw instead would
    make the cue quietly depend on two other settings, and a random start that
    is only random over part of the clip is the kind of thing nobody notices
    being wrong.

    `draw` is an argument so the random branch can be tested without patching
    the module, and defaults to `random.random` - which answers [0.0, 1.0), so
    a clip is never cued exactly to its own last frame.
    """
    if not random_cue:
        return 0.0
    return float((draw or random.random)())


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

    It redrew the clip list until 9.4 - the one place in this project a display
    was pushed to rather than deriving what it shows, because a reshuffle moves
    every row while the player's `file` stays exactly where it was, and nothing
    in TouchDesigner watches a Python global. The list is in the host now and
    the seed is here, so what crosses is the number: `publish_state` writes it
    into the state output and the host derives the order from
    `deck(count, seed)`. The push is still a push, but it now ends at a channel
    rather than at a display, and what reads that channel is pulling.
    """
    global SEED

    SEED = None if seed is None else int(seed)
    startup.report(
        f"[{startup.PACKAGE}] deck order: "
        + ("playlist order" if SEED is None else f"seed {SEED}")
    )
    # The one push left, and the one that cannot be anything else: a seed is a
    # Python global, and nothing in a network - or on another machine - can
    # watch one. The host derives the whole order from this number and the
    # playlist's length, so a reshuffle crosses as one channel rather than as a
    # list of rows.
    publish_state()
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


#: `playlist_table()` and `now_playing()` stood here until 9.5. They were the
#: clip list's two questions, asked of this module from the same process; the
#: list is in the host now and asks them of the state output instead - the
#: table arrives as a DAT and the row as a channel `publish_state` writes.
#: Deleted rather than kept: a function nothing calls still reads as the way
#: the display works.


def _step(step, into=None):
    """Move `step` places through the deck and cross to what is there.

    `into` names which player receives the clip. The default - the hidden one -
    is the crossfade, and it is what every automatic trigger and every panel
    button asks for. Naming a player instead is what the controller's per-deck
    Next buttons do, and asking for the player that is **already live** is a
    legitimate thing to want: the clip is replaced under itself and the fade
    has nowhere to travel, so it is a hard cut rather than a blend. That falls
    out of `_begin_fade` writing a target equal to the settled value, which
    needs no branch here.

    Both transport directions in one function, because next and previous
    differ by a sign and nothing else. Where the current position is kept is
    still nowhere: it is read back off the live player's `file` parameter every
    time, so a rebuild, a reshuffle or a rescan cannot desynchronise a stored
    index from what is on screen.

    **The clip is loaded onto the hidden player and the cross is sent at it.**
    That is the whole of the two-player arrangement from here: this function
    never touches the player that is showing, so the outgoing clip keeps running
    through the blend instead of being replaced under it. Which player is hidden
    is derived from the fade state rather than alternated by a counter - a
    counter would be a second record of the same fact, free to disagree with the
    cross after an interrupted fade.

    The fade's start is read off the cross as it stands **now**, not assumed to
    be settled. Press next in the middle of a fade and the new one begins from
    whatever blend is on screen, rather than snapping to one player first.
    """
    container = _container()
    if container is None:
        return None
    players = _players(container)
    state = _fade_state(container)
    if not players or state is None:
        return None

    table = container.op(build.PLAYLIST_DAT)
    paths = clip_paths(table)
    if not paths:
        startup.report(f"[{startup.PACKAGE}] playlist is empty - nothing to play")
        return None

    live = fade_target(state)
    incoming = (1 - live) if into is None else int(into)
    if not 0 <= incoming < len(players):
        startup.report(
            f"[{startup.PACKAGE}] no player {into!r}"
            f" - there are {len(players)}"
        )
        return None

    order = play_order(len(paths))
    # .val rather than .eval(): the literal string the build wrote, which is
    # what the table holds. An evaluated File parameter can come back expanded
    # and would then match nothing.
    current = current_index(paths, str(players[live].par.file.val))
    index = step_index(order, current, step)
    path = paths[index]

    # Written unconditionally rather than skipped when the preload already
    # guessed right. A Movie File In TOP given the file it already has does not
    # reopen it, so the saving is TouchDesigner's to make - and a conditional
    # here would be this module holding an opinion about when a file counts as
    # already loaded, which is the operator's business and not its caller's.
    startup.set_par(players[incoming], "file", path)
    # Cued at the cut and not at the preload. Opening the file is the slow half
    # and that has already happened; cueing is a pulse. Cueing early would mean
    # a random start point that the clip had then been running past for a whole
    # dwell before anybody saw it.
    fraction = _cue(players[incoming])
    startup.set_par(players[incoming], "play", True)

    _begin_fade(container, state, incoming)

    # The clip changed, so the dwell is measured from here rather than from
    # whenever the last cut happened to be. Without this the two advance
    # triggers interfere: a clip that ended early would be followed by one held
    # for whatever was left of the dwell.
    restart_dwell()
    # The position in the deck, not the row in the table - once shuffled, the
    # table row is not the number anyone watching the panel is looking at.
    startup.report(
        f"[{startup.PACKAGE}] clip {order.index(index) + 1}/{len(order)}"
        f" at {fraction:.0%}: {path}"
    )
    return path


def fade_seconds(dwell, fade):
    """How long a crossfade lasts, from the dwell and the fade fraction.

    **Fade is a fraction of the dwell, so this is a product**, and that is the
    one reason the fade timer's length is computed here rather than bound to a
    parameter the way every other setting reaches its operator. A binding
    mirrors one value; this is two of them multiplied, and the answer only has
    to be right at the instant a fade begins.

    **A hard cut is now `Fade` at 0 and nothing else.** It used to also fall
    out of a dwell of 0, since 0 was the bottom of that range and the timer
    switched off - so turning the cycle off silently turned blending off with
    it, on a next press as much as on an automatic advance. Splitting the
    switch from the duration on 2026-09-13 ended that: the dwell's bottom is
    one frame, a fade of a fraction of one frame is a hard cut in practice
    anyway, and with the cycle switched off a next press now crossfades over
    whatever the dwell says rather than jumping. That is a behaviour change,
    and it is the better one - the fade length was never really about whether
    the timer was running.

    Negative inputs answer 0 rather than a negative length. `Dwell` and `Fade`
    are both clamped at the bottom on the settings COMP, so this is the belt to
    that braces - a Timer CHOP given a negative length is a failure with no
    obvious symptom.
    """
    return max(float(dwell) * float(fade), 0.0)


def _begin_fade(container, state, incoming):
    """Send the cross at `incoming`, over the fade the settings ask for.

    Two numbers and a pulse. `start` is where the cross is at this instant, so
    an interrupted fade continues from the picture rather than from the clip it
    was leaving; `target` is the player being faded to, and it doubles as the
    record of which player is live - see `fade_target`.

    A fade of zero seconds writes them both to the same number, which settles
    the cross immediately and needs no timer at all. That is not a special case
    so much as the general one with the ramp removed: `on_fade_done` does the
    same two things afterwards either way, so a hard cut and a slow blend leave
    the machine in the same state.
    """
    seconds = fade_seconds(
        settings.value(settings.DWELL), settings.value(settings.FADE)
    )
    startup.set_par(state, "const0value", _cross_value(container, incoming))
    startup.set_par(state, "const1value", float(incoming))

    # This is where the controller's lamps were refreshed until 9.4 - the one
    # place the fade's target changes, and so the one place the lights saying
    # which deck is live had to be asked to look again. The lamps are on the
    # host's cable and this runs in the engine, so the push is gone rather than
    # moved: at 9.5 the host watches the `live` channel on the state output,
    # which is this same number crossing as a reading rather than as a call.
    if seconds <= 0:
        on_fade_done()
        return 0.0

    timer = fade_timer()
    if timer is None:
        on_fade_done()
        return 0.0
    startup.set_par(timer, "length", seconds)
    build.pulse(timer, "start")
    return seconds


def _cross_value(container, fallback):
    """What the Cross TOP is showing right now, or `fallback` if it is missing.

    The fallback is the incoming player rather than 0, so a build with no cross
    in it still cuts - hard, and to the right clip, with a line in the log
    saying what is not there.
    """
    cross = container.op(build.CROSS_TOP)
    if cross is None:
        startup.report(
            f"[{startup.PACKAGE}] no {build.CROSS_TOP} in {container.path}"
            " - cutting rather than fading"
        )
        return float(fallback)
    return float(cross.par.cross.eval())


def fade_timer():
    """The Timer CHOP ramping the cross, or None with a line about it."""
    container = _container()
    if container is None:
        return None
    timer = container.op(build.FADE_TIMER_CHOP)
    if timer is None:
        startup.report(
            f"[{startup.PACKAGE}] no {build.FADE_TIMER_CHOP} in"
            f" {container.path} - cuts will be hard"
        )
    return timer


def on_fade_done():
    """A fade finished. Settle the cross, and load the clip after this one.

    Called by the fade timer's `onDone`, and directly by `_begin_fade` when the
    fade was zero seconds long - the same two jobs either way.

    **Settling is what makes the rest of the arithmetic hold.** With `start` and
    `target` equal, `build.CROSS_EXPR` answers that value whatever the timer's
    fraction is doing, so nothing downstream has to be right about what a
    finished Timer CHOP leaves in `timer_fraction`.

    **The preload is the point of the phase.** The player that just went out of
    sight is given the next clip immediately, so it has the whole of this clip's
    dwell to open and decode it. That margin is what removes the hitch at a cut;
    the blend only hides what is left.
    """
    container = _container()
    if container is None:
        return None
    state = _fade_state(container)
    if state is None:
        return None

    startup.set_par(state, "const0value", state.par.const1value.eval())
    return _preload(container)


def _preload(container):
    """Give the hidden player the clip that comes next. Returns its path.

    File only - not cued, not stopped. Opening the file is the slow half and the
    only half that needs a head start; the cue is a pulse `_step` fires at the
    cut, where it can still be random about a clip nobody has seen yet.

    Silent on success, like the transport buttons: this runs once per cut and a
    line each time would turn the log into a record of the cycle rather than of
    the launch.
    """
    players = _players(container)
    state = _fade_state(container)
    if not players or state is None:
        return None

    table = container.op(build.PLAYLIST_DAT)
    paths = clip_paths(table)
    if not paths:
        return None

    live = fade_target(state)
    order = play_order(len(paths))
    current = current_index(paths, str(players[live].par.file.val))
    index = step_index(order, current, 1)
    if index is None:
        return None

    startup.set_par(players[1 - live], "file", paths[index])
    return paths[index]


def _cue(player):
    """Put the clip's start point on the player and jump to it. Returns it.

    Here rather than in each caller, so next, previous, the dwell timer, the
    end-of-file watcher and Phase 7's MIDI all inherit one cue policy instead of
    each applying their own. `_step` is the single funnel every clip change goes
    through, which is what makes one place possible.

    The unit is set once at build time - `cuepointunit` is Fraction - so this
    writes a number between 0 and 1 and never touches a menu.

    **Worth checking on screen:** the pulse is fired in the same frame the
    `file` parameter is written, and a Movie File In TOP does not open the new
    file until it cooks. If the cue lands on the outgoing clip for a frame, or
    does not take at all, the fix is to defer the pulse one frame rather than to
    change what is cued.
    """
    fraction = cue_fraction(settings.value(settings.RANDOM_CUE))
    startup.set_par(player, "cuepoint", fraction)
    build.pulse(player, "cuepulse")
    return fraction


def next_clip():
    """Load the next card of the deck and play it."""
    return _step(1)


def previous_clip():
    """Load the previous card of the deck and play it."""
    return _step(-1)


def dwell_timer():
    """The Timer CHOP counting out the dwell, or None with a line about it.

    Inside the build container, unlike the settings COMP: the dwell *value* has
    to survive a rebuild and the dwell *clock* does not.
    """
    container = _container()
    if container is None:
        return None
    timer = container.op(build.DWELL_TIMER_CHOP)
    if timer is None:
        startup.report(
            f"[{startup.PACKAGE}] no {build.DWELL_TIMER_CHOP} in"
            f" {container.path} - nothing will advance on the dwell"
        )
    return timer


def restart_dwell():
    """Put the dwell clock back to zero. Called whenever the clip changes.

    `masterSeconds` is the Timer CHOP's own clock, documented as counting from
    0 from a Start and settable directly from Python - so this is the whole of a
    restart, with no Initialize-then-Start sequence to get the timing of.
    """
    timer = dwell_timer()
    if timer is None:
        return None
    timer.masterSeconds = 0
    return timer


def on_loop(info_name):
    """A clip reached its end and wrapped. Advance, or leave it looping.

    Called by the CHOP Execute DAT watching `loop_frame` on a player's Info
    CHOP. Extend Right is Cycle permanently on both players, so looping is what
    a clip does when it runs out and this decides only whether that is the end
    of it - both behaviours come from one network and one toggle.

    **Only the player on screen counts.** The hidden one is decoding the next
    clip a whole dwell before anybody sees it, and a preloaded clip shorter than
    the dwell will wrap several times while it waits - each wrap arriving here.
    Acting on those would advance the playlist at the speed of the shortest clip
    in it, which reads as a player that has lost its mind rather than as a bug
    in a watcher.

    The check is `info_name` against the live player's own Info CHOP, so it
    holds however the fade got where it is - and it is asked here rather than
    built into the watchers, because which player is live changes every cut and
    the watchers are built once.

    Worth knowing: with random cue on, a clip cued close to its own end reaches
    that end almost immediately, so advance-at-end can cut within a second of a
    cut. That is the overrun the cue deliberately does not clamp away, arriving
    where it was meant to.
    """
    if not looped_player_is_live(info_name):
        return None
    if not settings.value(settings.ADVANCE_ON_END):
        return None
    return next_clip()


def looped_player_is_live(info_name):
    """Whether that Info CHOP belongs to the player currently on screen.

    Separate from `on_loop` so the question can be asked without a network, and
    because it is the one place a watcher's identity is turned into a decision.
    An unknown name answers False and says so: a watcher wired to an operator
    this module has never heard of should not advance the playlist.
    """
    container = _container()
    if container is None:
        return False
    if info_name not in build.PLAYER_INFO_CHOPS:
        startup.report(
            f"[{startup.PACKAGE}] loop from unknown {info_name!r}"
            f" - have {', '.join(build.PLAYER_INFO_CHOPS)}"
        )
        return False
    return build.PLAYER_INFO_CHOPS.index(info_name) == fade_target(
        _fade_state(container)
    )


def on_dwell(cycle):
    """A dwell cycle began. Advance, unless this is the timer starting.

    Called by the Timer CHOP's `onCycleStart`, which passes the cycle index -
    documented in the install's own callbacks file, and as `outcycle`: "the
    number of cycles completed ... starting with 0 during the entire first
    cycle." So index 0 beginning is the timer being started, not a dwell that
    expired, and advancing on it would cut a clip the instant it was loaded.

    The guard is written against the index rather than against a flag this
    module sets, so it holds however the timer was started - by the build, by a
    clip change, or by a hand on the parameter.

    **The run condition is then asked again**, and it is the same question
    `refresh_dwell` asks. The timer's Play follows that answer through two
    watchers, and a watcher runs a frame after the parameter it watches moved -
    so a cycle can complete in the frame between a slider reaching 0, or a clip
    being paused, and the timer being told about it. Asking here as well is what
    keeps a paused clip from being cut away by a cycle already in flight.
    """
    if cycle < 1:
        return None

    player, _ = _ops()
    if player is None:
        return None
    if not dwell_should_run(
        settings.value(settings.DWELL_ON), player.par.play.eval()
    ):
        return None
    return next_clip()


def dwell_should_run(dwell_on, clip_playing):
    """Whether the dwell timer should be counting. Both inputs have to be true.

    **The switch is its own parameter now.** Until 2026-09-13 this read the
    dwell itself and treated 0 as off, so one fader carried a rate at one end
    and a mode at the other - and the mode sat next to the fastest cutting,
    where nudging the control off the bottom went from never cutting to cutting
    thirty times a second. `Dwellon` answers whether, `Dwell` answers how long,
    and the fader is a duration all the way down.

    **A paused clip is not counted down**: pause means hold this frame, and a
    player that cut away from a held frame after the dwell expired would make
    pause mean something narrower than it reads. Note this is the *machine*
    being paused - a single deck held with `toggle_at` does not stop the clock,
    because the other deck is still playing and the cut is still due.

    Both inputs are *interpretations* rather than views of a value, which is
    why neither can be a binding: a binding mirrors a number and has no opinion
    about what it means. This function is where the opinions are, and it is
    separate from the operator it drives so it can be read on its own.
    """
    return bool(dwell_on and clip_playing)


def refresh_dwell():
    """Recompute whether the dwell timer runs, from the two things that decide.

    Named for `lister.refresh()` and doing the same job: recomputing a derived
    state from its sources rather than being told what to set it to. Two
    Parameter Execute DATs call it - one on the settings COMP's Dwell, one on the
    player's own Play - and `build()` calls it once, because a launch is not a
    change and neither watcher would otherwise fire.

    **Nothing here restarts the clock.** That belongs to a clip change and
    `_step()` already does it, which leaves `masterSeconds` meaning exactly one
    thing: how long this clip has been playing, not counting time paused. Pause
    and resume therefore continue rather than start over, which is what pause
    means - and turning a dwell on mid-clip measures it from when the clip
    started rather than from when the slider moved, so a clip already past the
    dwell cuts at once instead of being granted a fresh interval.

    The line is logged only when the answer changes, so dragging the slider does
    not fill a log kept for launches with a record of the drag.
    """
    timer = dwell_timer()
    if timer is None:
        return None
    player, _ = _ops()
    if player is None:
        return None

    dwell = settings.value(settings.DWELL)
    running = dwell_should_run(
        settings.value(settings.DWELL_ON), player.par.play.eval()
    )
    was_running = bool(timer.par.play.eval())

    startup.set_par(timer, "play", running)
    if running != was_running:
        startup.report(
            f"[{startup.PACKAGE}] dwell timer "
            + (f"running, {dwell:g}s" if running else "off")
        )
    return timer


def publish_state():
    """Write the state channels nothing can compute. Returns what it wrote.

    Three of the twelve: the seed, which is a Python global that no network can
    watch, and each deck's playlist row, which is a lookup over the table rather
    than a value sitting on an operator. The other nine are expressions on the
    same Constant CHOP - see `build.state_expressions` - and this must never
    write one of those, which is why the channels come from `link.PUSHED`
    rather than from a list here.

    Recomputes all three from scratch every time, for the reason
    `refresh_dwell` does: it is called from two row watchers, from `set_seed`
    and once at the end of the build, and a function that set only the half its
    caller knew about would need each caller to know which half that was.

    A row that is not in the playlist writes ABSENT, which is what a deck with
    no clip loaded means and what the host draws as no highlight.
    """
    from . import link

    container = _container()
    if container is None:
        return None
    state = container.op(build.STATE_CHOP)
    if state is None:
        startup.report(
            f"[{startup.PACKAGE}] no {build.STATE_CHOP} in {container.path}"
            " - the host cannot see what the player is doing"
        )
        return None

    players = _players(container)
    paths = clip_paths(container.op(build.PLAYLIST_DAT))
    written = {"seed": link.to_channel(SEED)}
    for index, channel in enumerate(link.DECK_ROW):
        row = None
        if index < len(players):
            row = current_index(paths, str(players[index].par.file.val))
        written[channel] = link.to_channel(row)

    for channel, value in written.items():
        startup.set_par(
            state, f"const{link.channel_index(channel)}value", value
        )
    return written


#: What the panel's buttons are wired to. The keys are operator names, because
#: the callback DAT dispatches on `panelValue.owner.name` - so adding a button
#: in `build.py` and adding a function here is the whole of adding a control,
#: with no third place listing them both.
#:
#: **Not every command has a button.** `toggle` never did - the panel keeps
#: play and pause as two momentary buttons, since two buttons that each do one
#: thing cannot lie about the state - and the per-deck four below have none
#: either. They exist for the controller, which has a pair of buttons per
#: channel strip and no room for a machine-wide transport as well.
#:
#: Written out as four entries rather than generated in a loop over the two
#: players: a table whose keys are computed is a table that cannot be grepped,
#: and these keys are what `tdpy.midi.MAP` refers to.
COMMANDS = {
    "play": play,
    "pause": pause,
    "toggle": toggle,
    "previous": previous_clip,
    "next": next_clip,
    "shuffle": shuffle,
    "toggle_a": lambda: toggle_at(0),
    "toggle_b": lambda: toggle_at(1),
    "next_a": lambda: next_into(0),
    "next_b": lambda: next_into(1),
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
