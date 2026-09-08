"""Bootstrap entry point, called by the Execute DAT one frame after start.

Two jobs and deliberately no more: run the build with failures made visible, and
provide a reload path so edits made in an editor take effect without restarting
TouchDesigner.

**This module must import only the standard library.** It runs early in a
project's life, and the side-loaded environment set up by TDPyEnvManager may not
be on `sys.path` yet - see `DAT/StartupExec.py` for the ordering constraint.
Project code that needs third-party packages imports them inside `build()`,
never at module scope.
"""

import importlib
import os
import pathlib
import sys
import time
import traceback

PACKAGE = __name__.split(".")[0]

#: Stamp on every reported line. Short on purpose - these lines are read minutes
#: after something broke, not months later, and a full ISO timestamp doubles the
#: width of a log whose messages are mostly short. The year is the one thing it
#: gives up; the file's own mtime still has it.
TIMESTAMP = "%m-%d %H:%M:%S"

#: Environment folders are named `<something>_vEnv`. TDPyEnvManager appends that
#: suffix itself - see appendVEnvSuffix() in its helper - so the pattern holds
#: whether the environment was made by the component or by create-venv.bat.
VENV_SUFFIX = "_vEnv"


def project_root() -> pathlib.Path:
    """The repository root - the folder holding the .toe and this package."""
    return pathlib.Path(__file__).resolve().parent.parent


def stamp(message: str, now: str = None) -> str:
    """Prefix a message with the time, leaving any continuation lines alone.

    Only the first line is stamped. Multi-line messages here are nearly always
    tracebacks, and a timestamp down the left of one makes it useless for the
    thing tracebacks are for - pasting somewhere and reading top to bottom.

    Takes `now` so the format is testable without freezing the clock.
    """
    now = time.strftime(TIMESTAMP) if now is None else now
    first, separator, rest = message.partition("\n")
    return f"[{now}] {first}" + separator + rest


def report(message: str) -> None:
    """Put a message somewhere it will actually be seen.

    Exceptions raised inside a DAT callback are easy to lose: TouchDesigner
    surfaces them inconsistently, and a startup that failed otherwise looks
    identical to a project that simply did nothing. Print to the textport and
    keep a file copy for when the textport was not open.

    Both copies get the same stamp. The textport is a running session where the
    time looks redundant, but a line pasted out of it into a bug report or a log
    entry stops being self-dating the moment it leaves, and the log file is
    append-only across every launch - without a stamp there is nothing marking
    where one session ends and the next begins.
    """
    line = stamp(message)
    print(line)
    try:
        log_dir = project_root() / "logs"
        log_dir.mkdir(exist_ok=True)
        with open(log_dir / "startup.log", "a", encoding="utf-8") as handle:
            handle.write(line.rstrip() + "\n")
    except OSError:
        pass  # logging must never be the thing that breaks startup


def main():
    """Called from the Execute DAT's onStart."""
    report(f"[{PACKAGE}] startup from {project_root()}")
    report(environment_report())
    _add_controls()
    return build()


def _site_packages(environment):
    """Every site-packages directory that could belong to one environment.

    Windows puts it at `Lib/site-packages`, macOS at
    `lib/python3.11/site-packages`. Both are checked rather than branching on
    the platform: guessing wrong here would report a working environment as
    missing, which is worse than looking in one extra place.
    """
    candidates = [environment / "Lib" / "site-packages"]
    candidates.extend(sorted(environment.glob("lib/python*/site-packages")))
    return [path for path in candidates if path.is_dir()]


def environment_report(root=None, search_path=None) -> str:
    """One line saying whether the side-loaded environment actually loaded.

    Worth reporting because it is genuinely unclear from the outside. A context
    file written by TDPyEnvManager's CLI records `active: false`, where the
    component's own pulse records `true` - and the helper reads that flag into
    `startAsActive` and then never uses it, while linking the environment
    unconditionally whenever a context file is found. Rather than reason about
    which of those wins, look at `sys.path` and say what is there.

    Takes `root` and `search_path` so it can be tested without a project or a
    running TouchDesigner.
    """
    root = project_root() if root is None else pathlib.Path(root)
    search_path = sys.path if search_path is None else search_path

    # sys.path holds whatever string was inserted - not necessarily normalised,
    # and on Windows not necessarily the same case or separator.
    on_path = {os.path.normcase(os.path.abspath(entry)) for entry in search_path}
    environments = sorted(
        path for path in root.glob("*" + VENV_SUFFIX) if path.is_dir()
    )

    if not environments:
        return (
            f"[{PACKAGE}] no {VENV_SUFFIX} folder in {root} - run create-venv.bat"
        )

    for environment in environments:
        for packages in _site_packages(environment):
            if os.path.normcase(os.path.abspath(str(packages))) in on_path:
                return f"[{PACKAGE}] environment linked: {environment.name}"

    found = ", ".join(environment.name for environment in environments)
    return (
        f"[{PACKAGE}] environment NOT on sys.path: {found}"
        " - link it in the tdPyEnvManager component"
    )


def _add_controls():
    """Put the rebuild button up without letting it block the build.

    The controls are furniture: a fault in them should cost the button, not the
    network. Kept out of build() for the same reason.
    """
    try:
        from . import controls

        controls.ensure_rebuild_button()
    except Exception:
        report(f"[{PACKAGE}] rebuild button setup failed\n{traceback.format_exc()}")


