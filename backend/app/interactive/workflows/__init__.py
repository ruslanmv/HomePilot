"""
Workflow runner package.

Public surface:

* ``Step``, ``WorkflowRunner`` — the in-house orchestrator.
* ``WorkflowEvent`` — structured event emitted during a run.
* ``StepResult``, ``WorkflowResult`` — return shapes.
* ``StepFailure`` — raised when ``fallback=abort`` trips.
* ``extract_content`` — tiny helper shared with other modules.
"""
from .runner import (
    Step,
    StepFailure,
    StepResult,
    WorkflowEvent,
    WorkflowResult,
    WorkflowRunner,
    extract_content,
)

__all__ = [
    "Step",
    "StepFailure",
    "StepResult",
    "WorkflowEvent",
    "WorkflowResult",
    "WorkflowRunner",
    "extract_content",
]
