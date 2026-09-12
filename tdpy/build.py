"""The network this project builds.

This is the file to edit. It is the only module that reaches into TouchDesigner,
which keeps the rest of the package readable - and testable - outside it.

Phase 2 builds the playlist and one clip playing from it: a Table DAT holding
one row per video file in `media/`, a Movie File In TOP loading the first of
them, and a null TOP to hang the rest of the project off. One clip, no cycling -
the shuffled deck, the random cue point and the dwell timer are all Phase 4.

Phase 5 adds a control panel - play, pause and next - in a bounded window of
its own on a display separate from the one showing the video. The buttons do
nothing themselves: each is a shim into `tdpy.player`, which is where Phase 4's
`advance()` will live and where anything worth calling from MIDI already does.

The panel then gained a clip list under those buttons: a List COMP showing
every file and its length in the order they will be played, with the playing
one highlighted. It is drawn entirely by `tdpy.lister` through a callbacks DAT
written from here, and its highlight is redrawn by a Parameter Execute DAT
watching the player's `file` - so the list follows what is on screen rather
than being told about it. See `tdpy/lister.py` for why that matters and why
this is a List COMP rather than the palette's lister.

Phase 4b puts the player's four settings on a `settings` COMP of their own as
custom parameters, and the panel gained a band between the transport and the
list showing them: a toggle or a slider each, and a Parameter COMP rendering
all four as editable fields. Every one of those controls is *bound* to its
parameter rather than wired to a callback, so the slider, the field and Phase
7's MIDI are three views of one value with nothing synchronising them. The
player's own `speed` is bound the same way. `tdpy/settings.py` holds what the
settings are; this file only draws them.

Phase 4c makes the other three settings do something, which takes two triggers
and no new behaviour. An Info CHOP on the player publishes `loop_frame`, a CHOP
Execute DAT watches its rising edge, and a Timer CHOP with its length bound to
the dwell calls back at the end of every cycle. Both callbacks are shims into
`tdpy.player`, which reads the relevant setting and either advances or does not
- so the end-of-file toggle and the dwell are policies rather than wiring, and
`media/` cycles on its own with nothing pressed. The cue point goes on the
player as configuration (Fraction units, Extend Right on Cycle) and the value
written into it comes from `player.cue_fraction`.

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

#: Extend Right - what the player does with movie positions past the end. Set
#: to Cycle permanently, so a clip that runs out loops back to its own start,
#: and the end-of-file *policy* is then one toggle deciding whether the watcher
#: below advances or does nothing. Both behaviours come out of one network.
#:
#: The alternative build - Hold, then detect the last frame - is the one to
#: avoid, and TouchDesigner's own help says why: of `last_frame` it notes "if a
#: frame is dropped the last frame may never get shown". `loop_frame` has no
#: such caveat, which is what decided this. Both are in Movie_File_In_TOP.htm
#: under the install's OfflineHelp.
#:
#: `cycle` is the internal name, documented outright on that page rather than
#: resolved by set_menu: "Cycle cycle - Loops the movie range continuously."
PLAYER_EXTEND_RIGHT = "cycle"

#: Cue Point Unit. Fraction, so a random start point needs no duration at all -
#: 0.0 is the head of the clip and 0.5 is halfway in, whatever it is measured
#: to be. The playlist has every length already, but a resolution-independent
#: cue means the cue policy does not go wrong on the one row whose duration
#: read 0 because ffprobe could not open it.
#:
#: The label rather than the token, because the token is not written down: the
#: help table describes this menu's items in prose ("Index, Frames, Seconds,
#: and Fraction (percentage)") and never names them. `set_menu` resolves it
#: against the live parameter and reports what it landed on.
CUE_POINT_UNIT = "Fraction"

#: The COMP carrying the player's settings as custom parameters - what happens
#: at the end of a file, where a clip starts, how long it is held, how fast it
#: runs. Beside the build container rather than inside it, for the reason the
#: windows are: `build()` destroys its own container, and a rebuild in the
#: middle of tuning a dwell should not put the dwell back. `tdpy/settings.py`
#: owns what is on it; this is only the name.
SETTINGS_COMP = "settings"

#: The Window COMP that puts `out` on a display. Created beside the build
#: container rather than inside it - see _ensure_window for why.
VIDEO_WINDOW_COMP = "videoPlayerWindow"

#: Names this project has used for nodes it builds beside the container, and
#: does not use any more. They are destroyed on every build, because a stale
#: one is not inert: a Window COMP left under the old name goes on holding its
#: display exclusively while the renamed one tries to take the same one.
#:
#: `window` was the video window's name through Phase 2, renamed when a second
#: window arrived and "the window" stopped meaning anything. `bindSpike` and
#: its window were the Phase 4b binding spike, deleted once it had answered.
#: Removable once no session or saved .toe can still be carrying one.
LEGACY_NAMES = ("window", "bindSpike", "bindSpikeWindow")

#: Which display, as a **zero-based** index into the Monitors DAT - the same
#: order `td.monitors` is in, and one less than the number Windows' own display
#: settings put on the same screen.
#:
#: Worth stating because it is the kind of thing that looks like a display
#: number and is not, and because a wrong one does not fail: TouchDesigner
#: opens the window somewhere else and carries on. Its own message is the
#: evidence for the numbering, lifted out of libTD.dll - "Monitor specified in
#: <op> does not exist. Opening on monitor 0 instead." - since a fallback onto
#: monitor 0 only makes sense where 0 is a monitor.
#:
#: So on this machine's three displays the valid values are 0, 1 and 2: the 4K
#: primary, and the two 2560x1440 panels beside it.
VIDEO_WINDOW_DISPLAY = 2

#: Positioning is relative to whatever area this names, and a display number
#: only means anything when that area is a specified display rather than the
#: primary one. The alternatives are `primarydisplay` and `alldisplays`.
WINDOW_AREA = "specifydisplay"

#: Where a window goes when the display it asked for is not attached. Two
#: displays open onto specified numbers now, and a machine with fewer would
#: otherwise place them by a rule nobody wrote down - Phase 5 is the point at
#: which the project has to know how many displays it has and say so when it
#: does not, rather than discovering it as a window that never appeared.
WINDOW_AREA_FALLBACK = "primarydisplay"

#: Opening Size for the video window. Exclusive rather than a borderless window
#: filling the screen: it hands the display to TouchDesigner outright, which is
#: what a playback machine wants and what a second monitor is here for.
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

#: Whether to open the video window at startup. Off is the useful setting when
#: working on the network itself: an exclusive fullscreen window takes the
#: display away from whatever is on it.
OPEN_VIDEO_WINDOW = True


#: The control panel, and the window that shows it. Both live beside the build
#: container, for the reason the video window does - but they are not treated
#: alike, and the difference is the whole of the arrangement. The *window* is
#: converged onto, so a rebuild leaves it open and where it was. The *panel* is
#: destroyed and rebuilt with everything else, so changing a button is a click
#: of rebuild rather than a restart.
#:
#: That asymmetry is safe here in a way it is not for the rebuild button, which
#: has to sit outside the build for exactly the opposite reason: it calls
#: build(), so rebuilding it would destroy the DAT running the callback. None
#: of these buttons calls build(). They call `tdpy.player`, which does not.
CONTROL_PANEL_COMP = "controlPanel"
CONTROL_WINDOW_COMP = "controlPanelWindow"

#: A different display from VIDEO_WINDOW_DISPLAY, which is the requirement
#: rather than a preference: the surface being operated and the surface being
#: shown should never be the same one.
#:
#: Zero-based, like VIDEO_WINDOW_DISPLAY - this was written as 3 first, on the
#: assumption that three displays are numbered 1, 2, 3, and the window opened
#: somewhere it had not been asked for rather than refusing.
CONTROL_WINDOW_DISPLAY = 1

#: Opening Size for the panel window. Custom, with the size below - a bounded
#: window, deliberately not exclusive. It is a thing to be clicked while other
#: windows are visible, so it gets borders and a title bar too.
#:
#: The internal name. It was left as the label "Custom" through Phase 5 and
#: reported a resolution line on every launch since; taking the token back is
#: the whole point of set_menu reporting it.
CONTROL_WINDOW_SIZE = "custom"

#: Whether to open the panel window at startup. Unlike the video window this
#: costs nothing to leave on - a bordered window on a spare display takes
#: nothing away from anything.
OPEN_CONTROL_WINDOW = True

#: The panel stacks two things - the row of transport buttons, and the clip
#: list under it - so it aligns vertically while the button row inside it
#: aligns horizontally.
#:
#: Internal names, not the UI labels "Top to Bottom" and "Left to Right". Both
#: were written as labels first - which is the half TouchDesigner's own help
#: documents, since it lists menu items in prose and never gives their names -
#: and `set_menu` reported what it resolved them to on the first launch. Same
#: route as `sequential` and `center` above, and the same reason for keeping
#: the resolved form: it costs no translation and no log line.
CONTROL_PANEL_ALIGN = "verttb"
TRANSPORT_ALIGN = "horizlr"

#: The container holding the buttons. It exists only so the panel can stack a
#: row on top of a list: two alignments cannot be asked of one container.
TRANSPORT_COMP = "transport"

#: Button geometry, and the panel and window sized from it. Derived rather than
#: three numbers separately maintained: a button width changed here moves the
#: window edge with it instead of leaving a strip of dead panel.
#:
#: Narrowed from 240 when the row went from three buttons to five, which at the
#: old width would have made the panel 1280 wide - and with it the clip list,
#: whose two columns have nothing to do with that much space.
BUTTON_WIDTH = 180
BUTTON_HEIGHT = 160
BUTTON_FONT_SIZE = 28
PANEL_SPACING = 20

#: The buttons, in order: operator name, and the label drawn on it. The name is
#: the load-bearing half - `tdpy.player.COMMANDS` is keyed on it, and the
#: callback DAT dispatches on the name of whichever panel was clicked. Adding a
#: control means a row here and a function there, and nothing else - which is
#: what adding previous and shuffle actually cost, and the first real evidence
#: that the dispatch was worth building instead of three wired buttons.
#:
#: Laid out as transport left to right with shuffle set apart at the end, since
#: it is the one button that does not move the playhead: it changes what comes
#: next and leaves the current clip playing.
#:
#: `previous` is labelled `prev` only because the label has to fit the button;
#: the name is the half that has to match `player.COMMANDS`, and it is spelled
#: out there.
CONTROL_BUTTONS = (
    ("previous", "prev"),
    ("play", "play"),
    ("pause", "pause"),
    ("next", "next"),
    ("shuffle", "shuffle"),
)

#: Momentary, like the rebuild button: a click is a clean off-to-on edge rather
#: than a state to be toggled back. Play and pause being two momentary buttons
#: rather than one toggle means neither shows the transport's actual state.
CONTROL_BUTTON_TYPE = "momentary"

#: The settings band: a row of toggles and sliders, and a Parameter COMP under
#: it, between the transport and the clip list. Everything in it is a *view* of
#: a parameter on SETTINGS_COMP rather than a control that decides anything -
#: which is why none of these operators has a callback, and why adding a third
#: writer later (a MIDI CC) needs nothing here changed.
SETTINGS_ROW_COMP = "settingsRow"
SETTINGS_ROW_HEIGHT = 100
PARAMETER_COMP = "parameters"
PARAMETER_HEIGHT = 170

#: Toggle Down: on when pushed, off when pushed again. These are values, not
#: actions, which is the whole difference between this row and the transport
#: above it - a transport button *does* something and springs back, a toggle
#: *is* something until it is changed.
SETTINGS_TOGGLE_TYPE = "toggledown"

#: Slider U - a horizontal slider tracking the u panel value. The other two are
#: `sliderv` and `slideruv`; all three are named in the Slider COMP's help.
SETTINGS_SLIDER_TYPE = "slideru"

#: The toggles take a transport button's width, so the row lines up with the
#: one above it; the sliders divide whatever is left.
SETTINGS_TOGGLE_WIDTH = BUTTON_WIDTH

#: The parameters mapping a slider's drag onto the setting's range.
#:
#: **Not in `Config/TDParameterHelp.json`** - that file's Slider COMP predates
#: them and lists only `value0`, `value1` and the zone parameters. They are in
#: the type stub TouchDesigner generates from the live operator, at
#: `bin/Lib/tdi/ops/comps/sliderCOMP.py`, where their help reads "Help Not
#: Available". So the names are read rather than guessed, but their behaviour
#: is not documented anywhere and is confirmed on screen instead: drag dwell to
#: the right-hand end and it should read 60, not 1.
#:
#: Without them the question would be open in a worse way. A slider's value0 is
#: a panel position, and a panel position bound to a parameter whose range is
#: 0-60 would write 0-1 into it and there would be nothing in the log to say
#: that was what happened.
SLIDER_RANGE_LOW = "valuerange0l"
SLIDER_RANGE_HIGH = "valuerange0h"

#: The Panel Execute DAT watching every button, and the shim it holds. One DAT
#: for all three: `panelValue.owner` is the panel that was clicked, so the
#: dispatch is a dictionary lookup in reloadable Python rather than three
#: near-identical DATs generated from here.
CONTROL_EXEC_NAME = "controls_exec"
CONTROL_PANEL_VALUE = "state"
CONTROL_CALLBACK = '''# Generated by tdpy/build.py - edits here are overwritten.


def onOffToOn(panelValue):
    import tdpy.player

    tdpy.player.command(panelValue.owner.name)
    return
'''


#: The clip list, and the Text DAT holding the callbacks that draw it.
#:
#: Named for what it shows rather than for the table behind it: `playlist` is
#: already the Table DAT inside the build container, and two operators of that
#: name in one project would make every log line ambiguous about which one it
#: meant.
#:
#: A built-in List COMP rather than the palette's lister. The lister would have
#: read the playlist table with two parameters and brought headers, sorting and
#: filtering with it, but its column definitions and cell looks live inside a
#: Config COMP inside a .tox - which is the one place this project has agreed
#: not to keep anything. Its selection also means "the user picked this", where
#: what has to be shown here is "this is playing". `tdpy/lister.py` has the
#: rest of that reasoning.
CLIP_LIST_COMP = "clipList"
CLIP_LIST_CALLBACK_DAT = "clipList_callbacks"

#: Height of the list, and so of the panel below the buttons. Fixed rather than
#: grown to fit the playlist: a folder of twenty clips is already taller than a
#: window wants to be and the folder is meant to change, so the list scrolls
#: instead of the window resizing itself out from under whoever is using it.
CLIP_LIST_HEIGHT = 620

#: Every callback is a shim into `tdpy.lister`, for the reason the buttons are
#: shims into `tdpy.player`: a DAT's contents are inside the .toe, and the .toe
#: is the thing this project keeps empty. Written here, reloadable there.
CLIP_LIST_CALLBACK = '''# Generated by tdpy/build.py - edits here are overwritten.


def onInitTable(comp, attribs):
    import tdpy.lister

    tdpy.lister.init_table(comp, attribs)
    return


def onInitCol(comp, col, attribs):
    import tdpy.lister

    tdpy.lister.init_col(comp, col, attribs)
    return


def onInitRow(comp, row, attribs):
    import tdpy.lister

    tdpy.lister.init_row(comp, row, attribs)
    return


def onInitCell(comp, row, col, attribs):
    import tdpy.lister

    tdpy.lister.init_cell(comp, row, col, attribs)
    return
'''

#: The Parameter Execute DAT that keeps the highlight true, and the parameter
#: it watches. Watching the player's `file` rather than having `next_clip()`
#: update the list is the whole design of the thing: the display then follows
#: what is actually on screen regardless of what put it there - the next
#: button, Phase 4's `advance()`, a MIDI note at Phase 7, or a path typed into
#: the parameter by hand. Nothing has to remember to redraw, and so nothing
#: can forget to.
#:
#: `pars`, not `parameters` - read off the operator's parameter list rather
#: than guessed, which is what `scaffold.params` is for.
CLIP_LIST_EXEC_NAME = "clipList_exec"
CLIP_LIST_WATCH_PAR = "file"
CLIP_LIST_EXEC_CALLBACK = '''# Generated by tdpy/build.py - edits here are overwritten.


def onValueChange(par, prev):
    import tdpy.lister

    tdpy.lister.refresh()
    return
'''

#: The Info CHOP reading the player's own state, and the CHOP Execute DAT
#: watching one channel of it. An Info CHOP is the only way to see `loop_frame`
#: from anywhere: it is a channel the Movie File In TOP publishes rather than a
#: parameter, so nothing can bind to it and no Parameter Execute DAT can watch
#: it.
#:
#: The channel name was read rather than guessed. `loop_frame` is documented on
#: Movie_File_In_TOP.htm as "1 if the movie has just looped", and the string is
#: in `libTD.dll` - which is also how the Timer CHOP's cycle-pulse channel was
#: ruled out for the dwell timer below: that one is *not* in the binary under
#: the name the docs' neighbouring entries would suggest, so the timer is read
#: through its callback instead.
PLAYER_INFO_CHOP = "playerInfo"
LOOP_EXEC_NAME = "loop_exec"
LOOP_CHANNEL = "loop_frame"

#: Info Type on that CHOP - see the comment where it is set for why this is the
#: widest of the three options rather than the one that sounds right.
INFO_TYPE = "all"

#: `onOffToOn` rather than `onValueChange`: `loop_frame` is 1 for the frame the
#: movie wrapped on and 0 either side, so the rising edge is exactly one event
#: per loop. Watching the value change would fire twice.
#:
#: The signature is the install's own, from
#: `bin/Lib/tdutils/DATScripts/chopexecuteDAT.py`.
LOOP_CALLBACK = '''# Generated by tdpy/build.py - edits here are overwritten.


def onOffToOn(channel, sampleIndex, val, prev):
    import tdpy.player

    tdpy.player.on_loop()
    return
'''

#: The dwell timer, and the Text DAT holding its callback.
#:
#: A Timer CHOP rather than a counter of frames in Python: it is the operator
#: that already knows how to be paused, sped up and asked how far through it
#: is, and its length can be a bind reference to the Dwell parameter so the
#: slider, the typed field and Phase 7's MIDI reach it without anything
#: carrying a number across.
DWELL_TIMER_CHOP = "dwell"
DWELL_CALLBACK_DAT = "dwell_callbacks"

#: Length Units. The label, resolved by `set_menu` - the help table gives this
#: menu's items in prose ("Samples, Frames, or Seconds") and not their tokens.
DWELL_LENGTH_UNITS = "Seconds"

#: Length Type. `fixed`, the documented token for a finite length; the other
#: item is `infinite`, which never reaches the end of a cycle and so would never
#: call back. Set explicitly for that reason - the wrong value here is a dwell
#: that silently does nothing, which is the symptom this phase exists to remove.
DWELL_LENGTH_TYPE = "fixed"

#: Defer Par Changes, explicitly off. On, "parameter changes like Length ... are
#: ignored until the next Initialize" - which would mean a dwell slider that
#: appeared to do nothing until the clip after next. Dragging it should take
#: effect now, so this is the default and it is still set, because the wrong
#: value here is invisible rather than broken.
DWELL_DEFER_PARS = False

#: `onCycleStart`, with the signature from the install's own
#: `bin/Lib/tdutils/DATScripts/timerCHOP_callbacks.py`.
#:
#: `cycle` is passed straight through and guarded on the far side rather than
#: here, because the shim's whole job is to know nothing: whether a cycle index
#: of 0 means the timer just started or the dwell just expired is a question
#: about the timer, and `tdpy.player` is where questions like that are answered.
DWELL_CALLBACK = '''# Generated by tdpy/build.py - edits here are overwritten.


def onCycleStart(timerOp, segment, cycle):
    import tdpy.player

    tdpy.player.on_dwell(cycle)
    return
'''

#: The Parameter Execute DAT that follows the Dwell setting, and the parameter
#: it watches.
#:
#: A dwell of 0 means the timer is *off* rather than cutting every frame, and
#: that is a mode rather than a value - so it cannot be a binding, which mirrors
#: a number and cannot interpret one. It is the same shape as the clip list's
#: watcher: one operator following one parameter, so nothing has to remember to
#: tell the timer that the dwell changed.
#:
#: The name of the parameter comes from `settings.DWELL` rather than being
#: spelled again here, so a rename is caught by the interpreter.
DWELL_EXEC_NAME = "dwell_exec"
DWELL_EXEC_CALLBACK = '''# Generated by tdpy/build.py - edits here are overwritten.


def onValueChange(par, prev):
    import tdpy.player

    tdpy.player.on_dwell_change()
    return
'''


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

    from . import lister, player, settings, startup

    parent = td.op(BUILD_PARENT) or td.op("/")

    previous = parent.op(BUILD_ROOT)
    if previous is not None:
        previous.destroy()

    _drop_legacy(parent)

    # Before the container, and outside it. The player binds its speed to one
    # of these parameters, and the panel binds four controls to them, so they
    # have to exist before either is built - and they have to survive the
    # destroy above, which is why they are not in the container at all.
    configuration = settings.ensure(parent, td)

    # startup.create rather than parent.create throughout: the latter appends a
    # digit rather than fail when it will not use a name, and every name here is
    # referred to again - by the log, by the next phase, or by a wire.
    container = startup.create(parent, td.baseCOMP, BUILD_ROOT)
    container.nodeX, container.nodeY = 0, 0

    table = _place(startup.create(container, td.tableDAT, PLAYLIST_DAT), 0, 0)
    rows = _fill_playlist(table, td)
    out = _add_player(container, rows, configuration, td)
    _add_cycle(container, configuration, td)
    _add_video_window(parent, out, td)

    panel = _add_control_panel(parent, container, rows, configuration, td)
    _add_control_window(parent, panel, td)

    # After the panel exists and the player has its file, so the highlight is
    # right on the first frame rather than on the first clip change. The init
    # callbacks put it down too - see lister.init_row for why both - so this
    # is really here for the scroll-into-view.
    lister.refresh()

    # The dwell watcher only fires when the Dwell parameter *changes*, and a
    # launch is not a change - so the timer would sit running with whatever
    # Play it was created holding until somebody touched the slider. Asking the
    # same function the watcher asks is how the state is right on the first
    # frame, and there is only one place that decides it either way.
    player.on_dwell_change()

    return container


def _drop_legacy(parent):
    """Destroy nodes this project used to build under names it has retired.

    Renaming a node in the source does not rename the one a running session or
    a saved .toe is already holding - it creates a second one and leaves the
    first where it was. For most nodes that is only clutter; for a Window COMP
    it is a window still open on a display the renamed one is about to ask for.
    """
    from . import startup

    for name in LEGACY_NAMES:
        stale = parent.op(name)
        if stale is None:
            continue
        startup.report(f"[{startup.PACKAGE}] removing retired {stale.path}")
        stale.destroy()


def _ensure_window(parent, name, target, display, td):
    """A Window COMP showing `target`, found or made, placed on a display.

    Created *beside* the build container, for the same reason the rebuild
    button is: build() destroys and recreates its own container, and a Window
    COMP inside it would go with everything else - closing and reopening an
    exclusive fullscreen window on every rebuild, which during Phase 4 means on
    every edit. Out here it is converged onto rather than recreated, so a
    rebuild leaves an open window alone.

    That works because `winop` stores a path, not a reference. The path is
    stable across rebuilds even though the operator at the end of it is not, so
    the window re-resolves to the newly built node without being touched.

    Returns the window and whether it was created by this call, since only the
    caller knows whether a new window should be opened.
    """
    from . import startup

    existing = parent.op(name)
    window = existing if existing is not None else startup.create(
        parent, td.windowCOMP, name
    )

    startup.set_par(window, "winop", target.path)
    if _display_attached(display, td):
        startup.set_menu(window, "justifyoffsetto", WINDOW_AREA)
        startup.set_par(window, "display", display)
    else:
        startup.set_menu(window, "justifyoffsetto", WINDOW_AREA_FALLBACK)
    startup.set_menu(window, "justifyh", WINDOW_JUSTIFY)
    startup.set_menu(window, "justifyv", WINDOW_JUSTIFY)
    startup.set_menu(window, "dpiscaling", WINDOW_DPI)

    return window, existing is None


def _display_attached(display, td):
    """Whether a display of that index exists, saying so if it does not.

    Zero-based, so `td.monitors` is indexed directly rather than offset - the
    Window COMP's Display parameter is an index into the same list the Monitors
    DAT shows, not the number Windows draws on the screen in its own display
    settings. Getting that wrong is what this function exists to catch, and it
    got it wrong itself first: written as a 1-based check, it passed a display
    3 that does not exist on a three-display machine and would have rejected
    display 0, which is the primary.

    TouchDesigner does not refuse an out-of-range index - it opens the window
    on monitor 0 and says so, which is the same fallback taken here. So this is
    about *where the sentence lands*: TouchDesigner's goes to the textport, and
    this project reads its diagnostics out of logs/startup.log.
    """
    from . import startup

    monitors = getattr(td, "monitors", None)
    try:
        count = len(monitors)
    except TypeError:
        return True  # cannot tell - let TouchDesigner place it

    if 0 <= display < count:
        return True
    startup.report(
        f"[{startup.PACKAGE}] display {display} requested, {count} attached"
        f" (valid 0-{count - 1}) - opening on the primary instead"
    )
    return False


def _add_video_window(parent, target, td):
    """The exclusive fullscreen output: `out`, alone on its display."""
    from . import startup

    window, created = _ensure_window(
        parent, VIDEO_WINDOW_COMP, target, VIDEO_WINDOW_DISPLAY, td
    )
    window.nodeX, window.nodeY = -250, -300
    startup.set_menu(window, "size", WINDOW_SIZE)

    # Only on the launch that created it. Pulsing winopen on every rebuild
    # would reopen a window that is already open, and with an exclusive display
    # that is a mode change rather than a no-op.
    if created and OPEN_VIDEO_WINDOW:
        pulse(window, "winopen")

    startup.report(
        f"[{startup.PACKAGE}] window at {window.path} -> {target.path}"
        f" on display {VIDEO_WINDOW_DISPLAY}"
    )
    return window


def _add_control_window(parent, target, td):
    """The panel's window: bounded, bordered, and on another display."""
    from . import startup

    window, created = _ensure_window(
        parent, CONTROL_WINDOW_COMP, target, CONTROL_WINDOW_DISPLAY, td
    )
    window.nodeX, window.nodeY = -250, -750
    startup.set_menu(window, "size", CONTROL_WINDOW_SIZE)
    # Sized from the panel rather than the other way round, so the window's
    # edges follow whatever the panel turns out to be. Note this only takes
    # effect on a window this build created: an already-open one keeps the size
    # it was opened at, which is the standing cost of converging onto a window
    # instead of rebuilding it. Changing the panel's geometry wants a restart.
    was = None if created else (window.par.winw.eval(), window.par.winh.eval())
    startup.set_par(window, "winw", _panel_width())
    startup.set_par(window, "winh", _panel_height())
    # Said out loud, because the symptom is a panel with its bottom cut off and
    # nothing anywhere to explain it. Read off the parameters rather than the
    # window, so it is the *change* that is reported: the launch after this one
    # is silent even though the window it reopens is the right size for the
    # first time. The panel has grown a row twice now, so this is the third
    # time the cost of converging onto a window rather than rebuilding it has
    # actually been paid.
    if was is not None and was != (_panel_width(), _panel_height()):
        startup.report(
            f"[{startup.PACKAGE}] panel is now {_panel_width()}x{_panel_height()},"
            f" window opened at {was[0]:g}x{was[1]:g}"
            " - restart TouchDesigner to resize it"
        )
    startup.set_par(window, "borders", True)
    # The one setting this window exists for, and off it would look exactly
    # like the activeViewer symptom the framework already has - a panel drawn
    # correctly that does not respond to the mouse.
    startup.set_par(window, "interact", True)

    if created and OPEN_CONTROL_WINDOW:
        pulse(window, "winopen")

    startup.report(
        f"[{startup.PACKAGE}] control window at {window.path} -> {target.path}"
        f" on display {CONTROL_WINDOW_DISPLAY}"
    )
    return window


