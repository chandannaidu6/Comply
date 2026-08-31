from __future__ import annotations
import re 
import httpx
from pydantic import BaseModel,Field
from .base import ToolResult

MAX_CHARS = 8000
TIMEOUT_SECONDS = 20.0

HEADERS = {
    "User-Agent": "Comply/0.1 (compliance research agent; +contact@example.com)" 
}

class FetchUrlArgs(BaseModel):
    url:str = Field(
        description="Full URL including the https:// scheme, e.g. "
        "'https://www.dfs.ny.gov/some/page'."
    )

def _strip_html(html:str)->str:
    html = re.sub(r"<(script|style)\b[^>]*>.*?</\1>"," ",html,flags=re.S | re.I)
    html = re.sub(r"</(p|div|br|li|h[1-6]|tr)\s*>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    for entity, char in (
        ("&nbsp;", " "),
        ("&amp;", "&"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&quot;", '"'),
        ("&#39;", "'"),
    ):
        text = text.replace(entity, char)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()

class FetchUrl:
    name = "fetch_url"
    description = (
        "Fetch a web page and return its readable text with HTML stripped. "
        "Use after web_search to read a specific result, or when you already "
        "know the exact URL. Returns plain text truncated to about 8000 "
        "characters. Requires a full URL including https://."
    )
    Args = FetchUrlArgs

    def run(self,args:FetchUrlArgs)->ToolResult:
        if not args.url.startswith(("http://", "https://")):
            return ToolResult(
                ok=False,
                content= (f"URL must start with http:// or https://. Got: {args.url}"),
                meta = {"url":args.url},
            )
        try:
            with httpx.Client(timeout = TIMEOUT_SECONDS,follow_redirects=True,headers=HEADERS) as client:
                response = client.get(args.url)
        except httpx.TimeoutException:
            return ToolResult(
                ok=False,
                content=f"Timed out after {TIMEOUT_SECONDS:.0f}s fetching {args.url}",
                meta={"url": args.url, "error": "timeout"},
            )
        except httpx.RequestError as e:
            return ToolResult(
                ok=False,
                content=f"Could not reach {args.url}: {e}",
                meta={"url": args.url, "error": "request_error"},
            )

        if response.status.code>= 400:
            return ToolResult(
                ok=False,
                content=f"Could not reach {args.url}: {e}",
                meta={"url": args.url, "error": "request_error"},
            )

        content_type = response.headers.get("content-type","")
        if not content_type.startswith(("text/", "application/xhtml")):
            return ToolResult(
                ok=False,
                content=(
                    f"Unsupported content type '{content_type}' at {args.url}. "
                    "This tool reads HTML and plain text only."
                ),
                meta={"url": args.url, "content_type": content_type},
            )

        text = _strip_html(response.text)
        truncated = len(text)>MAX_CHARS
        if truncated:
            text = text[:MAX_CHARS] + "\n\n[... truncated ...]"

        if not text:
            return ToolResult(
                ok=False,
                content=(
                    f"{args.url} returned no readable text (likely a "
                    "JavaScript-rendered page)."
                ),
                meta={"url": args.url, "status": response.status_code},
            )

        return ToolResult(
            ok=True,
            content=text,
            meta={
                "url":str(response.url),
                "status":response.status_code,
                "truncated":truncated,
                "chars":len(text)
            }
        )
        


        

            





