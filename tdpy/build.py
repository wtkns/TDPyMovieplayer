"""The network this project builds.

This is the file to edit. It is the only module that reaches into TouchDesigner,
which keeps the rest of the package readable - and testable - outside it.

Phase 2 builds the playlist and one clip playing from it: a Table DAT holding
one row per video file in `media/`, a Movie File In TOP loading the first of
them, and a null TOP to hang the rest of the project off. One clip, no cycling -
the shuffled deck, the random cue point and the dwell timer are all Phase 4.

Parameter names here were looked up rather than guessed, with
`py -3.11 -m scaffold.params moviefileinTOP` in the framework repository, which
reads the help table TouchDesigner ships in its own `Config/`. Menu items are
set through `startup.set_menu`, which resolves them against the live parameter -
the help table lists menu items in prose and never gives their internal names.

Any import of `td` or of a third-party package belongs inside build(), not at
module scope: this module is imported early enough that the side-loaded
environment may not be ready yet. Deferring the import until the function
actually runs is what Derivative means by initializing lazily - and it keeps
this file importable outside TouchDesigner, where neither exists.
"""

#: Where the network is built. TouchDesigner opens a project showing the inside
#: of /project1, not the true root, so building at "/" puts the network beside
#: that container rather than in it - present, addressable by path, and invisible
#: where you are actually looking. Falls back to the root if /project1 is absent.
BUILD_PARENT = "/project1"

#: Name of the container the build owns. Everything it makes lives in here.
BUILD_ROOT = "generated"

#: Name of the Table DAT holding the playlist. Phase 2 onwards reads the clips
#: out of here, so it is named once and referred to rather than spelled again.
PLAYLIST_DAT = "playlist"

#: The Movie File In TOP that decodes a clip, and the null TOP that terminates
#: the chain. Everything downstream - the switch of Phase 6, the output of
#: whatever displays this - connects to the null rather than to the player, so
#: the player can be replaced without anything else being rewired.
PLAYER_TOP = "player"
OUT_TOP = "out"

#: Which playlist row to load. Phase 4 replaces this with a draw from a shuffled
#: deck; until then it is the first clip, chosen because a fixed one makes a
#: rebuild comparable with the one before it.
FIRST_CLIP = 0

#: Play Mode. Sequential is the default already, and is set anyway because the
#: rest of the design depends on it: Cue and Speed are documented as working
#: only in this mode, so a project that quietly ended up in Locked to Timeline
#: would fail at Phase 4 rather than here.
#:
#: The internal name, not the UI label "Sequential". It was written as the label
#: first - which is the half TouchDesigner's own help documents - and set_menu
#: reported back what it resolved to on the first launch, which is how the token
#: below came to be read off the parameter rather than guessed. Either form
#: works; the name is kept because it costs no translation and no log line.
PLAY_MODE = "sequential"

#: The Window COMP that puts `out` on a display. Created beside the build
#: container rather than inside it - see _add_window for why.
WINDOW_COMP = "window"

#: Which display, in the Window COMP's own numbering (the number its Display
#: parameter shows, not a Python index into `td.monitors`).
WINDOW_DISPLAY = 2

#: Positioning is relative to whatever area this names, and WINDOW_DISPLAY
#: above only means anything when that area is a specified display rather than
#: the primary one. The alternatives are `primarydisplay` and `alldisplays`.
WINDOW_AREA = "specifydisplay"

#: Opening Size. Exclusive rather than a borderless window filling the screen:
#: it hands the display to TouchDesigner outright, which is what a playback
#: machine wants and what a second monitor is here for.
WINDOW_SIZE = "exclusive"

#: The three tokens above and below were read off the live parameters, not
#: guessed. They could not be read out of libTD.dll the way `sequential` was -
#: the binary carries parameter labels but not menu items - so they were first
#: written as UI labels and set_menu reported what each resolved to. It also
#: caught the one that was wrong: "Single Monitor" is not an item on
#: justifyoffsetto, and set_menu refused it and listed the real three rather
#: than writing a wrong value.
WINDOW_JUSTIFY = "center"