def _panel_width():
    """The panel's width, from the buttons it holds rather than as a constant.

    Spacing falls between the buttons and not outside them, so a row of n
    buttons is n widths and n-1 gaps. Getting this wrong shows up as a strip of
    empty panel or a button clipped at the edge, neither of which says which
    number was wrong.

    The clip list under the buttons takes the same width rather than setting
    its own - one edge down the panel, and a column in the list stretches to
    absorb whatever the buttons leave over.
    """
    count = len(CONTROL_BUTTONS)
    return count * BUTTON_WIDTH + max(count - 1, 0) * PANEL_SPACING


def _panel_height():
    """The panel's height: its four stacked rows, with a gap between each.

    Derived for the same reason the width is, and as a list rather than a sum
    of named constants so that adding a row is adding a row. The window is
    sized from this, so a taller list moves the window's bottom edge instead of
    being cut off by it.
    """
    rows = (BUTTON_HEIGHT, SETTINGS_ROW_HEIGHT, PARAMETER_HEIGHT, CLIP_LIST_HEIGHT)
    return sum(rows) + max(len(rows) - 1, 0) * PANEL_SPACING


def _slider_width():
    """How wide each settings slider is: the row, less the toggles and gaps.

    The toggles take a fixed width so the row lines up with the transport above
    it, and the sliders absorb whatever that leaves - so a button width changed
    at the top of this file moves the sliders rather than opening a strip of
    dead panel beside them.
    """
    from . import settings

    count = len(settings.sliders())
    if count <= 0:
        return 0
    fixed = len(settings.toggles()) * SETTINGS_TOGGLE_WIDTH
    gaps = max(len(settings.SETTINGS) - 1, 0) * PANEL_SPACING
    return max(_panel_width() - fixed - gaps, 0) // count


