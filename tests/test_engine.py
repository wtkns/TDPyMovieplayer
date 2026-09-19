"""Tests for Phase 9.3: the generated engine component and the host's wiring.

What is tested is the text that ships and the decisions made about it. The
bootstrap is generated source that runs in another process, where a mistake
surfaces only as an Engine COMP error at launch - so it is executed here, from
the string the host writes, rather than from a copy of the logic.

Expected names are literals, per `test_link.py`: the host and the engine
spelling one thing two ways is the failure these guard against.
"""

import ast
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tdpy import build, engine, startup  # noqa: E402

#: A path with everything that breaks naive quoting: spaces, backslashes, and a
#: backslash before a letter that would otherwise be an escape.
AWKWARD = r"C:\Users\jms\Documents\wtkns.com\300-Code\330 - TouchDesigner\new tdpy"


@pytest.fixture
def silent(monkeypatch):
    lines = []
    monkeypatch.setattr(startup, "report", lines.append)
    return lines


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


class FakeParent:
    def __init__(self, children):
        self.children = children

    def op(self, name):
        return self.children.get(name)


class FakeComp:
    path = "/project1/engine"

    def __init__(self, connectors, children):
        self.outputConnectors = connectors
        self._parent = FakeParent(children)

    def parent(self):
        return self._parent


class TestConnectorFor:
    def test_it_matches_by_label_not_position(self):
        wanted = FakeConnector("program video")
        connectors = [FakeConnector("state"), wanted]
        assert build.connector_for(connectors, "program video") is wanted

    def test_no_match_is_none(self):
        assert build.connector_for([FakeConnector("state")], "program video") is None


class TestWireEngine:
    def test_program_video_is_connected_to_the_hosts_null(self, silent):
        target = types.SimpleNamespace(path="/project1/engineProgram")
        program = FakeConnector("program video")
        comp = FakeComp([FakeConnector("state"), program], {"engineProgram": target})
        assert build.wire_engine(comp) is target
        assert program.connected == [target]

    def test_a_missing_output_says_what_there_is(self, silent):
        comp = FakeComp([FakeConnector("spike video")], {"engineProgram": object()})
        assert build.wire_engine(comp) is None
        assert "'spike video'" in silent[-1]

    def test_no_outputs_yet_says_none(self, silent):
        comp = FakeComp([], {"engineProgram": object()})
        assert build.wire_engine(comp) is None
        assert silent[-1].endswith("have none")

    def test_a_missing_null_is_reported_not_raised(self, silent):
        program = FakeConnector("program video")
        comp = FakeComp([program], {})
        assert build.wire_engine(comp) is None
        assert program.connected == []


class TestCallback:
    def test_on_ready_has_the_installs_signature(self):
        # bin/Lib/tdutils/DATScripts/engineCOMP_callbacks.py:
        # def onReady(engineComp: engineCOMP)
        tree = ast.parse(build.ENGINE_CALLBACK)
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        assert [arg.arg for arg in functions["onReady"].args.args] == ["engineComp"]


class TestNames:
    def test_the_host_side_names(self):
        assert (
            build.ENGINE_COMP,
            build.ENGINE_CALLBACK_DAT,
            build.ENGINE_PROGRAM_TOP,
            build.ENGINE_SOURCE,
            build.ENGINE_BOOTSTRAP_DAT,
        ) == ("engine", "engine_callbacks", "engineProgram", "engineSource", "bootstrap")

    def test_the_tox_is_written_where_git_ignores_it(self):
        assert build.ENGINE_TOX == "out/engine.tox"
        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        assert "/out/" in lines


class FakeOut:
    def __init__(self):
        self.path = "/engineSource/program_video"
        self.inputConnectors = [FakeConnector("in")]


class FakeTextPar:
    expr = None


class FakeProbe:
    def __init__(self, name):
        self.name = name
        self.path = f"/engineSource/{name}"
        self.par = types.SimpleNamespace(text=FakeTextPar())
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


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
    module.textTOP = FakeProbe
    monkeypatch.setitem(sys.modules, "td", module)
    return module


class TestMain:
    def test_the_probe_goes_through_the_program_output(self, fake_td, silent):
        out = FakeOut()
        probe = engine.main(FakeRoot({"program_video": out}))
        assert out.inputConnectors[0].connected == [probe]
        assert probe.name == "probe"

    def test_the_probe_text_is_an_expression_python_accepts(self, fake_td, silent):
        probe = engine.main(FakeRoot({"program_video": FakeOut()}))
        compile(probe.par.text.expr, "expr", "eval")
        assert "absTime.frame" in probe.par.text.expr

    def test_a_second_call_replaces_the_probe(self, fake_td, silent):
        old = FakeProbe("probe")
        root = FakeRoot({"program_video": FakeOut(), "probe": old})
        engine.main(root)
        assert old.destroyed

    def test_a_missing_output_raises_so_the_host_sees_it(self, fake_td, silent):
        with pytest.raises(LookupError, match="program_video"):
            engine.main(FakeRoot({}))
