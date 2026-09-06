from __future__ import annotations
from orchestration.state import EngagementState, RoadmapPhase
from agents._helpers import agent_step, set_summary
from agents.context import AgentContext

NAME = "Transformation Roadmap Agent"


@agent_step(NAME)
def run(state: EngagementState, ctx: AgentContext) -> EngagementState:
    top_opps = state.opportunities[:4]
    names = [o.name for o in top_opps]

    def slice_(lst, a, b):
        return lst[a:b] if len(lst) > a else []

    phases = [
        RoadmapPhase(
            phase="0-30 Days: Foundation",
            objectives=["Align stakeholders", "Confirm data access", "Stand up governance"],
            use_cases=slice_(names, 0, 1),
            people="Assign engagement sponsor + core sales ops team",
            process="Baseline current KPIs",
            technology="Data access, environment setup",
            data="CRM export, document corpus access",
            governance="Establish AI governance checklist",
            kpis=["Data readiness score", "Stakeholder sign-off"],
        ),
        RoadmapPhase(
            phase="30-90 Days: Pilot",
            objectives=[f"Pilot {names[0]}" if names else "Pilot first prioritized use case"],
            use_cases=slice_(names, 0, 2),
            people="Pilot user group (5-10 sellers)",
            process="Human-in-the-loop review of AI outputs",
            technology="RAG + LLM provider integration, sandbox environment",
            data="Cleaned pilot dataset",
            governance="Weekly governance review of pilot outputs",
            kpis=["Pilot adoption rate", "Time saved per user"],
        ),
        RoadmapPhase(
            phase="3-6 Months: Scale",
            objectives=["Expand to full sales team", "Integrate with CRM"],
            use_cases=slice_(names, 0, 3),
            people="Full sales org enablement + champions network",
            process="Embed AI outputs into standard sales workflow",
            technology="CRM integration, production-grade LLM/RAG",
            data="Live CRM + document feeds",
            governance="Formal approval workflow for client-facing outputs",
            kpis=["Adoption %", "Cycle-time reduction", "Win-rate delta"],
        ),
        RoadmapPhase(
            phase="6-12 Months: Transformation",
            objectives=["Institutionalize target operating model", "Expand opportunity portfolio"],
            use_cases=names,
            people="Center of excellence for Agentic AI in sales",
            process="Continuous governance + retraining cadence",
            technology="Multi-agent orchestration at scale",
            data="Unified customer 360",
            governance="Quarterly AI risk & value review",
            kpis=["Total value realized vs. business case", "ROI"],
        ),
    ]
    state.roadmap = phases

    set_summary(state, NAME, f"Sequenced a 4-phase roadmap (0-30/30-90/3-6mo/6-12mo) around the top {len(top_opps)} prioritized opportunities.")
    return state
