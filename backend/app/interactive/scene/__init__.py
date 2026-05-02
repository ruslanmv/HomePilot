"""
Scene planning subsystem.

Converts a filled BranchGraph (narration + prompts) into
production instructions: shot list, camera moves, overlay
placement, interaction UI positions.

Submodules:

  storyboard.py          plan_storyboard(graph, intent) — writes
                          the ``storyboard`` dict on every node.
  shot.py                 camera / duration / mood primitives.
  interaction_layout.py   where hotspots / choice UI render on
                          the video frame.
"""
from .interaction_layout import InteractionLayout, plan_interaction_layout
from .shot import ShotSpec
from .storyboard import plan_storyboard

__all__ = [
    "InteractionLayout",
    "plan_interaction_layout",
    "ShotSpec",
    "plan_storyboard",
]
