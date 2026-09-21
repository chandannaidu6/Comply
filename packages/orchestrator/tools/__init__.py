from __future__ import annotations
from typing import Any
from .base import Tool, ToolResult, safe_call, to_schema
from .fetch_url import FetchUrl
from .python_exec import PythonExecs
from .web_search import WebSearch

REGISTRY: dict[str,Tool] = {
    tool.name: tool
    for tool in (
        WebSearch(),
        FetchUrl(),
        PythonExecs(),
    )
}

def all_schemas() -> list[dict[str, Any]]:
    return [to_schema(tool) for tool in REGISTRY.values()]

__all__ = ["REGISTRY", "Tool", "ToolResult", "all_schemas", "safe_call", "to_schema"]