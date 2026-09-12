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
    """A player TOP whose Play can be moved, and no playlist behind it."""
    node = FakeOp("/project1/generated/player", play=True)
    monkeypatch.setattr(player, "_ops", lambda: (node, None))
    return node


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
    """The end-of-file policy: one toggle over a player that always loops."""

    def test_advances_when_advance_at_end_is_on(self, setting, advanced):
        player.on_loop()
        assert advanced == ["next"]

    def test_leaves_the_clip_looping_when_it_is_off(self, setting, advanced):
        setting[settings.ADVANCE_ON_END] = False
        player.on_loop()
        assert advanced == []

    def test_the_launch_default_advances(self, setting, advanced):
        # The one automatic behaviour that is on at launch, because with no
        # timer running and nothing pressed, nothing else would ever advance.
        assert setting[settings.ADVANCE_ON_END] is True
        player.on_loop()
        assert advanced == ["next"]


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
