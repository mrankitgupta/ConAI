import os
import sys
import tempfile
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env loader (no new dependency) — .env.example has documented
    this file's format since V2.1, but nothing actually read it until now.
    Only sets variables not already present in the real environment, so an
    explicit `export`/OS-level env var always wins over the .env file."""
    full_path = os.path.join(os.path.dirname(__file__), path)
    if not os.path.exists(full_path):
        return
    with open(full_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

from orchestration.state import EngagementState
from orchestration.graph import run_engagement, rerun_from, NODE_IDS
from orchestration.approval import sync_approval_state, approve as approve_fn, reject as reject_fn, is_send_eligible
from agents.context import AgentContext
from agents.lead_discovery import generate_leads
from agents.lead_qualification import qualify_lead, apply_human_override
from agents.client_communication import run as client_comm_run
from providers.llm.base import get_llm_provider
from providers.research.base import get_research_provider
from providers.vectorstore.base import get_vectorstore
from providers.database import base as db
from providers.email.base import is_smtp_configured
from utils.pdf_report import build_pdf
from utils.chart_layout import jitter_quadrant_points, tied_groups_note

st.set_page_config(page_title="ConAI — Sales Transformation Platform", page_icon=":material/diamond:", layout="wide")

# Visual design comes from .streamlit/config.toml (native theme tokens) rather
# than injected CSS — see AUDIT.md for why this replaced the old hand-rolled
# stylesheet. Badges/cards/empty-states below use native st.badge/st.container/
# st.info instead of custom HTML classes.
GOV_BADGE = {"PASS": ("green", ":material/check_circle:"), "REVIEW": ("orange", ":material/warning:"),
             "BLOCK": ("red", ":material/block:"), "NOT_RUN": ("gray", ":material/pending:")}
AGENT_BADGE = {"DONE": ("green", ":material/check_circle:"), "RUNNING": ("blue", ":material/sync:"),
               "FAILED": ("red", ":material/error:"), "PENDING": ("gray", ":material/pending:"),
               "SKIPPED": ("orange", ":material/skip_next:")}
LEAD_BADGE = {"HOT": ("red", ":material/local_fire_department:"), "WARM": ("orange", ":material/thermostat:"),
              "NURTURE": ("gray", ":material/eco:")}


def gov_badge(status: str):
    color, icon = GOV_BADGE.get(status, ("gray", ":material/help:"))
    st.badge(status, icon=icon, color=color)


def empty_state(message: str, icon: str = ":material/inbox:"):
    st.info(message, icon=icon)

# --------------------------------------------------------------- session ---
if "ctx" not in st.session_state:
    st.session_state.ctx = AgentContext(llm=get_llm_provider(), research=get_research_provider(), vectorstore=get_vectorstore())
if "current_engagement_id" not in st.session_state:
    st.session_state.current_engagement_id = None
if "leads" not in st.session_state:
    st.session_state.leads = []

ctx = st.session_state.ctx
db.init_db()


def current_state():
    if not st.session_state.current_engagement_id:
        return None
    return db.load_engagement(st.session_state.current_engagement_id)


def persist(state: EngagementState):
    db.save_engagement(state)


# ---------------------------------------------------------------- header ---
c1, c2 = st.columns([3, 2])
with c1:
    st.title("ConAI", icon=":material/diamond:")
    st.caption("AI-powered sales transformation, market intelligence, lead generation & proposal platform — from company intelligence to client-ready transformation.")
with c2:
    llm_ok = ctx.llm.name != "deterministic"
    research_ok = ctx.research.name != "none"
    st.write("")
    row = st.container(horizontal=True, horizontal_alignment="right")
    with row:
        st.badge(f"LLM: {ctx.llm.name if llm_ok else 'not configured'}", color="green" if llm_ok else "gray")
        st.badge(f"Web: {'on' if research_ok else 'off'}", color="green" if research_ok else "red")
        st.badge(f"RAG: {ctx.vectorstore.name}", color="blue")
        st.badge("DB: SQLite", color="green")
        st.badge(f"Email: {'SMTP' if is_smtp_configured() else 'dry-run'}", color="green" if is_smtp_configured() else "gray")

# ------------------------------------------------------------- sidebar nav -
PAGE_GROUPS = {
    "Command center": [("Overview", ":material/dashboard:"), ("Engagements", ":material/handshake:"), ("Leads", ":material/person_search:")],
    "Intelligence": [("Company Research", ":material/search:"), ("Market Intelligence", ":material/insights:"), ("Data Room", ":material/folder_open:")],
    "Transformation": [("Diagnosis", ":material/stethoscope:"), ("Opportunity Studio", ":material/lightbulb:"), ("Value Case", ":material/payments:"), ("Roadmap", ":material/map:"), ("Target Operating Model", ":material/hub:")],
    "Delivery": [("Proposal Studio", ":material/description:"), ("Approvals", ":material/verified:"), ("Client Email", ":material/mail:")],
    "AI system": [("Agent Control Center", ":material/smart_toy:")],
    "Admin": [("System Health", ":material/health_and_safety:"), ("Settings", ":material/settings:")],
}
ALL_PAGES = [p for group in PAGE_GROUPS.values() for p, _ in group]

with st.sidebar:
    st.markdown("**:material/diamond: ConAI**")
    if "page" not in st.session_state:
        st.session_state.page = "Overview"
    for group_name, pages in PAGE_GROUPS.items():
        st.caption(group_name.upper())
        for p, icon in pages:
            if st.button(p, key=f"navbtn_{p}", width="stretch", icon=icon,
                         type="primary" if st.session_state.page == p else "tertiary"):
                st.session_state.page = p
                # Without this, only buttons rendered AFTER this point in the loop
                # (in this same script run) would reflect the new active page —
                # buttons already drawn above it keep their stale highlight from
                # before the click, since nothing else forces a fresh top-to-bottom
                # rerun. Force one explicitly so every button's highlight is
                # computed from the final, consistent page value.
                st.rerun()
    st.divider()
    engagements = db.list_engagements()
    if engagements:
        labels = [f"{e['company_name']} ({e['status']})" for e in engagements]
        default_idx = 0
        if st.session_state.current_engagement_id:
            ids = [e["engagement_id"] for e in engagements]
            if st.session_state.current_engagement_id in ids:
                default_idx = ids.index(st.session_state.current_engagement_id)
        idx = st.selectbox("Active engagement", options=range(len(engagements)), format_func=lambda i: labels[i], index=default_idx)
        st.session_state.current_engagement_id = engagements[idx]["engagement_id"]
    else:
        st.caption("No engagements yet.")

page = st.session_state.page
s = current_state()

NO_HEADER_PAGES = {"Overview", "Engagements", "Leads", "System Health", "Settings"}


def render_engagement_header(state: EngagementState):
    """Persistent Engagement Workspace header — company/industry/region/status/
    transformation score/evidence confidence/data readiness/governance status,
    rendered once and shared across every engagement-scoped page instead of
    each page independently re-deriving its own subset of this context."""
    transformation_score = round(sum(o.priority_score for o in state.opportunities) / len(state.opportunities), 2) if state.opportunities else 0.0
    data_readiness = "HIGH" if state.documents.rag_chunks_indexed > 0 else ("MEDIUM" if state.company_profile.evidence else "LOW")
    approval_label = "APPROVED" if state.approval.is_current else ("INVALIDATED" if state.approval.approval_status == "INVALIDATED" else "PENDING")
    approval_color = "green" if state.approval.is_current else ("red" if state.approval.approval_status == "INVALIDATED" else "gray")
    with st.container(border=True):
        row = st.container(horizontal=True, vertical_alignment="center")
        with row:
            st.markdown(f"**{state.company_name}**")
            st.caption(f"{state.industry_hint or 'Industry not specified'} · {state.geography_hint or 'Region not specified'}")
            gov_badge(state.governance.status)
            st.badge(f"Approval: {approval_label}", color=approval_color)
            st.badge(f"Transformation {transformation_score}/5", color="blue")
            st.badge(f"Evidence {state.company_profile.research_quality}", color="gray")
            st.badge(f"Data readiness {data_readiness}", color="gray")


if s and page not in NO_HEADER_PAGES:
    render_engagement_header(s)

# ================================================================ OVERVIEW =
if page == "Overview":
    st.subheader("Command center", icon=":material/dashboard:")
    engs = db.list_engagements()
    leads_db = db.list_leads()
    hot_leads = [l for l in leads_db if l["classification"] == "HOT"]
    # Loading each engagement's full state is unavoidable with the current
    # SQLite schema (aggregates aren't pre-computed), but it's now done once
    # here via the EngagementRepository rather than scattered db.* calls.
    from providers.database.repositories import EngagementRepository
    engagement_repo = EngagementRepository()
    full_states = [engagement_repo.get(e["engagement_id"]) for e in engs]
    full_states = [st_e for st_e in full_states if st_e]
    total_value = sum(st_e.roi_outputs.total_annual_value_cr for st_e in full_states)
    pending_approval = sum(1 for st_e in full_states if st_e.governance.status == "PASS" and st_e.email_record.status != "SENT")
    governance_alerts = sum(1 for st_e in full_states if st_e.governance.status == "BLOCK")

    cols = st.columns(5)
    with cols[0]:
        st.metric("Active engagements", len(engs), border=True)
    with cols[1]:
        st.metric("Hot leads", len(hot_leads), border=True)
    with cols[2]:
        st.metric("Modeled value", f"₹{total_value:.1f} Cr", border=True)
    with cols[3]:
        st.metric("Awaiting approval", pending_approval, border=True)
    with cols[4]:
        st.metric("Governance alerts", governance_alerts, border=True, delta=None if governance_alerts == 0 else f"{governance_alerts} blocked", delta_color="inverse")

    if not engs:
        empty_state("No engagements yet. Start by researching a company in Engagements.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Engagement funnel", icon=":material/filter_alt:")
            stages = ["Created", "Diagnosed", "Opportunities found", "Proposal drafted", "Approved"]
            counts = [
                len(full_states),
                sum(1 for st_e in full_states if st_e.diagnosis.executive_diagnosis),
                sum(1 for st_e in full_states if st_e.opportunities),
                sum(1 for st_e in full_states if st_e.proposal_markdown),
                sum(1 for st_e in full_states if st_e.approval.is_current),
            ]
            fig_funnel = go.Figure(go.Funnel(
                y=stages, x=counts, marker={"color": ["#94A3B8", "#93A9FE", "#5B7CFC", "#3B5BFB", "#0B1E3A"]},
                textinfo="value+percent initial",
            ))
            fig_funnel.update_layout(height=340, plot_bgcolor="white", margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig_funnel, width="stretch")
            drop_off = counts[0] - counts[-1] if counts else 0
            if drop_off > 0:
                st.caption(f"{drop_off} of {counts[0]} engagement(s) haven't reached Approved yet — check Governance Alerts above for what's blocking them.")
        with c2:
            st.subheader("Value by engagement", icon=":material/payments:")
            val_df = pd.DataFrame({"Company": [st_e.company_name for st_e in full_states], "Value (₹Cr)": [st_e.roi_outputs.total_annual_value_cr for st_e in full_states]}).sort_values("Value (₹Cr)", ascending=True)
            fig_val = go.Figure(go.Bar(
                x=val_df["Value (₹Cr)"], y=val_df["Company"], orientation="h", marker_color="#3B5BFB",
                text=[f"₹{v:.1f}Cr" for v in val_df["Value (₹Cr)"]], textposition="outside",
            ))
            fig_val.update_layout(height=340, plot_bgcolor="white", margin=dict(l=10, r=10, t=10, b=10), xaxis_title="₹ Cr / year")
            st.plotly_chart(fig_val, width="stretch")
            if len(val_df) and val_df["Value (₹Cr)"].max() > 0:
                best = val_df.iloc[-1]
                st.caption(f"Highest modeled value: **{best['Company']}** at ₹{best['Value (₹Cr)']:.1f}Cr/year.")

        st.subheader("Recent engagements", icon=":material/history:")
        df = pd.DataFrame(engs)[["company_name", "industry", "status", "updated_at"]]
        st.dataframe(df, width="stretch", hide_index=True)

# ============================================================= ENGAGEMENTS =
elif page == "Engagements":
    st.subheader("Engagements", icon=":material/handshake:")
    with st.expander("Start new engagement", icon=":material/add_circle:", expanded=(s is None)):
        st.caption("Revenue and seller count drive the ROI business case — governance BLOCKs a proposal built on ₹0 inputs, so fill these in even as a rough estimate (you can refine them later in Value Case).")
        with st.form("engagement_form"):
            col1, col2 = st.columns(2)
            with col1:
                company = st.text_input("Company name *")
                industry = st.text_input("Industry (optional)")
                revenue_cr = st.number_input("Annual revenue (₹ Cr) *", min_value=0.0, value=500.0, step=10.0, help="Rough estimate is fine — this is a client assumption, clearly labeled as such throughout.")
            with col2:
                geography = st.text_input("Geography (optional)")
                scenario = st.selectbox("Default ROI scenario", ["Conservative", "Base", "Upside"], index=1)
                seller_count = st.number_input("Sales team size *", min_value=0, value=50, step=5)
            problem = st.text_area("Business challenge *", height=100)
            files = st.file_uploader("Optional documents (RFP, annual report, CRM export)", type=["pdf", "docx", "txt", "csv", "xlsx"], accept_multiple_files=True)
            submitted = st.form_submit_button("Start engagement", icon=":material/rocket_launch:", type="primary", width="stretch")

        if submitted:
            if not company.strip() or not problem.strip():
                st.error("Company name and business challenge are required.")
            elif revenue_cr <= 0 or seller_count <= 0:
                st.error("Annual revenue and sales team size must be greater than zero — governance will BLOCK a proposal with ₹0 financial inputs.")
            else:
                tmp_dir = tempfile.mkdtemp()
                saved_paths = []
                for f in files or []:
                    p = os.path.join(tmp_dir, f.name)
                    with open(p, "wb") as out:
                        out.write(f.getbuffer())
                    saved_paths.append(p)
                new_state = EngagementState(company_name=company.strip(), industry_hint=industry.strip(), geography_hint=geography.strip(), business_problem=problem.strip(), uploaded_file_paths=saved_paths)
                new_state.roi_inputs.scenario = scenario
                new_state.roi_inputs.annual_revenue_cr = revenue_cr
                new_state.roi_inputs.seller_count = seller_count
                st.session_state.ctx = AgentContext(llm=ctx.llm, research=ctx.research, vectorstore=get_vectorstore())
                with st.spinner("Agents researching, diagnosing, and building the business case..."):
                    result = run_engagement(new_state, st.session_state.ctx)
                persist(result)
                db.log_audit(result.engagement_id, "consultant", "ENGAGEMENT_CREATED", company)
                st.session_state.current_engagement_id = result.engagement_id
                st.success(f"Engagement created for {company}.")
                st.rerun()

    engs = db.list_engagements()
    if not engs:
        empty_state("No engagements yet. Use the form above to start one.")
    elif s:
        st.markdown(f"### {s.company_name}")
        c1, c2, c3, c4 = st.columns(4)
        c1.write(f"**Industry:** {s.industry_hint or '—'}")
        c2.write(f"**Region:** {s.geography_hint or '—'}")
        c3.write(f"**Created:** {s.created_at[:10]}")
        c4.write(f"**Governance:** {s.governance.status}")
        st.caption(f"Engagement ID: {s.engagement_id}")

# ========================================================= COMPANY RESEARCH
elif page == "Company Research":
    st.subheader("Company research", icon=":material/search:")
    if not s:
        empty_state("No active engagement. Create one first.")
    else:
        conf_color = {"HIGH": "green", "MEDIUM": "orange", "LOW": "gray"}.get(s.company_profile.research_quality, "gray")
        st.badge(f"Confidence: {s.company_profile.research_quality}", color=conf_color)
        st.write(s.company_profile.description)
        with st.expander("Evidence", icon=":material/library_books:"):
            if not s.company_profile.evidence:
                st.caption("No sourced evidence — web research unavailable or no results found.")
            for e in s.company_profile.evidence:
                row = st.container(horizontal=True, vertical_alignment="center")
                with row:
                    st.badge(e.confidence, color={"HIGH": "green", "MEDIUM": "orange", "LOW": "gray"}.get(e.confidence, "gray"))
                    st.write(f"{e.claim} — [{e.source}]({e.url})" if e.url else e.claim)
        if s.company_profile.recent_signals:
            st.subheader("Recent signals", icon=":material/notifications:")
            for sig in s.company_profile.recent_signals:
                st.write(f"- {sig}")

# ========================================================= MARKET INTEL ====
elif page == "Market Intelligence":
    st.subheader("Market intelligence", icon=":material/insights:")
    if not s:
        empty_state("No active engagement. Create one first.")
    else:
        st.write(f"**Market:** {s.market.market_definition}")
        st.write(f"**Growth:** {s.market.growth_note}")
        st.write(f"**AI adoption note:** {s.market.ai_adoption_note}")
        if s.market.key_trends:
            st.markdown("**Trend cards**")
            for t in s.market.key_trends:
                st.info(t)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Competitors**")
            if s.market.competitors:
                for comp in s.market.competitors:
                    st.write(f"- {comp}")
            else:
                st.caption("Not Found — no competitor names extracted from retrieved public snippets.")
            st.markdown("**Technology trends**")
            st.write(", ".join(s.market.technology_trends) or "Not Found")
        with c2:
            st.markdown("**Buying signals**")
            st.write(", ".join(s.market.buying_signals) or "Not Found")
            st.markdown("**Transformation triggers**")
            st.write(", ".join(s.market.transformation_triggers) or "Not Found")
        if s.market.strategic_implications:
            st.markdown("**Market signal → trigger → strategic implication**")
            for imp in s.market.strategic_implications:
                st.success(imp)

# ================================================================ DATA ROOM
elif page == "Data Room":
    st.subheader("Data room", icon=":material/folder_open:")
    if not s:
        empty_state("No active engagement. Create one first.")
    elif not s.documents.filenames:
        empty_state("No documents uploaded. Upload an RFP, annual report, proposal, or sales dataset when creating an engagement.", icon=":material/folder_off:")
    else:
        st.write(f"**RAG chunks indexed:** {s.documents.rag_chunks_indexed}")
        df = pd.DataFrame({"Document": s.documents.filenames})
        st.dataframe(df, width="stretch", hide_index=True)
        if s.documents.requirement_matrix:
            st.markdown("**Requirement matrix**")
            rows = s.documents.requirement_matrix
            mapped = [r for r in rows if not r.gap.startswith("Gap")]
            coverage_pct = round(100 * len(mapped) / len(rows), 1) if rows else 0.0
            critical_gaps = [r for r in rows if r.gap.startswith("Gap") and r.priority == "High"]
            manual_review = [r for r in rows if r.confidence == "LOW" or r.proposed_capability == "Not yet mapped"]
            c1, c2, c3 = st.columns(3)
            c1.metric("Requirement Coverage", f"{coverage_pct}%", help="Mapped requirements / total requirements")
            c2.metric("Critical Gaps", len(critical_gaps))
            c3.metric("Manual Review Required", len(manual_review))
            if critical_gaps:
                with st.expander("⚠️ Critical gaps"):
                    for r in critical_gaps:
                        st.write(f"- **{r.req_id}**: {r.requirement} — {r.gap}")
            df_rows = pd.DataFrame([r.model_dump() for r in rows])
            df_rows["page_or_section"] = df_rows["page_or_section"].fillna("Not Found")
            st.dataframe(df_rows, width="stretch")

# ================================================================= DIAGNOSIS
elif page == "Diagnosis":
    st.subheader("Sales diagnosis", icon=":material/stethoscope:")
    if not s:
        empty_state("No active engagement. Create one first.")
    else:
        st.write(s.diagnosis.executive_diagnosis)
        st.markdown("**Hypothesis tree**")
        for h in s.diagnosis.hypothesis_tree:
            prefix = "&nbsp;&nbsp;&nbsp;&nbsp;↳ " if h.parent else "🌳 "
            st.markdown(f"{prefix}**{h.label}** · impact: *{h.impact}* · confidence: *{h.confidence}* — {h.evidence}", unsafe_allow_html=True)

# ========================================================= OPPORTUNITY STUDIO
elif page == "Opportunity Studio":
    st.subheader("Opportunity studio", icon=":material/lightbulb:")
    if not s:
        empty_state("No active engagement. Create one first.")
    elif not s.opportunities:
        empty_state("No opportunities generated yet.", icon=":material/lightbulb:")
    else:
        def _quadrant(o):
            if o.feasibility >= 3 and o.business_value >= 3:
                return "Quick win", "#16A34A"
            if o.feasibility < 3 and o.business_value >= 3:
                return "Strategic", "#3B5BFB"
            if o.feasibility >= 3 and o.business_value < 3:
                return "Validate", "#D97706"
            return "Long term", "#6B7280"

        fig = go.Figure()
        # Quadrant background shading so the categories read at a glance.
        fig.add_shape(type="rect", x0=3, x1=6, y0=3, y1=6, fillcolor="#16A34A", opacity=0.06, line_width=0)
        fig.add_shape(type="rect", x0=0, x1=3, y0=3, y1=6, fillcolor="#3B5BFB", opacity=0.06, line_width=0)
        fig.add_shape(type="rect", x0=3, x1=6, y0=0, y1=3, fillcolor="#D97706", opacity=0.06, line_width=0)
        fig.add_shape(type="rect", x0=0, x1=3, y0=0, y1=3, fillcolor="#6B7280", opacity=0.06, line_width=0)
        for label, x, y, color in [("QUICK WIN", 4.5, 5.7, "#16A34A"), ("STRATEGIC", 1.5, 5.7, "#3B5BFB"),
                                    ("VALIDATE", 4.5, 0.3, "#D97706"), ("LONG TERM", 1.5, 0.3, "#6B7280")]:
            fig.add_annotation(x=x, y=y, text=f"<b>{label}</b>", showarrow=False, font=dict(size=10, color=color))

        # Opportunities are scored on coarse 1-5 integer scales, so it's
        # common for several to land on the exact same (feasibility,
        # business_value) point — plotted naively their markers and text
        # labels stack exactly on top of each other and become unreadable.
        # jitter_quadrant_points spreads exact ties around a small circle
        # for display only; hover text still shows each item's real score.
        for pt in jitter_quadrant_points(s.opportunities):
            o = pt["item"]
            quadrant_label, color = _quadrant(o)
            fig.add_trace(go.Scatter(
                x=[pt["x"]], y=[pt["y"]], mode="markers+text",
                marker=dict(size=22 + o.priority_score * 8, color=color, opacity=0.8, line=dict(width=1.5, color="#0B1E3A")),
                text=[o.name], textposition="top center" if pt["label_above"] else "bottom center", textfont=dict(size=10),
                hovertemplate=f"<b>{o.name}</b><br>Category: {quadrant_label}<br>Business value: {o.business_value}<br>"
                              f"Feasibility: {o.feasibility}<br>Priority score: {o.priority_score}<br>"
                              f"Time to value: {o.time_to_value_months} mo<extra></extra>",
                name=quadrant_label, showlegend=False,
            ))
        fig.update_layout(
            xaxis=dict(title="Feasibility", range=[0, 6], gridcolor="#F1F5F9"),
            yaxis=dict(title="Business value", range=[0, 6], gridcolor="#F1F5F9"),
            showlegend=False, height=480, plot_bgcolor="white",
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig, width="stretch")

        quick_wins = [o for o in s.opportunities if o.feasibility >= 3 and o.business_value >= 3]
        strategic = [o for o in s.opportunities if o.feasibility < 3 and o.business_value >= 3]
        top = max(s.opportunities, key=lambda o: o.priority_score)
        note = tied_groups_note(s.opportunities)
        st.info(
            f"**Interpretation:** Of {len(s.opportunities)} opportunities identified, **{len(quick_wins)}** are Quick Wins "
            f"(high feasibility, high value) and **{len(strategic)}** are Strategic bets (high value, needs more groundwork). "
            f"Highest-priority: **{top.name}** (score {top.priority_score}/5) — {top.problem}"
            + (f"\n\n{note}" if note else ""),
            icon=":material/insights:",
        )

        for o in sorted(s.opportunities, key=lambda x: x.priority_score, reverse=True):
            quadrant_label, _ = _quadrant(o)
            with st.expander(f"{o.name} — priority {o.priority_score} · {quadrant_label}", icon=":material/lightbulb:"):
                row = st.container(horizontal=True)
                with row:
                    st.badge(quadrant_label, color={"Quick win": "green", "Strategic": "blue", "Validate": "orange", "Long term": "gray"}[quadrant_label])
                    st.badge(f"Risk: {o.risk}", color={"Low": "green", "Medium": "orange", "High": "red"}.get(o.risk, "gray"))
                    st.badge(f"Time to value: {o.time_to_value_months} mo", color="gray")
                st.write(f"**Problem:** {o.problem}")
                st.write(f"**Solution:** {o.solution}")
                st.write(f"**Required data:** {', '.join(o.required_data)}")
                st.write(f"**KPIs:** {', '.join(o.kpis)}")
                if o.dependencies:
                    st.write(f"**Dependencies:** {', '.join(o.dependencies)}")

# ================================================================= VALUE ===
elif page == "Value Case":
    st.subheader("Value case", icon=":material/payments:")
    if not s:
        empty_state("No active engagement. Create one first.")
    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            s.roi_inputs.annual_revenue_cr = st.number_input("Annual revenue (₹ Cr)", min_value=0.0, value=float(s.roi_inputs.annual_revenue_cr or 500.0), step=10.0)
            s.roi_inputs.seller_count = st.number_input("Sellers", min_value=0, value=int(s.roi_inputs.seller_count or 80), step=5)
        with c2:
            s.roi_inputs.fully_loaded_seller_cost_lakh = st.number_input("Fully-loaded seller cost (₹L/yr)", min_value=0.0, value=float(s.roi_inputs.fully_loaded_seller_cost_lakh), step=1.0)
            s.roi_inputs.conversion_uplift_pct = st.slider("Conversion uplift %", 0.0, 30.0, float(s.roi_inputs.conversion_uplift_pct))
        with c3:
            s.roi_inputs.productivity_gain_pct = st.slider("Productivity gain %", 0.0, 40.0, float(s.roi_inputs.productivity_gain_pct))
            s.roi_inputs.implementation_cost_cr = st.number_input("Implementation investment (₹ Cr)", min_value=0.1, value=float(s.roi_inputs.implementation_cost_cr), step=0.1)
        s.roi_inputs.scenario = st.select_slider("Scenario", options=["Conservative", "Base", "Upside"], value=s.roi_inputs.scenario)

        if st.button("Recalculate", icon=":material/calculate:", help="Targeted re-run from Value/ROI onward", type="primary", width="stretch"):
            s = rerun_from(s, "value_roi", ctx)
            persist(s)
            db.log_audit(s.engagement_id, "consultant", "RERUN", "value_roi -> downstream")
            st.rerun()

        r = s.roi_outputs
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Annual value", f"₹{r.total_annual_value_cr} Cr", border=True)
        c2.metric("3-yr value", f"₹{r.three_year_value_cr} Cr", border=True)
        c3.metric("ROI", f"{r.roi_pct}%", border=True)
        c4.metric("Payback", f"{r.payback_months} mo", border=True,
                  delta="within 12mo" if 0 < r.payback_months <= 12 else None, delta_color="normal")

        fig = go.Figure(go.Waterfall(
            orientation="v", measure=["relative", "relative", "relative", "total"],
            x=["Conversion\nuplift", "Productivity\ngain", "Cost\nsavings", "Total\nannual value"],
            y=[r.incremental_revenue_cr, r.productivity_value_cr, r.cost_savings_cr, 0],
            text=[f"₹{v}Cr" for v in [r.incremental_revenue_cr, r.productivity_value_cr, r.cost_savings_cr, r.total_annual_value_cr]],
            textposition="outside",
            increasing={"marker": {"color": "#3B5BFB"}}, totals={"marker": {"color": "#0B1E3A"}},
            connector={"line": {"color": "#E5E7EB"}},
        ))
        fig.update_layout(height=420, plot_bgcolor="white", margin=dict(l=10, r=10, t=40, b=10),
                           title=f"Value waterfall — {s.roi_inputs.scenario} scenario (₹ Cr/yr)", yaxis_title="₹ Cr / year")
        st.plotly_chart(fig, width="stretch")
        st.caption("All figures are user-entered assumptions, scenario-modeled — not audited financials.")

        payback_note = "well within" if 0 < r.payback_months <= 12 else "beyond"
        st.info(
            f"**Interpretation:** Under the {s.roi_inputs.scenario} scenario, the program models ₹{r.total_annual_value_cr}Cr in "
            f"annual value against ₹{s.roi_inputs.implementation_cost_cr}Cr investment — payback in ~{r.payback_months} months, "
            f"{payback_note} a typical 12-month evaluation window." if r.total_annual_value_cr > 0 else
            "**Interpretation:** ROI inputs are still at defaults — adjust revenue/sellers above and Recalculate to see a real business case.",
            icon=":material/insights:",
        )

        if r.scenarios:
            st.markdown("**Scenario comparison**")
            comp_df = pd.DataFrame([
                {"Scenario": name, "Annual Value (₹Cr)": v.total_annual_value_cr, "3-Yr Value (₹Cr)": v.three_year_value_cr,
                 "ROI %": v.roi_pct, "Payback (mo)": v.payback_months}
                for name in ["Conservative", "Base", "Upside"] if name in r.scenarios
                for v in [r.scenarios[name]]
            ])
            st.dataframe(comp_df, width="stretch", hide_index=True)
            fig2 = go.Figure(go.Bar(
                x=comp_df["Scenario"], y=comp_df["Annual Value (₹Cr)"], marker_color=["#94A3B8", "#3B5BFB", "#0B1E3A"],
                text=[f"₹{v:.1f}Cr" for v in comp_df["Annual Value (₹Cr)"]], textposition="outside",
            ))
            fig2.update_layout(height=320, plot_bgcolor="white", margin=dict(l=10, r=10, t=10, b=10),
                                title="Annual value by scenario (₹ Cr)", yaxis_title="₹ Cr / year")
            st.plotly_chart(fig2, width="stretch")
            if "Conservative" in r.scenarios and "Upside" in r.scenarios:
                spread = r.scenarios["Upside"].total_annual_value_cr - r.scenarios["Conservative"].total_annual_value_cr
                st.caption(f"Range across scenarios: ₹{spread:.1f}Cr — the Upside case assumes stronger conversion/productivity gains than Base.")

        if r.sensitivity_matrix:
            with st.expander("Sensitivity matrix (conversion uplift × productivity gain)", icon=":material/grid_on:"):
                sens_df = pd.DataFrame(r.sensitivity_matrix)
                pivot = sens_df.pivot(index="productivity_gain_pct", columns="conversion_uplift_pct", values="total_annual_value_cr")
                fig3 = go.Figure(go.Heatmap(
                    z=pivot.values, x=[f"{c}%" for c in pivot.columns], y=[f"{i}%" for i in pivot.index],
                    colorscale=[[0, "#EFF3FF"], [0.5, "#93A9FE"], [1, "#0B1E3A"]],
                    text=[[f"₹{v:.1f}Cr" for v in row] for row in pivot.values], texttemplate="%{text}", textfont=dict(size=10),
                    colorbar=dict(title="₹Cr"),
                ))
                fig3.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10),
                                    xaxis_title="Conversion uplift %", yaxis_title="Productivity gain %")
                st.plotly_chart(fig3, width="stretch")
                st.caption("Darker cells = higher modeled annual value. Use this to show the client how sensitive the business case is to each driver.")

        if r.assumption_labels:
            with st.expander("Assumption table — data origin per field", icon=":material/label:"):
                labels_df = pd.DataFrame(sorted(r.assumption_labels.items()), columns=["Field", "Origin"])
                st.dataframe(labels_df, width="stretch", hide_index=True)

# =============================================================== ROADMAP ===
elif page == "Roadmap":
    st.subheader("Transformation roadmap", icon=":material/map:")
    if not s or not s.roadmap:
        empty_state("No roadmap yet.", icon=":material/map:")
    else:
        tabs = st.tabs([p.phase for p in s.roadmap])
        for t, p in zip(tabs, s.roadmap):
            with t:
                st.write(f"**Objectives:** {', '.join(p.objectives)}")
                st.write(f"**Use cases:** {', '.join(p.use_cases) or 'TBD'}")
                cols = st.columns(3)
                cols[0].write(f"**People:** {p.people}")
                cols[1].write(f"**Process:** {p.process}")
                cols[2].write(f"**Technology:** {p.technology}")
                st.write(f"**KPIs:** {', '.join(p.kpis)}")

# ==================================================== TARGET OPERATING MODEL
elif page == "Target Operating Model":
    st.subheader("Target operating model", icon=":material/hub:")
    if not s or not s.target_operating_model:
        empty_state("Not generated yet.", icon=":material/hub:")
    else:
        for b in s.target_operating_model:
            with st.expander(b.dimension, expanded=True):
                st.write(f"**Current state:** {b.current_state}")
                st.write(f"**Target state:** {b.target_state}")
                st.write(f"**Operating cadence:** {b.operating_cadence}")

# ================================================================= LEADS ====
elif page == "Leads":
    st.subheader("Lead discovery & qualification", icon=":material/person_search:")
    st.caption("Company-level discovery only. No personal contact data is scraped or fabricated.")
    c1, c2, c3 = st.columns(3)
    ind = c1.text_input("Industry")
    geo = c2.text_input("Geography")
    challenge = c3.text_input("Business challenge / AI opportunity")
    if st.button("Find & qualify candidates", icon=":material/search:", width="stretch", type="primary"):
        with st.spinner("Searching public sources..."):
            leads = generate_leads(ind, geo, challenge, ctx)
            leads = [qualify_lead(l) for l in leads]
        st.session_state.leads = leads
        if not leads:
            st.warning("No candidates found — web research may be unavailable, or try broader terms.")

    if st.session_state.leads:
        for i, lead in enumerate(st.session_state.leads):
            badge_color, badge_icon = LEAD_BADGE[lead.classification]
            with st.container(border=True):
                row = st.container(horizontal=True, vertical_alignment="center")
                with row:
                    st.markdown(f"**{lead.company}**")
                    st.badge(lead.classification, icon=badge_icon, color=badge_color)
                    st.caption(f"score: {lead.overall_score}")
                st.caption(f"{lead.why_now} · {lead.evidence}")
                c1, c2, c3 = st.columns(3)
                if c1.button("Save lead", icon=":material/bookmark:", key=f"save_{i}"):
                    db.save_lead(lead)
                    st.toast("Lead saved")
                if c2.button("Create engagement", icon=":material/handshake:", key=f"eng_{i}"):
                    new_state = EngagementState(company_name=lead.company, industry_hint=lead.industry, business_problem=lead.trigger)
                    result = run_engagement(new_state, ctx)
                    persist(result)
                    st.session_state.current_engagement_id = result.engagement_id
                    st.success(f"Engagement created for {lead.company}.")
                    st.info("Governance will show BLOCK until you enter real revenue/seller estimates in **Value Case** — public lead data never includes a company's financials, so this starts at ₹0 by design, not as an error.")
                override = c3.selectbox("Override", ["—", "HOT", "WARM", "NURTURE"], key=f"ov_{i}")
                if override != "—" and override != lead.classification:
                    reason = st.text_input("Override reason", key=f"reason_{i}")
                    if st.button("Apply override", key=f"applyov_{i}") and reason:
                        st.session_state.leads[i] = apply_human_override(lead, override, reason)
                        st.toast("Override applied")
    else:
        empty_state("No leads yet. Define an ICP above to discover prospects.", icon=":material/person_search:")

# ========================================================== PROPOSAL STUDIO
elif page == "Proposal Studio":
    st.subheader("Proposal studio", icon=":material/description:")
    if not s:
        empty_state("No active engagement. Create one first.")
    else:
        approval_label = "APPROVED — CURRENT" if s.approval.is_current else ("INVALIDATED — PROPOSAL CHANGED" if s.approval.approval_status == "INVALIDATED" else "NOT YET APPROVED")
        approval_color = "green" if s.approval.is_current else ("red" if s.approval.approval_status == "INVALIDATED" else "gray")
        c1, c2 = st.columns(2)
        with c1:
            st.write("**Governance**")
            gov_badge(s.governance.status)
        with c2:
            st.write("**Approval**")
            st.badge(approval_label, color=approval_color)
        st.caption(f"Proposal version {s.approval.proposal_version} · hash `{s.approval.proposal_hash}`")
        with st.expander("Governance checks", icon=":material/checklist:"):
            for k, v in s.governance.checks.items():
                st.write(f"- {k}: {v}")
        edited = st.text_area("Proposal (editable — your edits are preserved, not auto-overwritten)", value=s.proposal_markdown, height=500)
        if st.button("Save edits", icon=":material/save:", type="primary"):
            s.proposal_markdown = edited
            s = sync_approval_state(s)  # any edit re-hashes the proposal; a prior approval is invalidated if the text actually changed
            persist(s)
            db.log_audit(s.engagement_id, "consultant", "PROPOSAL_EDITED", f"new_hash={s.approval.proposal_hash}")
            st.success("Saved." + (" Note: this invalidated the existing approval — re-approve before sending." if s.approval.approval_status == "INVALIDATED" else ""))
            st.rerun()

# =============================================================== APPROVALS =
elif page == "Approvals":
    st.subheader("Approvals", icon=":material/verified:")
    if not s:
        empty_state("No active engagement. Create one first.")
    else:
        s = sync_approval_state(s)
        row = st.container(horizontal=True, vertical_alignment="center")
        with row:
            st.write("**Governance status:**")
            gov_badge(s.governance.status)
        if s.governance.status == "BLOCK":
            st.error("BLOCKED — client-ready PDF and email are disabled until governance passes.", icon=":material/block:")
            for r in s.governance.reasons:
                st.write(f"- {r}")

        approval_label = "APPROVED — CURRENT" if s.approval.is_current else ("INVALIDATED — PROPOSAL CHANGED" if s.approval.approval_status == "INVALIDATED" else "NOT YET APPROVED")
        approval_color = "green" if s.approval.is_current else ("red" if s.approval.approval_status == "INVALIDATED" else "gray")
        row2 = st.container(horizontal=True, vertical_alignment="center")
        with row2:
            st.write("**Approval status:**")
            st.badge(approval_label, color=approval_color)
        if s.approval.approved_at:
            st.caption(f"Last approved by {s.approval.approved_by} at {s.approval.approved_at} (proposal v{s.approval.proposal_version}, hash `{s.approval.approved_proposal_hash}`)")

        c1, c2, c3 = st.columns(3)
        if c1.button("Approve for client", icon=":material/verified:", type="primary", width="stretch", disabled=(s.governance.status == "BLOCK")):
            s, ok, msg = approve_fn(s)
            persist(s)
            db.record_approval(s.engagement_id, "proposal", "APPROVED" if ok else "APPROVE_FAILED")
            db.log_audit(s.engagement_id, "consultant", "APPROVAL", f"{msg} hash={s.approval.approved_proposal_hash}")
            st.success(msg) if ok else st.error(msg)
            st.rerun()
        if c2.button("Request changes", icon=":material/edit_note:", width="stretch"):
            db.record_approval(s.engagement_id, "proposal", "CHANGES_REQUESTED")
            st.info("Marked for changes.")
        if c3.button("Reject", icon=":material/cancel:", width="stretch"):
            s = reject_fn(s)
            persist(s)
            db.record_approval(s.engagement_id, "proposal", "REJECTED")
            st.rerun()

        eligible, reason = is_send_eligible(s)
        if eligible:
            pdf_bytes = build_pdf(s)
            st.download_button("Download client PDF", icon=":material/download:", data=pdf_bytes, file_name=f"ConAI_{s.company_name.replace(' ','_')}.pdf", mime="application/pdf")
        else:
            st.caption(f"PDF locked: {reason}")

        st.subheader("Audit trail", icon=":material/history_edu:")
        logs = db.list_audit(s.engagement_id)
        if logs:
            st.dataframe(pd.DataFrame(logs), width="stretch", hide_index=True)
        else:
            st.caption("No audit events yet.")

# ============================================================= CLIENT EMAIL
elif page == "Client Email":
    st.subheader("Client email", icon=":material/mail:")
    if not s:
        empty_state("No active engagement. Create one first.")
    else:
        eligible, reason = is_send_eligible(s)
        if not eligible:
            empty_state(f"Email locked: {reason} Approve the current proposal in Approvals first.", icon=":material/lock:")
        else:
            to_addr = st.text_input("Recipient email")
            subject = st.text_input("Subject", value=f"Sales Transformation Proposal — {s.company_name}")
            body = st.text_area("Message", value=f"Dear team,\n\nPlease find attached our ConAI sales transformation assessment for {s.company_name}.\n\nBest regards,")
            st.caption("SMTP configured" if is_smtp_configured() else "SMTP not configured — sending will run in DRY RUN mode (no email actually sent).")
            if st.button("Send", icon=":material/send:", type="primary", width="stretch"):
                pdf_bytes = build_pdf(s)
                s = client_comm_run(s, ctx, to_addr=to_addr, subject=subject, body=body, pdf_bytes=pdf_bytes)
                persist(s)
                result_status = s.email_record.status
                if result_status == "SENT":
                    st.success(s.email_record.detail)
                elif result_status == "DRY_RUN":
                    st.warning(s.email_record.detail)
                else:
                    st.error(s.email_record.detail)

# ===================================================== AGENT CONTROL CENTER
elif page == "Agent Control Center":
    st.subheader("Agent control center", icon=":material/smart_toy:")
    if not s:
        empty_state("No active engagement. Create one first.")
    else:
        for name, run in s.agent_runs.items():
            badge_color, badge_icon = AGENT_BADGE.get(run.status, ("gray", ":material/help:"))
            with st.container(border=True):
                row = st.container(horizontal=True, vertical_alignment="center")
                with row:
                    st.markdown(f"**{name}**")
                    st.badge(run.status, icon=badge_icon, color=badge_color)
                st.caption(f"{run.started_at or ''} → {run.ended_at or ''}")
                st.write(run.reasoning_summary)
                if run.tools_used:
                    st.caption(f"Tools: {', '.join(run.tools_used)}")
                if run.errors:
                    st.error(" | ".join(run.errors), icon=":material/warning:")
        st.subheader("Targeted re-run", icon=":material/replay:")
        node_choice = st.selectbox("Re-run from", NODE_IDS, format_func=lambda n: n.replace("_", " ").title())
        if st.button("Re-run and everything downstream", icon=":material/replay:", type="primary"):
            s = rerun_from(s, node_choice, ctx)
            persist(s)
            db.log_audit(s.engagement_id, "consultant", "TARGETED_RERUN", node_choice)
            st.success(f"Re-ran {node_choice} and downstream agents. Any existing approval was invalidated if the proposal content changed.")
            st.rerun()

        if s.supervisor_log:
            st.subheader("Supervisor decision log", icon=":material/route:")
            sup_df = pd.DataFrame([d.model_dump() for d in s.supervisor_log])
            st.dataframe(sup_df[["node", "decision", "next_node", "iteration_count", "reason"]], width="stretch", hide_index=True)

        st.markdown("**Tool call telemetry** (from database — not fabricated)")
        telemetry = db.list_tool_telemetry(s.engagement_id)
        if telemetry:
            cols = [c for c in ["agent_name", "tool_name", "success", "duration_ms", "input_summary", "output_summary", "source_urls", "error", "timestamp"] if c in pd.DataFrame(telemetry).columns]
            st.dataframe(pd.DataFrame(telemetry)[cols], width="stretch", hide_index=True)
        else:
            st.caption("No tool calls recorded yet for this engagement.")

# =============================================================== SYS HEALTH
elif page == "System Health":
    st.subheader("System health", icon=":material/health_and_safety:")
    def status_row(label, ok, detail=""):
        st.write(f"**{label}:** {'🟢 AVAILABLE' if ok else '🟡 NOT CONFIGURED'} {detail}")
    status_row("Database (SQLite)", True, f"— {db.DB_PATH}")
    status_row("LLM", ctx.llm.name != "deterministic", f"— provider: {ctx.llm.name}")
    status_row("Web Research", ctx.research.name != "none", f"— provider: {ctx.research.name}")
    status_row("RAG", True, f"— backend: {ctx.vectorstore.name}, {ctx.vectorstore.size} chunks in current session")
    status_row("PDF (ReportLab)", True)
    status_row("Email (SMTP)", is_smtp_configured(), "— dry-run otherwise")
    if st.button("Run Diagnostics"):
        try:
            db.init_db()
            st.success("Database: OK")
        except Exception as e:
            st.error(f"Database: {e}")
        try:
            build_pdf(EngagementState(company_name="Diagnostic Test", business_problem="test"))
            st.success("PDF generation: OK")
        except Exception as e:
            st.error(f"PDF generation: {e}")

# =================================================================== SETTINGS
elif page == "Settings":
    st.subheader("Settings", icon=":material/settings:")
    st.caption("Configured providers (secrets never displayed).")
    st.write(f"**LLM:** {ctx.llm.name}")
    st.write(f"**Web research:** {ctx.research.name}")
    st.write(f"**RAG backend:** {ctx.vectorstore.name}")
    st.write(f"**Email:** {'SMTP configured' if is_smtp_configured() else 'Not configured (dry-run)'}")
    st.write(f"**Database:** SQLite at `{db.DB_PATH}`")
    st.info("Change providers via environment variables — see .env.example. Restart the app after changing secrets.")
