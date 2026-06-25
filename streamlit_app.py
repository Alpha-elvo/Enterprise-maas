"""
streamlit_app.py — Enterprise Decision Intelligence Platform
=============================================================
Run with:  streamlit run streamlit_app.py
Requires:  pip install -r requirements.txt  and  GROQ_API_KEY in .env
"""

import json
import sys
from pathlib import Path

# ── Path bootstrap (allows running from project root) ─────────────────────────
ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import config
from core.models import RoutingDecision, OrchestratorRun
from storage.database import Database

# ── Page configuration (must be first Streamlit call) ────────────────────────
st.set_page_config(
    page_title="Decision Intelligence Platform",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"About": "Enterprise Multi-Agent Decision Intelligence Platform v2.0"},
)

# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL CSS — Professional dark UI with Inter font
# ══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

html, body, [class*="css"], .stApp {
    font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
}

/* Hide Streamlit chrome */
#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }
header    { visibility: hidden; }

/* Sidebar */
[data-testid="stSidebar"] {
    background: #0f172a !important;
    border-right: 1px solid #1e293b !important;
}
[data-testid="stSidebar"] * { color: #e2e8f0 !important; }
[data-testid="stSidebar"] .stSelectbox label { color: #94a3b8 !important; }

/* Main area */
.stApp { background: #0d1117; }
.main .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }

/* KPI card */
.kpi-card {
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    border: 1px solid #334155;
    border-radius: 14px;
    padding: 22px 20px;
    text-align: center;
    margin-bottom: 12px;
    transition: border-color 0.2s;
}
.kpi-card:hover { border-color: #6366f1; }
.kpi-value {
    font-size: 2.4rem;
    font-weight: 800;
    color: #f1f5f9;
    line-height: 1;
    margin-bottom: 4px;
}
.kpi-label {
    font-size: 0.75rem;
    font-weight: 600;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}
.kpi-delta { font-size: 0.8rem; font-weight: 500; margin-top: 4px; }
.kpi-up   { color: #10b981; }
.kpi-down { color: #ef4444; }

/* Section header */
.section-header {
    font-size: 1.15rem;
    font-weight: 700;
    color: #e2e8f0;
    border-left: 4px solid #6366f1;
    padding-left: 12px;
    margin: 24px 0 16px 0;
    line-height: 1.3;
}

/* Risk badge */
.badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
}
.badge-CRITICAL { background:#450a0a; color:#fca5a5; border:1px solid #ef4444; }
.badge-HIGH     { background:#431407; color:#fdba74; border:1px solid #f97316; }
.badge-MEDIUM   { background:#172554; color:#93c5fd; border:1px solid #3b82f6; }
.badge-LOW      { background:#052e16; color:#86efac; border:1px solid #22c55e; }
.badge-UNKNOWN  { background:#1e293b; color:#94a3b8; border:1px solid #475569; }

/* Escalation card */
.esc-card {
    background: #1e293b;
    border-left: 4px solid #ef4444;
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 10px;
}
.esc-card-title { font-size: 0.95rem; font-weight: 700; color: #f1f5f9; }
.esc-card-body  { font-size: 0.82rem; color: #94a3b8; margin-top: 4px; line-height: 1.5; }
.esc-card-action {
    font-size: 0.78rem; color: #6366f1; font-weight: 600;
    margin-top: 8px; border-top: 1px solid #334155; padding-top: 8px;
}

/* Timeline dot */
.timeline-dot {
    display: inline-block;
    width: 10px; height: 10px;
    border-radius: 50%;
    margin-right: 8px;
    vertical-align: middle;
}

/* Agent status */
.agent-row {
    display: flex;
    align-items: center;
    padding: 8px 0;
    border-bottom: 1px solid #1e293b;
    font-size: 0.82rem;
    color: #cbd5e1;
}
.agent-name { flex: 1; font-weight: 500; }
.agent-ok   { color: #10b981; font-weight: 600; }
.agent-fail { color: #ef4444; font-weight: 600; }
.agent-skip { color: #475569; }

/* Input card */
.input-card {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 10px;
}
.input-card-header { font-weight: 700; color: #e2e8f0; margin-bottom: 6px; }
.input-card-body   { font-size: 0.8rem; color: #94a3b8; line-height: 1.6; }

/* Divider */
hr.styled {
    border: none;
    border-top: 1px solid #1e293b;
    margin: 16px 0;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE BOOTSTRAP
# ══════════════════════════════════════════════════════════════════════════════
def _init_session() -> None:
    defaults = {
        "run_result":   None,     # OrchestratorRun from last execution
        "active_page":  "Dashboard",
        "api_key_set":  config.is_api_configured(),
        "tenant_id":    config.DEFAULT_TENANT,
        "run_history":  [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_session()
db = Database()


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
def render_sidebar() -> None:
    with st.sidebar:
        # Brand
        st.markdown("""
        <div style="padding:16px 0 20px 0;">
            <div style="font-size:1.4rem;font-weight:800;color:#f1f5f9;">
                🧠 DecisionIQ
            </div>
            <div style="font-size:0.72rem;color:#64748b;margin-top:2px;letter-spacing:0.06em;">
                ENTERPRISE INTELLIGENCE PLATFORM
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("<hr style='border-color:#1e293b;margin:0 0 16px 0;'>", unsafe_allow_html=True)

        # Navigation
        pages = {
            "Dashboard":       "📊",
            "Run Analysis":    "⚡",
            "Reports":         "📄",
            "Audit Trail":     "🔍",
            "System Health":   "💚",
            "Settings":        "⚙️",
        }
        for page, icon in pages.items():
            active = st.session_state.active_page == page
            if st.button(
                f"{icon}  {page}",
                key=f"nav_{page}",
                use_container_width=True,
                type="primary" if active else "secondary",
            ):
                st.session_state.active_page = page
                st.rerun()

        st.markdown("<hr style='border-color:#1e293b;margin:16px 0;'>", unsafe_allow_html=True)

        # API status indicator
        if st.session_state.api_key_set:
            st.markdown(
                "<div style='font-size:0.78rem;color:#10b981;'>● API Connected</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='font-size:0.78rem;color:#ef4444;'>● API Key Required</div>",
                unsafe_allow_html=True,
            )
            st.caption("Go to Settings to configure.")

        # Model info
        st.markdown(
            f"<div style='font-size:0.72rem;color:#475569;margin-top:8px;'>"
            f"Model: {config.MODEL_ID}<br>"
            f"Gate: Score ≥ {config.HIGH_IMPACT_THRESHOLD}<br>"
            f"v{config.APP_VERSION}</div>",
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
def render_dashboard() -> None:
    st.markdown(
        "<h1 style='color:#f1f5f9;font-weight:800;margin-bottom:4px;'>Decision Intelligence Dashboard</h1>"
        "<p style='color:#64748b;margin-top:0;font-size:0.9rem;'>Real-time multi-domain agentic analysis</p>",
        unsafe_allow_html=True,
    )

    # ── KPI Row ───────────────────────────────────────────────────────────────
    stats = db.get_run_statistics(st.session_state.tenant_id)
    run   = st.session_state.run_result

    col1, col2, col3, col4, col5 = st.columns(5)
    kpis = [
        (col1, stats.get("total_runs", 0),       "Total Runs",        "#6366f1"),
        (col2, stats.get("total_records", 0),     "Records Analysed",  "#3b82f6"),
        (col3, stats.get("total_escalated", 0),   "Escalations",       "#f59e0b"),
        (col4, stats.get("total_errors", 0),      "Errors",            "#ef4444"),
        (col5, f"{stats.get('total_tokens',0):,}", "Tokens Used",      "#10b981"),
    ]
    for col, val, label, color in kpis:
        with col:
            st.markdown(
                f"<div class='kpi-card'>"
                f"<div class='kpi-value' style='color:{color};'>{val}</div>"
                f"<div class='kpi-label'>{label}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # ── Charts Row ────────────────────────────────────────────────────────────
    history = db.get_domain_score_history(st.session_state.tenant_id)

    if run:
        from services.report_generator import ReportGenerator
        rg      = ReportGenerator()
        scores  = rg.score_index(run)

        col_left, col_right = st.columns([3, 2])

        with col_left:
            st.markdown("<div class='section-header'>Domain Impact Scores</div>", unsafe_allow_html=True)
            if scores:
                df = pd.DataFrame(scores)
                color_map = {
                    "CRITICAL": "#ef4444",
                    "HIGH":     "#f59e0b",
                    "MEDIUM":   "#3b82f6",
                    "LOW":      "#10b981",
                }
                df["color"] = df["urgency"].map(color_map).fillna("#64748b")

                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=df["record_id"],
                    y=df["impact_score"],
                    marker_color=df["color"],
                    text=df["impact_score"].astype(str) + "/10",
                    textposition="outside",
                    hovertemplate=(
                        "<b>%{x}</b><br>"
                        "Domain: %{customdata[0]}<br>"
                        "Score: %{y}/10<br>"
                        "Urgency: %{customdata[1]}<br>"
                        "<extra></extra>"
                    ),
                    customdata=df[["domain", "urgency"]].values,
                ))
                fig.add_hline(
                    y=config.HIGH_IMPACT_THRESHOLD,
                    line_dash="dot",
                    line_color="#6366f1",
                    annotation_text=f"Escalation Gate ({config.HIGH_IMPACT_THRESHOLD})",
                    annotation_font_color="#6366f1",
                )
                fig.update_layout(**_chart_layout("Impact Score by Domain", y_range=[0, 11]))
                st.plotly_chart(fig, use_container_width=True)

        with col_right:
            st.markdown("<div class='section-header'>Urgency Distribution</div>", unsafe_allow_html=True)
            if scores:
                urgency_counts = pd.DataFrame(scores)["urgency"].value_counts().reset_index()
                urgency_counts.columns = ["urgency", "count"]
                fig2 = go.Figure(go.Pie(
                    labels=urgency_counts["urgency"],
                    values=urgency_counts["count"],
                    hole=0.55,
                    marker_colors=[
                        color_map.get(u, "#64748b") for u in urgency_counts["urgency"]
                    ],
                    textinfo="label+percent",
                    textfont_size=11,
                ))
                fig2.update_layout(**_chart_layout("Urgency Breakdown"))
                st.plotly_chart(fig2, use_container_width=True)

    elif history:
        st.markdown("<div class='section-header'>Historical Domain Scores</div>", unsafe_allow_html=True)
        df_h = pd.DataFrame(history)
        fig = px.scatter(
            df_h, x="created_at", y="impact_score",
            color="domain", size="impact_score",
            labels={"created_at": "Time", "impact_score": "Score"},
            color_discrete_sequence=px.colors.qualitative.Vivid,
        )
        fig.update_layout(**_chart_layout("Score History"))
        st.plotly_chart(fig, use_container_width=True)
    else:
        _empty_state(
            "No analysis data yet",
            "Go to **Run Analysis** to execute your first multi-agent pipeline run.",
        )

    # ── Risk Heatmap ──────────────────────────────────────────────────────────
    if run:
        st.markdown("<div class='section-header'>Risk Category Heatmap</div>", unsafe_allow_html=True)
        _render_risk_heatmap(run)

    # ── Escalation Queue ──────────────────────────────────────────────────────
    if run:
        escalated = [
            r for r in run.records
            if r.routing_decision == RoutingDecision.ESCALATED_TO_AGENTS
        ]
        if escalated:
            st.markdown(
                f"<div class='section-header'>Escalation Queue "
                f"<span style='color:#ef4444;'>({len(escalated)} records)</span></div>",
                unsafe_allow_html=True,
            )
            for rec in escalated:
                _render_escalation_card(rec)

    # ── Recent Runs Table ─────────────────────────────────────────────────────
    runs = db.get_runs(st.session_state.tenant_id, limit=10)
    if runs:
        st.markdown("<div class='section-header'>Recent Runs</div>", unsafe_allow_html=True)
        df_runs = pd.DataFrame(runs)[
            ["run_id", "status", "total_records", "escalated", "errors",
             "total_tokens", "started_at"]
        ].rename(columns={
            "run_id":        "Run ID",
            "status":        "Status",
            "total_records": "Records",
            "escalated":     "Escalated",
            "errors":        "Errors",
            "total_tokens":  "Tokens",
            "started_at":    "Started",
        })
        df_runs["Run ID"] = df_runs["Run ID"].str[:12].str.upper()
        st.dataframe(df_runs, use_container_width=True, hide_index=True)


def _render_risk_heatmap(run: OrchestratorRun) -> None:
    """Plotly heatmap of risk categories per domain."""
    cats   = ["operational", "financial", "reputational", "regulatory", "strategic"]
    level_score = {"CRITICAL": 4, "HIGH": 3, "MODERATE": 2, "LOW": 1, "N/A": 0}
    domains, matrix = [], []

    for rec in run.records:
        if not rec.risk:
            continue
        domains.append(f"{rec.record_id}\n({rec.domain})")
        row = [level_score.get(rec.risk.risk_categories.get(c, "N/A").upper(), 0) for c in cats]
        matrix.append(row)

    if not matrix:
        st.caption("No risk data — run analysis first.")
        return

    fig = go.Figure(go.Heatmap(
        z=matrix,
        x=[c.title() for c in cats],
        y=domains,
        colorscale=[[0, "#0f172a"], [0.25, "#1e3a5f"], [0.5, "#78350f"],
                    [0.75, "#7f1d1d"], [1.0, "#450a0a"]],
        text=[[["N/A","LOW","MOD","HIGH","CRIT"][v] for v in row] for row in matrix],
        texttemplate="%{text}",
        textfont_size=10,
        showscale=True,
        colorbar=dict(
            title="Level",
            tickvals=[0, 1, 2, 3, 4],
            ticktext=["N/A", "LOW", "MOD", "HIGH", "CRIT"],
            tickfont_color="#94a3b8",
        ),
    ))
    fig.update_layout(**_chart_layout("Risk Category Heatmap", height=250 + len(domains) * 40))
    st.plotly_chart(fig, use_container_width=True)


def _render_escalation_card(rec) -> None:
    triage = rec.triage
    exec_  = rec.executive
    urgency = triage.urgency if triage else "UNKNOWN"
    score   = triage.impact_score if triage else 0

    badge = f"<span class='badge badge-{urgency}'>{urgency}</span>"
    action = exec_.recommended_action[:120] + "…" if exec_ and exec_.recommended_action else "—"
    link   = (f"<a href='{exec_.action_link}' target='_blank' "
              f"style='color:#6366f1;'>{exec_.action_link[:60]}…</a>"
              if exec_ and exec_.action_link else "")
    deadline = exec_.response_deadline if exec_ else "—"

    st.markdown(
        f"<div class='esc-card'>"
        f"<div class='esc-card-title'>{rec.domain}  ·  {rec.record_id}  "
        f"{badge}  Score: {score}/10</div>"
        f"<div class='esc-card-body'>{action}</div>"
        f"<div class='esc-card-action'>⏱ Deadline: {deadline}  |  {link}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: RUN ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
def render_run_analysis() -> None:
    st.markdown(
        "<h1 style='color:#f1f5f9;font-weight:800;'>⚡ Run Analysis</h1>"
        "<p style='color:#64748b;'>Configure domain records and execute the 8-agent pipeline</p>",
        unsafe_allow_html=True,
    )

    if not st.session_state.api_key_set:
        st.error("⚠️ GROQ_API_KEY not configured. Add it to your .env file or via Settings.")
        return

    from core.orchestrator import Orchestrator, DEFAULT_INPUT_MATRIX

    # ── Input Configuration ───────────────────────────────────────────────────
    st.markdown("<div class='section-header'>Input Matrix</div>", unsafe_allow_html=True)

    use_custom = st.toggle("Use custom domain records (JSON)", value=False)

    records = None
    if use_custom:
        sample = json.dumps([
            {"record_id": "CUSTOM-001", "domain": "Finance",
             "payload": "Describe your domain data here..."}
        ], indent=2)
        raw = st.text_area(
            "Paste JSON array of records",
            value=sample, height=200,
            help='Each object needs "record_id", "domain", "payload"',
        )
        if st.button("Validate JSON"):
            try:
                parsed = json.loads(raw)
                st.success(f"✅ Valid — {len(parsed)} records")
            except json.JSONDecodeError as exc:
                st.error(f"Invalid JSON: {exc}")
    else:
        # Show default matrix
        for rec in DEFAULT_INPUT_MATRIX:
            st.markdown(
                f"<div class='input-card'>"
                f"<div class='input-card-header'>📁 {rec.domain}  ·  {rec.record_id}</div>"
                f"<div class='input-card-body'>{rec.payload[:200]}…</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # ── Run Controls ──────────────────────────────────────────────────────────
    st.markdown("<hr class='styled'>", unsafe_allow_html=True)
    col_left, col_right = st.columns([2, 1])
    with col_left:
        threshold = st.slider(
            "Impact Gate Threshold",
            min_value=1, max_value=10,
            value=config.HIGH_IMPACT_THRESHOLD,
            help="Records scoring at or above this value are escalated to all 8 agents.",
        )
    with col_right:
        tenant = st.text_input("Tenant ID", value=st.session_state.tenant_id)
        st.session_state.tenant_id = tenant

    run_btn = st.button(
        "🚀 Execute Multi-Agent Pipeline",
        type="primary",
        use_container_width=True,
    )

    if run_btn:
        config.HIGH_IMPACT_THRESHOLD = threshold

        # Build records
        if use_custom:
            try:
                parsed = json.loads(raw)
                from core.models import DomainRecord
                records = [
                    DomainRecord(
                        record_id=r["record_id"],
                        domain=r["domain"],
                        payload=r["payload"],
                        tenant_id=tenant,
                    )
                    for r in parsed
                ]
            except Exception as exc:
                st.error(f"Record parsing failed: {exc}")
                return

        # Progress display
        progress_bar = st.progress(0, text="Initialising pipeline…")
        status_box   = st.empty()
        log_container = st.container()

        def progress_cb(stage: str, pct: float, msg: str) -> None:
            progress_bar.progress(min(pct, 1.0), text=msg)
            status_box.caption(f"Stage: {stage.upper()}  |  {msg}")

        with st.spinner("Running 8-agent pipeline…"):
            try:
                orc  = Orchestrator(tenant_id=tenant, db=db)
                result = orc.execute(
                    records=records,
                    progress_cb=progress_cb,
                )
                st.session_state.run_result = result
                progress_bar.progress(1.0, text="✅ Pipeline complete!")

                # Summary
                summary = result.summary
                st.success(
                    f"✅ Run complete — "
                    f"{summary.get('escalated_records',0)} escalations, "
                    f"{summary.get('errors_encountered',0)} errors, "
                    f"{summary.get('total_tokens_used',0):,} tokens used"
                )

                # Agent status table
                with log_container:
                    st.markdown("<div class='section-header'>Agent Execution Status</div>", unsafe_allow_html=True)
                    _render_agent_status_table(result)

            except Exception as exc:
                st.error(f"Pipeline failed: {exc}")
                progress_bar.progress(0)


def _render_agent_status_table(run: OrchestratorRun) -> None:
    agent_names = [
        "Strategic Context Triage",
        "Executive Content Engine",
        "Risk Assessment Agent",
        "Evidence Validation Agent",
        "Recommendation Quality Agent",
        "Explainability Agent",
        "Memory and Learning Agent",
        "Report Generation Agent",
    ]

    rows = []
    for rec in run.records:
        agent_results = [
            rec.triage, rec.executive, rec.risk, rec.evidence,
            rec.recommendation_quality, rec.explanation, rec.memory, rec.report,
        ]
        for agent_name, agent_res in zip(agent_names, agent_results):
            if agent_res is None:
                status = "SKIPPED"
                ms     = 0
            else:
                status = getattr(agent_res, "agent_status", "SKIPPED")
                ms     = getattr(agent_res, "execution_time_ms", 0)
            rows.append({
                "Record":        rec.record_id,
                "Domain":        rec.domain,
                "Agent":         agent_name,
                "Status":        status,
                "Time (ms)":     ms,
            })

    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(
            df.style.applymap(
                lambda v: "color: #10b981; font-weight:bold" if v == "SUCCESS"
                else ("color: #ef4444" if v == "FAILED" else "color: #475569"),
                subset=["Status"],
            ),
            use_container_width=True,
            hide_index=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: REPORTS
# ══════════════════════════════════════════════════════════════════════════════
def render_reports() -> None:
    from services.report_generator import ReportGenerator

    st.markdown(
        "<h1 style='color:#f1f5f9;font-weight:800;'>📄 Reports</h1>"
        "<p style='color:#64748b;'>Executive briefs, board summaries, and full exports</p>",
        unsafe_allow_html=True,
    )

    run = st.session_state.run_result

    if not run:
        _empty_state("No run data", "Execute a pipeline run first.")
        return

    rg = ReportGenerator()

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4 = st.tabs([
        "Executive Summary", "Board Brief", "Full JSON Export", "Download PDF"
    ])

    with tab1:
        st.markdown("<div class='section-header'>Executive Summary</div>", unsafe_allow_html=True)
        for rec in run.records:
            if rec.routing_decision != RoutingDecision.ESCALATED_TO_AGENTS:
                continue
            if rec.report:
                with st.expander(f"📁 {rec.domain}  ·  {rec.record_id}", expanded=True):
                    st.markdown(
                        f"<p style='color:#e2e8f0;line-height:1.8;'>"
                        f"{rec.report.executive_summary}</p>",
                        unsafe_allow_html=True,
                    )
                    if rec.report.key_findings:
                        st.markdown("**Key Findings:**")
                        for f_ in rec.report.key_findings:
                            st.markdown(f"- {f_}")
                    if rec.executive:
                        st.markdown(
                            f"**Recommended Action:** {rec.executive.recommended_action}"
                        )
                        st.markdown(
                            f"**Resource:** [{rec.executive.action_link}]"
                            f"({rec.executive.action_link})"
                        )
                        st.caption(
                            f"Escalation: {rec.executive.escalation_tier}  |  "
                            f"Deadline: {rec.executive.response_deadline}"
                        )

    with tab2:
        st.markdown("<div class='section-header'>Board Intelligence Brief</div>", unsafe_allow_html=True)
        board_text = rg.to_board_summary(run)
        st.text_area("Board Brief", value=board_text, height=400)
        st.download_button(
            "📥 Download Board Brief (.txt)",
            data=board_text,
            file_name=f"board_brief_{run.run_id[:8]}.txt",
            mime="text/plain",
        )

    with tab3:
        st.markdown("<div class='section-header'>Full JSON Export</div>", unsafe_allow_html=True)
        json_str = rg.to_json(run)
        st.download_button(
            "📥 Download Full JSON",
            data=json_str,
            file_name=f"run_{run.run_id[:8]}.json",
            mime="application/json",
            use_container_width=True,
        )
        with st.expander("Preview JSON (first 3000 chars)"):
            st.code(json_str[:3000] + "\n// … truncated", language="json")

    with tab4:
        st.markdown("<div class='section-header'>PDF Report Export</div>", unsafe_allow_html=True)
        try:
            from services.pdf_exporter import PDFExporter
            if st.button("🖨️ Generate PDF Report", type="primary", use_container_width=True):
                with st.spinner("Rendering PDF…"):
                    exporter  = PDFExporter()
                    pdf_bytes = exporter.export_run(run)
                st.success(f"PDF ready — {len(pdf_bytes):,} bytes")
                st.download_button(
                    "📥 Download PDF",
                    data=pdf_bytes,
                    file_name=f"intelligence_report_{run.run_id[:8]}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
        except RuntimeError as exc:
            st.warning(f"PDF export unavailable: {exc}")
            st.code("pip install reportlab", language="bash")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: AUDIT TRAIL
# ══════════════════════════════════════════════════════════════════════════════
def render_audit_trail() -> None:
    st.markdown(
        "<h1 style='color:#f1f5f9;font-weight:800;'>🔍 Audit Trail</h1>"
        "<p style='color:#64748b;'>Immutable event log for compliance and forensics</p>",
        unsafe_allow_html=True,
    )

    run = st.session_state.run_result
    run_id = run.run_id if run else ""

    # Controls
    col1, col2, col3 = st.columns(3)
    with col1:
        filter_run = st.text_input("Filter by Run ID", value=run_id[:12] if run_id else "")
    with col2:
        filter_severity = st.selectbox("Severity", ["ALL", "INFO", "WARN", "ERROR"])
    with col3:
        limit = st.selectbox("Show last", [50, 100, 200, 500], index=0)

    entries = db.get_audit_trail(run_id=filter_run, limit=limit)

    if filter_severity != "ALL":
        entries = [e for e in entries if e.get("severity","").upper() == filter_severity]

    if not entries:
        _empty_state("No audit entries found", "Run the pipeline to generate audit events.")
        return

    # Timeline view

    severity_color = {"INFO": "#10b981", "WARN": "#f59e0b", "ERROR": "#ef4444"}

    for entry in reversed(entries[-50:]):
        sev    = entry.get("severity", "INFO")
        color  = severity_color.get(sev, "#64748b")
        ts     = entry.get("timestamp", "")[:19].replace("T", " ")
        event  = entry.get("event_type", "—")
        agent  = entry.get("agent_name", "")
        record = entry.get("record_id", "")
        data   = entry.get("data", {})

        detail = ""
        if isinstance(data, dict):
            parts = [f"{k}: {v}" for k, v in list(data.items())[:3]]
            detail = "  ·  ".join(parts)

    # Full table
    with st.expander("Full Audit Table"):
        df = pd.DataFrame(entries)
        if "data" in df.columns:
            df["data"] = df["data"].apply(
                lambda x: json.dumps(x, default=str)[:100] if isinstance(x, dict) else str(x)[:100]
            )
        st.dataframe(df, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: SYSTEM HEALTH
# ══════════════════════════════════════════════════════════════════════════════
def render_system_health() -> None:
    from core.rate_limiter import groq_circuit_breaker
    from core.cache import get_cache

    st.markdown(
        "<h1 style='color:#f1f5f9;font-weight:800;'>💚 System Health</h1>"
        "<p style='color:#64748b;'>Live infrastructure and reliability status</p>",
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("<div class='section-header'>Circuit Breaker</div>", unsafe_allow_html=True)
        cb_stats = groq_circuit_breaker.get_stats()
        state    = cb_stats["state"]
        state_color = {"CLOSED": "#10b981", "OPEN": "#ef4444", "HALF_OPEN": "#f59e0b"}
        _cb_color = state_color.get(state, "#94a3b8")
        st.markdown(
            f"<div class='kpi-card'>"
            f"<div class='kpi-value' style='color:{_cb_color};'>{state}</div>"
            f"<div class='kpi-label'>Circuit State</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.json(cb_stats)

    with col2:
        st.markdown("<div class='section-header'>Cache Statistics</div>", unsafe_allow_html=True)
        cache_stats = get_cache().stats()
        hit_rate    = cache_stats.get("hit_rate", 0)
        st.markdown(
            f"<div class='kpi-card'>"
            f"<div class='kpi-value' style='color:#6366f1;'>{hit_rate:.0%}</div>"
            f"<div class='kpi-label'>Cache Hit Rate</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.json(cache_stats)

    # Config overview
    st.markdown("<div class='section-header'>Runtime Configuration</div>", unsafe_allow_html=True)
    cfg_display = {
        "Model":               config.MODEL_ID,
        "Endpoint":            config.GROQ_ENDPOINT,
        "Impact Gate":         config.HIGH_IMPACT_THRESHOLD,
        "Rate Limit Sleep (s)": config.RATE_LIMIT_SLEEP,
        "Max Retries":         config.MAX_RETRIES,
        "Request Timeout (s)": config.REQUEST_TIMEOUT,
        "Cache TTL (s)":       config.CACHE_TTL,
        "CB Failure Threshold": config.CB_FAILURE_THRESHOLD,
        "CB Recovery (s)":     config.CB_RECOVERY_TIMEOUT,
        "Database":            str(config.STORAGE_DIR / "enterprise_maas.db"),
        "App Version":         config.APP_VERSION,
    }
    df_cfg = pd.DataFrame(list(cfg_display.items()), columns=["Setting", "Value"])
    st.dataframe(df_cfg, use_container_width=True, hide_index=True)

    # API connectivity test
    st.markdown("<div class='section-header'>API Connectivity Test</div>", unsafe_allow_html=True)
    if st.button("🔌 Test Groq API Connection", use_container_width=True):
        if not st.session_state.api_key_set:
            st.error("No API key configured.")
        else:
            with st.spinner("Testing…"):
                from services.groq_client import get_client
                health = get_client().health_check()
            if health["status"] == "healthy":
                st.success(f"✅ Connected — Response: {health['response']}")
            else:
                st.error(f"❌ Unhealthy — {health['response'][:200]}")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
def render_settings() -> None:
    st.markdown(
        "<h1 style='color:#f1f5f9;font-weight:800;'>⚙️ Settings</h1>"
        "<p style='color:#64748b;'>API keys, thresholds, and platform configuration</p>",
        unsafe_allow_html=True,
    )

    with st.form("settings_form"):
        st.markdown("<div class='section-header'>API Configuration</div>", unsafe_allow_html=True)

        api_key = st.text_input(
            "Groq API Key",
            value=config.GROQ_API_KEY if config.GROQ_API_KEY else "",
            type="password",
            help="Get your key at https://console.groq.com",
        )
        model = st.selectbox(
            "Model",
            ["llama-3.1-8b-instant", "llama-3.1-70b-versatile", "mixtral-8x7b-32768"],
            index=0,
        )

        st.markdown("<div class='section-header'>Pipeline Thresholds</div>", unsafe_allow_html=True)
        threshold = st.slider("Impact Gate Threshold", 1, 10, config.HIGH_IMPACT_THRESHOLD)
        temp      = st.slider("Temperature", 0.0, 1.0, config.TEMPERATURE, step=0.05)
        max_tok   = st.number_input("Max Tokens", 256, 4096, config.MAX_TOKENS, step=128)

        st.markdown("<div class='section-header'>Reliability</div>", unsafe_allow_html=True)
        rate_sleep = st.number_input("Rate Limit Sleep (s)", 1.0, 30.0, config.RATE_LIMIT_SLEEP)
        max_retry  = st.number_input("Max Retries", 0, 10, config.MAX_RETRIES)

        submitted = st.form_submit_button("💾 Save Settings", use_container_width=True)

        if submitted:
            if api_key:
                config.GROQ_API_KEY = api_key
                st.session_state.api_key_set = bool(api_key)
            config.MODEL_ID                = model
            config.HIGH_IMPACT_THRESHOLD   = threshold
            config.TEMPERATURE             = temp
            config.MAX_TOKENS              = int(max_tok)
            config.RATE_LIMIT_SLEEP        = rate_sleep
            config.MAX_RETRIES             = int(max_retry)

            # Invalidate the groq client singleton so it picks up new key
            import services.groq_client as _gc
            _gc._client = None

            st.success("✅ Settings saved for this session. "
                       "To persist across restarts, update your .env file.")

    st.markdown("<div class='section-header'>Clear Session Data</div>", unsafe_allow_html=True)
    if st.button("🗑️ Clear Run Result from Session", use_container_width=True):
        st.session_state.run_result = None
        st.success("Session cleared.")
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# CHART LAYOUT HELPER
# ══════════════════════════════════════════════════════════════════════════════
def _chart_layout(title: str, height: int = 320, y_range=None) -> dict:
    layout = dict(
        title=dict(text=title, font=dict(color="#e2e8f0", size=13)),
        paper_bgcolor="#0f172a",
        plot_bgcolor="#0f172a",
        font=dict(color="#94a3b8", size=11),
        margin=dict(l=20, r=20, t=40, b=20),
        height=height,
        legend=dict(bgcolor="#0f172a", bordercolor="#1e293b"),
        xaxis=dict(gridcolor="#1e293b", linecolor="#334155"),
        yaxis=dict(gridcolor="#1e293b", linecolor="#334155"),
    )
    if y_range:
        layout["yaxis"]["range"] = y_range
    return layout


def _empty_state(title: str, msg: str) -> None:
    st.markdown(
        f"<div style='text-align:center;padding:60px 20px;'>"
        f"<div style='font-size:3rem;'>📭</div>"
        f"<div style='font-size:1.1rem;font-weight:700;color:#e2e8f0;margin:12px 0 6px;'>{title}</div>"
        f"<div style='color:#64748b;'>{msg}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ROUTER
# ══════════════════════════════════════════════════════════════════════════════
def main() -> None:
    render_sidebar()

    page = st.session_state.active_page
    page_map = {
        "Dashboard":     render_dashboard,
        "Run Analysis":  render_run_analysis,
        "Reports":       render_reports,
        "Audit Trail":   render_audit_trail,
        "System Health": render_system_health,
        "Settings":      render_settings,
    }
    renderer = page_map.get(page, render_dashboard)
    renderer()


if __name__ == "__main__":
    main()
