from __future__ import annotations
from langgraph.graph import StateGraph, END
from orchestration.state import EngagementState
from orchestration.approval import sync_approval_state
from orchestration import supervisor
from agents.context import AgentContext
from agents import (
    intake, company_research, market_intelligence, document_intelligence,
    sales_diagnostic, opportunity, value_roi, roadmap, target_operating_model,
    proposal, governance,
)

# Main per-engagement pipeline (lead discovery/qualification and client
# communication are separate workspaces invoked directly, not part of this
# chain — see agents/lead_discovery.py, agents/lead_qualification.py,
# agents/client_communication.py).
#
# This is no longer a pure straight line: a bounded Supervisor
# (orchestration/supervisor.py) sits after company_research, document_intelligence,
# sales_diagnostic, opportunity, value_roi and governance and decides whether to
# advance or take one more bounded pass. NODE_ORDER below still defines the
# canonical forward sequence used for display (Agent Control Center) and for
# targeted `rerun_from` — the conditional edges never skip a node, they only ever
# add a bounded retry loop back onto the immediately-preceding node.
NODE_ORDER = [
    ("intake", intake),
    ("company_research", company_research),
    ("market_intelligence", market_intelligence),
    ("document_intelligence", document_intelligence),
    ("sales_diagnostic", sales_diagnostic),
    ("opportunity", opportunity),
    ("value_roi", value_roi),
    ("roadmap", roadmap),
    ("target_operating_model", target_operating_model),
    ("proposal", proposal),
    ("governance", governance),
]

NODE_IDS = [n for n, _ in NODE_ORDER]


def downstream_of(node_id: str) -> list[str]:
    if node_id not in NODE_IDS:
        return []
    idx = NODE_IDS.index(node_id)
    return NODE_IDS[idx:]  # includes the node itself


def build_graph(ctx: AgentContext):
    g = StateGraph(EngagementState)

    def make_node(module):
        def node_fn(state: EngagementState) -> EngagementState:
            return module.run(state, ctx)
        return node_fn

    for node_id, module in NODE_ORDER:
        g.add_node(node_id, make_node(module))

    # A decision node runs the pure `decide_after_*` supervisor function as
    # part of the graph's own node-execution step (so its mutation of
    # node_iterations/supervisor_log/pending_route is actually persisted —
    # see orchestration/supervisor.py docstring for why this can't live in
    # the add_conditional_edges callback itself).
    def decision_node(decide_fn):
        def fn(state: EngagementState) -> EngagementState:
            return decide_fn(state)
        return fn

    g.add_node("decide_company_research", decision_node(supervisor.decide_after_company_research))
    g.add_node("decide_document_intelligence", decision_node(supervisor.decide_after_document_intelligence))
    g.add_node("decide_sales_diagnostic", decision_node(supervisor.decide_after_sales_diagnostic))
    g.add_node("decide_opportunity", decision_node(supervisor.decide_after_opportunity))
    g.add_node("decide_value_roi", decision_node(supervisor.decide_after_value_roi))
    g.add_node("decide_governance", decision_node(supervisor.decide_after_governance))

    g.set_entry_point("intake")
    g.add_edge("intake", "company_research")
    g.add_edge("company_research", "decide_company_research")
    g.add_conditional_edges(
        "decide_company_research", supervisor.route_after_company_research,
        {"company_research": "company_research", "market_intelligence": "market_intelligence"},
    )
    g.add_edge("market_intelligence", "document_intelligence")
    g.add_edge("document_intelligence", "decide_document_intelligence")
    g.add_conditional_edges(
        "decide_document_intelligence", supervisor.route_after_document_intelligence,
        {"sales_diagnostic": "sales_diagnostic"},
    )
    g.add_edge("sales_diagnostic", "decide_sales_diagnostic")
    g.add_conditional_edges(
        "decide_sales_diagnostic", supervisor.route_after_sales_diagnostic,
        {"sales_diagnostic": "sales_diagnostic", "opportunity": "opportunity"},
    )
    g.add_edge("opportunity", "decide_opportunity")
    g.add_conditional_edges(
        "decide_opportunity", supervisor.route_after_opportunity,
        {"opportunity": "opportunity", "value_roi": "value_roi"},
    )
    g.add_edge("value_roi", "decide_value_roi")
    g.add_conditional_edges(
        "decide_value_roi", supervisor.route_after_value_roi,
        {"roadmap": "roadmap"},
    )
    g.add_edge("roadmap", "target_operating_model")
    g.add_edge("target_operating_model", "proposal")
    g.add_edge("proposal", "governance")
    g.add_edge("governance", "decide_governance")
    g.add_conditional_edges(
        "decide_governance", supervisor.route_after_governance,
        {"proposal": "proposal", "END": END},
    )
    return g.compile()


def run_engagement(state: EngagementState, ctx: AgentContext) -> EngagementState:
    app = build_graph(ctx)
    # LangGraph's default recursion_limit (25) is comfortably above our worst case
    # (11 nodes + bounded retries capped at 2 each), but pass it explicitly so a
    # future node addition can't silently hit the ceiling and raise instead of
    # ending cleanly.
    result = app.invoke(state, config={"recursion_limit": 60})
    if not isinstance(result, EngagementState):
        result = EngagementState(**result)
    return sync_approval_state(result)


def rerun_from(state: EngagementState, node_id: str, ctx: AgentContext) -> EngagementState:
    """Targeted re-run: re-executes `node_id` and everything downstream of it
    in NODE_ORDER, leaving upstream agent outputs untouched. This bypasses the
    supervisor's bounded-retry graph entirely (it always runs each node exactly
    once, in order) — it's a deliberate manual override distinct from a full
    `run_engagement` pass."""
    if node_id not in NODE_IDS:
        raise ValueError(f"Unknown node '{node_id}'")

    module_by_id = dict(NODE_ORDER)
    for nid in downstream_of(node_id):
        state = module_by_id[nid].run(state, ctx)
    return sync_approval_state(state)
