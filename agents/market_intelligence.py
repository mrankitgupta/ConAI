from __future__ import annotations
import re
from orchestration.state import EngagementState, Evidence
from agents._helpers import agent_step, set_summary
from agents.context import AgentContext
from tools.registry import ToolRegistry

NAME = "Market Intelligence Agent"

TECH_TREND_KEYWORDS = {
    "generative ai": "Generative AI adoption",
    "genai": "Generative AI adoption",
    "automation": "Process automation",
    "cloud": "Cloud migration",
    "data platform": "Data platform modernization",
    "cybersecurity": "Cybersecurity investment",
    "analytics": "Analytics / BI investment",
}
BUYING_SIGNAL_KEYWORDS = {
    "hiring": "Active hiring signal",
    "funding": "Funding / investment round",
    "acquisition": "M&A activity",
    "rfp": "Active RFP / procurement process",
    "partnership": "New partnership announced",
    "expansion": "Market expansion",
}
TRIGGER_KEYWORDS = {
    "leadership change": "Leadership change",
    "new ceo": "Leadership change",
    "restructur": "Organizational restructuring",
    "digital transformation": "Digital transformation initiative",
    "regulat": "Regulatory change",
}


@agent_step(NAME)
def run(state: EngagementState, ctx: AgentContext) -> EngagementState:
    industry = state.industry_hint.strip() or _guess_industry(state)
    market = state.market
    market.market_definition = industry or "Industry not specified"

    if not state.web_research_available:
        market.growth_note = "Not found / requires validation — web research unavailable."
        set_summary(state, NAME, "Skipped live market search (web research unavailable this session); using business-problem text only.")
        return state

    registry = ToolRegistry(ctx, engagement_id=state.engagement_id, agent_name=NAME)
    q = f"{industry} industry trends AI adoption sales digital transformation India" if industry else f"{state.company_name} industry competitors trends"
    search_result = registry.call("web_search", query=q, max_results=5)
    results = search_result.output if search_result.ok else []

    evidences, sources = [], []
    all_text = []
    for r in results:
        fetch_result = registry.call("web_fetch", url=r.url, max_chars=1500)
        text = fetch_result.output if fetch_result.ok else ""
        if not text:
            continue
        sources.append(r.url)
        all_text.append(text)
        evidences.append(Evidence(claim=r.snippet or r.title, source=r.title, source_type="web", url=r.url, origin="REAL_PUBLIC_DATA", confidence="MEDIUM"))
        registry.call("evidence_store", action="add", document=f"web:{r.title}", text=text, metadata={"url": r.url, "source_type": "web"})

    combined_text = " ".join(all_text).lower()
    market.evidence = evidences
    market.key_trends = [e.claim for e in evidences][:6]
    market.competitors = _extract_competitors(all_text, state.company_name)
    market.technology_trends = [label for kw, label in TECH_TREND_KEYWORDS.items() if kw in combined_text]
    market.buying_signals = [label for kw, label in BUYING_SIGNAL_KEYWORDS.items() if kw in combined_text]
    market.transformation_triggers = [label for kw, label in TRIGGER_KEYWORDS.items() if kw in combined_text]
    market.strategic_implications = (
        [f"{t} suggests increased near-term appetite for AI-enabled sales/service tooling." for t in market.technology_trends[:2]]
        if market.technology_trends else []
    )
    market.ai_adoption_note = (
        "Illustrative — inferred from retrieved trend snippets; not a market-sizing study."
        if evidences else "Not found / requires validation."
    )
    market.growth_note = "Estimated — see sourced trend snippets below; no verified market-sizing figure retrieved." if evidences else "Not found / requires validation."

    set_summary(
        state, NAME,
        f"Researched '{industry or 'inferred industry'}' market context, retrieved {len(evidences)} sourced trend "
        f"snippets, extracted {len(market.competitors)} competitor mention(s) and {len(market.transformation_triggers)} "
        "transformation trigger(s). Labelled as Estimated/Illustrative — no numeric market-size claim is asserted without a source.",
        sources=list(set(sources))[:8],
        tools=["web_search", "web_fetch", "evidence_store"],
    )
    return state


def _guess_industry(state: EngagementState) -> str:
    text = (state.company_profile.description + " " + state.business_problem).lower()
    for kw, label in [
        ("logistics", "Logistics & Supply Chain"), ("bank", "Banking & Financial Services"),
        ("steel", "Metals & Mining"), ("software", "IT Services / Software"),
        ("retail", "Retail & Consumer"), ("manufactur", "Manufacturing"),
        ("insurance", "Insurance"), ("pharma", "Pharmaceuticals"), ("auto", "Automotive"),
    ]:
        if kw in text:
            return label
    return ""


# Capitalized multi-word sequences appearing near a competitor-signal keyword —
# never invents a name outside what's actually present in the retrieved text.
_COMPETITOR_SIGNAL = re.compile(
    r"([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+){0,2})\s+(?:vs\.?|versus|and|,)\s+"
    r"([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+){0,2})"
)
_COMPETITOR_CONTEXT = re.compile(
    r"(?:competitors?|rivals?|alternatives?)\s*(?:include|are|:)?\s*"
    r"([A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+){0,2}"
    r"(?:,\s*[A-Z][A-Za-z0-9&.\-]+(?:\s+[A-Z][A-Za-z0-9&.\-]+){0,2}){0,4})"
)


def _extract_competitors(texts: list[str], own_company: str) -> list[str]:
    """Extracts competitor names only if actually present in retrieved snippets
    near a competitor-signal word — never invented. Returns [] honestly if
    nothing matched (previously this always returned [] unconditionally)."""
    found: set[str] = set()
    own = own_company.strip().lower()
    for text in texts:
        for m in _COMPETITOR_CONTEXT.finditer(text):
            for name in re.split(r",\s*", m.group(1)):
                name = name.strip()
                if name and name.lower() != own and len(name) > 2:
                    found.add(name)
        for m in _COMPETITOR_SIGNAL.finditer(text):
            for name in (m.group(1), m.group(2)):
                name = name.strip()
                if name and name.lower() != own and len(name) > 2:
                    found.add(name)
    return sorted(found)[:8]
