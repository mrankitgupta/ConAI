import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["DISABLE_WEB_RESEARCH"] = "true"
os.environ["CONAI_DB_PATH"] = "/tmp/conai_test.db"
import pytest

@pytest.fixture
def ctx():
    from agents.context import AgentContext
    from providers.llm.base import get_llm_provider
    from providers.research.base import get_research_provider
    from providers.vectorstore.base import get_vectorstore
    return AgentContext(llm=get_llm_provider(), research=get_research_provider(), vectorstore=get_vectorstore())

@pytest.fixture
def base_state():
    from orchestration.state import EngagementState
    s = EngagementState(company_name="Example Industrial Technologies Ltd", business_problem="Sales cycles are increasing, win rates are declining, and sellers spend too much time researching accounts.")
    s.roi_inputs.annual_revenue_cr = 500
    s.roi_inputs.seller_count = 80
    return s