def _add_control_panel(parent, container, rows, configuration, td):
    """The panel: transport, the settings band, and the clip list beneath them.

    Destroyed and rebuilt on every build, unlike the window that shows it - so
    a button relabelled or a column added here arrives with a click of rebuild.
    The window converges onto the new panel because `winop` holds a path, and
    the path does not change when the operator at the end of it does.

    `container` is the build container, needed only so the Parameter Execute
    DAT can be pointed at the player TOP inside it; `rows` is the scanned
    playlist, needed only for its length; `configuration` is the settings COMP
    the band's controls bind to.
    """
    from . import startup

    existing = parent.op(CONTROL_PANEL_COMP)
    if existing is not None:
        existing.destroy()

    panel = startup.create(parent, td.containerCOMP, CONTROL_PANEL_COMP)
    panel.nodeX, panel.nodeY = -250, -600
    startup.set_par(panel, "w", _panel_width())
    startup.set_par(panel, "h", _panel_height())
    startup.set_menu(panel, "align", CONTROL_PANEL_ALIGN)
    startup.set_par(panel, "spacing", PANEL_SPACING)
    # Both flags, for the reason the rebuild button needs both: `viewer` draws
    # the panel on the node, `activeViewer` makes that drawing answer the
    # mouse. Neither governs the window, which is where this panel is actually
    # meant to be clicked - they are here so the node in the network works too.
    panel.viewer = True
    panel.activeViewer = True

    _add_transport(panel, td)
    _add_settings_row(panel, configuration, td)
    _add_parameters(panel, configuration, td)
    _add_clip_list(panel, container, rows, td)

    startup.report(
        f"[{startup.PACKAGE}] control panel at {panel.path}:"
        f" {', '.join(name for name, _ in CONTROL_BUTTONS)}"
        f" over {len(rows)} clip(s)"
    )
    return panel


