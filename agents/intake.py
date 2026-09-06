from __future__ import annotations
from orchestration.state import EngagementState
from agents._helpers import agent_step, set_summary
from agents.context import AgentContext

NAME = "Intake & Engagement Agent"


@agent_step(NAME)
def run(state: EngagementState, ctx: AgentContext) -> EngagementState:
    missing = []
    if not state.company_name.strip():
        missing.append("company name")
    if not state.business_problem.strip():
        missing.append("business problem")

    if missing:
        set_summary(
            state, NAME,
            f"Missing required inputs: {', '.join(missing)}. Cannot proceed without them.",
        )
        state.agent_runs[NAME].warnings.append(f"Missing: {', '.join(missing)}")
        return state

    state.company_profile.name = state.company_name.strip()
    set_summary(
        state, NAME,
        f"Validated inputs for '{state.company_name}'. Business problem parsed "
        f"({len(state.business_problem.split())} words). "
        f"{len(state.uploaded_file_paths)} document(s) attached. Engagement "
        f"{state.engagement_id} created; research plan: company profile -> market "
        "-> documents -> diagnosis -> opportunities -> value case -> roadmap -> proposal.",
    )
    return state
