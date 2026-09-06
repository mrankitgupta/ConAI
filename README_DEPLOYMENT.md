# Deployment Guide

## Streamlit Community Cloud (recommended, free)
1. Push this folder to a GitHub repo.
2. share.streamlit.io -> New app -> main file `app.py`.
3. Optional secrets (App Settings -> Secrets):
   ```
   GROQ_API_KEY = "..."
   RAG_BACKEND = "tfidf"
   SMTP_HOST = "smtp.example.com"
   SMTP_USER = "..."
   SMTP_PASS = "..."
   ```
4. Deploy. `data/conai.db` is created automatically on first run — note that
   Streamlit Community Cloud's filesystem is ephemeral across redeploys; for
   durable multi-session history in production, point `CONAI_DB_PATH` at a
   mounted volume or migrate to Postgres (see ARCHITECTURE.md).

## Hugging Face Spaces (alternative, free)
Same as V1 — SDK: Streamlit, add secrets via Space Settings -> Variables and secrets.

## Required secrets
None. Everything in `.env.example` is optional.

## What works with zero configuration
Full pipeline, keyless web research, TF-IDF RAG, ROI/governance/roadmap/TOM,
SQLite persistence, PDF export, lead qualification, email DRY RUN, targeted re-run.

## What improves with configuration
- `GROQ_API_KEY` → LLM-narrated diagnosis/summaries.
- `RAG_BACKEND=faiss` + `pip install faiss-cpu sentence-transformers` → semantic RAG.
- `SMTP_*` → real email sending instead of dry-run.

## Known limitations (V2.0)
- SQLite is single-file, fine for demo/small team use; swap for Postgres/Supabase
  behind the same `providers/database` interface for multi-user production.
- DuckDuckGo's HTML endpoint is unofficial/best-effort and can rate-limit under load.
- Lead discovery surfaces company names from search snippet titles — a shortlist to
  validate, not a verified, deduplicated account list.
- No OCR — scanned PDFs return "no extractable text."
- No Playwright/browser E2E in this build environment; UI was regression-tested via
  Streamlit's `AppTest` headless framework (full page walk + create/approve/email/
  targeted-rerun flows, zero exceptions) — a real browser pass is recommended before
  a client-facing demo if one is available to you.

## V3+ roadmap
Postgres/Supabase backend · auth · CRM connector · richer conditional LangGraph
routing (multi-step planning, not just the one bounded retry) · Playwright CI · OCR.
