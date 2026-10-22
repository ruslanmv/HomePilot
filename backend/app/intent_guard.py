"""When a keyword shortcut may answer instead of the model.

Persona chats have deterministic fast paths ("show me your back" → the back view, "photo 2" →
the second photo) and prompt hints built from the same keywords. They scan for words such as
"back", "first", "front", "more" — which any long text contains. A user who pasted a work log
and asked "give a summary" got "I only have the front in my look for now. Here it is!": the
paste said "moved HomePilot back to 8002" and "the reply first shows…".

A display command is short. Anything longer — a question with context, a pasted document, a
composed message — goes to the model, which reads all of it.
"""
from __future__ import annotations

MAX_COMMAND_CHARS = 160
MAX_COMMAND_WORDS = 24
MAX_COMMAND_LINES = 2


def is_short_command(message: str) -> bool:
    """Whether ``message`` is short enough to be a display command a keyword shortcut may
    answer: at most two lines, 160 characters and 24 words."""
    text = (message or "").strip()
    if not text:
        return False
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) > MAX_COMMAND_LINES:
        return False
    return len(text) <= MAX_COMMAND_CHARS and len(text.split()) <= MAX_COMMAND_WORDS
