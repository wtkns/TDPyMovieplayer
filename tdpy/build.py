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

**Phase 9.4 splits this file's output across two processes, and not this file.**
`build()` is the host's network - the windows, the panel, MIDI, the settings and
the Engine COMP - and `build_player()` is everything the engine runs, called
from `tdpy.engine.main()` inside the other process. The player half is the same
code it always was: those functions took the container and the settings COMP as
arguments already, and inside the engine the settings COMP *is* the component's
top level, whose custom parameters the host fills by expression. So the move is
a change of arguments rather than a rewrite, which is why they are still here
rather than in a module of their own.

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

#: The two Movie File In TOPs that decode clips, and the null TOP that
#: terminates the chain. Everything downstream connects to the null rather than
#: to a player, which is what let Phase 6 put a Cross TOP between them without
#: rewiring the window, and is why the null was built at Phase 2 for a chain
#: that did not need one yet.
#:
#: **Two, because one cannot crossfade with itself**, and because a single
#: player has to finish decoding a new file in the frame it is asked for it.
#: Two players means the incoming clip is opened, cued and held a whole dwell
#: before it is needed - which is the hitch Phase 6 existed to remove, removed
#: by the preload rather than by the blend.
#:
#: The order is load-bearing: index 0 is the Cross TOP's Input1 and index 1 is
#: its Input2, so a cross value of 0 shows PLAYER_TOPS[0] and 1 shows
#: PLAYER_TOPS[1]. `tdpy.player` indexes this tuple with the same number it
#: writes into the cross, which is what keeps "which player" from becoming a
#: second fact that could disagree with the first.
PLAYER_TOPS = ("playerA", "playerB")
OUT_TOP = "out"

#: The Cross TOP blending them. Its help: "when Cross = 0, Input1 is output;
#: when Cross = 1, Input2 is output" - read out of the type stub at
#: `bin/Lib/tdi/ops/tops/crossTOP.py` rather than assumed, since the Phase 6
#: plan had named a Switch TOP, which hard-cuts and has no blend at all.
#:
#: Its `cross` is an **expression**, not a value anything writes per frame. See
#: CROSS_EXPR for what the expression is and why the fade is shaped this way.
CROSS_TOP = "cross"

#: The Constant CHOP holding the two ends of the current fade, and the names of
#: its two channels. This is the whole of the fade's state, it lives in the
#: network rather than in Python, and it is written twice per cut.
#:
#: **Two channels rather than one.** `target` alone would do for a fade that
#: always runs to completion from a settled start - but `start` is what makes
#: three other cases fall out with no special handling. A fade interrupted by a
#: next press starts from wherever the blend had got to rather than snapping.
#: A hard cut is `start` and `target` written to the same number, so nothing
#: has to branch on whether a fade is happening. And a fresh build is both at 0,
#: which is correct **whatever the fade timer's fraction happens to hold** -
#: worth having, because `timer_fraction` at a timer that has never run is a
#: thing this project would otherwise have to be right about.
FADE_STATE_CHOP = "fadeState"
FADE_START_CHANNEL = "start"
FADE_TARGET_CHANNEL = "target"

#: The Timer CHOP supplying the ramp between those two ends, and the channel it
#: is read through. `timer_fraction` runs 0 to 1 over the timer's length, which
#: is the whole reason a Timer CHOP is used here rather than a Lag or Filter
#: CHOP: the Lag CHOP's own help describes its lag as "approximately the time
#: that the output follows 90% of a change", and a fade asked to take a fifth of
#: the dwell should take a fifth of the dwell.
#:
#: The channel name is in `libTD.dll` alongside `timer_seconds` and
#: `timer_active`, and is documented on Timer_CHOP.htm in the install's own
#: OfflineHelp - the same two places `loop_frame` was confirmed and
#: `cycle_pulse` was refused.
FADE_TIMER_CHOP = "fade"
FADE_CALLBACK_DAT = "fade_callbacks"
FADE_FRACTION_CHANNEL = "timer_fraction"

#: What drives the Cross TOP. Linear interpolation between the fade's two ends,
#: evaluated every frame by TouchDesigner rather than by a Python callback
#: pushing a number - which is the same reason the clip list's highlight is an
#: expression over the player's `file` rather than something `_step` remembers
#: to update.
#:
#: At rest `start` equals `target`, so the fraction drops out of the arithmetic
#: entirely and the expression answers that value no matter what the timer is
#: doing. `player.on_fade_done()` is what makes that true at the end of every
#: fade, and it is why this needs no clamp: an expression that only matters
#: while the two ends differ cannot overshoot once they are equal.
#:
#: Relative paths, because all three operators are siblings inside the build
#: container - which also means the expression survives the container being
#: created somewhere other than /project1.
#:
#: A template rather than a finished string, because the audio mixer needs the
#: **same arithmetic** from a node one level deeper, where a bare `fadeState`
#: resolves to nothing. `{prefix}` is empty for the Cross TOP's own sibling
#: reference and the mixer's containing path for the gains. Generating both
#: from one template is the point: two spellings of where the fade has got to
#: could disagree, and the symptom would be sound that leads or lags the
#: picture by an amount nobody wrote down.
CROSS_EXPR_TEMPLATE = (
    "op('{prefix}" + FADE_STATE_CHOP + "')['" + FADE_START_CHANNEL + "']"
    " + (op('{prefix}" + FADE_STATE_CHOP + "')['" + FADE_TARGET_CHANNEL + "']"
    " - op('{prefix}" + FADE_STATE_CHOP + "')['" + FADE_START_CHANNEL + "'])"
    " * op('{prefix}" + FADE_TIMER_CHOP + "')['" + FADE_FRACTION_CHANNEL + "']"
)

CROSS_EXPR = CROSS_EXPR_TEMPLATE.format(prefix="")

#: The mixer, and the base COMP it all lives in.
#:
#: A COMP of its own inside the build container, rather than fourteen more
#: operators loose beside the players. It is a baseCOMP and not a containerCOMP
#: because nothing in it is a panel widget - the rule that a widget must live
#: in a panel-type COMP is about widgets, and these are CHOPs.
#:
#: It buys one thing beyond tidiness: the whole mixer is one node to bypass,
#: one node to look inside, and one node whose absence says the audio was never
#: built. It costs the gain expressions their relative paths, which is why they
#: are baked absolute at build time - see `tdpy.audio.parameter_expression`.
AUDIO_COMP = "audio"

#: One strip per player, in `PLAYER_TOPS` order. Each name below is suffixed
#: with the strip's letter, so the operators read `audioA`, `leftA`, `nameLA`
#: and so on - which is the same A/B the players and the Cross TOP use, and
#: the reason the suffix is taken from `PLAYER_TOPS` rather than written twice.
AUDIO_STRIP_SUFFIXES = tuple(name[-1] for name in PLAYER_TOPS)

#: The Audio Movie CHOP, which plays the audio of a movie a Movie File In TOP
#: is already decoding. Its `moviefileintop` parameter takes the TOP's path -
#: so the audio follows whatever clip the player is on with nothing telling it,
#: in the same way the clip list's highlight does.
AUDIO_MOVIE_PREFIX = "audio"

#: The two Math CHOPs per strip that do the actual mixing, and the two Rename
#: CHOPs that name their output.
#:
#: **One Math CHOP does both jobs.** `chanop = avg` collapses the clip's stereo
#: pair to one channel, and the same node's `gain` carries the level, the pan
#: law and the fade share. The Math CHOP's help gives the order the four stages
#: run in - Channel Pre OP, Combine Channels, Combine CHOPs, Channel Post OP -
#: and the Mult-Add page's gain is applied after them, so the sum happens first
#: and the gain scales the summed result. That order is why this is one node
#: rather than a mono node feeding a gain node.
AUDIO_LEFT_PREFIX = "left"
AUDIO_RIGHT_PREFIX = "right"
AUDIO_NAME_LEFT_PREFIX = "nameL"
AUDIO_NAME_RIGHT_PREFIX = "nameR"
AUDIO_STRIP_PREFIX = "strip"

#: The sum of both strips, and the device it goes to.
AUDIO_MIX_CHOP = "mix"
AUDIO_OUT_CHOP = "audioOut"

#: Combine Channels: Average. **Not Add.** `add` is L+R, which clips on
#: correlated material, and most music is correlated. `avg` is (L+R)/2 and
#: cannot, at the cost of sitting 6 dB below a hard sum - which the level
#: control makes back. Both tokens are in the Math CHOP's own help.
AUDIO_MONO_OP = "avg"

#: Combine CHOPs: Add, matching channels by index. The two strips are the same
#: two channel names in the same order by the time they reach here, so name and
#: index agree; index is set because it is the one that says what is meant.
AUDIO_SUM_OP = "add"
AUDIO_SUM_MATCH = "index"

#: What the Rename CHOPs match and what they write.
#:
#: A dedicated Rename CHOP rather than the rename fields on each Math CHOP's
#: Common page, and the reason is that the install disagrees with itself about
#: what those are called: `Math_CHOP.htm` names them `commonrenamefrom` and
#: `commonrenameto`, while the type stub at `bin/Lib/tdi/ops/chops/mathCHOP.py`
#: names them `renamefrom` and `renameto`. The Rename CHOP's own parameters are
#: `renamefrom`/`renameto` in **both**, so this is the spelling that is not a
#: coin flip. Two nodes per strip is the price.
#:
#: `*` matches whatever single channel the average produced, whose name is not
#: documented anywhere and does not need to be.
AUDIO_RENAME_FROM = "*"

#: Cook Every Frame on the Audio Device Out CHOP. Its help: "This should be
#: checked on at all times when outputing audio." Set rather than left to a
#: default, because the failure is silence with nothing in the log.
AUDIO_OUT_COOK_ALWAYS = True

#: Length Type and Units for the fade timer, same tokens as the dwell's. The
#: length itself is **not** bound: it is `Dwell * Fade`, a product of two
#: parameters rather than a view of one, and it only has to be right at the
#: instant a fade begins - so `player._step` computes it and writes it. Binding
#: would have needed a bindExpr helper in `startup.py`, which is a file this
#: project does not own.
FADE_LENGTH_TYPE = "fixed"
FADE_LENGTH_UNITS = "Seconds"

#: Outputs the `timer_fraction` channel at all. Set explicitly rather than
#: trusted to a default, because the failure is invisible from the outside: the
#: expression above would evaluate against a channel that is not there, and the
#: cross would sit wherever it last was.
FADE_OUT_FRACTION = True

#: `onDone`, the callback that fires when the timer reaches its length -
#: signature from the install's own
#: `bin/Lib/tdutils/DATScripts/timerCHOP_callbacks.py`, where it is documented
#: "Called when the timer is done."
#:
#: It does two things, both of which are `tdpy.player`'s to decide: it settles
#: the fade's start onto its target, and it hands the now-hidden player the
#: clip after this one so that player has the whole of the next dwell to open
#: and decode it.
#:
#: It refreshed the controller's lamps as well until 9.4. The lamps are on a
#: device the host owns and this callback now runs in the engine, which cannot
#: reach it - so the fade no longer pushes them, and at 9.5 the host reads the
#: same fact off the state CHOP's `live` channel instead.
FADE_CALLBACK = '''# Generated by tdpy/build.py - edits here are overwritten.


def onDone(timerOp, segment, interrupt):
    import tdpy.player

    tdpy.player.on_fade_done()
'''

