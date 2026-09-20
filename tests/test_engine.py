"""Tests for Phase 9.4: the generated component, and both ends of its boundary.

What is tested is the text that ships and the decisions made about it. The
bootstrap is generated source that runs in another process, where a mistake
surfaces only as an Engine COMP error at launch - so it is executed here, from
the string the host writes, rather than from a copy of the logic.

The boundary itself is two one-way paths and they are tested separately: the
host pulsing a command into the engine (`send`), and the engine answering it
(`on_command`). Between them sits a name that is spelled in two processes,
which is what `test_link.py` guards.

Expected names and expressions are literals, per `test_link.py`: the host and
the engine spelling one thing two ways is the failure these guard against.
"""

import ast
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tdpy import build, engine, link, startup  # noqa: E402

#: A path with everything that breaks naive quoting: spaces, backslashes, and a
#: backslash before a letter that would otherwise be an escape.
AWKWARD = r"C:\Users\jms\Documents\wtkns.com\300-Code\330 - TouchDesigner\new tdpy"


@pytest.fixture
def silent(monkeypatch):
    lines = []
    monkeypatch.setattr(startup, "report", lines.append)
    return lines


@pytest.fixture(autouse=True)
def host_process(monkeypatch):
    """Every test starts in the host, where `ROOT` is None.

    `engine.main` sets it, and a module global that survived one test would
    make the next one's `player` lookups reach for a component that is not
    there - the order-dependent failure this suite should not be able to
    produce.
    """
    monkeypatch.setattr(engine, "ROOT", None)


def _bootstrap_namespace(repo=AWKWARD):
    """The bootstrap executed as its DAT would be, without calling onCreate."""
    namespace = {}
    exec(compile(engine.bootstrap_source(repo), "bootstrap", "exec"), namespace)
    return namespace


class TestBootstrap:
    def test_the_generated_text_is_python(self):
        ast.parse(engine.bootstrap_source(AWKWARD))

    def test_the_repository_path_arrives_exactly(self):
        assert _bootstrap_namespace()["REPO"] == AWKWARD

    def test_the_package_it_purges_is_tdpy(self):
        assert _bootstrap_namespace()["PACKAGE"] == "tdpy"

    def test_it_is_driven_by_on_create_and_not_on_start(self):
        # Engine_COMP.htm: under TouchEngine "an Execute DAT's onStart() and
        # onExit() method will never be executed", and onCreate() runs on load.
        namespace = _bootstrap_namespace()
        assert "onCreate" in namespace
        assert "onStart" not in namespace
        assert "onExit" not in namespace

    def test_it_imports_nothing_outside_the_standard_library_at_module_scope(self):
        tree = ast.parse(engine.bootstrap_source(AWKWARD))
        imported = [
            alias.name for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        ]
        assert imported == ["sys"]


class TestPurge:
    MODULES = ("tdpy", "tdpy.player", "tdpy.engine", "tdpyx", "spikes.baseline", "os")

    def purged(self):
        purge = _bootstrap_namespace()["purge"]
        modules = {name: object() for name in self.MODULES}
        stale = purge(modules, "tdpy")
        return set(modules), set(stale)

    def test_the_package_and_every_submodule_go(self):
        _, stale = self.purged()
        assert stale == {"tdpy", "tdpy.player", "tdpy.engine"}

    def test_a_module_that_only_starts_with_the_name_stays(self):
        # tdpyx is not tdpy. A prefix test without the dot would drop it.
        remaining, _ = self.purged()
        assert "tdpyx" in remaining

    def test_everything_else_is_left_alone(self):
        remaining, _ = self.purged()
        assert remaining == {"tdpyx", "spikes.baseline", "os"}


class FakeConnector:
    def __init__(self, description):
        self.description = description
        self.connected = []

    def connect(self, target):
        self.connected.append(target)


class FakePar:
    """A parameter that can be put into Expression mode, and nothing else."""

    def __init__(self):
        self.expr = None
        self.mode = None


class FakePulsePar:
    def __init__(self):
        self.pulses = 0

    def pulse(self):
        self.pulses += 1


