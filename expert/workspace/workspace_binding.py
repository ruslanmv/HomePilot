class WorkspaceBinding:
    def __init__(self):
        self._bindings: dict[str, str] = {}

    def bind(self, session_id: str, workspace_id: str) -> None:
        self._bindings[session_id] = workspace_id

    def get(self, session_id: str) -> str | None:
        return self._bindings.get(session_id)

    def unbind(self, session_id: str) -> None:
        self._bindings.pop(session_id, None)


workspace_binding = WorkspaceBinding()