def _add_transport(panel, td):
    """The row of buttons, and the one DAT that dispatches all of them.

    A container of its own rather than buttons sitting directly in the panel,
    because the panel now stacks two things vertically and these three go
    across. One container cannot be asked for both alignments.
    """
    from . import startup

    transport = startup.create(panel, td.containerCOMP, TRANSPORT_COMP)
    transport.nodeX, transport.nodeY = 0, 0
    startup.set_par(transport, "w", _panel_width())
    startup.set_par(transport, "h", BUTTON_HEIGHT)
    startup.set_menu(transport, "align", TRANSPORT_ALIGN)
    startup.set_par(transport, "spacing", PANEL_SPACING)
    startup.set_par(transport, "alignorder", 0)

    buttons = []
    for order, (name, label) in enumerate(CONTROL_BUTTONS):
        button = startup.create(transport, td.buttonCOMP, name)
        button.nodeX, button.nodeY = 0, -150 * order
        startup.set_par(button, "w", BUTTON_WIDTH)
        startup.set_par(button, "h", BUTTON_HEIGHT)
        startup.set_par(button, "buttontype", CONTROL_BUTTON_TYPE)
        startup.set_par(button, "label", label)
        startup.set_par(button, "fontsize", BUTTON_FONT_SIZE)
        # Align Order, not node position: the container lays its children out
        # by this number, and the network layout above is for reading.
        startup.set_par(button, "alignorder", order)
        buttons.append(button)

    executor = startup.create(transport, td.panelexecuteDAT, CONTROL_EXEC_NAME)
    executor.nodeX, executor.nodeY = 300, 0
    executor.text = CONTROL_CALLBACK
    startup.set_par(executor, "panels", " ".join(b.path for b in buttons))
    startup.set_par(executor, "panelvalue", CONTROL_PANEL_VALUE)
    startup.set_par(executor, "offtoon", True)
    startup.set_par(executor, "active", True)

    return transport