class FakeParMode:
    """Stands in for `tdutils.TDDefinitions.ParMode`, which needs the install."""

    EXPRESSION = "expression"
    BIND = "bind"


@pytest.fixture
def par_mode(monkeypatch):
    monkeypatch.setattr(
        startup, "td_enum", lambda name: FakeParMode if name == "ParMode" else None
    )


@pytest.fixture
def painted(monkeypatch):
    """The two surfaces the host repaints, recorded rather than drawn.

    Both reach into the panel and the controller, which is a network and a
    cable.
    """
    from tdpy import lister, midi

    calls = []
    monkeypatch.setattr(lister, "resize", lambda: calls.append("list"))
    monkeypatch.setattr(midi, "refresh_lights", lambda: calls.append("lamps"))
    return calls


@pytest.fixture
def paint_asked(monkeypatch):
    """`wire_engine`'s request for a repaint, without the waiting behind it.

    The wait is `_paint_when_published`'s and is tested on its own; what the
    wiring has to get right is asking for it at all, since nothing else in the
    host will draw the engine's first values.
    """
    calls = []
    monkeypatch.setattr(build, "_paint_when_published", lambda: calls.append("paint"))
    return calls


class FakeParent:
    def __init__(self, children):
        self.path = "/project1"
        self.children = dict(children)

    def op(self, name):
        return self.children.get(name)


class FakeComp:
    path = "/project1/engine"

    def __init__(self, connectors, children, pars=None):
        self.outputConnectors = list(connectors)
        self._parent = FakeParent(children)
        self.par = types.SimpleNamespace(**(pars or {}))

    def parent(self):
        return self._parent


def _loaded_engine(missing=()):
    """An Engine COMP as it is once the component has loaded.

    One connector per declared output, one Null beside it to receive each, the
    settings COMP the expressions point at, and one parameter per setting.
    `missing` names parameters to leave off, which is what a stale .tox looks
    like from the host.
    """
    connectors = [FakeConnector(item.label) for item in link.declared()]
    children = {item.name: types.SimpleNamespace(path=f"/project1/{item.name}")
                for item in link.declared()}
    children["settings"] = types.SimpleNamespace(path="/project1/settings")
    pars = {
        name: FakePar() for name in link.parameters() if name not in missing
    }
    return FakeComp(connectors, children, pars)


class TestConnectorFor:
    def test_it_matches_by_label_not_position(self):
        wanted = FakeConnector("program video")
        connectors = [FakeConnector("state"), wanted]
        assert build.connector_for(connectors, "program video") is wanted

    def test_no_match_is_none(self):
        assert build.connector_for([FakeConnector("state")], "program video") is None


class TestWireEngine:
    def test_every_declared_output_reaches_the_null_named_after_it(
        self, par_mode, paint_asked, silent
    ):
        comp = _loaded_engine()
        assert build.wire_engine(comp) == list(link.DECLARED)
        for connector, item in zip(comp.outputConnectors, link.declared()):
            assert [target.path for target in connector.connected] == [
                f"/project1/{item.name}"
            ]

    def test_an_output_with_no_connector_says_what_there_is(self, par_mode, paint_asked, silent):
        comp = _loaded_engine()
        comp.outputConnectors = [FakeConnector("spike video")]
        assert build.wire_engine(comp) == []
        assert "'spike video'" in silent[0]

    def test_no_outputs_yet_says_none(self, par_mode, paint_asked, silent):
        comp = _loaded_engine()
        comp.outputConnectors = []
        assert build.wire_engine(comp) == []
        assert silent[0].endswith("have none")

    def test_it_asks_for_a_repaint_once_it_has_wired_the_outputs(
        self, par_mode, paint_asked, silent
    ):
        # Nothing else in the host will draw the engine's first values: they
        # arrive holding what they mean rather than changing into it, so no
        # watcher fires, and the build painted before any of this existed.
        build.wire_engine(_loaded_engine())
        assert paint_asked == ["paint"]

    def test_ready_means_the_outputs_have_something_in_them(self):
        # Engine_COMP.htm, Ready When: "buffered - ... sufficient frames have
        # been cooked to fill the input and output buffers". On the default,
        # Component Loaded, onReady fires before any frame has crossed and the
        # paint above would draw against empty channels.
        assert build.ENGINE_READY_WHEN == "buffered"

    def test_a_missing_null_is_reported_not_raised(self, par_mode, paint_asked, silent):
        comp = _loaded_engine()
        del comp.parent().children[link.DECLARED[0]]
        assert link.DECLARED[0] not in build.wire_engine(comp)
        assert comp.outputConnectors[0].connected == []


