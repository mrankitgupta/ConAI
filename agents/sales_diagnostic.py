from __future__ import annotations
from orchestration.state import EngagementState, HypothesisNode
from agents._helpers import agent_step, set_summary
from agents.context import AgentContext

NAME = "Sales Diagnostic & Hypothesis Agent"

DIMENSIONS = {
    "conversion": ["convert", "win rate", "qualif", "close"],
    "productivity": ["time", "research", "prepar", "manual", "coordinat", "productiv"],
    "sales cycle": ["cycle", "slow", "delay", "approval", "long"],
    "pricing": ["pric", "discount", "margin"],
    "data fragmentation": ["fragmented", "siloed", "multiple systems", "data quality"],
}


@agent_step(NAME)
def run(state: EngagementState, ctx: AgentContext) -> EngagementState:
    problem = state.business_problem.lower()
    hits = {dim: sum(kw in problem for kw in kws) for dim, kws in DIMENSIONS.items()}
    active_dims = [d for d, c in hits.items() if c > 0] or ["productivity", "conversion"]

    if ctx.llm.name != "deterministic":
        diag = ctx.llm.complete(
            system="You are a management consultant writing a crisp executive diagnosis (5-7 sentences) "
                   "grounded ONLY in the client's stated problem and company context provided. No invented numbers.",
            prompt=f"Company: {state.company_name}\nBusiness problem: {state.business_problem}\n"
                   f"Company context: {state.company_profile.description}\n"
                   f"Write the Executive Diagnosis.",
        )
        state.diagnosis.executive_diagnosis = diag.strip()
    else:
        state.diagnosis.executive_diagnosis = (
            f"{state.company_name} has flagged the following as the primary sales challenge: "
            f"\"{state.business_problem.strip()}\". Based on the language used, the issue clusters around "
            f"{', '.join(active_dims)}. This diagnosis is a structured restatement of client input, not an "
            f"independently audited finding — validate with pipeline and CRM data where available."
        )

    tree = [HypothesisNode(label="Revenue Growth", parent=None, evidence="Root node", impact="High", confidence="MEDIUM")]
    dim_labels = {
        "conversion": "Conversion & Qualification",
        "productivity": "Sales Productivity",
        "sales cycle": "Sales Cycle Length",
        "pricing": "Pricing & Deal Economics",
        "data fragmentation": "Data & Systems Fragmentation",
    }
    for dim in active_dims:
        label = dim_labels[dim]
        tree.append(
            HypothesisNode(
                label=label, parent="Revenue Growth",
                evidence=f"Client language referencing '{dim}' found in stated business problem ({hits.get(dim,0)} signal(s)).",
                impact="High" if hits.get(dim, 0) >= 1 else "Medium",
                confidence="MEDIUM",
                data_required="CRM pipeline export, seller time-tracking, or proposal cycle-time data",
                validation="Confirm with CRM/pipeline data upload or stakeholder interviews",
            )
        )
        for sub in _sub_hypotheses(dim):
            tree.append(HypothesisNode(label=sub, parent=label, evidence="Derived sub-driver", impact="Medium", confidence="LOW"))

    state.diagnosis.hypothesis_tree = tree
    set_summary(
        state, NAME,
        f"Parsed the stated business problem for revenue-driver signals; identified {len(active_dims)} primary "
        f"hypothesis branch(es): {', '.join(active_dims)}. Built a {len(tree)}-node hypothesis tree pending "
        "data validation.",
    )
    return state


def _sub_hypotheses(dim: str) -> list[str]:
    return {
        "conversion": ["Weak deal qualification", "Limited next-best-action guidance"],
        "productivity": ["Manual account research", "Manual proposal drafting", "Cross-team coordination overhead"],
        "sales cycle": ["Slow internal approvals", "Slow proposal turnaround"],
        "pricing": ["Inconsistent discounting", "Limited pricing intelligence"],
        "data fragmentation": ["CRM/ERP disconnect", "No unified customer 360"],
    }.get(dim, [])
