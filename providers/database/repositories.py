"""
Thin repository-per-entity façade over `providers/database/base.py`.

This is deliberately NOT a rewrite: `base.py` remains the actual SQLite
implementation (raw sqlite3, unchanged schema). Each repository class below
just gives callers a clean, entity-scoped interface (`.get()`, `.save()`,
`.list()`, ...) instead of calling loose `db.*` functions directly — so a
future swap to Postgres/Supabase only requires re-implementing these classes
against the new backend, not touching every call site in `app.py`/agents.

No new dependency (no ORM), no schema changes, no behavior changes: every
method below is a 1:1 pass-through to the existing function it wraps.
"""
from __future__ import annotations
from providers.database import base as db


class EngagementRepository:
    def get(self, engagement_id: str):
        return db.load_engagement(engagement_id)

    def save(self, state) -> None:
        db.save_engagement(state)

    def list(self) -> list[dict]:
        return db.list_engagements()


class LeadRepository:
    def save(self, lead, engagement_id: str = "") -> None:
        db.save_lead(lead, engagement_id=engagement_id)

    def list(self) -> list[dict]:
        return db.list_leads()


class DocumentRepository:
    """Documents live embedded in EngagementState.documents (no separate
    table) — this repository reads them via the owning engagement."""
    def get_for_engagement(self, engagement_id: str):
        state = db.load_engagement(engagement_id)
        return state.documents if state else None


class EvidenceRepository:
    """Evidence lives embedded in EngagementState (company_profile.evidence,
    market.evidence) — no separate table exists; this repository reads it
    via the owning engagement rather than duplicating storage."""
    def get_for_engagement(self, engagement_id: str) -> list:
        state = db.load_engagement(engagement_id)
        if not state:
            return []
        return list(state.company_profile.evidence) + list(state.market.evidence)


class AgentRunRepository:
    """Agent runs live embedded in EngagementState.agent_runs — this
    repository reads them via the owning engagement."""
    def get_for_engagement(self, engagement_id: str) -> dict:
        state = db.load_engagement(engagement_id)
        return state.agent_runs if state else {}

    def list_tool_telemetry(self, engagement_id: str) -> list[dict]:
        return db.list_tool_telemetry(engagement_id)


class OpportunityRepository:
    def get_for_engagement(self, engagement_id: str) -> list:
        state = db.load_engagement(engagement_id)
        return state.opportunities if state else []


class ROIRepository:
    def get_for_engagement(self, engagement_id: str):
        state = db.load_engagement(engagement_id)
        return state.roi_outputs if state else None


class ProposalRepository:
    def get_for_engagement(self, engagement_id: str) -> str:
        state = db.load_engagement(engagement_id)
        return state.proposal_markdown if state else ""


class ApprovalRepository:
    def record(self, engagement_id: str, stage: str, decision: str, reviewer: str = "consultant") -> None:
        db.record_approval(engagement_id, stage, decision, reviewer=reviewer)

    def get_for_engagement(self, engagement_id: str):
        state = db.load_engagement(engagement_id)
        return state.approval if state else None


class EmailRepository:
    def record(self, engagement_id: str, recipient: str, subject: str, status: str) -> None:
        db.record_email(engagement_id, recipient, subject, status)

    def get_for_engagement(self, engagement_id: str):
        state = db.load_engagement(engagement_id)
        return state.email_record if state else None


class AuditRepository:
    def log(self, engagement_id: str, actor: str, action: str, detail: str = "") -> None:
        db.log_audit(engagement_id, actor, action, detail=detail)

    def list(self, engagement_id: str) -> list[dict]:
        return db.list_audit(engagement_id)