#: Which playlist row to load when the deck cannot say. Phase 4 made the deck
#: the answer and `_first_clip` asks it, so this is now only the fallback for an
#: empty playlist - kept as a named number rather than a literal 0, because the
#: case it covers is the one nobody looks at.
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
#: `engineProgram` was 9.3's single Null for the engine's picture, replaced at
#: 9.4 by one Null per declared output, each named as the output is.
#: Removable once no session or saved .toe can still be carrying one.
LEGACY_NAMES = ("window", "bindSpike", "bindSpikeWindow", "engineProgram")

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
VIDEO_WINDOW_DISPLAY = 1

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
CONTROL_WINDOW_DISPLAY = 0

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

#: The mixer's band, drawn as a second settings row under the first. One row
#: per custom page, which is what `settings.Setting.page` decides - and the
#: reason there are two rows rather than one long one is arithmetic:
#: `_slider_width` shares the panel between the sliders on a row, so seven
#: sliders in a row would be seven thin sliders.
AUDIO_ROW_COMP = "audioRow"
AUDIO_ROW_HEIGHT = SETTINGS_ROW_HEIGHT

#: The panel's rows, top to bottom. A row's position in this tuple **is** its
#: `alignorder`, so inserting a row is inserting a name here rather than
#: renumbering every row below it by hand - which is what the previous version
#: needed, and what the comment above the diagnostics strip was compensating
#: for by naming the clip list's number in prose.
PANEL_ROWS = (
    "transport",
    "settings",
    "audio",
    "parameters",
    "cliplist",
    "diagnostics",
)

#: Toggle Down: on when pushed, off when pushed again. These are values, not
#: actions, which is the whole difference between this row and the transport
#: above it - a transport button *does* something and springs back, a toggle
#: *is* something until it is changed.
SETTINGS_TOGGLE_TYPE = "toggledown"

#: Slider U - a horizontal slider tracking the u panel value. The other two are
#: `sliderv` and `slideruv`; all three are named in the Slider COMP's help.
SETTINGS_SLIDER_TYPE = "slideru"

#: The toggles' width; the sliders divide whatever is left of the row.
#:
#: This was `BUTTON_WIDTH`, so a row of toggles lined up with the transport
#: above it. That alignment stopped being reachable when the Player row went to
#: three toggles - at a transport button's width they leave 320px for four
#: sliders, which is 80px each and not a control anybody can set a dwell with.
#: Narrower toggles put the sliders back to 125px. A toggle needs less width
#: than a transport button in any case: it carries a two-word label and a
#: state, not a target for a hand moving quickly.
SETTINGS_TOGGLE_WIDTH = 120

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

#: The diagnostics strip: one Text COMP per player, reading that player's Info
#: CHOP, at the bottom of the control panel. Built 2026-09-12 because the frames
#: being dropped at a cut had two plausible causes and no measurement.
#:
#: **Every channel below is a real Movie File In TOP channel**, and establishing
#: that took more than grepping `libTD.dll`. The obvious name for the symptom,
#: `dropped_frames`, *is* in the binary - and belongs to the Video Device Out
#: TOP. The Movie File In TOP's own list is on `Point_File_In_TOP.htm` in the
#: install's OfflineHelp, which enumerates the shared file-reading channel set
#: (it contains `loop_frame`, which is how it was identified as the right list);
#: the Movie File In TOP's page names them only in prose. So the binary says a
#: name exists somewhere and the help says which operator it is on, and this
#: needed both.
#:
#: `pre_read_misses` is the one that answers the question. The read-ahead
#: failing to keep up is precisely what a random cue into the middle of a long
#: GOP causes, and it counts the event rather than its symptom.
DIAGNOSTICS_COMP = "diagnostics"
DIAGNOSTICS_HEIGHT = 90
DIAGNOSTICS_FONT_SIZE = 20

#: Label and decimals for the two readings that cross, keyed by which `link`
#: channel pair they come from. A deck's own channel name is taken from that
#: pair by index, so this table says what a reading is *called on the panel* and
#: nothing about where it lives.
#:
#: **Four readings were dropped here, and they are not lost.** The strip drew
#: `hardware_decode`, `last_frame_decode_time`, `last_gpu_upload_time` and
#: `has_decode_errors` off each player's Info CHOP while the players were in
#: this process. Those channels still exist, on the Info CHOPs inside the
#: engine; what does not exist is a way for the host to read them, since
#: `link.STATE_CHANNELS` carries only these two across. Adding one back means
#: adding a channel there and a block to the engine's state CHOP.
#:
#: `pre_read_misses` is the one that answers the question the strip was built
#: for. The read-ahead failing to keep up is precisely what a random cue into
#: the middle of a long GOP causes, and it counts the event rather than its
#: symptom.
DIAGNOSTIC_READINGS = (
    ("DECK_MISSES", "miss", 0),
    ("DECK_BUFFER", "buf", 0),
)


def _diagnostics_expression(label, chop_path, index):
    """The Text COMP `text` expression for one deck. Returns the string.

    **The channels are named in the expression rather than read by a function
    it calls**, and that is not a style preference. TouchDesigner tracks a
    parameter expression's dependencies by what the expression references, so a
    tidier `tdpy.engine.state()` reading the same channels inside itself would
    leave the readout to cook whenever it felt like it - which for a diagnostic
    is worse than not having one, because a stale number reads as a
    measurement. It is also why the strip needs no watcher while the clip list
    does: an expression is pulled, and a List COMP's rows are painted.

    An f-string, because a parameter expression is an ordinary Python
    expression. The path is baked in at build time from the Null's real `path`,
    so nothing here depends on where the network was built - and since that
    Null is the one `engine.output` finds, a player on another machine changes
    nothing about this.

    **`.eval()` is not decoration.** `op(chop)['channel']` answers a
    `td.Channel`, not a number, and formatting one raises *"unsupported format
    string passed to td.Channel.__format__"* - which is what the first version
    of this did on both readouts. The Channel class documents
    `eval(index) -> float`, evaluating "at the current index based on the
    current time" when given no argument, and that is the number wanted here.
    """
    from . import link

    parts = " ".join(
        f"{name} {{op({chop_path!r})[{getattr(link, pair)[index]!r}].eval():.{places}f}}"
        for pair, name, places in DIAGNOSTIC_READINGS
    )
    return f'f"{label}  {parts}"'


#: The Panel Execute DAT watching every button, and the shim it holds. One DAT
#: for all three: `panelValue.owner` is the panel that was clicked, so the
#: dispatch is a dictionary lookup in reloadable Python rather than three
#: near-identical DATs generated from here.
#:
#: **The shim now names the other process rather than the transport.** The
#: buttons are in the host and the transport is in the engine, so a press pulses
#: the command's parameter on the Engine COMP and `tdpy.engine.on_command` calls
#: `player.command` at the far end. The button still knows nothing but its own
#: name, which is what kept this dispatch worth having across the move.
CONTROL_EXEC_NAME = "controls_exec"
CONTROL_PANEL_VALUE = "state"
CONTROL_CALLBACK = '''# Generated by tdpy/build.py - edits here are overwritten.


def onOffToOn(panelValue):
    import tdpy.engine

    tdpy.engine.send(panelValue.owner.name)
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

#: **The highlight's watchers are gone at 9.4, and the highlight with them.**
#: They were two Parameter Execute DATs watching each player's `file`, so that
#: the list followed what was on screen regardless of what put it there. Both
#: players are in the engine now and a host DAT cannot watch a parameter in
#: another process, so the mechanism is not adjusted here - it is replaced at
#: 9.5 by a watcher on the state CHOP's `row_a` and `row_b`, which carry the
#: same fact across. The rule that made it worth building survives the move:
#: the display is pulled from what the player is doing, never pushed to.

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
#: One of each per player, in the same order as PLAYER_TOPS, because both
#: players are always decoding and either can reach its own end. Only the one
#: on screen should advance anything - the hidden player runs out constantly
#: while it waits - so the callback says which player looped and
#: `player.on_loop` refuses the one that is not showing.
PLAYER_INFO_CHOPS = ("playerAInfo", "playerBInfo")
LOOP_EXEC_NAMES = ("loopA_exec", "loopB_exec")
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

    tdpy.player.on_loop(channel.owner.name)
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

#: The two Parameter Execute DATs that decide whether the dwell timer counts,
#: and the player parameter the second of them watches. The first watches the
#: settings COMP's Dwell, whose name comes from `settings.DWELL` rather than
#: being spelled again here so a rename is caught by the interpreter.
#:
#: **Two inputs, because two things stop the timer.** `Dwellon` is the switch -
#: the dwell itself is a duration and no longer carries a mode at the bottom of
#: its range - and a paused clip is not counted down - pause
#: means hold this frame, and cutting away from a held frame would make pause
#: mean something narrower than it reads. Neither is a binding: both are
#: interpretations of a parameter rather than views of one, and a binding
#: mirrors a value without having an opinion about it.
#:
#: Two DATs rather than one because they watch different operators. They run the
#: same callback, which recomputes the answer from both inputs rather than
#: setting the half it knows about - so it does not matter which of them fired,
#: and a third input later is a third watcher and no new logic.
#: One Play watcher per player now, for the reason there is one clip-list
#: watcher per player: pause writes both, and whichever of them the dwell is
#: reading has to be the one on screen. The callback is unchanged and still
#: recomputes from scratch, so three watchers need no more logic than two did -
#: which was the stated reason for recomputing rather than setting, arriving
#: earlier than expected.
DWELL_EXEC_NAME = "dwell_exec"
DWELL_PLAY_EXEC_NAMES = ("dwellA_play_exec", "dwellB_play_exec")
PLAYER_PLAY_PAR = "play"
#:
#: The lamp refresh went with the move to the engine, for the reason it left
#: FADE_CALLBACK: the controller is on the host's cable and this runs in the
#: other process.
DWELL_EXEC_CALLBACK = '''# Generated by tdpy/build.py - edits here are overwritten.


def onValueChange(par, prev):
    import tdpy.player

    tdpy.player.refresh_dwell()
    return
'''


#: The Constant CHOP the engine publishes its state through, and the Parameter
#: Execute DATs that keep the two row channels true.
#:
#: **Most of it is expressions, and three channels are written.** A channel that
#: is a reading of an operator - which deck the cross is settling on, whether a
#: player is playing, what its decoder is doing - is an expression naming that
#: operator, so TouchDesigner cooks it when the thing it reports changes. That
#: is the same rule the Cross TOP's value and the mixer's gains are built on,
#: and the diagnostics strip is where the cost of breaking it was learned: a
#: channel computed inside a Python function would cook when it felt like it,
#: and a stale number does not look broken.
#:
#: `link.PUSHED` is the rest - the seed, which is a Python global that nothing
#: in a network can watch, and the two row numbers, which are a lookup over the
#: playlist table rather than a value sitting on an operator. Those three are
#: written by `player.publish_state()`.
STATE_CHOP = "state"
STATE_EXEC_NAMES = ("stateA_exec", "stateB_exec")
STATE_WATCH_PAR = "file"

#: The rows follow each player's `file`, which is the parameter the host's clip
#: list used to watch from the other side of the boundary. Same trigger, same
#: fact, one process over - what changed is that it writes a number into a
#: channel instead of repainting a list.
STATE_EXEC_CALLBACK = '''# Generated by tdpy/build.py - edits here are overwritten.


