"""Reading the media folder into rows a Table DAT can hold.

Standard library only, and nothing here imports `td`. That is the point of the
module: the playlist is ordinary Python over ordinary files, so it can be tested
at a normal prompt instead of by opening TouchDesigner and looking at a network.
`build.py` is the only side that knows what a DAT is.

Durations come from `ffprobe`, which TouchDesigner ships in its own `bin/`
alongside `TouchDesigner.exe`, `ffmpeg.exe` and the libav DLLs its movie reader
is built on. That is worth being explicit about, because this project's plan
originally rejected ffprobe as an external dependency and it is not one: it is
part of the TouchDesigner install, and the same libraries are already decoding
these files a moment later. Probing the whole folder costs about a second, so
the build does it every time rather than carrying a cache it would then have to
invalidate.
"""

import json
import pathlib
import shutil
import subprocess
import sys

#: Media folder, relative to the project root.
MEDIA_FOLDER = "media"

#: Extensions the Movie File In TOP will open, filtered to the ones that carry
#: picture. The full list is TouchDesigner's own, lifted out of libTD.dll where
#: it sits beside the libav protocol whitelist:
#:
#:     .mov .gif .mpg .mpeg .swf .avi .mp4 .m4v .wmv .flv .mkv .m2ts .mp3 .ogg
#:     .aif .aiff .flac .wav .mts .3gp .m4a .mxf .ts .265 .webm
#:
#: The audio containers are dropped here (.mp3 .ogg .aif .aiff .flac .wav .m4a)
#: since a movie player has nothing to do with a file that has no video stream.
#: .ogg goes with them: it can carry Theora, but in practice it is a music file,
#: and a stray one would land in the playlist as a black clip.
VIDEO_EXTENSIONS = frozenset(
    {
        ".mov", ".gif", ".mpg", ".mpeg", ".swf", ".avi", ".mp4", ".m4v",
        ".wmv", ".flv", ".mkv", ".m2ts", ".mts", ".3gp", ".mxf", ".ts",
        ".265", ".webm",
    }
)

#: Columns written to the playlist table, in order. `path` is relative to the
#: project root and stays that way: a playlist full of absolute paths is one
#: that only works on the machine that built it.
COLUMNS = ("name", "path", "size", "duration", "fps", "width", "height", "codec")

#: Stop a console window flashing up for every file probed. Twenty files means
#: twenty windows otherwise, in front of whatever TouchDesigner is displaying.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_ffprobe(bin_folder=None):
    """Locate ffprobe, preferring the copy inside the TouchDesigner install.

    `bin_folder` is TouchDesigner's `app.binFolder`, passed in by the caller so
    this module never has to import `td`. Falls back to the folder holding the
    running interpreter - which is that same `bin` when the interpreter is
    TouchDesigner's - and then to PATH, so the tests and the textport both work.

    Returns a path, or None. None is a legitimate outcome and the caller has to
    cope with it: a playlist without durations is still a playlist.
    """
    candidates = []
    if bin_folder:
        candidates.append(pathlib.Path(bin_folder))
    executable = getattr(sys, "executable", None)
    if executable:
        candidates.append(pathlib.Path(executable).parent)

    for folder in candidates:
        for name in ("ffprobe.exe", "ffprobe"):
            candidate = folder / name
            if candidate.is_file():
                return str(candidate)

    return shutil.which("ffprobe")


def media_files(folder):
    """Every video file directly inside `folder`, ordered by name.

    Not recursive, and not sorted cleverly. The player shuffles anyway, so the
    only thing the order has to be is stable - otherwise a seeded run is not
    reproducible, which is the whole reason Phase 5 wants a seed.
    """
    folder = pathlib.Path(folder)
    if not folder.is_dir():
        return []
    found = [
        entry
        for entry in folder.iterdir()
        if entry.is_file() and entry.suffix.lower() in VIDEO_EXTENSIONS
    ]
    return sorted(found, key=lambda entry: entry.name.lower())


