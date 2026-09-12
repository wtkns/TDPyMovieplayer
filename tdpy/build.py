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
CROSS_EXPR = (
    f"op('{FADE_STATE_CHOP}')['{FADE_START_CHANNEL}']"
    f" + (op('{FADE_STATE_CHOP}')['{FADE_TARGET_CHANNEL}']"
    f" - op('{FADE_STATE_CHOP}')['{FADE_START_CHANNEL}'])"
    f" * op('{FADE_TIMER_CHOP}')['{FADE_FRACTION_CHANNEL}']"
)

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

#: Channel, label, and how many decimals to draw. Kept as one table so adding a
#: reading is a row here and nothing else - the same shape as CONTROL_BUTTONS
#: and settings.SETTINGS.
#:
#: `hardware_decode` is first because it is the one that says whether the Nvidia
#: decoder is being used at all; its help notes it "does nothing for Hap and
#: NotchLC codecs, which are always hardware decoded", so on this project's
#: H.264 media a 0 here is a real finding rather than a formality.
DIAGNOSTIC_CHANNELS = (
    ("hardware_decode", "hw", 0),
    ("pre_read_misses", "miss", 0),
    ("num_pre_read_frames", "buf", 0),
    ("last_frame_decode_time", "dec", 1),
    ("last_gpu_upload_time", "gpu", 1),
    ("has_decode_errors", "err", 0),
)


def _diagnostics_expression(label, info_path):
    """The Text COMP `text` expression for one player. Returns the string.

    **The channels are named in the expression rather than read by a function
    it calls**, and that is not a style preference. TouchDesigner tracks a
    parameter expression's dependencies by what the expression references, so a
    tidier `tdpy.player.diagnostics()` reading the same CHOPs inside itself
    would leave the readout to cook whenever it felt like it - which for a
    diagnostic is worse than not having one, because a stale number reads as a
    measurement.

    An f-string, because a parameter expression is an ordinary Python
    expression. The path is baked in at build time from the Info CHOP's real
    `path`, so nothing here depends on where the network was built.
    """
    parts = " ".join(
        f"{name} {{op({info_path!r})[{channel!r}]:.{places}f}}"
        for channel, name, places in DIAGNOSTIC_CHANNELS
    )
    return f'f"{label}  {parts}"'


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
#: One per player, in PLAYER_TOPS order. Both are watched rather than only the
#: one on screen, because the highlight follows whichever clip the fade is
#: heading towards - and that is the hidden player's `file` right up until the
#: fade begins. Watching both means the row lights up when the clip arrives on
#: screen and not a dwell early, without anything tracking which watcher is the
#: interesting one this time round.
CLIP_LIST_EXEC_NAMES = ("clipListA_exec", "clipListB_exec")
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
#: **Two inputs, because two things stop the timer.** A dwell of 0 means off
#: rather than a cut every frame, and a paused clip is not counted down - pause
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
DWELL_EXEC_CALLBACK = '''# Generated by tdpy/build.py - edits here are overwritten.


def onValueChange(par, prev):
    import tdpy.player

    tdpy.player.refresh_dwell()
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

    # The dwell's watchers only fire when a parameter *changes*, and a launch is
    # not a change - so the timer would sit running with whatever Play it was
    # created holding until somebody touched the slider or pressed pause. Asking
    # the same function they ask is how the state is right on the first frame,
    # and there is only one place that decides it either way.
    player.refresh_dwell()

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
        PARAMETER_HEIGHT,
        CLIP_LIST_HEIGHT,
        DIAGNOSTICS_HEIGHT,
    )
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
    _add_diagnostics(panel, container, td)

    startup.report(
        f"[{startup.PACKAGE}] control panel at {panel.path}:"
        f" {', '.join(name for name, _ in CONTROL_BUTTONS)}"
        f" over {len(rows)} clip(s)"
    )
    return panel


def _add_diagnostics(panel, container, td):
    """A line per player of what its decoder is actually doing. Returns the row.

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
    from . import startup

    row = startup.create(panel, td.containerCOMP, DIAGNOSTICS_COMP)
    row.nodeX, row.nodeY = 0, -900
    startup.set_par(row, "w", _panel_width())
    startup.set_par(row, "h", DIAGNOSTICS_HEIGHT)
    startup.set_menu(row, "align", TRANSPORT_ALIGN)
    startup.set_par(row, "spacing", PANEL_SPACING)
    # After the clip list, which is alignorder 3 - so this sits at the bottom
    # and the list keeps the position it has had since Phase 5a.
    startup.set_par(row, "alignorder", 4)

    width = max(
        (_panel_width() - PANEL_SPACING * (len(PLAYER_TOPS) - 1)) // len(PLAYER_TOPS),
        0,
    )
    mode = startup.td_enum("ParMode")
    readouts = []
    for index, (name, info_name) in enumerate(zip(PLAYER_TOPS, PLAYER_INFO_CHOPS)):
        info = container.op(info_name)
        if info is None:
            startup.report(
                f"[{startup.PACKAGE}] no {info_name} - {name} has no diagnostics"
            )
            continue

        readout = startup.create(row, td.textCOMP, f"{DIAGNOSTICS_COMP}_{name}")
        readout.nodeX, readout.nodeY = index * 200, -900
        startup.set_par(readout, "w", width)
        startup.set_par(readout, "h", DIAGNOSTICS_HEIGHT)
        startup.set_par(readout, "fontsize", DIAGNOSTICS_FONT_SIZE)
        startup.set_par(readout, "alignorder", index)
        if mode is not None:
            readout.par.text.expr = _diagnostics_expression(name, info.path)
            readout.par.text.mode = mode.EXPRESSION
        readouts.append(readout)

    startup.report(
        f"[{startup.PACKAGE}] diagnostics at {row.path}: "
        + ", ".join(name for _, name, _ in DIAGNOSTIC_CHANNELS)
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

    players = [container.op(name) for name in PLAYER_TOPS]
    if any(player is None for player in players):
        startup.report(
            f"[{startup.PACKAGE}] no {', '.join(PLAYER_TOPS)} to watch - the"
            " clip list will not follow the transport"
        )
        return None

    executors = []
    for index, (player, name) in enumerate(zip(players, CLIP_LIST_EXEC_NAMES)):
        executor = startup.create(panel, td.parameterexecuteDAT, name)
        executor.nodeX, executor.nodeY = 300, -750 - index * 150
        executor.text = CLIP_LIST_EXEC_CALLBACK
        startup.set_par(executor, "op", player.path)
        startup.set_par(executor, "pars", CLIP_LIST_WATCH_PAR)
        startup.set_par(executor, "builtin", True)
        startup.set_par(executor, "custom", False)
        startup.set_par(executor, "valuechange", True)
        startup.set_par(executor, "active", True)
        executors.append(executor)
    return executors


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

    Speed is **bound** to the settings COMP's Speed on both, which is what makes
    two players cost nothing here: one master, two views, and a MIDI CC at Phase
    7 still writing one place. Nothing in this project may write `speed` on a
    player - a binding is two-way, so a stray `set_par` would overwrite the
    master rather than be overridden by it.
    """
    from . import playlist, settings, startup

    speed = settings.parameter(configuration, settings.SPEED)
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
    return out


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
    # stopped by a dwell of 0 and by a paused clip, and `player.refresh_dwell`
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


def _place(operator, x, y):
    """Position a node so the built network is legible when opened."""
    operator.nodeX, operator.nodeY = x, y
    return operator
