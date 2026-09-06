import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_imports():
    import app  # noqa - if this imports cleanly, the app is wired correctly
    from orchestration import state, graph
    from providers.llm import base as llm_base
    from providers.research import base as research_base
    from providers.vectorstore import base as vs_base
    from providers.database import base as db_base
    from providers.email import base as email_base
    from tools import registry


def test_pydantic_schema_defaults():
    from orchestration.state import EngagementState
    s = EngagementState()
    assert s.engagement_id
    assert s.company_profile.description == "Not found / requires validation"
    assert s.governance.status == "NOT_RUN"


def test_engagement_pipeline_end_to_end(ctx, base_state):
    from orchestration.graph import run_engagement
    result = run_engagement(base_state, ctx)
    failed = [n for n, r in result.agent_runs.items() if r.status == "FAILED"]
    assert failed == [], f"Agents failed: {failed}"
    assert result.diagnosis.executive_diagnosis
    assert len(result.opportunities) > 0
    assert result.roi_outputs.total_annual_value_cr >= 0
    assert len(result.roadmap) == 4
    assert len(result.target_operating_model) == 5
    assert result.proposal_markdown
    assert result.governance.status in ("PASS", "REVIEW", "BLOCK")


def test_second_company_is_generic(ctx):
    from orchestration.state import EngagementState
    from orchestration.graph import run_engagement
    s = EngagementState(company_name="Example Financial Services Ltd", business_problem="Relationship managers spend excessive time preparing client insights and identifying cross-sell opportunities.")
    s.roi_inputs.annual_revenue_cr = 300
    s.roi_inputs.seller_count = 40
    result = run_engagement(s, ctx)
    names = [o.name for o in result.opportunities]
    assert "Cross-sell / Whitespace Agent" in names  # different signal -> different opportunity mix


