"""
Central tool registry. Agents call ToolRegistry.call(name, **kwargs) instead
of importing provider internals directly, so every tool call gets uniform
input validation, timeout handling, and logging in one place.

This wraps the SAME real providers used elsewhere (no parallel fake
implementation) — it's a thin, consistent front door onto them.
"""
from __future__ import annotations
import time
import logging
from dataclasses import dataclass
from typing import Callable, Any

logger = logging.getLogger("conai.tools")
logging.basicConfig(level=logging.INFO)


@dataclass
class ToolResult:
    ok: bool
    output: Any
    error: str = ""
    duration_ms: float = 0.0


class ToolRegistry:
    def __init__(self, ctx, engagement_id: str = "", agent_name: str = ""):
        """ctx: agents.context.AgentContext (llm, research, vectorstore).
        engagement_id/agent_name are stamped onto every telemetry row so the
        Agent Control Center can show real per-agent tool traces from the DB,
        not fabricated ones."""
        self.ctx = ctx
        self.engagement_id = engagement_id
        self.agent_name = agent_name
        self._tools: dict[str, Callable] = {
            "web_search": self._web_search,
            "web_fetch": self._web_fetch,
            "rag_retrieval": self._rag_retrieval,
            "document_parser": self._document_parser,
            "calculator": self._calculator,
            "evidence_store": self._evidence_store,
            "scenario_model": self._scenario_model,
            "proposal_renderer": self._proposal_renderer,
            "pdf_generator": self._pdf_generator,
            "email_sender": self._email_sender,
        }

    def call(self, name: str, timeout_s: float = 20.0, **kwargs) -> ToolResult:
        if name not in self._tools:
            return ToolResult(ok=False, output=None, error=f"Unknown tool '{name}'")
        start = time.time()
        input_summary = ", ".join(f"{k}={str(v)[:60]}" for k, v in kwargs.items())
        try:
            out = self._tools[name](**kwargs)
            dur = (time.time() - start) * 1000
            if dur > timeout_s * 1000:
                logger.warning(f"tool {name} exceeded soft timeout ({dur:.0f}ms)")
            logger.info(f"tool={name} ok=True duration_ms={dur:.0f}")
            self._telemetry(name, True, dur, input_summary, _summarize_output(out), _extract_sources(out), "")
            return ToolResult(ok=True, output=out, duration_ms=dur)
        except Exception as e:
            dur = (time.time() - start) * 1000
            logger.error(f"tool={name} ok=False error={e}")
            self._telemetry(name, False, dur, input_summary, "", "", str(e))
            return ToolResult(ok=False, output=None, error=str(e), duration_ms=dur)

    def _telemetry(self, tool_name: str, success: bool, duration_ms: float, input_summary: str, output_summary: str, source_urls: str, error: str):
        if not self.engagement_id:
            return  # telemetry is per-engagement; skip if called outside an engagement context
        try:
            from providers.database import base as db
            db.log_tool_call(self.engagement_id, self.agent_name, tool_name, success, duration_ms, input_summary, output_summary, source_urls, error)
        except Exception:
            pass  # telemetry must never break the agent pipeline

    # ---- individual tool implementations (validate inputs, delegate to providers) ----
    def _web_search(self, query: str, max_results: int = 5):
        if not query or not isinstance(query, str):
            raise ValueError("query must be a non-empty string")
        return self.ctx.research.search(query, max_results=min(max_results, 10))

    def _web_fetch(self, url: str, max_chars: int = 3000):
        if not url or not url.startswith(("http://", "https://")):
            raise ValueError("url must be a valid http(s) URL")
        return self.ctx.research.fetch_text(url, max_chars=max_chars)

    def _rag_retrieval(self, query: str, top_k: int = 5):
        if not query:
            raise ValueError("query required")
        return self.ctx.vectorstore.query(query, top_k=top_k)

    def _document_parser(self, path: str):
        from utils.documents import extract_text
        return extract_text(path)

    def _calculator(self, expression_inputs: dict, formula: str):
        """Deterministic-only arithmetic — never routed through the LLM,
        per the spec's requirement that ROI/scoring math stay deterministic."""
        allowed_formulas = {
            "sum": lambda v: sum(v.values()),
            "weighted_avg": lambda v: sum(val * wt for val, wt in v.get("pairs", [])) / max(sum(wt for _, wt in v.get("pairs", [])), 1e-9),
        }
        if formula not in allowed_formulas:
            raise ValueError(f"Unknown formula '{formula}'")
        return allowed_formulas[formula](expression_inputs)

    def _evidence_store(self, action: str, document: str = "", text: str = "", metadata: dict | None = None, query: str = "", top_k: int = 5):
        """Thin front door onto the vectorstore provider for indexing/retrieving
        evidence text — action='add' indexes `text` under `document`, action='query' retrieves."""
        if action == "add":
            if not text:
                raise ValueError("text required for action='add'")
            n = self.ctx.vectorstore.add_document(document or "evidence", text, metadata=metadata or {})
            return {"chunks_indexed": n}
        if action == "query":
            if not query:
                raise ValueError("query required for action='query'")
            return self.ctx.vectorstore.query(query, top_k=top_k)
        raise ValueError("action must be 'add' or 'query'")

    def _scenario_model(self, base_values: dict, multipliers: dict):
        """Applies named scenario multipliers to a set of base numeric values —
        deterministic-only, used by value_roi.py for Conservative/Base/Upside."""
        if not isinstance(base_values, dict) or not isinstance(multipliers, dict):
            raise ValueError("base_values and multipliers must be dicts")
        return {
            scenario: {k: round(v * mult, 4) for k, v in base_values.items()}
            for scenario, mult in multipliers.items()
        }

    def _proposal_renderer(self, sections: dict):
        """Assembles a proposal_markdown string from an ordered dict of
        {section_title: body}. Pure string assembly — no LLM call, so it
        never fabricates content beyond what agents already computed."""
        if not isinstance(sections, dict):
            raise ValueError("sections must be a dict of {title: body}")
        return "\n\n".join(f"## {title}\n\n{body}" for title, body in sections.items())

    def _pdf_generator(self, state):
        from utils.pdf_report import build_pdf
        return build_pdf(state)

    def _email_sender(self, to_addr: str, subject: str, body: str, attachment_bytes: bytes | None = None):
        from providers.email import base as email_base
        if not to_addr or "@" not in to_addr:
            raise ValueError("to_addr must be a valid email address")
        return email_base.send_email(to_addr, subject, body, attachment_bytes=attachment_bytes)


def _summarize_output(out) -> str:
    try:
        if isinstance(out, list):
            return f"{len(out)} item(s)"
        if isinstance(out, str):
            return out[:120]
        return str(out)[:120]
    except Exception:
        return ""


def _extract_sources(out) -> str:
    """Best-effort extraction of URLs from a tool's output, for the
    'source_urls' telemetry column — previously always hardcoded to "".
    Returns a comma-joined string of up to 5 URLs found; empty if none."""
    try:
        urls: list[str] = []
        if isinstance(out, list):
            for item in out:
                url = getattr(item, "url", None) if not isinstance(item, dict) else item.get("url")
                if url:
                    urls.append(url)
        elif isinstance(out, str) and out.startswith(("http://", "https://")):
            urls.append(out)
        return ", ".join(urls[:5])
    except Exception:
        return ""
