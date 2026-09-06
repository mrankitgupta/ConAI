from __future__ import annotations
from orchestration.state import EngagementState, Opportunity
from agents._helpers import agent_step, set_summary
from agents.context import AgentContext

NAME = "AI Opportunity Discovery Agent"

# Library of candidate agent archetypes. Which ones get proposed, and their
# scores, are driven by the hypothesis tree + doc requirements actually
# present in THIS engagement's state — not a fixed four-item list.
CATALOG = {
    "Sales Copilot": dict(family="Productivity", problem_kw=["productiv", "research", "prepar", "coordinat"]),
    "Account Intelligence Agent": dict(family="Productivity", problem_kw=["research", "account", "data fragmentation"]),
    "Lead Qualification Agent": dict(family="Conversion", problem_kw=["qualif", "conversion", "lead"]),
    "Deal Strategy / Next-Best-Action Agent": dict(family="Conversion", problem_kw=["conversion", "win rate", "next-best"]),
    "Proposal Generation Agent": dict(family="Cycle Time", problem_kw=["proposal", "productiv", "sales cycle"]),
    "RFP Response Agent": dict(family="Cycle Time", problem_kw=["rfp", "proposal", "requirement"]),
    "Pricing Intelligence Agent": dict(family="Economics", problem_kw=["pricing", "discount", "margin"]),
    "Cross-sell / Whitespace Agent": dict(family="Conversion", problem_kw=["cross-sell", "account", "penetration"]),
    "Revenue Forecasting Agent": dict(family="Visibility", problem_kw=["forecast", "pipeline", "visibility"]),
}


@agent_step(NAME)
def run(state: EngagementState, ctx: AgentContext) -> EngagementState:
    problem_text = (state.business_problem + " " + state.diagnosis.executive_diagnosis).lower()
    hyp_labels = " ".join(h.label.lower() for h in state.diagnosis.hypothesis_tree)
    signal_text = problem_text + " " + hyp_labels
    has_docs = state.documents.rag_chunks_indexed > 0
    has_reqs = len(state.documents.requirement_matrix) > 0

    opps: list[Opportunity] = []
    for i, (name, meta) in enumerate(CATALOG.items(), start=1):
        hits = sum(kw in signal_text for kw in meta["problem_kw"])
        if hits == 0 and name not in ("Sales Copilot",):
            continue  # only surface opportunities with an actual signal in this engagement

        business_value = min(5, 2 + hits)
        feasibility = 4 if not has_reqs else (3 if len(state.documents.requirement_matrix) > 15 else 4)
        data_readiness = 4 if has_docs else 2
        strategic_fit = min(5, 3 + hits)

        opps.append(
            Opportunity(
                opp_id=f"OPP-{i:02d}",
                name=name,
                family=meta["family"],
                problem=f"Addresses signal(s): {', '.join(k for k in meta['problem_kw'] if k in signal_text) or 'general productivity gap'}",
                solution=_solution_text(name),
                business_value=business_value,
                feasibility=feasibility,
                data_readiness=data_readiness,
                strategic_fit=strategic_fit,
                time_to_value_months=3 if feasibility >= 4 else 6,
                risk="Low" if feasibility >= 4 else "Medium",
                required_data=_required_data(name),
                kpis=_kpis(name),
                dependencies=["CRM/pipeline data access", "Stakeholder sign-off"] + (["RFP/requirement corpus"] if "RFP" in name else []),
            )
        )

    opps.sort(key=lambda o: o.priority_score, reverse=True)
    state.opportunities = opps[:8]

    set_summary(
        state, NAME,
        f"Scored {len(CATALOG)} candidate AI-agent archetypes against this engagement's hypothesis tree and "
        f"document signals; {len(state.opportunities)} passed the relevance threshold and were prioritized "
        "on Business Value x Feasibility x Data Readiness x Strategic Fit.",
    )
    return state


def _solution_text(name: str) -> str:
    return {
        "Sales Copilot": "Conversational assistant embedded in the seller workflow for account research, meeting prep, and follow-up drafting.",
        "Account Intelligence Agent": "Autonomously aggregates public + internal signals into a living account brief before every client interaction.",
        "Lead Qualification Agent": "Scores and routes inbound/outbound leads using firmographic + engagement signals, reducing manual triage.",
        "Deal Strategy / Next-Best-Action Agent": "Recommends the next action per open deal based on historical win patterns.",
        "Proposal Generation Agent": "Drafts first-cut proposals from templates + RAG over past deals and product knowledge, for human edit.",
        "RFP Response Agent": "Extracts requirements from RFPs, maps them to capabilities, and drafts compliant responses with traceable sources.",
        "Pricing Intelligence Agent": "Surfaces comparable deal pricing and margin guardrails at quote time.",
        "Cross-sell / Whitespace Agent": "Identifies under-penetrated product lines within existing accounts.",
        "Revenue Forecasting Agent": "Produces a bottoms-up forecast with confidence bands from pipeline stage data.",
    }.get(name, "AI agent addressing the identified sales challenge.")


def _required_data(name: str) -> list[str]:
    base = ["CRM export (opportunities, activities)"]
    if "RFP" in name or "Proposal" in name:
        base.append("Historical proposals / RFP corpus")
    if "Pricing" in name:
        base.append("Historical deal pricing data")
    return base


def _kpis(name: str) -> list[str]:
    return {
        "Sales Copilot": ["Hours saved per seller/week", "Meeting prep time"],
        "Proposal Generation Agent": ["Proposal turnaround time", "Proposals per seller/month"],
        "RFP Response Agent": ["RFP response cycle time", "Win rate on responded RFPs"],
        "Lead Qualification Agent": ["Lead-to-opportunity conversion rate"],
        "Deal Strategy / Next-Best-Action Agent": ["Win rate", "Stage conversion rate"],
        "Pricing Intelligence Agent": ["Average discount %", "Gross margin per deal"],
        "Cross-sell / Whitespace Agent": ["Cross-sell revenue %", "Products per account"],
        "Revenue Forecasting Agent": ["Forecast accuracy (MAPE)"],
        "Account Intelligence Agent": ["Research time per account"],
    }.get(name, ["Value delivered vs. baseline"])
