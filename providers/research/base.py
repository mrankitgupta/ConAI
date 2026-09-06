"""
WebResearchProvider interface. Three implementations ship today:

- TavilyProvider — a real search API purpose-built for AI agents. Free tier:
  1,000 searches/month, no credit card required at signup
  (https://app.tavily.com). Used automatically when TAVILY_API_KEY is set.
- BraveProvider — Brave's Search API. Also has a free tier (check
  https://api-dashboard.search.brave.com for current limits — Brave's own
  pricing page is authoritative, not this comment). Used when
  BRAVE_API_KEY is set and no Tavily key is present.
- DuckDuckGoProvider — free, keyless fallback via HTML scraping (no
  official API, no signup at all). Kept as the zero-signup fallback, but
  DuckDuckGo's HTML endpoint frequently returns an anti-bot challenge page
  instead of real results depending on the network it's called from — when
  that happens this degrades to an honest empty list, never fabricated
  results.

Every option above except DuckDuckGo requires a one-time free API-key
signup (a developer/operator step, not an end-user login) — there is no
search provider that is both reliable and truly signup-free; scraping
(DuckDuckGo) is the only zero-signup path and it is exactly the one that's
prone to being blocked.

get_research_provider() picks, in order: Tavily (if TAVILY_API_KEY set) ->
Brave (if BRAVE_API_KEY set) -> DuckDuckGo -> NullResearchProvider if web
research is explicitly disabled.
"""
from __future__ import annotations
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass


_PUA_RE = re.compile(
    "[\U0000E000-\U0000F8FF\U000F0000-\U000FFFFD\U00100000-\U0010FFFD]"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
_MD_HEADER_RE = re.compile(r"(?m)(?:(?<=^)|(?<=\s))#{1,6}(?=\s|$)")
_WS_RE = re.compile(r"[ \t]{2,}")


def sanitize_snippet(text: str) -> str:
    """
    Clean scraped web text before it enters any state field, UI, or PDF.

    Real-world source: many corporate/financial sites (esp. Indian investor-
    relations pages) render currency symbols via a private-use-area glyph
    from a page-specific icon font. Copied out of that font context (e.g.
    into a search API's plain-text extraction), the codepoint has no glyph
    in any other font and renders as a black "tofu" box everywhere else —
    browser, terminal, or PDF. There's no way to recover which symbol it
    was with certainty, but in this platform's domain (Indian sales/finance
    content) it is virtually always a Rupee sign, so we substitute ₹.
    Scraped pages also leak raw markdown ("# Business highlights") that
    was never meant to be read as a heading in our own output — strip it.
    """
    if not text:
        return text
    text = _PUA_RE.sub("₹", text)
    text = _CONTROL_RE.sub("", text)
    text = _MD_HEADER_RE.sub("", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class WebResearchProvider(ABC):
    name: str = "base"

    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        ...

    @abstractmethod
    def fetch_text(self, url: str, max_chars: int = 4000) -> str:
        ...


class TavilyProvider(WebResearchProvider):
    """Real search API (not scraping) — https://tavily.com. Free tier: 1,000
    searches/month, no credit card. Set TAVILY_API_KEY to use it."""

    name = "tavily"

    def __init__(self, api_key: str):
        self._api_key = api_key

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        try:
            import requests

            r = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": self._api_key, "query": query, "max_results": min(max_results, 10)},
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            return [
                SearchResult(title=sanitize_snippet(item.get("title", "")), url=item.get("url", ""), snippet=sanitize_snippet(item.get("content", ""))[:500])
                for item in data.get("results", [])
            ]
        except Exception:
            return []

    def fetch_text(self, url: str, max_chars: int = 4000) -> str:
        try:
            import requests

            r = requests.post(
                "https://api.tavily.com/extract",
                json={"api_key": self._api_key, "urls": [url]},
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            results = data.get("results", [])
            if not results:
                return ""
            return sanitize_snippet((results[0].get("raw_content") or "")[:max_chars])
        except Exception:
            return ""


class BraveProvider(WebResearchProvider):
    """Real search API (not scraping) — https://brave.com/search/api. Set
    BRAVE_API_KEY to use it. Brave's search API has no page-extraction
    endpoint, so fetch_text() does a direct HTTP GET + HTML-strip of the
    result URL (same approach as DuckDuckGoProvider.fetch_text), which can
    fail for JS-rendered pages or sites that block bots — degrades to an
    honest empty string, same as every other provider here."""

    name = "brave"

    def __init__(self, api_key: str):
        self._api_key = api_key

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        try:
            import requests

            r = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": min(max_results, 20)},
                headers={"Accept": "application/json", "X-Subscription-Token": self._api_key},
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            results = (data.get("web") or {}).get("results", [])
            return [
                SearchResult(title=sanitize_snippet(item.get("title", "")), url=item.get("url", ""), snippet=sanitize_snippet(item.get("description", ""))[:500])
                for item in results
            ]
        except Exception:
            return []

    def fetch_text(self, url: str, max_chars: int = 4000) -> str:
        try:
            import requests
            from bs4 import BeautifulSoup

            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (AgenticRevenue research bot)"}, timeout=10)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
            return sanitize_snippet(text[:max_chars])
        except Exception:
            return ""


class DuckDuckGoProvider(WebResearchProvider):
    """Free, keyless. Uses the HTML endpoint (no official API) — best-effort
    and rate-limited; failures degrade to an empty list rather than raising
    past the caller, so the platform never crashes for lack of a key."""

    name = "duckduckgo"

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        try:
            import requests
            from bs4 import BeautifulSoup

            r = requests.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (AgenticRevenue research bot)"},
                timeout=10,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            out = []
            for res in soup.select(".result")[:max_results]:
                a = res.select_one(".result__a")
                snip = res.select_one(".result__snippet")
                if not a:
                    continue
                url = a.get("href", "")
                out.append(
                    SearchResult(
                        title=sanitize_snippet(a.get_text(strip=True)),
                        url=url,
                        snippet=sanitize_snippet(snip.get_text(strip=True)) if snip else "",
                    )
                )
            return out
        except Exception:
            return []

    def fetch_text(self, url: str, max_chars: int = 4000) -> str:
        try:
            import requests
            from bs4 import BeautifulSoup

            r = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (AgenticRevenue research bot)"},
                timeout=10,
            )
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()
            return sanitize_snippet(text[:max_chars])
        except Exception:
            return ""


class NullResearchProvider(WebResearchProvider):
    """Used when web research is disabled/unreachable. Always returns empty
    so agents fall back to 'Not found / requires validation' honestly."""

    name = "none"

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        return []

    def fetch_text(self, url: str, max_chars: int = 4000) -> str:
        return ""


def get_research_provider() -> WebResearchProvider:
    if os.environ.get("DISABLE_WEB_RESEARCH", "").lower() == "true":
        return NullResearchProvider()
    tavily_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if tavily_key:
        return TavilyProvider(tavily_key)
    brave_key = os.environ.get("BRAVE_API_KEY", "").strip()
    if brave_key:
        return BraveProvider(brave_key)
    return DuckDuckGoProvider()
