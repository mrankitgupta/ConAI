"""
DatabaseProvider: SQLite by default (V1/V2), swappable for Postgres/Supabase
later behind the same repository interface. Session state in the UI is a
cache of what's in this DB, never the source of truth — engagements survive
a Streamlit rerun/restart.
"""
from __future__ import annotations
import os
import sqlite3
import json
import datetime
from contextlib import contextmanager

DB_PATH = os.environ.get(
    "CONAI_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "conai.db"),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS engagements (
    engagement_id TEXT PRIMARY KEY,
    company_name TEXT,
    industry TEXT,
    geography TEXT,
    business_problem TEXT,
    status TEXT DEFAULT 'IN_PROGRESS',
    state_json TEXT,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS leads (
    lead_id TEXT PRIMARY KEY,
    company TEXT,
    industry TEXT,
    region TEXT,
    fit_score INTEGER,
    classification TEXT,
    evidence TEXT,
    created_at TEXT,
    engagement_id TEXT
);
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement_id TEXT,
    actor TEXT,
    action TEXT,
    detail TEXT,
    timestamp TEXT
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement_id TEXT,
    stage TEXT,
    decision TEXT,
    reviewer TEXT,
    timestamp TEXT
);
CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement_id TEXT,
    recipient TEXT,
    subject TEXT,
    status TEXT,
    timestamp TEXT
);
CREATE TABLE IF NOT EXISTS tool_telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement_id TEXT,
    agent_name TEXT,
    tool_name TEXT,
    success INTEGER,
    duration_ms REAL,
    input_summary TEXT,
    output_summary TEXT,
    source_urls TEXT,
    error TEXT,
    timestamp TEXT
);
"""


@contextmanager
def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def save_engagement(state) -> None:
    """state: orchestration.state.EngagementState (pydantic). Upserts the full
    serialized state as JSON plus a few indexed columns for listing."""
    init_db()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO engagements (engagement_id, company_name, industry, geography, business_problem,
                                         status, state_json, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(engagement_id) DO UPDATE SET
                 company_name=excluded.company_name, industry=excluded.industry, geography=excluded.geography,
                 business_problem=excluded.business_problem, status=excluded.status,
                 state_json=excluded.state_json, updated_at=excluded.updated_at""",
            (
                state.engagement_id, state.company_name, state.industry_hint, state.geography_hint,
                state.business_problem, _status_for(state), state.model_dump_json(),
                state.created_at, now,
            ),
        )


def _status_for(state) -> str:
    if state.governance.status == "BLOCK":
        return "BLOCKED"
    if state.proposal_markdown and state.governance.status == "PASS":
        return "READY_FOR_APPROVAL"
    return "IN_PROGRESS"


def list_engagements() -> list[dict]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute("SELECT engagement_id, company_name, industry, geography, status, created_at, updated_at FROM engagements ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]


def load_engagement(engagement_id: str):
    from orchestration.state import EngagementState

    init_db()
    with get_conn() as conn:
        row = conn.execute("SELECT state_json FROM engagements WHERE engagement_id=?", (engagement_id,)).fetchone()
        if not row:
            return None
        return EngagementState(**json.loads(row["state_json"]))


def log_audit(engagement_id: str, actor: str, action: str, detail: str = ""):
    init_db()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_logs (engagement_id, actor, action, detail, timestamp) VALUES (?,?,?,?,?)",
            (engagement_id, actor, action, detail, datetime.datetime.now().isoformat(timespec="seconds")),
        )


def list_audit(engagement_id: str) -> list[dict]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM audit_logs WHERE engagement_id=? ORDER BY id DESC", (engagement_id,)).fetchall()
        return [dict(r) for r in rows]


def record_approval(engagement_id: str, stage: str, decision: str, reviewer: str = "consultant"):
    init_db()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO approvals (engagement_id, stage, decision, reviewer, timestamp) VALUES (?,?,?,?,?)",
            (engagement_id, stage, decision, reviewer, datetime.datetime.now().isoformat(timespec="seconds")),
        )
    log_audit(engagement_id, reviewer, f"APPROVAL:{stage}", decision)


def save_lead(lead, engagement_id: str = ""):
    import uuid

    init_db()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO leads (lead_id, company, industry, region, fit_score, classification, evidence, created_at, engagement_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4())[:8], lead.company, lead.industry, "", lead.fit_score, lead.classification, lead.evidence,
             datetime.datetime.now().isoformat(timespec="seconds"), engagement_id),
        )


def list_leads() -> list[dict]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM leads ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def record_email(engagement_id: str, recipient: str, subject: str, status: str):
    init_db()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO emails (engagement_id, recipient, subject, status, timestamp) VALUES (?,?,?,?,?)",
            (engagement_id, recipient, subject, status, datetime.datetime.now().isoformat(timespec="seconds")),
        )
    log_audit(engagement_id, "consultant", "EMAIL", f"{status} -> {recipient}")


def log_tool_call(engagement_id: str, agent_name: str, tool_name: str, success: bool, duration_ms: float,
                   input_summary: str = "", output_summary: str = "", source_urls: str = "", error: str = ""):
    """No secrets/content bodies here — summaries only, per the no-sensitive-logging requirement."""
    init_db()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO tool_telemetry (engagement_id, agent_name, tool_name, success, duration_ms,
                                            input_summary, output_summary, source_urls, error, timestamp)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (engagement_id, agent_name, tool_name, int(success), duration_ms, input_summary[:200],
             output_summary[:200], source_urls[:500], error[:300], datetime.datetime.now().isoformat(timespec="seconds")),
        )


def list_tool_telemetry(engagement_id: str) -> list[dict]:
    init_db()
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM tool_telemetry WHERE engagement_id=? ORDER BY id", (engagement_id,)).fetchall()
        return [dict(r) for r in rows]
