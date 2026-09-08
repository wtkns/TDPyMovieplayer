"""The network this project builds.

This is the file to edit. It is the only module that reaches into TouchDesigner,
which keeps the rest of the package readable - and testable - outside it.

Phase 0 builds a placeholder network. Its only real job is to prove the loop end
to end: the .toe opens, the Python on disk runs, and operators appear.

Any import of `td` or of a third-party package belongs inside build(), not at
module scope: this module is imported early enough that the side-loaded
environment may not be ready yet. Deferring the import until the function
actually runs is what Derivative means by initializing lazily - and it keeps
this file importable outside TouchDesigner, where neither exists.
"""

#: Where the network is built. TouchDesigner opens a project showing the inside
#: of /project1, not the true root, so building at "/" puts the network beside
#: that container rather than in it - present, addressable by path, and invisible
#: where you are actually looking. Falls back to the root if /project1 is absent.
BUILD_PARENT = "/project1"

#: Name of the container the build owns. Everything it makes lives in here.
BUILD_ROOT = "generated"


def build():
    """Create the network, replacing whatever the last build left behind.

    Clear-and-rebuild rather than converging on the existing network: it is the
    simpler of the two options and makes a re-run predictable. Anything created
    outside `BUILD_ROOT` is left alone, so hand-made work sitting next to it
    survives.
    """
    # TouchDesigner injects op(), the operator classes and the rest of its
    # globals into DAT scripts, expressions and the textport - not into modules
    # imported from disk. From here they come off the td module instead.
    import td

    from . import startup

    parent = td.op(BUILD_PARENT) or td.op("/")

    previous = parent.op(BUILD_ROOT)
    if previous is not None:
        previous.destroy()

    container = parent.create(td.baseCOMP, BUILD_ROOT)
    container.nodeX, container.nodeY = 0, 0

    noise = _place(container.create(td.noiseTOP, "noise"), 0, 0)
    level = _place(container.create(td.levelTOP, "level"), 200, 0)
    out = _place(container.create(td.nullTOP, "out"), 400, 0)

    level.inputConnectors[0].connect(noise)
    out.inputConnectors[0].connect(level)

    # Verified against a running TouchDesigner. set_par() still reports an unknown
    # name rather than failing the whole build, which is how the earlier wrong
    # guess ("monochrome" - it is "mono") cost a warning instead of the network.
    # Setting parameters properly is Phase 3 work.
    startup.set_par(noise, "period", 0.175)
    startup.set_par(noise, "mono", True)

    return container


def _place(operator, x, y):
    """Position a node so the built network is legible when opened."""
    operator.nodeX, operator.nodeY = x, y
    return operator


