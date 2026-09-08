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
import traceback

PACKAGE = __name__.split(".")[0]

#: Environment folders are named `<something>_vEnv`. TDPyEnvManager appends that
#: suffix itself - see appendVEnvSuffix() in its helper - so the pattern holds
#: whether the environment was made by the component or by create-venv.bat.
VENV_SUFFIX = "_vEnv"


def project_root() -> pathlib.Path:
    """The repository root - the folder holding the .toe and this package."""
    return pathlib.Path(__file__).resolve().parent.parent


def report(message: str) -> None:
    """Put a message somewhere it will actually be seen.

    Exceptions raised inside a DAT callback are easy to lose: TouchDesigner
    surfaces them inconsistently, and a startup that failed otherwise looks
    identical to a project that simply did nothing. Print to the textport and
    keep a file copy for when the textport was not open.
    """
    print(message)
    try:
        log_dir = project_root() / "logs"
        log_dir.mkdir(exist_ok=True)
        with open(log_dir / "startup.log", "a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")
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
