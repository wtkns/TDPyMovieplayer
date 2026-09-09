# TDPyMovieplayer — Project Instructions

## TouchDesigner Conventions

- **Verify every API symbol against the installed build before writing code against it** — enums, COMP types, operator attributes, parameter modes. Do not write one from memory. The install describes itself in four places: the offline wiki under `Samples/Learn/OfflineHelp`, `Config/TDParameterHelp.json`, the type stubs under `bin/Lib/tdi/ops`, and the strings in `bin/libTD.dll`. A live `python` query in the app settles anything they don't. Enums are **not** on the `td` module — `ParMode`, `JustifyType` and friends live in `tdutils.TDDefinitions`.
- **Never write a silent `getattr` fallback** for an API symbol you're unsure of. It resolves to something plausible and hides the broken feature; let it raise.
- **Display indices are 0-based.** A Window COMP's `Display` parameter indexes the Monitors DAT from 0, and TouchDesigner silently opens the window somewhere else rather than refusing an out-of-range value. Derive a bounds check from the Monitors DAT row count, not from the same assumption as the value being checked.
- **Panel widgets must live inside a panel-type COMP** (a containerCOMP), not a baseCOMP. Put one in a baseCOMP and it simply doesn't render — no error.
- **Add new controls to the existing `controlPanelWindow`**, rather than creating a new panel or window.
- **`COMP.create()` appends a digit to the name**, even when the name is free. Use `startup.create()` anywhere the new node's name is referred to again.
- **Shared `tdpy` files belong upstream.** Anything in the generator's VERBATIM manifest is owned by `300-Code/330 - TouchDesigner/0010 - TouchDesigner-Python` — change it there and copy it down, never edit it project-side.

## Handover

When a surface is built ahead of the engine behind it, **name the dead controls** in the handover. Otherwise the intended behaviour comes back as a bug report.
