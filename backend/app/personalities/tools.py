"""
Personality-Aware Tool Declarations

Maps personality allowed_tools to actual tool schemas.
When the orchestrator asks "what tools does this personality have?",
this module returns the filtered, validated list.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .types import PersonalityAgent


# ---------------------------------------------------------------------------
# Master tool catalog
# Each entry is a tool declaration compatible with the OpenAI/Anthropic
# function-calling format. The orchestrator sends these alongside the prompt.
# ---------------------------------------------------------------------------
TOOL_CATALOG: Dict[str, Dict[str, Any]] = {
    "imagine": {
        "name": "imagine",
        "description": "Generate an image based on a text description",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed description of the image to generate",
                },
            },
            "required": ["prompt"],
        },
    },
    "search": {
        "name": "search",
        "description": "Search the web for current information",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
            },
            "required": ["query"],
        },
    },
    "smart_home": {
        "name": "smart_home",
        "description": "Control smart home devices (lights, thermostat, locks, etc.)",
        "parameters": {
            "type": "object",
            "properties": {
                "device": {
                    "type": "string",
                    "description": "Device name or area",
                },
                "action": {
                    "type": "string",
                    "description": "Action to perform (on, off, set, toggle)",
                },
                "value": {
                    "type": "string",
                    "description": "Optional value (brightness, temperature, etc.)",
                },
            },
            "required": ["device", "action"],
        },
    },
    "reminder": {
        "name": "reminder",
        "description": "Set a reminder for the user",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Reminder message",
                },
                "when": {
                    "type": "string",
                    "description": "When to remind (e.g. 'in 30 minutes', 'tomorrow at 9am')",
                },
            },
            "required": ["message", "when"],
        },
    },
    "weather": {
        "name": "weather",
        "description": "Get current weather information",
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "Location for weather (default: user's location)",
                },
            },
            "required": [],
        },
    },
    "animate": {
        "name": "animate",
        "description": "Create a simple animation or visual effect",
        "parameters": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Description of the animation to create",
                },
                "style": {
                    "type": "string",
                    "description": "Animation style (sparkle, wave, bounce, fade)",
                },
            },
            "required": ["description"],
        },
    },
}


def get_tools_for_agent(agent: PersonalityAgent) -> List[Dict[str, Any]]:
    """
    Return the tool declarations this personality is allowed to use.

    Only tools listed in agent.allowed_tools AND present in TOOL_CATALOG
    are returned. Unknown tool names are silently skipped.
    """
    return [
        TOOL_CATALOG[tool_name]
        for tool_name in agent.allowed_tools
        if tool_name in TOOL_CATALOG
    ]


def get_tool_names_for_agent(agent: PersonalityAgent) -> List[str]:
    """Return just the tool names this personality can use."""
    return [name for name in agent.allowed_tools if name in TOOL_CATALOG]
