"""Meeting intelligence — the typed layer on top of a finished transcript.

One ``MeetingAnalysis`` per transcript version: topics, decisions (confirmed / proposed /
rejected), risks, action items, open questions and conclusions, every one of them carrying a
verbatim quote and the transcript line it came from. A validator keeps an item only when its
quote really is in that line, so what the visual page shows is what the meeting said.

From the analysis the module derives a ``VisualSpec`` — the one-page summary as a list of
typed blocks whose cells reference analysis items by id — and a handful of suggested
questions for the assistant.

Additive and flag-gated (``MEETINGS_INTELLIGENCE``, default off). Nothing here touches
MeetingSense's own tables, routes or the live recorder, and nothing here calls a model when
none is configured: without one, the analysis is assembled from the meeting's own words and
says so (``degraded == "extractive"``).
"""

from .schema import SCHEMA_VERSION, MeetingAnalysis, SuggestedQuestion, VisualSpec

__all__ = ["SCHEMA_VERSION", "MeetingAnalysis", "SuggestedQuestion", "VisualSpec"]
