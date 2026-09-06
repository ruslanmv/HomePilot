"""Try harder before giving up, and never lead with a model's name (batch V6).

Two things live here, and they are the same idea from two sides.

**The ladder** (`ladder.py`) turns one model call into a sequence: the whole screen, then each
crop on its own at close to native resolution, then a better installed model, and only then an
admission. The crop rung is the one that does the work, and it works on today's models because
each crop is its own ordinary single-image request — V5's gate guards several images in *one*
request, which is a different and harder thing to ask of a model.

**The copy** (`copy.py`) is what a person reads when none of that was enough. The rule is that
the model's name is not the first thing they see. "moondream returned no description of the
image" names a piece of software the user did not choose and offers them nothing to do; the name
belongs beside the command that fixes it, in the last message, once the retries are spent.

`usable.py` is the judgement that drives both: a vision model handed a destroyed screenshot
rarely errors, it answers "An image of a computer screen." So the ladder cannot switch on a
status code — it has to look at the reply. That judgement is deliberately generous, because the
best reply is always kept: being wrong costs a model call, never an answer.
"""

from .copy import LOOKING, could_not_read, no_vision_model  # noqa: F401
from .ladder import analyze_persistently  # noqa: F401
from .usable import assess  # noqa: F401

__all__ = ["LOOKING", "analyze_persistently", "assess", "could_not_read", "no_vision_model"]