def parse_fps(rate):
    """Turn ffprobe's `r_frame_rate` into a number.

    It is a rational string - "30/1", or "30000/1001" for the NTSC rates - and
    "0/0" when the stream has none, which is why this cannot just be a float().
    """
    if not rate:
        return 0.0
    text = str(rate)
    if "/" in text:
        numerator, _, denominator = text.partition("/")
        try:
            numerator, denominator = float(numerator), float(denominator)
        except ValueError:
            return 0.0
        return numerator / denominator if denominator else 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def parse_probe(payload):
    """Pull the fields we want out of ffprobe's JSON.

    Split from the subprocess call so the parsing is testable against a literal
    payload, which is the part that actually has edge cases in it.

    A missing duration comes back as 0.0 rather than None. Zero is already how
    TouchDesigner itself reports an unmeasurable file - "File is reporting a
    length of 0." is one of its own error strings - so the sentinel is one the
    rest of the project would have needed regardless.
    """
    streams = payload.get("streams") or [{}]
    stream = streams[0]
    fmt = payload.get("format") or {}

    try:
        duration = float(fmt.get("duration", 0.0) or 0.0)
    except (TypeError, ValueError):
        duration = 0.0

    return {
        "duration": duration,
        "fps": parse_fps(stream.get("r_frame_rate")),
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "codec": stream.get("codec_name") or "",
    }


def probe(path, ffprobe):
    """Measure one file. Never raises - an unreadable file is a zeroed row.

    One clip that will not probe should cost that clip, not the playlist. The
    build has to finish either way, and a row with duration 0 is visible in the
    table as the thing to go and look at.
    """
    blank = {"duration": 0.0, "fps": 0.0, "width": 0, "height": 0, "codec": ""}
    if not ffprobe:
        return blank

    command = [
        ffprobe,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,r_frame_rate",
        "-show_entries", "format=duration",
        "-of", "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=_NO_WINDOW,
        )
        return parse_probe(json.loads(completed.stdout or "{}"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return blank


def scan(root, ffprobe=None):
    """Build the playlist: one dict per video file, keyed by COLUMNS.

    `root` is the project root, not the media folder - keeping the join in here
    is what lets `path` come out relative to the root without the caller having
    to know the layout.
    """
    root = pathlib.Path(root)
    rows = []
    for entry in media_files(root / MEDIA_FOLDER):
        measured = probe(entry, ffprobe)
        rows.append(
            {
                "name": entry.stem,
                # Forward slashes on every platform: TouchDesigner takes them on
                # Windows, and a backslash in a DAT cell is an escape waiting to
                # happen the first time one of these is pasted into an expression.
                "path": entry.relative_to(root).as_posix(),
                "size": entry.stat().st_size,
                **measured,
            }
        )
    return rows


def clip_path(rows, index=0):
    """The path of one playlist row, or "" when there is no such row.

    An empty playlist is a normal state, not an error: `media/` is gitignored,
    so a fresh clone has an empty one, and a scan that finds nothing should
    produce a player with no file loaded rather than a failed build. TouchDesigner
    treats an empty `file` parameter as no movie, which is exactly right.

    The index is taken modulo the length so a caller cannot run off the end.
    Phase 4 draws from a shuffled deck and will not need that, but the wrap
    costs nothing and turns a whole class of off-by-one into a repeat.
    """
    if not rows:
        return ""
    return rows[index % len(rows)]["path"]


def summarise(rows):
    """One line for the startup log. Says enough to spot a bad scan."""
    if not rows:
        return "playlist empty"
    total = sum(row["duration"] for row in rows)
    unmeasured = sum(1 for row in rows if row["duration"] <= 0)
    line = f"playlist {len(rows)} file(s), {total / 60:.1f} min"
    return line + (f", {unmeasured} unmeasured" if unmeasured else "")
