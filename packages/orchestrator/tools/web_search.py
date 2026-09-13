from __future__ import annotations
import re 
import httpx
from pydantic import BaseModel,Field
from .base import ToolResult
import os
TAVILY_URL = "https://api.tavily.com/search"
TIMEOUT_SECONDS = 20.0
MAX_SNIPPET_CHARS = 300

API_KEY = os.getenv("BROWSER_API","")
USE_STUB = os.getenv("SEARCH_STUB", "0") == "1" or not API_KEY


class WebSearchArgs(BaseModel):
    query:str = Field(
        description=("Short keyword search query, not a full sentence. "
        "Good: 'New York money transmitter surety bond'. "
        "Poor: 'What is the surety bond requirement for money transmitters "
        "in the state of New York?'")
                )
    max_results:int = Field(
        default = 5,
        ge = 1,
        le = 10,
        description="Maximum number of search results to return, between 1 and 10.",
    )

def _format(results:list[dict],query:str)->str:
    lines : list[str] = []
    for i,r in enumerate(results,start=1):
        title = (r.get("title" or "untitled")).strip()
        url = (r.get("url" or "")).strip()
        snippet = (r.get("content") or r.get("snippet") or "").strip()
        if len(snippet) > MAX_SNIPPET_CHARS:
            snippet = snippet[:MAX_SNIPPET_CHARS] + "..."
        lines.append(f"{i}. {title}\n   URL: {url}\n   {snippet}")
 
    return f"Search results for '{query}':\n\n" + "\n\n".join(lines)

_STUB_RESULTS = [
    {
        "title": "Money Transmitter License - NYS Department of Financial Services",
        "url": "https://www.dfs.ny.gov/apps_and_licensing/money_transmitters",
        "content": "Licensing requirements for money transmitters operating "
        "in New York State, including application, surety bond, and net worth "
        "requirements. [STUB RESULT - not a real search]",
    },
    {
        "title": "NMLS Resource Center - Money Services Businesses",
        "url": "https://mortgage.nationwidelicensingsystem.org/slr/Pages/DynamicLicenses.aspx",
        "content": "State-by-state licensing requirements and checklists for "
        "money services businesses. [STUB RESULT - not a real search]",
    },
    {
        "title": "CSBS Money Transmission Modernization Act",
        "url": "https://www.csbs.org/money-transmission-modernization-act",
        "content": "Model law standardising money transmission requirements "
        "across states. [STUB RESULT - not a real search]",
    },
]
class Websearch:
    name="web search"
    description = (
        "Search the web and return a numbered list of pages with titles, "
        "full URLs, and short snippets. Use this to find candidate sources, "
        "then pass a URL to fetch_url to read the actual page. Snippets are "
        "previews only -- never answer from a snippet alone."
    )
    Args = WebSearchArgs

    def run(self, args: WebSearchArgs) -> ToolResult:
        if USE_STUB:
            results = _STUB_RESULTS[: args.max_results]
            return ToolResult(
                ok=True,
                content=_format(results, args.query),
                meta={"provider": "stub", "count": len(results)},
            )

        payload = {
            "api_key" :API_KEY,        
            "query":args.query,
            "max_results":args.max_results,
            "search_depth":"basic"
        }

        try:
            with httpx.client(timeout=TIMEOUT_SECONDS) as client:
                response = client.post(TAVILY_URL,json=payload)
        except httpx.TimeoutException:
            return ToolResult(
                ok=False,
                content=f"Search timed out after {TIMEOUT_SECONDS:.0f}s.",
                meta={"provider": "tavily", "error": "timeout"},
            )
        except httpx.RequestError as e:
            return ToolResult(
                ok=False,
                content=f"Could not reach the search service: {e}",
                meta={"provider": "tavily", "error": "request_error"},
            )
 
        if response.status_code == 401:
            return ToolResult(
                ok=False,
                content="Search API key is invalid or missing. Search is "
                "unavailable -- try answering from another source.",
                meta={"provider": "tavily", "status": 401},
            )
        if response.status_code == 429:
            return ToolResult(
                ok=False,
                content="Search rate limit reached. Wait before searching again.",
                meta={"provider": "tavily", "status": 429},
            )
        if response.status_code >= 400:
            return ToolResult(
                ok=False,
                content=f"Search failed with HTTP {response.status_code}.",
                meta={"provider": "tavily", "status": response.status_code},
            )

        try:
            results = response.json().get("results",[])
        except Exception as e:
            return ToolResult(
                ok=False,
                content=f"Search returned an unreadable response: {e}",
                meta={"provider": "tavily", "error": "parse_error"},
            )
 

        if not results:
            return ToolResult(
                ok=True,
                content=(
                    f"No results found for '{args.query}'. "
                    "Try different or broader keywords."
                ),
                meta={"provider": "tavily", "count": 0},
            )
 
        return ToolResult(
            ok=True,
            content=_format(results, args.query),
            meta={"provider": "tavily", "count": len(results)},
        )


