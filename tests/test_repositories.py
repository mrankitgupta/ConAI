import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_engagement_repository_roundtrip_matches_base_db(ctx, base_state):
    from providers.database.repositories import EngagementRepository
    from providers.database import base as db

    repo = EngagementRepository()
    repo.save(base_state)
    via_repo = repo.get(base_state.engagement_id)
    via_base = db.load_engagement(base_state.engagement_id)
    assert via_repo.engagement_id == via_base.engagement_id == base_state.engagement_id
    assert via_repo.company_name == via_base.company_name


def test_audit_repository_matches_base_db(base_state):
    from providers.database.repositories import AuditRepository
    from providers.database import base as db

    repo = AuditRepository()
    repo.log(base_state.engagement_id, "tester", "TEST_ACTION", "detail")
    via_repo = repo.list(base_state.engagement_id)
    via_base = db.list_audit(base_state.engagement_id)
    assert len(via_repo) == len(via_base)
    assert via_repo[0]["action"] == "TEST_ACTION"


def test_agent_run_repository_reads_embedded_runs(ctx, base_state):
    from orchestration.graph import run_engagement
    from providers.database.repositories import EngagementRepository, AgentRunRepository

    result = run_engagement(base_state, ctx)
    EngagementRepository().save(result)
    runs = AgentRunRepository().get_for_engagement(result.engagement_id)
    assert len(runs) > 0
    assert "Governance Agent" in runs
