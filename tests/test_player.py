"""Tests for the transport's decision-making.

Same rule as `test_playlist.py`: this runs at a normal prompt, with no
TouchDesigner. That is possible for exactly the parts of `player.py` that were
written to make it possible - `next_index` takes a list of strings, and
`clip_paths` takes anything shaped like a Table DAT. The functions that reach
for `td.op` are not tested here, because a test of those would be a test of a
stub of TouchDesigner rather than of this project.

`startup.report` is stubbed out wherever a test drives a reporting path. It
appends to `logs/startup.log`, which is a record of launches, and a test suite
writing into it would leave lines there that never happened in a session.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from tdpy import player, settings, startup  # noqa: E402


class Cell:
    """The one thing this code asks of a DAT cell: a `.val`."""

    def __init__(self, val):
        self.val = val


class FakeTable:
    """A Table DAT's `col()`, and nothing else.

    Returns None for an unknown column, which is what a DAT does, and includes
    the header cell in the column, which is also what a DAT does - both are the
    behaviours `clip_paths` is written against.
    """

    path = "/project1/generated/playlist"

    def __init__(self, columns):
        self.columns = {name: [Cell(v) for v in values]
                        for name, values in columns.items()}

    def col(self, name):
        return self.columns.get(name)


@pytest.fixture
def silent(monkeypatch):
    """Collect reported lines instead of writing them to the log."""
    lines = []
    monkeypatch.setattr(startup, "report", lines.append)
    return lines


class TestStepIndex:
    """What `next_index` used to cover, in deck terms, plus the new direction.

    The transport moves through the *deck*, so this answers playlist rows from
    deck positions. Unshuffled the two coincide, which is why most of these
    read like the old sequential tests - the shuffled cases below are where
    they stop coinciding.
    """

    def test_steps_forward_one(self):
        assert player.step_index([0, 1, 2], 0, 1) == 1
        assert player.step_index([0, 1, 2], 1, 1) == 2

    def test_steps_backward_one(self):
        assert player.step_index([0, 1, 2], 2, -1) == 1
        assert player.step_index([0, 1, 2], 1, -1) == 0

    def test_wraps_at_the_end(self):
        assert player.step_index([0, 1, 2], 2, 1) == 0

    def test_wraps_at_the_beginning(self):
        assert player.step_index([0, 1, 2], 0, -1) == 2

    def test_a_single_clip_is_its_own_successor_and_predecessor(self):
        assert player.step_index([0], 0, 1) == 0
        assert player.step_index([0], 0, -1) == 0

    def test_an_unknown_clip_starts_at_an_end(self):
        # Both cases that produce one: a build that loaded no file, and a clip
        # since removed from media/. Next lands on the first card, previous on
        # the last - the same courtesy in both directions.
        assert player.step_index([0, 1, 2], None, 1) == 0
        assert player.step_index([0, 1, 2], None, -1) == 2
        assert player.step_index([0, 1, 2], 9, 1) == 0
        assert player.step_index([0, 1, 2], 9, -1) == 2

    def test_an_empty_deck_has_no_next(self):
        # None rather than 0: there is no card to turn over, and _step has to
        # tell that apart from "play the first one".
        assert player.step_index([], 0, 1) is None
        assert player.step_index([], None, -1) is None

    def test_follows_the_deck_and_not_the_table(self):
        # The point of the whole function. In this deck the clip after
        # playlist row 0 is row 1's neighbour in the *deck*, which is row 3.
        assert player.step_index([2, 0, 3, 1], 0, 1) == 3
        assert player.step_index([2, 0, 3, 1], 0, -1) == 2

    def test_a_step_of_zero_stays_put(self):
        assert player.step_index([0, 1, 2], 1, 0) == 1

    def test_takes_any_sequence_not_only_a_list(self):
        # play_order returns a list, but nothing should depend on that.
        assert player.step_index((0, 1, 2), 0, 1) == 1


class TestDeck:
    def test_no_seed_is_the_playlists_own_order(self):
        # What a launch starts in: the files play in the order they sit in
        # media/ until somebody presses shuffle.
        assert player.deck(4) == [0, 1, 2, 3]
        assert player.deck(4, None) == [0, 1, 2, 3]

    def test_a_seed_shuffles(self):
        assert player.deck(20, 12345) != list(range(20))

    def test_every_row_appears_exactly_once(self):
        # The property that makes this a deck rather than repeated random
        # draws: a clip cannot come up again until every other one has played.
        # A shuffle that dropped or duplicated a row would show up here rather
        # than as clips that mysteriously never play.
        for seed in (None, 1, 12345, 999999):
            assert sorted(player.deck(20, seed)) == list(range(20))

    def test_the_same_seed_deals_the_same_deck(self):
        # The reason a seed is stored rather than an order - a sequence that
        # did something interesting can be replayed from the log.
        assert player.deck(20, 4242) == player.deck(20, 4242)

    def test_different_seeds_deal_different_decks(self):
        assert player.deck(20, 1) != player.deck(20, 2)

    def test_an_empty_playlist_deals_an_empty_deck(self):
        assert player.deck(0) == []
        assert player.deck(0, 12345) == []

    def test_a_negative_count_is_not_a_negative_range(self):
        assert player.deck(-1) == []

    def test_one_clip_shuffles_to_itself(self):
        assert player.deck(1, 12345) == [0]

    def test_covers_the_playlist_it_was_measured_from(self):
        paths = ["a", "b", "c", "d"]
        assert sorted(paths[i] for i in player.deck(len(paths), 7)) == sorted(paths)


class TestSeedAndShuffle:
    """The seed is module state, so every test here puts it back.

    Not a fixture on the class, because a test that failed halfway would
    otherwise leave a shuffled deck behind for whatever ran next - which is
    exactly the kind of order-dependent failure this suite should not be able
    to produce.
    """

    @pytest.fixture(autouse=True)
    def restore_seed(self):
        before = player.SEED
        yield
        player.SEED = before

    @pytest.fixture(autouse=True)
    def no_redraw(self, monkeypatch):
        # _redraw reaches into TouchDesigner for the List COMP. The seed is
        # what these tests are about.
        monkeypatch.setattr(player, "_redraw", lambda: None)

    def test_a_launch_starts_in_playlist_order(self):
        # The default this project ships in, and the thing jms asked for
        # explicitly: shuffle is a button, not a mode it boots into.
        assert player.SEED is None

    def test_play_order_follows_the_seed(self, silent):
        assert player.play_order(6) == [0, 1, 2, 3, 4, 5]
        player.set_seed(31337)
        assert player.play_order(6) == player.deck(6, 31337)

    def test_set_seed_none_restores_playlist_order(self, silent):
        player.set_seed(31337)
        player.set_seed(None)
        assert player.play_order(6) == [0, 1, 2, 3, 4, 5]

    def test_shuffle_picks_a_seed_and_reports_it(self, silent):
        seed = player.shuffle()
        assert player.SEED == seed
        assert str(seed) in silent[-1]

    def test_shuffle_actually_changes_the_order(self, silent):
        player.shuffle()
        assert player.play_order(20) != list(range(20))

    def test_the_reported_seed_reproduces_the_order(self, silent):
        seed = player.shuffle()
        dealt = player.play_order(20)
        player.set_seed(None)
        player.set_seed(seed)
        assert player.play_order(20) == dealt

    def test_set_seed_takes_a_string_from_the_textport(self, silent):
        player.set_seed("4242")
        assert player.SEED == 4242

    def test_playlist_order_says_so_rather_than_printing_none(self, silent):
        player.set_seed(None)
        assert "None" not in silent[-1]


class TestClipPaths:
    def test_drops_the_header_row(self):
        table = FakeTable({"path": ["path", "media/one.mkv", "media/two.mkv"]})
        assert player.clip_paths(table) == ["media/one.mkv", "media/two.mkv"]

    def test_a_header_only_table_is_empty(self):
        assert player.clip_paths(FakeTable({"path": ["path"]})) == []

    def test_no_table_at_all_is_empty(self):
        assert player.clip_paths(None) == []

    def test_a_missing_column_reports_and_returns_empty(self, silent):
        table = FakeTable({"name": ["name", "one.mkv"]})
        assert player.clip_paths(table) == []
        assert len(silent) == 1
        assert "path" in silent[0]

    def test_reads_by_column_name_not_position(self):
        # playlist.COLUMNS decides the order; this should not have to agree
        # with it separately.
        table = FakeTable(
            {
                "name": ["name", "one.mkv"],
                "path": ["path", "media/one.mkv"],
            }
        )
        assert player.clip_paths(table) == ["media/one.mkv"]


class TestCommand:
    def test_every_button_in_the_build_has_a_command(self):
        # The one place the two halves are checked against each other: build.py
        # names the buttons, player.py implements them, and nothing at runtime
        # would notice a button wired to nothing until it was pressed.
        from tdpy import build

        names = {name for name, _ in build.CONTROL_BUTTONS}
        assert names == set(player.COMMANDS)

    def test_an_unknown_command_reports_rather_than_raises(self, silent):
        assert player.command("rewind") is None
        assert len(silent) == 1
        assert "rewind" in silent[0]

    def test_the_report_lists_what_is_available(self, silent):
        player.command("rewind")
        for name in player.COMMANDS:
            assert name in silent[0]


class TestCurrentIndex:
    def test_finds_the_loaded_clip(self):
        assert player.current_index(["a", "b", "c"], "b") == 1

    def test_the_first_clip_is_zero_not_falsy_by_accident(self):
        # 0 is a real answer here, which is the whole reason the "no answer"
        # case below is None rather than 0.
        assert player.current_index(["a", "b"], "a") == 0

    def test_an_unknown_clip_is_none_not_the_top(self):
        # Deliberately not next_index's answer to the same question. There, an
        # unknown clip means "start at the top"; here it means "nothing is
        # playing", and answering 0 would highlight a row that is not playing.
        assert player.current_index(["a", "b"], "gone.mkv") is None
        assert player.current_index(["a", "b"], "") is None

    def test_an_empty_playlist_is_none(self):
        assert player.current_index([], "a") is None


class TestCurrentIndex:
    def test_finds_the_loaded_clip(self):
        assert player.current_index(["a", "b", "c"], "b") == 1

    def test_the_first_clip_is_zero_not_falsy_by_accident(self):
        # 0 is a real answer here, which is the whole reason the "no answer"
        # case below is None rather than 0.
        assert player.current_index(["a", "b"], "a") == 0

    def test_an_unknown_clip_is_none_not_the_top(self):
        # Deliberately not next_index's answer to the same question. There, an
        # unknown clip means "start at the top"; here it means "nothing is
        # playing", and answering 0 would highlight a row that is not playing.
        assert player.current_index(["a", "b"], "gone.mkv") is None
        assert player.current_index(["a", "b"], "") is None

    def test_an_empty_playlist_is_none(self):
        assert player.current_index([], "a") is None


class TestPlayOrder:
    def test_is_the_table_order_today(self):
        assert player.play_order(3) == [0, 1, 2]

    def test_an_empty_playlist_is_an_empty_order(self):
        assert player.play_order(0) == []

    def test_a_negative_count_is_not_a_negative_range(self):
        assert player.play_order(-1) == []

    def test_every_row_appears_exactly_once(self):
        # The property Phase 4's shuffled deck has to keep when it replaces the
        # body of this function - a deck that drops or repeats a row would show
        # up here rather than as clips that never play.
        order = player.play_order(20)
        assert sorted(order) == list(range(20))

    def test_covers_the_playlist_it_was_measured_from(self):
        paths = ["a", "b", "c", "d"]
        order = player.play_order(len(paths))
        assert [paths[i] for i in order] == paths


class FakePar:
    """A Par as far as this code uses one: a value, read two ways.

    `.val` is what `startup.set_par` writes and `.eval()` is what `on_dwell_
    change` reads, and they are the same number here - which is true of an
    unbound parameter and is the case being tested.
    """

    def __init__(self, val):
        self.val = val

    def eval(self):
        return self.val


class FakePars:
    """An operator's `.par`, carrying whichever parameters a test needs."""

    def __init__(self, **values):
        for name, value in values.items():
            setattr(self, name, FakePar(value))


