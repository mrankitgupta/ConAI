import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_get_research_provider_prefers_tavily_when_key_set(monkeypatch):
    from providers.research.base import get_research_provider, TavilyProvider
    monkeypatch.delenv("DISABLE_WEB_RESEARCH", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "test-key-123")
    p = get_research_provider()
    assert isinstance(p, TavilyProvider)
    assert p.name == "tavily"


def test_get_research_provider_falls_back_to_duckduckgo_without_any_key(monkeypatch):
    from providers.research.base import get_research_provider, DuckDuckGoProvider
    monkeypatch.delenv("DISABLE_WEB_RESEARCH", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    p = get_research_provider()
    assert isinstance(p, DuckDuckGoProvider)


def test_get_research_provider_uses_brave_when_only_brave_key_set(monkeypatch):
    from providers.research.base import get_research_provider, BraveProvider
    monkeypatch.delenv("DISABLE_WEB_RESEARCH", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("BRAVE_API_KEY", "test-brave-key")
    p = get_research_provider()
    assert isinstance(p, BraveProvider)
    assert p.name == "brave"


def test_get_research_provider_prefers_tavily_over_brave_when_both_set(monkeypatch):
    from providers.research.base import get_research_provider, TavilyProvider
    monkeypatch.delenv("DISABLE_WEB_RESEARCH", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "test-tavily-key")
    monkeypatch.setenv("BRAVE_API_KEY", "test-brave-key")
    p = get_research_provider()
    assert isinstance(p, TavilyProvider)


def test_brave_search_degrades_honestly_on_failure():
    from providers.research.base import BraveProvider
    p = BraveProvider(api_key="definitely-invalid-key-for-testing")
    results = p.search("test query", max_results=3)
    assert results == []


def test_get_research_provider_respects_disable_flag_even_with_key(monkeypatch):
    from providers.research.base import get_research_provider, NullResearchProvider
    monkeypatch.setenv("TAVILY_API_KEY", "test-key-123")
    monkeypatch.setenv("DISABLE_WEB_RESEARCH", "true")
    p = get_research_provider()
    assert isinstance(p, NullResearchProvider)


def test_tavily_search_degrades_honestly_on_failure(monkeypatch):
    """A bad/unreachable key must return [] like every other provider failure
    mode here — never raise past the caller, never fabricate results."""
    from providers.research.base import TavilyProvider
    p = TavilyProvider(api_key="definitely-invalid-key-for-testing")
    results = p.search("test query", max_results=3)
    assert results == []
    text = p.fetch_text("https://example.com")
    assert text == ""
