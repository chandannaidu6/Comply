from __future__ import annotations

import time

from packages.orchestrator.budgets import Budgets


def test_fresh_budget_is_not_exhausted():
    b = Budgets()
    stop, reason = b.exhausted()
    assert stop is False
    assert reason is None


def test_charge_accumulates_usage():
    b = Budgets()
    b.charge(steps=1, tokens=100, cost_usd=0.01)
    b.charge(steps=1, tokens=250, cost_usd=0.02)

    assert b.used_steps == 2
    assert b.used_tokens == 350
    assert b.used_cost_usd == 0.03


def test_stops_on_steps():
    b = Budgets(max_steps=3)
    for _ in range(3):
        b.charge(steps=1)

    stop, reason = b.exhausted()
    assert stop is True
    assert reason == "steps"


def test_stops_on_tokens():
    b = Budgets(max_tokens=1_000)
    b.charge(tokens=1_000)

    stop, reason = b.exhausted()
    assert stop is True
    assert reason == "tokens"


def test_stops_on_cost():
    b = Budgets(max_cost_usd=0.50)
    b.charge(cost_usd=0.60)

    stop, reason = b.exhausted()
    assert stop is True
    assert reason == "cost"


def test_stops_on_time():
    b = Budgets(max_seconds=0)  # already expired
    time.sleep(0.01)

    stop, reason = b.exhausted()
    assert stop is True
    assert reason == "time"


def test_any_single_limit_stops_the_run():
    """The critical behaviour: ANY one limit stops it, not all of them."""
    b = Budgets(max_steps=2, max_tokens=1_000_000, max_cost_usd=100.0)
    b.charge(steps=2, tokens=5, cost_usd=0.001)  # way under tokens and cost

    stop, reason = b.exhausted()
    assert stop is True
    assert reason == "steps"


def test_reason_reports_the_first_limit_hit():
    b = Budgets(max_steps=1, max_tokens=10)
    b.charge(steps=5, tokens=500)  # both blown

    stop, reason = b.exhausted()
    assert stop is True
    assert reason == "steps"  # checked first, by design


def test_snapshot_reports_usage_and_limits():
    b = Budgets(max_steps=10)
    b.charge(steps=3, tokens=42, cost_usd=0.05)

    snap = b.snapshot()
    assert snap["steps"] == [3, 10]
    assert snap["tokens"][0] == 42
    assert snap["cost_usd"][0] == 0.05