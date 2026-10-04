"""Live Token Factory test. Skipped by default; run with `pytest -m live` (spends ~1 cent)."""

import pytest

from reliability_agent.config import api_key, load_config
from reliability_agent.nemotron import BudgetGuard
from reliability_agent.nemotron.planner import make_planner

pytestmark = pytest.mark.live


@pytest.mark.skipif(api_key() is None, reason="NEBIUS_API_KEY not set")
def test_live_nemotron_plan_is_valid():
    from reliability_agent.contracts.models import FaultType
    from scripts.spike_nemotron import make_incident

    cfg = load_config()
    planner = make_planner(cfg, api_key(), BudgetGuard.from_config(cfg))
    out = planner.plan(make_incident(FaultType.BLACKOUT, 0))
    assert out.source == "nemotron", out.error
    assert out.usage.input_tokens > 0 and out.usage.estimated_cost_usd > 0
