import uuid


class ArchiveRegistry:
    def __init__(self):
        self._registry = {}

    def register_archive(self, session_id: str, path: str) -> dict:
        workspace_id = str(uuid.uuid4())
        self._registry[workspace_id] = {"session_id": session_id, "path": path}
        return {"workspace_id": workspace_id, "path": path}

    def get(self, workspace_id: str):
        return self._registry.get(workspace_id)


archive_registry = ArchiveRegistry()