def _add_settings_row(panel, configuration, td):
    """Toggles and sliders for the four settings, each bound to its parameter.

    **Nothing here has a callback.** A transport button is a shim into
    `tdpy.player`, because pressing it *does* something; these are views of a
    value, and binding is what makes a view. The consequence is the phase's
    whole argument: a toggle clicked, a number typed into the Parameter COMP
    below, and a MIDI CC at Phase 7 all write the same parameter, and none of
    them has to tell the others.

    A control whose parameter is missing is left unbound rather than skipped -
    `settings.parameter()` has already said which one, and a slider that moves
    nothing is a more legible symptom than a gap in the row.
    """
    from . import settings, startup

    row = startup.create(panel, td.containerCOMP, SETTINGS_ROW_COMP)
    row.nodeX, row.nodeY = 0, -200
    startup.set_par(row, "w", _panel_width())
    startup.set_par(row, "h", SETTINGS_ROW_HEIGHT)
    startup.set_menu(row, "align", TRANSPORT_ALIGN)
    startup.set_par(row, "spacing", PANEL_SPACING)
    startup.set_par(row, "alignorder", 1)

    for order, setting in enumerate(settings.SETTINGS):
        if setting.kind == "toggle":
            control = _add_settings_toggle(row, setting, td)
        else:
            control = _add_settings_slider(row, setting, td)
        control.nodeX, control.nodeY = 0, -150 * order
        startup.set_par(control, "h", SETTINGS_ROW_HEIGHT)
        startup.set_par(control, "label", setting.label)
        startup.set_par(control, "alignorder", order)

        master = settings.parameter(configuration, setting.name)
        if master is not None:
            # value0 on both, and it means the same thing on both: the control's
            # own value. Binding it to the setting is what makes the control a
            # view rather than a second copy.
            startup.bind(control.par.value0, master)

    startup.report(
        f"[{startup.PACKAGE}] settings row at {row.path}: "
        + ", ".join(
            setting.node
            if setting.kind == "toggle"
            else f"{setting.node} {setting.minimum:g}-{setting.maximum:g}"
            for setting in settings.SETTINGS
        )
    )
    return row


