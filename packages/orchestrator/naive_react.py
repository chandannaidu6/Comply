from __future__ import annotations
from typing import Any
from .budgets import Budgets
from .models import call_model,ModelUnavailable
from .tools import REGISTRY, all_schemas, safe_call
import json
import sys
SYSTEM_PROMPT = """You are a compliance research agent for US financial regulation.
 
How to work:
- Use web_search to find candidate sources, then fetch_url to read them.
- Never answer from a search snippet alone. Read the actual page.
- Prefer official sources: state regulators, NMLS, CSBS, FinCEN.
- Use python_exec only for calculations or date arithmetic.
 
How to answer:
- Cite the URL each fact came from.
- If you cannot find a source for something, say so plainly. Do not guess.
- Be concise."""

def _log(step:int,event:str,**data:Any)->None:
    details = " ".join(f"{k}:{v}" for k,v in data.items())
    print(f"[step:{step}] {event} {details}".rstrip())


def _assistant_message(response) -> dict[str,Any]:
    message:dict[str,Any] = {
        "role":"assistant",
        "content":response.text or None
    }  
    if response.tool_calls:
        message["tool_calls"] = [
            {
                "id":call.id,
                "type":"function",
                "function":{
                    "name":call.name,
                    "arguments":json.dumps(call.args)
                }

            }
            for call in response.tool_calls
        ]
    return message


def run_naive(task,budgets:Budgets | None = None)->str:
    budgets = Budgets()
    schemas = all_schemas()
    context: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    step = 0
    while True:
        exhausted,reason = budgets.exhausted()
        if exhausted:
            _log(step,"stop",reason="reason",budget = budgets.snapshot())
            return f"Stopped: budget exhausted ({reason}) before an answer was reached."
        step+=1

        try:
            response = call_model(context,tools=schemas)
        except ModelUnavailable as e:
            _log(step,"model unavailable",error=e)
            return f"Stopped: the model could not be reached ({e})."


        budgets.charge(steps=1,tokens=response.tokens,cost_usd=response.cost_usd)
        context.append(_assistant_message(response=response))

        if response.stop:
            if response.finish_reason == "length":
                _log(step, "truncated", budget=budgets.snapshot())
                return (
                    "Stopped: the model's answer was cut off at the output "
                    "token limit. Partial answer:\n\n" + response.text
                )
            _log(step, "final", budget=budgets.snapshot())
            return response.text

        for call in response.tool_calls:
            tool = REGISTRY.get(call.name)

            if tool is None:
                content = (
                    f"No tool named '{call.name}'. "
                    f"Available tools: {', '.join(REGISTRY)}."
                )
                _log(step, "unknown_tool", name=call.name)

            else:
                _log(step,"tool_call",name=call.name,args=call.args)
                result = safe_call(tool,call.args)
                content = result.content
                _log(step, "tool_result", name=call.name, ok=result.ok, meta=result.meta)
            context.append(
                {"role": "tool", "tool_call_id": call.id, "content": content}
            )

if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or (
        "What surety bond does New York require for a money transmitter? "
        "Cite your source."
    )
    print(f"\nTASK: {question}\n")
    answer = run_naive(question)
    print(f"\nANSWER:\n{answer}\n")



        




        


