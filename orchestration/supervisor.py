"""
Bounded Supervisor / Orchestrator decision layer.

The supervisor sits between certain nodes in the LangGraph pipeline and
decides, from the state produced so far, whether to advance to the next
node or send the pipeline back for one more bounded pass. Every decision
is deterministic (a plain function of EngagementState) so the zero-key
demo path stays fully functional, and every decision is logged with
{decision, reason, next_node, iteration_count} to `state.supervisor_log`.

Design note: LangGraph conditional-edge router functions must be pure —
mutations performed inside a router are NOT guaranteed to be part of the
persisted graph state (they can be silently dropped, which previously
caused an infinite proposal<->governance loop here). So the pattern is
split in two: `decide_*` computes {decision, reason, next_node} as a pure
function and is called from inside the *node* wrapper (graph.py), which
mutates `state.node_iterations` / `state.supervisor_log` and stashes the
routing choice in `state.pending_route` — a real state field. The actual
`add_conditional_edges` callback (`route_*` below) then just reads
`state.pending_route`, without mutating anything.

No decision point can loop more than MAX_ITERATIONS times per node —
once exhausted, the supervisor always forces forward progress. This is
the one invariant that must never regress: an infinite loop here would
hang every engagement run.
"""
from __future__ import annotations
from orchestration.state import EngagementState, SupervisorDecision

MAX_ITERATIONS: dict[str, int] = {
    "company_research": 2,
    "sales_diagnostic": 2,
    "opportunity": 2,
    "proposal": 2,
}


def _exhausted(state: EngagementState, node: str) -> bool:
    return state.node_iterations.get(node, 0) >= MAX_ITERATIONS.get(node, 1)


def _apply(state: EngagementState, node: str, decision: str, reason: str, next_node: str) -> EngagementState:
    """Mutate state with the decision. Must only ever be called from inside a
    graph *node* (not a router), so the mutation is part of the value
    LangGraph persists for the next step. `node_iterations[node]` counts
    actual retries taken (bounded by MAX_ITERATIONS), not decision-point
    visits — an "advance"/exhausted decision does not itself count as a
    retry, so the counter can never exceed MAX_ITERATIONS."""
    if decision in ("retry", "regenerate"):
        state.node_iterations[node] = state.node_iterations.get(node, 0) + 1
    state.supervisor_log.append(SupervisorDecision(
        node=node, decision=decision, reason=reason, next_node=next_node,
        iteration_count=state.node_iterations.get(node, 0),
    ))
    state.pending_route = next_node
    return state


def decide_after_company_research(state: EngagementState) -> EngagementState:
    """Is research evidence sufficient, or does it need another pass?"""
    node = "company_research"
    evidence_count = len(state.company_profile.evidence)
    if _exhausted(state, node):
        return _apply(state, node, "advance", "Max research iterations reached; proceeding with available evidence.", "market_intelligence")
    if state.company_profile.research_quality == "LOW" and evidence_count < 3 and state.web_research_available:
        return _apply(state, node, "retry", f"Research quality LOW with only {evidence_count} evidence item(s); running another research pass.", node)
    return _apply(state, node, "advance", "Research evidence sufficient for this pass.", "market_intelligence")


def decide_after_document_intelligence(state: EngagementState) -> EngagementState:
    """Was an RFP uploaded (needs requirement-matrix analysis), and is RAG retrieval populated?
    This is a bookkeeping decision — document_intelligence.py already performs both when
    files are present; the supervisor just records whether they were needed and applied."""
    node = "document_intelligence"
    has_files = bool(state.uploaded_file_paths)
    rag_needed = state.documents.rag_chunks_indexed > 0
    reason = (
        f"RFP analysis {'required and applied' if has_files else 'not required (no files uploaded)'}; "
        f"RAG retrieval {'populated (' + str(state.documents.rag_chunks_indexed) + ' chunks)' if rag_needed else 'not applicable'}."
    )
    return _apply(state, node, "advance", reason, "sales_diagnostic")


def decide_after_sales_diagnostic(state: EngagementState) -> EngagementState:
    """Does the diagnosis need more evidence before opportunities are scored?"""
    node = "sales_diagnostic"
    if _exhausted(state, node):
        return _apply(state, node, "advance", "Max diagnosis iterations reached; proceeding with current hypothesis tree.", "opportunity")
    if not state.diagnosis.executive_diagnosis or len(state.diagnosis.hypothesis_tree) == 0:
        return _apply(state, node, "retry", "Diagnosis is empty or has no hypotheses; running another diagnostic pass.", node)
    return _apply(state, node, "advance", "Diagnosis has sufficient content to proceed.", "opportunity")


def decide_after_opportunity(state: EngagementState) -> EngagementState:
    """Does opportunity discovery need another pass to find enough candidates?"""
    node = "opportunity"
    if _exhausted(state, node):
        return _apply(state, node, "advance", "Max opportunity-discovery iterations reached; proceeding with current portfolio.", "value_roi")
    if len(state.opportunities) == 0:
        return _apply(state, node, "retry", "No opportunities identified yet; running another discovery pass.", node)
    return _apply(state, node, "advance", f"{len(state.opportunities)} opportunity(ies) identified; proceeding.", "value_roi")


def decide_after_value_roi(state: EngagementState) -> EngagementState:
    """Are ROI inputs sufficient to produce a meaningful business case?"""
    node = "value_roi"
    if state.roi_inputs.annual_revenue_cr <= 0 or state.roi_inputs.seller_count <= 0:
        return _apply(state, node, "flag_review", "ROI inputs (revenue/seller count) are zero or missing; governance should flag for review.", "roadmap")
    return _apply(state, node, "advance", "ROI inputs sufficient.", "roadmap")


def decide_after_governance(state: EngagementState) -> EngagementState:
    """Does governance BLOCK/REVIEW require the proposal to be regenerated before END?"""
    node = "proposal"  # tracks retries of the proposal<->governance loop
    if state.governance.status == "BLOCK" and not _exhausted(state, node) and state.proposal_markdown:
        reason = f"Governance status is BLOCK ({state.governance.reasons[0] if state.governance.reasons else 'see reasons'}); regenerating proposal once before finishing."
        return _apply(state, node, "regenerate", reason, "proposal")
    if state.governance.status == "BLOCK":
        return _apply(state, node, "advance", "Regeneration attempts exhausted; ending with BLOCK status for human review.", "END")
    return _apply(state, node, "advance", f"Governance status is {state.governance.status}; no regeneration required.", "END")


# Pure router callbacks for add_conditional_edges — read-only, never mutate state.
def route_after_company_research(state: EngagementState) -> str:
    return state.pending_route


def route_after_document_intelligence(state: EngagementState) -> str:
    return state.pending_route


def route_after_sales_diagnostic(state: EngagementState) -> str:
    return state.pending_route


def route_after_opportunity(state: EngagementState) -> str:
    return state.pending_route


def route_after_value_roi(state: EngagementState) -> str:
    return state.pending_route


def route_after_governance(state: EngagementState) -> str:
    return state.pending_route
