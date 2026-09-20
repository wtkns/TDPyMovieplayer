"""The playlist display - what is queued, and which of it is playing.

A List COMP rather than the palette's lister. The lister is the richer of the
two and would have read the playlist table with two parameters, but its
configuration - column definitions, cell looks, callbacks - lives inside a
Config COMP inside a .tox, which is the one place this project has agreed not
to keep anything: the network is described by the files in this folder, and the
.toe is disposable. List COMP is the built-in operator the lister is built on,
so its parameters are in the help table `scaffold.params` reads, and everything
below - the text, the widths, the colours, the highlight - is ordinary Python.

The other half of the choice is what the highlight means. A lister highlights
what the *user* picked; this has to show what is *playing*, which is not the
same thing and would have fought the user the moment they clicked a row.

**Nothing here remembers which row is active.** The active row was derived,
every time, from the player's own `file` parameter - the same rule that keeps
`player.next_clip` from storing an index, applied to the display. A rebuild, a
MIDI note, an automatic advance and a hand edit of the parameter all moved the
highlight, because none of them was what the highlight was read from.

**The player is in another process, and the rule survived it.** The row and the
deck it belongs to arrive on the state output, the playlist arrives as a table,
and both are read here rather than pushed from there - so a clip changed by the
dwell, by a button, by MIDI or by a hand on the parameter moves this list the
same way, and none of them has to know the list exists. What changed at 9.5 is
that the derivation happens where the player is and crosses as two numbers.

The host does not scan `media/`. The folder belongs to the machine holding the
files; this draws what that machine says it found.
"""

from . import player, startup

#: The columns shown, in order: the playlist column to read, the header label,
#: a width in pixels, and whether the column stretches to take up spare width.
#: The list's Columns parameter is set from the length of this, so a column
#: added here appears without `build.py` being touched.
COLUMNS = (
    ("name", "clip", 360, True),
    ("duration", "length", 110, False),
)

#: Columns whose text reads better against the right edge - a duration is a
#: number, and a ragged right edge on a column of them is hard to compare.
RIGHT_ALIGNED = frozenset({"duration"})

#: What a duration of zero is drawn as. Zero is not a short clip: it is
#: TouchDesigner's own sentinel for a file whose length it could not read, and
#: what `playlist.probe` returns for a clip ffprobe would not open or when
#: there is no ffprobe at all. A row reading this is one to go and look at.
UNMEASURED = "--"

#: Row geometry. The header gets its own height so it can be sized apart from
#: the rows it labels.
ROW_HEIGHT = 34
HEADER_HEIGHT = 30
FONT_SIZE = 16

#: How far the text sits in from the cell edge it is justified against.
TEXT_INSET = 10

#: The palette. Dark, because the panel shares a room with a video wall and a
#: bright list beside a projected image is the brightest thing in it.
#:
#: Row striping is two backgrounds a hair apart: enough to follow a row across
#: to its duration, not enough to compete with the highlight, which is the one
#: colour on the panel that is meant to be found without looking for it.
TABLE_BG = (0.10, 0.10, 0.11, 1.00)
HEADER_BG = (0.17, 0.17, 0.19, 1.00)
ROW_BG = (0.12, 0.12, 0.13, 1.00)
ROW_BG_ALT = (0.15, 0.15, 0.16, 1.00)
ACTIVE_BG = (0.16, 0.42, 0.30, 1.00)

TEXT_COLOR = (0.78, 0.78, 0.80, 1.00)
HEADER_TEXT_COLOR = (0.55, 0.55, 0.58, 1.00)
ACTIVE_TEXT_COLOR = (1.00, 1.00, 1.00, 1.00)

#: Drawn under every row, so the eye can run along one without a stripe to
#: follow. Barely lighter than the background on purpose.
GRID_COLOR = (0.20, 0.20, 0.22, 1.00)


def format_duration(seconds):
    """Seconds as `m:ss`, or `h:mm:ss` once there is an hour to show.

    Takes whatever a DAT cell hands over - the table stores durations as text -
    so a string, a float and an int all work, and anything unparseable reads as
    UNMEASURED rather than raising inside a cell callback.

    Truncates rather than rounds. A clip of 59.7 seconds reading 1:00 would be
    the only row in the table that disagreed with the file it names.
    """
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return UNMEASURED
    if total <= 0:
        return UNMEASURED

    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def active_row(order, index):
    """Which list row is showing playlist row `index`, or None for none of them.

    The `+ 1` is the header row, which is row 0 of the list and no row at all
    of the playlist. None rather than 0 for "no such row" precisely because 0
    is a real row: a caller that let the two answers collapse would highlight
    the header every time the player had no file loaded.
    """
    if index is None:
        return None
    try:
        return list(order).index(index) + 1
    except ValueError:
        return None


