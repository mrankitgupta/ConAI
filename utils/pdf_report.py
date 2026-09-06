"""
Client-facing PDF: a genuine consulting-report structure (cover, executive
summary, company/market intelligence, diagnosis, opportunity portfolio with
a real feasibility/value quadrant chart, business case with scenario and
waterfall charts, roadmap, target operating model, governance) rather than a
flat dump of state fields.

Every "interpretation" paragraph below is deterministic — computed directly
from the numbers/counts already in EngagementState (top opportunity by
priority score, quadrant tallies, payback-month framing, etc.) via plain
arithmetic and string templates, never an LLM call and never an invented
fact. This keeps the report's narrative sections honestly grounded in the
same data the tables show, consistent with the platform's no-fabrication
principle (see AUDIT.md / Section 20 of the product spec).
"""
from __future__ import annotations
from io import BytesIO
import matplotlib
matplotlib.use("Agg")  # headless — no display server in this environment
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable, Image, KeepTogether,
)
from orchestration.state import EngagementState
from providers.research.base import sanitize_snippet
from utils.chart_layout import jitter_quadrant_points, tied_groups_note

# ReportLab's built-in PDF base fonts (Helvetica etc.) ship with the
# standard WinAnsi/Latin-1 glyph set only — there is no glyph for the
# Indian Rupee sign (U+20B9), which was added to Unicode in 2010, long
# after those base-14 fonts were fixed. Any ₹ in Paragraph/Table text
# renders as a black ".notdef" box. Registering/embedding a Unicode TTF
# is the "correct" fix but adds a font-file dependency; substituting the
# plain-ASCII "Rs." here is the same tradeoff this codebase already makes
# elsewhere (browser/UI text keeps ₹ via the system font, which does have
# the glyph) — this substitution is PDF-only.
def _pdf_text(t: str) -> str:
    return sanitize_snippet(t).replace("₹", "Rs.")

NAVY = colors.HexColor("#0B1E3A")
ACCENT = colors.HexColor("#3B5BFB")
GREEN = colors.HexColor("#16A34A")
AMBER = colors.HexColor("#D97706")
RED = colors.HexColor("#DC2626")
GRAY = colors.HexColor("#6B7280")
LIGHT = colors.HexColor("#F7F8FB")

MPL_NAVY = "#0B1E3A"
MPL_ACCENT = "#3B5BFB"
MPL_GREEN = "#16A34A"
MPL_AMBER = "#D97706"
MPL_GRAY = "#94A3B8"


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#9CA3AF"))
    canvas.drawString(2 * cm, 1.2 * cm, "ConAI — AI-powered sales transformation platform. Confidential — prepared for internal client use.")
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
    canvas.restoreState()


