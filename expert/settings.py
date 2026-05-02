from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="EXPERT_")

    app_name: str = "expert-assistant"
    default_model_provider: str = "dummy"
    default_model_name: str = "dummy-chat"
    max_agent_steps: int = 6

    mcp_web_search_url: str = "http://localhost:9132/rpc"
    mcp_doc_retrieval_url: str = "http://localhost:9133/rpc"
    mcp_archive_workspace_url: str = "http://localhost:9134/rpc"
    mcp_code_sandbox_url: str = "http://localhost:9135/rpc"
    mcp_citation_url: str = "http://localhost:9136/rpc"
    mcp_memory_url: str = "http://localhost:9137/rpc"
    mcp_safety_url: str = "http://localhost:9138/rpc"
    mcp_observability_url: str = "http://localhost:9139/rpc"
    mcp_cost_url: str = "http://localhost:9140/rpc"


settings = Settings()