class TestLinkSettings:
    """The host filling the engine's parameters from its own settings COMP."""

    def test_each_parameter_reads_the_setting_of_the_same_name(self, par_mode, paint_asked, silent):
        comp = _loaded_engine()
        build.wire_engine(comp)
        # Written out rather than built from `audio.parameter_expression`: this
        # string is evaluated by TouchDesigner in the host, and a test that
        # generated it the same way the code does could not see it change.
        assert comp.par.Dwell.expr == "op('/project1/settings').par.Dwell.eval()"
        assert comp.par.Levelb.expr == "op('/project1/settings').par.Levelb.eval()"

    def test_a_parameter_left_in_constant_mode_would_be_inert(self, par_mode, paint_asked, silent):
        # Both halves or neither: an expression on a parameter still in Constant
        # mode looks exactly like one that failed, and the engine would run on
        # the .tox's defaults with nothing saying so.
        comp = _loaded_engine()
        build.wire_engine(comp)
        assert comp.par.Dwell.mode == FakeParMode.EXPRESSION

    def test_every_setting_is_linked(self, par_mode, paint_asked, silent):
        comp = _loaded_engine()
        build.wire_engine(comp)
        unlinked = [
            name for name in link.parameters()
            if getattr(comp.par, name).expr is None
        ]
        assert unlinked == []

    def test_a_parameter_the_tox_never_declared_is_named(self, par_mode, paint_asked, silent):
        comp = _loaded_engine(missing=("Dwell",))
        build.wire_engine(comp)
        assert any("Dwell" in line and "regenerate" in line for line in silent)
        assert any(line.endswith("not linked: Dwell") for line in silent)

    def test_no_settings_comp_is_reported_rather_than_raised(self, par_mode, paint_asked, silent):
        comp = _loaded_engine()
        del comp.parent().children["settings"]
        build.wire_engine(comp)
        assert any("defaults" in line for line in silent)


class TestSend:
    """The host's end: a command becomes a pulse on the Engine COMP."""

    def _engine(self, monkeypatch, comp):
        parent = FakeParent({build.ENGINE_COMP: comp} if comp is not None else {})
        module = types.ModuleType("td")
        module.op = lambda path: parent if path == build.BUILD_PARENT else None
        monkeypatch.setitem(sys.modules, "td", module)
        return parent

    def test_a_command_pulses_the_parameter_that_carries_it(self, monkeypatch, silent):
        comp = types.SimpleNamespace(
            path="/project1/engine",
            par=types.SimpleNamespace(Next=FakePulsePar(), Togglea=FakePulsePar()),
        )
        self._engine(monkeypatch, comp)
        engine.send("next")
        assert (comp.par.Next.pulses, comp.par.Togglea.pulses) == (1, 0)

    def test_a_per_deck_command_pulses_its_own_parameter(self, monkeypatch, silent):
        comp = types.SimpleNamespace(
            path="/project1/engine",
            par=types.SimpleNamespace(Next=FakePulsePar(), Togglea=FakePulsePar()),
        )
        self._engine(monkeypatch, comp)
        engine.send("toggle_a")
        assert (comp.par.Next.pulses, comp.par.Togglea.pulses) == (0, 1)

    def test_an_unknown_command_reports_and_lists_the_real_ones(
        self, monkeypatch, silent
    ):
        comp = types.SimpleNamespace(path="/project1/engine", par=types.SimpleNamespace())
        self._engine(monkeypatch, comp)
        assert engine.send("rewind") is None
        assert "rewind" in silent[0]
        assert "shuffle" in silent[0]

    def test_a_press_before_the_engine_exists_says_where_it_went(
        self, monkeypatch, silent
    ):
        self._engine(monkeypatch, None)
        assert engine.send("next") is None
        assert "next went nowhere" in silent[0]