def _quadrant_chart(opportunities) -> bytes | None:
    if not opportunities:
        return None
    fig, ax = plt.subplots(figsize=(6.4, 4.6), dpi=160)
    ax.set_xlim(0, 6)
    ax.set_ylim(0, 6)
    ax.axvline(3, color="#D1D5DB", linewidth=1)
    ax.axhline(3, color="#D1D5DB", linewidth=1)
    ax.set_xlabel("Feasibility", fontsize=10, color=MPL_NAVY)
    ax.set_ylabel("Business value", fontsize=10, color=MPL_NAVY)
    ax.text(4.5, 5.6, "Quick win", ha="center", fontsize=9, color=MPL_GRAY, style="italic")
    ax.text(1.5, 5.6, "Strategic", ha="center", fontsize=9, color=MPL_GRAY, style="italic")
    ax.text(4.5, 0.3, "Validate", ha="center", fontsize=9, color=MPL_GRAY, style="italic")
    ax.text(1.5, 0.3, "Long term", ha="center", fontsize=9, color=MPL_GRAY, style="italic")
    for pt in jitter_quadrant_points(opportunities):
        o = pt["item"]
        size = 200 + o.priority_score * 220
        ax.scatter(pt["x"], pt["y"], s=size, alpha=0.55, color=MPL_ACCENT, edgecolors=MPL_NAVY, linewidths=0.8)
        dy = 9 if pt["label_above"] else -13
        va = "bottom" if pt["label_above"] else "top"
        ax.annotate(o.name, (pt["x"], pt["y"]), fontsize=7.5, color=MPL_NAVY,
                    xytext=(0, dy), textcoords="offset points", ha="center", va=va)
    ax.set_xticks(range(0, 7))
    ax.set_yticks(range(0, 7))
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", transparent=False, facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _waterfall_chart(r) -> bytes | None:
    if r.total_annual_value_cr <= 0:
        return None
    labels = ["Conversion\nuplift", "Productivity\ngain", "Cost\nsavings", "Total\nannual value"]
    values = [r.incremental_revenue_cr, r.productivity_value_cr, r.cost_savings_cr]
    cum = [0, values[0], values[0] + values[1]]
    fig, ax = plt.subplots(figsize=(6.4, 4.0), dpi=160)
    colors_bar = [MPL_ACCENT, MPL_ACCENT, MPL_ACCENT, MPL_NAVY]
    for i, v in enumerate(values):
        ax.bar(i, v, bottom=cum[i], color=colors_bar[i], width=0.6)
        ax.text(i, cum[i] + v / 2, f"{v:.1f}", ha="center", va="center", fontsize=8.5, color="white", fontweight="bold")
    ax.bar(3, r.total_annual_value_cr, color=MPL_NAVY, width=0.6)
    ax.text(3, r.total_annual_value_cr / 2, f"{r.total_annual_value_cr:.1f}", ha="center", va="center", fontsize=8.5, color="white", fontweight="bold")
    ax.set_xticks(range(4))
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylabel("₹ Cr / year", fontsize=9.5, color=MPL_NAVY)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _scenario_chart(r) -> bytes | None:
    if not r.scenarios:
        return None
    order = ["Conservative", "Base", "Upside"]
    names = [n for n in order if n in r.scenarios]
    values = [r.scenarios[n].total_annual_value_cr for n in names]
    fig, ax = plt.subplots(figsize=(6.4, 3.6), dpi=160)
    bar_colors = [MPL_GRAY, MPL_ACCENT, MPL_NAVY]
    bars = ax.bar(names, values, color=bar_colors[: len(names)], width=0.5)
    for b, v in zip(bars, values):
        ax.text(b.get_x() + b.get_width() / 2, v, f"₹{v:.1f}Cr", ha="center", va="bottom", fontsize=9, color=MPL_NAVY)
    ax.set_ylabel("Annual value (₹ Cr)", fontsize=9.5, color=MPL_NAVY)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _quadrant_interpretation(opportunities) -> str:
    if not opportunities:
        return "No opportunities have been identified yet for this engagement."
    quick_wins = [o for o in opportunities if o.feasibility >= 3 and o.business_value >= 3]
    strategic = [o for o in opportunities if o.feasibility < 3 and o.business_value >= 3]
    top = max(opportunities, key=lambda o: o.priority_score)
    note = tied_groups_note(opportunities)
    base = (
        f"Of the {len(opportunities)} AI opportunities identified, {len(quick_wins)} sit in the Quick Win "
        f"quadrant (high feasibility, high business value) and {len(strategic)} are Strategic bets (high value, "
        f"lower near-term feasibility). The highest-priority opportunity is <b>{top.name}</b> "
        f"(priority score {top.priority_score}/5), addressing: {top.problem}"
    )
    return f"{base} {note}" if note else base


def _value_interpretation(inp, r) -> str:
    if r.total_annual_value_cr <= 0:
        return "ROI inputs have not yet been provided for this engagement — see Value Case to model the business case."
    payback_note = "well within a typical 12-month evaluation window" if r.payback_months <= 12 else "beyond a typical 12-month evaluation window, worth flagging to the client"
    scenario_note = ""
    if r.scenarios and len(r.scenarios) >= 2:
        cons = r.scenarios.get("Conservative")
        up = r.scenarios.get("Upside")
        if cons and up:
            scenario_note = (
                f" Across scenarios, modeled annual value ranges from ₹{cons.total_annual_value_cr:.1f}Cr (Conservative) "
                f"to ₹{up.total_annual_value_cr:.1f}Cr (Upside)."
            )
    return (
        f"Under the {inp.scenario} scenario, the modeled AI-enabled sales transformation program is estimated to "
        f"deliver ₹{r.total_annual_value_cr:.1f}Cr in annual value against a ₹{inp.implementation_cost_cr:.1f}Cr "
        f"implementation investment — a payback of approximately {r.payback_months:.1f} months, "
        f"{payback_note}.{scenario_note} All figures are scenario-modeled from user-provided assumptions, "
        "not audited financials — see the Assumption Table for the origin of every input."
    )


