"""
Analytics subsystem — read-side queries over session events.

  aggregator.py   session_summary(session_id) → dict
                  experience_summary(experience_id) → dict

All functions are read-only SQL over ``ix_session_events`` +
``ix_session_turns`` + ``ix_session_progress``. No mutation, safe
to call from public endpoints.
"""
from .aggregator import (
    ExperienceSummary,
    SessionSummary,
    experience_summary,
    session_summary,
)

__all__ = [
    "ExperienceSummary",
    "SessionSummary",
    "experience_summary",
    "session_summary",
]
