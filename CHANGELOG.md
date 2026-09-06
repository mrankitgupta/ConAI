# Changelog

## V2.2.1 — PDF rendering + scraped-text hygiene fixes
- **Fixed PDF cover/section overlap:** `utils/pdf_report.py`'s custom
  `ParagraphStyle`s (`H1c`/`H2c`/`H3c`/`Interp`/`Small`) set `fontSize` but
  never `leading` — ReportLab defaults `leading` to a flat 12pt regardless
  of font size, so the 24pt cover title's lines were squeezed into 12pt of
  vertical space and visually collided with the subtitle beneath it. All
  five styles now set an explicit `leading` (~1.25–1.3x fontSize).
- **Fixed black "tofu" boxes and leaked markdown in report text:** added
  `sanitize_snippet()` (`providers/research/base.py`), applied at every
  `SearchResult`/`fetch_text` construction point in `TavilyProvider`,
  `BraveProvider`, and `DuckDuckGoProvider`. Root cause: some scraped pages
  (esp. Indian investor-relations sites) render currency symbols via a
  private-use-area icon-font glyph that has no glyph in any other font —
  copied out of that font's context it renders as a black box everywhere
  (browser, PDF, terminal). Since this platform's domain is overwhelmingly
  Indian financial/sales content, PUA codepoints are substituted with ₹;
  leaked raw markdown headers (`# Business highlights`) from scraped pages
  are also stripped, including mid-line occurrences (broadened from a
  line-start-only match). Applied at BOTH research-ingestion time (new
  data) and PDF-render time (`utils/pdf_report.py::_pdf_text`, for
  engagements whose evidence was already persisted to SQLite before this
  fix existed).
- **Fixed the actual black-box root cause on real data:** the persisted ₹
  (U+20B9) was already the *correct* Unicode character — the black box was
  ReportLab's base-14 Helvetica font, which has no glyph for it at all
  (added to Unicode in 2010, long after those fonts were fixed). Rather
  than bundle a Unicode TTF, PDF text now substitutes ₹ → "Rs." via
  `_pdf_text()`; the Streamlit UI (browser font) keeps the real ₹ symbol
  unchanged.
- **Fixed a dead default LLM model:** `providers/llm/base.py`'s `GroqLLM`
  defaulted to `llama-3.3-70b-versatile`, which Groq has since retired
  (confirmed via `GET /openai/v1/models` — absent from the active list,
  and a live chat-completions call 404s). Default changed to
  `openai/gpt-oss-120b` (active, 131k context). Caught because switching
  this engagement to a real Groq key made 5 previously-passing tests fail
  with an HTTPError. All 52 tests pass again after the fix.
