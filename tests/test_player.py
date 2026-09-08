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

from tdpy import player, startup  # noqa: E402


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
