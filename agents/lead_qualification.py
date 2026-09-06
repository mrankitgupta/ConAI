from __future__ import annotations
from orchestration.state import LeadCandidate

NAME = "Lead Qualification Agent"

# Deterministic scoring — per spec, scoring formulas must NOT go through the LLM.


def qualify_lead(lead: LeadCandidate) -> LeadCandidate:
    text = f"{lead.why_now} {lead.trigger}".lower()

    lead.pain_intensity = 4 if any(k in text for k in ["declin", "pressure", "increasing", "losing", "slow"]) else 3
    lead.ai_opportunity_fit = 4 if any(k in text for k in ["ai", "digital", "automat", "transform"]) else 3
    lead.data_readiness = 3  # unknown until validated with the account — conservative default
    lead.investment_signal = 4 if any(k in text for k in ["invest", "budget", "initiative", "launch"]) else 2
    lead.transformation_readiness = 3
    lead.timing = 4 if any(k in text for k in ["now", "urgent", "this year", "q1", "q2", "q3", "q4"]) else 3
    lead.strategic_fit = max(lead.strategic_fit, 3)

    score = lead.overall_score
    if score >= 4.0:
        lead.classification = "HOT"
    elif score >= 3.0:
        lead.classification = "WARM"
    else:
        lead.classification = "NURTURE"
    lead.confidence = "LOW"  # scoring is heuristic from search-snippet text only, never overstate certainty
    return lead


def apply_human_override(lead: LeadCandidate, new_classification: str, reason: str) -> LeadCandidate:
    lead.classification = new_classification
    lead.override_reason = reason
    return lead