def onValueChange(par, prev):
    import tdpy.player

    tdpy.player.publish_state()
    return
'''


MIDI_IN_DAT = "midi_in"
MIDI_OUT_CHOP = "midi_out"
MIDI_CALLBACK_DAT = "midi_callbacks"

#: Sense and timing messages are a device saying it is still there, several
#: times a second. Left on they would be most of what the learn pass reports
#: and all of what the log fills with.
MIDI_SKIP_SENSE = True
MIDI_SKIP_TIMING = True

#: The signature is `onReceiveMIDI(dat, rowIndex, message, channel, index,
#: value, input, byteData)`, from the stock callback file at
#: `bin/Lib/tdutils/DATScripts/midiinDAT_callbacks.py` rather than from the
#: wiki's prose. Written without the annotations that file carries: the names
#: in them are TouchDesigner's injected globals, and a shim that does not
#: depend on them is one less thing to be wrong about.
#:
#: `input` is True for a received event, which is the only kind this project
#: has - it sends nothing - but it is passed through rather than dropped, so
#: the filtering decision stays in `tdpy.midi` with every other decision.
MIDI_CALLBACK = '''# Generated by tdpy/build.py - edits here are overwritten.


def onReceiveMIDI(dat, rowIndex, message, channel, index, value, input, byteData):
    import tdpy.midi

    if not input:
        return
    tdpy.midi.on_message(message, channel, index, value)
    return
'''

#: Phase 9's Engine COMP, and what the host keeps beside it. All of these sit
#: beside the build container rather than in it, like the windows: `build()`
#: destroys its container, and an Engine COMP in there would quit and relaunch
#: its whole process on every rebuild instead of reloading the component.
#:
#: The Nulls that receive the engine's outputs are beside it too, and they are
#: **named exactly as the outputs are** - `link.OUTPUTS` spells each one once
#: and the host's node, the engine's Out operator and the connector's label all
#: come from that spelling. The 9.3 Null was called `engineProgram`, which is
#: why that name is retired below rather than simply dropped.
ENGINE_COMP = "engine"
ENGINE_CALLBACK_DAT = "engine_callbacks"

#: Asset Paths: relative paths inside the component resolve against the `.toe`
#: rather than against the `.tox`, which is the default.
#:
#: The playlist stores every clip relative to the repository root, which is
#: where the .toe sits, and the .tox is generated into `out/` - so on the
#: documented default those paths would be looked for inside `out/media/`.
#: Relative paths are the project's rule (a clone has to play on another
#: machine), so the setting moves rather than the paths. The failure that
#: reasoning predicts has not been watched happen: the first run with this set
#: correctly played, which is evidence the setting is right and not evidence
#: about what the default would have done.
#:
#: **The token is `toe`, and the help says `project`.** `Engine_COMP.htm`'s
#: parameter table gives this menu's items as `project` and `comp`; the live
#: parameter has `toe` and `tox`, which is what `set_menu` reported when it
#: refused the documented one on 2026-09-19. The same disagreement the Math
#: CHOP's rename parameters have, caught the same way - and this is the case
#: `set_menu` exists for, because a menu item that is simply wrong would have
#: left the default in place and every clip unfound, with nothing said.
ENGINE_ASSET_PATHS = "toe"

#: The Parameter Execute DAT inside the engine that turns a pulsed parameter
#: back into a transport command, and the shim it holds.
#:
#: **`pars` is `*` rather than the list of commands.** The help for that
#: parameter says only "Specify which parameter(s) to monitor" and does not give
#: the syntax for naming several, so a space-separated list would be a guess
#: that looks like a configuration. Every custom parameter is watched instead
#: and only `onpulse` is enabled - and the only custom parameters that can be
#: pulsed are the commands, since the settings are floats and toggles. A name
#: that reaches `engine.on_command` and means nothing is reported there.
ENGINE_COMMAND_EXEC = "commands_exec"
ENGINE_COMMAND_PARS = "*"
ENGINE_COMMAND_CALLBACK = '''# Generated by tdpy/build.py - edits here are overwritten.


def onPulse(par):
    import tdpy.engine

    tdpy.engine.on_command(par.name)
    return
'''

#: The Base COMP the `.tox` is generated from. It exists only between being
#: built and being saved, so that nothing in it ever runs in the host.
ENGINE_SOURCE = "engineSource"
ENGINE_BOOTSTRAP_DAT = "bootstrap"

#: Where the generated `.tox` is written, relative to the project root. Git
#: ignores it: it is rebuilt on every build, and a committed copy would be a
#: second record of what `tdpy/engine.py` says.
ENGINE_TOX = "out/engine.tox"

#: The Engine COMP's callbacks. `onReady(engineComp)` is copied from the
#: install's `bin/Lib/tdutils/DATScripts/engineCOMP_callbacks.py`, "Called when
#: the Engine COMP is ready". The outputs are wired from here rather than at
#: build time because they come from the loaded component - on a first launch
#: the build finishes before the engine has loaded anything to wire.
ENGINE_CALLBACK = '''# Generated by tdpy/build.py - edits here are overwritten.


def onReady(engineComp):
    from tdpy import build

    build.wire_engine(engineComp)
    return