def row_bg(row, active=None):
    """The background one list row is drawn with.

    Shared by the init callbacks and by `refresh`, which is what stops the two
    from drifting: the initial fill and every later repaint ask the same
    function what a row looks like, and neither has a copy of the answer.
    """
    if row == active:
        return ACTIVE_BG
    if row == 0:
        return HEADER_BG
    return ROW_BG if row % 2 else ROW_BG_ALT


def row_text_color(row, active=None):
    """The text colour one list row is drawn with. See `row_bg`."""
    if row == active:
        return ACTIVE_TEXT_COLOR
    if row == 0:
        return HEADER_TEXT_COLOR
    return TEXT_COLOR


def cell_text(table, order, row, col):
    """The string one cell shows, or "" where there is nothing to show.

    Row 0 is the header and takes its text from COLUMNS rather than from the
    table. Every other row indexes `order` to find which playlist row belongs
    at that position, then reads the cell by column *name* - the playlist's own
    column order is `playlist.COLUMNS`' business and this should not have to
    agree with it separately.

    Returns "" rather than raising for a row or column outside the data. The
    List COMP calls this for every cell its Rows and Columns parameters claim
    exist, and those are set from a scan that can find fewer files than the
    last one did.
    """
    if col < 0 or col >= len(COLUMNS):
        return ""
    key, label, _, _ = COLUMNS[col]
    if row == 0:
        return label

    order = list(order)
    position = row - 1
    if table is None or position < 0 or position >= len(order):
        return ""

    # +1 again, for the header row `build._fill_playlist` writes into the DAT.
    cell = table[order[position] + 1, key]
    if cell is None:
        return ""
    return format_duration(cell.val) if key == "duration" else cell.val


def _justify(name):
    """A JustifyType by name, or None where there is no TouchDesigner.

    This was `getattr(td, "JustifyType", None)` until 2026-09-08, on the
    assumption that TouchDesigner's enums hang off the `td` module. They do
    not - they live in `tdutils.TDDefinitions` - so every column was justified
    by default and the guard reported nothing, because it had been written to
    treat a missing constant as acceptable. It was not a missing constant; it
    was a wrong path, and the two are indistinguishable through a getattr.
    `startup.td_enum` now says so out loud.
    """
    return getattr(startup.td_enum("JustifyType"), name, None)


def _playlist_table():
    """The playlist the engine scanned, as it arrives in the host, or None.

    **The host does not open `media/`.** The folder belongs to the machine
    holding the files, which scans it and sends the table across; this is the
    Null DAT that table lands in. `engine.output` is the only thing that knows
    where it comes from, so a player on another machine changes that function
    and nothing here.

    None until the component has loaded and its output is wired, which is a
    normal state for the first seconds of a launch rather than a fault - so it
    is silent, and the list simply has no rows yet.
    """
    from . import engine, link

    return engine.output(link.output("playlist").name)


def _table_and_order():
    """The playlist DAT and the order its rows will be played in.

    Row count comes from `numRows` rather than from reading a column, because
    this is called once per cell and once per row during a reset and the count
    is the only thing needed to work out the order.

    The order is `deck(count, seed)` against the seed the engine publishes, not
    `player.play_order()`: that reads this process's own `SEED`, which in the
    host is always None. The deck is the player's, and the host re-deals the
    same cards from the same number rather than being sent a list of rows.
    """
    from . import engine, link

    table = _playlist_table()
    count = 0 if table is None else max(table.numRows - 1, 0)
    seed = engine.state("seed")
    return table, player.deck(count, None if seed is None else link.from_channel(seed))


def _active():
    """Which list row is playing right now, or None.

    The engine publishes a row per deck and which deck the cross is settling
    on; this asks for the live one. Still derived rather than remembered, and
    still derived from what the player is actually doing - the difference from
    Phase 5 is only that the derivation happens in another process and arrives
    as a number.

    None when the engine has not said yet, when the deck has no clip, or when
    the clip is not in the playlist - all three already meant no highlight.
    """
    from . import engine, link

    row = engine.deck_state(link.DECK_ROW)
    if row is None:
        return None
    _, order = _table_and_order()
    return active_row(order, link.from_channel(row))


def init_table(comp, attribs):
    """Everything true of every cell unless a row or column overrides it."""
    attribs.bgColor = TABLE_BG
    attribs.textColor = TEXT_COLOR
    attribs.fontSizeX = FONT_SIZE
    attribs.rowHeight = ROW_HEIGHT
    attribs.bottomBorderOutColor = GRID_COLOR


def init_col(comp, col, attribs):
    """Column width, stretch and which edge its text sits against."""
    if col < 0 or col >= len(COLUMNS):
        return
    key, _, width, stretch = COLUMNS[col]
    attribs.colWidth = width
    attribs.colStretch = stretch

    right = key in RIGHT_ALIGNED
    justify = _justify("CENTERRIGHT" if right else "CENTERLEFT")
    if justify is not None:
        attribs.textJustify = justify
    attribs.textOffsetX = -TEXT_INSET if right else TEXT_INSET