def _add_settings_toggle(row, setting, td):
    """One toggle button, sized to match a transport button above it."""
    from . import startup

    toggle = startup.create(row, td.buttonCOMP, setting.node)
    startup.set_par(toggle, "w", SETTINGS_TOGGLE_WIDTH)
    startup.set_menu(toggle, "buttontype", SETTINGS_TOGGLE_TYPE)
    startup.set_par(toggle, "fontsize", BUTTON_FONT_SIZE * 0.6)
    return toggle


def _add_settings_slider(row, setting, td):
    """One horizontal slider, its ends set to the setting's range.

    The range is the part worth watching. `valuerange0l`/`valuerange0h` are
    read off the type stub rather than the shipped parameter help, which does
    not carry them, and their help text there is "Help Not Available" - so what
    they do is confirmed by dragging one, not by having read it. If dwell tops
    out at 1 rather than 60, this is the pair that did not do what their names
    say.
    """
    from . import startup

    slider = startup.create(row, td.sliderCOMP, setting.node)
    startup.set_par(slider, "w", _slider_width())
    startup.set_menu(slider, "slidertype", SETTINGS_SLIDER_TYPE)
    startup.set_par(slider, SLIDER_RANGE_LOW, setting.minimum)
    startup.set_par(slider, SLIDER_RANGE_HIGH, setting.maximum)
    # Clamped at both ends, so a drag cannot put a value outside the range the
    # slider draws. Typing a larger one into the Parameter COMP still can -
    # the parameter itself is clamped only at the bottom.
    startup.set_par(slider, "clampul", True)
    startup.set_par(slider, "clampuh", True)
    return slider


