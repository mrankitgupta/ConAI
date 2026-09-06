"""
Strict, typed state for the whole engagement.

This exists to fix the #1 bug class in the previous prototype: agents reading
dict keys that might not exist ('account_name' KeyError) and nested state
getting lost between LangGraph nodes. Every agent reads/writes this model,
never a raw dict, and every field has a safe default.
"""
from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict
import uuid
import datetime

Confidence = Literal["HIGH", "MEDIUM", "LOW"]
DataOrigin = Literal[
    "REAL_PUBLIC_DATA", "USER_PROVIDED", "SYNTHETIC_DEMO", "ASSUMPTION", "AI_GENERATED", "CALCULATED"
]
GovernanceStatus = Literal["PASS", "REVIEW", "BLOCK", "NOT_RUN"]
AgentStatus = Literal["PENDING", "RUNNING", "DONE", "FAILED", "SKIPPED"]


class Evidence(BaseModel):
    claim: str
    source: str
    source_type: Literal["web", "upload", "demo", "assumption", "llm_inference"]
    url: Optional[str] = None
    date: Optional[str] = None
    confidence: Confidence = "MEDIUM"
    origin: DataOrigin = "AI_GENERATED"


class AgentRun(BaseModel):
    name: str
    status: AgentStatus = "PENDING"
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    reasoning_summary: str = ""
    tools_used: list[str] = Field(default_factory=list)
    sources_used: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    human_status: Literal["NONE", "APPROVED", "EDITED", "REJECTED"] = "NONE"


class CompanyProfile(BaseModel):
    name: str = ""
    industry_guess: str = ""
    geography: str = ""
    description: str = "Not found / requires validation"
    segments: list[str] = Field(default_factory=list)
    strategic_priorities: list[str] = Field(default_factory=list)
    recent_signals: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    research_quality: Confidence = "LOW"


class MarketLandscape(BaseModel):
    market_definition: str = ""
    growth_note: str = "Not found / requires validation"
    key_trends: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    ai_adoption_note: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    technology_trends: list[str] = Field(default_factory=list)
    buying_signals: list[str] = Field(default_factory=list)
    transformation_triggers: list[str] = Field(default_factory=list)
    strategic_implications: list[str] = Field(default_factory=list)


class RequirementRow(BaseModel):
    req_id: str
    requirement: str
    category: str
    priority: str
    source: str
    page_or_section: Optional[str] = None  # None/"Not Found" unless the source format actually carries page info (PDF only)
    proposed_capability: str = ""
    ai_agent: str = ""
    kpi: str = ""
    confidence: Confidence = "MEDIUM"
    gap: str = ""


class DocumentInsights(BaseModel):
    filenames: list[str] = Field(default_factory=list)
    requirement_matrix: list[RequirementRow] = Field(default_factory=list)
    key_extracts: list[str] = Field(default_factory=list)
    rag_chunks_indexed: int = 0


class HypothesisNode(BaseModel):
    label: str
    parent: Optional[str] = None
    evidence: str = ""
    impact: str = "Medium"
    confidence: Confidence = "MEDIUM"
    data_required: str = ""
    validation: str = ""


class Diagnosis(BaseModel):
    executive_diagnosis: str = ""
    hypothesis_tree: list[HypothesisNode] = Field(default_factory=list)


class Opportunity(BaseModel):
    opp_id: str
    name: str
    problem: str
    solution: str
    business_value: int = Field(ge=1, le=5, default=3)
    feasibility: int = Field(ge=1, le=5, default=3)
    data_readiness: int = Field(ge=1, le=5, default=3)
    strategic_fit: int = Field(ge=1, le=5, default=3)
    time_to_value_months: int = 6
    risk: str = "Medium"
    required_data: list[str] = Field(default_factory=list)
    kpis: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    family: str = "General"

    @property
    def priority_score(self) -> float:
        return round(
            0.35 * self.business_value
            + 0.30 * self.feasibility
            + 0.20 * self.data_readiness
            + 0.15 * self.strategic_fit,
            2,
        )


class ROIInputs(BaseModel):
    annual_revenue_cr: float = 0.0
    seller_count: int = 0
    avg_deal_size_lakh: float = 0.0
    sales_cycle_days: int = 90
    win_rate_pct: float = 20.0
    fully_loaded_seller_cost_lakh: float = 18.0
    conversion_uplift_pct: float = 8.0
    productivity_gain_pct: float = 15.0
    proposal_effort_reduction_pct: float = 30.0
    implementation_cost_cr: float = 1.5
    scenario: Literal["Conservative", "Base", "Upside"] = "Base"


class ROIOutputs(BaseModel):
    incremental_revenue_cr: float = 0.0
    productivity_value_cr: float = 0.0
    cost_savings_cr: float = 0.0
    total_annual_value_cr: float = 0.0
    three_year_value_cr: float = 0.0
    roi_pct: float = 0.0
    payback_months: float = 0.0
    # All three scenarios computed simultaneously (keyed "Conservative"/"Base"/"Upside"),
    # in addition to the single `scenario`-selected values above for backward compatibility.
    scenarios: dict[str, "ROIOutputs"] = Field(default_factory=dict)
    # 2-driver sensitivity grid: each row is {conversion_uplift_pct, productivity_gain_pct, total_annual_value_cr}
    sensitivity_matrix: list[dict] = Field(default_factory=list)
    # Per-field data-origin labels: USER INPUT | PUBLIC DATA | ASSUMPTION | CALCULATED | AI GENERATED
    assumption_labels: dict[str, str] = Field(default_factory=dict)


