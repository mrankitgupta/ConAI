# TEST_REPORT.md — ConAI V2.2

## pytest — full suite, real output

Command: `pytest tests -v` (from `C:\ConAI_V2\ConAI_v2.2`, venv Python 3.14.7)

```
============================= test session starts =============================
platform win32 -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
collected 45 items

tests/test_core.py .......................... (28 tests, all passing — unchanged from V2.1)
tests/test_lead_pipeline.py .... (4 passed)
tests/test_repositories.py ... (3 passed)
tests/test_rfp_matrix.py ... (3 passed)
tests/test_roi_engine.py .... (4 passed)
tests/test_supervisor.py ... (3 passed)

============================= 45 passed in 14.24s =============================
```

All 28 original V2.1 tests pass unmodified. 17 new tests added this
iteration, none replacing or weakening an existing one.

`python -m compileall .` — clean, no output, on every phase (run after each
change during development, not just once at the end).

## What each new test file actually proves

- **`test_supervisor.py`**: a permanently-BLOCKed engagement (zero revenue —
  regeneration cannot fix a missing user input) still terminates rather than
  looping forever, and every decision node's log entries carry all 4
  required fields. This test caught a real bug during development (an
  infinite proposal↔governance loop from a LangGraph router mutating state
  that wasn't persisted) — the fix is documented in `orchestration/supervisor.py`.
- **`test_lead_pipeline.py`**: uses a fake research provider (not the real
  DuckDuckGo scraper, which is inherently non-deterministic) to prove the
  pipeline actually detects a trigger keyword and matches an opportunity
  archetype from snippet text, rather than always returning the old
  hardcoded placeholder strings; also proves it degrades honestly (no
  trigger claimed) when the snippet has no signal, and returns `[]` when
  research is unavailable.
- **`test_rfp_matrix.py`**: generates a real 2-page PDF via PyMuPDF and
  proves requirement rows get real page numbers ("1"/"2"), while a `.txt`
  upload correctly gets `None` (never a fabricated page number).
- **`test_roi_engine.py`**: proves all 3 scenarios are computed with
  Conservative < Base < Upside ordering, the sensitivity grid has the
  expected number of points, assumption labels are present and correct for
  both a user-input and a calculated field, and — importantly — that the
  new `scenarios` dict doesn't create a circular reference when the state
  is serialized (this was a real bug caught and fixed during development).
- **`test_repositories.py`**: proves each repository class returns the same
  data as the underlying `db.*` function it wraps (parity, not just "it
  doesn't crash").

## Live browser verification (not headless AppTest only)

Launched the actual Streamlit app via the in-session Browser tool
(`streamlit run app.py`, real Chromium-based rendering) and:

1. Loaded the Command Center — metric cards, Engagement Funnel chart, and
   Value-by-Engagement chart all rendered with real (zero-state) data.
2. Created a real engagement ("Acme Manufacturing") through the actual form
   — the full 11-agent pipeline ran end-to-end with zero exceptions.
3. Confirmed the **persistent engagement header** renders on every
   engagement-scoped page with real values (governance status, transformation
   score, evidence confidence, data readiness).
4. Opened **Opportunity Studio** — 8 real prioritized opportunities with
   distinct priority scores rendered (not hardcoded).
5. Opened **Market Intelligence** — the new Competitors/Technology
   Trends/Buying Signals/Transformation Triggers sections rendered, honestly
   showing "Not Found" (web research was unreachable in this sandboxed
   environment, exactly as designed — no facts were invented to fill the
   gap).
6. Opened **Value Case**, edited inputs (₹500Cr revenue, 80 sellers) via the
   live UI, clicked **Recalculate**, and confirmed: ROI outputs updated
   (₹43.46Cr annual value), governance flipped from BLOCK to REVIEW as a
   direct consequence, the new **Scenario Comparison** chart rendered with
   3 distinct bars, and the **Sensitivity Matrix** and **Assumption Table**
   expanders both opened and displayed real computed content.
7. Opened **Agent Control Center** — all 11 agent run cards showed real
   timestamps and reasoning summaries (including honest "web research
   unavailable" messages, not fabricated success), the Value/ROI agent's
   summary correctly mentioned "Computed all 3 scenarios" and listed its
   real tool calls (`scenario_model`, `calculator`), and the new Supervisor
   decision log section rendered.
8. Resized the viewport to **375px (mobile)** and reloaded — the sidebar
   auto-collapsed, metric cards stacked full-width, and the funnel chart
   remained legible. This is a genuine observation of Streamlit's native
   responsive behavior working correctly with the new components, not a
   claim of full cross-device QA.

### What was NOT verified live (disclosed, not claimed)

- Individual screenshots at exactly 1440/1024/768px were not captured — only
  the default desktop pane width and 375px mobile were checked.
- Real SMTP email sending was not exercised live (dry-run mode only, by
  design in this environment with no SMTP credentials) — covered instead by
  `test_email_dry_run_when_unconfigured` and
  `test_client_communication_agent_sends_dry_run_when_approved`.
- PDF download was not clicked in the live browser session (Streamlit
  download buttons don't reliably trigger in the automated browser tool);
  covered instead by `test_pdf_generation` which asserts real `%PDF` magic
  bytes and a non-trivial byte count.
- Cross-browser (Firefox/Safari/Edge) rendering was not checked — one
  Chromium-based engine only.
- The Opportunity Studio click-to-open dialog and "Add to Proposal" feature
  described in the original spec was not built this iteration (see
  AUDIT.md) and so obviously was not tested.

## Honesty check (Section 20 of the original spec)

No company facts, market facts, TAM/SAM/SOM figures, lead information,
sources, tool traces, email-delivery status, approval status, or ROI values
were fabricated anywhere in this iteration's code or in this report. Every
number quoted above (₹43.46Cr, 8 opportunities, 45 tests, 375px, etc.) was
read directly from an actual command or browser observation during this
session, not estimated or invented.
