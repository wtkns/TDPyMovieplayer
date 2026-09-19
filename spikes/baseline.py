"""Phase 9.0 and 9.7 - one fixed run of the player, measured frame by frame.

Scratch, like `engine_spike.py`: nothing in `tdpy` imports it. The same
recorder takes the 9.0 baseline from today's single-process build and the 9.7
measurement from the Engine COMP build, so the two numbers come from one
instrument.

Run from the textport, **straight after pressing rebuild**, so the run starts
from the first clip with nothing cued:

    import spikes.baseline as b; b.start()

**Rebuild does not reload this file.** `startup.reload()` drops the modules
under `tdpy.` and nothing else, so a `spikes.baseline` already in
`sys.modules` is handed back unchanged however many times the rebuild button
is pressed - and a run then measures the last version imported rather than the
one on disk, which reads as an edit that silently did not work. After editing
this file:

    import importlib, spikes.baseline; b = importlib.reload(spikes.baseline)

Only ever with no run active, since a reload while `player._step` is wrapped
strands the old wrapper - the identity check in `stop()` will not recognise it.
`b.RUN is None` answers whether a run is active.

It writes the cycle's settings, deals seed `SEED`, presses play, and records
until `minutes` have passed. Then it stops itself and writes two CSVs -
`logs/baseline-<label>-<time>.csv` (one row a second) and
`logs/baseline-<label>-<time>-cuts.csv` (one row a cut) - plus a summary line
to `logs/startup.log`. `b.stop()` ends a run early and still writes both.

**Random cue is on, and its draw is seeded.** It has to be on: cueing into the
middle of a clip is the suspected cause of the thing being measured, and a run
that cues every clip to frame 0 measures the easy case. It used to be switched
off because `player.cue_fraction` draws from an unseeded generator and two
unrepeatable runs compare the draw as much as the build - but that is a false
choice. `start()` patches `cue_fraction` to draw from a `random.Random(seed)`
of its own, so the same seed cues the same points in the same clips.

**`stop()` pauses the player and puts the settings back**, which is also how a
finished run announces itself: the picture stops moving. `start()` presses
play, so this is the inverse rather than an extra courtesy.

**What is counted, and from where.**

The first run trusted a Perform CHOP's `droppedframes` and `msec` channels for
frame timing, on the assumption that channels named on the type stub existed
under those names on this operator - and they did not, so its "0 dropped" was
never a reading. The fix is not a corrected channel name; it is to stop asking
the Perform CHOP and time frames in Python instead. `on_frame` runs once per
TD frame from the Execute DAT below, so the wall-clock delta between one call
and the next *is* that frame's real duration, whatever produced it - decode,
compositor, or anything else. Recorded as `frame_ms` per second (mean and
max), with no threshold guessing which frames count as "dropped" - the CSV
settles that the way it settles the pre-read counter's semantics.

The first run also summed `pre_read_misses`' *increases* once a second, which
turned out to count recoveries rather than misses: the counter swings between
1 and 2 at every cut rather than climbing, so an increase is as likely to be
the read-ahead catching up as falling behind. The per-second sample is kept
for a trend line, but the number that answers the question is sampled once
**right before each cut**, in `cuts.csv`. `player._step` is the single funnel
every clip change goes through - dwell, loop, button, MIDI - so wrapping it
here is the one hook that sees every cut without five separate ones.

For 9.7, pass `sources` naming the engine's Info CHOP channels instead of the
players' - `engine_read_ahead_misses` in place of `pre_read_misses` - since the
players will be in another process. Frame timing needs no equivalent change:
`on_frame` times the host's own frames either way.
"""

import csv
import random
import time

from tdpy import startup

# `perf_counter` rather than `monotonic`, and the difference is the whole
# measurement. `time.get_clock_info` on this machine reports monotonic as
# GetTickCount64 at 15.625ms, against a 60fps frame of 16.67ms - so every
# reading came back a multiple of one tick and a dropped frame was
# indistinguishable from a good one. perf_counter is QueryPerformanceCounter
# at 0.1us. Every time in a run is compared against the others, so they all
# have to come from the same clock.

PARENT = "/project1"
EXECUTE = "baselineExec"
TAG = "[baseline]"

SEED = 419273
MINUTES = 5.0


def _tdpy():
    """The project modules, imported now rather than at module scope.

    The rebuild button runs `startup.reload()`, which drops every `tdpy`
    submodule. A reference taken when this file was first imported would then
    point at the old `player`, whose seed is not the one the new network reads -
    so a second run after a rebuild would deal a deck nothing is playing.
    """
    from tdpy import build, player, settings

    return build, player, settings