class FakeOp:
    """An operator with a Play parameter, which is all the dwell reads.

    Both operands are shaped the same: the timer's Play is what gets written and
    the player's Play is what gets read, and neither needs anything else. The
    timer also carries a clock, and `masterSeconds` starts at something other
    than 0 so a test can tell a restart from a timer that was already at zero.
    """

    def __init__(self, path, play=0):
        self.path = path
        self.par = FakePars(play=play)
        self.masterSeconds = 99.0


@pytest.fixture
def setting(monkeypatch):
    """The settings a decision reads, without a settings COMP to read them off.

    Defaults are the launch defaults from `settings.SETTINGS`, so a test that
    changes nothing is testing the behaviour of a fresh launch. Returns the dict
    for a test to alter.
    """
    values = {
        settings.ADVANCE_ON_END: True,
        settings.RANDOM_CUE: False,
        settings.DWELL: 0.0,
        settings.SPEED: 1.0,
    }
    monkeypatch.setattr(settings, "value", values.get)
    return values


@pytest.fixture
def advanced(monkeypatch):
    """Record calls to next_clip instead of reaching for a player TOP."""
    calls = []
    monkeypatch.setattr(player, "next_clip", lambda: calls.append("next"))
    return calls


@pytest.fixture
def clip(monkeypatch):
    """A player TOP whose Play can be moved, and no playlist behind it.

    Stubbed at `_ops`, which since Phase 6 answers *the live player* rather than
    the only one - so a test of the dwell still gets one operator and does not
    have to know there are two behind it.
    """
    node = FakeOp("/project1/generated/playerA", play=True)
    monkeypatch.setattr(player, "_ops", lambda: (node, None))
    return node


