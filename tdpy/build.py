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
    _add_player(container, rows, td)

    return container


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