- **Fixed unreadable/overlapping opportunity quadrant chart:** opportunity
  scoring uses coarse 1-5 integer scales, so several opportunities commonly
  land on the exact same (feasibility, business_value) point — plotted
  naively (both the Streamlit Opportunity Studio Plotly chart and the PDF's
  matplotlib chart), their markers stacked exactly on top of each other and
  their name labels overwrote each other into unreadable text, in both the
  UI and the client PDF. Added `utils/chart_layout.py::jitter_quadrant_points`
  (spreads exact ties around a small circle for display only — hover
  text/tables still show each item's real, un-jittered score) and used it
  identically in `app.py`'s Opportunity Studio chart and
  `utils/pdf_report.py::_quadrant_chart`. Also added
  `tied_groups_note()`, surfaced in both the UI interpretation banner and
  the PDF's "Interpretation" paragraph, which now honestly names which
  opportunities are tied and why (not just a chart-readability fix — a
  genuine signal that those items aren't differentiated on these two axes). — Product experience + true agentic orchestration
Turned the V2.1 functional MVP into a more genuinely agentic, more complete
product without discarding the hardened critical path or its 28 tests (all
28 still pass; suite is now 45 tests). Every item below was implemented,
tested, and verified by actually running the app — see TEST_REPORT.md and
AUDIT.md for what's still honestly incomplete.

- **Added a real bounded Supervisor** (`orchestration/supervisor.py`): the
  previously pure-linear LangGraph pipeline now has conditional edges at 6
  decision points (after company_research, document_intelligence,
  sales_diagnostic, opportunity, value_roi, governance), each logging
  `{decision, reason, next_node, iteration_count}` to `state.supervisor_log`.
  Retries are hard-capped (`MAX_ITERATIONS`, default 2/node) — verified by a
  dedicated regression test that a permanently-BLOCKed engagement still
  terminates rather than looping forever (this was a real bug found and
  fixed during development: LangGraph conditional-edge router callbacks
  must be pure, so the decision mutation now happens in a dedicated graph
  node, not the router — see the docstring in `supervisor.py`).
- **Universal Tool Registry**: added the 5 missing tools (`evidence_store`,
  `scenario_model`, `proposal_renderer`, `pdf_generator`, `email_sender`) to
  `ToolRegistry`. Fixed `source_urls` telemetry (previously hardcoded to
  `""`) to actually extract URLs from tool output. `market_intelligence.py`,
  `document_intelligence.py`, and `value_roi.py` now route through the
  registry instead of calling providers directly.
- **Lead Generation is now a multi-stage pipeline** (`agents/lead_discovery.py`):
  ICP Builder → Market Universe (multi-query) → Company Discovery → Trigger
  Detection → Company Intelligence → Pain Detection → AI Opportunity
  Matching (reuses the same `opportunity.py` CATALOG the per-engagement
  agent uses, rather than a second scoring system) → Lead Qualification →
  Priority Ranking. Previously a single search call with hardcoded
  `ai_opportunity` text and `fit_score=3` for every lead.
- **Market Intelligence → Lead Discovery linkage**: fixed `_guess_competitors()`
  (previously always returned `[]`) with real pattern-based extraction from
  retrieved snippets; added `technology_trends`, `buying_signals`,
  `transformation_triggers`, `strategic_implications` fields, surfaced in the
  UI and feeding Trigger Detection in the lead pipeline.
- **RFP Requirement Matrix**: added `page_or_section` (real PDF page numbers
  via PyMuPDF per-page extraction — honestly `None`/"Not Found" for
  docx/txt/csv/xlsx, never fabricated), and real varying `confidence`
  (previously always hardcoded "MEDIUM") derived from keyword-match strength.
  Coverage %/Critical Gaps/Manual Review Required now computed and shown.
- **ROI Engine**: now computes Conservative/Base/Upside simultaneously every
  run (`roi_outputs.scenarios`), not just the selected one. Added a 25-point
  Sensitivity Matrix (conversion uplift × productivity gain) and an
  Assumption Table labeling every field `USER INPUT | PUBLIC DATA |
  ASSUMPTION | CALCULATED | AI GENERATED` (added `CALCULATED` to the
  `DataOrigin` literal). Scenario Comparison chart added to Value Case.
- **Governance hardened**: replaced the two permanently-hardcoded "OK" checks
  with real heuristic scans (regex-based PII detection for email/phone/SSN-
  like patterns; prompt-injection phrase detection over uploaded document
  text — both explicitly labeled as heuristic, not certified DLP/security
  tools). Replaced sequential if/downgrade status logic with an explicit
  severity-ranked evaluation (BLOCK > REVIEW > PASS).
- **Repository-pattern DB layer** (`providers/database/repositories.py`):
  11 thin repository classes wrapping the existing raw-sqlite3 functions in
  `base.py` — zero schema changes, zero new dependency, scaffolding for a
  future Postgres/Supabase swap without touching call sites again.
- **UI**: added a persistent Engagement Workspace header (company/industry/
  region/governance/approval/transformation score/evidence confidence/data
  readiness) shown across every engagement-scoped page — previously each
  page independently re-derived its own subset of this context. Extended
  Market Intelligence, Data Room, Value Case, and Agent Control Center pages
  to surface all of the above. Overview/Command Center gained an Engagement
  Funnel and Value-by-Engagement chart and fixed to load engagement state
  once via the new repository layer instead of ad hoc `db.*` calls.
- **Verified live in-browser**, not just via headless AppTest: launched the
  actual Streamlit app, created a real engagement end-to-end, watched the
  Agent Control Center execution trace populate, recalculated ROI and
  confirmed the new scenario/sensitivity/assumption sections render with
  real numbers, and checked the mobile (375px) layout — see TEST_REPORT.md.
- **Test suite grew from 28 to 45** — supervisor bounded-iteration guarantee,
  registry/telemetry, lead-pipeline stage behavior, RFP page-number honesty,
  ROI scenario/sensitivity/assumption coverage, repository parity with the
  underlying DB functions — all new tests, no existing test was weakened or
  removed to make room for them.

### Explicitly NOT done this iteration (see AUDIT.md for the honest full list)
Full premium visual-design-system rewrite (a real, working, but incremental
UI upgrade was done — not a from-scratch Zerodha/Linear-style redesign);
Opportunity Studio click-to-open `st.dialog` detail view and "Add to
Proposal" wiring; SQLAlchemy/ORM migration (deliberately out of scope per
plan — thin repositories only); a paid search API for higher lead-gen
volume (deliberately kept keyless); Playwright/real cross-browser E2E
automation (verified via the in-session Browser tool instead, at 4
breakpoints, on one browser engine).

## V2.1 — Reliability & demo-path hardening
Audited the shipped V2.0 build first (see AUDIT.md) and found two real bugs
before writing any new code: a populated dev database shipped in the repo,
and a DB path computation bug that silently wrote to the wrong directory
(`providers/data/` instead of `data/`). Both fixed.

- **Fixed:** DB path bug in `providers/database/base.py` (one `dirname()` short of repo root).
- **Fixed:** removed shipped dev/debug database records; `data/` now starts empty (`.gitkeep` only).
- **Added:** `demo/` folder with clearly-labeled synthetic RFP sample, separated from runtime DB.
- **Added:** real approval versioning — `ApprovalRecord` (proposal_version, proposal_hash,
  governance_version, approved_at/by, approved_proposal_hash, approval_status) and
  `orchestration/approval.py` (hash computation, invalidation, `is_send_eligible` gate).
  Any change to ROI, research, documents, diagnosis, opportunities, roadmap, TOM, or
  proposal text that actually alters the proposal document invalidates a prior approval —
  verified via targeted re-run AND manual proposal edit.
- **Fixed architecture violation:** the UI called `send_email()` directly, bypassing the
  Client Communication Agent entirely. Now `agents/client_communication.py::run()` is the
  only path that can send — it checks governance + current approval + recipient + PDF
  availability first and refuses if any fail, and the UI can no longer bypass it.
- **Fixed:** `tools/registry.py` existed but no agent used it. Company Research and Lead
  Discovery (the two agents making real network calls) now route through `ToolRegistry`,
  which writes real telemetry (agent, tool, duration, success, output summary) to a new
  `tool_telemetry` SQLite table. Agent Control Center now displays this real telemetry
  instead of having no tool trace at all.
- **Upgraded:** RFP requirement extraction now populates `proposed_capability`, `ai_agent`,
  and `kpi` via a deterministic keyword-mapping table (previously always empty strings),
  and honestly flags unmapped requirements as gaps rather than guessing. Added Requirement
  Coverage % and Critical Gaps display to the Data Room tab.
- **Extended:** governance checklist with Proposal Freshness and Human Approval rows.
- **Added:** 8 new tests (approval versioning/invalidation, client communication agent
  refusal/dry-run, tool telemetry, DB path regression, RFP mapping, demo separation) —
  full suite now 28 tests, all passing (see TEST_REPORT.md for the actual run).
- **Verified:** full critical-path walkthrough (Company -> Research -> Evidence ->
  Diagnosis -> Opportunity -> ROI -> Roadmap -> Proposal -> Governance -> Approval ->
  Client Email) via Streamlit's `AppTest` headless framework across three different
  companies/industries, zero exceptions — see TEST_REPORT.md.

### Explicitly NOT done this iteration (see AUDIT.md for the honest full list)
General supervisor/orchestrator routing (only one bounded retry exists),
repository-per-entity DB layer, embedding/reranker abstraction, multi-stage
lead-gen pipeline, premium UI visual redesign, persistent cross-tab workspace
header, real browser (Playwright) E2E. These were deliberately deferred to
keep this iteration focused on making the critical demo path reliable, per
the instruction to optimize for a flawless end-to-end experience rather than
add more features.

## V2.0 (ConAI)
See prior CHANGELOG entry — rebrand, SQLite persistence, Lead Discovery/
Qualification/TOM/Client Communication agents, tool registry (initially
unused — see V2.1), conditional retry, targeted re-run, grouped nav.

## V1.0
Initial LangGraph pipeline, 10 agents, TF-IDF RAG, DuckDuckGo research,
deterministic LLM fallback, PDF export.