class FakeFadeState:
    """The Constant CHOP holding the fade's two ends.

    Only its two value parameters, which is all `fade_target` reads and all
    `_begin_fade` writes.
    """

    path = "/project1/generated/fadeState"

    def __init__(self, start=0.0, target=0.0):
        self.par = FakePars(const0value=start, const1value=target)


@pytest.fixture
def fade_state(monkeypatch):
    """A fade state settled on the first player, with a container behind it.

    `_container` is stubbed to something that is merely not None, because the
    functions under test reach it only to pass it to `_fade_state`, which is
    stubbed too.
    """
    state = FakeFadeState()
    monkeypatch.setattr(player, "_container", lambda: object())
    monkeypatch.setattr(player, "_fade_state", lambda container: state)
    return state


@pytest.fixture
def live(monkeypatch):
    """Whether the player that looped is the one on screen.

    A one-item list so a test can flip it: `live[0] = False` is the hidden
    player wrapping while it waits, which is the case two players introduced.
    """
    answer = [True]
    monkeypatch.setattr(player, "looped_player_is_live", lambda name: answer[0])
    return answer


@pytest.fixture
def timer(monkeypatch):
    """The dwell timer, stubbed at the lookup rather than at the container."""
    node = FakeOp("/project1/generated/dwell")
    monkeypatch.setattr(player, "dwell_timer", lambda: node)
    return node


