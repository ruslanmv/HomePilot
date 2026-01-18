"""
Search provider for HomePilot
Implements web search with summarization (Grok-style)
"""
from typing import Any, Dict, List, Optional
import httpx
from .llm import chat as llm_chat


async def web_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    """
    Perform web search using a search provider

    TODO: Integrate with real search API (SerpAPI, Brave Search, etc.)
    For now, returns mock results
    """
    # Mock results - replace with real search API
    return [
        {
            "title": f"Result for: {query}",
            "url": "https://example.com/search",
            "snippet": f"This is a mock search result for '{query}'. Integrate with SerpAPI, Brave Search, or DuckDuckGo API for real results.",
            "published_date": "2026-01-18"
        }
    ]


async def summarize_results(query: str, results: List[Dict[str, Any]], provider: str = "openai_compat") -> str:
    """
    Use LLM to summarize search results (Grok-style)
    """
    if not results:
        return "No search results found."

    # Build context from search results
    context = f"User query: {query}\n\nSearch results:\n\n"
    for idx, result in enumerate(results, 1):
        context += f"{idx}. {result['title']}\n"
        context += f"   {result['snippet']}\n"
        context += f"   Source: {result['url']}\n\n"

    # System prompt for search summarization
    system = """You are a search assistant. Provide a concise, accurate summary of the search results.

    - Cite sources using [1], [2], etc.
    - Be direct and informative
    - If results are limited/mock, acknowledge it
    - Maintain a helpful, Grok-like tone
    """

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Summarize these search results:\n\n{context}"}
    ]

    try:
        response = await llm_chat(
            messages,
            provider=provider,
            temperature=0.3,  # Lower temperature for factual summarization
            max_tokens=500
        )

        summary = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        return summary.strip() or "Could not generate summary."

    except Exception as e:
        return f"Error generating summary: {str(e)}"


async def run_search(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main search handler

    Returns:
        {
            "type": "search",
            "query": str,
            "summary": str,
            "results": List[Dict],
            "provider": str
        }
    """
    query = payload.get("message", "").strip()
    provider = payload.get("provider", "openai_compat")

    if not query:
        return {
            "type": "search",
            "query": "",
            "summary": "Please provide a search query.",
            "results": [],
            "provider": provider
        }

    # Perform search
    results = await web_search(query, max_results=5)

    # Summarize results
    summary = await summarize_results(query, results, provider)

    return {
        "type": "search",
        "query": query,
        "summary": summary,
        "results": results,
        "provider": provider
    }