def _add_parameters(panel, configuration, td):
    """A Parameter COMP rendering the settings COMP's four custom parameters.

    The typed half of the surface, and it is built in - which is the answer to
    a gap the plan carried until the Phase 4b spike closed it. A Field COMP has
    no value parameter to bind, only a panel value, and panel values can be
    bind masters only; a Parameter COMP needs no binding at all, because it
    edits the parameters themselves.

    It draws each float as a slider *and* a numeric field, so the two halves of
    "editable in the control panel" arrive together and correctly ranged. The
    big sliders in the row above are the tactile version of the same values,
    not the only way to reach them.
    """
    from . import startup

    node = startup.create(panel, td.parameterCOMP, PARAMETER_COMP)
    node.nodeX, node.nodeY = 0, -400
    startup.set_par(node, "w", _panel_width())
    startup.set_par(node, "h", PARAMETER_HEIGHT)
    startup.set_par(node, "alignorder", 2)
    if configuration is not None:
        startup.set_par(node, "op", configuration.path)
    startup.set_par(node, "custom", True)
    # The built-in parameters of a base COMP are pages of clone, extension and
    # external .tox settings - nothing to do with the player, and enough of
    # them to bury the four that are.
    startup.set_par(node, "builtin", False)
    startup.set_par(node, "header", False)
    startup.set_par(node, "pagenames", False)
    startup.set_par(node, "labels", True)
    return node


def _add_clip_list(panel, container, rows, td):
    """The list of clips, and the DAT that keeps its highlight true.

    Rows is the playlist plus one for the header; columns come from
    `lister.COLUMNS`, so a column added there needs nothing changed here. The
    list draws nothing until its init callbacks have run, which is what the
    Reset pulse at the end is for - creating the node and setting Rows does
    not itself fill anything in.
    """
    from . import lister, startup

    callbacks = startup.create(panel, td.textDAT, CLIP_LIST_CALLBACK_DAT)
    callbacks.nodeX, callbacks.nodeY = 300, -600
    callbacks.text = CLIP_LIST_CALLBACK

    node = startup.create(panel, td.listCOMP, CLIP_LIST_COMP)
    node.nodeX, node.nodeY = 0, -600
    startup.set_par(node, "w", _panel_width())
    startup.set_par(node, "h", CLIP_LIST_HEIGHT)
    startup.set_par(node, "alignorder", 3)
    startup.set_par(node, "callbacks", callbacks.path)
    # One more row than there are clips: row 0 is the header, and locking it
    # keeps it visible once the list is long enough to scroll.
    startup.set_par(node, "rows", len(rows) + 1)
    startup.set_par(node, "cols", len(lister.COLUMNS))
    startup.set_par(node, "lockfirstrow", True)
    startup.set_par(node, "vscrollbar", True)
    # The columns are sized to the panel, so nothing ever needs scrolling
    # sideways - and a horizontal bar would eat a row's worth of height to
    # say so.
    startup.set_par(node, "hscrollbar", False)
    pulse(node, "reset")

    _add_clip_list_watch(panel, container, td)
    return node


def _add_clip_list_watch(panel, container, td):
    """A Parameter Execute DAT redrawing the highlight when the clip changes.

    Watching the player's `file` rather than having `player.next_clip()` update
    the list itself. The difference only shows up later, and shows up as a lie:
    a display pushed to by one caller goes stale the moment a second one exists
    - Phase 4's `advance()`, a MIDI note at Phase 7, or a path typed into the
    parameter by hand - and a playlist highlighting the wrong row is worse than
    one highlighting no row at all.

    Both `builtin` and `custom` are set explicitly. `file` is a built-in
    parameter, and a DAT watching only the custom ones would sit there looking
    correctly configured and never fire.
    """
    from . import startup

    player = container.op(PLAYER_TOP)
    if player is None:
        startup.report(
            f"[{startup.PACKAGE}] no {PLAYER_TOP} to watch - the clip list"
            " will not follow the transport"
        )
        return None

    executor = startup.create(panel, td.parameterexecuteDAT, CLIP_LIST_EXEC_NAME)
    executor.nodeX, executor.nodeY = 300, -750
    executor.text = CLIP_LIST_EXEC_CALLBACK
    startup.set_par(executor, "op", player.path)
    startup.set_par(executor, "pars", CLIP_LIST_WATCH_PAR)
    startup.set_par(executor, "builtin", True)
    startup.set_par(executor, "custom", False)
    startup.set_par(executor, "valuechange", True)
    startup.set_par(executor, "active", True)
    return executor


def pulse(operator, name):
    """Fire a pulse parameter, reporting rather than raising if it is missing.

    Not set_par: a pulse is an event, and assigning to its value is not the
    same as firing it.

    Public rather than private because `tdpy.player` fires the player's Cue
    Pulse on every clip change, and a second copy of these six lines is worse
    than a module that runs at build time owning one thing called at run time.
    """
    from . import startup

    parameter = getattr(operator.par, name, None)
    if parameter is None:
        startup.report(f"[{startup.PACKAGE}] no parameter {name!r} on {operator.path}")
        return None
    parameter.pulse()
    return parameter


