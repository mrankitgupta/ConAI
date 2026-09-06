from __future__ import annotations
import datetime
from orchestration.state import EngagementState, EmailRecord
from orchestration.approval import is_send_eligible
from agents._helpers import agent_step, set_summary
from agents.context import AgentContext
from providers.email.base import send_email
from providers.database import base as db

NAME = "Client Communication Agent"


@agent_step(NAME)
def run(state: EngagementState, ctx: AgentContext, to_addr: str, subject: str, body: str, pdf_bytes: bytes) -> EngagementState:
    """
    The ONLY path that may send a client email. Called by the UI — the UI
    itself never calls providers.email.base.send_email() directly. Verifies,
    in order: governance status, current (non-stale) approval, a valid
    recipient address, and PDF availability — refusing to send if any fail.
    """
    eligible, reason = is_send_eligible(state)
    if not eligible:
        state.email_record = EmailRecord(recipient=to_addr, subject=subject, status="FAILED", detail=f"Refused to send: {reason}", timestamp=_now())
        db.record_email(state.engagement_id, to_addr, subject, "FAILED")
        set_summary(state, NAME, f"Refused to send — {reason}")
        return state

    if not to_addr or "@" not in to_addr:
        state.email_record = EmailRecord(recipient=to_addr, subject=subject, status="FAILED", detail="Invalid recipient address.", timestamp=_now())
        db.record_email(state.engagement_id, to_addr, subject, "FAILED")
        set_summary(state, NAME, "Refused to send — invalid recipient address.")
        return state

    if not pdf_bytes:
        state.email_record = EmailRecord(recipient=to_addr, subject=subject, status="FAILED", detail="PDF not available.", timestamp=_now())
        db.record_email(state.engagement_id, to_addr, subject, "FAILED")
        set_summary(state, NAME, "Refused to send — PDF unavailable.")
        return state

    result = send_email(to_addr, subject, body, attachment_bytes=pdf_bytes, attachment_name=f"ConAI_{state.company_name}.pdf")
    state.email_record = EmailRecord(recipient=to_addr, subject=subject, status=result.status, detail=result.detail, timestamp=_now())
    db.record_email(state.engagement_id, to_addr, subject, result.status)
    db.log_audit(
        state.engagement_id, "consultant", "CLIENT_EMAIL",
        f"status={result.status} recipient={to_addr} proposal_version={state.approval.proposal_version} proposal_hash={state.approval.proposal_hash}",
    )
    set_summary(state, NAME, f"Verified governance={state.governance.status}, approval={state.approval.approval_status} (current), recipient valid, PDF present. Email {result.status}: {result.detail}")
    return state


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")
