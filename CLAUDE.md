# TDPyMovieplayer — Project Instructions

## TouchDesigner Conventions

- **Verify every API symbol against the installed build before writing code against it** — enums, COMP types, operator attributes, parameter modes. Do not write one from memory. The install describes itself in five places: the offline wiki under `Samples/Learn/OfflineHelp`, `Config/TDParameterHelp.json`, the type stubs under `bin/Lib/tdi/ops`, the stock callback files under `bin/Lib/tdutils/DATScripts`, and the strings in `bin/libTD.dll`. A live `python` query in the app settles anything they don't. Enums are **not** on the `td` module — `ParMode`, `JustifyType` and friends live in `tdutils.TDDefinitions`.

- **A callback's name and signature come from `bin/Lib/tdutils/DATScripts/`.** One file per operator that has callbacks (`timerCHOP_callbacks.py`, `chopexecuteDAT.py`, `listCOMP_callbacks.py`), carrying the exact argument list and a docstring per argument. The wiki's prose is not enough: it names the Timer CHOP's cycle callback in passing and leaves the reader to guess which end of a cycle it means. `timerCHOP_callbacks.py` has **both** — `onCycleStart(timerOp, segment, cycle)` at line 120, *"Called when a cycle starts"*, and `onCycle(timerOp, segment, cycle)` at line 147, *"Called when a cycle completes"*. The dwell uses `onCycleStart`, which is why `player.on_dwell` has to refuse cycle 0: the timer starting is a cycle beginning. `onDone(timerOp, segment, interrupt)` is the one the fade timer uses, since a fade runs once rather than cycling.

    Corrected 2026-09-12. This file previously said `onCycle` "does not exist", which came from reading the wiki rather than the file — the same mistake the rule above exists to prevent, made while writing the rule.

- **A channel name that is not in `libTD.dll` is not a channel name.** An operator's output channels are reachable only through an Info CHOP, and their names are documented unevenly — the Timer CHOP's help names `segment_pulse` outright and leaves its cycle-pulse channel unnamed. Grepping the binary settles it: `loop_frame` and `segment_pulse` are both in there and `cycle_pulse` is not, which is why the dwell timer is read through its callback rather than watched as a channel.
- **Never write a silent `getattr` fallback** for an API symbol you're unsure of. It resolves to something plausible and hides the broken feature; let it raise.
- **Display indices are 0-based.** A Window COMP's `Display` parameter indexes the Monitors DAT from 0, and TouchDesigner silently opens the window somewhere else rather than refusing an out-of-range value. Derive a bounds check from the Monitors DAT row count, not from the same assumption as the value being checked.
- **Panel widgets must live inside a panel-type COMP** (a containerCOMP), not a baseCOMP. Put one in a baseCOMP and it simply doesn't render — no error.
- **Add new controls to the existing `controlPanelWindow`**, rather than creating a new panel or window.
- **`COMP.create()` appends a digit to the name**, even when the name is free. Use `startup.create()` anywhere the new node's name is referred to again.
- **Shared `tdpy` files belong upstream.** Anything in the generator's VERBATIM manifest is owned by `300-Code/330 - TouchDesigner/0010 - TouchDesigner-Python` — change it there and copy it down, never edit it project-side.

## Handover

When a surface is built ahead of the engine behind it, **name the dead controls** in the handover. Otherwise the intended behaviour comes back as a bug report.
