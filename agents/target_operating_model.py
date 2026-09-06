from __future__ import annotations
from orchestration.state import EngagementState, TOMBlock
from agents._helpers import agent_step, set_summary
from agents.context import AgentContext

NAME = "Target Operating Model Agent"


@agent_step(NAME)
def run(state: EngagementState, ctx: AgentContext) -> EngagementState:
    opp_names = ", ".join(o.name for o in state.opportunities[:3]) or "prioritized AI opportunities"

    blocks = [
        TOMBlock(
            dimension="People",
            current_state="Sellers/account teams perform research and proposal work manually.",
            target_state=f"Sellers supervised by {opp_names}, with a designated AI champion per team.",
            operating_cadence="Weekly enablement + adoption review",
        ),
        TOMBlock(
            dimension="Process",
            current_state="Ad hoc account research and proposal drafting.",
            target_state="Standardized AI-assisted workflow with human review checkpoint before client-facing output.",
            operating_cadence="Human-in-the-loop review on every AI-generated client artifact",
        ),
        TOMBlock(
            dimension="Technology",
            current_state="Fragmented tools; manual data pulls.",
            target_state="RAG-backed agent layer integrated with CRM and document repository.",
            operating_cadence="Monthly model/provider review",
        ),
        TOMBlock(
            dimension="Data",
            current_state=f"{'Uploaded documents available' if state.documents.filenames else 'No structured data provided yet'}.",
            target_state="Unified customer/account data feeding retrieval and scoring.",
            operating_cadence="Quarterly data quality audit",
        ),
        TOMBlock(
            dimension="Governance",
            current_state="No formal AI governance gate.",
            target_state="Mandatory governance PASS + human approval before any client-facing AI output ships.",
            operating_cadence="Governance review on every engagement; quarterly policy refresh",
        ),
    ]
    state.target_operating_model = blocks
    set_summary(state, NAME, f"Defined current vs. target state across People/Process/Technology/Data/Governance, anchored to the top opportunities ({opp_names}).")
    return state
