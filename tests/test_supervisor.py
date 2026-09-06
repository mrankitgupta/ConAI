import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_supervisor_never_infinite_loops_on_permanent_block(ctx):
    """Zero revenue + zero sellers keeps governance BLOCK forever (regeneration
    can't fix a missing user input) — the proposal<->governance loop must still
    terminate via the bounded iteration cap, not hang or raise GraphRecursionError."""
    from orchestration.state import EngagementState
    from orchestration.graph import run_engagement
    s = EngagementState(company_name="Zero Revenue Co", business_problem="a generic sales productivity problem")
    result = run_engagement(s, ctx)
    assert result.governance.status == "BLOCK"
    proposal_decisions = [d for d in result.supervisor_log if d.node == "proposal"]
    assert 1 <= len(proposal_decisions) <= 3
    assert max(d.iteration_count for d in proposal_decisions) <= 2


def test_supervisor_log_has_required_fields(ctx, base_state):
    from orchestration.graph import run_engagement
    result = run_engagement(base_state, ctx)
    assert len(result.supervisor_log) > 0
    for d in result.supervisor_log:
        assert d.decision
        assert d.reason
        assert d.next_node
        assert d.iteration_count >= 0


def test_supervisor_research_retry_is_bounded(ctx):
    from orchestration.state import EngagementState
    from orchestration.graph import run_engagement
    s = EngagementState(company_name="Obscure Co With No Public Footprint", business_problem="sales productivity")
    result = run_engagement(s, ctx)
    assert result.node_iterations.get("company_research", 1) <= 2