class FakeChannel:
    def __init__(self, value):
        self.value = value

    def eval(self, index=None):
        return self.value


class FakeStateChop:
    """The host's Null carrying the state output: `[]` by channel name."""

    path = "/project1/state"

    def __init__(self, values):
        self.values = dict(values)

    def __getitem__(self, name):
        found = self.values.get(name)
        return None if found is None else FakeChannel(found)


class FakeRun:
    """`td.run`, recording what was deferred instead of deferring it."""

    def __init__(self):
        self.deferred = []

    def __call__(self, callable_, *args, delayFrames=0):
        self.deferred.append((callable_, args, delayFrames))


class TestPaintWhenPublished:
    """The host waiting for the engine's first frame before drawing it.

    The defect this exists for, seen on 2026-09-19: the clip list showed every
    clip and highlighted nothing until the first cut. Its channels arrive
    holding the right values rather than changing into them, so the watchers
    have nothing to fire on, and the Nulls they are read through had not cooked
    at the moment `onReady` wired them.
    """

    @pytest.fixture
    def deferred(self, monkeypatch):
        module = types.ModuleType("td")
        module.run = FakeRun()
        monkeypatch.setitem(sys.modules, "td", module)
        return module.run

    def test_it_waits_while_the_state_reads_nothing(
        self, deferred, painted, monkeypatch, silent
    ):
        monkeypatch.setattr(engine, "state", lambda channel: None)
        assert build._paint_when_published() is None
        assert painted == []
        # One frame at a time, so the wait is as short as the engine allows.
        assert [delay for _, _, delay in deferred.deferred] == [1]

    def test_it_counts_down_so_it_cannot_wait_forever(
        self, deferred, painted, monkeypatch, silent
    ):
        monkeypatch.setattr(engine, "state", lambda channel: None)
        build._paint_when_published(3)
        assert deferred.deferred[0][1] == (2,)

    def test_giving_up_says_so_rather_than_going_quiet(
        self, deferred, painted, monkeypatch, silent
    ):
        monkeypatch.setattr(engine, "state", lambda channel: None)
        assert build._paint_when_published(0) is None
        assert deferred.deferred == []
        assert "published no state" in silent[-1]

    def test_it_paints_once_the_state_can_be_read(
        self, deferred, painted, monkeypatch, silent
    ):
        monkeypatch.setattr(engine, "state", lambda channel: 0.0)
        assert build._paint_when_published() is True
        assert painted == ["list", "lamps"]
        assert deferred.deferred == []

    def test_a_live_deck_of_zero_is_a_reading_and_not_an_absence(
        self, deferred, painted, monkeypatch, silent
    ):
        # Deck A is `live = 0`, which is falsy and is the value the channel
        # holds for the whole of a launch that has not cut yet. Testing the
        # channel for truth rather than for None would wait out all 120 frames
        # and then report a fault, on the most ordinary state there is.
        monkeypatch.setattr(engine, "state", lambda channel: 0.0)
        build._paint_when_published()
        assert painted == ["list", "lamps"]


class TestReadingWhatTheEngineSays:
    """The host's one place that knows where the engine's data arrives."""

    @pytest.fixture
    def published(self, monkeypatch):
        chop = FakeStateChop(
            {"live": 1.0, "row_a": 4.0, "row_b": 7.0, "seed": 419273.0}
        )
        monkeypatch.setattr(
            engine, "output", lambda name: chop if name == "state" else None
        )
        return chop

    def test_a_channel_reads_as_a_number(self, published):
        assert engine.state("seed") == 419273.0

    def test_a_channel_the_engine_does_not_publish_is_none(self, published):
        # An older .tox, or a name that drifted. None is what every surface
        # already draws as "nothing to show".
        assert engine.state("rows") is None

    def test_no_output_yet_is_none_rather_than_an_error(self, monkeypatch):
        # The first seconds of a launch, every frame. A reported line here
        # would fill a log kept for launches.
        monkeypatch.setattr(engine, "output", lambda name: None)
        assert engine.state("live") is None

    def test_a_per_deck_channel_answers_for_the_deck_that_is_showing(self, published):
        assert engine.deck_state(link.DECK_ROW) == 7.0
        published.values["live"] = 0.0
        assert engine.deck_state(link.DECK_ROW) == 4.0

    def test_a_silent_engine_has_no_live_deck(self, monkeypatch):
        monkeypatch.setattr(engine, "output", lambda name: FakeStateChop({}))
        assert engine.deck_state(link.DECK_ROW) is None


