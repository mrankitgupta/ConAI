# ConAI

**AI-powered Sales Transformation, Market Intelligence, Lead Generation & Proposal Platform**
*From company intelligence to client-ready transformation.*

Real LangGraph-orchestrated agent pipeline — company research, market intelligence,
document/RFP intelligence, sales diagnosis, AI opportunity discovery, ROI modeling,
roadmap, target operating model, proposal drafting, and a genuine governance gate —
persisted to SQLite, with human approval required before any client-facing PDF or
email goes out.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```
No API key required. Boots in **zero-key mode**: deterministic analysis + free
keyless web search (DuckDuckGo) + TF-IDF RAG + SQLite + email dry-run.

## Run tests
```bash
python -m compileall .
pytest tests/ -v
```
45 tests, last actual run: **45 passed** (see `TEST_REPORT.md` for the full log,
including the real bugs found and fixed while building this iteration —
an infinite-loop bug in the new supervisor, and a circular-reference
serialization bug in the new ROI scenarios).

## What's IMPLEMENTED vs SIMPLIFIED vs NOT IMPLEMENTED
See `AUDIT.md` for the full, evidence-based GREEN/AMBER/RED breakdown (this is
not a marketing claim — every row points to the actual code or test that backs it).

Headline honesty notes (V2.2):
- **IMPLEMENTED (GREEN)**: bounded Supervisor with logged, capped-retry conditional
  routing; universal tool registry with real telemetry (source URLs included);
  multi-stage lead-generation pipeline (ICP → Market Universe → Discovery → Trigger
  Detection → Pain Detection → AI Opportunity Matching → Qualification → Ranking);
  RFP requirement matrix with real PDF page numbers and varying confidence; ROI engine
  computing all 3 scenarios + a sensitivity matrix + per-field assumption labels;
  hardened governance with real heuristic PII/injection scans and severity-ranked
  status; thin repository-pattern DB layer; persistent engagement workspace header.
- **SIMPLIFIED (AMBER)**: lead-gen's "Company Intelligence" stage reuses the already-
  fetched search snippet rather than an extra fetch per candidate; PII/injection
  scans are explicitly heuristic, not certified DLP/security tooling; UI upgrade is
  incremental within the existing design system, not a from-scratch visual rewrite;
  browser/mobile validation was a single manual pass on one browser engine, not
  automated cross-browser E2E.
- **NOT IMPLEMENTED (RED)**: Opportunity Studio click-to-open dialog + "Add to
  Proposal" wiring, SQLAlchemy/ORM migration (deliberately out of scope), paid
  search API (deliberately kept keyless), Postgres/Supabase backend, multi-user
  auth, Playwright cross-browser E2E — see AUDIT.md.

## Deployment
See `README_DEPLOYMENT.md` — Streamlit Community Cloud (primary) or Hugging Face
Spaces (alternative), zero local dependency.
