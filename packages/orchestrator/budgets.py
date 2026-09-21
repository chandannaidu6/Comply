from __future__ import annotations
"This file essentially sets up the budget for the agent, so if and when an agent or a group of agents cross the final budget the"
"The Operation will be exited with exhaused message. This is not an error this is just a message"
"The Budget class contains"
"steps,time,max_tokens,cost,number of workers"
from typing import Any
from dataclasses import dataclass, field
import time


@dataclass
class Budgets:
    max_steps: int = 25
    max_seconds: int = 600
    max_tokens: int = 120_000
    max_cost_usd: float = 1.50
    max_parallel_workers: int = 8

    used_steps: int = 0
    used_tokens: int = 0
    used_cost_usd: float = 0.0
    started_at: float = field(default_factory=time.monotonic)

    def charge(self, *, steps: int = 0, tokens: int = 0, cost_usd: float = 0.0) -> None:
        self.used_steps += steps
        self.used_tokens += tokens
        self.used_cost_usd += cost_usd

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at

    def exhausted(self) -> tuple[bool, str | None]:
        if self.used_steps >= self.max_steps:
            return True, "steps"
        if self.elapsed_seconds() >= self.max_seconds:
            return True, "time"
        if self.used_tokens >= self.max_tokens:
            return True, "tokens"
        if self.used_cost_usd >= self.max_cost_usd:
            return True, "cost"
        return False, None

    def snapshot(self) -> dict[str, Any]:
        return {
            "steps": [self.used_steps, self.max_steps],
            "seconds": [round(self.elapsed_seconds(), 2), self.max_seconds],
            "tokens": [self.used_tokens, self.max_tokens],
            "cost_usd": [round(self.used_cost_usd, 4), self.max_cost_usd],
            "max_parallel_workers": self.max_parallel_workers,
        }