def run_settings():
    """The cycle for a measured run.

    A four-second dwell with a fifth of it spent fading cuts fifteen times a
    minute and keeps both players busy - the condition the stutter was
    reported under.
    """
    _, _, settings = _tdpy()
    return {
        settings.DWELL_ON: True,
        settings.DWELL: 4.0,
        settings.FADE: 0.2,
        settings.RANDOM_CUE: True,
        settings.ADVANCE_ON_END: True,
    }

EXECUTE_TEXT = '''# Generated by spikes/baseline.py - edits here are overwritten.
def onFrameEnd(frame):
    import spikes.baseline
    spikes.baseline.on_frame(frame)
    return
'''

#: The run in progress, or None. Module state because the recorder is called
#: once a frame from a DAT and has nowhere else to keep a running total.
RUN = None

#: `player._step`, saved while a run has it wrapped. None the rest of the
#: time, which is also how `stop()` knows whether there is anything to undo.
_ORIGINAL_STEP = None

#: `player.cue_fraction`, saved while a run has it drawing from a seeded
#: generator instead of the module's own.
_ORIGINAL_CUE = None


def player_sources():
    """(label, CHOP path, channel) for each player's pre-read misses and buffer."""
    build, _, _ = _tdpy()
    container = f"{build.BUILD_PARENT}/{build.BUILD_ROOT}"
    sources = []
    for top, info in zip(build.PLAYER_TOPS, build.PLAYER_INFO_CHOPS):
        sources.append((f"{top}_misses", f"{container}/{info}", "pre_read_misses"))
        sources.append((f"{top}_buffer", f"{container}/{info}", "num_pre_read_frames"))
    return sources


def start(label="single", seed=SEED, minutes=MINUTES, sources=None):
    """Configure the player, begin recording, and press play."""
    import td

    global RUN, _ORIGINAL_STEP, _ORIGINAL_CUE
    stop(write=False)
    _, player, settings = _tdpy()
    parent = td.op(PARENT)
    configuration = run_settings()

    comp = settings.comp()
    before = {}
    for name, value in configuration.items():
        found = settings.parameter(comp, name)
        if found is not None:
            before[name] = found.val
            found.val = value

    RUN = {
        "label": label,
        "seed": seed,
        "until": time.perf_counter() + minutes * 60.0,
        "started": time.perf_counter(),
        "sources": list(player_sources() if sources is None else sources),
        "settings_before": before,
        "frames": 0,
        "last_frame_at": None,
        "frame_ms_max": 0.0,
        "frame_ms_sum": 0.0,
        "frame_ms_count": 0,
        "row_ms_max": 0.0,
        "row_ms_sum": 0.0,
        "row_ms_count": 0,
        "last": {},
        "rows": [],
        "cuts": [],
        "next_row": time.perf_counter(),
        "missing": set(),
    }

    player.set_seed(seed)
    player.play()

    _ORIGINAL_STEP = player._step
    player._step = _wrapped_step

    # A generator of this run's own, so the cue points are part of what the
    # seed reproduces. `player.random` is left alone: patching the module would
    # break `deck()`, which calls `random.Random` on it.
    draw = random.Random(seed).random
    _ORIGINAL_CUE = player.cue_fraction
    player.cue_fraction = lambda random_cue, draw=None, _draw=draw: _ORIGINAL_CUE(
        random_cue, draw=_draw
    )

    execute = startup.create(parent, td.executeDAT, EXECUTE)
    execute.nodeX, execute.nodeY = -500, -750
    execute.text = EXECUTE_TEXT
    startup.set_par(execute, "frameend", True)

    startup.report(
        f"{TAG} {label}: seed {seed}, {minutes:g} min, settings {configuration}"
    )


def _wrapped_step(step, into=None):
    """Sample `pre_read_misses` before the real `_step` fires the cut.

    `_step` is the funnel every clip change goes through regardless of what
    triggered it, so wrapping the module's own reference here is the one hook
    that needs no change wherever `next_clip`, `on_dwell`, `on_loop` or MIDI
    call it.
    """
    _sample_before_cut()
    return _ORIGINAL_STEP(step, into=into)


def _sample_before_cut():
    """One row into `RUN['cuts']`: the misses sources read right now."""
    if RUN is None:
        return
    row = {"seconds": round(time.perf_counter() - RUN["started"], 1)}
    for label, path, channel in RUN["sources"]:
        if channel == "pre_read_misses":
            row[label] = _read(path, channel)
    RUN["cuts"].append(row)