class RoadmapPhase(BaseModel):
    phase: str
    objectives: list[str] = Field(default_factory=list)
    use_cases: list[str] = Field(default_factory=list)
    people: str = ""
    process: str = ""
    technology: str = ""
    data: str = ""
    governance: str = ""
    kpis: list[str] = Field(default_factory=list)


class SupervisorDecision(BaseModel):
    """One bounded routing decision made by the Supervisor after a node runs."""
    node: str
    decision: str
    reason: str
    next_node: str
    iteration_count: int


class GovernanceCheck(BaseModel):
    status: GovernanceStatus = "NOT_RUN"
    checks: dict[str, str] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


class LeadCandidate(BaseModel):
    company: str
    industry: str
    why_now: str
    trigger: str
    ai_opportunity: str
    fit_score: int = Field(ge=1, le=5, default=3)
    confidence: Confidence = "LOW"
    classification: Literal["HOT", "WARM", "NURTURE"] = "NURTURE"
    evidence: str = ""
    # qualification sub-scores (1-5), set by Lead Qualification Agent
    strategic_fit: int = Field(ge=1, le=5, default=3)
    pain_intensity: int = Field(ge=1, le=5, default=3)
    ai_opportunity_fit: int = Field(ge=1, le=5, default=3)
    data_readiness: int = Field(ge=1, le=5, default=3)
    investment_signal: int = Field(ge=1, le=5, default=3)
    transformation_readiness: int = Field(ge=1, le=5, default=3)
    timing: int = Field(ge=1, le=5, default=3)
    override_reason: str = ""

    @property
    def overall_score(self) -> float:
        vals = [
            self.strategic_fit, self.pain_intensity, self.ai_opportunity_fit,
            self.data_readiness, self.investment_signal, self.transformation_readiness, self.timing,
        ]
        return round(sum(vals) / len(vals), 2)


class TOMBlock(BaseModel):
    dimension: str  # People / Process / Technology / Data / Governance
    current_state: str = ""
    target_state: str = ""
    operating_cadence: str = ""


class EmailRecord(BaseModel):
    recipient: str = ""
    subject: str = ""
    status: str = "NOT_SENT"  # NOT_SENT | DRY_RUN | SENT | FAILED
    detail: str = ""
    timestamp: str = ""


class ApprovalRecord(BaseModel):
    proposal_version: int = 0
    proposal_hash: str = ""
    governance_version: str = "NOT_RUN"
    approval_status: Literal["NONE", "APPROVED", "INVALIDATED", "REJECTED"] = "NONE"
    approved_at: str = ""
    approved_by: str = ""
    approved_proposal_hash: str = ""

    @property
    def is_current(self) -> bool:
        """Approval is valid ONLY when APPROVED and the proposal hasn't
        changed since — any upstream edit that alters proposal_markdown
        changes proposal_hash, which is checked here."""
        return self.approval_status == "APPROVED" and self.proposal_hash == self.approved_proposal_hash != ""


class EngagementState(BaseModel):
    """The single object passed through every LangGraph node."""

    engagement_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: str = Field(default_factory=lambda: datetime.datetime.now().isoformat())

    company_name: str = ""
    industry_hint: str = ""
    geography_hint: str = ""
    business_problem: str = ""
    uploaded_file_paths: list[str] = Field(default_factory=list)

    company_profile: CompanyProfile = Field(default_factory=CompanyProfile)
    market: MarketLandscape = Field(default_factory=MarketLandscape)
    documents: DocumentInsights = Field(default_factory=DocumentInsights)
    diagnosis: Diagnosis = Field(default_factory=Diagnosis)
    opportunities: list[Opportunity] = Field(default_factory=list)
    roi_inputs: ROIInputs = Field(default_factory=ROIInputs)
    roi_outputs: ROIOutputs = Field(default_factory=ROIOutputs)
    roadmap: list[RoadmapPhase] = Field(default_factory=list)
    target_operating_model: list[TOMBlock] = Field(default_factory=list)
    proposal_markdown: str = ""
    governance: GovernanceCheck = Field(default_factory=GovernanceCheck)
    leads: list[LeadCandidate] = Field(default_factory=list)
    email_record: EmailRecord = Field(default_factory=EmailRecord)
    approval: ApprovalRecord = Field(default_factory=ApprovalRecord)

    agent_runs: dict[str, AgentRun] = Field(default_factory=dict)
    web_research_available: bool = True
    llm_available: bool = False

    supervisor_log: list[SupervisorDecision] = Field(default_factory=list)
    node_iterations: dict[str, int] = Field(default_factory=dict)
    pending_route: str = ""

    model_config = ConfigDict(arbitrary_types_allowed=True)
