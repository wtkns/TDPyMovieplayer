"""A module whose only job is to show whether the engine kept it loaded.

Spike 3: an Engine COMP loads components "into an already-running instance",
so a Reload may or may not start from a fresh interpreter. The bootstrap in
`engine_spike.py` imports this and counts. A count that climbs across Reloads,
with `IMPORTED_AT` unchanged, means `sys.modules` survived and the real
bootstrap needs `startup.reload()`'s purge. A count stuck at 1 with a new
`IMPORTED_AT` means every Reload is a fresh import.
"""

import time

IMPORTED_AT = time.strftime("%H:%M:%S")
LOADS = 0