#: DPI Scaling. The alternative is `usedpiscale` ("Use DPI Scale"), which is
#: what TouchDesigner warns about on this machine: "the current position and DPI
#: scaling settings of your displays result in overlapping displays when working
#: with Scaled DPI Scaling."
#:
#: The warning is about the desktop arrangement, not about this window. The
#: displays here are mixed-DPI - a 3840x2160 primary at 150% beside two
#: 2560x1440 panels at 100% - so the two coordinate spaces disagree about where
#: the right-hand pair starts: physical x 3840, scaled x 2560, because the
#: primary is 3840 native and 2560 scaled. Anything paring a scaled origin with
#: a native size overlaps by that 1280.
#:
#: Native is both the fix and the right setting on its own terms: measured in
#: physical pixels the three displays tile exactly edge to edge, with no overlap
#: and no gaps, and an exclusive fullscreen output wants true pixels rather than
#: scaled ones. TouchDesigner has a matching warning for Native, so if that one
#: appears instead, the physical layout is not as clean as Windows reports it.
WINDOW_DPI = "native"

#: Whether to open the window at startup. Off is the useful setting when
#: working on the network itself: an exclusive fullscreen window takes the
#: display away from whatever is on it.
OPEN_WINDOW = True


def build():
    """Create the network, replacing whatever the last build left behind.

    Clear-and-rebuild rather than converging on the existing network: it is the
    simpler of the two options and makes a re-run predictable. Anything created
    outside `BUILD_ROOT` is left alone, so hand-made work sitting next to it
    survives.
    """
    # TouchDesigner injects op(), the operator classes and the rest of its
    # globals into DAT scripts, expressions and the textport - not into modules
    # imported from disk. From here they come off the td module instead.
    import td

    from . import startup

    parent = td.op(BUILD_PARENT) or td.op("/")

    previous = parent.op(BUILD_ROOT)
    if previous is not None:
        previous.destroy()

    # startup.create rather than parent.create throughout: the latter appends a
    # digit rather than fail when it will not use a name, and every name here is
    # referred to again - by the log, by the next phase, or by a wire.
    container = startup.create(parent, td.baseCOMP, BUILD_ROOT)
    container.nodeX, container.nodeY = 0, 0

    table = _place(startup.create(container, td.tableDAT, PLAYLIST_DAT), 0, 0)
    rows = _fill_playlist(table, td)
    out = _add_player(container, rows, td)
    _add_window(parent, out, td)

    return container


def _add_window(parent, target, td):
    """A Window COMP showing `target` on its own display.

    Created *beside* the build container, for the same reason the rebuild
    button is: build() destroys and recreates its own container, and a Window
    COMP inside it would go with everything else - closing and reopening an
    exclusive fullscreen window on every rebuild, which during Phase 4 means on
    every edit. Out here it is converged onto rather than recreated, so a
    rebuild leaves an open window alone.

    That works because `winop` stores a path, not a reference. The path is
    stable across rebuilds even though the operator at the end of it is not, so
    the window re-resolves to the new `out` without being touched.
    """
    from . import startup

    existing = parent.op(WINDOW_COMP)
    window = existing if existing is not None else startup.create(
        parent, td.windowCOMP, WINDOW_COMP
    )
    window.nodeX, window.nodeY = -250, -300

    startup.set_par(window, "winop", target.path)
    startup.set_menu(window, "justifyoffsetto", WINDOW_AREA)
    startup.set_par(window, "display", WINDOW_DISPLAY)
    startup.set_menu(window, "justifyh", WINDOW_JUSTIFY)
    startup.set_menu(window, "justifyv", WINDOW_JUSTIFY)
    startup.set_menu(window, "size", WINDOW_SIZE)
    startup.set_menu(window, "dpiscaling", WINDOW_DPI)

    # Only on the launch that created it. Pulsing winopen on every rebuild
    # would reopen a window that is already open, and with an exclusive display
    # that is a mode change rather than a no-op.
    if existing is None and OPEN_WINDOW:
        _pulse(window, "winopen")

    startup.report(
        f"[{startup.PACKAGE}] window at {window.path} -> {target.path}"
        f" on display {WINDOW_DISPLAY}"
    )
    return window


