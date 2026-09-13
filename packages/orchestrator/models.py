from __future__ import annotations
import json
import os
from typing import Any
 
import litellm
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

load_dotenv()

PLANNER_MODEL = os.getenv("PLANNER_MODEL", "gpt-4o")
WORKER_MODEL = os.getenv("WORKER_MODEL", "gpt-4o-mini")
 
TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0.0"))
MAX_TOKENS = int(os.getenv("MODEL_MAX_TOKENS", "4096"))

class ToolCall(BaseModel):
    id: str = Field(
        description="Provider-assigned call id. MUST be echoed back with the "
        "tool result or the next turn breaks."
    )
    name: str
    args: dict[str, Any]

class ModelResponse(BaseModel):
    text:str = ""
    tool_calls:list[ToolCall] = Field(default_factory=list)
    stop:bool = True
    tokens:int = 0
    cost_usd:float = 0.0
    finish_reason:str = ""
    model:str = ""


class ModelUnavailable(Exception):
    """Raised when the provider is unreachable after retries.
 
    The one place raising is correct: if the model can't be reached, the run
    genuinely cannot continue, and returning an empty response would leave
    the loop spinning.
    """
@retry(
        retry=retry_if_exception_type(
        (litellm.RateLimitError, litellm.APIConnectionError, litellm.Timeout)
    ),
    stop = stop_after_attempt(3),
    wait = wait_exponential(multiplier=1, min=2, max=20),
    reraise=True,
)
def _completion(**kwargs):
    return litellm.completion(**kwargs)

def call_model(context:list[dict[str,Any]], tools:list[dict[str,Any]] | None=None,*,model:str | None = None) -> ModelResponse:
    model = model or PLANNER_MODEL

    kwargs: dict[str,Any] = {
        "model":model,
        "messages":context,
        "temperature":TEMPERATURE,
        "max_tokens":MAX_TOKENS
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    try:
        raw = _completion(**kwargs)
    except Exception as e:
        raise ModelUnavailable(f"{type(e).__name__}: {e}") from e

    choice = raw.choices[0]
    message = choice.message

    text = message.content or ""

    tool_calls: list[ToolCall] = []
    for tc in getattr(message,"tool_calls",None) or []:
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {"__malformed__": tc.function.arguments}
        tool_calls.append(
            ToolCall(id=tc.id, name=tc.function.name, args=args)
        )

    stop = not tool_calls
    finish_reason = getattr(choice,"finish_reason","") or ""

    usage = getattr(raw, "usage", None)
    tokens = int(getattr(usage, "total_tokens", 0) or 0)
 
    try:
        cost_usd = float(litellm.completion_cost(completion_response=raw) or 0.0)
    except Exception:  
        cost_usd = 0.0
 
    return ModelResponse(
        text=text,
        tool_calls=tool_calls,
        stop=stop,
        tokens=tokens,
        cost_usd=cost_usd,
        finish_reason=finish_reason,
        model=model,
    )








