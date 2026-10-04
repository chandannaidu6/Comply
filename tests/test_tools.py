"""Tests for the tool layer.

Three tiers:
  - Default: fully offline. HTTP is faked with httpx.MockTransport, so these
    run in CI with no network, no API keys, no Docker.
  - SANDBOX_ENABLED=1 + Docker running: real container tests for python_exec.
  - LIVE_TESTS=1: hits the real internet (example.com, Tavily).

Run:
    uv run pytest tests/test_tools.py -v
    $env:SANDBOX_ENABLED="1"; uv run pytest tests/test_tools.py -v
    $env:LIVE_TESTS="1";      uv run pytest tests/test_tools.py -v
"""

from __future__ import annotations

import os

import httpx
import pytest
from pydantic import BaseModel

import packages.orchestrator.tools.fetch_url as fetch_mod
import packages.orchestrator.tools.python_exec as exec_mod
import packages.orchestrator.tools.web_search as search_mod
from packages.orchestrator.tools import REGISTRY, Tool, all_schemas, safe_call
from packages.orchestrator.tools.base import ToolResult, to_schema
from packages.orchestrator.tools.fetch_url import FetchUrl, FetchUrlArgs
from packages.orchestrator.tools.python_exec import PythonExecs, PythonExecArgs
from packages.orchestrator.tools.web_search import WebSearch, WebSearchArgs

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

_REAL_CLIENT = httpx.Client


def fake_http(monkeypatch, handler):
    """Route every httpx.Client created inside the tools through `handler`.

    `handler(request) -> httpx.Response`. No real network is touched.
    """

    def client_factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_CLIENT(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)


def html_response(body: str, status: int = 200, ctype: str = "text/html") -> httpx.Response:
    return httpx.Response(status, text=body, headers={"content-type": ctype})


def docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:  # noqa: BLE001
        return False


needs_docker = pytest.mark.skipif(
    os.getenv("SANDBOX_ENABLED") != "1" or not docker_available(),
    reason="set SANDBOX_ENABLED=1 and start Docker Desktop",
)
needs_live = pytest.mark.skipif(
    os.getenv("LIVE_TESTS") != "1", reason="set LIVE_TESTS=1 to hit the real network"
)


# --------------------------------------------------------------------------
# base.py: safe_call and to_schema
# --------------------------------------------------------------------------


class _EchoArgs(BaseModel):
    text: str


class _Echo:
    name = "echo"
    description = "Echo the text back."
    Args = _EchoArgs

    def run(self, args: _EchoArgs) -> ToolResult:
        return ToolResult(ok=True, content=args.text)


class _Boom:
    name = "boom"
    description = "Always raises."
    Args = _EchoArgs

    def run(self, args: _EchoArgs) -> ToolResult:
        raise RuntimeError("kaboom")


def test_safe_call_happy_path():
    result = safe_call(_Echo(), {"text": "hi"})
    assert result.ok is True
    assert result.content == "hi"


def test_safe_call_missing_arg_is_validation_failure():
    result = safe_call(_Echo(), {})
    assert result.ok is False
    assert result.meta["stage"] == "validation"
    assert "Invalid arguments" in result.content


def test_safe_call_wrong_type_is_validation_failure():
    result = safe_call(_Echo(), {"text": {"nested": "dict"}})
    assert result.ok is False
    assert result.meta["stage"] == "validation"


def test_safe_call_malformed_json_from_model_is_recoverable():
    """models.py turns broken JSON into {'__malformed__': raw}. It must not crash."""
    result = safe_call(FetchUrl(), {"__malformed__": '{"url": "https://www.dfs.ny'})
    assert result.ok is False
    assert result.meta["stage"] == "validation"


def test_safe_call_catches_exceptions_from_run():
    """The core guarantee: nothing escapes a tool."""
    result = safe_call(_Boom(), {"text": "x"})
    assert result.ok is False
    assert result.meta["stage"] == "execution"
    assert "RuntimeError" in result.content
    assert "kaboom" in result.content


