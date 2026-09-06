# AUDIT.md — ConAI V2.2

Audit performed by inspecting every changed source file, running
`python -m compileall .`, running `pytest tests/ -v` (45 tests), and
actually launching the Streamlit app in a real browser (Chromium-based, via
the in-session Browser tool) — not just headless `AppTest` — to create a
live engagement end-to-end, click through pages, and check three viewport
widths. See TEST_REPORT.md for exact commands and output.

Legend: **GREEN** = genuinely implemented and verified · **AMBER** =
implemented but simplified/bounded · **RED** = missing or not attempted.

## V2.1 → V2.2 status changes

| Area | V2.1 status | V2.2 status | Evidence |
|---|---|---|---|
| Supervisor/orchestrator | RED | **GREEN (bounded)** | `orchestration/supervisor.py` + conditional edges in `graph.py` at 6 decision points; `tests/test_supervisor.py` verifies the bounded-iteration guarantee actually terminates (a real infinite-loop bug was found and fixed during development — see the file's docstring) |
| Tool registry universal use | AMBER (2 of ~14 agents) | **AMBER→GREEN for the agents touched this iteration** | `market_intelligence.py`, `document_intelligence.py`, `value_roi.py` now route through `ToolRegistry`; `company_research.py` and `lead_discovery.py` already did (V2.1). `proposal.py`, `roadmap.py`, `target_operating_model.py`, `governance.py` still call no external tools (they're pure logic over existing state, so there is nothing to route) |
| Tool telemetry completeness | AMBER (`source_urls` hardcoded `""`) | **GREEN** | `_extract_sources()` in `tools/registry.py` populates `source_urls` from actual tool output |
| Lead generation multi-stage pipeline | RED | **GREEN (8 of 10 named stages as distinct logic, 2 already existed)** | ICP Builder, Market Universe, Company Discovery, Trigger Detection, Pain Detection, AI Opportunity Matching all newly implemented in `agents/lead_discovery.py`; Lead Qualification and Create Engagement already existed. Company Intelligence stage is deliberately shallow (reuses the already-fetched snippet rather than an extra fetch per candidate, to keep DuckDuckGo search volume bounded on the keyless path) — this is the one stage that's AMBER, not GREEN |
| Market Intelligence → Lead linkage | RED | **GREEN** | `_extract_competitors()` real pattern-based extraction (previously always `[]`); `technology_trends`/`buying_signals`/`transformation_triggers`/`strategic_implications` fields added and surfaced in UI |
| RFP requirement matrix — page numbers | RED (file-level only) | **GREEN for PDF, honestly RED for other formats** | `utils/documents.py::extract_pages()` returns real PyMuPDF page numbers for PDFs; docx/txt/csv/xlsx correctly report `None`/"Not Found" rather than fabricating a page. Verified by `tests/test_rfp_matrix.py` with an actual generated PDF fixture |
| RFP requirement confidence | RED (hardcoded MEDIUM) | **GREEN** | Now derived from keyword-match count + capability-map strength; varies across rows |
| ROI: 3 scenarios simultaneously | RED (one selected scenario only) | **GREEN** | `roi_outputs.scenarios` computes all 3 every run; `tests/test_roi_engine.py` verifies Conservative < Base < Upside |
| ROI: sensitivity matrix | RED | **GREEN** | 25-point grid (conversion uplift × productivity gain), rendered as a pivot table in Value Case |
| ROI: assumption labeling per field | RED (one caption string) | **GREEN** | `ASSUMPTION_LABELS` dict covers every input/output field; added `CALCULATED` to the `DataOrigin` literal |
| Governance PII/injection checks | RED (hardcoded "OK") | **AMBER (heuristic, explicitly labeled as such)** | Regex-based email/phone/SSN-pattern scan and injection-phrase scan — real code, real detection, but explicitly NOT a certified DLP or security product; UI/docs never claim otherwise |
| Governance severity logic | AMBER (sequential if/downgrade) | **GREEN** | Explicit severity-ranked evaluation (`max(severities)`), order-independent |
| Repository-per-entity DB pattern | RED | **GREEN (thin façade, as scoped)** | `providers/database/repositories.py` — 11 classes wrapping the existing raw-sqlite3 functions; zero schema change, zero new dependency; parity verified by `tests/test_repositories.py` |
| Persistent engagement workspace header | RED | **GREEN** | `render_engagement_header()` in `app.py`, shown on every engagement-scoped page |
| Command Center charts (funnel, value, agent activity) | RED | **AMBER — funnel and value-by-engagement done, agent-activity chart not added** | Overview page now shows an Engagement Funnel and Value-by-Engagement bar chart; a dedicated cross-engagement "Agent Activity" chart was not built this iteration (per-engagement Agent Control Center trace was extended instead, which is the more requested view) |
| Opportunity Studio click-to-open detail + Add to Proposal | RED | **RED — not done** | The existing 2×2 bubble scatter and expander-based detail view (from V2.1) were kept; a `st.dialog`-based click interaction and "Add to Proposal" wiring were not built this iteration — out of time budget, not attempted, not claimed done |
| Premium visual design system (Zerodha/Linear-grade) | RED | **AMBER — incremental, not a rewrite** | Persistent header, new charts, and data tables were added within the existing CSS system (`:root` custom properties, card/badge classes); a from-scratch design-token rewrite, typography system overhaul, and full nav restructure into `st.tabs` were not attempted — the existing sidebar-button nav was kept because restructuring it carried real risk of breaking working pages with the time available |
| Browser/mobile validation | RED (never run) | **AMBER — run once, one browser engine, not automated** | Launched the real app via the in-session Browser tool, created an engagement end-to-end, verified Value Case/Market Intelligence/Agent Control Center render with real (non-fabricated) data, and checked a 375px mobile viewport (sidebar auto-collapses, cards stack — genuinely responsive, not just claimed). Did NOT check 1440/1024/768px individually, and this is one Chromium-based engine, not Playwright cross-browser automation |

## Carried over from V2.1 (unchanged, still true)

Approval hash-based versioning/invalidation, Client Communication Agent as
sole send path, SQLite persistence as source of truth, TF-IDF/FAISS RAG,
no-hardcoded-company-name discipline (`agents/` greps clean for
Tata/Reliance/HDFC/Infosys/Mahindra/Accenture) — all still GREEN, all still
covered by their original V2.1 tests plus new ones added this iteration.

## Explicitly still RED (honest, not attempted)

- Embedding/reranker abstraction beyond TF-IDF/FAISS auto-selection.
- SQLAlchemy/ORM migration (deliberately out of scope — thin repositories chosen instead, see plan).
- Paid search API for higher lead-gen volume (deliberately kept keyless per plan).
- Full Playwright/cross-browser E2E automation (one manual live-browser pass was run instead).
- A from-scratch premium design system matching the depth of Zerodha/Linear/Stripe's actual design work.
