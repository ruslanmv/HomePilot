from expert.orchestration.tool_registry import build_registry
from expert.orchestration.tool_router import ToolRouter


def test_router_workspace():
    router = ToolRouter(build_registry())
    tools = router.route("open this zip and search files")
    assert "hp.ws.search" in tools
