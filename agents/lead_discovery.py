"""
Lead Generation as a first-class, multi-stage pipeline:

ICP Builder -> Market Universe -> Company Discovery -> Trigger Detection ->
Company Intelligence -> Pain Detection -> AI Opportunity Matching ->
Lead Qualification -> Priority Ranking -> Create Engagement

The last two stages (Lead Qualification, Create Engagement) already existed
as `lead_qualification.qualify_lead()` and the UI's "Create Engagement"
button respectively — this module builds the eight stages that feed them,
replacing what was previously a single web_search call with hardcoded
placeholder fields (`ai_opportunity` was always one literal string,
`fit_score` was always 3).

Company-level and public-role-level signals only — never scrapes or
fabricates personal contact data. If web research is unavailable, every
stage degrades to an empty/honest result rather than inventing companies.
"""
from __future__ import annotations
from orchestration.state import LeadCandidate
from agents.context import AgentContext
from agents.opportunity import CATALOG, _solution_text
from tools.registry import ToolRegistry

TRIGGER_KEYWORDS = {
    "hiring": "Active hiring signal",
    "funding": "Funding / investment round",
    "acquisition": "M&A activity",
    "expansion": "Market expansion",
    "digital transformation": "Digital transformation initiative",
    "new ceo": "Leadership change",
    "restructur": "Organizational restructuring",
    "launch": "Product/initiative launch",
}
PAIN_KEYWORDS = ["declin", "pressure", "increasing cost", "losing", "slow", "inefficient", "manual", "backlog"]


def build_icp(industry: str, geography: str, challenge: str) -> dict:
    """Stage 1 — ICP Builder: turns the user's stated criteria into a
    structured Ideal Customer Profile used to drive Market Universe search."""
    return {
        "industry": industry.strip() or "Not specified",
        "geography": geography.strip() or "Not specified",
        "challenge": challenge.strip() or "General sales transformation fit",
    }


def _market_universe_queries(icp: dict) -> list[str]:
    """Stage 2 — Market Universe: a small set of query angles sizing the
    addressable universe of companies matching the ICP (not a single query)."""
    base = f"{icp['industry']} companies {icp['geography']}".strip()
    return [
        f"{base} {icp['challenge']}".strip(),
        f"{base} digital transformation initiative".strip(),
        f"{base} recent news announcement".strip(),
    ]


def generate_leads(industry: str, geography: str, challenge: str, ctx: AgentContext, max_leads: int = 6, engagement_id: str = "") -> list[LeadCandidate]:
    if not ctx.research or ctx.research.name == "none":
        return []

    icp = build_icp(industry, geography, challenge)
    registry = ToolRegistry(ctx, engagement_id=engagement_id, agent_name="Lead Discovery Agent")

    # Stage 3 — Company Discovery: run multiple query angles, dedupe by company name guess.
    candidates: dict[str, dict] = {}
    for q in _market_universe_queries(icp):
        result = registry.call("web_search", query=q, max_results=max_leads)
        if not result.ok:
            continue
        for r in result.output:
            company_name = r.title.split(" - ")[0][:60].strip()
            if not company_name or company_name in candidates:
                continue
            candidates[company_name] = {"title": r.title, "url": r.url, "snippet": r.snippet or ""}
            if len(candidates) >= max_leads:
                break
        if len(candidates) >= max_leads:
            break

    leads: list[LeadCandidate] = []
    for company_name, info in candidates.items():
        text = f"{info['title']} {info['snippet']}".lower()

        # Stage 4 — Trigger Detection: only claim a specific trigger if a
        # keyword actually matched the retrieved snippet; otherwise say so.
        matched_triggers = [label for kw, label in TRIGGER_KEYWORDS.items() if kw in text]
        trigger = matched_triggers[0] if matched_triggers else "No specific trigger detected in available public snippet"

        # Stage 5 — Company Intelligence: enrichment is limited to the
        # already-retrieved snippet (no extra fetch per candidate, to keep
        # lead-gen search volume bounded on the keyless DuckDuckGo path).
        why_now = info["snippet"][:200] or "Signal detected in public search result"

        # Stage 6 — Pain Detection.
        pain_hits = sum(kw in text for kw in PAIN_KEYWORDS)
        pain_intensity = min(5, 2 + pain_hits)

        # Stage 7 — AI Opportunity Matching: reuse the same CATALOG the
        # per-engagement Opportunity agent uses, so lead-gen and engagement
        # scoring share one source of truth instead of two systems.
        best_name, best_hits = None, 0
        for name, meta in CATALOG.items():
            hits = sum(kw in text for kw in meta["problem_kw"])
            if hits > best_hits:
                best_name, best_hits = name, hits
        if best_name:
            ai_opportunity = f"{best_name} — {_solution_text(best_name)}"
            fit_score = min(5, 2 + best_hits)
        else:
            ai_opportunity = "No specific AI opportunity pattern matched public snippet — requires discovery call to validate."
            fit_score = 2

        leads.append(
            LeadCandidate(
                company=company_name,
                industry=icp["industry"],
                why_now=why_now,
                trigger=trigger,
                ai_opportunity=ai_opportunity,
                fit_score=fit_score,
                confidence="LOW",  # heuristic from public search snippets only
                classification="NURTURE",
                evidence=info["url"],
                strategic_fit=fit_score,
                pain_intensity=pain_intensity,
                ai_opportunity_fit=fit_score,
                timing=4 if matched_triggers else 3,
                investment_signal=4 if any(k in text for k in ("funding", "invest", "budget")) else 2,
            )
        )
    return leads[:max_leads]