def init_row(comp, row, attribs):
    """Row height and colour, highlight included.

    The highlight is applied here as well as in `refresh` on purpose. A reset
    re-runs these callbacks and would otherwise repaint over a highlight that
    `refresh` had already put down, which makes the display's correctness
    depend on the order two things happen in. Both ask `row_bg` instead, so
    there is no order to get wrong.
    """
    active = _active()
    attribs.rowHeight = HEADER_HEIGHT if row == 0 else ROW_HEIGHT
    attribs.bgColor = row_bg(row, active)
    attribs.textColor = row_text_color(row, active)
    attribs.fontBold = row == 0 or row == active


def init_cell(comp, row, col, attribs):
    """What one cell says."""
    table, order = _table_and_order()
    attribs.text = cell_text(table, order, row, col)


def refresh():
    """Repaint the highlight from what the player is actually showing.

    Called by the Parameter Execute DAT watching the player's `file`, so it
    runs whenever the clip changes and no matter what changed it - the next
    button, a MIDI note at Phase 7, `advance()` at Phase 4, or someone typing
    a path into the parameter by hand. Nothing has to remember to call it, and
    nothing can forget.

    Every row is repainted rather than only the two that changed, because
    tracking which row was highlighted last would be exactly the stored state
    this project keeps refusing to keep. Twenty rows is not a cost worth
    introducing a second source of truth for.

    Returns the row it highlighted, or None - useful from the textport.
    """
    comp = _list_comp()
    if comp is None:
        return None

    _, order = _table_and_order()
    active = _active()

    for row in range(len(order) + 1):
        attribs = comp.rowAttribs[row]
        attribs.bgColor = row_bg(row, active)
        attribs.textColor = row_text_color(row, active)
        attribs.fontBold = row == 0 or row == active

    if active is not None:
        try:
            comp.scroll(active, 0)
        except Exception:
            # The one call here that can fail on a list which has not laid
            # itself out yet - during the build, before the panel is drawn.
            # The highlight is the point and the scroll is a convenience; it
            # does not get to take the build with it.
            pass
    return active


def on_state(channel):
    """Redraw whatever that state channel changing has affected. Returns the row.

    **A moved row and a moved deck are not the same redraw**, and that is the
    whole of what this decides. `live`, `row_a` and `row_b` change which clip is
    playing, and the highlight is row attributes - `refresh` repaints those. The
    seed changes the *order*, which moves every row's text, and text is written
    by the init callbacks - so that one needs `reset`.

    Doing the cheap one for a seed change is a specific and confusing symptom:
    the highlight jumps to where the clip now sits in the deck while the list
    still shows the old order, so the wrong row lights up. Doing the expensive
    one for every cut would re-run the init callbacks over every cell several
    times a cut.

    The shim in `build.STATE_WATCH_CALLBACK` hands over a name and decides
    nothing, like every other shim here - which is what makes this one function
    rather than a condition in a DAT.
    """
    if channel == "seed":
        return reset()
    return refresh()


def resize():
    """Set the list's row count from the playlist that arrived, then redraw.

    The table comes from the other process, so its length is not known when the
    panel is built and changes again whenever the engine rescans - which is why
    the List COMP's Rows is written here rather than at build time. One more
    row than there are clips: row 0 is the header.

    Called at the end of the build, with whatever has arrived by then, and from
    the playlist's watcher every time the table changes. Both go through here,
    so a list that is one row short is one place to look.
    """
    comp = _list_comp()
    if comp is None:
        return None

    _, order = _table_and_order()
    startup.set_par(comp, "rows", len(order) + 1)
    return reset()


def reset():
    """Rebuild every row's text, then repaint the highlight.

    For when the *order* changed rather than the clip - which today means the
    shuffle button, and nothing else. The highlight follows the player's
    `file` on its own, but a reshuffle moves every row while leaving `file`
    exactly where it was, so nothing would otherwise fire.

    Pulsing Reset re-runs the init callbacks, which is what re-reads the order
    and rewrites the cells; `refresh` afterwards is for the scroll, since the
    playing clip has very likely moved a long way up or down the list.
    """
    comp = _list_comp()
    if comp is None:
        return None

    parameter = getattr(comp.par, "reset", None)
    if parameter is None:
        startup.report(f"[{startup.PACKAGE}] no reset parameter on {comp.path}")
        return None
    parameter.pulse()
    return refresh()


def _list_comp():
    """The List COMP, or None with a line saying why.

    Looked up by path every time rather than held, for the reason
    `player._ops` does the same: `build()` destroys and recreates the panel,
    and a reference captured once would be pointing at a corpse afterwards.
    """
    import td

    from . import build

    parent = td.op(build.BUILD_PARENT) or td.op("/")
    panel = parent.op(build.CONTROL_PANEL_COMP)
    node = None if panel is None else panel.op(build.CLIP_LIST_COMP)
    if node is None:
        startup.report(
            f"[{startup.PACKAGE}] no {build.CLIP_LIST_COMP} under"
            f" {build.CONTROL_PANEL_COMP} - has the build run?"
        )
    return node
