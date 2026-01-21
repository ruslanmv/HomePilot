"""
Search provider for HomePilot
Implements web search with summarization (Grok-style) and conversation history search
"""
from typing import Any, Dict, List, Optional
import httpx
from .llm import chat as llm_chat
from .storage import get_messages


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


# ==========================================
# Conversation History Search
# ==========================================

def search_conversation_history(
    query: str,
    conversation_id: Optional[str] = None,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Search through conversation history

    Args:
        query: Search query string
        conversation_id: Optional conversation ID to search within specific conversation
        limit: Maximum number of results to return

    Returns:
        List of matching messages with context
    """
    if not query or not query.strip():
        return []

    query_lower = query.lower().strip()
    results = []

    # Get messages from conversation
    if conversation_id:
        # Use get_messages which returns List[Dict] with 'role', 'content', 'created_at'
        messages = get_messages(conversation_id, limit=1000)  # Get many messages for searching
    else:
        # If no conversation_id, search recent messages across all conversations
        # For now, we'll just return empty since we need conversation context
        return []

    # Search through messages
    for msg in messages:
        content = msg.get("content", "")
        if not content:
            continue

        content_lower = content.lower()

        # Calculate relevance score
        relevance_score = 0

        # Exact phrase match (highest score)
        if query_lower in content_lower:
            relevance_score = 10
            # Boost if it's at the start of the message
            if content_lower.startswith(query_lower):
                relevance_score += 5
        # Word-based matching (medium score)
        elif _contains_all_words(content_lower, query_lower):
            relevance_score = 5

        # No match
        if relevance_score == 0:
            continue

        # Extract context snippet
        snippet = _extract_snippet(content, query_lower)

        # Use created_at from get_messages (ISO timestamp string)
        timestamp = msg.get("created_at", "")

        results.append({
            "role": msg.get("role", ""),
            "content": content,
            "snippet": snippet,
            "timestamp": timestamp,
            "relevance_score": relevance_score
        })

    # Sort by relevance and timestamp
    results.sort(key=lambda x: (
        -x["relevance_score"],
        -x["timestamp"]
    ))

    return results[:limit]


def _contains_all_words(text: str, query: str) -> bool:
    """Check if text contains all words from query"""
    query_words = query.split()
    return all(word in text for word in query_words)


def _extract_snippet(text: str, query: str, context_length: int = 100) -> str:
    """
    Extract a snippet of text around the search query

    Args:
        text: Full text content
        query: Search query
        context_length: Characters to show around the match

    Returns:
        Text snippet with query highlighted
    """
    text_lower = text.lower()
    query_lower = query.lower()

    # Find first occurrence
    idx = text_lower.find(query_lower)

    if idx == -1:
        # If no exact match, just return start of text
        return text[:context_length * 2] + ("..." if len(text) > context_length * 2 else "")

    # Calculate start and end positions
    start = max(0, idx - context_length)
    end = min(len(text), idx + len(query) + context_length)

    snippet = text[start:end]

    # Add ellipsis if truncated
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."

    return snippet
