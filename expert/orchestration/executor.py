import httpx
from typing import Awaitable, Callable, Optional
from expert.types import ToolResult, AgentEvent
from expert.orchestration.fallback_router import FallbackRouter


EventCallback = Callable[[AgentEvent], Awaitable[None]]


class ToolExecutor:
    def __init__(self, registry: dict[str, object]):
        self.registry = registry
        self.fallback_router = FallbackRouter()

    async def call(
        self,
        tool_name: str,
        arguments: dict,
        emit: Optional[EventCallback] = None,
    ) -> ToolResult:
        if emit:
            await emit(AgentEvent(type="tool_start", data={"tool_name": tool_name, "arguments": arguments}))

        meta = self.registry[tool_name]
        payload = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        try:
            async with httpx.AsyncClient(timeout=25) as client:
                resp = await client.post(meta.server_url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                result = ToolResult(tool_name=tool_name, ok=True, data=data)

                if emit:
                    await emit(AgentEvent(type="tool_result", data={
                        "tool_name": tool_name,
                        "ok": True,
                        "result": result.model_dump(),
                    }))

                return result
        except Exception as e:
            error_result = ToolResult(tool_name=tool_name, ok=False, error=str(e))

            if emit:
                await emit(AgentEvent(type="tool_error", data={
                    "tool_name": tool_name,
                    "error": str(e),
                }))

            fallback = self.fallback_router.pick_fallback(tool_name)
            if fallback and fallback in self.registry:
                if emit:
                    await emit(AgentEvent(type="status", data={
                        "message": f"Falling back from {tool_name} to {fallback}"
                    }))
                return await self.call(fallback, arguments, emit=emit)

            return error_result
