"""The eight nodes (batch MS23).

Each is ``async (state, deps) -> partial state``. No node reads a clock, a config or a store
directly: everything it needs arrives in `state` or in `deps`, which is what lets the whole
graph run in a test with every external stubbed — MS23's acceptance — and what lets the
Note-taker path be compared frame-for-frame against the fixed loop.

**No node raises.** A graph that can take a meeting down is worse than one that occasionally
does nothing, so each catches its own failures into `errors` and returns what it has.
"""

from .perceive import perceive
from .reflect import reflect
from .decide import decide, route_after_decide
from .recall import recall
from .answer import answer
from .coach import coach
from .act import act
from .deliver import deliver

__all__ = ["perceive", "reflect", "decide", "route_after_decide", "recall", "answer",
           "coach", "act", "deliver"]
