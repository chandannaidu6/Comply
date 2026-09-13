from __future__ import annotations
from typing import Any,Protocol,runtime_checkable
from pydantic import BaseModel,Field,ValidationError

class ToolResult(BaseModel):
    ok:bool
    content:str = Field(description="Text that goes into the model's context. On failure," "an error message the model can act on.")
    meta:dict[str,Any] = Field(default_factory=dict,description = "Diagnostics for the journal, not for the model: status "
        "codes, timings, truncation flags, resolved URLs.")


@runtime_checkable
class Tool(Protocol):
    name:str
    description:str
    Args:type[BaseModel]
    def run(self,args:BaseModel)->ToolResult:
        ...

def to_schema(tool:Tool)->dict[str,Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.Args.model_json_schema(),
        },
    }

def safe_call(tool:Tool,raw_args:dict[str,Any])->ToolResult:
    try:
        args = tool.Args(**raw_args)
    except ValidationError as e:
        return ToolResult(
            ok=False,
            content=f"Invalid arguments for {tool.name}: {e.errors()}",
            meta={"stage": "validation", "tool": tool.name},
        )
    except TypeError as e:  
        return ToolResult(
            ok=False,
            content=f"Malformed arguments for {tool.name}: {e}",
            meta={"stage": "validation", "tool": tool.name},
        )
    try:
        return tool.run(args)
    except Exception as e: 
        return ToolResult(
            ok=False,
            content=f"{tool.name} failed: {type(e).__name__}: {e}",
            meta={"stage": "execution", "tool": tool.name},
        )




