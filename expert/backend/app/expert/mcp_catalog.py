from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class MCPServerSpec:
    key: str
    priority: str
    purpose: str
    required_apis: List[str]


ESSENTIAL_MCP_SERVERS: List[MCPServerSpec] = [
    MCPServerSpec(
        key="mcp-web-search",
        priority="P0",
        purpose="Grounded web retrieval and citation candidates.",
        required_apis=["search(query, top_k, recency_days)", "fetch(url)", "extract(content)"],
    ),
    MCPServerSpec(
        key="mcp-doc-retrieval",
        priority="P0",
        purpose="Private knowledge retrieval and RAG.",
        required_apis=["index(document_id, text, metadata)", "query(text, top_k, filters)", "delete(document_id)"],
    ),
    MCPServerSpec(
        key="mcp-code-sandbox",
        priority="P0",
        purpose="Safe code execution and deterministic computation.",
        required_apis=["run(language, code, timeout_s, memory_mb)", "status(run_id)", "result(run_id)"],
    ),
    MCPServerSpec(
        key="mcp-citation-provenance",
        priority="P0",
        purpose="Claim to source lineage and citation integrity checks.",
        required_apis=["attach_claim(claim_text, source_refs)", "verify_citations(response_text)", "get_lineage(response_id)"],
    ),
    MCPServerSpec(
        key="mcp-memory-store",
        priority="P0",
        purpose="Durable memory service with privacy controls.",
        required_apis=["append(session_id, role, content)", "recall(session_id, limit)", "profile_upsert(user_id, key, value)", "forget(scope_id)"],
    ),
    MCPServerSpec(
        key="mcp-safety-policy",
        priority="P1",
        purpose="Input and output policy checks plus risk scoring.",
        required_apis=["check_input(text, profile)", "check_output(text, profile)", "risk_score(context)"],
    ),
    MCPServerSpec(
        key="mcp-eval-runner",
        priority="P1",
        purpose="Automated quality, safety, and cost evaluation suites.",
        required_apis=["run_suite(suite_id, model_profile)", "report(run_id)", "regression_gate(run_id, baseline_id)"],
    ),
    MCPServerSpec(
        key="mcp-observability",
        priority="P1",
        purpose="Central export for metrics, traces, and event logs.",
        required_apis=["emit_metric(name, value, tags)", "emit_trace(trace_id, spans)", "emit_event(event_type, payload)"],
    ),
    MCPServerSpec(
        key="mcp-cost-router",
        priority="P2",
        purpose="Budget-aware route recommendations and cost recording.",
        required_apis=["recommend_route(query_meta, budget_state)", "record_cost(provider, tokens, latency_ms, success)", "monthly_budget_status(org_id)"],
    ),
    MCPServerSpec(
        key="mcp-job-orchestrator",
        priority="P2",
        purpose="Long-running simulation and research job queue orchestration.",
        required_apis=["submit(job_type, payload, priority)", "status(job_id)", "cancel(job_id)", "result(job_id)"],
    ),
]


TOOL_MAPPING: Dict[str, str] = {
    "web_search": "mcp-web-search",
    "retrieval": "mcp-doc-retrieval",
    "code_exec": "mcp-code-sandbox",
    "model_compare": "mcp-eval-runner",
}

# MCP Context Forge tool identifiers used by the Expert gateway.
# Default pattern keeps names predictable and can be overridden by env.
FORGE_TOOL_MAPPING: Dict[str, str] = {
    "mcp-web-search": "mcp_web_search",
    "mcp-doc-retrieval": "mcp_doc_retrieval",
    "mcp-code-sandbox": "mcp_code_sandbox",
    "mcp-citation-provenance": "mcp_citation_provenance",
    "mcp-memory-store": "mcp_memory_store",
    "mcp-safety-policy": "mcp_safety_policy",
    "mcp-eval-runner": "mcp_eval_runner",
    "mcp-observability": "mcp_observability",
    "mcp-cost-router": "mcp_cost_router",
    "mcp-job-orchestrator": "mcp_job_orchestrator",
}


def mcp_key_to_env(key: str) -> str:
    normalized = key.upper().replace("-", "_")
    return f"EXPERT_{normalized}_URL"


def p0_required_server_keys() -> List[str]:
    return [s.key for s in ESSENTIAL_MCP_SERVERS if s.priority == "P0"]


def mcp_key_to_forge_tool_env(key: str) -> str:
    normalized = key.upper().replace("-", "_")
    return f"EXPERT_{normalized}_FORGE_TOOL_ID"
