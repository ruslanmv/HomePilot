"""Marketplace module — optional proxy to Matrix Hub for MCP server discovery."""

from .routes import router as marketplace_router

__all__ = ["marketplace_router"]