def test_tool_result_meta_is_not_shared_between_instances():
    """default_factory, not a shared mutable default."""
    a = ToolResult(ok=True, content="a")
    b = ToolResult(ok=True, content="b")
    a.meta["x"] = 1
    assert b.meta == {}


def test_to_schema_shape():
    schema = to_schema(_Echo())
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "echo"
    assert fn["description"] == "Echo the text back."
    assert fn["parameters"]["type"] == "object"
    assert "text" in fn["parameters"]["properties"]
    assert "text" in fn["parameters"]["required"]


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def test_registry_contains_the_three_tools():
    assert set(REGISTRY) == {"web_search", "fetch_url", "python_execs"}


def test_registry_keys_match_tool_names():
    for key, tool in REGISTRY.items():
        assert key == tool.name


def test_every_registered_tool_satisfies_the_protocol():
    for tool in REGISTRY.values():
        assert isinstance(tool, Tool)
        assert tool.description.strip(), f"{tool.name} has an empty description"


def test_all_schemas_one_per_tool():
    schemas = all_schemas()
    assert len(schemas) == len(REGISTRY)
    assert {s["function"]["name"] for s in schemas} == set(REGISTRY)


# --------------------------------------------------------------------------
# fetch_url (offline, mocked HTTP)
# --------------------------------------------------------------------------


def test_fetch_strips_html_and_scripts(monkeypatch):
    page = """
    <html><head><style>body{color:red}</style>
    <script>alert('should vanish')</script></head>
    <body><h1>Surety Bond</h1><p>Minimum bond is $500,000 &amp; up.</p></body></html>
    """
    fake_http(monkeypatch, lambda req: html_response(page))

    result = FetchUrl().run(FetchUrlArgs(url="https://example.com"))

    assert result.ok is True
    assert "Surety Bond" in result.content
    assert "$500,000 & up" in result.content  # entity unescaped
    assert "<" not in result.content  # no tags left
    assert "alert" not in result.content  # script body removed
    assert "color:red" not in result.content  # style body removed
    assert result.meta["status"] == 200


def test_fetch_rejects_url_without_scheme(monkeypatch):
    def fail_if_called(req):
        raise AssertionError("no request should be made for a bad URL")

    fake_http(monkeypatch, fail_if_called)
    result = FetchUrl().run(FetchUrlArgs(url="www.dfs.ny.gov"))
    assert result.ok is False
    assert "https://" in result.content


def test_fetch_404_is_actionable_failure(monkeypatch):
    fake_http(monkeypatch, lambda req: html_response("not found", status=404))
    result = FetchUrl().run(FetchUrlArgs(url="https://example.com/missing"))
    assert result.ok is False
    assert result.meta["status"] == 404
    assert "try a different URL" in result.content


def test_fetch_timeout_is_failure_not_exception(monkeypatch):
    def slow(req):
        raise httpx.ReadTimeout("too slow", request=req)

    fake_http(monkeypatch, slow)
    result = FetchUrl().run(FetchUrlArgs(url="https://example.com"))
    assert result.ok is False
    assert result.meta["error"] == "timeout"


def test_fetch_connection_error_is_failure(monkeypatch):
    def unreachable(req):
        raise httpx.ConnectError("no route", request=req)

    fake_http(monkeypatch, unreachable)
    result = FetchUrl().run(FetchUrlArgs(url="https://example.com"))
    assert result.ok is False
    assert result.meta["error"] == "request_error"


def test_fetch_rejects_pdf(monkeypatch):
    fake_http(
        monkeypatch,
        lambda req: httpx.Response(
            200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"}
        ),
    )
    result = FetchUrl().run(FetchUrlArgs(url="https://example.com/rule.pdf"))
    assert result.ok is False
    assert "application/pdf" in result.content


def test_fetch_truncates_long_pages(monkeypatch):
    big = "<p>" + ("word " * 5_000) + "</p>"
    fake_http(monkeypatch, lambda req: html_response(big))
    result = FetchUrl().run(FetchUrlArgs(url="https://example.com"))
    assert result.ok is True
    assert result.meta["truncated"] is True
    assert "[... truncated ...]" in result.content
    assert len(result.content) < fetch_mod.MAX_CHARS + 100