class TestOnCommand:
    """The engine's end: a pulsed parameter becomes a transport call."""

    def test_it_runs_the_command_the_parameter_stands_for(self, monkeypatch, silent):
        from tdpy import player

        called = []
        monkeypatch.setattr(player, "command", called.append)
        engine.on_command("Previous")
        assert called == ["previous"]

    def test_the_round_trip_is_the_same_name_it_started_as(self, monkeypatch, silent):
        from tdpy import player

        called = []
        monkeypatch.setattr(player, "command", called.append)
        for command in link.commands():
            engine.on_command(command.parameter)
        assert called == [command.name for command in link.commands()]

    def test_a_parameter_no_command_owns_is_reported(self, silent):
        # A built-in pulse on the component would arrive here if the watcher's
        # `builtin` flag were ever set the wrong way round.
        assert engine.on_command("Reload") is None
        assert "Reload" in silent[0]


class FakeOut:
    def __init__(self, name):
        self.name = name
        self.path = f"/engineSource/{name}"
        self.inputConnectors = [FakeConnector("in")]


class FakeSelect:
    """A Select with only its own family's parameter, so a wrong name shows."""

    PARAMETER = None

    def __init__(self, name):
        self.name = name
        self.path = f"/engineSource/{name}"
        self.par = types.SimpleNamespace(**{self.PARAMETER: FakeValuePar()})
        self.destroyed = False

    def destroy(self):
        self.destroyed = True

    def selected(self):
        return getattr(self.par, self.PARAMETER).val


class FakeValuePar:
    val = None


class FakeSelectTOP(FakeSelect):
    PARAMETER = "top"


class FakeSelectCHOP(FakeSelect):
    PARAMETER = "chops"


class FakeSelectDAT(FakeSelect):
    PARAMETER = "dat"


class FakeRoot:
    path = "/engineSource"

    def __init__(self, children):
        self.children = dict(children)

    def op(self, name):
        return self.children.get(name)

    def create(self, optype, name):
        made = optype(name)
        self.children[name] = made
        return made


@pytest.fixture
def fake_td(monkeypatch):
    module = types.ModuleType("td")
    module.selectTOP = FakeSelectTOP
    module.selectCHOP = FakeSelectCHOP
    module.selectDAT = FakeSelectDAT
    monkeypatch.setitem(sys.modules, "td", module)
    return module


@pytest.fixture
def built(monkeypatch):
    """`build_player` and its sources, stubbed: `main` is what is under test.

    The player half is the same code the host ran until 9.4 and is covered
    where it always was. What is new here is the wiring between that network
    and the component's outputs.
    """
    container = types.SimpleNamespace(path="/engineSource/generated")
    sources = {
        item.name: types.SimpleNamespace(path=f"/engineSource/generated/{item.name}")
        for item in link.declared()
    }
    monkeypatch.setattr(build, "build_player", lambda root: container)
    monkeypatch.setattr(build, "engine_sources", lambda comp: sources)
    return container, sources


def _root():
    return FakeRoot({item.name: FakeOut(item.name) for item in link.declared()})


