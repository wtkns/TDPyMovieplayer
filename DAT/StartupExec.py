"""Contents of the Execute DAT that lives inside the .toe.

This is the only code that lives inside the binary, and it stays this short on
purpose: its whole job is to reach the Python on disk and hand off. Anything
that grows here is logic that cannot be diffed.

Kept as a file so the snippet itself is version-controlled and reviewable. Paste
it into an Execute DAT at the root of the project and enable that DAT's `Start`
parameter (Execute page). Re-paste if this file changes - or point the DAT's
`File` parameter here and enable `Sync to File`, and it will follow this file instead.

Two constraints shape this snippet, both about startup ordering:

  * It imports nothing outside the standard library. TDPyEnvManager sets up the
    side-loaded environment during startup, and Derivative's guidance is that it
    "should be the first component initializing on start so that the environment
    is setup before any additional component attempt to import modules from it."
    Code running this early cannot assume that environment exists yet.

  * The work is deferred by a frame rather than done here. That steps it out of
    the startup callback entirely: by the time it fires, the first frame has
    cooked and lazily-initialized components - TDPyEnvManager among them - are
    up.

`project` and `run` are globals TouchDesigner injects at runtime, so this module
will not import outside TouchDesigner. It is not meant to.
"""


def onStart():
    import sys

    root = project.folder  # noqa: F821 - TouchDesigner global
    if root not in sys.path:
        sys.path.insert(0, root)

    # The import lives inside the deferred script too, so nothing in the package
    # is touched until the environment has had its chance to come up.
    run(  # noqa: F821 - TouchDesigner global
        "import tdpy.startup; tdpy.startup.main()",
        delayFrames=1,
    )
    return