'''


def build():
    """Create the host's network, replacing whatever the last build left behind.

    Clear-and-rebuild rather than converging on the existing network: it is the
    simpler of the two options and makes a re-run predictable. Anything created
    outside `BUILD_ROOT` is left alone, so hand-made work sitting next to it
    survives.

    **This is the host half only.** Since 9.4 the playlist, both players, the
    fade, the dwell and the mixer are built by `build_player()` in the engine's
    process; what is left here is the window, the audio device, MIDI, the panel
    and the settings the engine reads. The Engine COMP is not wrapped in a
    try/except any more, and that is the whole difference the move makes to this
    function's shape: at 9.3 a fault there cost a probe beside a working player,
    and now it costs the player - so it is a failed build, which
    `startup.build()` reports with its traceback.
    """
    # TouchDesigner injects op(), the operator classes and the rest of its
    # globals into DAT scripts, expressions and the textport - not into modules
    # imported from disk. From here they come off the td module instead.
    import td

    from . import lister, link, midi, settings, startup

    parent = td.op(BUILD_PARENT) or td.op("/")

    previous = parent.op(BUILD_ROOT)
    if previous is not None:
        previous.destroy()

    _drop_legacy(parent)

    # Before the container, and outside it. The panel binds its controls to
    # these parameters and the Engine COMP's own parameters are expressions over
    # them, so they have to exist before either is built - and they have to
    # survive the destroy above, which is why they are not in the container.
    configuration = settings.ensure(parent, td)

    # startup.create rather than parent.create throughout: the latter appends a
    # digit rather than fail when it will not use a name, and every name here is
    # referred to again - by the log, by the next phase, or by a wire.
    container = startup.create(parent, td.baseCOMP, BUILD_ROOT)
    container.nodeX, container.nodeY = 0, 0

    # **The host does not scan `media/`.** The folder belongs to the process
    # that plays from it, which sends its table across as an output - so there
    # is one scan, on the machine holding the files, and the clip list draws
    # what that machine says it found rather than a second opinion about the
    # same folder.

    # The device table before the listener that reads it: the MIDI In DAT hears
    # nothing without a device mapping, and this is where one comes from.
    _ensure_device_table(td)
    _add_midi(container, td)

    # Before the window and the audio device, both of which take an engine
    # output as their source.
    _add_engine(parent, td)
    _add_audio_out(parent, td)
    # Named rather than assumed: a window built against a Null that is not
    # there would raise an AttributeError on `None.path`, which says nothing
    # about what went wrong.
    picture = parent.op(link.output("program_video").name)
    if picture is None:
        startup.report(
            f"[{startup.PACKAGE}] no {link.output('program_video').name}"
            f" under {parent.path} - there is nothing to put on the display"
        )
    else:
        _add_video_window(parent, picture, td)

    panel = _add_control_panel(parent, configuration, td)
    _add_control_window(parent, panel, td)
    # After the panel, because they call into it - and in the container, so a
    # rebuild replaces them rather than leaving two watchers on one channel.
    _add_state_watch(container, parent, td)

    # After the panel exists, so the list has whatever the engine has already
    # sent rather than waiting for the next change. On a first launch that is
    # nothing, and the playlist watcher fills it in when the table arrives.
    lister.resize()

    # A launch is not a change, so no watcher fires and the controller's LEDs
    # would sit at whatever the device powered up with until the first cut.
    midi.refresh_lights()

    return container


def build_player(root):
    """Build the player under `root`, inside the engine. Returns the container.

    Called by `tdpy.engine.main()` on every load and reload of the component.
    Everything here ran in the host until 9.4 and none of it changed in the
    move: each function already took the container it builds into and the COMP
    carrying the settings, and inside the engine that COMP is `root` itself -
    the component's top level, whose custom parameters the host fills with
    expressions over its own settings.

    The container is destroyed and rebuilt whole, for the reason `build()` does
    it: a re-run should be predictable, and the Out operators and the bootstrap
    that sit outside it are the component's interface rather than its network.
    """
    import td

    from . import player, startup

    previous = root.op(BUILD_ROOT)
    if previous is not None:
        previous.destroy()

    container = startup.create(root, td.baseCOMP, BUILD_ROOT)
    container.nodeX, container.nodeY = 0, 0

    table = _place(startup.create(container, td.tableDAT, PLAYLIST_DAT), 0, 0)
    rows = _fill_playlist(table, td)
    _, players = _add_player(container, rows, root, td)
    _add_cycle(container, root, td)
    # After the players, which it reads, and after the fade's state and timer,
    # which its gains reference: an expression written against an operator that
    # does not exist yet holds the error even once the operator arrives. Both
    # are built inside `_add_player`.
    _add_audio(container, players, root, td)
    _add_commands(container, root, td)
    # Last of the network, because every computed channel on it names something
    # built above - the players, the fade, the Info CHOPs.
    _add_state(container, td)

    # The dwell's watchers only fire when a parameter *changes*, and a load is
    # not a change - so the timer would sit running with whatever Play it was
    # created holding until somebody touched the slider or pressed pause. Asking
    # the same function they ask is how the state is right on the first frame,
    # and there is only one place that decides it either way.
    player.refresh_dwell()
    # Same reasoning as the dwell, for the three channels nothing computes: the
    # row watchers fire on a change and a load is not one, so the rows and the
    # seed would sit at ABSENT until the first cut.
    player.publish_state()
    return container


def state_expressions(container_path=""):
    """The expression for each computed state channel, keyed by channel name.

    Pure, so the arithmetic the host reads its surfaces off can be checked
    without a network. `container_path` is prefixed onto every operator name,
    empty for a sibling of the state CHOP - the same shape `CROSS_EXPR_TEMPLATE`
    takes, and for the same reason: the mixer needed the fade's arithmetic from
    one level down, and a second spelling of it could disagree.

    **The fade's three channels are derived here the way `player` derives them**,
    and from the same two numbers: `live` is which end the cross is settling on,
    `fading` is the two ends differing by more than a step of 8-bit blend, and
    `cross` is the ramp between them - `CROSS_EXPR` itself rather than a reading
    of the Cross TOP's parameter, which is a frame stale. `FADE_SETTLED` is read
    off `player` rather than written again, since a tolerance spelled twice is
    two tolerances.
    """
    from . import link, player

    fade = f"op('{container_path}{FADE_STATE_CHOP}')"
    start = f"{fade}['{FADE_START_CHANNEL}']"
    target = f"{fade}['{FADE_TARGET_CHANNEL}']"

    expressions = {
        "live": f"1 if {target} >= 0.5 else 0",
        "fading": f"1 if abs({target} - {start}) > {player.FADE_SETTLED!r} else 0",
        "cross": CROSS_EXPR_TEMPLATE.format(prefix=container_path),
    }
    for index, name in enumerate(PLAYER_TOPS):
        info = f"op('{container_path}{PLAYER_INFO_CHOPS[index]}')"
        expressions[link.DECK_PLAYING[index]] = (
            f"1 if op('{container_path}{name}').par.play.eval() else 0"
        )
        expressions[link.DECK_MISSES[index]] = f"{info}['pre_read_misses']"
        expressions[link.DECK_BUFFER[index]] = f"{info}['num_pre_read_frames']"
    return expressions


def _add_state(container, td):
    """The Constant CHOP carrying every state channel. Returns it.

    One block per name in `link.STATE_CHANNELS`, in that order, because the
    engine writes the pushed three by index and the host reads all twelve by
    name. Built after the players, the fade and the Info CHOPs, since every
    computed channel names one of them and an expression written against an
    operator that does not exist yet keeps the error afterwards.
    """
    from . import link, startup

    state = _place(startup.create(container, td.constantCHOP, STATE_CHOP), 500, -900)
    # The Constant CHOP ships with fewer blocks than this needs. `seq.const` is
    # the sequence of them, and `numBlocks` was seen taking a new length in
    # spikes/engine_spike.py on 2026-09-14.
    state.seq.const.numBlocks = max(state.seq.const.numBlocks, len(link.STATE_CHANNELS))

    expressions = state_expressions()
    for index, channel in enumerate(link.STATE_CHANNELS):
        startup.set_par(state, f"const{index}name", channel)
        expression = expressions.get(channel)
        if expression is None:
            # A pushed channel starts absent rather than at 0, which is a real
            # row and a real seed. `player.publish_state` writes the truth a
            # moment later, at the end of the build.
            startup.set_par(state, f"const{index}value", link.ABSENT)
            continue
        _set_expression(getattr(state.par, f"const{index}value"), expression, startup)

    for index, (name, exec_name) in enumerate(zip(PLAYER_TOPS, STATE_EXEC_NAMES)):
        player_top = container.op(name)
        if player_top is None:
            continue
        executor = _place(
            startup.create(container, td.parameterexecuteDAT, exec_name),
            750, -900 - index * 150,
        )
        executor.text = STATE_EXEC_CALLBACK
        startup.set_par(executor, "op", player_top.path)
        startup.set_par(executor, "pars", STATE_WATCH_PAR)
        # `file` is built in, and a DAT watching only the custom parameters
        # would sit there looking correctly configured and never fire.
        startup.set_par(executor, "builtin", True)
        startup.set_par(executor, "custom", False)
        startup.set_par(executor, "valuechange", True)
        startup.set_par(executor, "active", True)

    startup.report(
        f"[{startup.PACKAGE}] state at {state.path}: {len(link.STATE_CHANNELS)}"
        f" channels, {', '.join(link.PUSHED)} written"
    )
    return state


def _add_commands(container, root, td):
    """The watcher that turns a pulsed parameter into a transport command.

    The engine's end of every button press. It watches the component's own
    top-level parameters - the ones the Engine COMP shows in the host - and
    `tdpy.engine.on_command` maps the parameter back to the name in
    `player.COMMANDS`.

    Inside the container rather than beside the Out operators, so it is
    destroyed and rebuilt with everything else it dispatches into.
    """
    from . import startup

    executor = _place(
        startup.create(container, td.parameterexecuteDAT, ENGINE_COMMAND_EXEC),
        250, -1150,
    )
    executor.text = ENGINE_COMMAND_CALLBACK
    startup.set_par(executor, "op", root.path)
    startup.set_par(executor, "pars", ENGINE_COMMAND_PARS)
    # Custom only, and the rising edge only. A command is a pulse, so nothing
    # else here should fire: `valuechange` on every setting would run the
    # transport whenever a slider moved.
    startup.set_par(executor, "custom", True)
    startup.set_par(executor, "builtin", False)
    startup.set_par(executor, "onpulse", True)
    startup.set_par(executor, "valuechange", False)
    startup.set_par(executor, "active", True)

    startup.report(
        f"[{startup.PACKAGE}] commands at {executor.path} from {root.path}"
    )
    return executor


def engine_sources(container):
    """Which operator inside the container feeds each declared output.

    **The decks are tapped before the blend, and the program after it.** Deck
    video is the player's own picture, so deck audio is the clip's own stereo
    off the Audio Movie CHOP - neither level, pan nor the fade's share applied.
    That keeps the pair symmetrical: a deck output is a source, and the program
    outputs are what the Cross TOP and the mixer make of the two of them.

    A missing operator answers None rather than raising, so `engine.main` can
    say which output had nothing to carry.
    """
    from . import link

    audio = container.op(AUDIO_COMP)
    sources = {
        "program_video": container.op(OUT_TOP),
        "program_audio": None if audio is None else audio.op(AUDIO_MIX_CHOP),
        # The playlist the engine actually plays from, rather than a second
        # scan of the same folder in the host - which is the whole point of it
        # crossing, and why the host no longer opens `media/` at all.
        "playlist": container.op(PLAYLIST_DAT),
        "state": container.op(STATE_CHOP),
    }
    for index, name in enumerate(PLAYER_TOPS):
        sources[link.DECK_VIDEO[index]] = container.op(name)
        sources[link.DECK_AUDIO[index]] = (
            None if audio is None
            else audio.op(AUDIO_MOVIE_PREFIX + AUDIO_STRIP_SUFFIXES[index])
        )
    return sources


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


def _add_engine(parent, td):
    """Generate the engine's `.tox`, and load it into an Engine COMP.

    Generate, save, destroy the source, load: the same sequence
    `spikes/engine_spike.setup()` ran on 2026-09-14, which is where `save`,
    the Out TOP's `label`, the Synchronized clock menu and the Execute DAT's
    `create` flag were seen working. The source is destroyed as soon as it is
    saved so that its bootstrap never runs in the host.

    The `.tox` carries its **interface** and nothing behind it: the bootstrap,
    one Out operator per declared output, and the custom parameters - the
    settings the engine reads and one pulse per transport command. The network
    behind the outputs is built inside the engine by `tdpy.engine.main()`, which
    is what makes an edit to `build_player` arrive with a rebuild rather than a
    regenerated file.

    The Engine COMP is converged onto: created on the first build, then given
    the same file and pulsed to reload. Its callbacks DAT and the host's Nulls
    exist before its `file` is set, because setting it on a new COMP is what
    starts the load, and `onReady` reaches for all of them.
    """
    from . import engine, link, settings, startup

    root = startup.project_root()
    path = root / ENGINE_TOX

    stale = parent.op(ENGINE_SOURCE)
    if stale is not None:
        stale.destroy()
    source = _place(startup.create(parent, td.baseCOMP, ENGINE_SOURCE), 250, -700)
    bootstrap = startup.create(source, td.executeDAT, ENGINE_BOOTSTRAP_DAT)
    bootstrap.text = engine.bootstrap_source(root)
    startup.set_par(bootstrap, "create", True)

    # The settings, then the commands. Both are custom parameters on the top
    # level and so both appear on the Engine COMP - which is the only channel
    # the host has into the engine, per `Engine_COMP.htm`: parameters cross one
    # way and nothing inside the .tox may write one.
    settings.declare(source)
    for command in link.commands():
        startup.custom_par(
            source, link.COMMAND_PAGE, "pulse", command.parameter, label=command.name
        )

    outs = {"TOP": td.outTOP, "CHOP": td.outCHOP, "DAT": td.outDAT}
    for index, item in enumerate(link.declared()):
        out = _place(
            startup.create(source, outs[item.family], item.name), 0, -150 * index
        )
        # The label is how the host tells one connector from another: a
        # connector's description is its Out operator's label, and the order
        # they arrive in is undocumented. See `connector_for`.
        startup.set_par(out, "label", item.label)

    source.save(str(path), createFolders=True)
    source.destroy()

    callbacks = parent.op(ENGINE_CALLBACK_DAT)
    if callbacks is None:
        callbacks = _place(
            startup.create(parent, td.textDAT, ENGINE_CALLBACK_DAT), 250, -450
        )
    callbacks.text = ENGINE_CALLBACK
    _add_engine_nulls(parent, td)

    existing = parent.op(ENGINE_COMP)
    comp = existing
    if comp is None:
        comp = _place(startup.create(parent, td.engineCOMP, ENGINE_COMP), 250, -300)
    startup.set_menu(comp, "clock", "synced")
    startup.set_menu(comp, "assetpaths", ENGINE_ASSET_PATHS)
    startup.set_par(comp, "callbacks", callbacks.path)
    startup.set_par(comp, "file", str(path))
    if existing is not None:
        pulse(comp, "reload")

    startup.report(
        f"[{startup.PACKAGE}] engine {'loading' if existing is None else 'reloading'}"
        f" {path.name} at {comp.path}:"
        f" {len(link.parameters())} settings, {len(link.commands())} commands,"
        f" {len(link.declared())} outputs"
    )
    return comp


def _add_engine_nulls(parent, td):
    """One Null beside the container per declared output, found or made.

    Each is named as its output is, so the host's node, the engine's Out
    operator and the connector's label are one spelling from `link.OUTPUTS`.
    They exist before the component loads because `onReady` wires into them,
    and they are converged onto rather than rebuilt for the reason the windows
    are: the window's `winop` holds one by path.

    The deck outputs are here with nothing reading them yet, and that is what
    they are for - a tap for the processing this phase exists to make possible.
    """
    from . import link, startup

    kinds = {"TOP": td.nullTOP, "CHOP": td.nullCHOP, "DAT": td.nullDAT}
    made = []
    for index, item in enumerate(link.declared()):
        if parent.op(item.name) is not None:
            continue
        _place(
            startup.create(parent, kinds[item.family], item.name),
            450, -300 - 100 * index,
        )
        made.append(item.name)
    if made:
        startup.report(f"[{startup.PACKAGE}] engine outputs land in {', '.join(made)}")
    return made


def connector_for(connectors, label):
    """The output connector whose description is `label`, or None.

    By label because the order is not documented: the Out operators'
    `connectorder` is "Help Not Available" in the stub, and the 2026-09-14
    spikes found a connector's `description` is its Out operator's `label`. A family mismatch
    would raise on connecting, so matching the wrong output by position is
    at best a loud failure and at worst a quiet one between two outputs of the
    same family.
    """
    for connector in connectors:
        if connector.description == label:
            return connector
    return None


def wire_engine(comp):
    """Connect every engine output to its Null, and fill its settings. Idempotent.

    Called by the Engine COMP's `onReady`, which fires after each load **and
    after each reload** - seen in `logs/startup.log` on 2026-09-19, one line per
    event. That is why the settings expressions are written here rather than
    where the Engine COMP is created: on a first launch the component's custom
    parameters do not exist until it has loaded, and the build is long finished
    by then.

    It says what it did either way, since the host's first sight of the engine
    working is this line and its first sight of it not working is its absence.
    """
    from . import link, startup

    parent = comp.parent()
    wired = []
    for item in link.declared():
        target = parent.op(item.name)
        if target is None:
            startup.report(f"[{startup.PACKAGE}] no {item.name} beside {comp.path}")
            continue
        connector = connector_for(comp.outputConnectors, item.label)
        if connector is None:
            found = ", ".join(repr(c.description) for c in comp.outputConnectors)
            startup.report(
                f"[{startup.PACKAGE}] no engine output labelled {item.label!r}"
                f" - have {found or 'none'}"
            )
            continue
        connector.connect(target)
        wired.append(item.name)

    startup.report(
        f"[{startup.PACKAGE}] engine outputs wired: {', '.join(wired) or 'none'}"
    )
    _link_settings(comp, parent)
    return wired


def _link_settings(comp, parent):
    """Point the engine's settings parameters at the host's settings COMP.

    One expression per setting, over the parameter of the same name - so the
    engine reads what the panel, the Parameter COMP and a MIDI CC are writing,
    with nothing carrying a value across and nothing to keep in step.

    **An expression rather than a binding**, which is the one place this project
    does not bind two parameters holding one value. `Engine_COMP.htm`: parameters
    "work in one direction only - you cannot set a parameter from within the
    loaded .tox". A binding is two-way by definition, so it would be claiming
    something the boundary cannot do.

    The spelling is `tdpy.audio.parameter_expression`, the same one the mixer's
    gains are built from. Two ways of writing "read this setting" could disagree,
    and the gains are evaluated *inside* the engine against these very
    parameters - so the two are ends of one sentence.
    """
    from . import audio, link, settings, startup

    configuration = parent.op(SETTINGS_COMP)
    if configuration is None:
        startup.report(
            f"[{startup.PACKAGE}] no {SETTINGS_COMP} beside {comp.path}"
            " - the engine will run on the .tox's defaults"
        )
        return []

    linked = []
    for name in link.parameters():
        parameter = getattr(comp.par, name, None)
        if parameter is None:
            startup.report(
                f"[{startup.PACKAGE}] {comp.path} has no {name}"
                " - regenerate the .tox"
            )
            continue
        _set_expression(
            parameter, audio.parameter_expression(configuration.path, name), startup
        )
        linked.append(name)

    startup.report(
        f"[{startup.PACKAGE}] engine settings follow {configuration.path}:"
        f" {len(linked)} of {len(link.parameters())}"
    )
    # Named rather than counted only where it fails, since a setting that did
    # not link is a control that appears to do nothing.
    missing = [name for name in link.parameters() if name not in linked]
    if missing:
        startup.report(f"[{startup.PACKAGE}] not linked: {', '.join(missing)}")
    return linked


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

    # Claim F1. The Perform Window is a *project* setting living in the Window
    # Placement dialog rather than a property of any window, so a project with
    # two Window COMPs and no opinion gets whichever one the dialog already
    # named - which is how F1 came to open the control panel.
    #
    # Pulsed on every build rather than only on the launch that created the
    # window, because the setting is not this window's to hold: anything else
    # can take it, and a rebuild is the project restating what it wants. That
    # is the same argument as the build being clear-and-rebuild at all.
    #
    # It also makes the .toe saved on 2026-09-12 redundant rather than
    # load-bearing. Setting this by hand and saving worked, but it put project
    # state in the one file this project keeps disposable.
    pulse(window, "setperform")

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


def reopen_windows():
    """Pulse Open as Separate Window on both of this project's windows.

    Public because the rebuild button calls it - see the CALLBACK in
    `tdpy/controls.py`. It is deliberately *not* part of `build()`: the build
    opens a window only on the launch that created it, for the reason written
    at `_add_video_window`, and that stays true. This is the button's
    behaviour rather than the build's, so the textport's
    `tdpy.startup.reload()` still leaves the windows exactly as they were.

    Unconditional, and the cost is worth stating: reopening the video window is
    a display mode change rather than a no-op, since it opens exclusive. The
    alternative was a guard on `windowCOMP.isOpen` - a real member, "True when
    window is open" - and it was rejected because it makes the button do
    nothing for a window that is open but buried behind the editor, which is
    one of the cases it gets clicked for.
    """
    import td

    parent = td.op(BUILD_PARENT) or td.op("/")
    return _reopen_windows_under(parent)


def _reopen_windows_under(parent):
    """The half of `reopen_windows` that does not need TouchDesigner.

    Returns the windows it pulsed. A window that is not there is reported and
    skipped rather than raised on: this runs from a Panel Execute DAT after a
    build that `startup.build()` will have swallowed the exception from, so the
    case of "the build failed and the window was never made" is a live one.
    """
    from . import startup

    reopened = []
    for name in (VIDEO_WINDOW_COMP, CONTROL_WINDOW_COMP):
        window = parent.op(name)
        if window is None:
            startup.report(
                f"[{startup.PACKAGE}] no window {name!r} under {parent.path}"
                " - nothing to reopen"
            )
            continue
        pulse(window, "winopen")
        reopened.append(window)
    return reopened


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
    rows = (
        BUTTON_HEIGHT,
        SETTINGS_ROW_HEIGHT,
        AUDIO_ROW_HEIGHT,
        PARAMETER_HEIGHT,
        CLIP_LIST_HEIGHT,
        DIAGNOSTICS_HEIGHT,
    )
    return sum(rows) + max(len(rows) - 1, 0) * PANEL_SPACING


def _row_order(name):
    """A row's `alignorder`, from its place in `PANEL_ROWS`."""
    return PANEL_ROWS.index(name)


def _slider_width(page=None):
    """How wide each slider on that page is: the row, less its toggles and gaps.

    The toggles take a fixed width so the row lines up with the transport above
    it, and the sliders absorb whatever that leaves - so a button width changed
    at the top of this file moves the sliders rather than opening a strip of
    dead panel beside them.

    Per page, because a page is a row: the mixer's four sliders divide the
    panel between themselves and know nothing about the cycle's three above
    them. Passing `None` measures every setting as one row, which is what the
    single-row panel did and is no longer how any row is drawn.
    """
    from . import settings

    count = len(settings.sliders(page))
    if count <= 0:
        return 0
    fixed = len(settings.toggles(page)) * SETTINGS_TOGGLE_WIDTH
    gaps = max(len(settings.on_page(page)) - 1, 0) * PANEL_SPACING
    return max(_panel_width() - fixed - gaps, 0) // count


#: The host's watchers on what the engine publishes: one CHOP Execute per state
#: channel that a surface draws from, and one DAT Execute on the playlist.
#:
#: **One DAT per channel, because the parameter is singular.** The CHOP Execute
#: DAT's help calls its Channel parameter "Which channel will trigger change",
#: and gives no syntax for naming several - so a space-separated list would be a
#: guess that looked like configuration. This is the same shape the dwell's
#: three watchers already take: several DATs, one callback, which recomputes
#: from scratch and therefore does not care which of them fired.
#:
#: **Only the channels a surface draws from.** `misses_*` and `buffer_*` are on
#: the same output and change constantly; they are read by expressions on the
#: diagnostics strip, which needs no callback at all. Watching them here would
#: repaint the clip list every frame.
STATE_WATCH_EXEC_PREFIX = "state_"
STATE_WATCH_CALLBACK = '''# Generated by tdpy/build.py - edits here are overwritten.