class TestCueFraction:
    """Where a clip starts. A fraction, so it needs no duration to be right."""

    def test_off_is_the_head_of_the_clip(self):
        assert player.cue_fraction(False) == 0.0

    def test_on_draws_a_fraction(self):
        assert player.cue_fraction(True, draw=lambda: 0.42) == 0.42

    def test_off_does_not_draw_at_all(self):
        # Not just "returns 0" - nothing is consumed from the random stream, so
        # a launch with random cue off is reproducible clip for clip.
        def refuse():
            raise AssertionError("drew a cue point with random cue off")

        assert player.cue_fraction(False, draw=refuse) == 0.0

    def test_the_default_draw_stays_inside_the_clip(self):
        # random.random answers [0.0, 1.0), so a clip is never cued to exactly
        # its own end - which with Extend Right on Cycle would loop instantly.
        for _ in range(200):
            fraction = player.cue_fraction(True)
            assert 0.0 <= fraction < 1.0

    def test_a_falsy_setting_is_off(self):
        # settings.value answers a float for a toggle read through eval(), so
        # 0.0 has to mean off as surely as False does.
        assert player.cue_fraction(0.0) == 0.0
        assert player.cue_fraction(1.0, draw=lambda: 0.7) == 0.7


class TestOnLoop:
    """The end-of-file policy: one toggle over players that always loop.

    Two players now, and only the one on screen counts - `looped_player_is_live`
    is the question, and it is stubbed here so these stay tests of the policy
    rather than of the fade state behind it. `TestLoopedPlayerIsLive` covers the
    question itself.
    """

    def test_advances_when_advance_at_end_is_on(self, setting, live, advanced):
        player.on_loop("playerAInfo")
        assert advanced == ["next"]

    def test_leaves_the_clip_looping_when_it_is_off(self, setting, live, advanced):
        setting[settings.ADVANCE_ON_END] = False
        player.on_loop("playerAInfo")
        assert advanced == []

    def test_the_launch_default_advances(self, setting, live, advanced):
        # The one automatic behaviour that is on at launch, because with no
        # timer running and nothing pressed, nothing else would ever advance.
        assert setting[settings.ADVANCE_ON_END] is True
        player.on_loop("playerAInfo")
        assert advanced == ["next"]

    def test_the_hidden_player_looping_advances_nothing(
        self, setting, live, advanced
    ):
        # The case the second player introduced, and the one that would look
        # like the transport had lost its mind: a preloaded clip shorter than
        # the dwell wraps repeatedly while it waits to be shown, and every wrap
        # arrives here.
        live[0] = False
        player.on_loop("playerBInfo")
        assert advanced == []

    def test_the_setting_is_not_even_read_for_the_hidden_player(
        self, monkeypatch, live, advanced
    ):
        # Which player looped is asked first. Reading the toggle for a loop that
        # cannot advance anything would be harmless today and misleading to
        # anyone reading the order later.
        def refuse(name):
            raise AssertionError(f"read {name} for a loop that is not on screen")

        monkeypatch.setattr(settings, "value", refuse)
        live[0] = False
        player.on_loop("playerBInfo")
        assert advanced == []