def _market_interpretation(market) -> str:
    parts = []
    if market.transformation_triggers:
        parts.append(f"{len(market.transformation_triggers)} transformation trigger(s) were detected in public sources ({', '.join(market.transformation_triggers)})")
    if market.buying_signals:
        parts.append(f"{len(market.buying_signals)} buying signal(s) ({', '.join(market.buying_signals)})")
    if market.competitors:
        parts.append(f"{len(market.competitors)} named competitor(s) surfaced in retrieved coverage")
    if not parts:
        return "No market triggers, buying signals, or competitor names were extracted from available public sources for this engagement — this reflects data availability, not an absence of market activity."
    return "Market scan found: " + "; ".join(parts) + ". These signals support the timing case for an AI-enabled sales transformation conversation."


def build_pdf(state: EngagementState) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=2 * cm, bottomMargin=2.2 * cm, leftMargin=2 * cm, rightMargin=2 * cm)
    styles = getSampleStyleSheet()
    # NOTE: ReportLab's ParagraphStyle defaults `leading` to a flat 12pt when
    # not passed explicitly — independent of `fontSize`. Every style here
    # must set leading >= ~1.25x fontSize or larger headings visually
    # collide with the line below them (this was a real bug: the 24pt H1c
    # cover title had leading=12, overlapping the subtitle under it).
    styles.add(ParagraphStyle("H1c", fontSize=24, leading=29, textColor=NAVY, spaceAfter=8, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle("H2c", fontSize=15, leading=19, textColor=NAVY, spaceBefore=16, spaceAfter=8, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle("H3c", fontSize=11.5, leading=15, textColor=ACCENT, spaceBefore=10, spaceAfter=4, fontName="Helvetica-Bold"))
    styles.add(ParagraphStyle("Body", fontSize=10, leading=14.5, textColor=colors.black))
    styles.add(ParagraphStyle("Small", fontSize=8, leading=11, textColor=GRAY))
    styles.add(ParagraphStyle("Interp", fontSize=9.5, leading=14, textColor=colors.HexColor("#1E293B"), backColor=LIGHT, borderPadding=8))

    flow = []

    # Defense in depth: also clean text at render time, not just at
    # research-ingestion time — this protects engagements whose evidence
    # was captured and persisted to SQLite before sanitize_snippet existed
    # (e.g. already-saved company/market descriptions and signals), so a
    # stale record doesn't ship a client PDF with tofu boxes / raw markdown.
    def h2(t):
        flow.append(Paragraph(_pdf_text(t), styles["H2c"]))

    def h3(t):
        flow.append(Paragraph(_pdf_text(t), styles["H3c"]))

    def body(t):
        flow.append(Paragraph(_pdf_text(t).replace("\n", "<br/>"), styles["Body"]))

    def interp(t):
        flow.append(Spacer(1, 4))
        flow.append(Paragraph(f"<b>Interpretation:</b> {_pdf_text(t)}", styles["Interp"]))
        flow.append(Spacer(1, 4))

    def styled_table(data, col_widths, header_color=NAVY):
        data = [[_pdf_text(cell) if isinstance(cell, str) else cell for cell in row] for row in data]
        t = Table(data, colWidths=col_widths)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), header_color), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ]))
        return t

    # ---------------------------------------------------------------- Cover
    flow.append(Spacer(1, 3.5 * cm))
    flow.append(Paragraph("◆ ConAI", styles["H1c"]))
    flow.append(Paragraph("AI-powered sales transformation, market intelligence, lead generation &amp; proposal platform", styles["Body"]))
    flow.append(Spacer(1, 0.8 * cm))
    flow.append(Paragraph("Sales Transformation Assessment", styles["H2c"]))
    flow.append(Spacer(1, 0.6 * cm))
    flow.append(Paragraph(f"<b>Prepared for:</b> {state.company_name}", styles["Body"]))
    flow.append(Paragraph(f"<b>Industry:</b> {state.industry_hint or state.market.market_definition or 'Not specified'}", styles["Body"]))
    flow.append(Paragraph(f"<b>Engagement ID:</b> {state.engagement_id}", styles["Body"]))
    flow.append(Paragraph(f"<b>Date:</b> {state.created_at[:10]}", styles["Body"]))
    flow.append(Paragraph(f"<b>Governance status:</b> {state.governance.status}", styles["Body"]))
    flow.append(Spacer(1, 0.6 * cm))
    flow.append(HRFlowable(width="100%", color=ACCENT, thickness=1.4))
    flow.append(Spacer(1, 0.3 * cm))
    flow.append(Paragraph("Independent AI-assisted assessment, generated from public research and client-provided inputs. Not an audited financial or legal document. See the Data &amp; Assumption Disclaimer at the end of this report.", styles["Small"]))
    flow.append(PageBreak())

    # ---------------------------------------------------------- Exec Summary
    h2("Executive summary")
    body(state.diagnosis.executive_diagnosis or "Not generated.")
    h3("Client context")
    body(f"<b>Stated business problem:</b> {state.business_problem}")

    # -------------------------------------------------------- Company intel
    h2("Company intelligence")
    body(state.company_profile.description or "Not found / requires validation.")
    body(f"<i>Research confidence: {state.company_profile.research_quality} · {len(state.company_profile.evidence)} sourced evidence item(s)</i>")
    if state.company_profile.recent_signals:
        h3("Recent signals")
        for sig in state.company_profile.recent_signals[:5]:
            body(f"• {sig}")

    # --------------------------------------------------------- Market intel
    h2("Market intelligence")
    body(f"<b>Market:</b> {state.market.market_definition or 'Not specified'}")
    body(f"<b>Growth:</b> {state.market.growth_note}")
    body(f"<b>AI adoption:</b> {state.market.ai_adoption_note}")
    if state.market.key_trends:
        h3("Key trends")
        for t in state.market.key_trends[:5]:
            body(f"• {t}")
    if state.market.competitors:
        h3("Competitors identified")
        body(", ".join(state.market.competitors))
    interp(_market_interpretation(state.market))

    # --------------------------------------------------------------- Diagnosis
    h2("Sales diagnosis &amp; hypothesis tree")
    for hnode in state.diagnosis.hypothesis_tree:
        prefix = "&nbsp;&nbsp;&nbsp;&nbsp;↳ " if hnode.parent else "• "
        body(f"{prefix}<b>{hnode.label}</b> (impact: {hnode.impact}, confidence: {hnode.confidence}) — {hnode.evidence}")

    # ------------------------------------------------------------ Opportunity
    flow.append(PageBreak())
    h2("AI opportunity portfolio")
    data = [["Opportunity", "Family", "Value", "Feasibility", "Data\nreadiness", "Priority", "Time to\nvalue (mo)", "Risk"]]
    for o in state.opportunities:
        data.append([o.name, o.family, str(o.business_value), str(o.feasibility), str(o.data_readiness), str(o.priority_score), str(o.time_to_value_months), o.risk])
    if len(data) > 1:
        flow.append(styled_table(data, [4.2 * cm, 2.3 * cm, 1.4 * cm, 1.7 * cm, 1.7 * cm, 1.5 * cm, 1.8 * cm, 1.4 * cm]))
        chart = _quadrant_chart(state.opportunities)
        if chart:
            flow.append(Spacer(1, 10))
            flow.append(Image(BytesIO(chart), width=14 * cm, height=10.06 * cm))
        interp(_quadrant_interpretation(state.opportunities))
    else:
        body("No opportunities generated yet.")

    # ------------------------------------------------------------- Value case
    flow.append(PageBreak())
    h2("Business case (value / ROI)")
    r = state.roi_outputs
    inp = state.roi_inputs
    roi_data = [
        ["Metric", "Value"],
        ["Scenario", inp.scenario],
        ["Incremental revenue value / yr", f"₹{r.incremental_revenue_cr} Cr"],
        ["Productivity value / yr", f"₹{r.productivity_value_cr} Cr"],
        ["Cost savings / yr", f"₹{r.cost_savings_cr} Cr"],
        ["Total annual value", f"₹{r.total_annual_value_cr} Cr"],
        ["3-year value", f"₹{r.three_year_value_cr} Cr"],
        ["ROI", f"{r.roi_pct}%"],
        ["Payback", f"{r.payback_months} months"],
    ]
    flow.append(styled_table(roi_data, [9 * cm, 5 * cm]))
    waterfall = _waterfall_chart(r)
    if waterfall:
        flow.append(Spacer(1, 10))
        flow.append(Image(BytesIO(waterfall), width=13 * cm, height=8.13 * cm))

    if r.scenarios:
        h3("Scenario comparison")
        scen_data = [["Scenario", "Annual value (₹Cr)", "3-yr value (₹Cr)", "ROI %", "Payback (mo)"]]
        for name in ["Conservative", "Base", "Upside"]:
            if name in r.scenarios:
                sv = r.scenarios[name]
                scen_data.append([name, f"{sv.total_annual_value_cr}", f"{sv.three_year_value_cr}", f"{sv.roi_pct}", f"{sv.payback_months}"])
        flow.append(styled_table(scen_data, [3.5 * cm, 3.3 * cm, 3 * cm, 2.3 * cm, 2.4 * cm]))
        scen_chart = _scenario_chart(r)
        if scen_chart:
            flow.append(Spacer(1, 10))
            flow.append(Image(BytesIO(scen_chart), width=13 * cm, height=7.31 * cm))

    interp(_value_interpretation(inp, r))

    if r.assumption_labels:
        h3("Assumption table — data origin per field")
        assum_data = [["Field", "Origin"]] + [[k, v] for k, v in sorted(r.assumption_labels.items())]
        flow.append(styled_table(assum_data, [9 * cm, 5 * cm]))

    body("<i>All figures are scenario-modeled from user-entered assumptions — not audited financials.</i>")

    # -------------------------------------------------------------- Roadmap
    flow.append(PageBreak())
    h2("Transformation roadmap")
    for p in state.roadmap:
        h3(p.phase)
        body(f"<b>Objectives:</b> {', '.join(p.objectives) or 'TBD'}")
        body(f"<b>Use cases:</b> {', '.join(p.use_cases) or 'TBD'}")
        body(f"<b>People:</b> {p.people} · <b>Process:</b> {p.process} · <b>Technology:</b> {p.technology}")
        body(f"<b>KPIs:</b> {', '.join(p.kpis) or 'TBD'}")

    # --------------------------------------------------- Target operating model
    h2("Target operating model")
    if state.target_operating_model:
        tom_data = [["Dimension", "Current state", "Target state", "Operating cadence"]]
        for b in state.target_operating_model:
            tom_data.append([b.dimension, b.current_state, b.target_state, b.operating_cadence])
        flow.append(styled_table(tom_data, [2.8 * cm, 3.8 * cm, 3.8 * cm, 3.6 * cm]))
    else:
        body("Not generated yet.")

    # ------------------------------------------------------------- Governance
    flow.append(PageBreak())
    h2("Governance &amp; risk")
    gov_hex = {"PASS": "#16A34A", "REVIEW": "#D97706", "BLOCK": "#DC2626"}.get(state.governance.status, "#6B7280")
    flow.append(Paragraph(f"<b>Status: <font color='{gov_hex}'>{state.governance.status}</font></b>", styles["Body"]))
    gov_data = [["Check", "Result"]] + [[k, v] for k, v in state.governance.checks.items()]
    flow.append(styled_table(gov_data, [4.5 * cm, 9.5 * cm]))
    if state.governance.reasons:
        h3("Reasons")
        for reason in state.governance.reasons:
            body(f"• {reason}")

    # ------------------------------------------------------------ Disclaimer
    h2("Data &amp; assumption disclaimer")
    body(
        "This report blends client-provided input, publicly retrieved web evidence, and deterministic AI-assisted "
        "analysis. Financial figures are illustrative and assumption-driven — see the Assumption Table above for "
        "the origin of every ROI field. Items marked 'Not found / requires validation' were not independently "
        "verifiable from available public sources at the time this report was generated. This is not an audited "
        "financial, legal, or investment document."
    )

    doc.build(flow, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
