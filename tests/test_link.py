"""Tests for the names shared across the Engine COMP boundary.

**Every expected name is written out as a literal.** The failure this module
exists to prevent is the host and the engine disagreeing about a spelling, and
a test that compared `link.OUTPUTS` against `link.OUTPUTS` could not see a
rename at all. Changing a name here should mean changing it in two places, one
of which is this file - which is the cost of a name that crosses a process.
"""

import pathlib
import struct
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tdpy import link  # noqa: E402


class TestParameters:
    def test_one_parameter_per_setting_spelled_as_the_settings_are(self):
        assert link.parameters() == (
            "Advanceonend",
            "Randomcue",
            "Dwellon",
            "Dwell",
            "Fade",
            "Speeda",
            "Speedb",
            "Levela",
            "Pana",
            "Levelb",
            "Panb",
            "Dwellcurve",
        )

    def test_every_parameter_is_a_name_touchdesigner_will_create(self):
        assert [name for name in link.parameters() if not link.valid_parameter(name)] == []

    @pytest.mark.parametrize(
        "name", ["dwell", "DwellOn", "Dwell_on", "Dwell on", "", "1dwell"]
    )
    def test_names_touchdesigner_refuses_are_refused(self, name):
        # The control for the test above: the check has to be able to say no.
        assert not link.valid_parameter(name)

    def test_capital_then_lowercase_and_digits_is_accepted(self):
        assert link.valid_parameter("Speed2")


class TestOutputs:
    def test_the_outputs_by_name_family_and_label(self):
        assert [tuple(item) for item in link.OUTPUTS] == [
            ("program_video", "TOP", "program video"),
            ("program_audio", "CHOP", "program audio"),
            ("deck_a_video", "TOP", "deck A video"),
            ("deck_a_audio", "CHOP", "deck A audio"),
            ("deck_b_video", "TOP", "deck B video"),
            ("deck_b_audio", "CHOP", "deck B audio"),
            ("state", "CHOP", "state"),
            ("playlist", "DAT", "playlist"),
        ]

    def test_every_output_is_a_family_the_engine_passes(self):
        assert {item.family for item in link.OUTPUTS} <= {"TOP", "CHOP", "DAT"}

    def test_names_and_labels_are_each_unique(self):
        names = [item.name for item in link.OUTPUTS]
        labels = [item.label for item in link.OUTPUTS]
        assert len(set(names)) == len(names)
        assert len(set(labels)) == len(labels)

    def test_an_output_is_found_by_name(self):
        assert link.output("state") == ("state", "CHOP", "state")

    def test_a_wrong_name_raises_and_lists_the_real_ones(self):
        with pytest.raises(KeyError, match="program_video"):
            link.output("program")


class TestState:
    def test_the_state_channels(self):
        assert link.STATE_CHANNELS == (
            "live",
            "fading",
            "cross",
            "seed",
            "playing_a",
            "row_a",
            "misses_a",
            "buffer_a",
            "playing_b",
            "row_b",
            "misses_b",
            "buffer_b",
        )

    def test_channel_names_are_unique(self):
        assert len(set(link.STATE_CHANNELS)) == len(link.STATE_CHANNELS)

    def test_absent_is_minus_one(self):
        assert link.ABSENT == -1

    @pytest.mark.parametrize("value", [None, 0, 1, 17, 999999])
    def test_a_seed_or_row_survives_a_32_bit_channel(self, value):
        # Packed and unpacked as a real float32, which is what CHOP.htm says a
        # channel sample is - not handed back as the Python float it went in as.
        stored = struct.unpack("f", struct.pack("f", link.to_channel(value)))[0]
        assert link.from_channel(stored) == value

    def test_none_is_written_as_minus_one(self):
        assert link.to_channel(None) == -1

    def test_a_value_just_under_an_integer_rounds_to_it(self):
        assert link.from_channel(418272.99999) == 418273

    def test_any_negative_reads_as_absent(self):
        assert link.from_channel(-1.0) is None
        assert link.from_channel(-3.0) is None
