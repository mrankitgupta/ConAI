from __future__ import annotations
from orchestration.state import EngagementState
from agents._helpers import agent_step, set_summary
from agents.context import AgentContext

NAME = "Proposal Agent"


@agent_step(NAME)
def run(state: EngagementState, ctx: AgentContext) -> EngagementState:
    c = state.company_name
    md = []
    md.append(f"# Agentic AI Sales Transformation Proposal\n**Prepared for:** {c}\n**Engagement ID:** {state.engagement_id}\n")
    md.append("## 1. Executive Summary")
    md.append(state.diagnosis.executive_diagnosis or "_Not yet generated._")
    md.append("\n## 2. Client Context")
    md.append(f"**Business problem (client-provided):** {state.business_problem}")
    md.append("\n## 3. Company Intelligence")
    md.append(f"{state.company_profile.description}\n\n_Research confidence: {state.company_profile.research_quality}_")
    md.append("\n## 4. Market & Industry Context")
    md.append(f"{state.market.market_definition}. {state.market.growth_note}")
    if state.market.key_trends:
        md.append("\nKey trends (sourced):")
        for t in state.market.key_trends:
            md.append(f"- {t}")
    md.append("\n## 5. Hypothesis Tree")
    for h in state.diagnosis.hypothesis_tree:
        indent = "  " if h.parent else ""
        md.append(f"{indent}- **{h.label}** (impact: {h.impact}, confidence: {h.confidence}) — {h.evidence}")
    md.append("\n## 6. AI Opportunity Portfolio (Prioritized)")
    for o in state.opportunities:
        md.append(f"### {o.name} — Priority Score {o.priority_score}")
        md.append(f"- Problem: {o.problem}\n- Solution: {o.solution}\n- KPIs: {', '.join(o.kpis)}\n- Time to value: {o.time_to_value_months} months, Risk: {o.risk}")
    md.append("\n## 7. Business Case")
    r = state.roi_outputs
    md.append(f"**Scenario:** {state.roi_inputs.scenario} _(ASSUMPTION-based; see inputs in the Value tab)_\n")
    md.append(f"- Incremental revenue value: ₹{r.incremental_revenue_cr} Cr/year\n- Productivity value: ₹{r.productivity_value_cr} Cr/year\n- Cost savings: ₹{r.cost_savings_cr} Cr/year\n- **Total annual value: ₹{r.total_annual_value_cr} Cr**\n- 3-year value: ₹{r.three_year_value_cr} Cr\n- ROI: {r.roi_pct}%\n- Payback: {r.payback_months} months")
    md.append("\n## 8. Transformation Roadmap")
    for p in state.roadmap:
        md.append(f"### {p.phase}\n- Objectives: {', '.join(p.objectives)}\n- Use cases: {', '.join(p.use_cases) or 'TBD'}\n- Technology: {p.technology}\n- Governance: {p.governance}")
    md.append("\n## 9. Governance & Risk")
    md.append(f"Status: **{state.governance.status}**")
    for k, v in state.governance.checks.items():
        md.append(f"- {k}: {v}")
    md.append("\n## 10. Data & Assumption Disclaimer")
    md.append(
        "This proposal blends **client-provided input**, **publicly retrieved web evidence** (labelled with source "
        "URLs where used), and **AI-generated / templated analysis**. Financial figures are illustrative scenario "
        "modeling based on user-entered assumptions, not audited financials. Items marked 'Not found / requires "
        "validation' were not independently verifiable in this session."
    )

    state.proposal_markdown = "\n".join(md)
    set_summary(state, NAME, "Assembled the full proposal from validated engagement state (no section fabricated independently of upstream agent outputs).")
    return state
