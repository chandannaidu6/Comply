from __future__ import annotations
import os
import tempfile
from pathlib import Path
from pydantic import BaseModel,Field
from .base import ToolResult

IMAGE = "python:3.12-slim"
TIMEOUT_SECONDS = 30
MEM_LIMIT = "256m"
CPUS = 1.0
MAX_CHARS = 8000

ENABLED = os.getenv("SANDBOX_ENABLED","0") == "1"

class PythonExecArgs(BaseModel):
    code:str = Field(
        description="Python code to execute. Print anything you want back -- "
        "only stdout and stderr are returned. No network access, no access to "
        "files outside the sandbox. The standard library is available; "
        "third-party packages are not."    
        )

class PythonExecs:
    name = "python_execs"
    description = (
        "Run short Python code in an isolated sandbox and return whatever it "
        "prints. Use for calculations, date arithmetic, parsing, and comparing "
        "structured data. No network access and no third-party packages -- "
        "standard library only. Print your results; return values are ignored."
    )
    Args = PythonExecArgs

    def __init__(self)->None:
        self._client = None

    def _get_client(self):
        if self._client is None:
            import docker
            self._client = docker.from_env()
        return self._client

    def run(self,args:PythonExecArgs)->ToolResult:
        if not ENABLED:
            return ToolResult(
                ok=False,
                content=(
                    "The code sandbox is disabled in this environment. "
                    "Answer without running code, or use another tool."
                ),
                meta={"reason": "sandbox_disabled"},
            )
        try:
            client = self._get_client()
        except Exception as e:
            return ToolResult(
                ok = False,
                content = (
                    "Could not reach the code sandbox (Docker is not "
                    f"available): {e}"
                ),
                meta={"reason":"docker_unavailable"}
            )

        with tempfile.TemporaryDiectory() as workdir:
            script = Path(workdir) / "main.py"
            script.write_text(args.code,encoding="utf-8")
            container = None
            try:
                container = client.containers.run(
                    image = IMAGE,
                    command = ["python","/work/main.py"],
                    volumes = {str(workdir): {"bind": "/work", "mode": "ro"}},
                    working_dir = "/work",
                    network_disabled = True,
                    mem_limit = MEM_LIMIT,
                    nano_cpus = int(CPUS*1e9),
                    pids_limit = 64,
                    detach = True
                )

                try:
                    result = container.wait(timeout=TIMEOUT_SECONDS)
                    exit_code = result.get("StatusCode",-1)
                    timed_out = False
                except Exception:
                    container.kill()
                    exit_code,timed_out = -1,True

                logs = container.logs(stdout=True,stderr=True).decode("utf-8",errors="replace")


            except Exception as e:  
                return ToolResult(
                    ok=False,
                    content=f"Sandbox failed to run the code: {e}",
                    meta={"reason": "container_error"},
                )
            finally:
                if container is not None:
                    try:
                        container.remove(force=True)
                    except Exception:  
                        pass

        truncated = len(logs) > MAX_CHARS
        if truncated:
            logs = logs[:MAX_CHARS]
        
        if timed_out:
            return ToolResult(
                ok=False,
                content=(
                    f"Code timed out after {TIMEOUT_SECONDS}s and was killed. "
                    f"Partial output:\n{logs}"
                ),
                meta={"timed_out": True, "exit_code": exit_code},
            )
        if exit_code != 0:
            return ToolResult(
                ok=False,
                content=f"Code exited with status {exit_code}:\n{logs}",
                meta={"exit_code": exit_code, "truncated": truncated},
            )
 
        return ToolResult(
            ok=True,
            content=logs if logs.strip() else "(code ran successfully, no output)",
            meta={"exit_code": 0, "truncated": truncated, "chars": len(logs)},
        )



        

