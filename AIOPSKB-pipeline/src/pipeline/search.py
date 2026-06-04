import os
from config import TAVILY_API_KEY

# Search provider: "duckduckgo" (default, free) or "tavily" (requires API key + credits)
SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "duckduckgo").strip('"')

# Max chars per search result snippet (trim to save tokens)
MAX_SNIPPET_LENGTH = 300


# ── DuckDuckGo (free, no API key) ──

def _ddg_search(query: str, max_results: int = 5) -> list[dict]:
    import warnings
    warnings.filterwarnings("ignore")
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("href", r.get("url", "")),
                "content": r.get("body", r.get("content", "")),
            })
    return results


# ── Tavily (requires API key + credits) ──

def _tavily_search(query: str, max_results: int = 5) -> list[dict]:
    from tavily import TavilyClient
    client = TavilyClient(api_key=TAVILY_API_KEY)
    resp = client.search(query=query, max_results=max_results, search_depth="advanced")
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
        for r in resp.get("results", [])
    ]


# ── Unified interface ──

def web_search(query: str, max_results: int = 5) -> list[dict]:
    if SEARCH_PROVIDER == "tavily":
        return _tavily_search(query, max_results)
    try:
        return _ddg_search(query, max_results)
    except Exception:
        return []


def search_and_format(queries: list[str], max_results: int = 3) -> str:
    """Search multiple queries, deduplicate, trim, and format for LLM consumption."""
    all_results = []
    seen_urls = set()
    for q in queries:
        try:
            results = web_search(q, max_results)
            for r in results:
                if r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    # Trim content to save tokens
                    content = r["content"][:MAX_SNIPPET_LENGTH]
                    if len(r["content"]) > MAX_SNIPPET_LENGTH:
                        content += "..."
                    all_results.append({
                        "title": r["title"],
                        "url": r["url"],
                        "content": content,
                    })
        except Exception as e:
            all_results.append({"title": f"[搜索错误: {q}]", "url": "", "content": str(e)})

    if not all_results:
        return "未获取到搜索结果。"

    parts = ["## 搜索结果\n"]
    for i, r in enumerate(all_results, 1):
        parts.append(f"### [{i}] {r['title']}")
        if r["url"]:
            parts.append(f"来源: {r['url']}")
        parts.append(r["content"])
        parts.append("")

    return "\n".join(parts)