def _add_player(container, rows, configuration, td):
    """One Movie File In TOP, playing, into a null.

    The null is not decoration. A Movie File In TOP is the operator most likely
    to be replaced - by a second one and a Switch TOP at Phase 6 - and anything
    connected to it directly would have to be rewired when that happens.

    Its speed is **bound** to the settings COMP's Speed rather than set here,
    which is the whole of what item 5 costs: a slider, a typed value and a MIDI
    CC all reach the player through one parameter, and no code carries a number
    from one to the other. Nothing else in this project may write `speed` on
    the player - a binding is two-way, so a stray `set_par` would not be
    overridden by the master, it would overwrite it.
    """
    from . import playlist, settings, startup

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

    # The end-of-file and cue policies are *configuration* rather than
    # behaviour: the player always loops and always cues in fractions, and the
    # two settings decide what is done about it. Set here so `tdpy.player` never
    # has to touch a menu - it writes a number into `cuepoint` and fires a
    # pulse, and both mean the same thing on every clip.
    startup.set_menu(player, "textendright", PLAYER_EXTEND_RIGHT)
    startup.set_menu(player, "cuepointunit", CUE_POINT_UNIT)

    speed = settings.parameter(configuration, settings.SPEED)
    if speed is not None:
        startup.bind(player.par.speed, speed)

    # TOPs draw their image on the node when the viewer flag is set, which is
    # all "on screen" needs to mean at this phase. A perform window is a Phase 8
    # concern, and would be one more thing to undo if it were built now.
    player.viewer = True
    out.viewer = True

    startup.report(
        f"[{startup.PACKAGE}] player at {out.path} <- "
        + (path or "no file - playlist is empty")
    )
    return out


def _add_cycle(container, configuration, td):
    """The two things that advance a clip with nobody pressing a button.

    **Neither of them decides anything.** The loop watcher calls
    `player.on_loop()` and the timer calls `player.on_dwell()`, and both of
    those read a setting and then either advance or do not. That is the same
    division the transport buttons are built on - a trigger is a shim, and the
    behaviour is a function in `tdpy.player` that a MIDI note could call just
    as well.

    There are now **two advance triggers, and whichever comes first wins.** At
    speed *s* and dwell *T* a clip consumes *s* x *T* seconds of media, so a random
    cue point will sometimes run off the end before the dwell expires - and the
    advance-at-end toggle is the answer to what happens when it does. That is
    why the timer, the cue and the end-of-file watcher are one phase rather
    than three jobs.

    Everything here is inside the build container and so goes with a rebuild.
    That is the right side of the line: the *settings* have to survive one and
    live outside, but the dwell clock restarting on a rebuild is not a loss.
    """
    from . import settings, startup

    player = container.op(PLAYER_TOP)
    if player is None:
        startup.report(
            f"[{startup.PACKAGE}] no {PLAYER_TOP} to drive - nothing will"
            " advance on its own"
        )
        return None

    # Info CHOP, because `loop_frame` is a channel the player publishes rather
    # than a parameter it carries. Nothing can bind to it and no Parameter
    # Execute DAT can watch it; an Info CHOP is how it is reached at all.
    info = _place(startup.create(container, td.infoCHOP, PLAYER_INFO_CHOP), 0, -400)
    startup.set_par(info, "op", player.path)
    # All rather than General, deliberately. General is documented as "the
    # channels of the specific OP type", which should be where `loop_frame`
    # lives - but All is documented as every set appended together, so it cannot
    # be the narrower one that leaves the channel out. The cost is channels
    # nothing reads; the alternative risks a watcher wired to a channel that
    # is not there, which fails silently.
    startup.set_menu(info, "infotype", INFO_TYPE)

    watcher = _place(
        startup.create(container, td.chopexecuteDAT, LOOP_EXEC_NAME), 250, -400
    )
    watcher.text = LOOP_CALLBACK
    startup.set_par(watcher, "chop", info.path)
    startup.set_par(watcher, "channel", LOOP_CHANNEL)
    # The rising edge only. Every other trigger is turned off explicitly rather
    # than left at its default, because a second one firing would advance twice
    # per loop and the symptom is a player that skips a clip now and then.
    startup.set_par(watcher, "offtoon", True)
    startup.set_par(watcher, "whileon", False)
    startup.set_par(watcher, "ontooff", False)
    startup.set_par(watcher, "whileoff", False)
    startup.set_par(watcher, "valuechange", False)
    startup.set_par(watcher, "active", True)

    callbacks = _place(
        startup.create(container, td.textDAT, DWELL_CALLBACK_DAT), 250, -550
    )
    callbacks.text = DWELL_CALLBACK

    timer = _place(
        startup.create(container, td.timerCHOP, DWELL_TIMER_CHOP), 0, -550
    )
    startup.set_menu(timer, "lengthtype", DWELL_LENGTH_TYPE)
    startup.set_menu(timer, "lengthunits", DWELL_LENGTH_UNITS)
    startup.set_par(timer, "cycle", True)
    startup.set_par(timer, "cyclelimit", False)
    startup.set_par(timer, "deferpars", DWELL_DEFER_PARS)
    startup.set_par(timer, "callbacks", callbacks.path)

    # Bound, not set. The dwell has a slider, a typed field and a MIDI CC at
    # Phase 7, and this is the fourth view of the same number rather than a
    # copy of it that something has to keep in step.
    dwell = settings.parameter(configuration, settings.DWELL)
    if dwell is not None:
        startup.bind(timer.par.length, dwell)

    # Running from the first frame. Whether it actually *counts* is the Play
    # parameter's business, and the watcher below owns that - a dwell of 0 is
    # the timer switched off rather than a cut every frame.
    pulse(timer, "start")

    executor = _place(
        startup.create(container, td.parameterexecuteDAT, DWELL_EXEC_NAME), 250, -700
    )
    executor.text = DWELL_EXEC_CALLBACK
    startup.set_par(executor, "op", configuration.path)
    startup.set_par(executor, "pars", settings.DWELL)
    # The mirror of the clip list's watcher, which sets these the other way
    # round: `file` is built in, and `Dwell` is custom. A DAT watching the
    # wrong one of the two sits there looking correctly configured and never
    # fires, which is why both are set explicitly in both places.
    startup.set_par(executor, "builtin", False)
    startup.set_par(executor, "custom", True)
    startup.set_par(executor, "valuechange", True)
    startup.set_par(executor, "active", True)

    startup.report(
        f"[{startup.PACKAGE}] cycle at {timer.path}: {LOOP_CHANNEL} watched"
        f" via {info.path}, dwell bound to {settings.DWELL}"
    )
    return timer


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