class TestLoopedPlayerIsLive:
    """Turning the name of a watcher's Info CHOP into a yes or no."""

    def test_the_live_players_info_chop_is_live(self, fade_state):
        fade_state.par.const1value.val = 0.0
        assert player.looped_player_is_live("playerAInfo") is True
        assert player.looped_player_is_live("playerBInfo") is False

    def test_it_follows_the_fade_target(self, fade_state):
        fade_state.par.const1value.val = 1.0
        assert player.looped_player_is_live("playerBInfo") is True
        assert player.looped_player_is_live("playerAInfo") is False

    def test_an_unknown_watcher_advances_nothing(self, fade_state, silent):
        # A watcher wired to an operator this module has never heard of should
        # not advance the playlist, and should say so rather than fail silently.
        assert player.looped_player_is_live("somethingElse") is False
        assert any("somethingElse" in line for line in silent)

    def test_no_container_is_not_live(self, monkeypatch):
        monkeypatch.setattr(player, "_container", lambda: None)
        assert player.looped_player_is_live("playerAInfo") is False


class TestFadeSeconds:
    """The fade's length: a fraction of the dwell, so a product of two."""

    def test_a_fraction_of_the_dwell(self):
        assert player.fade_seconds(10.0, 0.2) == 2.0
        assert player.fade_seconds(4.0, 0.5) == 2.0

    def test_a_fade_of_zero_is_a_hard_cut(self):
        assert player.fade_seconds(10.0, 0.0) == 0.0

    def test_a_full_fade_is_the_whole_dwell(self):
        # Fade 1 is a player that is never settled on one clip - the top of the
        # slider is a real mode, the way the bottom of the dwell is.
        assert player.fade_seconds(10.0, 1.0) == 10.0

    def test_no_dwell_means_no_fade(self):
        # The consequence of making fade a fraction: with the dwell timer off
        # there is nothing for the fraction to be a fraction of, so a next press
        # and an end-of-file advance both cut hard.
        assert player.fade_seconds(0.0, 0.5) == 0.0

    def test_negatives_answer_zero_rather_than_a_negative_length(self):
        # Both parameters clamp at the bottom on the settings COMP, so this is
        # the belt to that braces: a Timer CHOP given a negative length fails
        # with no obvious symptom.
        assert player.fade_seconds(-4.0, 0.5) == 0.0
        assert player.fade_seconds(4.0, -0.5) == 0.0

    def test_answers_a_float_from_whatever_a_parameter_gives(self):
        # Both arrive from Par.eval(), which can hand back an int.
        assert player.fade_seconds(10, 1) == 10.0
        assert isinstance(player.fade_seconds(10, 1), float)


class TestFadeTarget:
    """Which player is live, read off the network rather than remembered."""

    def test_zero_is_the_first_player(self, fade_state):
        fade_state.par.const1value.val = 0.0
        assert player.fade_target(fade_state) == 0

    def test_one_is_the_second_player(self, fade_state):
        fade_state.par.const1value.val = 1.0
        assert player.fade_target(fade_state) == 1

    def test_a_missing_fade_state_answers_the_first_player(self):
        # Rather than None. Every caller indexes a two-item list with this, and
        # a build with no fade state in it should still play something.
        assert player.fade_target(None) == 0

    def test_it_answers_during_a_fade_and_not_only_at_rest(self, fade_state):
        # The property the clip list depends on: target is written once per cut
        # and holds, so the highlight moves to the incoming clip when the fade
        # begins rather than flipping halfway through it. Nothing about a fade
        # in progress is visible in this number, which is the point.
        fade_state.par.const0value.val = 0.0
        fade_state.par.const1value.val = 1.0
        assert player.fade_target(fade_state) == 1


