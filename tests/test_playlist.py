"""Tests for the playlist scan.

All of this runs at a normal prompt - no TouchDesigner, and no video files. That
is the reason Phase 1 was put first: it is the part of the project that can be
checked without opening anything.

ffprobe is never actually invoked here. `probe()` is a thin wrapper around
subprocess and testing it would mean testing ffmpeg; the part with edge cases in
it is `parse_probe()`, which takes a payload and is exercised directly.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tdpy import playlist  # noqa: E402


def touch(folder, *names):
    """Make empty files, returning the folder. Contents never matter here."""
    for name in names:
        (folder / name).write_bytes(b"")
    return folder


class TestMediaFiles:
    def test_keeps_video_and_drops_everything_else(self, tmp_path):
        touch(
            tmp_path,
            "a.mkv",
            "b.mp4",
            "c.mov",
            "notes.txt",
            "cover.jpg",
            "soundtrack.flac",
        )
        assert [entry.name for entry in playlist.media_files(tmp_path)] == [
            "a.mkv",
            "b.mp4",
            "c.mov",
        ]

    def test_extension_match_is_case_insensitive(self, tmp_path):
        # Files copied off a camera or another OS regularly arrive shouting.
        touch(tmp_path, "CLIP.MKV", "other.Mp4")
        assert len(playlist.media_files(tmp_path)) == 2

    def test_skips_the_folders_own_gitignore(self, tmp_path):
        # media/ carries a .gitignore so the folder stays tracked but empty.
        # It has no extension, so nothing special is needed - but if the
        # filtering were ever loosened this is the file that would show up.
        touch(tmp_path, ".gitignore", "clip.mkv")
        assert [entry.name for entry in playlist.media_files(tmp_path)] == ["clip.mkv"]

    def test_does_not_recurse(self, tmp_path):
        nested = tmp_path / "archive"
        nested.mkdir()
        touch(nested, "buried.mkv")
        touch(tmp_path, "surface.mkv")
        assert [entry.name for entry in playlist.media_files(tmp_path)] == [
            "surface.mkv"
        ]

    def test_missing_folder_is_empty_not_an_error(self, tmp_path):
        assert playlist.media_files(tmp_path / "nope") == []

    def test_order_is_stable_and_case_insensitive(self, tmp_path):
        touch(tmp_path, "b.mkv", "A.mkv", "c.mkv")
        assert [entry.name for entry in playlist.media_files(tmp_path)] == [
            "A.mkv",
            "b.mkv",
            "c.mkv",
        ]


class TestParseFps:
    @pytest.mark.parametrize(
        "rate, expected",
        [
            ("30/1", 30.0),
            ("60/1", 60.0),
            ("25/1", 25.0),
            ("30000/1001", pytest.approx(29.97, abs=0.01)),
            ("0/0", 0.0),  # what ffprobe reports for a stream with no rate
            ("24", 24.0),
            ("", 0.0),
            (None, 0.0),
            ("nonsense", 0.0),
        ],
    )
    def test_rational_strings(self, rate, expected):
        assert playlist.parse_fps(rate) == expected


class TestParseProbe:
    # Trimmed from a real run of TouchDesigner's own ffprobe against
    # "Copy of 01 Introit.mkv".
    PAYLOAD = json.loads(
        """
        {
          "streams": [
            {"codec_name": "h264", "width": 1280, "height": 720,
             "r_frame_rate": "30/1"}
          ],
          "format": {"duration": "36.000000"}
        }
        """
    )

    def test_reads_a_real_payload(self):
        assert playlist.parse_probe(self.PAYLOAD) == {
            "duration": 36.0,
            "fps": 30.0,
            "width": 1280,
            "height": 720,
            "codec": "h264",
        }

    def test_empty_payload_zeroes_rather_than_raising(self):
        assert playlist.parse_probe({}) == {
            "duration": 0.0,
            "fps": 0.0,
            "width": 0,
            "height": 0,
            "codec": "",
        }

    def test_audio_only_file_has_no_video_stream(self):
        # -select_streams v:0 returns an empty list rather than omitting the key.
        measured = playlist.parse_probe(
            {"streams": [], "format": {"duration": "12.5"}}
        )
        assert measured["duration"] == 12.5
        assert measured["width"] == 0
        assert measured["codec"] == ""

    def test_unparseable_duration_falls_back_to_zero(self):
        # Some containers report "N/A" rather than omitting the field.
        assert playlist.parse_probe({"format": {"duration": "N/A"}})["duration"] == 0.0


class TestFindFfprobe:
    def test_prefers_the_given_bin_folder(self, tmp_path):
        bundled = tmp_path / "ffprobe.exe"
        bundled.write_bytes(b"")
        assert playlist.find_ffprobe(tmp_path) == str(bundled)

    def test_falls_back_to_the_running_interpreter(self, tmp_path, monkeypatch):
        # Inside TouchDesigner sys.executable already sits in that same bin
        # folder, so this path is the one that works without app.binFolder.
        beside = tmp_path / "ffprobe.exe"
        beside.write_bytes(b"")
        monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
        monkeypatch.setattr(playlist.shutil, "which", lambda _: None)

        assert playlist.find_ffprobe(None) == str(beside)

    def test_falls_through_to_path_when_no_folder_holds_it(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
        monkeypatch.setattr(playlist.shutil, "which", lambda _: "/usr/bin/ffprobe")

        assert playlist.find_ffprobe(tmp_path) == "/usr/bin/ffprobe"

    def test_none_when_there_is_no_ffprobe_anywhere(self, tmp_path, monkeypatch):
        # A legitimate outcome, not an error: the build reports it and carries
        # on with a playlist whose durations all read 0.
        monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
        monkeypatch.setattr(playlist.shutil, "which", lambda _: None)

        assert playlist.find_ffprobe(tmp_path) is None


class TestScan:
    def test_rows_carry_every_column(self, tmp_path):
        media = tmp_path / playlist.MEDIA_FOLDER
        media.mkdir()
        (media / "clip.mkv").write_bytes(b"0123456789")

        rows = playlist.scan(tmp_path, ffprobe=None)

        assert len(rows) == 1
        assert set(rows[0]) == set(playlist.COLUMNS)

    def test_paths_are_relative_to_the_project_root(self, tmp_path):
        media = tmp_path / playlist.MEDIA_FOLDER
        media.mkdir()
        (media / "clip.mkv").write_bytes(b"")

        row = playlist.scan(tmp_path, ffprobe=None)[0]

        # Relative, forward-slashed, and not the absolute path of this machine.
        assert row["path"] == "media/clip.mkv"
        assert row["name"] == "clip"

    def test_size_is_read_from_disk(self, tmp_path):
        media = tmp_path / playlist.MEDIA_FOLDER
        media.mkdir()
        (media / "clip.mkv").write_bytes(b"0123456789")
        assert playlist.scan(tmp_path, ffprobe=None)[0]["size"] == 10

    def test_without_ffprobe_rows_are_unmeasured_but_present(self, tmp_path):
        media = tmp_path / playlist.MEDIA_FOLDER
        media.mkdir()
        (media / "clip.mkv").write_bytes(b"")

        row = playlist.scan(tmp_path, ffprobe=None)[0]

        assert row["duration"] == 0.0
        assert row["fps"] == 0.0

    def test_missing_media_folder_scans_to_nothing(self, tmp_path):
        assert playlist.scan(tmp_path, ffprobe=None) == []


class TestSummarise:
    def test_empty(self):
        assert playlist.summarise([]) == "playlist empty"

    def test_counts_and_totals_in_minutes(self):
        rows = [{"duration": 60.0}, {"duration": 90.0}]
        assert playlist.summarise(rows) == "playlist 2 file(s), 2.5 min"

    def test_flags_unmeasured_files(self):
        rows = [{"duration": 60.0}, {"duration": 0.0}]
        assert playlist.summarise(rows).endswith("1 unmeasured")
