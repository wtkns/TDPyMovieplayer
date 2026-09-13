"""Tests for the MIDI dispatch - everything Phase 7 decides before it writes.

`tdpy/midi.py` is written so that exactly one function needs TouchDesigner
(`apply_setting`, which reads and writes a Par) and everything that makes a
decision sits above it: which control a message belongs to, whether a message
is a press or a release, and what a CC value means for a given setting. Those
are what is tested here.

The scaling tests read their ranges out of `settings.SETTINGS` rather than
writing 60 or 4 into an assertion. That is the property worth holding: the map
must not carry a second copy of a number the settings table already has, so
moving a slider's maximum there has to move what the knob does without anything
here being edited.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tdpy import midi, player, settings, startup  # noqa: E402


@pytest.fixture
def silent(monkeypatch):
    """Collect reported lines instead of writing them to the log."""
    lines = []
    monkeypatch.setattr(startup, "report", lines.append)
    return lines


@pytest.fixture(autouse=True)
def clean_slate(monkeypatch):
    """A fresh module state per test - SEEN and MAP are module-level."""
    monkeypatch.setattr(midi, "SEEN", type(midi.SEEN)())
    monkeypatch.setattr(midi, "MAP", ())
    monkeypatch.setattr(midi, "LEARN", True)


class TestLearn:
    def test_a_new_control_is_reported_once(self, silent):
        midi.note(midi.CONTROL_CHANGE, 1, 13, 64)
        assert len(silent) == 1
        assert "index 13" in silent[0]

    def test_the_same_control_moving_is_not_reported_again(self, silent):
        # The point of the learn mode. A fader sweep is a hundred messages and
        # one control, and a line per message would bury the eight lines
        # actually wanted under a thousand that repeat.
        for value in range(128):
            midi.note(midi.CONTROL_CHANGE, 1, 13, value)
        assert len(silent) == 1

    def test_a_second_control_is_its_own_line(self, silent):
        midi.note(midi.CONTROL_CHANGE, 1, 13, 64)
        midi.note(midi.CONTROL_CHANGE, 1, 14, 64)
        assert len(silent) == 2

    def test_the_same_index_on_another_channel_is_another_control(self, silent):
        midi.note(midi.CONTROL_CHANGE, 1, 13, 64)
        midi.note(midi.CONTROL_CHANGE, 2, 13, 64)
        assert len(silent) == 2

    def test_a_note_and_a_cc_of_the_same_number_are_different_controls(self, silent):
        midi.note(midi.CONTROL_CHANGE, 1, 41, 127)
        midi.note(midi.NOTE_ON, 1, 41, 127)
        assert len(silent) == 2

    def test_the_range_is_tracked_so_a_fader_can_be_told_from_a_button(self, silent):
        # A button reads 0 and 127 and nothing between; a fader fills the
        # range. That is the difference the map is written from, and the count
        # alone does not carry it.
        for value in (64, 0, 127, 70):
            seen = midi.note(midi.CONTROL_CHANGE, 1, 13, value)
        assert (seen.count, seen.lowest, seen.highest) == (4, 0, 127)

    def test_learned_gives_a_line_per_control(self, silent):
        midi.note(midi.CONTROL_CHANGE, 1, 13, 64)
        midi.note(midi.NOTE_ON, 1, 41, 127)
        lines = midi.learned()
        assert len(lines) == 2
        assert "Control Change ch1 index 13" in lines[0]

    def test_learned_says_so_when_nothing_has_arrived(self, silent):
        # The first thing to go wrong is the device not being heard at all,
        # and an empty list is indistinguishable from a device sitting still.
        assert midi.learned() == []
        assert len(silent) == 1
        assert "nothing heard" in silent[0]

    def test_learn_can_be_turned_off(self, silent, monkeypatch):
        monkeypatch.setattr(midi, "LEARN", False)
        midi.on_message(midi.CONTROL_CHANGE, 1, 13, 64)
        assert silent == []


class TestIsPress:
    def test_a_note_on_is_a_press(self):
        assert midi.is_press(midi.NOTE_ON, 127) is True

    def test_a_note_off_is_not(self):
        assert midi.is_press(midi.NOTE_OFF, 0) is False

    def test_a_note_on_of_velocity_zero_is_not(self):
        # The MIDI spec lets a device end a note this way, and a controller
        # that used it would otherwise fire every command twice - once going
        # down and once coming up, which on `next` is a clip skipped.
        assert midi.is_press(midi.NOTE_ON, 0) is False

    def test_a_control_change_of_zero_is_not_a_press(self):
        assert midi.is_press(midi.CONTROL_CHANGE, 0) is False


class TestTargetValue:
    def test_a_cc_of_zero_is_the_bottom_of_the_range(self):
        dwell = settings.spec(settings.DWELL)
        assert midi.target_value(dwell, 0) == dwell.minimum

    def test_a_cc_of_127_is_the_top_of_the_range(self):
        dwell = settings.spec(settings.DWELL)
        assert midi.target_value(dwell, midi.FULL) == dwell.maximum

    def test_the_middle_of_the_fader_is_the_middle_of_the_range(self):
        fade = settings.spec(settings.FADE)
        middle = midi.target_value(fade, midi.FULL // 2 + 1)
        assert fade.minimum < middle < fade.maximum

    def test_the_range_comes_from_the_settings_table_not_from_here(self):
        # The property this module is built around: no number that
        # settings.SETTINGS already holds is copied into the map. Move the
        # maximum and the knob has to follow with nothing edited here.
        speed = settings.spec(settings.SPEED)
        widened = speed._replace(maximum=speed.maximum * 2)
        assert midi.target_value(widened, midi.FULL) == speed.maximum * 2

    def test_a_toggle_flips_what_it_is_given(self):
        toggle = settings.spec(settings.RANDOM_CUE)
        assert midi.target_value(toggle, 127, current=False) is True
        assert midi.target_value(toggle, 127, current=True) is False

    def test_a_toggle_with_nothing_to_read_turns_on(self):
        # The best a caller who could not read the parameter can do, and it is
        # the direction that shows something happened rather than nothing.
        toggle = settings.spec(settings.RANDOM_CUE)
        assert midi.target_value(toggle, 127) is True


class TestDispatch:
    CC = midi.Control(midi.CONTROL_CHANGE, 1, 13, "setting", settings.DWELL)
    BUTTON = midi.Control(midi.NOTE_ON, 1, 41, "command", "next")

    def test_an_unmapped_message_does_nothing(self, silent, monkeypatch):
        monkeypatch.setattr(midi, "LEARN", False)
        assert midi.on_message(midi.CONTROL_CHANGE, 1, 99, 64) is None
        assert silent == []

    def test_a_mapped_button_calls_the_transport_command(self, monkeypatch, silent):
        called = []
        monkeypatch.setattr(midi, "MAP", (self.BUTTON,))
        monkeypatch.setattr(player, "command", called.append)
        midi.on_message(midi.NOTE_ON, 1, 41, 127)
        assert called == ["next"]

    def test_a_button_release_does_not_call_it_again(self, monkeypatch, silent):
        called = []
        monkeypatch.setattr(midi, "MAP", (self.BUTTON, self.BUTTON._replace(
            message=midi.NOTE_OFF
        )))
        monkeypatch.setattr(player, "command", called.append)
        midi.on_message(midi.NOTE_ON, 1, 41, 127)
        midi.on_message(midi.NOTE_OFF, 1, 41, 0)
        assert called == ["next"]

    def test_a_mapped_cc_writes_the_setting(self, monkeypatch, silent):
        written = []
        monkeypatch.setattr(midi, "MAP", (self.CC,))
        monkeypatch.setattr(
            midi, "apply_setting", lambda name, message, value: written.append(name)
        )
        midi.on_message(midi.CONTROL_CHANGE, 1, 13, 64)
        assert written == [settings.DWELL]

    def test_an_unknown_kind_is_reported_rather_than_raised(self, monkeypatch, silent):
        monkeypatch.setattr(midi, "LEARN", False)
        monkeypatch.setattr(midi, "MAP", (self.CC._replace(kind="knob"),))
        assert midi.on_message(midi.CONTROL_CHANGE, 1, 13, 64) is None
        assert len(silent) == 1
        assert "knob" in silent[0]

    def test_control_for_finds_nothing_in_an_empty_map(self):
        assert midi.control_for(midi.CONTROL_CHANGE, 1, 13) is None


class TestDeviceTable:
    """`/local/midi/device`, authored rather than clicked.

    The MIDI In DAT hears nothing without a device mapping - measured, after a
    learn pass that reported nothing until the Device Mapper dialog had been
    used. What the dialog writes is a five-column Table DAT, so the build
    writes it instead and the `.toe` stays disposable.
    """

    HEADER = list(midi.DEVICE_COLUMNS)
    HAND_MADE = ["1", "Launch Control XL", "", "/local/midi/userdevices/x", "1"]

    def test_a_fresh_table_gets_a_header_and_our_row(self):
        rows = midi.device_table_rows(None)
        assert rows[0] == self.HEADER
        assert rows[1][0] == midi.DEVICE_ID
        assert rows[1][1] == midi.DEVICE_NAME
        assert len(rows) == 2

    def test_the_columns_are_the_ones_the_dialog_wrote(self):
        # Read off /local/midi/device on 2026-09-12. A column renamed or
        # reordered here is a table TouchDesigner will not read, and the
        # symptom is silence rather than an error.
        assert midi.DEVICE_COLUMNS == (
            "id", "indevice", "outdevice", "definition", "channel"
        )

    def test_the_out_device_is_claimed_now_the_buttons_have_lights(self):
        # It was empty while this project only listened, on the grounds that an
        # out device never written to is a claim on hardware for no reason.
        # The lamps are written back down the same cable, so it is the same
        # device in both columns.
        assert midi.device_row()[2] == midi.DEVICE_NAME
        assert midi.device_row()[1] == midi.DEVICE_NAME

    def test_a_definition_made_by_hand_is_kept(self):
        # The build authors the mapping; it does not get to throw away a MIDI
        # map somebody built in the dialog. Deleting that silently would be
        # the same mistake as saving the .toe, pointed the other way.
        rows = midi.device_table_rows([self.HEADER, self.HAND_MADE])
        assert rows[1][3] == "/local/midi/userdevices/x"

    def test_our_row_is_rewritten_rather_than_duplicated(self):
        stale = ["1", "Some Other Controller", "", "", "1"]
        rows = midi.device_table_rows([self.HEADER, stale])
        assert len(rows) == 2
        assert rows[1][1] == midi.DEVICE_NAME

    def test_another_device_is_left_alone(self):
        # ID 1 is this project's. A second controller somebody attaches later
        # is not, and a build that dropped it would be a surprising thing for
        # a movie player to do.
        other = ["2", "Some Other Controller", "", "", "1"]
        rows = midi.device_table_rows([self.HEADER, self.HAND_MADE, other])
        assert other in rows
        assert len(rows) == 3

    def test_the_header_is_not_duplicated_when_one_is_already_there(self):
        rows = midi.device_table_rows([self.HEADER, self.HAND_MADE])
        assert rows.count(self.HEADER) == 1

    def test_an_empty_row_is_dropped(self):
        rows = midi.device_table_rows([self.HEADER, [], self.HAND_MADE])
        assert [] not in rows

    def test_every_row_has_a_cell_per_column(self):
        rows = midi.device_table_rows([self.HEADER, self.HAND_MADE])
        assert all(len(row) == len(midi.DEVICE_COLUMNS) for row in rows)

    def test_the_id_is_a_string_because_a_dat_cell_is_text(self):
        assert isinstance(midi.DEVICE_ID, str)
        assert midi.device_row()[0] == midi.DEVICE_ID


class TestLights:
    """The button LEDs - views of the machine, not state of their own."""

    BOTH = {"playing": True, "fading": True}
    NEITHER = {"playing": False, "fading": False}

    def test_every_lamp_is_written_on_a_refresh(self):
        assert len(midi.light_messages(self.BOTH)) == len(midi.LIGHTS)

    def test_a_true_state_lights_its_lamp(self):
        sent = dict(midi.light_messages(self.BOTH))
        assert set(sent.values()) == {midi.LIGHT_ON}

    def test_a_false_state_darkens_it(self):
        sent = dict(midi.light_messages(self.NEITHER))
        assert set(sent.values()) == {midi.LIGHT_OFF}

    def test_the_two_lamps_are_independent(self):
        sent = dict(midi.light_messages({"playing": True, "fading": False}))
        assert sent[42] == midi.LIGHT_ON
        assert sent[74] == midi.LIGHT_OFF

    def test_the_pause_lamp_is_lit_while_playing(self):
        # The direction was a decision rather than an accident: lit means
        # running, dark means held.
        #
        # Asserted against the literal velocities rather than against
        # LIGHT_ON/LIGHT_OFF. Written the obvious way it compared the output
        # with the same constants that produced it, which made it a test of
        # self-consistency - it stayed green with the two swapped. 127 is what
        # actually goes down the wire and lights the lamp.
        playing = dict(midi.light_messages({"playing": True, "fading": False}))
        paused = dict(midi.light_messages({"playing": False, "fading": False}))
        assert playing[42] == 127
        assert paused[42] == 0

    def test_the_fade_lamp_is_lit_while_fading(self):
        fading = dict(midi.light_messages({"playing": True, "fading": True}))
        settled = dict(midi.light_messages({"playing": True, "fading": False}))
        assert fading[74] == 127
        assert settled[74] == 0

    def test_an_unknown_state_is_reported_and_skipped(self, silent, monkeypatch):
        # A light stuck on is worse than a light that never comes on, so a lamp
        # naming a state nobody answers is dropped rather than guessed at.
        monkeypatch.setattr(midi, "LIGHTS", (midi.Light(42, "nosuchstate"),))
        assert midi.light_messages(self.BOTH) == []
        assert len(silent) == 1
        assert "nosuchstate" in silent[0]

    def test_the_velocities_are_the_two_ends_of_the_range(self):
        # Not a colour. sendNoteOn's valid range depends on the Note Normalize
        # menu, whose tokens are in neither the help nor the stubs - the ends
        # clamp the same way under either setting, a middle value does not.
        assert (midi.LIGHT_OFF, midi.LIGHT_ON) == (0, 127)

    def test_every_lamp_sits_on_a_button_that_sends(self, monkeypatch):
        # A light on a button that sends nothing would be a lamp nobody can
        # reach. Held by a test rather than by merging the two tables, since a
        # button that sends without lighting is perfectly reasonable.
        monkeypatch.undo()  # this one asks about the real MAP, not the fixture's
        buttons = {e.index for e in midi.MAP if e.message == midi.NOTE_ON}
        for lamp in midi.LIGHTS:
            assert lamp.index in buttons

    def test_light_states_answers_every_state_a_lamp_asks_for(self, monkeypatch):
        # The two tables are written in different places and this is where they
        # have to agree. Faked because the real ones read the network.
        monkeypatch.setattr(player, "playing", lambda: True)
        monkeypatch.setattr(player, "is_fading", lambda: False)
        states = midi.light_states()
        for lamp in midi.LIGHTS:
            assert lamp.state in states


class TestTheMapIsHonest:
    def test_it_holds_the_controls_the_learn_pass_found(self, monkeypatch):
        # Replaces the placeholder that asserted MAP was empty, which existed
        # so that a map invented from a chart could not quietly pass as one
        # that had been measured. These three were read off the log on
        # 2026-09-12 with the controller in front of the listener.
        monkeypatch.undo()
        assert {entry.index for entry in midi.MAP} == {78, 50, 30, 42, 74}

    def test_no_button_is_mapped_on_its_release(self, monkeypatch):
        # The device sends Note On 127 then Note Off 0 for every press. is_press
        # already refuses the release, so a Note Off row would be a second way
        # to say the same thing - and the one that fires at the wrong end if
        # is_press were ever relaxed.
        monkeypatch.undo()
        assert not [e for e in midi.MAP if e.message == midi.NOTE_OFF]

    def test_every_control_is_on_the_channel_that_was_learned(self, monkeypatch):
        # Three different numbers are called channel here - the MIDI channel
        # (9), the device table's channel column (1), and the hardware's
        # "channel 1" meaning the leftmost strip. Keying on the wrong one
        # fails silently, because an unmapped message is a no-op by design.
        monkeypatch.undo()
        assert all(entry.channel == midi.CHANNEL for entry in midi.MAP)
        assert midi.CHANNEL == 9

    def test_no_two_controls_share_a_key(self, monkeypatch):
        # control_for returns the first match, so a duplicate would shadow
        # rather than raise, and the shadowed control would just go quiet.
        monkeypatch.undo()
        keys = [(e.message, e.channel, e.index) for e in midi.MAP]
        assert len(keys) == len(set(keys))

    def test_every_mapped_command_exists(self):
        for entry in midi.MAP:
            if entry.kind == "command":
                assert entry.target in player.COMMANDS

    def test_every_mapped_setting_exists(self):
        names = {item.name for item in settings.SETTINGS}
        for entry in midi.MAP:
            if entry.kind == "setting":
                assert entry.target in names
