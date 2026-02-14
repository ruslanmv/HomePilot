"""
Conversation Memory System

Lightweight, per-session memory that tracks:
  - Emotional trajectory  (what the user is feeling over time)
  - Topic history         (what we talked about and when)
  - Engagement metrics    (are they engaged, fading, or returning)
  - User preferences      (things they mentioned liking/disliking)

This feeds the prompt_builder so each response feels connected
to the full arc of conversation — not just the last message.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional


@dataclass
class TopicEntry:
    """A topic discussed during conversation."""
    topic: str
    turn_number: int
    timestamp: float = field(default_factory=time.time)
    was_followed_up: bool = False


@dataclass
class EmotionEntry:
    """Snapshot of detected user emotion."""
    emotion: str
    intensity: float  # 0.0 – 1.0
    turn_number: int
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConversationMemory:
    """
    Per-session memory for a single conversation.

    Thread-safe for single-writer (the orchestrator).
    Lightweight — no database, no persistence. Lives and dies with the session.
    """
    # Rolling topic and emotion buffers (bounded)
    topics: Deque[TopicEntry] = field(default_factory=lambda: deque(maxlen=50))
    emotions: Deque[EmotionEntry] = field(default_factory=lambda: deque(maxlen=50))

    # Simple key-value preferences detected from conversation
    preferences: Dict[str, str] = field(default_factory=dict)

    # Turn counter
    turn_count: int = 0

    # Engagement tracking
    consecutive_short_responses: int = 0
    last_activity_time: float = field(default_factory=time.time)
    is_returning_user: bool = False

    # -----------------------------------------------------------------------
    # Topic tracking
    # -----------------------------------------------------------------------

    def add_topic(self, topic: str) -> None:
        """Record a new topic discussed."""
        self.topics.append(TopicEntry(topic=topic, turn_number=self.turn_count))

    def get_unfollowed_topics(self) -> List[TopicEntry]:
        """Topics we haven't circled back to yet."""
        return [t for t in self.topics if not t.was_followed_up]

    def mark_followed_up(self, topic: str) -> None:
        """Mark a topic as followed up on."""
        for entry in self.topics:
            if entry.topic == topic:
                entry.was_followed_up = True

    def recent_topics(self, n: int = 5) -> List[str]:
        """Last N topics discussed."""
        return [t.topic for t in list(self.topics)[-n:]]

    # -----------------------------------------------------------------------
    # Emotion tracking
    # -----------------------------------------------------------------------

    def add_emotion(self, emotion: str, intensity: float = 0.5) -> None:
        """Record a detected emotion."""
        self.emotions.append(
            EmotionEntry(
                emotion=emotion,
                intensity=min(1.0, max(0.0, intensity)),
                turn_number=self.turn_count,
            )
        )

    def current_emotion(self) -> Optional[EmotionEntry]:
        """Most recently detected emotion."""
        return self.emotions[-1] if self.emotions else None

    def emotional_trajectory(self) -> List[str]:
        """Sequence of emotions across the conversation."""
        return [e.emotion for e in self.emotions]

    def is_emotional_peak(self, threshold: float = 0.7) -> bool:
        """Whether the current emotional intensity is above threshold."""
        current = self.current_emotion()
        return current is not None and current.intensity >= threshold

    # -----------------------------------------------------------------------
    # Engagement tracking
    # -----------------------------------------------------------------------

    def record_turn(self, user_message_length: int) -> None:
        """Call once per user turn to update engagement metrics."""
        self.turn_count += 1
        self.last_activity_time = time.time()

        if user_message_length < 20:
            self.consecutive_short_responses += 1
        else:
            self.consecutive_short_responses = 0

    def is_disengaging(self) -> bool:
        """Heuristic: user might be losing interest."""
        return self.consecutive_short_responses >= 3

    def seconds_since_last_activity(self) -> float:
        """Time since last user message."""
        return time.time() - self.last_activity_time

    # -----------------------------------------------------------------------
    # Preferences
    # -----------------------------------------------------------------------

    def set_preference(self, key: str, value: str) -> None:
        """Store a detected preference."""
        self.preferences[key] = value

    def get_preference(self, key: str) -> Optional[str]:
        """Retrieve a preference."""
        return self.preferences.get(key)

    # -----------------------------------------------------------------------
    # Summary for prompt injection
    # -----------------------------------------------------------------------

    def to_prompt_context(self) -> str:
        """
        Generate a compact context string for the prompt builder.
        This gets injected into the system prompt so the LLM
        is aware of conversation history.
        """
        parts: List[str] = []

        if self.turn_count > 0:
            parts.append(f"[Turn {self.turn_count}]")

        # Current emotion
        emotion = self.current_emotion()
        if emotion:
            parts.append(f"[User emotion: {emotion.emotion} ({emotion.intensity:.1f})]")

        # Recent topics
        recent = self.recent_topics(3)
        if recent:
            parts.append(f"[Recent topics: {', '.join(recent)}]")

        # Unfollowed topics
        unfollowed = self.get_unfollowed_topics()
        if unfollowed and self.turn_count > 3:
            candidates = [t.topic for t in unfollowed[-2:]]
            parts.append(f"[Consider following up on: {', '.join(candidates)}]")

        # Engagement
        if self.is_disengaging():
            parts.append("[User may be disengaging — try re-engaging or changing topic]")

        # Preferences
        if self.preferences:
            pref_str = ", ".join(f"{k}={v}" for k, v in list(self.preferences.items())[:5])
            parts.append(f"[Preferences: {pref_str}]")

        return " ".join(parts) if parts else ""