class TestOnDwell:
    """The dwell policy, including the cycle that is the timer starting."""

    def test_the_first_cycle_beginning_is_not_a_dwell(self, setting, clip, advanced):
        # Cycle index 0 is the timer being started. Advancing on it would cut a
        # clip the instant it was loaded, because _step restarts the clock.
        setting[settings.DWELL] = 5.0
        player.on_dwell(0)
        assert advanced == []

    def test_a_later_cycle_advances(self, setting, clip, advanced):
        setting[settings.DWELL] = 5.0
        player.on_dwell(1)
        player.on_dwell(7)
        assert advanced == ["next", "next"]

    def test_a_dwell_of_zero_advances_nothing(self, setting, clip, advanced):
        setting[settings.DWELL] = 0.0
        player.on_dwell(3)
        assert advanced == []

    def test_a_paused_clip_is_not_cut_away(self, setting, clip, advanced):
        # A cycle already in flight when the clip was paused. The timer's Play
        # follows the pause a frame later, so the condition is asked again here -
        # otherwise a held frame could still be cut away once.
        setting[settings.DWELL] = 5.0
        clip.par.play.val = False
        player.on_dwell(3)
        assert advanced == []

    def test_a_negative_cycle_is_refused_like_zero(self, setting, clip, advanced):
        setting[settings.DWELL] = 5.0
        player.on_dwell(-1)
        assert advanced == []


class TestDwellShouldRun:
    """Both inputs, as a function, because both are opinions about a value."""

    def test_needs_a_dwell_and_a_playing_clip(self):
        assert player.dwell_should_run(4.0, True) is True

    def test_a_dwell_of_zero_is_off(self):
        assert player.dwell_should_run(0.0, True) is False

    def test_a_paused_clip_is_not_counted_down(self):
        # What pause means: hold this frame. A player that cut away from a held
        # frame once the dwell expired would make pause narrower than it reads.
        assert player.dwell_should_run(4.0, False) is False

    def test_neither_is_off(self):
        assert player.dwell_should_run(0.0, False) is False

    def test_answers_a_bool_from_the_floats_a_parameter_gives(self):
        # Both arguments arrive from Par.eval(), so both can be floats - and the
        # answer is assigned to a Toggle, which should get True rather than 1.0.
        assert player.dwell_should_run(4.0, 1.0) is True
        assert player.dwell_should_run(4.0, 0.0) is False


class TestRefreshDwell:
    """Recomputing the timer's Play from both inputs, whichever one moved."""

    def test_a_dwell_above_zero_starts_the_timer(self, setting, timer, clip, silent):
        setting[settings.DWELL] = 4.0
        player.refresh_dwell()
        assert timer.par.play.val is True

    def test_a_dwell_of_zero_stops_it(self, setting, timer, clip, silent):
        timer.par.play.val = True
        setting[settings.DWELL] = 0.0
        player.refresh_dwell()
        assert timer.par.play.val is False

    def test_a_paused_clip_stops_it(self, setting, timer, clip, silent):
        # The whole point of the second watcher: the dwell is untouched and the
        # timer stops anyway, because the clip is not playing.
        timer.par.play.val = True
        setting[settings.DWELL] = 4.0
        clip.par.play.val = False
        player.refresh_dwell()
        assert timer.par.play.val is False

    def test_resuming_continues_rather_than_starting_over(
        self, setting, timer, clip, silent
    ):
        # Nothing here restarts the clock - that belongs to a clip change, and
        # `_step` does it. So pause and resume continue, which is what pause
        # means; `masterSeconds` keeps meaning "how long this clip has played".
        setting[settings.DWELL] = 4.0
        clip.par.play.val = False
        player.refresh_dwell()
        clip.par.play.val = True
        player.refresh_dwell()
        assert timer.par.play.val is True
        assert timer.masterSeconds == 99.0

    def test_only_a_change_of_mode_is_logged(self, setting, timer, clip, silent):
        setting[settings.DWELL] = 4.0
        player.refresh_dwell()
        assert len(silent) == 1
        # Second call changes nothing, so it says nothing - otherwise dragging
        # the slider would fill a log kept for launches with a record of a drag.
        player.refresh_dwell()
        assert len(silent) == 1

    def test_a_missing_timer_is_not_an_exception(self, setting, clip, monkeypatch):
        # `dwell_timer` has already said which node is missing; this only has to
        # not take the Parameter Execute callback down with it.
        monkeypatch.setattr(player, "dwell_timer", lambda: None)
        assert player.refresh_dwell() is None

    def test_a_missing_player_is_not_an_exception(self, setting, timer, monkeypatch):
        monkeypatch.setattr(player, "_ops", lambda: (None, None))
        assert player.refresh_dwell() is None
