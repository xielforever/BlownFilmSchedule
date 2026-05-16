from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class IssueSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Machine(BaseModel):
    machine_id: str
    mold_spec: str | None = None
    capacity_min_kg_h: float | None = None
    capacity_max_kg_h: float | None = None
    insert_size_mm: str | None = None
    width_limit_br1: float | None = None
    width_recommend_br1_5: float | None = None
    width_recommend_br2: float | None = None
    width_recommend_br2_5: float | None = None
    width_over_range_br3: float | None = None
    width_limit_br3_5: float | None = None
    width_hd_limit: float | None = None
    width_hd_br2: float | None = None
    width_hd_br3: float | None = None
    width_hd_br4: float | None = None
    width_hd_br5: float | None = None
    width_hd_br6: float | None = None
    remark: str | None = None
    rule_tags: list[str] = Field(default_factory=list)

    @property
    def capacity_avg_kg_h(self) -> float | None:
        if self.capacity_min_kg_h and self.capacity_max_kg_h:
            return (self.capacity_min_kg_h + self.capacity_max_kg_h) / 2
        return self.capacity_min_kg_h or self.capacity_max_kg_h

    @property
    def max_width_mm(self) -> float | None:
        values = [
            self.width_limit_br1,
            self.width_recommend_br1_5,
            self.width_recommend_br2,
            self.width_recommend_br2_5,
            self.width_over_range_br3,
            self.width_limit_br3_5,
            self.width_hd_limit,
            self.width_hd_br2,
            self.width_hd_br3,
            self.width_hd_br4,
            self.width_hd_br5,
            self.width_hd_br6,
        ]
        present = [v for v in values if v is not None]
        return max(present) if present else None


class ParsedSpec(BaseModel):
    width_mm: float | None = None
    thickness_mm: float | None = None
    insert_width_mm: float | None = None
    raw: str
    parse_status: str
    parse_message: str | None = None


class OrderJob(BaseModel):
    job_id: str
    order_date: datetime | None = None
    planner: str | None = None
    plan_finish_time: datetime | None = None
    formula: str | None = None
    batch_no: str | None = None
    material_code: str | None = None
    spec_raw: str
    order_qty: float | None = None
    unit_weight_g: float | None = None
    batch_kg: float | None = None
    work_hours: float | None = None
    urgency: str | None = None
    customer: str | None = None
    clean_level: str | None = None
    is_medical: bool | None = None
    color: str | None = None
    allow_split: bool | None = None
    parsed_spec: ParsedSpec | None = None


class ValidationIssue(BaseModel):
    job_id: str | None = None
    machine_id: str | None = None
    field: str | None = None
    severity: IssueSeverity
    message: str


class ScheduleRunConfig(BaseModel):
    horizon_start: datetime | None = None
    horizon_end: datetime | None = None


class ScheduleAssignment(BaseModel):
    job_id: str
    machine_id: str
    sequence_no: int = 0
    formula: str | None = None
    spec_raw: str
    start_time: datetime
    production_start_time: datetime
    end_time: datetime
    plan_finish_time: datetime | None = None
    duration_hours: float
    production_hours: float
    changeover_hours: float = 0
    changeover_detail: str | None = None
    fit_level: str | None = None
    is_late: bool
    late_hours: float = 0
    score: float | None = None
    audit_status: str
    reason: str
    priority_reason: str | None = None
    idle_before_hours: float = 0
    idle_before_reason: str | None = None
    previous_job_id: str | None = None
    previous_formula: str | None = None
    width_mm: float | None = None
    thickness_mm: float | None = None
    insert_width_mm: float | None = None


class ScheduleException(BaseModel):
    job_id: str
    severity: IssueSeverity
    reason: str
    detail: str | None = None


class ConstraintAuditRow(BaseModel):
    job_id: str
    machine_id: str | None = None
    check_name: str
    passed: bool
    fit_level: str | None = None
    message: str


class ScheduleSummary(BaseModel):
    total_jobs: int
    scheduled_jobs: int
    unplanned_jobs: int
    late_jobs: int
    machine_count: int
    total_production_hours: float = 0
    total_changeover_hours: float = 0
    total_idle_hours: float = 0
    marginal_jobs: int = 0
    average_load_pct: float = 0


class MachineLoad(BaseModel):
    machine_id: str
    job_count: int
    first_start: datetime | None = None
    last_end: datetime | None = None
    production_hours: float = 0
    changeover_hours: float = 0
    occupied_hours: float = 0
    idle_hours: float = 0
    load_pct: float = 0
    best_jobs: int = 0
    recommended_jobs: int = 0
    marginal_jobs: int = 0
    late_jobs: int = 0


class ScheduleInsight(BaseModel):
    code: str
    severity: IssueSeverity
    title: str
    message: str
    job_id: str | None = None
    related_job_id: str | None = None
    machine_id: str | None = None
    metric_hours: float | None = None


class ScheduleCandidateAudit(BaseModel):
    job_id: str
    machine_id: str
    selected: bool
    rank: int
    fit_level: str | None = None
    score: float
    score_delta: float
    start_time: datetime
    production_start_time: datetime
    end_time: datetime
    production_hours: float
    changeover_hours: float
    late_hours: float = 0
    previous_job_id: str | None = None
    reason: str
    decision_reason: str


class MachineInsight(BaseModel):
    machine_id: str
    kind: str
    severity: IssueSeverity
    title: str
    message: str
    load_pct: float | None = None
    job_count: int = 0
    production_hours: float = 0
    changeover_hours: float = 0
    changeover_ratio: float | None = None
    eligible_orders: int = 0
    selected_orders: int = 0
    example_orders: list[str] = Field(default_factory=list)


class ScheduleResult(BaseModel):
    summary: ScheduleSummary
    assignments: list[ScheduleAssignment]
    exceptions: list[ScheduleException]
    audit: list[ConstraintAuditRow]
    validation_issues: list[ValidationIssue] = Field(default_factory=list)
    machine_loads: list[MachineLoad] = Field(default_factory=list)
    schedule_insights: list[ScheduleInsight] = Field(default_factory=list)
    candidate_audit: list[ScheduleCandidateAudit] = Field(default_factory=list)
    machine_insights: list[MachineInsight] = Field(default_factory=list)
    export_id: str | None = None

    def as_jsonable(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class PreviewResult(BaseModel):
    summary: ScheduleSummary
    validation_issues: list[ValidationIssue]
    audit: list[ConstraintAuditRow]
    orders: list[OrderJob]
    machines: list[Machine]
