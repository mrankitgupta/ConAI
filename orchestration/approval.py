"""
Approval service: the single place that computes proposal hashes and decides
whether an existing approval is still current. Both the UI and the Client
Communication Agent call THIS, never a raw boolean flag, so "approved" always
means "approved for the exact proposal content that exists right now."
"""
from __future__ import annotations
import hashlib
import datetime
from orchestration.state import EngagementState


def compute_proposal_hash(state: EngagementState) -> str:
    """Hash of the proposal document text. Because proposal_markdown is
    assembled from company research, market intel, diagnosis, opportunities,
    ROI, roadmap, and TOM (see agents/proposal.py), any upstream change that
    actually affects the client-facing document changes this hash — that is
    the invalidation trigger, with no separate field-by-field diffing needed."""
    return hashlib.sha256(state.proposal_markdown.encode("utf-8")).hexdigest()[:16]


def sync_approval_state(state: EngagementState) -> EngagementState:
    """Call after any agent re-run or manual proposal edit. Recomputes the
    current hash and, if a prior approval no longer matches it, flips the
    status to INVALIDATED (never silently keeps a stale APPROVED)."""
    new_hash = compute_proposal_hash(state)
    approval = state.approval
    approval.proposal_hash = new_hash
    approval.governance_version = state.governance.status
    if approval.approval_status == "APPROVED" and new_hash != approval.approved_proposal_hash:
        approval.approval_status = "INVALIDATED"
    return state


def approve(state: EngagementState, reviewer: str = "consultant") -> tuple[EngagementState, bool, str]:
    """Returns (state, ok, message). Refuses to approve when governance BLOCKs."""
    if state.governance.status == "BLOCK":
        return state, False, "Cannot approve: governance status is BLOCK."
    state = sync_approval_state(state)
    state.approval.approval_status = "APPROVED"
    state.approval.approved_proposal_hash = state.approval.proposal_hash
    state.approval.approved_at = datetime.datetime.now().isoformat(timespec="seconds")
    state.approval.approved_by = reviewer
    state.approval.proposal_version += 1
    return state, True, "Approved."


def reject(state: EngagementState, reviewer: str = "consultant") -> EngagementState:
    state.approval.approval_status = "REJECTED"
    return state


def is_send_eligible(state: EngagementState) -> tuple[bool, str]:
    """The single gate both the UI and the Client Communication Agent check
    before any client-facing action (PDF unlock, email send)."""
    state = sync_approval_state(state)
    if state.governance.status == "BLOCK":
        return False, "Governance status is BLOCK."
    if not state.approval.is_current:
        if state.approval.approval_status == "INVALIDATED":
            return False, "Approval invalidated — the proposal changed since it was approved. Re-approve the current version first."
        return False, "Proposal has not been approved yet."
    return True, "Approved — current."
