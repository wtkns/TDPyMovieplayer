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
        speed = settings.spec(settings.SPEED_A)
        widened = speed._replace(maximum=speed.maximum * 2)
        assert midi.target_value(widened, midi.FULL) == speed.maximum * 2

    def test_normal_speed_sits_at_the_middle_of_a_knob(self):
        # Why the speed range is -2 to 4 rather than the symmetric -2 to 2 it
        # was first asked for: the midpoint of the range is where a knob's
        # centre detent lands, and 1 - ordinary playback - is what should be
        # there. A symmetric range would put 0 at the detent, which is a frozen
        # frame.
        #
        # 1.0 written as a literal, not as `spec.default`: the claim is about
        # where normal speed falls on the hardware, and comparing the range's
        # midpoint against the default it was chosen to match would be the same
        # number on both sides.
        for name in settings.SPEEDS:
            speed = settings.spec(name)
            assert (speed.minimum + speed.maximum) / 2 == 1.0, name

    def test_a_knob_at_its_detent_is_within_a_hair_of_normal_speed(self):
        # The residue of doing it with 128 steps: the exact midpoint falls
        # between CC 63 and 64 and neither is reachable, so the detent gives
        # 0.976 or 1.024 rather than 1. Recorded rather than fixed - a 2%
        # speed error is not audible or visible, and snapping would put a dead
        # zone in the middle of the knob.
        speed = settings.spec(settings.SPEED_A)
        for value in (midi.FULL // 2, midi.FULL // 2 + 1):
            assert abs(midi.target_value(speed, value) - 1.0) < 0.03

    def test_a_knob_at_the_bottom_plays_backwards(self):
        # The Movie File In TOP's help: "Negative values will play the movie
        # backwards." -2 is the literal the parameter receives at CC 0.
        assert midi.target_value(settings.spec(settings.SPEED_A), 0) == -2.0

    def test_a_pan_knob_sweeps_the_whole_field(self):
        for name in (settings.PAN_A, settings.PAN_B):
            pan = settings.spec(name)
            assert midi.target_value(pan, 0) == 0.0
            assert midi.target_value(pan, midi.FULL) == 1.0

    def test_an_exponent_of_one_is_the_even_sweep(self):
        # The anchor the whole family hangs off: raising a fraction to the
        # first power changes nothing, so a curve of 1 and no curve at all are
        # the same code path rather than two.
        dwell = settings.spec(settings.DWELL)
        for cc in (0, 32, 64, 96, 127):
            assert midi.target_value(dwell, cc, exponent=1.0) == pytest.approx(
                midi.target_value(dwell, cc)
            )

    def test_the_cubed_dwell_reaches_both_ends_of_its_range(self):
        # A taper must not cost the range its ends. The bottom is one frame of
        # 30fps media and the top is a minute; a curve that fell short of
        # either would have traded reach for resolution.
        dwell = settings.spec(settings.DWELL)
        assert midi.target_value(dwell, 0, exponent=3.0) == pytest.approx(1 / 30)
        assert midi.target_value(dwell, midi.FULL, exponent=3.0) == 60.0

    def test_the_bottom_of_the_dwell_fader_is_one_frame_and_not_a_stop(self):
        # The reversal, as the number that goes to the Timer CHOP. This used to
        # be 0, which the engine read as the timer off - so the fastest cutting
        # and no cutting at all were adjacent positions on one fader.
        dwell = settings.spec(settings.DWELL)
        assert midi.target_value(dwell, 0, exponent=3.0) > 0
        assert midi.target_value(dwell, 0, exponent=3.0) == pytest.approx(
            0.0333, abs=0.0005
        )

    def test_the_cubed_dwell_spends_a_quarter_of_the_fader_below_one_second(self):
        # The request, as a number. Written as literal CC positions and
        # literal seconds rather than derived from the curve, so a changed
        # exponent has to walk past this rather than moving the goalposts
        # with it: at cubed, CC 32 is about a second.
        dwell = settings.spec(settings.DWELL)
        assert midi.target_value(dwell, 32, exponent=3.0) == pytest.approx(
            0.99, abs=0.02
        )
        assert midi.target_value(dwell, 64, exponent=3.0) == pytest.approx(
            7.7, abs=0.1
        )

    def test_the_taper_gives_the_bottom_more_travel_than_the_top(self):
        # The property that was actually asked for, stated as the comparison
        # rather than as two magic numbers: 0-1s should get more of the fader
        # than 20-40s does. Linear fails this and cubed passes, which is why
        # squared was not enough - it reverses the ratio only partway.
        dwell = settings.spec(settings.DWELL)

        def steps(low, high, exponent):
            return sum(
                1 for cc in range(midi.FULL + 1)
                if low <= midi.target_value(dwell, cc, exponent=exponent) < high
            )

        assert steps(0, 1, 3.0) > steps(20, 40, 3.0)
        assert steps(0, 1, 1.0) < steps(20, 40, 1.0)

    def test_a_curveless_setting_sweeps_evenly(self):
        # Every setting but the dwell. Pan in particular must stay even, or
        # centre stops being the middle of the knob.
        assert settings.spec(settings.PAN_A).curve is None
        assert midi.curve_exponent(settings.spec(settings.PAN_A)) == 1.0

    def test_the_dwell_takes_its_exponent_from_another_setting(self, monkeypatch):
        # Not a constant in this module: the point of the indirection is that a
        # knob can be put on the exponent later without touching the map.
        dwell = settings.spec(settings.DWELL)
        assert dwell.curve == settings.DWELL_CURVE
        monkeypatch.setattr(settings, "value", lambda name: 2.0)
        assert midi.curve_exponent(dwell) == 2.0

    def test_an_exponent_of_zero_does_not_peg_the_fader_at_maximum(self):
        # `0 ** 0` is 1 in Python, so an unclamped exponent of 0 would make
        # every position answer the top of the range - a fader that reads full
        # everywhere and does not look broken. The parameter is clamped at 1;
        # this is the guard that does not depend on that being true.
        dwell = settings.spec(settings.DWELL)
        assert midi.target_value(dwell, 0, exponent=0.0) == pytest.approx(1 / 30)
        assert midi.target_value(dwell, 64, exponent=0.0) < 60.0

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

    #: Every state name a lamp asks for, all true and all false. Derived from
    #: LIGHTS rather than written out, so a lamp added to the table is covered
    #: by these without this class being edited - the previous version listed
    #: the two states by hand and every one of these tests broke when the
    #: surface went from one deck to two.
    BOTH = {lamp.state: True for lamp in midi.LIGHTS}
    NEITHER = {lamp.state: False for lamp in midi.LIGHTS}

    def test_every_lamp_is_written_on_a_refresh(self):
        assert len(midi.light_messages(self.BOTH)) == len(midi.LIGHTS)

    def test_a_true_state_lights_its_lamp(self):
        sent = dict(midi.light_messages(self.BOTH))
        assert set(sent.values()) == {midi.LIGHT_ON}

    def test_a_false_state_darkens_it(self):
        sent = dict(midi.light_messages(self.NEITHER))
        assert set(sent.values()) == {midi.LIGHT_OFF}

    def test_each_lamp_answers_only_its_own_state(self):
        # One state true at a time, and only that lamp lights. A lamp reading
        # the wrong state is the failure that looks like a wiring mistake on
        # the controller rather than a table with two rows the same way round.
        for lamp in midi.LIGHTS:
            states = dict(self.NEITHER, **{lamp.state: True})
            sent = dict(midi.light_messages(states))
            assert sent[lamp.index] == 127, lamp
            for other in midi.LIGHTS:
                if other.index != lamp.index:
                    assert sent[other.index] == 0, (lamp, other)

    def test_the_pause_lamp_is_lit_while_its_own_deck_runs(self):
        # The direction was a decision rather than an accident: lit means
        # running, dark means held.
        #
        # Asserted against the literal velocities rather than against
        # LIGHT_ON/LIGHT_OFF. Written the obvious way it compared the output
        # with the same constants that produced it, which made it a test of
        # self-consistency - it stayed green with the two swapped. 127 is what
        # actually goes down the wire and lights the lamp.
        running = dict(midi.light_messages(dict(self.NEITHER, playing_a=True)))
        held = dict(midi.light_messages(dict(self.NEITHER, playing_a=False)))
        assert running[42] == 127
        assert held[42] == 0

    def test_one_deck_running_does_not_light_the_other(self):
        # The whole point of the surface going per-deck. Player A paused while
        # B runs is a state the single-lamp version could not show at all.
        sent = dict(midi.light_messages(dict(self.NEITHER, playing_b=True)))
        assert sent[42] == 0
        assert sent[43] == 127

    def test_the_live_lamp_follows_the_deck_the_cross_settles_on(self):
        sent = dict(midi.light_messages(dict(self.NEITHER, live_b=True)))
        assert sent[74] == 0
        assert sent[75] == 127

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
        monkeypatch.setattr(player, "playing_at", lambda index: True)
        monkeypatch.setattr(player, "is_live", lambda index: False)
        states = midi.light_states()
        for lamp in midi.LIGHTS:
            assert lamp.state in states

    def test_light_states_asks_each_deck_about_itself(self, monkeypatch):
        # A per-deck reading that passed the same index twice would light both
        # lamps together and look like a controller fault. The doubles record
        # which index they were handed rather than what they were asked.
        asked = []
        monkeypatch.setattr(player, "playing_at", lambda index: asked.append(index))
        monkeypatch.setattr(player, "is_live", lambda index: False)
        midi.light_states()
        assert asked == [0, 1]


class TestTheMapIsHonest:
    def test_it_holds_the_controls_the_learn_pass_found(self, monkeypatch):
        # Replaces the placeholder that asserted MAP was empty, which existed
        # so that a map invented from a chart could not quietly pass as one
        # that had been measured. Read off the device rather than off a chart:
        # five controls on 2026-09-12, extended to two full channel strips on
        # 2026-09-13 when the mixer gave column 2 something to drive.
        monkeypatch.undo()
        assert {entry.index for entry in midi.MAP} == {
            14, 30, 50, 78, 42, 74,   # column 1 - player A
            15, 31, 51, 79, 43, 75,   # column 2 - player B
        }

    def test_the_two_columns_hold_the_same_controls_one_deck_apart(self, monkeypatch):
        # Column 2's index is column 1's plus one on every row of the device.
        # Worth pinning because 74 was given for both Next buttons when the
        # map was dictated, and a duplicated key does not raise - control_for
        # returns the first match and the second control simply goes quiet.
        monkeypatch.undo()
        indexes = {entry.index for entry in midi.MAP}
        for first in (14, 30, 50, 78, 42, 74):
            assert first in indexes
            assert first + 1 in indexes

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