def test_fetch_empty_page_is_failure(monkeypatch):
    """A JS-rendered page returns 200 with no text. That's not success."""
    fake_http(monkeypatch, lambda req: html_response("<html><script>app()</script></html>"))
    result = FetchUrl().run(FetchUrlArgs(url="https://example.com"))
    assert result.ok is False
    assert "JavaScript" in result.content


def test_fetch_records_post_redirect_url(monkeypatch):
    """The citation must point at where we landed, not where we asked."""

    def handler(req):
        if req.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://example.com/new"})
        return html_response("<p>moved content</p>")

    fake_http(monkeypatch, handler)
    result = FetchUrl().run(FetchUrlArgs(url="https://example.com/old"))
    assert result.ok is True
    assert result.meta["url"] == "https://example.com/new"


# --------------------------------------------------------------------------
# web_search (offline: stub mode and mocked Tavily)
# --------------------------------------------------------------------------


@pytest.fixture
def tavily_mode(monkeypatch):
    """Force the real-API code path with a fake key."""
    monkeypatch.setattr(search_mod, "USE_STUB", False)
    monkeypatch.setattr(search_mod, "API_KEY", "test-key")


def test_search_stub_mode_returns_fetchable_urls(monkeypatch):
    monkeypatch.setattr(search_mod, "USE_STUB", True)
    result = WebSearch().run(WebSearchArgs(query="ny money transmitter bond"))
    assert result.ok is True
    assert result.meta["provider"] == "stub"
    assert "URL: https://" in result.content
    assert "STUB RESULT" in result.content


def test_search_stub_respects_max_results(monkeypatch):
    monkeypatch.setattr(search_mod, "USE_STUB", True)
    result = WebSearch().run(WebSearchArgs(query="x", max_results=2))
    assert result.meta["count"] == 2


def test_search_formats_tavily_results(monkeypatch, tavily_mode):
    payload = {
        "results": [
            {
                "title": "NY DFS Money Transmitters",
                "url": "https://www.dfs.ny.gov/money_transmitters",
                "content": "Bond requirements for licensees.",
            }
        ]
    }
    fake_http(monkeypatch, lambda req: httpx.Response(200, json=payload))

    result = WebSearch().run(WebSearchArgs(query="ny bond"))

    assert result.ok is True
    assert result.meta["provider"] == "tavily"
    assert "1. NY DFS Money Transmitters" in result.content
    assert "URL: https://www.dfs.ny.gov/money_transmitters" in result.content


def test_search_sends_key_and_query(monkeypatch, tavily_mode):
    seen = {}

    def handler(req):
        import json

        seen.update(json.loads(req.content))
        return httpx.Response(200, json={"results": []})

    fake_http(monkeypatch, handler)
    WebSearch().run(WebSearchArgs(query="surety bond", max_results=3))
    assert seen["api_key"] == "test-key"
    assert seen["query"] == "surety bond"
    assert seen["max_results"] == 3


def test_search_long_snippet_truncated_but_url_intact(monkeypatch, tavily_mode):
    long_url = "https://www.dfs.ny.gov/" + "deep/" * 30 + "page"
    payload = {"results": [{"title": "T", "url": long_url, "content": "z" * 2_000}]}
    fake_http(monkeypatch, lambda req: httpx.Response(200, json=payload))

    result = WebSearch().run(WebSearchArgs(query="x"))

    assert long_url in result.content  # the fetch_url handoff depends on this
    assert "z" * 2_000 not in result.content


def test_search_zero_results_is_success(monkeypatch, tavily_mode):
    fake_http(monkeypatch, lambda req: httpx.Response(200, json={"results": []}))
    result = WebSearch().run(WebSearchArgs(query="nothing matches this"))
    assert result.ok is True
    assert result.meta["count"] == 0
    assert "No results" in result.content


