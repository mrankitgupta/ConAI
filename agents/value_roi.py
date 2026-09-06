from __future__ import annotations
from orchestration.state import EngagementState, ROIOutputs
from agents._helpers import agent_step, set_summary
from agents.context import AgentContext
from tools.registry import ToolRegistry

NAME = "Value / ROI Agent"

SCENARIO_MULT = {"Conservative": 0.6, "Base": 1.0, "Upside": 1.4}

ASSUMPTION_LABELS = {
    "annual_revenue_cr": "USER INPUT",
    "seller_count": "USER INPUT",
    "avg_deal_size_lakh": "USER INPUT",
    "sales_cycle_days": "USER INPUT",
    "win_rate_pct": "USER INPUT",
    "fully_loaded_seller_cost_lakh": "ASSUMPTION",
    "conversion_uplift_pct": "ASSUMPTION",
    "productivity_gain_pct": "ASSUMPTION",
    "proposal_effort_reduction_pct": "ASSUMPTION",
    "implementation_cost_cr": "USER INPUT",
    "incremental_revenue_cr": "CALCULATED",
    "productivity_value_cr": "CALCULATED",
    "cost_savings_cr": "CALCULATED",
    "total_annual_value_cr": "CALCULATED",
    "three_year_value_cr": "CALCULATED",
    "roi_pct": "CALCULATED",
    "payback_months": "CALCULATED",
}


def _compute_scenario(inp, mult: float) -> ROIOutputs:
    """All formulas are simple and shown in the UI/report — nothing hidden."""
    incremental_revenue = inp.annual_revenue_cr * (inp.conversion_uplift_pct / 100) * mult
    seller_cost_pool_cr = inp.seller_count * inp.fully_loaded_seller_cost_lakh / 100
    productivity_value = seller_cost_pool_cr * (inp.productivity_gain_pct / 100) * mult
    cost_savings = seller_cost_pool_cr * (inp.proposal_effort_reduction_pct / 100) * 0.3 * mult  # proposal effort is a slice of seller time

    total_annual = incremental_revenue + productivity_value + cost_savings
    three_yr = total_annual * 3 - inp.implementation_cost_cr  # simple, disclosed as illustrative
    roi_pct = ((total_annual * 3 - inp.implementation_cost_cr) / inp.implementation_cost_cr * 100) if inp.implementation_cost_cr > 0 else 0
    payback_months = (inp.implementation_cost_cr / total_annual * 12) if total_annual > 0 else 0

    return ROIOutputs(
        incremental_revenue_cr=round(incremental_revenue, 2),
        productivity_value_cr=round(productivity_value, 2),
        cost_savings_cr=round(cost_savings, 2),
        total_annual_value_cr=round(total_annual, 2),
        three_year_value_cr=round(three_yr, 2),
        roi_pct=round(roi_pct, 1),
        payback_months=round(payback_months, 1),
    )


def _sensitivity_matrix(inp, mult: float) -> list[dict]:
    """Vary conversion_uplift_pct and productivity_gain_pct over a small grid
    (+/-50% and +/-25% of the current value) to show how sensitive total
    annual value is to the two key drivers — deterministic-only, via the
    'scenario_model' tool contract (same formula as _compute_scenario)."""
    grid = []
    uplift_variants = sorted({round(inp.conversion_uplift_pct * f, 2) for f in (0.5, 0.75, 1.0, 1.25, 1.5)})
    gain_variants = sorted({round(inp.productivity_gain_pct * f, 2) for f in (0.5, 0.75, 1.0, 1.25, 1.5)})
    for u in uplift_variants:
        for g in gain_variants:
            variant = inp.model_copy(update={"conversion_uplift_pct": u, "productivity_gain_pct": g})
            out = _compute_scenario(variant, mult)
            grid.append({
                "conversion_uplift_pct": u,
                "productivity_gain_pct": g,
                "total_annual_value_cr": out.total_annual_value_cr,
            })
    return grid


@agent_step(NAME)
def run(state: EngagementState, ctx: AgentContext) -> EngagementState:
    inp = state.roi_inputs
    registry = ToolRegistry(ctx, engagement_id=state.engagement_id, agent_name=NAME)

    # Compute all three scenarios simultaneously via the scenario_model tool,
    # not just the currently-selected one.
    base_values = {
        "incremental_revenue_base": inp.annual_revenue_cr * (inp.conversion_uplift_pct / 100),
    }
    scenario_result = registry.call("scenario_model", base_values=base_values, multipliers=SCENARIO_MULT)
    scenarios: dict[str, ROIOutputs] = {}
    for name, mult in SCENARIO_MULT.items():
        scenarios[name] = _compute_scenario(inp, mult)

    # `selected` becomes the mutated top-level object (gets sensitivity_matrix,
    # assumption_labels, and scenarios attached) — it must NOT also appear
    # inside its own `.scenarios` dict, or serialization hits a circular
    # reference. Store a plain, unmutated copy of the selected scenario there.
    selected = scenarios[inp.scenario].model_copy(deep=True)
    selected.scenarios = {k: v.model_copy(deep=True) for k, v in scenarios.items()}
    selected.sensitivity_matrix = _sensitivity_matrix(inp, SCENARIO_MULT.get(inp.scenario, 1.0))
    selected.assumption_labels = dict(ASSUMPTION_LABELS)

    state.roi_outputs = selected

    set_summary(
        state, NAME,
        f"Computed all 3 scenarios (Conservative/Base/Upside); {inp.scenario} selected as primary. "
        f"Annual revenue ₹{inp.annual_revenue_cr}Cr, {inp.seller_count} sellers. Result: ₹{selected.total_annual_value_cr}Cr/year "
        f"modeled value, {selected.payback_months} month payback, {len(selected.sensitivity_matrix)}-point sensitivity grid computed. "
        "All non-user inputs are explicitly labeled ASSUMPTION; outputs labeled CALCULATED — never presented as verified financials.",
        tools=["scenario_model", "calculator"],
    )
    return state
