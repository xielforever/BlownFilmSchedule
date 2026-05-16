export type Severity = 'error' | 'warning' | 'info';

export interface Summary {
  total_jobs: number;
  scheduled_jobs: number;
  unplanned_jobs: number;
  late_jobs: number;
  machine_count: number;
  total_production_hours?: number;
  total_changeover_hours?: number;
  total_idle_hours?: number;
  marginal_jobs?: number;
  average_load_pct?: number;
}

export interface ValidationIssue {
  job_id?: string | null;
  machine_id?: string | null;
  field?: string | null;
  severity: Severity;
  message: string;
}

export interface MachineCapability {
  machine_id: string;
  mold_spec?: string | null;
  capacity_min_kg_h?: number | null;
  capacity_max_kg_h?: number | null;
  insert_size_mm?: string | null;
  max_width_mm?: number | null;
  remark?: string | null;
  rule_tags: string[];
}

export interface MachinesResponse {
  count: number;
  machines: MachineCapability[];
}

export interface OrderJob {
  job_id: string;
  order_date?: string | null;
  plan_finish_time?: string | null;
  formula?: string | null;
  batch_no?: string | null;
  material_code?: string | null;
  spec_raw: string;
  batch_kg?: number | null;
  work_hours?: number | null;
  urgency?: string | null;
}

export interface ConstraintAuditRow {
  job_id: string;
  machine_id?: string | null;
  check_name: string;
  passed: boolean;
  fit_level?: 'best' | 'recommended' | 'marginal' | 'blocked' | null;
  message: string;
}

export interface ScheduleAssignment {
  job_id: string;
  machine_id: string;
  sequence_no: number;
  formula?: string | null;
  spec_raw: string;
  start_time: string;
  production_start_time: string;
  end_time: string;
  plan_finish_time?: string | null;
  duration_hours: number;
  production_hours: number;
  changeover_hours: number;
  changeover_detail?: string | null;
  fit_level?: 'best' | 'recommended' | 'marginal' | 'blocked' | null;
  is_late: boolean;
  late_hours: number;
  score?: number | null;
  audit_status: string;
  reason: string;
  priority_reason?: string | null;
  idle_before_hours: number;
  idle_before_reason?: string | null;
  previous_job_id?: string | null;
  previous_formula?: string | null;
  width_mm?: number | null;
  thickness_mm?: number | null;
  insert_width_mm?: number | null;
}

export interface ScheduleException {
  job_id: string;
  severity: Severity;
  reason: string;
  detail?: string | null;
}

export interface PreviewResponse {
  upload_id: string;
  summary: Summary;
  validation_issues: ValidationIssue[];
  audit: ConstraintAuditRow[];
  orders: OrderJob[];
  machines: MachineCapability[];
}

export interface MachineLoad {
  machine_id: string;
  job_count: number;
  first_start?: string | null;
  last_end?: string | null;
  production_hours: number;
  changeover_hours: number;
  occupied_hours: number;
  idle_hours: number;
  load_pct: number;
  best_jobs: number;
  recommended_jobs: number;
  marginal_jobs: number;
  late_jobs: number;
}

export interface ScheduleInsight {
  code: string;
  severity: Severity;
  title: string;
  message: string;
  job_id?: string | null;
  related_job_id?: string | null;
  machine_id?: string | null;
  metric_hours?: number | null;
}

export interface ScheduleCandidateAudit {
  job_id: string;
  machine_id: string;
  selected: boolean;
  rank: number;
  fit_level?: 'best' | 'recommended' | 'marginal' | 'blocked' | null;
  score: number;
  score_delta: number;
  start_time: string;
  production_start_time: string;
  end_time: string;
  production_hours: number;
  changeover_hours: number;
  late_hours: number;
  previous_job_id?: string | null;
  reason: string;
  decision_reason: string;
}

export interface ScheduleResult {
  summary: Summary;
  assignments: ScheduleAssignment[];
  exceptions: ScheduleException[];
  audit: ConstraintAuditRow[];
  validation_issues: ValidationIssue[];
  machine_loads: MachineLoad[];
  schedule_insights: ScheduleInsight[];
  candidate_audit: ScheduleCandidateAudit[];
  export_id?: string | null;
}