def build():
    """Run the network build, reporting any failure instead of swallowing it."""
    try:
        module = importlib.import_module(PACKAGE + ".build")
        result = module.build()
    except Exception:
        report(f"[{PACKAGE}] BUILD FAILED\n{traceback.format_exc()}")
        return None
    # Say where, not just that: a build placed somewhere unexpected is nearly
    # indistinguishable from one that never happened.
    where = getattr(result, "path", None)
    report(f"[{PACKAGE}] build complete" + (f" at {where}" if where else ""))
    return result


def create(parent, optype, name):
    """Create an operator, and give it the name that was asked for.

    `COMP.create()` treats its name argument as a base rather than a
    requirement: where it will not use the name it appends a digit, returns the
    node under that instead, and says nothing. It does this even when the name
    is free - the rebuild button landed at `rebuild1` on every cold launch of
    both projects built with this framework, and renaming it immediately
    afterwards succeeds, which is only possible if nothing held the name. Why
    create() declines an available name is not established, and this does not
    guess at it; taking the name afterwards works whichever the reason.

    Silent when it succeeds, because it succeeds on every node of every build
    and six log lines a launch to say so would bury the ones that matter. Note
    that the silence does not distinguish a rename from a create() that behaved
    - only comparing against a run without this function does that.
    """
    operator = parent.create(optype, name)
    if operator.name == name:
        return operator

    holder = parent.op(name)
    if holder is not None and holder is not operator:
        report(
            f"[{PACKAGE}] {parent.path}/{name} is held by a {holder.type}"
            f" - left as {operator.name}"
        )
        return operator

    attempted = operator.name
    operator.name = name
    if operator.name != name:
        report(f"[{PACKAGE}] could not rename {attempted} to {name}")
    return operator


def set_par(operator, name, value):
    """Set a parameter, reporting rather than raising if the name is wrong.

    A misremembered internal name should cost one warning, not the whole
    network. TouchDesigner's internal names are regularly not what the UI label
    suggests - Monochrome is `mono` - and they are not worth guessing at the
    price of a failed build.
    """
    parameter = getattr(operator.par, name, None)
    if parameter is None:
        report(f"[{PACKAGE}] no parameter {name!r} on {operator.path}")
        return None
    parameter.val = value
    return parameter


def set_menu(operator, name, choice):
    """Set a menu parameter, given either its internal name or its UI label.

    Menu items carry two names - the internal one stored in the file
    (`sequential`) and the label the parameter dialog draws ("Sequential") -
    and neither is derivable from the other. This is the one mistake `set_par`
    cannot catch: with a menu, the parameter genuinely exists, so a wrong item
    name raises nothing useful and the network is quietly built on the default.

    Resolving against the live parameter is the only reliable answer, because
    the live parameter is the only place both lists are written down.
    TouchDesigner's own parameter help ships the labels in prose and the
    internal names not at all.

    Accepts either form and matches case-insensitively. When the caller passed
    something other than the exact internal name, the resolved name is reported
    once - so a project that was written against labels ends up with its real
    tokens in the log, ready to be pasted back into the source.
    """
    parameter = getattr(operator.par, name, None)
    if parameter is None:
        report(f"[{PACKAGE}] no parameter {name!r} on {operator.path}")
        return None

    names = list(getattr(parameter, "menuNames", None) or ())
    if not names:
        report(f"[{PACKAGE}] {operator.path}.{name} is not a menu")
        return None
    # menuLabels is the same length as menuNames, but read defensively: a
    # mismatch here should cost the label lookup, not raise inside a build.
    labels = list(getattr(parameter, "menuLabels", None) or ())

    index = _menu_index(names, labels, str(choice))
    if index is None:
        report(
            f"[{PACKAGE}] {operator.path}.{name}: no menu item {choice!r}"
            f" - have {', '.join(names)}"
        )
        return None

    parameter.menuIndex = index
    if names[index] != str(choice):
        report(f"[{PACKAGE}] {operator.path}.{name} = {names[index]!r} ({choice!r})")
    return parameter


def _menu_index(names, labels, wanted):
    """Find `wanted` among menu names first, then labels. None if absent.

    Names are tried before labels, and exactly before case-insensitively, so a
    menu whose label collides with a different item's internal name resolves
    the way the file spells it rather than the way the dialog draws it.
    """
    if wanted in names:
        return names.index(wanted)
    folded = wanted.casefold()
    for candidates in (names, labels):
        for index, item in enumerate(candidates):
            if str(item).casefold() == folded:
                return index
    return None


def reload():
    """Discard this package's modules and build again.

    TouchDesigner keeps modules loaded for the life of the process, so a file
    saved in an editor changes nothing until the old module objects are thrown
    away. Run this from the textport after editing:

        import tdpy.startup; tdpy.startup.reload()

    Dropping a module from `sys.modules` is only half of it. The parent package
    also holds the submodule as an attribute, and `from . import build` consults
    that attribute first - so a plain sys.modules delete hands back the stale
    module object anyway, and the reload silently does nothing. Both have to go,
    which is why `build()` imports by name rather than with `from . import`.

    Caveat worth knowing: this reloads everything *except* this module, because
    it is the one doing the reloading. Edits to `startup.py` itself still need
    TouchDesigner restarted.
    """
    stale = [
        name
        for name in list(sys.modules)
        if name.startswith(PACKAGE + ".") and name != __name__
    ]
    for name in stale:
        del sys.modules[name]
        parent_name, _, attribute = name.rpartition(".")
        parent = sys.modules.get(parent_name)
        if parent is not None and hasattr(parent, attribute):
            delattr(parent, attribute)
    importlib.invalidate_caches()
    report(f"[{PACKAGE}] dropped {len(stale)} module(s), rebuilding")
    return build()