def _pulse(operator, name):
    """Fire a pulse parameter, reporting rather than raising if it is missing.

    Not set_par: a pulse is an event, and assigning to its value is not the
    same as firing it.
    """
    from . import startup

    parameter = getattr(operator.par, name, None)
    if parameter is None:
        startup.report(f"[{startup.PACKAGE}] no parameter {name!r} on {operator.path}")
        return None
    parameter.pulse()
    return parameter


def _add_player(container, rows, td):
    """One Movie File In TOP, playing, into a null.

    The null is not decoration. A Movie File In TOP is the operator most likely
    to be replaced - by a second one and a Switch TOP at Phase 6 - and anything
    connected to it directly would have to be rewired when that happens.
    """
    from . import playlist, startup

    player = _place(
        startup.create(container, td.moviefileinTOP, PLAYER_TOP), 0, -200
    )
    out = _place(startup.create(container, td.nullTOP, OUT_TOP), 250, -200)
    out.inputConnectors[0].connect(player)

    # Relative to the .toe, which sits at the project root - the same root the
    # playlist stored these paths against. Keeping them relative is what lets
    # the repository be cloned to a different folder and still play.
    path = playlist.clip_path(rows, FIRST_CLIP)
    startup.set_par(player, "file", path)
    startup.set_menu(player, "playmode", PLAY_MODE)
    startup.set_par(player, "play", True)
    startup.set_par(player, "speed", 1.0)

    # TOPs draw their image on the node when the viewer flag is set, which is
    # all "on screen" needs to mean at this phase. A perform window is a Phase 5
    # concern, and would be one more thing to undo if it were built now.
    player.viewer = True
    out.viewer = True

    startup.report(
        f"[{startup.PACKAGE}] player at {out.path} <- "
        + (path or "no file - playlist is empty")
    )
    return out


def _fill_playlist(table, td):
    """Scan the media folder into the Table DAT.

    Not wrapped in a try/except. A failure here is a failure of the build, and
    startup.build() already catches, logs and reports it - catching again would
    turn a traceback into a silently empty table, which is the one outcome that
    looks exactly like an empty media folder.
    """
    from . import playlist, startup

    # app.binFolder is TouchDesigner's own install path, so the ffprobe it finds
    # is the one built against the same libav version the movie reader uses.
    # Read defensively: outside TouchDesigner there is no app at all, and
    # find_ffprobe() falls back to sys.executable and then PATH.
    app = getattr(td, "app", None)
    bin_folder = getattr(app, "binFolder", None) if app is not None else None

    ffprobe = playlist.find_ffprobe(bin_folder)
    if not ffprobe:
        startup.report(f"[{startup.PACKAGE}] no ffprobe found - durations read 0")

    rows = playlist.scan(startup.project_root(), ffprobe)

    table.clear()
    table.appendRow(list(playlist.COLUMNS))
    for row in rows:
        table.appendRow([row[column] for column in playlist.COLUMNS])

    startup.report(f"[{startup.PACKAGE}] " + playlist.summarise(rows))
    # Say where it landed as well as what is in it. A rebuild destroys the table
    # along with the rest of the container, so Phase 2 needs the path, not just
    # the count.
    startup.report(f"[{startup.PACKAGE}] playlist at {table.path}")
    return rows


def _place(operator, x, y):
    """Position a node so the built network is legible when opened."""
    operator.nodeX, operator.nodeY = x, y
    return operator
