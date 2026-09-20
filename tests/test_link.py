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


class TestCommands:
    def test_every_command_and_the_parameter_that_carries_it(self):
        assert [tuple(item) for item in link.commands()] == [
            ("play", "Play"),
            ("pause", "Pause"),
            ("toggle", "Toggle"),
            ("previous", "Previous"),
            ("next", "Next"),
            ("shuffle", "Shuffle"),
            ("toggle_a", "Togglea"),
            ("toggle_b", "Toggleb"),
            ("next_a", "Nexta"),
            ("next_b", "Nextb"),
        ]

    def test_the_commands_are_the_transport_the_project_already_had(self):
        # The direction that matters: a command the panel or the MIDI map can
        # ask for and the .tox never declared is a button that does nothing,
        # and nothing would report it until it was pressed.
        from tdpy import player

        assert {item.name for item in link.commands()} == set(player.COMMANDS)

    def test_every_command_parameter_is_a_name_touchdesigner_will_create(self):
        assert [
            item.parameter
            for item in link.commands()
            if not link.valid_parameter(item.parameter)
        ] == []

    def test_no_command_is_spelled_like_a_setting(self):
        # Both live on the same COMP - the component's top level - so a
        # collision would be one parameter doing two jobs, and the loser would
        # be whichever was appended second.
        assert set(link.parameters()).isdisjoint(
            item.parameter for item in link.commands()
        )

    def test_a_parameter_names_the_command_it_came_from(self):
        assert link.command_for("Nextb") == "next_b"

    def test_a_parameter_no_command_owns_is_none(self):
        # The control for the test above: this arrives from another process,
        # so it has to be able to say no rather than guess.
        assert link.command_for("Reload") is None


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

    def test_the_decks_in_player_order(self):
        # The index into either of these is the index into `build.PLAYER_TOPS`,
        # the Cross TOP's inputs and the mixer's strips. A pair the other way
        # round would put deck B's picture on deck A's output, which looks like
        # a controller mapped wrongly rather than a table in the wrong order.
        assert link.DECK_VIDEO == ("deck_a_video", "deck_b_video")
        assert link.DECK_AUDIO == ("deck_a_audio", "deck_b_audio")


class TestDeclared:
    def test_what_the_component_carries(self):
        assert link.DECLARED == (
            "program_video",
            "program_audio",
            "deck_a_video",
            "deck_a_audio",
            "deck_b_video",
            "deck_b_audio",
            "state",
            "playlist",
        )

    def test_every_output_is_carried(self):
        # They were not always: `state` and `playlist` were named here before
        # 9.5 built them, because an Out operator the engine has nothing to
        # feed is a connector answering an empty image.
        assert set(link.DECLARED) == {item.name for item in link.OUTPUTS}

    def test_every_declared_name_is_a_real_output(self):
        assert [item.name for item in link.declared()] == list(link.DECLARED)

    def test_the_families_the_host_has_to_build_a_null_for(self):
        assert [item.family for item in link.declared()] == [
            "TOP", "CHOP", "TOP", "CHOP", "TOP", "CHOP", "CHOP", "DAT"
        ]


class TestDeckChannels:
    def test_the_per_deck_channels_in_player_order(self):
        assert link.DECK_PLAYING == ("playing_a", "playing_b")
        assert link.DECK_ROW == ("row_a", "row_b")
        assert link.DECK_MISSES == ("misses_a", "misses_b")
        assert link.DECK_BUFFER == ("buffer_a", "buffer_b")

    def test_every_per_deck_channel_is_on_the_state_output(self):
        for pair in (
            link.DECK_PLAYING, link.DECK_ROW, link.DECK_MISSES, link.DECK_BUFFER
        ):
            assert set(pair) <= set(link.STATE_CHANNELS), pair

    def test_the_written_channels_are_the_seed_and_the_two_rows(self):
        # The engine writes these and computes the rest. A channel that drifted
        # onto this list would be written over an expression, and the symptom
        # is a reading that stops moving.
        assert link.PUSHED == ("seed", "row_a", "row_b")

    def test_a_channels_index_is_where_the_engine_writes_it(self):
        assert link.channel_index("live") == 0
        assert link.channel_index("row_b") == 9

    def test_an_unknown_channel_raises_rather_than_answering_a_block(self):
        # A wrong name here would write over whichever channel happened to sit
        # at the index a silent answer produced.
        with pytest.raises(ValueError):
            link.channel_index("rows")


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