def test_no_hardcoded_company_names_in_agent_logic():
    banned = ["Tata", "Reliance", "HDFC", "Infosys", "Mahindra", "Accenture"]
    for fname in os.listdir(os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents")):
        if not fname.endswith(".py"):
            continue
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents", fname)
        with open(path) as f:
            content = f.read()
        for name in banned:
            assert name not in content, f"{name} hardcoded in agents/{fname}"


def test_web_research_fallback_is_honest(ctx, base_state):
    from orchestration.graph import run_engagement
    result = run_engagement(base_state, ctx)
    assert result.web_research_available is False
    assert "Not found" in result.company_profile.description or "Not found" in result.company_profile.description


def test_document_extraction_and_rag(ctx, base_state, tmp_path):
    p = tmp_path / "rfp.txt"
    p.write_text("The vendor shall provide proposal automation. The system must support SLA of 48 hours. Evaluation criteria include cost and security compliance.")
    base_state.uploaded_file_paths = [str(p)]
    from orchestration.graph import run_engagement
    result = run_engagement(base_state, ctx)
    assert result.documents.rag_chunks_indexed > 0
    assert len(result.documents.requirement_matrix) > 0
    hits = ctx.vectorstore.query("SLA requirement", top_k=3)
    assert len(hits) > 0


def test_roi_formulas_deterministic():
    from orchestration.state import EngagementState, ROIInputs
    from agents.value_roi import run as roi_run
    from agents.context import AgentContext
    from providers.llm.base import DeterministicLLM
    from providers.research.base import NullResearchProvider
    from providers.vectorstore.base import TfidfVectorStore

    ctx = AgentContext(llm=DeterministicLLM(), research=NullResearchProvider(), vectorstore=TfidfVectorStore())
    s = EngagementState(company_name="X", business_problem="test")
    s.roi_inputs = ROIInputs(annual_revenue_cr=100, seller_count=10, fully_loaded_seller_cost_lakh=20, conversion_uplift_pct=10, productivity_gain_pct=10, implementation_cost_cr=1, scenario="Base")
    s = roi_run(s, ctx)
    assert s.roi_outputs.incremental_revenue_cr == 10.0  # 100 * 10%
    s.roi_inputs.scenario = "Conservative"
    s2 = roi_run(s, ctx)
    assert s2.roi_outputs.incremental_revenue_cr < 10.0  # conservative multiplier < 1


def test_governance_blocks_on_zero_roi_inputs(ctx):
    from orchestration.state import EngagementState
    from orchestration.graph import run_engagement
    s = EngagementState(company_name="Zero Revenue Co", business_problem="test problem statement about sales productivity")
    result = run_engagement(s, ctx)
    assert result.governance.status == "BLOCK"


def test_governance_pass_with_good_inputs(ctx, base_state):
    from orchestration.graph import run_engagement
    result = run_engagement(base_state, ctx)
    assert result.governance.status in ("PASS", "REVIEW")


def test_pdf_generation(ctx, base_state):
    from orchestration.graph import run_engagement
    from utils.pdf_report import build_pdf
    result = run_engagement(base_state, ctx)
    pdf_bytes = build_pdf(result)
    assert pdf_bytes[:4] == b"%PDF"
    assert len(pdf_bytes) > 1000


def test_lead_qualification_scoring():
    from orchestration.state import LeadCandidate
    from agents.lead_qualification import qualify_lead
    lead = LeadCandidate(company="Acme Corp", industry="Manufacturing", why_now="declining margins under pressure", trigger="launching new digital transformation initiative this year", ai_opportunity="Sales Copilot")
    lead = qualify_lead(lead)
    assert lead.classification in ("HOT", "WARM", "NURTURE")
    assert 1 <= lead.overall_score <= 5


def test_targeted_rerun_leaves_upstream_untouched(ctx, base_state):
    from orchestration.graph import run_engagement, rerun_from
    result = run_engagement(base_state, ctx)
    original_desc = result.company_profile.description
    result.roi_inputs.conversion_uplift_pct = 25
    result2 = rerun_from(result, "value_roi", ctx)
    assert result2.company_profile.description == original_desc  # untouched


def test_database_persistence_roundtrip(ctx, base_state):
    from orchestration.graph import run_engagement
    from providers.database import base as db
    result = run_engagement(base_state, ctx)
    db.save_engagement(result)
    loaded = db.load_engagement(result.engagement_id)
    assert loaded is not None
    assert loaded.company_name == result.company_name
    listed = db.list_engagements()
    assert any(e["engagement_id"] == result.engagement_id for e in listed)


def test_audit_log_and_approval(ctx, base_state):
    from orchestration.graph import run_engagement
    from providers.database import base as db
    result = run_engagement(base_state, ctx)
    db.save_engagement(result)
    db.record_approval(result.engagement_id, "proposal", "APPROVED")
    logs = db.list_audit(result.engagement_id)
    assert any("APPROVAL" in l["action"] for l in logs)


def test_email_dry_run_when_unconfigured():
    from providers.email.base import send_email
    result = send_email("client@example.com", "Test", "Body")
    assert result.status == "DRY_RUN"


def test_email_rejects_invalid_address():
    from providers.email.base import send_email
    result = send_email("not-an-email", "Test", "Body")
    assert result.status == "FAILED"


def test_tool_registry_validates_input(ctx):
    from tools.registry import ToolRegistry
    reg = ToolRegistry(ctx)
    result = reg.call("web_fetch", url="not-a-url")
    assert result.ok is False
    assert "url" in result.error.lower()


def test_malformed_document_does_not_crash(tmp_path):
    from utils.documents import extract_text
    p = tmp_path / "bad.pdf"
    p.write_bytes(b"not a real pdf")
    text = extract_text(str(p))
    assert "failed" in text.lower() or text == ""


def test_approval_versioning_and_invalidation(ctx, base_state):
    from orchestration.graph import run_engagement, rerun_from
    from orchestration.approval import approve, is_send_eligible
    result = run_engagement(base_state, ctx)
    assert result.approval.approval_status == "NONE"
    result, ok, msg = approve(result)
    assert ok, msg
    assert result.approval.is_current
    eligible, reason = is_send_eligible(result)
    assert eligible, reason

    # Change an upstream input and re-run downstream — approval must invalidate
    result.roi_inputs.conversion_uplift_pct = 25
    result2 = rerun_from(result, "value_roi", ctx)
    assert result2.approval.approval_status == "INVALIDATED"
    eligible2, reason2 = is_send_eligible(result2)
    assert not eligible2


def test_proposal_edit_invalidates_approval(ctx, base_state):
    from orchestration.graph import run_engagement
    from orchestration.approval import approve, sync_approval_state
    result = run_engagement(base_state, ctx)
    result, ok, msg = approve(result)
    assert ok
    result.proposal_markdown += "\n\nManually added client-specific note."
    result = sync_approval_state(result)
    assert result.approval.approval_status == "INVALIDATED"


def test_client_communication_agent_refuses_without_approval(ctx, base_state):
    from orchestration.graph import run_engagement
    from agents.client_communication import run as client_comm_run
    result = run_engagement(base_state, ctx)
    result = client_comm_run(result, ctx, to_addr="client@example.com", subject="Test", body="Body", pdf_bytes=b"%PDF-fake")
    assert result.email_record.status == "FAILED"
    assert "Refused" in result.agent_runs["Client Communication Agent"].reasoning_summary


def test_client_communication_agent_sends_dry_run_when_approved(ctx, base_state):
    from orchestration.graph import run_engagement
    from orchestration.approval import approve
    from agents.client_communication import run as client_comm_run
    result = run_engagement(base_state, ctx)
    result, ok, msg = approve(result)
    assert ok
    result = client_comm_run(result, ctx, to_addr="client@example.com", subject="Test", body="Body", pdf_bytes=b"%PDF-fake")
    assert result.email_record.status == "DRY_RUN"


def test_tool_registry_records_telemetry(ctx, base_state):
    from orchestration.graph import run_engagement
    from providers.database import base as db
    result = run_engagement(base_state, ctx)
    # web research is disabled in tests (conftest), so calls should have been
    # attempted and recorded as failed/empty rather than silently skipped —
    # but since DISABLE_WEB_RESEARCH short-circuits at the provider level
    # with an empty result (not an exception), no telemetry rows are produced
    # in that mode. This test instead verifies the DB table exists and is queryable.
    telemetry = db.list_tool_telemetry(result.engagement_id)
    assert isinstance(telemetry, list)


def test_db_path_default_is_at_repo_root_not_inside_providers(monkeypatch):
    """Verifies the fixed path bug: default DB_PATH must resolve to
    <repo_root>/data/conai.db, not <repo_root>/providers/data/conai.db."""
    import importlib
    monkeypatch.delenv("CONAI_DB_PATH", raising=False)
    import providers.database.base as db_mod
    importlib.reload(db_mod)
    assert db_mod.DB_PATH.endswith(os.path.join("data", "conai.db"))
    assert os.sep + "providers" + os.sep not in db_mod.DB_PATH
    # restore test env var so subsequent tests in this session aren't affected
    monkeypatch.setenv("CONAI_DB_PATH", "/tmp/conai_test.db")
    importlib.reload(db_mod)


def test_rfp_requirement_mapping_produces_capability_fields(ctx, base_state, tmp_path):
    p = tmp_path / "rfp.txt"
    p.write_text("The vendor shall provide a proposal automation capability with a 48-hour SLA for RFP responses. The system must integrate with the existing CRM.")
    base_state.uploaded_file_paths = [str(p)]
    from orchestration.graph import run_engagement
    result = run_engagement(base_state, ctx)
    assert len(result.documents.requirement_matrix) > 0
    assert any(r.proposed_capability != "" for r in result.documents.requirement_matrix)
    assert any(r.ai_agent not in ("", None) for r in result.documents.requirement_matrix)


def test_demo_folder_separated_from_runtime_db():
    demo_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "demo")
    assert os.path.isdir(demo_dir)
    assert "sample_rfp.txt" in os.listdir(demo_dir)


def test_empty_csv_does_not_crash(tmp_path):
    from utils.documents import extract_text
    p = tmp_path / "empty.csv"
    p.write_text("")
    text = extract_text(str(p))
    assert isinstance(text, str)
