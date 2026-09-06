from __future__ import annotations
from orchestration.state import EngagementState, Evidence
from agents._helpers import agent_step, set_summary
from agents.context import AgentContext
from tools.registry import ToolRegistry

NAME = "Company Research Agent"
MIN_SUFFICIENT_EVIDENCE = 3  # below this, agent does one extra conditional retrieval pass


@agent_step(NAME)
def run(state: EngagementState, ctx: AgentContext) -> EngagementState:
    company = state.company_name.strip()
    profile = state.company_profile
    profile.name = company
    registry = ToolRegistry(ctx, engagement_id=state.engagement_id, agent_name=NAME)

    queries = [
        f"{company} company overview business segments",
        f"{company} strategic priorities digital transformation",
        f"{company} annual report highlights",
        f"{company} AI artificial intelligence initiative",
    ]

    sources_used, evidences = _search_pass(registry, company, queries)
    fetched_any = bool(evidences)

    # Conditional agentic behavior: if evidence is thin, decide to retrieve
    # more before concluding, instead of settling for a weak first pass.
    retry_note = ""
    if 0 < len(evidences) < MIN_SUFFICIENT_EVIDENCE:
        initial_count = len(evidences)
        extra_queries = [f"{company} news recent announcement", f"{company} products services customers"]
        more_sources, more_evidence = _search_pass(registry, company, extra_queries)
        sources_used += more_sources
        evidences += more_evidence
        retry_note = f" Evidence was initially thin ({initial_count} item(s)); agent decided to run one additional retrieval pass, now {len(evidences)}."

    if not fetched_any:
        state.web_research_available = False
        profile.description = "Not found / requires validation — web research unavailable."
        profile.research_quality = "LOW"
        set_summary(
            state, NAME,
            "Web research provider returned no reachable results (likely blocked or offline in this "
            "environment). Falling back to user-provided input only — no facts were invented.",
        )
        return state

    # Build description from LLM if available, else deterministic summary of retrieved snippets
    context_text = "\n".join(e.claim for e in evidences)[:3000]
    if ctx.llm.name != "deterministic":
        desc = ctx.llm.complete(
            system=(
                "You are a company research analyst. Summarize ONLY what is stated in the provided "
                "web snippets. If something is not covered, do not guess. Be concise, 4-6 sentences."
            ),
            prompt=f"Company: {company}\nSnippets:\n{context_text}\n\nWrite a factual company overview.",
        )
        profile.description = desc.strip()
    else:
        profile.description = (
            f"Based on {len(evidences)} retrieved public snippets: "
            + " ".join(e.claim for e in evidences[:4])
        )[:1200]

    profile.evidence = evidences[:12]
    profile.research_quality = "MEDIUM" if len(evidences) >= 4 else "LOW"
    profile.recent_signals = [e.claim for e in evidences if "expand" in e.claim.lower() or "launch" in e.claim.lower() or "invest" in e.claim.lower()][:5]

    set_summary(
        state, NAME,
        f"Searched {len(queries)} query angles, retrieved {len(evidences)} sourced snippets from "
        f"{len(set(sources_used))} distinct pages for '{company}'. Confidence: {profile.research_quality}.{retry_note}",
        sources=list(set(sources_used))[:10],
        tools=["web_search", "web_fetch", "vectorstore.add_document"],
    )
    return state


def _search_pass(registry: ToolRegistry, company: str, queries: list[str]):
    sources_used, evidences = [], []
    for q in queries:
        search_result = registry.call("web_search", query=q, max_results=3)
        if not search_result.ok:
            continue
        for r in search_result.output[:2]:
            fetch_result = registry.call("web_fetch", url=r.url, max_chars=2500)
            if not fetch_result.ok or not fetch_result.output:
                continue
            text = fetch_result.output
            sources_used.append(r.url)
            registry.ctx.vectorstore.add_document(document=f"web:{r.title}", text=text, metadata={"url": r.url, "source_type": "web"})
            evidences.append(
                Evidence(claim=r.snippet or r.title, source=r.title, source_type="web", url=r.url, confidence="MEDIUM", origin="REAL_PUBLIC_DATA")
            )
    return sources_used, evidences
