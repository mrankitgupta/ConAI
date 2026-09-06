import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _base_inputs():
    from orchestration.state import ROIInputs
    return ROIInputs(annual_revenue_cr=100, seller_count=10, fully_loaded_seller_cost_lakh=20,
                      conversion_uplift_pct=10, productivity_gain_pct=10, implementation_cost_cr=1, scenario="Base")


def test_all_three_scenarios_computed_simultaneously(ctx):
    from orchestration.state import EngagementState
    from agents.value_roi import run as roi_run
    s = EngagementState(company_name="X", business_problem="test")
    s.roi_inputs = _base_inputs()
    s = roi_run(s, ctx)
    assert set(s.roi_outputs.scenarios.keys()) == {"Conservative", "Base", "Upside"}
    cons = s.roi_outputs.scenarios["Conservative"].total_annual_value_cr
    base = s.roi_outputs.scenarios["Base"].total_annual_value_cr
    upside = s.roi_outputs.scenarios["Upside"].total_annual_value_cr
    assert cons < base < upside


def test_sensitivity_matrix_has_multiple_points(ctx):
    from orchestration.state import EngagementState
    from agents.value_roi import run as roi_run
    s = EngagementState(company_name="X", business_problem="test")
    s.roi_inputs = _base_inputs()
    s = roi_run(s, ctx)
    assert len(s.roi_outputs.sensitivity_matrix) >= 9
    for row in s.roi_outputs.sensitivity_matrix:
        assert "conversion_uplift_pct" in row and "productivity_gain_pct" in row and "total_annual_value_cr" in row


def test_assumption_labels_cover_user_input_and_calculated(ctx):
    from orchestration.state import EngagementState
    from agents.value_roi import run as roi_run
    s = EngagementState(company_name="X", business_problem="test")
    s.roi_inputs = _base_inputs()
    s = roi_run(s, ctx)
    labels = s.roi_outputs.assumption_labels
    assert labels["annual_revenue_cr"] == "USER INPUT"
    assert labels["fully_loaded_seller_cost_lakh"] == "ASSUMPTION"
    assert labels["total_annual_value_cr"] == "CALCULATED"


def test_roi_state_serializes_without_circular_reference(ctx):
    from orchestration.state import EngagementState
    from agents.value_roi import run as roi_run
    s = EngagementState(company_name="X", business_problem="test")
    s.roi_inputs = _base_inputs()
    s = roi_run(s, ctx)
    s.model_dump_json()  # must not raise PydanticSerializationError
