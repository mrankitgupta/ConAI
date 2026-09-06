from __future__ import annotations
import re
from orchestration.state import EngagementState, GovernanceCheck
from agents._helpers import agent_step, set_summary
from agents.context import AgentContext

NAME = "Governance Agent"

SEVERITY = {"OK": 0, "PENDING": 0, "REVIEW": 1, "BLOCK": 2}
STATUS_BY_SEVERITY = {0: "PASS", 1: "REVIEW", 2: "BLOCK"}

# Heuristic patterns — labelled as such; this is not a certified PII/DLP scanner
# or a general prompt-injection defense system, just a lightweight best-effort scan.
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3,5}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b")
_SSN_LIKE_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"ignore (?:all |the )?(?:previous|prior|above) instructions",
        r"disregard (?:all |the )?(?:previous|prior|above) instructions",
        r"you are now (?:in )?(?:developer|admin|god) mode",
        r"system\s*:\s*override",
        r"reveal (?:your|the) (?:system )?prompt",
    ]
]


@agent_step(NAME)
def run(state: EngagementState, ctx: AgentContext) -> EngagementState:
    checks: dict[str, str] = {}
    reasons: list[str] = []
    severities: list[int] = []

    def add(name: str, sev: int, detail: str, reason: str = ""):
        checks[name] = detail
        severities.append(sev)
        if reason:
            reasons.append(reason)

    # Source coverage
    if state.company_profile.research_quality == "LOW" and not state.uploaded_file_paths:
        add("Source coverage", 1, "REVIEW — low research confidence and no supporting documents uploaded",
            "Company research confidence is LOW with no documents to compensate.")
    else:
        add("Source coverage", 0, "OK")

    # Financial assumptions disclosed
    if state.roi_inputs.annual_revenue_cr == 0 or state.roi_inputs.seller_count == 0:
        add("Financial inputs", 2, "BLOCK — ROI inputs not provided",
            "ROI section cannot be presented to a client with zero/default financial inputs.")
    else:
        add("Financial inputs", 0, "OK — labelled as client assumption")

    # Missing critical sections
    if not state.opportunities:
        add("Opportunity portfolio", 2, "BLOCK — no opportunities generated",
            "No AI opportunities were identified; proposal would be empty.")
    else:
        add("Opportunity portfolio", 0, "OK")

    if not state.diagnosis.executive_diagnosis:
        add("Diagnosis", 2, "BLOCK — missing", "Executive diagnosis missing.")
    else:
        add("Diagnosis", 0, "OK")

    # PII scan — heuristic regex over uploaded doc extracts + proposal text.
    scan_text = " ".join(state.documents.key_extracts) + " " + state.proposal_markdown
    pii_hits = []
    if _EMAIL_RE.search(scan_text):
        pii_hits.append("email address")
    if _PHONE_RE.search(scan_text):
        pii_hits.append("phone-number-like pattern")
    if _SSN_LIKE_RE.search(scan_text):
        pii_hits.append("SSN-like pattern")
    if pii_hits:
        add("PII / sensitive data scan", 1, f"REVIEW — heuristic scan found possible {', '.join(pii_hits)} in extracted text",
            f"Heuristic PII scan flagged possible {', '.join(pii_hits)} — manual review recommended before client sharing.")
    else:
        add("PII / sensitive data scan", 0, "OK — heuristic scan found no email/phone/SSN-like patterns (not a certified DLP scan)")

    # Prompt-injection heuristic scan over uploaded document extracts only
    # (documents are the one place external, untrusted text enters the pipeline).
    doc_text = " ".join(state.documents.key_extracts)
    injection_hits = [p.pattern for p in _INJECTION_PATTERNS if p.search(doc_text)]
    if injection_hits:
        add("Prompt-injection defense", 1, "REVIEW — uploaded document text matched a known injection-style pattern",
            "Uploaded document text contains a phrase resembling a prompt-injection attempt; treated as inert data, but flagged for human review.")
    else:
        add("Prompt-injection defense", 0, "OK — heuristic scan found no known injection-style phrases; document text is always treated as data, not instructions")

    add("Proposal freshness", 0 if state.proposal_markdown else 2,
        "OK — proposal generated in this same run from current state" if state.proposal_markdown else "BLOCK — no proposal generated",
        "" if state.proposal_markdown else "No proposal was generated.")

    checks["Human approval"] = "PENDING — governance runs before human review; see Approvals tab"

    # Severity-ranked evaluation: BLOCK beats REVIEW beats PASS, regardless of
    # check order (previously a later PASS-only check could never downgrade
    # status, but order-dependence made the logic fragile to reordering).
    final_severity = max(severities) if severities else 0
    status = STATUS_BY_SEVERITY[final_severity]

    state.governance = GovernanceCheck(status=status, checks=checks, reasons=reasons)
    set_summary(state, NAME, f"Ran {len(checks)} governance checks (severity-ranked). Result: {status}." + (f" Reasons: {'; '.join(reasons)}" if reasons else ""))
    return state