def _read(path, channel):
    """A channel's value, or None - reported once per run, not once a frame."""
    import td

    chop = td.op(path)
    found = chop[channel] if chop is not None else None
    if found is None:
        key = (path, channel)
        if key not in RUN["missing"]:
            RUN["missing"].add(key)
            startup.report(f"{TAG} no {channel} on {path}")
        return None
    return found.eval()


def on_frame(frame):
    """Accumulate one frame. Called by the Execute DAT."""
    if RUN is None:
        return
    now = time.perf_counter()
    previous = RUN["last_frame_at"]
    RUN["last_frame_at"] = now

    RUN["frames"] += 1
    if previous is not None and RUN["frames"] > 60:
        # The first second is warm-up - the callback settling in, not the run.
        frame_ms = (now - previous) * 1000.0
        RUN["frame_ms_max"] = max(RUN["frame_ms_max"], frame_ms)
        RUN["frame_ms_sum"] += frame_ms
        RUN["frame_ms_count"] += 1
        RUN["row_ms_max"] = max(RUN["row_ms_max"], frame_ms)
        RUN["row_ms_sum"] += frame_ms
        RUN["row_ms_count"] += 1

    values = {}
    for label, path, channel in RUN["sources"]:
        value = _read(path, channel)
        values[label] = value
        RUN["last"][label] = value

    if now >= RUN["next_row"]:
        RUN["next_row"] += 1.0
        # This row's own frames, not the run's. A running max reports only the
        # worst frame so far, so it goes flat after the first spike and cannot
        # say whether a given cut cost anything - which is the question.
        mean_ms = (
            RUN["row_ms_sum"] / RUN["row_ms_count"]
            if RUN["row_ms_count"] else None
        )
        RUN["rows"].append(
            {"seconds": round(now - RUN["started"], 1),
             "frame_ms_mean": mean_ms, "frame_ms_max": RUN["row_ms_max"],
             **values}
        )
        RUN["row_ms_max"] = 0.0
        RUN["row_ms_sum"] = 0.0
        RUN["row_ms_count"] = 0
    if now >= RUN["until"]:
        stop()


def stop(write=True):
    """End the run, remove the recorder, and write the CSVs and summary."""
    import td

    global RUN, _ORIGINAL_STEP, _ORIGINAL_CUE
    _, player, settings = _tdpy()
    if _ORIGINAL_STEP is not None:
        # Only when the live module is still the one that was wrapped. Pressing
        # rebuild between start and stop runs `startup.reload()`, which drops
        # `player` - and writing the saved function onto the fresh module would
        # install one whose globals belong to the dropped copy.
        if player._step is _wrapped_step:
            player._step = _ORIGINAL_STEP
        _ORIGINAL_STEP = None
    if _ORIGINAL_CUE is not None:
        player.cue_fraction = _ORIGINAL_CUE
        _ORIGINAL_CUE = None

    parent = td.op(PARENT)
    found = parent.op(EXECUTE) if parent is not None else None
    if found is not None:
        found.destroy()
    if RUN is None:
        return None
    run, RUN = RUN, None

    # The picture stopping is how a finished run announces itself across the
    # room, and the settings going back is the inverse of `start()` writing
    # them - a recorder that left the machine reconfigured would make the next
    # thing anybody did depend on whether they remembered this one.
    player.pause()
    comp = settings.comp()
    for name, value in run["settings_before"].items():
        previous = settings.parameter(comp, name)
        if previous is not None:
            previous.val = value

    if not write:
        return None

    stamp = time.strftime("%Y%m%d-%H%M%S")
    root = startup.project_root() / "logs"
    root.mkdir(exist_ok=True)
    path = root / f"baseline-{run['label']}-{stamp}.csv"
    if run["rows"]:
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(run["rows"][0]))
            writer.writeheader()
            writer.writerows(run["rows"])

    cuts_path = root / f"baseline-{run['label']}-{stamp}-cuts.csv"
    if run["cuts"]:
        with open(cuts_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(run["cuts"][0]))
            writer.writeheader()
            writer.writerows(run["cuts"])

    seconds = time.perf_counter() - run["started"]
    mean_ms = run["frame_ms_sum"] / run["frame_ms_count"] if run["frame_ms_count"] else None
    summary = (
        f"{TAG} {run['label']} seed {run['seed']}: {seconds:.0f}s, {run['frames']} frames,"
        f" frame ms mean {mean_ms}, max {run['frame_ms_max']:.1f},"
        f" {len(run['cuts'])} cuts - {path.name}"
    )
    startup.report(summary)
    return summary