def onValueChange(channel, sampleIndex, val, prev):
    import tdpy.lister
    import tdpy.midi

    tdpy.lister.refresh()
    tdpy.midi.refresh_lights()
    return
'''

#: The playlist's watcher. The table arrives after the panel is built - the
#: engine has a folder to scan and files to measure first - and it changes again
#: whenever that scan does, so the list's row count cannot be set once at build
#: time the way it was when the host did its own scanning.
#:
#: `onTableChange(dat, prevDAT, info)` is the signature from the install's
#: `bin/Lib/tdutils/DATScripts/datexecuteDAT.py`.
PLAYLIST_EXEC_NAME = "playlist_exec"
PLAYLIST_EXEC_CALLBACK = '''# Generated by tdpy/build.py - edits here are overwritten.


def onTableChange(dat, prevDAT, info):
    import tdpy.lister

    tdpy.lister.resize()
    return
'''


def state_watch_channels():
    """Which state channels the host's surfaces are redrawn by.

    The union of what the clip list and the lamps read: which deck is live,
    each deck's row, the seed the order is dealt from, and each deck's
    transport. Derived from `link` rather than listed, so a channel renamed
    there is renamed here.
    """
    from . import link

    return ("live", "seed") + link.DECK_ROW + link.DECK_PLAYING


def _add_state_watch(container, parent, td):
    """A watcher per state channel, and one on the playlist. Returns them.

    Both read through the Nulls beside the container rather than through the
    Engine COMP, for the reason `engine.output` exists: what the host draws
    should not know which machine the player is on.
    """
    from . import link, startup

    made = []
    state = parent.op(link.output("state").name)
    if state is None:
        startup.report(
            f"[{startup.PACKAGE}] no {link.output('state').name} under"
            f" {parent.path} - the clip list and the lamps will not follow the player"
        )
    else:
        for index, channel in enumerate(state_watch_channels()):
            watcher = _place(
                startup.create(
                    container, td.chopexecuteDAT, STATE_WATCH_EXEC_PREFIX + channel
                ),
                500, -200 - index * 100,
            )
            watcher.text = STATE_WATCH_CALLBACK
            startup.set_par(watcher, "chop", state.path)
            startup.set_par(watcher, "channel", channel)
            # The value changing is the whole trigger. Every other condition is
            # turned off explicitly, because a second one firing would repaint
            # the list twice per cut and the symptom is a panel that stutters.
            startup.set_par(watcher, "valuechange", True)
            startup.set_par(watcher, "offtoon", False)
            startup.set_par(watcher, "whileon", False)
            startup.set_par(watcher, "ontooff", False)
            startup.set_par(watcher, "whileoff", False)
            startup.set_par(watcher, "active", True)
            made.append(watcher)

    playlist = parent.op(link.output("playlist").name)
    if playlist is None:
        startup.report(
            f"[{startup.PACKAGE}] no {link.output('playlist').name} under"
            f" {parent.path} - the clip list will stay empty"
        )
    else:
        watcher = _place(
            startup.create(container, td.datexecuteDAT, PLAYLIST_EXEC_NAME), 500, -100
        )
        watcher.text = PLAYLIST_EXEC_CALLBACK
        startup.set_par(watcher, "dat", playlist.path)
        startup.set_par(watcher, "tablechange", True)
        startup.set_par(watcher, "active", True)
        made.append(watcher)

    startup.report(
        f"[{startup.PACKAGE}] watching {', '.join(state_watch_channels())}"
        f" and the playlist, {len(made)} watcher(s)"
    )
    return made


def _add_control_panel(parent, configuration, td):
    """The panel: transport, the settings band, and the clip list beneath them.

    Destroyed and rebuilt on every build, unlike the window that shows it - so
    a button relabelled or a column added here arrives with a click of rebuild.
    The window converges onto the new panel because `winop` holds a path, and
    the path does not change when the operator at the end of it does.

    `configuration` is the settings COMP the band's controls bind to, and is all
    this needs now. It took the build container until 9.4, to point the clip
    list's watchers and the diagnostics readouts at the players, and the scanned
    playlist until 9.5, for the list's row count - both of those now come from
    the engine, the first as channels and the second as a table.
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

    from . import settings as settings_module

    _add_transport(panel, td)
    # Iterated rather than called twice by hand, so `settings.PANEL_PAGES` is
    # what decides which pages become bands - a page added there without a row
    # here is reported below rather than quietly not drawn.
    # Two collections in one function now, so neither is called `rows`. The
    # playlist arrived under that name and this dict was assigned over it,
    # which handed the clip list two panel-row definitions instead of
    # seventeen clips - and a length taken from the wrong collection is not
    # wrong in a way anything but the screen can see.
    bands = _settings_rows(settings_module)
    for page in settings_module.PANEL_PAGES:
        band = bands.get(page)
        if band is None:
            startup.report(
                f"[{startup.PACKAGE}] no panel row defined for page {page!r}"
                f" - have {', '.join(sorted(bands))}"
            )
            continue
        _add_settings_row(panel, configuration, page, *band, td)
    _add_parameters(panel, configuration, td)
    _add_clip_list(panel, td)
    _add_diagnostics(panel, td)

    startup.report(
        f"[{startup.PACKAGE}] control panel at {panel.path}:"
        f" {', '.join(name for name, _ in CONTROL_BUTTONS)}"
    )
    return panel


def _add_diagnostics(panel, td):
    """A line per deck of what its decoder is doing, read off the state output.

    The readings are the engine's, and they arrive as two channels per deck -
    `misses_*` and `buffer_*`, which are that player's `pre_read_misses` and
    `num_pre_read_frames`, derived on the machine that holds the decoder. The
    strip does not know that: it reads the Null `engine.output` finds, the same
    as every other surface here.

    Built because the stutter at a cut had two plausible causes - a decode that
    could not keep up, or the desktop compositor dropping frames outside a
    full-screen exclusive Perform Window - and arguing about which was cheaper
    than measuring, right up until it wasn't. The Info CHOPs were already there
    from Phase 4c, publishing all of this and read by nothing.

    **Every reading is an expression over a channel, so nothing pushes here.**
    Same rule as the clip list's highlight and the Cross TOP's value: the thing
    that knows is the operator, and the display asks it. A diagnostic is the
    worst possible place to break that rule, because a stale number does not
    look broken - it looks like a measurement.

    Two Text COMPs rather than one, because the two players are in different
    states at any moment and averaging them would hide the case that matters:
    the hidden player opening a new file while the visible one plays.
    """
    from . import engine, link, startup

    row = startup.create(panel, td.containerCOMP, DIAGNOSTICS_COMP)
    row.nodeX, row.nodeY = 0, -900
    startup.set_par(row, "w", _panel_width())
    startup.set_par(row, "h", DIAGNOSTICS_HEIGHT)
    startup.set_menu(row, "align", TRANSPORT_ALIGN)
    startup.set_par(row, "spacing", PANEL_SPACING)
    # Last in PANEL_ROWS, so this sits at the bottom and the list keeps the
    # position it has had since Phase 5a. The order is read from that tuple
    # rather than written here, which is what stopped a row being inserted
    # above from silently reshuffling the panel.
    startup.set_par(row, "alignorder", _row_order("diagnostics"))

    state = engine.output(link.output("state").name)
    if state is None:
        startup.report(
            f"[{startup.PACKAGE}] no {link.output('state').name} to read"
            f" - {row.path} will be empty"
        )
        return row

    width = max(
        (_panel_width() - PANEL_SPACING * (len(PLAYER_TOPS) - 1)) // len(PLAYER_TOPS),
        0,
    )
    mode = startup.td_enum("ParMode")
    for index, name in enumerate(PLAYER_TOPS):
        readout = startup.create(row, td.textCOMP, f"{DIAGNOSTICS_COMP}_{name}")
        readout.nodeX, readout.nodeY = index * 200, -900
        startup.set_par(readout, "w", width)
        startup.set_par(readout, "h", DIAGNOSTICS_HEIGHT)
        startup.set_par(readout, "fontsize", DIAGNOSTICS_FONT_SIZE)
        startup.set_par(readout, "alignorder", index)
        if mode is not None:
            readout.par.text.expr = _diagnostics_expression(name, state.path, index)
            readout.par.text.mode = mode.EXPRESSION

    startup.report(
        f"[{startup.PACKAGE}] diagnostics at {row.path} <- {state.path}: "
        + ", ".join(name for _, name, _ in DIAGNOSTIC_READINGS)
    )
    return row


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
    startup.set_par(transport, "alignorder", _row_order("transport"))

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


def _settings_rows(settings):
    """Which operator, `PANEL_ROWS` key and height each drawn page gets.

    A function rather than a module constant because the keys are page names
    owned by `tdpy.settings`, and this module cannot import it at module scope
    - `settings` imports `build`, so the dependency only runs one way at import
    time. Taking the module as an argument keeps the names spelled once.
    """
    return {
        settings.PAGE_PLAYER: (SETTINGS_ROW_COMP, "settings", SETTINGS_ROW_HEIGHT),
        settings.PAGE_AUDIO: (AUDIO_ROW_COMP, "audio", AUDIO_ROW_HEIGHT),
    }


def _add_settings_row(panel, configuration, page, comp_name, row, height, td):
    """Toggles and sliders for one page of settings, each bound to its parameter.

    **Nothing here has a callback.** A transport button is a shim into
    `tdpy.player`, because pressing it *does* something; these are views of a
    value, and binding is what makes a view. The consequence is the phase's
    whole argument: a toggle clicked, a number typed into the Parameter COMP
    below, and a MIDI CC all write the same parameter, and none of them has to
    tell the others. The mixer's row was the test of that claim: four sliders
    reaching four gain expressions, and not one line of code connecting them.

    One call per custom page. `page` picks the settings, `comp_name` names the
    operator, and `row` is the key in `PANEL_ROWS` that decides where the band
    sits vertically.

    A control whose parameter is missing is left unbound rather than skipped -
    `settings.parameter()` has already said which one, and a slider that moves
    nothing is a more legible symptom than a gap in the row.
    """
    from . import settings, startup

    band = startup.create(panel, td.containerCOMP, comp_name)
    band.nodeX, band.nodeY = 0, -200 - 150 * _row_order(row)
    startup.set_par(band, "w", _panel_width())
    startup.set_par(band, "h", height)
    startup.set_menu(band, "align", TRANSPORT_ALIGN)
    startup.set_par(band, "spacing", PANEL_SPACING)
    startup.set_par(band, "alignorder", _row_order(row))

    drawn = settings.on_page(page)
    for order, setting in enumerate(drawn):
        if setting.kind == "toggle":
            control = _add_settings_toggle(band, setting, td)
        else:
            control = _add_settings_slider(band, setting, page, td)
        control.nodeX, control.nodeY = 0, -150 * order
        startup.set_par(control, "h", height)
        startup.set_par(control, "label", setting.label)
        startup.set_par(control, "alignorder", order)

        master = settings.parameter(configuration, setting.name)
        if master is not None:
            # value0 on both, and it means the same thing on both: the control's
            # own value. Binding it to the setting is what makes the control a
            # view rather than a second copy.
            startup.bind(control.par.value0, master)

    startup.report(
        f"[{startup.PACKAGE}] {page.lower()} row at {band.path}: "
        + ", ".join(
            setting.node
            if setting.kind == "toggle"
            else f"{setting.node} {setting.minimum:g}-{setting.maximum:g}"
            for setting in drawn
        )
    )
    return band


def _add_settings_toggle(row, setting, td):
    """One toggle button, sized to match a transport button above it."""
    from . import startup

    toggle = startup.create(row, td.buttonCOMP, setting.node)
    startup.set_par(toggle, "w", SETTINGS_TOGGLE_WIDTH)
    startup.set_menu(toggle, "buttontype", SETTINGS_TOGGLE_TYPE)
    startup.set_par(toggle, "fontsize", BUTTON_FONT_SIZE * 0.6)
    return toggle


def _add_settings_slider(row, setting, page, td):
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
    startup.set_par(slider, "w", _slider_width(page))
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
    startup.set_par(node, "alignorder", _row_order("parameters"))
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


def _add_clip_list(panel, td):
    """The list of clips. Returns it.

    Columns come from `lister.COLUMNS`, so a column added there needs nothing
    changed here. The list draws nothing until its init callbacks have run,
    which is what `lister.resize()` is for - creating the node does not itself
    fill anything in.

    **The row count is not set here**, and that is the change 9.5 made. It used
    to be the length of the host's own scan, known at build time; the table now
    arrives from the engine after the panel is built and changes again whenever
    that scan does. So `lister.resize()` sets it from whatever has arrived - at
    the end of the build, and again from the playlist's watcher.
    """
    from . import lister, startup

    callbacks = startup.create(panel, td.textDAT, CLIP_LIST_CALLBACK_DAT)
    callbacks.nodeX, callbacks.nodeY = 300, -600
    callbacks.text = CLIP_LIST_CALLBACK

    node = startup.create(panel, td.listCOMP, CLIP_LIST_COMP)
    node.nodeX, node.nodeY = 0, -600
    startup.set_par(node, "w", _panel_width())
    startup.set_par(node, "h", CLIP_LIST_HEIGHT)
    startup.set_par(node, "alignorder", _row_order("cliplist"))
    startup.set_par(node, "callbacks", callbacks.path)
    # Row 0 is the header, and locking it keeps it visible once the list is
    # long enough to scroll. How many rows follow it is `lister.resize()`'s.
    startup.set_par(node, "cols", len(lister.COLUMNS))
    startup.set_par(node, "lockfirstrow", True)
    startup.set_par(node, "vscrollbar", True)
    # The columns are sized to the panel, so nothing ever needs scrolling
    # sideways - and a horizontal bar would eat a row's worth of height to
    # say so.
    startup.set_par(node, "hscrollbar", False)
    return node


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
    """Two Movie File In TOPs, through a Cross TOP, into a null.

    The null is not decoration, and Phase 6 is what it was for. A Movie File In
    TOP was always the operator most likely to be replaced, so nothing
    downstream was ever connected to one - which is why a second player and a
    blend could be dropped into the middle of the chain with the window, the
    control panel and the display all untouched.

    **The Cross TOP rather than the Switch TOP the plan named.** A Switch is a
    hard cut, and this phase is a fade; the Cross's own help gives the
    convention the rest of this module depends on - Cross 0 shows Input1, Cross
    1 shows Input2 - so the connection order here *is* the meaning of the number
    `tdpy.player` writes.

    Both players are configured identically and neither is special. Which of
    them is on screen is a fact about the cross value, derived wherever it is
    needed rather than recorded anywhere - the same move the transport makes in
    reading its position off `file` instead of keeping an index.

    Speed is **bound**, each player to its own `Speeda`/`Speedb` setting. It was
    one master for both until 2026-09-13, on the argument that one value with
    many views costs nothing; splitting it cost nothing for the same reason, and
    two decks that can run at different rates is audible now that each has its
    own mixer strip. Nothing in this project may write `speed` on a player - a
    binding is two-way, so a stray `set_par` would overwrite the master rather
    than be overridden by it.
    """
    from . import playlist, settings, startup

    players = []
    for index, name in enumerate(PLAYER_TOPS):
        player = _place(
            startup.create(container, td.moviefileinTOP, name), 0, -150 - index * 150
        )
        startup.set_menu(player, "playmode", PLAY_MODE)
        startup.set_par(player, "play", True)

        # The end-of-file and cue policies are *configuration* rather than
        # behaviour: a player always loops and always cues in fractions, and the
        # two settings decide what is done about it. Set here so `tdpy.player`
        # never has to touch a menu - it writes a number into `cuepoint` and
        # fires a pulse, and both mean the same thing on every clip.
        startup.set_menu(player, "textendright", PLAYER_EXTEND_RIGHT)
        startup.set_menu(player, "cuepointunit", CUE_POINT_UNIT)

        # Each player binds to its **own** speed, so the two decks can run at
        # different rates either side of a crossfade. One setting bound to both
        # was the arrangement until 2026-09-13 and it cost nothing; two costs
        # nothing either, because the binding does the work in both cases.
        speed = settings.parameter(configuration, settings.SPEEDS[index])
        if speed is not None:
            startup.bind(player.par.speed, speed)

        # TOPs draw their image on the node when the viewer flag is set, which
        # makes a network opened mid-performance legible: both players visible,
        # and the cross between them showing which one is actually out.
        player.viewer = True
        players.append(player)

    # Both of the expression's operands before the expression. A parameter put
    # into Expression mode against an `op()` that does not exist yet holds the
    # error even after the node arrives, so the fade's timer and state are built
    # here - with the chain they drive - rather than with the cycle that starts
    # them.
    state = _add_fade_state(container, td)
    _add_fade(container, td)

    cross = _place(startup.create(container, td.crossTOP, CROSS_TOP), 250, -225)
    cross.inputConnectors[0].connect(players[0])
    cross.inputConnectors[1].connect(players[1])
    _set_expression(cross.par.cross, CROSS_EXPR, startup)
    cross.viewer = True

    out = _place(startup.create(container, td.nullTOP, OUT_TOP), 500, -225)
    out.inputConnectors[0].connect(cross)
    out.viewer = True

    # Both players get a clip up front, and they get *different* ones: the
    # second is the preload the whole phase is for, sitting decoded and ready
    # so the first cut has the same margin every later cut does. A playlist of
    # one hands both players the same file, which is correct - there is nothing
    # else to cut to, and it fades to itself rather than failing.
    #
    # Relative to the .toe, which sits at the project root - the same root the
    # playlist stored these paths against. Keeping them relative is what lets
    # the repository be cloned to a different folder and still play.
    paths = []
    for index, player in enumerate(players):
        path = playlist.clip_path(rows, _first_clip(rows, index))
        startup.set_par(player, "file", path)
        paths.append(path)

    startup.report(
        f"[{startup.PACKAGE}] player at {out.path} <- "
        + (" / ".join(path or "-" for path in paths) if any(paths)
           else "no file - playlist is empty")
        + f", crossfading via {state.path}"
    )
    # The players as well as the chain's end: the mixer needs the TOPs
    # themselves for its Audio Movie CHOPs, and looking them up again by name
    # would be a second place that has to agree about what they are called.
    return out, players


def _first_clip(rows, index):
    """Which playlist row player `index` opens with.

    The deck's own order, so the first cut plays the clip the panel says is
    next rather than whatever happened to be preloaded. `player.play_order` is
    asked rather than `range` assumed, for the same reason the clip list asks
    it: a seed set before a rebuild should survive one.
    """
    from . import player

    order = player.play_order(len(rows))
    if not order:
        return FIRST_CLIP
    return order[index % len(order)]


def _set_expression(parameter, expression, startup):
    """Put a parameter into Expression mode with that expression. Returns it.

    Not `startup.bind`, and the difference is the point. A binding is between
    two parameters and carries a value both ways; this is one parameter
    computed from CHOP channels, read-only from the network's side, and there
    is no master to write back to.

    Both halves are set for the same reason `bind` sets both: an `expr` on a
    parameter still in Constant mode is inert and looks from the outside
    exactly like an expression that failed.
    """
    mode = startup.td_enum("ParMode")
    if mode is None:
        return None
    parameter.expr = expression
    parameter.mode = mode.EXPRESSION
    return parameter


def _add_fade_state(container, td):
    """The Constant CHOP holding the fade's two ends. Returns it.

    Created at 0 and 0, which is a settled cross on PLAYER_TOPS[0] - the state
    a fresh build should be in, and the one case the arithmetic in CROSS_EXPR
    has to be right about before anything has run.
    """
    from . import startup

    state = _place(
        startup.create(container, td.constantCHOP, FADE_STATE_CHOP), 250, -400
    )
    # `const0name`/`const0value`, read off the type stub at
    # bin/Lib/tdi/ops/chops/constantCHOP.py rather than guessed - the pairing of
    # a name parameter with a value parameter is the kind of thing that is
    # spelled three plausible ways.
    startup.set_par(state, "const0name", FADE_START_CHANNEL)
    startup.set_par(state, "const0value", 0.0)
    startup.set_par(state, "const1name", FADE_TARGET_CHANNEL)
    startup.set_par(state, "const1value", 0.0)
    return state


def _add_audio(container, players, configuration, td):
    """The mixer: each player summed to mono, panned, and the two summed out.

    Two strips and a sum, in a base COMP of their own. A strip is four
    operators - the Audio Movie CHOP that plays the clip's sound, two Math
    CHOPs that each average the stereo pair to one channel and scale it, and
    two Rename CHOPs that call those results `chan1` and `chan2` - and a Merge
    CHOP puts the pair back together as a stereo signal.

    **The clip's own stereo image is deliberately thrown away.** Averaging the
    pair makes each player a mono point source, which is what a pan control
    places; scaling a stereo pair by two different numbers would tilt a balance
    instead, and would leave a hard-panned element in the clip where the clip
    put it no matter where the strip's pan was set.

    **Nothing stores a gain.** Each Math CHOP's `gain` is an expression over
    the two settings parameters and the fade, evaluated by TouchDesigner every
    cook - so a MIDI CC, the panel slider and a typed field are three writers
    to one parameter and none of them has to tell the mixer anything. See
    `tdpy.audio` for the arithmetic and why the paths in it are absolute.

    Returns the Audio Device Out CHOP.
    """
    from . import audio, settings, startup

    comp = _place(startup.create(container, td.baseCOMP, AUDIO_COMP), 500, -600)

    # The fade, spelled from inside this COMP. The players' own container is
    # one level up, so the mixer reaches the fade's state and timer through the
    # container's path rather than as siblings - and it is the same template
    # the Cross TOP's own expression is generated from.
    share = audio.share_expressions(
        CROSS_EXPR_TEMPLATE.format(prefix=f"{container.path}/")
    )
    settings_path = configuration.path if configuration is not None else ""

    strips = []
    for index, player in enumerate(players):
        suffix = AUDIO_STRIP_SUFFIXES[index]
        level_name, pan_name = settings.STRIPS[index]

        source = _place(
            startup.create(comp, td.audiomovieCHOP, AUDIO_MOVIE_PREFIX + suffix),
            0, -200 * index,
        )
        # The TOP's own path rather than a relative hop out of this COMP: the
        # build knows it, and it is the same choice the diagnostics strip makes
        # about the Info CHOPs it reads.
        startup.set_par(source, "moviefileintop", player.path)
        startup.set_par(source, "play", True)

        sides = []
        for side, gain_prefix, name_prefix, offset in (
            (audio.LEFT, AUDIO_LEFT_PREFIX, AUDIO_NAME_LEFT_PREFIX, 0),
            (audio.RIGHT, AUDIO_RIGHT_PREFIX, AUDIO_NAME_RIGHT_PREFIX, -80),
        ):
            gain = _place(
                startup.create(comp, td.mathCHOP, gain_prefix + suffix),
                250, -200 * index + offset,
            )
            gain.inputConnectors[0].connect(source)
            startup.set_menu(gain, "chanop", AUDIO_MONO_OP)
            expression = audio.gain_expression(
                settings_path, level_name, pan_name, share[index], side
            )
            _set_expression(gain.par.gain, expression, startup)
            audio.report_strip(gain.name, side, expression)

            named = _place(
                startup.create(comp, td.renameCHOP, name_prefix + suffix),
                500, -200 * index + offset,
            )
            named.inputConnectors[0].connect(gain)
            startup.set_par(named, "renamefrom", AUDIO_RENAME_FROM)
            startup.set_par(named, "renameto", side)
            sides.append(named)

        strip = _place(
            startup.create(comp, td.mergeCHOP, AUDIO_STRIP_PREFIX + suffix),
            750, -200 * index,
        )
        for position, named in enumerate(sides):
            strip.inputConnectors[position].connect(named)
        strips.append(strip)

    mix = _place(startup.create(comp, td.mathCHOP, AUDIO_MIX_CHOP), 1000, -100)
    for position, strip in enumerate(strips):
        mix.inputConnectors[position].connect(strip)
    startup.set_menu(mix, "chopop", AUDIO_SUM_OP)
    startup.set_menu(mix, "match", AUDIO_SUM_MATCH)

    startup.report(
        f"[{startup.PACKAGE}] audio at {comp.path}: "
        f"{len(strips)} strips summed into {mix.name}"
        + ("" if settings_path else " - no settings COMP, gains will not resolve")
    )
    # The sum, not a device. Since 9.4 the mixer runs in the engine and the
    # sound leaves it as the `program_audio` output; the Audio Device Out CHOP
    # is the host's, because the host owns the audio hardware.
    return mix


def _add_audio_out(parent, td):
    """The host's Audio Device Out CHOP, fed by the engine's program audio.

    Beside the build container, like the windows and the engine's Nulls: it is
    wired to one of those Nulls, and a wire joins siblings. Converged onto
    rather than rebuilt, so a rebuild does not take the sound down.

    The mixer that decides what it carries is in the other process. What is
    host-side is the *device*, for the reason the window is: the host owns the
    hardware, and an engine feeding several sources into it later should not
    each be opening their own.
    """
    from . import link, startup

    source = parent.op(link.output("program_audio").name)
    if source is None:
        startup.report(
            f"[{startup.PACKAGE}] no {link.output('program_audio').name}"
            f" under {parent.path} - there will be no sound"
        )
        return None

    existing = parent.op(AUDIO_OUT_CHOP)
    out = existing if existing is not None else _place(
        startup.create(parent, td.audiodeviceoutCHOP, AUDIO_OUT_CHOP), 700, -300
    )
    out.inputConnectors[0].connect(source)
    startup.set_par(out, "cookalways", AUDIO_OUT_COOK_ALWAYS)

    startup.report(f"[{startup.PACKAGE}] audio out at {out.path} <- {source.path}")
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

    players = [container.op(name) for name in PLAYER_TOPS]
    if any(player is None for player in players):
        startup.report(
            f"[{startup.PACKAGE}] no {', '.join(PLAYER_TOPS)} to drive -"
            " nothing will advance on its own"
        )
        return None

    # One Info CHOP and one watcher per player, because `loop_frame` is a
    # channel a player publishes rather than a parameter it carries: nothing can
    # bind to it and no Parameter Execute DAT can watch it, so each player needs
    # its own reader.
    #
    # **Both are watched and only one of them counts.** The hidden player is
    # decoding a clip nobody is looking at and will loop repeatedly while it
    # waits, so the callback says which player it was and `player.on_loop`
    # refuses the one that is not on screen. Filtering here instead would mean
    # building the watchers around a fact that changes every cut.
    for index, (player, info_name, exec_name) in enumerate(
        zip(players, PLAYER_INFO_CHOPS, LOOP_EXEC_NAMES)
    ):
        y = -400 - index * 150
        info = _place(startup.create(container, td.infoCHOP, info_name), 0, y)
        startup.set_par(info, "op", player.path)
        # All rather than General, deliberately. General is documented as "the
        # channels of the specific OP type", which should be where `loop_frame`
        # lives - but All is documented as every set appended together, so it
        # cannot be the narrower one that leaves the channel out. The cost is
        # channels nothing reads; the alternative risks a watcher wired to a
        # channel that is not there, which fails silently.
        startup.set_menu(info, "infotype", INFO_TYPE)

        watcher = _place(
            startup.create(container, td.chopexecuteDAT, exec_name), 250, y
        )
        watcher.text = LOOP_CALLBACK
        startup.set_par(watcher, "chop", info.path)
        startup.set_par(watcher, "channel", LOOP_CHANNEL)
        # The rising edge only. Every other trigger is turned off explicitly
        # rather than left at its default, because a second one firing would
        # advance twice per loop and the symptom is a player that skips a clip
        # now and then.
        startup.set_par(watcher, "offtoon", True)
        startup.set_par(watcher, "whileon", False)
        startup.set_par(watcher, "ontooff", False)
        startup.set_par(watcher, "whileoff", False)
        startup.set_par(watcher, "valuechange", False)
        startup.set_par(watcher, "active", True)

    callbacks = _place(
        startup.create(container, td.textDAT, DWELL_CALLBACK_DAT), 250, -700
    )
    callbacks.text = DWELL_CALLBACK

    timer = _place(
        startup.create(container, td.timerCHOP, DWELL_TIMER_CHOP), 0, -700
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
    # parameter's business, and the two watchers below own that: the timer is
    # stopped by the Dwellon switch and by a paused clip, and `refresh_dwell`
    # is the one place those two are turned into an answer.
    pulse(timer, "start")

    # `Dwell` is a custom parameter and `play` is a built-in one, which is the
    # only difference between these two watchers - the same callback runs from
    # both, and recomputes the answer rather than setting the half it knows
    # about. A DAT watching the wrong one of builtin/custom sits there looking
    # correctly configured and never fires, so both are always set explicitly.
    _add_dwell_watch(
        container, DWELL_EXEC_NAME, configuration, settings.DWELL, -850, True, td
    )
    for index, (player, exec_name) in enumerate(zip(players, DWELL_PLAY_EXEC_NAMES)):
        _add_dwell_watch(
            container, exec_name, player, PLAYER_PLAY_PAR,
            -1000 - index * 150, False, td,
        )

    startup.report(
        f"[{startup.PACKAGE}] cycle at {timer.path}: {LOOP_CHANNEL} watched"
        f" via {', '.join(PLAYER_INFO_CHOPS)}, dwell bound to {settings.DWELL}"
    )
    return timer


def _add_fade(container, td):
    """The Timer CHOP that ramps the cross, and its callback. Returns it.

    Built with the chain rather than with the cycle, because the Cross TOP's
    expression names it and a parameter put into Expression mode against an
    operator that is not there yet keeps the error afterwards.

    Not started here, and that is the difference between this timer and the
    dwell's. The dwell runs continuously and its Play is a derived state; this
    one is started by `player._step()` at each cut and runs exactly once per
    fade, so a build leaves it idle and there is nothing to refresh.

    Its length is not bound either - see FADE_LENGTH_TYPE for why the product of
    two parameters is computed rather than mirrored. Which means `deferpars`
    matters here in a way it does not for the dwell: the length is written in
    the same breath as the Start pulse, so a timer that ignored parameter
    changes until its next Initialize would run every fade at the *previous*
    fade's length. Off, explicitly, for a failure that would otherwise look
    like a fade slider one cut behind itself.
    """
    from . import startup

    callbacks = _place(
        startup.create(container, td.textDAT, FADE_CALLBACK_DAT), 250, -550
    )
    callbacks.text = FADE_CALLBACK

    timer = _place(
        startup.create(container, td.timerCHOP, FADE_TIMER_CHOP), 0, -550
    )
    startup.set_menu(timer, "lengthtype", FADE_LENGTH_TYPE)
    startup.set_menu(timer, "lengthunits", FADE_LENGTH_UNITS)
    # One run per fade: no cycling, and nothing to reset between fades beyond
    # the Start pulse `_step` fires.
    startup.set_par(timer, "cycle", False)
    startup.set_par(timer, "deferpars", False)
    # The channel CROSS_EXPR reads. A default is not trusted for this one
    # because its absence is silent: the expression would evaluate against a
    # channel that is not there and the cross would sit where it last was.
    startup.set_par(timer, "outfraction", FADE_OUT_FRACTION)
    startup.set_par(timer, "callbacks", callbacks.path)
    return timer


def _add_dwell_watch(container, name, target, parameter, y, custom, td):
    """One Parameter Execute DAT feeding `player.refresh_dwell()`.

    Both of the dwell's inputs are watched the same way and run the same
    callback, so this is written once and called twice. `custom` is the one
    thing that differs: the settings COMP's Dwell is a custom parameter and the
    player's Play is a built-in one, and a DAT with that flag the wrong way
    round never fires and gives no sign of it.
    """
    from . import startup

    executor = _place(
        startup.create(container, td.parameterexecuteDAT, name), 250, y
    )
    executor.text = DWELL_EXEC_CALLBACK
    startup.set_par(executor, "op", target.path)
    startup.set_par(executor, "pars", parameter)
    startup.set_par(executor, "builtin", not custom)
    startup.set_par(executor, "custom", custom)
    startup.set_par(executor, "valuechange", True)
    startup.set_par(executor, "active", True)
    return executor


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


#: Where TouchDesigner keeps the MIDI device mapping. `/local` exists in every
#: project; `midi` and the table inside it are made by the Device Mapper dialog
#: - or, here, by the build.
MIDI_LOCAL = "/local"
MIDI_LOCAL_FOLDER = "midi"
MIDI_DEVICE_DAT = "device"


def _ensure_device_table(td):
    """Author `/local/midi/device`, so the Device Mapper dialog is optional.

    The MIDI In DAT hears nothing without a device mapping - measured on
    2026-09-12, and it is the reason this function exists. The documented way
    to make one is the dialog, which writes into `/local`, which lives in the
    `.toe`. That would make MIDI the one feature requiring a saved `.toe`, in a
    project whose rule is that nothing may.

    What the dialog actually writes is a five-column Table DAT, so the build
    writes it instead, on every launch, the same as everything else here.

    Converged onto rather than cleared: a definition made by hand is kept, and
    so is any row for a device that is not this one. See `midi.device_row`.
    """
    from . import midi, startup

    local = td.op(MIDI_LOCAL)
    if local is None:
        startup.report(
            f"[{startup.PACKAGE}] no {MIDI_LOCAL} - cannot map a MIDI device"
        )
        return None

    folder = local.op(MIDI_LOCAL_FOLDER) or startup.create(
        local, td.baseCOMP, MIDI_LOCAL_FOLDER
    )
    table = folder.op(MIDI_DEVICE_DAT)
    existing = (
        [[cell.val for cell in row] for row in table.rows()]
        if table is not None
        else None
    )
    if table is None:
        table = startup.create(folder, td.tableDAT, MIDI_DEVICE_DAT)

    table.clear()
    for row in midi.device_table_rows(existing):
        table.appendRow(row)

    startup.report(
        f"[{startup.PACKAGE}] midi device {midi.DEVICE_NAME!r}"
        f" as id {midi.DEVICE_ID} in {table.path}"
    )
    return table


def _add_midi(container, td):
    """A MIDI In DAT logging into `tdpy.midi`, and the shim that gets it there.

    The Device Table and Device ID are set explicitly, pointing at the table
    `_ensure_device_table` just authored. They were left on their defaults
    first, on the theory that a raw listener needs no mapping, and the learn
    pass proved that wrong: nothing arrived until a device mapping existed.

    What the mapping does *not* do is decide what any control means. That is
    `midi.MAP`, in Python, for the reason the playlist is scanned rather than
    typed - a map in the `.toe` is a map that cannot be diffed.
    """
    from . import midi, startup

    callbacks = _place(
        startup.create(container, td.textDAT, MIDI_CALLBACK_DAT), 250, -1000
    )
    callbacks.text = MIDI_CALLBACK

    listener = _place(
        startup.create(container, td.midiinDAT, MIDI_IN_DAT), 0, -1000
    )
    startup.set_par(listener, "callbacks", callbacks.path)
    startup.set_par(listener, "device", midi.DEVICE_TABLE)
    startup.set_par(listener, "id", midi.DEVICE_ID)
    startup.set_par(listener, "skipsense", MIDI_SKIP_SENSE)
    startup.set_par(listener, "skiptiming", MIDI_SKIP_TIMING)
    startup.set_par(listener, "active", True)

    # Names the way to ask what has been heard, because the learn mode reports
    # once per control and then goes quiet - so an absent line means either
    # "never arrived" or "already known", and on 2026-09-12 that ambiguity was
    # read as a controller whose buttons had stopped working. They were fine.
    # The lamps' end of the same cable. A CHOP rather than a DAT because
    # sending is a method on midioutCHOP and there is no DAT equivalent - it
    # carries no channels and is never cooked for its output, only called.
    lamps = _place(
        startup.create(container, td.midioutCHOP, MIDI_OUT_CHOP), 0, -1150
    )
    startup.set_par(lamps, "device", midi.DEVICE_TABLE)
    startup.set_par(lamps, "id", midi.DEVICE_ID)
    startup.set_par(lamps, "active", True)

    startup.report(
        f"[{startup.PACKAGE}] midi listening at {listener.path}"
        f" for {midi.DEVICE_NAME!r}, lights via {lamps.path}"
        " - tdpy.midi.learned() lists every control heard since this build"
    )
    return listener


def _place(operator, x, y):
    """Position a node so the built network is legible when opened."""
    operator.nodeX, operator.nodeY = x, y
    return operator