def test_search_bad_key_names_the_problem(monkeypatch, tavily_mode):
    fake_http(monkeypatch, lambda req: httpx.Response(401, json={"error": "bad key"}))
    result = WebSearch().run(WebSearchArgs(query="x"))
    assert result.ok is False
    assert result.meta["status"] == 401
    assert "API key" in result.content


def test_search_rate_limit(monkeypatch, tavily_mode):
    fake_http(monkeypatch, lambda req: httpx.Response(429))
    result = WebSearch().run(WebSearchArgs(query="x"))
    assert result.ok is False
    assert result.meta["status"] == 429


def test_search_max_results_is_bounded():
    """The model can't ask for 500 results."""
    result = safe_call(WebSearch(), {"query": "x", "max_results": 500})
    assert result.ok is False
    assert result.meta["stage"] == "validation"


# --------------------------------------------------------------------------
# python_exec
# --------------------------------------------------------------------------


def test_exec_disabled_by_default(monkeypatch):
    monkeypatch.setattr(exec_mod, "ENABLED", False)
    result = PythonExecs().run(PythonExecArgs(code="print(1)"))
    assert result.ok is False
    assert result.meta["reason"] == "sandbox_disabled"


@needs_docker
def test_exec_returns_stdout(monkeypatch):
    monkeypatch.setattr(exec_mod, "ENABLED", True)
    result = PythonExecs().run(PythonExecArgs(code="print(2 ** 10)"))
    assert result.ok is True
    assert "1024" in result.content


@needs_docker
def test_exec_traceback_comes_back_as_content(monkeypatch):
    """The traceback is exactly what the model needs to fix its code."""
    monkeypatch.setattr(exec_mod, "ENABLED", True)
    result = PythonExecs().run(PythonExecArgs(code="1 / 0"))
    assert result.ok is False
    assert "ZeroDivisionError" in result.content
    assert result.meta["exit_code"] != 0


@needs_docker
def test_exec_has_no_network(monkeypatch):
    """The security test. If this ever passes a request through, stop everything."""
    monkeypatch.setattr(exec_mod, "ENABLED", True)
    code = (
        "import urllib.request\n"
        "urllib.request.urlopen('https://example.com', timeout=5)\n"
        "print('NETWORK REACHABLE')"
    )
    result = PythonExecs().run(PythonExecArgs(code=code))
    assert "NETWORK REACHABLE" not in result.content
    assert result.ok is False


@needs_docker
def test_exec_infinite_loop_is_killed(monkeypatch):
    monkeypatch.setattr(exec_mod, "ENABLED", True)
    monkeypatch.setattr(exec_mod, "TIMEOUT_SECONDS", 3)
    result = PythonExecs().run(PythonExecArgs(code="while True: pass"))
    assert result.ok is False
    assert result.meta["timed_out"] is True


@needs_docker
def test_exec_cannot_modify_its_own_script(monkeypatch):
    """Mounted read-only."""
    monkeypatch.setattr(exec_mod, "ENABLED", True)
    code = "open('/work/main.py', 'w').write('hacked')"
    result = PythonExecs().run(PythonExecArgs(code=code))
    assert result.ok is False
    assert "Read-only" in result.content or "Permission" in result.content


# --------------------------------------------------------------------------
# Live (opt-in): real internet
# --------------------------------------------------------------------------


@needs_live
def test_live_fetch_example_com():
    result = FetchUrl().run(FetchUrlArgs(url="https://example.com"))
    assert result.ok is True
    assert "Example Domain" in result.content


@needs_live
def test_live_two_hop_chain():
    """Search, then fetch a URL from the results. The whole Week-1 premise."""
    if search_mod.USE_STUB:
        pytest.skip("no TAVILY_API_KEY set")
    search = WebSearch().run(WebSearchArgs(query="New York money transmitter license", max_results=3))
    assert search.ok is True

    url = next(
        line.split("URL:", 1)[1].strip()
        for line in search.content.splitlines()
        if "URL:" in line
    )
    page = FetchUrl().run(FetchUrlArgs(url=url))
    # A real site may block us or be JS-rendered; either way it must not raise.
    assert isinstance(page, ToolResult)