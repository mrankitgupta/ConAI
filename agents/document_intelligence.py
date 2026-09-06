from __future__ import annotations
import os
import re
from orchestration.state import EngagementState, RequirementRow
from agents._helpers import agent_step, set_summary
from agents.context import AgentContext
from tools.registry import ToolRegistry
from utils.documents import extract_text, extract_pages

NAME = "Document / RFP Intelligence Agent"

REQ_KEYWORDS = ["shall", "must", "should", "required", "deliverable", "kpi", "sla", "scope", "evaluation criteria"]
STRONG_KEYWORDS = ["shall", "must", "sla"]


@agent_step(NAME)
def run(state: EngagementState, ctx: AgentContext) -> EngagementState:
    if not state.uploaded_file_paths:
        set_summary(state, NAME, "No documents uploaded — skipped. Diagnosis will rely on the stated business problem and public research only.")
        state.agent_runs[NAME].status = "SKIPPED"
        return state

    registry = ToolRegistry(ctx, engagement_id=state.engagement_id, agent_name=NAME)
    total_chunks = 0
    req_rows: list[RequirementRow] = []
    extracts: list[str] = []
    rid = 1
    for path in state.uploaded_file_paths:
        fname = os.path.basename(path)
        parse_result = registry.call("document_parser", path=path)
        text = parse_result.output if parse_result.ok else ""
        if not text or text.startswith("[Skipped") or text.startswith("[Extraction failed"):
            state.agent_runs[NAME].warnings.append(text or f"[No text extracted from {fname}]")
            continue
        state.documents.filenames.append(fname)
        n = ctx.vectorstore.add_document(document=f"upload:{fname}", text=text, metadata={"source_type": "upload"})
        total_chunks += n
        extracts.append(text[:400])

        # Per-page text is only recoverable for PDFs (PyMuPDF). For every other
        # format we honestly leave page_or_section as None rather than guess.
        pages = extract_pages(path)
        if pages is not None:
            page_spans = [(str(i + 1), p) for i, p in enumerate(pages)]
        else:
            page_spans = [(None, text)]

        for page_label, page_text in page_spans:
            if rid > 60:
                break
            for sent in re.split(r"(?<=[.\n])", page_text):
                s = sent.strip()
                if len(s) < 15 or len(s) > 300:
                    continue
                low = s.lower()
                matched_kw = [k for k in REQ_KEYWORDS if k in low]
                if not matched_kw:
                    continue
                category = _categorize(low)
                capability, agent_name, kpi, gap, map_strength = _map_requirement(low, category)
                req_rows.append(
                    RequirementRow(
                        req_id=f"REQ-{rid:03d}",
                        requirement=s[:200],
                        category=category,
                        priority="High" if any(k in low for k in STRONG_KEYWORDS) else "Medium",
                        source=fname,
                        page_or_section=page_label,
                        proposed_capability=capability,
                        ai_agent=agent_name,
                        kpi=kpi,
                        confidence=_confidence(matched_kw, map_strength),
                        gap=gap,
                    )
                )
                rid += 1
                if rid > 60:
                    break

    state.documents.requirement_matrix = req_rows
    state.documents.key_extracts = extracts
    state.documents.rag_chunks_indexed = total_chunks

    coverage_pct, critical_gaps, manual_review = _coverage_stats(req_rows)
    set_summary(
        state, NAME,
        f"Processed {len(state.documents.filenames)} document(s), indexed {total_chunks} chunks into RAG, "
        f"extracted {len(req_rows)} candidate requirement statements. Requirement coverage {coverage_pct:.0f}%, "
        f"{critical_gaps} critical gap(s), {manual_review} requiring manual review.",
        tools=["document_parser", "evidence_store"],
    )
    return state


def _categorize(low: str) -> str:
    if any(k in low for k in ["price", "cost", "commercial", "payment"]):
        return "Commercial"
    if any(k in low for k in ["security", "data", "privacy", "compliance"]):
        return "Compliance/Data"
    if any(k in low for k in ["kpi", "sla", "evaluation"]):
        return "KPI/Evaluation"
    if any(k in low for k in ["technology", "integration", "api", "platform"]):
        return "Technology"
    return "Scope/Deliverable"


# Deterministic requirement -> ConAI capability mapping. Coarse but honest —
# "Gap" is the default; a requirement is only marked "Mapped"/"Partial" when
# it actually matches a capability keyword ConAI has an agent for.
# Last tuple element is the match "strength" used for confidence scoring: a
# multi-keyword category match with a real capability is HIGH, a single-keyword
# partial match is MEDIUM, an unmapped default is LOW.
CAPABILITY_MAP = [
    (["sla", "turnaround", "48-hour", "response time"], "Proposal automation with tracked SLA", "Proposal Agent", "Proposal turnaround time", "Partial", "HIGH"),
    (["proposal", "rfp response"], "RFP-aware proposal drafting", "Proposal Agent", "Proposal cycle time", "Partial", "HIGH"),
    (["crm", "integrat"], "CRM data integration for account context", "Account Intelligence Agent", "Data sync latency", "Gap — no CRM connector built yet", "MEDIUM"),
    (["security", "compliance", "audit"], "Governance-logged AI outputs with audit trail", "Governance Agent", "Governance PASS rate", "Partial", "HIGH"),
    (["scalab"], "Cloud-deployed, stateless agent pipeline", "Platform (all agents)", "Concurrent engagements supported", "Partial", "MEDIUM"),
    (["access control", "role-based", "rbac"], "Not implemented — no multi-user auth in this build", "N/A", "N/A", "Gap — no RBAC in V2", "MEDIUM"),
]


def _map_requirement(low: str, category: str) -> tuple[str, str, str, str, str]:
    for keywords, capability, agent_name, kpi, gap, strength in CAPABILITY_MAP:
        if any(k in low for k in keywords):
            return capability, agent_name, kpi, gap, strength
    # No keyword match — honestly flag as an unmapped gap rather than guessing.
    return "Not yet mapped", "Unassigned", "TBD", "Gap — requires manual review", "LOW"


def _confidence(matched_kw: list[str], map_strength: str) -> str:
    """Real, varying confidence — previously always hardcoded 'MEDIUM'.
    Derived from (a) how many requirement-signal keywords matched the sentence
    and (b) how strong the capability-map match was, not a single flat value."""
    if map_strength == "HIGH" and len(matched_kw) >= 2:
        return "HIGH"
    if map_strength == "LOW" or len(matched_kw) == 0:
        return "LOW"
    return "MEDIUM"


def _coverage_stats(rows: list[RequirementRow]) -> tuple[float, int, int]:
    if not rows:
        return 0.0, 0, 0
    mapped = sum(1 for r in rows if r.proposed_capability not in ("Not yet mapped", ""))
    coverage_pct = 100.0 * mapped / len(rows)
    critical_gaps = sum(1 for r in rows if r.priority == "High" and r.gap.startswith("Gap"))
    manual_review = sum(1 for r in rows if r.confidence == "LOW" or r.proposed_capability == "Not yet mapped")
    return coverage_pct, critical_gaps, manual_review
