import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class _FakeResult:
    def __init__(self, title, url, snippet):
        self.title, self.url, self.snippet = title, url, snippet


class _FakeResearch:
    name = "fake"

    def __init__(self, results):
        self._results = results

    def search(self, query, max_results=5):
        return self._results[:max_results]

    def fetch_text(self, url, max_chars=4000):
        return ""


def test_lead_pipeline_detects_trigger_and_matches_opportunity(ctx):
    from agents.lead_discovery import generate_leads
    from agents.context import AgentContext

    fake_results = [
        _FakeResult(
            "Acme Manufacturing - Expansion Plans",
            "https://example.com/acme",
            "Acme Manufacturing announces digital transformation initiative and hiring surge amid declining win rates.",
        ),
    ]
    fake_ctx = AgentContext(llm=ctx.llm, research=_FakeResearch(fake_results), vectorstore=ctx.vectorstore)
    leads = generate_leads("Manufacturing", "India", "sales productivity", fake_ctx, max_leads=3)
    assert len(leads) == 1
    lead = leads[0]
    assert lead.company == "Acme Manufacturing"
    assert lead.trigger != "No specific trigger detected in available public snippet"
    assert lead.ai_opportunity != "Sales Copilot / Account Intelligence Agent (default hypothesis — validate per account)"
    assert lead.pain_intensity >= 3
    assert lead.evidence == "https://example.com/acme"


def test_lead_pipeline_honest_when_no_trigger_or_opportunity_signal(ctx):
    from agents.lead_discovery import generate_leads
    from agents.context import AgentContext

    fake_results = [_FakeResult("Generic Co", "https://example.com/generic", "")]
    fake_ctx = AgentContext(llm=ctx.llm, research=_FakeResearch(fake_results), vectorstore=ctx.vectorstore)
    leads = generate_leads("Retail", "Global", "", fake_ctx, max_leads=3)
    assert len(leads) == 1
    assert leads[0].trigger == "No specific trigger detected in available public snippet"


def test_lead_pipeline_returns_empty_when_research_unavailable(ctx):
    from agents.lead_discovery import generate_leads
    leads = generate_leads("Retail", "Global", "cost", ctx, max_leads=3)  # ctx fixture has NullResearchProvider
    assert leads == []


def test_lead_qualification_and_ranking_end_to_end(ctx):
    from agents.lead_discovery import generate_leads
    from agents.lead_qualification import qualify_lead
    from agents.context import AgentContext

    fake_results = [
        _FakeResult("Hot Co", "https://example.com/hot", "Hot Co announces urgent digital transformation this year, funding round, declining margins."),
        _FakeResult("Cold Co", "https://example.com/cold", ""),
    ]
    fake_ctx = AgentContext(llm=ctx.llm, research=_FakeResearch(fake_results), vectorstore=ctx.vectorstore)
    leads = generate_leads("Manufacturing", "India", "sales", fake_ctx, max_leads=5)
    qualified = sorted([qualify_lead(l) for l in leads], key=lambda l: l.overall_score, reverse=True)
    assert qualified[0].overall_score >= qualified[-1].overall_score
