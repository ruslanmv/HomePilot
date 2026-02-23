"""HomePilot MCP server: Inventory

Read-only inventory service that lets agents query project/persona assets
(photos, outfits, documents) using the existing HomePilot legacy storage:

  - uploads/projects_metadata.json
  - uploads/homepilot.db  (file_assets table)
  - uploads/projects/<project_id>/persona/appearance/*

Tools:
  hp.inventory.list_categories
  hp.inventory.search
  hp.inventory.get
  hp.inventory.resolve_media
"""

__all__ = ["app"]
