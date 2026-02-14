"""
HomePilot Personality Agent Framework
======================================

Production-grade personality system that replaces fragmented frontend
personality configs with a unified, backend-authoritative agent framework.

Public API:

    from backend.app.personalities import (
        registry,              # PersonalityRegistry singleton
        build_system_prompt,   # Dynamic prompt assembly
        ConversationMemory,    # Per-session conversation memory
        PersonalityAgent,      # Type for a personality definition
        get_tools_for_agent,   # Filtered tool declarations
    )

Quick usage:

    agent = registry.get("therapist")
    memory = ConversationMemory()
    prompt = build_system_prompt(agent, memory, is_first_turn=True)
"""

from .types import PersonalityAgent
from .registry import registry
from .memory import ConversationMemory
from .prompt_builder import build_system_prompt
from .tools import get_tools_for_agent, get_tool_names_for_agent

__all__ = [
    "PersonalityAgent",
    "registry",
    "ConversationMemory",
    "build_system_prompt",
    "get_tools_for_agent",
    "get_tool_names_for_agent",
]
