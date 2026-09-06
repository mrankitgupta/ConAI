# ConAI Architecture

```
app.py                          Streamlit UI — grouped sidebar nav, DB-backed pages
orchestration/state.py          Single typed Pydantic EngagementState — no raw dict access anywhere
orchestration/graph.py          LangGraph pipeline (11 nodes) + rerun_from() targeted re-run
agents/*.py                     One file per agent: intake, company_research, market_intelligence,
                                 document_intelligence, sales_diagnostic, opportunity, value_roi,
                                 roadmap, target_operating_model, proposal, governance,
                                 lead_discovery, lead_qualification, client_communication
tools/registry.py                Central tool registry: validated, timed, logged wrapper around
                                 web_search / web_fetch / rag_retrieval / document_parser / calculator
providers/llm/base.py            LLMProvider: Groq | OpenAI-compatible | HF | Ollama | Deterministic
providers/research/base.py       WebResearchProvider: DuckDuckGo (free) | Null
providers/vectorstore/base.py    VectorStoreProvider: TF-IDF (default) | FAISS+embeddings
providers/database/base.py       DatabaseProvider: SQLite — engagements/leads/audit/approvals/emails
providers/email/base.py          EmailProvider: SMTP | honest DRY_RUN
utils/documents.py               Untrusted file extraction (pdf/docx/csv/xlsx/txt) — data, never instructions
utils/pdf_report.py              ReportLab client PDF, built from live state, no stale cache
tests/                            pytest suite (45 tests)
```

## IMPLEMENTED / SIMPLIFIED / NOT IMPLEMENTED

| Area | Status |
|---|---|
| LangGraph typed pipeline | IMPLEMENTED |
| Bounded Supervisor (conditional edges, logged decisions, capped retries) | IMPLEMENTED — `orchestration/supervisor.py`, 6 decision points |
| Targeted re-run with downstream invalidation | IMPLEMENTED (bypasses the supervisor graph — always runs each node exactly once) |
| SQLite persistence, source of truth | IMPLEMENTED |
| Repository-pattern DB layer | IMPLEMENTED (thin façade over raw sqlite3, `providers/database/repositories.py`) |
| Postgres/Supabase | NOT IMPLEMENTED (repository interface now exists to make this swap cleaner; still no adapter) |
| Tool registry | IMPLEMENTED (10 tools; routed through by market_intelligence, document_intelligence, value_roi, company_research, lead_discovery) |
| Lead discovery pipeline | IMPLEMENTED — ICP Builder → Market Universe → Discovery → Trigger Detection → Pain Detection → AI Opportunity Matching → Qualification → Ranking |
| Lead qualification scoring | IMPLEMENTED (deterministic, human override supported) |
| RFP requirement matrix (page numbers, real confidence) | IMPLEMENTED for PDF; honestly "Not Found" for other formats |
| ROI: 3 scenarios + sensitivity + assumption labels | IMPLEMENTED |
| Governance PASS/REVIEW/BLOCK gate | IMPLEMENTED, severity-ranked, with heuristic PII/injection scans |
| Audit log | IMPLEMENTED (SQLite `audit_logs` table) |
| Email | IMPLEMENTED — real SMTP send, honest DRY_RUN fallback |
| RAG | IMPLEMENTED — TF-IDF default, FAISS optional |
| PDF export | IMPLEMENTED |
| Persistent engagement workspace header | IMPLEMENTED |
| Opportunity Studio click-to-open + Add to Proposal | NOT IMPLEMENTED |
| Premium visual design-system rewrite | NOT IMPLEMENTED (incremental UI upgrade done instead — see AUDIT.md) |
| Browser UI E2E (Playwright, cross-browser) | NOT IMPLEMENTED — one manual live-browser pass (Chromium-based) was run instead, see TEST_REPORT.md |
| Multi-user auth | NOT IMPLEMENTED |
| OCR for scanned PDFs | NOT IMPLEMENTED |

## Adding an agent
Write `agents/foo.py` with `run(state, ctx) -> state` under `@agent_step("Foo Agent")`,
add to `NODE_ORDER` in `orchestration/graph.py`. `rerun_from()` and the Agent Control
Center pick it up automatically (dependency = position in `NODE_ORDER`). If the new
node needs supervisor-style conditional routing, add a `decide_after_*`/`route_after_*`
pair in `orchestration/supervisor.py` following the existing pattern (mutation happens
in a dedicated graph node, not the conditional-edge callback — see that file's docstring
for why) and wire it with `add_conditional_edges` in `graph.py`.

## Swapping a provider
Implement the relevant `providers/<kind>/` interface, update its `get_*_provider()`
factory. Agents never import a concrete provider class directly — only the interface.