class TestMain:
    def test_every_declared_output_is_fed_from_the_container(
        self, fake_td, built, silent
    ):
        _, sources = built
        root = _root()
        engine.main(root)
        for item in link.declared():
            select = root.op(engine.SELECT_PREFIX + item.name)
            assert select.selected() == sources[item.name].path, item.name
            assert root.op(item.name).inputConnectors[0].connected == [select]

    def test_a_top_is_tapped_with_a_select_top_and_a_chop_with_a_select_chop(
        self, fake_td, built, silent
    ):
        root = _root()
        engine.main(root)
        video = root.op(engine.SELECT_PREFIX + "program_video")
        audio = root.op(engine.SELECT_PREFIX + "program_audio")
        table = root.op(engine.SELECT_PREFIX + "playlist")
        assert isinstance(video, FakeSelectTOP)
        assert isinstance(audio, FakeSelectCHOP)
        assert isinstance(table, FakeSelectDAT)

    def test_the_root_is_recorded_so_the_player_can_find_its_network(
        self, fake_td, built, silent
    ):
        assert engine.root() is None
        engine.main(_root())
        assert engine.ROOT == "/engineSource"

    def test_a_second_call_replaces_the_taps(self, fake_td, built, silent):
        root = _root()
        engine.main(root)
        first = root.op(engine.SELECT_PREFIX + "program_video")
        engine.main(root)
        assert first.destroyed
        assert root.op(engine.SELECT_PREFIX + "program_video") is not first

    def test_a_missing_output_raises_so_the_host_sees_it(self, fake_td, built, silent):
        root = _root()
        del root.children["program_audio"]
        with pytest.raises(LookupError, match="program_audio"):
            engine.main(root)

    def test_an_output_with_nothing_to_carry_raises(self, fake_td, built, silent):
        _, sources = built
        sources["deck_b_audio"] = None
        with pytest.raises(LookupError, match="deck_b_audio"):
            engine.main(_root())


class TestNames:
    def test_the_host_side_names(self):
        assert (
            build.ENGINE_COMP,
            build.ENGINE_CALLBACK_DAT,
            build.ENGINE_SOURCE,
            build.ENGINE_BOOTSTRAP_DAT,
            build.ENGINE_COMMAND_EXEC,
        ) == ("engine", "engine_callbacks", "engineSource", "bootstrap", "commands_exec")

    def test_the_retired_null_is_swept(self):
        # 9.3's single Null for the picture. A stale one beside the container
        # would sit there taking an output nothing is wired to any more.
        assert "engineProgram" in build.LEGACY_NAMES

    def test_relative_paths_resolve_against_the_toe_not_the_tox(self):
        # The token read off the live parameter, which has `toe` and `tox`.
        # Engine_COMP.htm's parameter table says `project` and `comp` for the
        # same menu, and that is the spelling this was written as first:
        # set_menu refused it on 2026-09-19 and named the real two. The default
        # is the .tox's own folder, which is `out/` - one level below the media
        # paths the playlist stores, so the wrong token here is a player that
        # finds no clips.
        assert build.ENGINE_ASSET_PATHS == "toe"

    def test_the_tox_is_written_where_git_ignores_it(self):
        assert build.ENGINE_TOX == "out/engine.tox"
        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        assert "/out/" in lines


class TestCallbacks:
    def test_on_ready_has_the_installs_signature(self):
        # bin/Lib/tdutils/DATScripts/engineCOMP_callbacks.py:
        # def onReady(engineComp: engineCOMP)
        tree = ast.parse(build.ENGINE_CALLBACK)
        functions = {
            node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
        }
        assert [arg.arg for arg in functions["onReady"].args.args] == ["engineComp"]

    def test_the_command_watcher_has_the_installs_signature(self):
        # bin/Lib/tdutils/DATScripts/parameterexecuteDAT.py: def onPulse(par: Par)
        tree = ast.parse(build.ENGINE_COMMAND_CALLBACK)
        functions = {
            node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
        }
        assert list(functions) == ["onPulse"]
        assert [arg.arg for arg in functions["onPulse"].args.args] == ["par"]

    def test_the_panel_sends_rather_than_calling_the_transport(self):
        # The buttons are in the host and the transport is not. A callback
        # still calling `player.command` would find an empty container and say
        # so on every press.
        assert "tdpy.engine.send(panelValue.owner.name)" in build.CONTROL_CALLBACK
        assert "tdpy.player" not in build.CONTROL_CALLBACK

    def test_the_engine_side_callbacks_do_not_reach_for_the_host(self):
        # Both run in the engine's process, where the controller's cable and
        # the clip list do not exist.
        for callback in (build.FADE_CALLBACK, build.DWELL_EXEC_CALLBACK):
            assert "tdpy.midi" not in callback
            assert "tdpy.lister" not in callback
